# Phase 3 — Trade GPS

Replace the existing backend folder with this backend folder.

New features:
- 5-minute intraday candles
- Session VWAP
- EMA 9 and EMA 21
- Opening range high/low
- Two-candle acceptance logic
- Automatic FORMING / ACTIVE scenario states
- Bullish and bearish confirmation scores
- Diagnostic endpoint

Render settings stay unchanged.

After upload:
Manual Deploy -> Clear build cache & deploy

Health:
GET /health
Expected:
{"status":"ok","version":"3.0.0"}

Protected diagnostics:
GET /api/diagnostics/SPY
