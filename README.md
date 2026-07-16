# Clean backend replacement

Delete the existing `backend/` folder completely before uploading this one.
That removes old files such as `live_engine.py`.

Render:
- Root Directory: backend
- Build: python -m pip install --upgrade pip && python -m pip install -r requirements.txt
- Start: uvicorn app.main:app --host 0.0.0.0 --port $PORT
- Health: /health
- PYTHON_VERSION: 3.12.11
- PERSONAL_ACCESS_CODE: your code
- TOKEN_SECRET: long random string
- FRONTEND_ORIGIN: your Vercel URL

Then use Clear build cache & deploy.
