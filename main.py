import os, re, uuid, subprocess, shutil, tempfile
from pathlib import Path
from typing import Optional
import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from faster_whisper import WhisperModel

load_dotenv()
ROOT = Path(__file__).resolve().parent
WORK = ROOT / "work"
WORK.mkdir(exist_ok=True)
app = FastAPI(title="Myanmar Auto Edit Studio API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
_model = None

def whisper():
    global _model
    if _model is None:
        _model = WhisperModel(os.getenv("WHISPER_MODEL", "small"), device="cpu", compute_type="int8")
    return _model

def ffmpeg(*args):
    if not shutil.which("ffmpeg"):
        raise HTTPException(500, "FFmpeg မတွေ့ပါ။ FFmpeg ကို install လုပ်ပါ။")
    p = subprocess.run(["ffmpeg", "-y", *args], capture_output=True, text=True)
    if p.returncode:
        raise HTTPException(500, "FFmpeg processing failed: " + p.stderr[-1200:])
    return p

def split_burmese(text, max_chars=42):
    # Greedy sentence/phrase wrapping, preserving readable short caption lines.
    words = re.split(r"(?<=[။!?])\s+|(?<=၊)\s+|\s+", text.strip())
    out, line = [], ""
    for word in filter(None, words):
        candidate = (line + " " + word).strip()
        if len(candidate) > max_chars and line:
            out.append(line); line = word
        else:
            line = candidate
    if line: out.append(line)
    return out or [text]

async def translate(text):
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        return text
    url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/") + "/chat/completions"
    body = {"model": os.getenv("TRANSLATION_MODEL", "gpt-4o-mini"),
            "messages": [{"role":"system","content":"Translate the input into natural, concise Burmese (Myanmar Unicode). Preserve meaning and names. Return only the translation."},
                         {"role":"user","content":text}],
            "temperature":0.2}
    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.post(url, headers={"Authorization":f"Bearer {key}"}, json=body)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()

@app.get("/health")
def health():
    return {"ok": True, "message": "Myanmar Auto Edit Studio API is running"}

@app.post("/transcribe")
async def transcribe(file: UploadFile = File(...), translate_to_burmese: bool = Form(True)):
    suffix = Path(file.filename or "video.mp4").suffix or ".mp4"
    path = WORK / f"{uuid.uuid4().hex}{suffix}"
    path.write_bytes(await file.read())
    try:
        segments, info = whisper().transcribe(str(path), vad_filter=True, beam_size=5)
        result = []
        for seg in segments:
            raw = seg.text.strip()
            translated = await translate(raw) if translate_to_burmese else raw
            # Time-aligned captions: split text across duration proportionally by character count.
            lines = split_burmese(translated)
            weights = [max(1, len(s)) for s in lines]
            total = sum(weights); cursor = float(seg.start)
            duration = max(0.15, float(seg.end-seg.start))
            for i, line in enumerate(lines):
                end = float(seg.end) if i == len(lines)-1 else cursor + duration*weights[i]/total
                result.append({"start":round(cursor,3),"end":round(end,3),"text":line,"source":raw})
                cursor = end
        return {"language":info.language, "duration":info.duration, "captions":result}
    finally:
        path.unlink(missing_ok=True)

@app.post("/render")
async def render(file: UploadFile = File(...), captions_json: str = Form(...),
                 burn_subtitles: bool = Form(True), keep_original_audio: bool = Form(False)):
    import json
    captions = json.loads(captions_json)
    job = uuid.uuid4().hex
    source = WORK / f"{job}_source{Path(file.filename or 'video.mp4').suffix or '.mp4'}"
    output = WORK / f"{job}_final.mp4"
    source.write_bytes(await file.read())
    if not captions:
        raise HTTPException(400, "Subtitle မရှိပါ။")
    # Create ASS subtitle with a single line per event and Myanmar-friendly styling.
    ass = WORK / f"{job}.ass"
    def stamp(t):
        cs = int(round(float(t)*100)); h=cs//360000; m=(cs//6000)%60; s=(cs//100)%60; c=cs%100
        return f"{h}:{m:02d}:{s:02d}.{c:02d}"
    events = []
    for c in captions:
        txt = str(c.get("text","")).replace("\\","\\\\").replace("{","\\{").replace("}","\\}").replace("\n"," ")
        events.append(f"Dialogue: 0,{stamp(c['start'])},{stamp(c['end'])},Default,,0,0,0,,{txt}")
    ass.write_text("[Script Info]\nScriptType: v4.00+\nPlayResX: 1920\nPlayResY: 1080\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\nStyle: Default,Noto Sans Myanmar,52,&H00FFFFFF,&H000000FF,&H00101010,&H80000000,1,0,1,3,1,2,60,60,55,1\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n" + "\n".join(events), encoding="utf-8")
    try:
        args = ["-i", str(source)]
        if burn_subtitles:
            args += ["-vf", f"ass={str(ass).replace(':','\\\\:')}"]
        if keep_original_audio:
            args += ["-c:a","aac","-b:a","192k"]
        else:
            args += ["-c:a","aac","-b:a","192k"]
        args += ["-c:v","libx264","-preset","veryfast","-crf","22","-movflags","+faststart",str(output)]
        ffmpeg(*args)
        return FileResponse(output, media_type="video/mp4", filename="myanmar_auto_edit.mp4")
    finally:
        source.unlink(missing_ok=True); ass.unlink(missing_ok=True)

@app.post("/tts")
async def tts(text: str = Form(...), voice: str = Form("alloy")):
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        raise HTTPException(400, "TTS အတွက် .env ထဲမှာ OPENAI_API_KEY ထည့်ပါ။ Burmese voice ရရှိမှုသည် provider အပေါ် မူတည်သည်။")
    url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/") + "/audio/speech"
    body = {"model":os.getenv("TTS_MODEL","gpt-4o-mini-tts"),"voice":voice,"input":text,"response_format":"mp3"}
    async with httpx.AsyncClient(timeout=180) as c:
        r=await c.post(url,headers={"Authorization":f"Bearer {key}"},json=body)
        if r.status_code >= 400:
            raise HTTPException(r.status_code, r.text[:1000])
    out=WORK/f"{uuid.uuid4().hex}.mp3"; out.write_bytes(r.content)
    return FileResponse(out, media_type="audio/mpeg", filename="myanmar_voice.mp3")
