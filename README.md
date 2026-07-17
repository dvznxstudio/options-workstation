# Options Workstation v6 — Institutional Decision Engine

This build uses a Fincept-inspired modular architecture without copying Fincept source code.

## Core upgrades

- Provider registry with automatic fallback
- Optional Databento futures connector
- Today, Week, Month, and Combined decision engines
- Expiration-aware option-chain filtering
- Distance-aware strike filtering
- Distant mathematical levels hidden from actionable roadmaps
- ES/MES, NQ/MNQ, and RTY/M2K futures leadership
- Evidence scorecard instead of an unexplained probability
- Multi-timeframe interpretation
- Existing history, OCC, database, event, and alert features remain included

## Why the $584-type level is fixed

Each timeframe uses a separate relevance window:

- Today: expirations up to 2 days and strikes about 3.5% from spot
- Week: expirations up to 10 days and strikes about 9% from spot
- Month: expirations up to 45 days and strikes about 18% from spot

Levels outside that window are not shown as actionable levels.

## Databento

Add this optional Render environment variable:

DATABENTO_API_KEY=db-your-key

Without a key, futures analysis automatically falls back to Yahoo chart data.

Databento mappings:

- ES / MES / NQ / MNQ / RTY / M2K
- CL and GC
- Dataset: GLBX.MDP3
- Continuous volume-ranked symbols such as ES.v.0

## API

GET /api/roadmap/SPY?timeframe=today
GET /api/roadmap/SPY?timeframe=week
GET /api/roadmap/SPY?timeframe=month
GET /api/roadmap/SPY?timeframe=combined
GET /api/futures-leadership/SPY?interval=5m

## Evidence scorecard

- Options positioning
- Price structure
- Trend alignment
- Futures leadership
- Data quality

The overall conviction score measures alignment of observable evidence. It is not claimed to be a guaranteed win probability.

## Deployment

Replace both frontend and backend folders.

Render:
- Root: backend
- Build: python -m pip install --upgrade pip && python -m pip install -r requirements.txt
- Start: uvicorn app.main:app --host 0.0.0.0 --port $PORT
- Health: /health

Vercel:
- Root: frontend
- NEXT_PUBLIC_API_URL=https://options-workstation.onrender.com

Expected health:
{"status":"ok","version":"6.0.0"}
