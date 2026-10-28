# Myanmar Auto Edit Studio — Full-stack starter

This is a runnable local starter project for automatic transcription, Burmese translation, Burmese TTS, subtitles, and MP4 rendering.

## Important
- This is a functional starter, not a hosted cloud service.
- Transcription uses faster-whisper locally.
- Translation and Burmese speech use optional API providers configured by environment variables. Burmese TTS quality depends on the chosen provider.
- Final video rendering uses FFmpeg.
- Review the generated Burmese translation and subtitle timing before publishing.

## Run
1. Install Python 3.11+, FFmpeg, and (optional) Node.js.
2. In `backend/`, create a virtual environment and install `requirements.txt`.
3. Copy `.env.example` to `.env` and set provider credentials.
4. Start API: `uvicorn main:app --host 127.0.0.1 --port 8000`
5. Serve the `app/` folder (e.g. `python -m http.server 5173`) and open `http://127.0.0.1:5173`.
6. In the web UI, set API URL to `http://127.0.0.1:8000`.

This project provides the pipeline and UI. It does not claim to provide a perfect Burmese voice on every machine/provider.
