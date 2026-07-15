# Options Workstation Personal v1

Single-user private build with live roadmap, functional tabs, flow metrics, and browser alerts.

## Render backend
- Root Directory: `backend`
- Build: `pip install -r requirements.txt`
- Start: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`

Environment variables:
- `PERSONAL_ACCESS_CODE` = your private login code
- `TOKEN_SECRET` = a long random string
- `FRONTEND_ORIGIN` = your full Vercel URL

## Vercel frontend
- Root Directory: `frontend`
- Node.js: 20.x

Environment variable:
- `NEXT_PUBLIC_API_URL` = your Render URL with no trailing slash

After changing environment variables, redeploy both services.

## Current alerts
Browser alerts work while the website is open. Closed-app push notifications require the next background-worker and service-worker phase.
