# Options Workstation Phase 4 + 5

This release combines:

## Phase 4
- Persistent PostgreSQL/SQLite market snapshots
- Five-minute scheduled collector
- Scenario event lifecycle detection
- Roadmap direction-change events
- Conviction-jump events
- Email delivery through SMTP
- Snapshot and event history API
- History tab in the frontend

## Phase 5
- Official OCC CSV importer
- Manual official-file upload
- Configurable scheduled OCC download URL
- Prior-day call and put walls
- Day-over-day call/put wall migration
- Day-over-day call/put OI changes
- Morning briefing endpoint
- Official structural values added to roadmap metrics

## Database

For production, create a Render PostgreSQL database and add its Internal Database URL as:

DATABASE_URL

Without it, the backend uses SQLite. SQLite storage on an ephemeral Render filesystem may be lost during redeploys.

## Required Render environment variables

PERSONAL_ACCESS_CODE
TOKEN_SECRET
FRONTEND_ORIGIN=https://options-workstation.vercel.app
DATABASE_URL=<Render Postgres internal URL>
SUPPORTED_SYMBOLS=SPY,QQQ,IWM
CRON_SECRET=<long random value>

## Optional email variables

SMTP_HOST
SMTP_PORT=587
SMTP_USERNAME
SMTP_PASSWORD
ALERT_EMAIL_FROM
ALERT_EMAIL_TO

## OCC configuration

The official OCC importer supports two methods:

1. Upload an official OCC CSV using `POST /api/occ/upload` in `/docs`.
2. Set `OCC_OI_URL_TEMPLATE` to the official downloadable file URL.

The URL template can contain:

{date}       -> YYYY-MM-DD
{yyyymmdd}   -> YYYYMMDD
{mmddyyyy}   -> MMDDYYYY

If the current official OCC download address is not configured, the scheduled OCC job will fail clearly while the rest of the workstation remains operational.

## Deployment

Replace both `backend/` and `frontend/` with this release.

Render web service:
- Root: backend
- Build: `python -m pip install --upgrade pip && python -m pip install -r requirements.txt`
- Start: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- Health: `/health`

Vercel:
- Root: frontend
- `NEXT_PUBLIC_API_URL=https://options-workstation.onrender.com`

Expected backend health:
`{"status":"ok","version":"5.0.0"}`
