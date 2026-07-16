from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from .auth import LoginRequest, create_token, require_owner, verify_access_code
from .collector import collect_all, snapshot_payload
from .database import MarketSnapshot, ScenarioEvent, SessionLocal, init_db
from .engine import get_diagnostics, get_roadmap
from .occ_importer import import_latest_occ, import_occ_bytes, latest_structure
from .providers import SUPPORTED_SYMBOLS


app = FastAPI(title="Options Workstation API", version="5.0.0")

origin = os.getenv("FRONTEND_ORIGIN", "*")
origins = ["*"] if origin == "*" else [
    origin.rstrip("/"),
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=origin != "*",
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    init_db()


@app.get("/")
def root():
    return {
        "name": "Options Workstation API",
        "status": "online",
        "version": "5.0.0",
        "features": [
            "persistent snapshots",
            "scenario event history",
            "server-side email alerts",
            "five-minute collector",
            "official OCC importer",
            "day-over-day OI changes",
            "wall migration",
            "morning briefing",
        ],
        "docs": "/docs",
    }


@app.get("/health")
def health():
    return {"status": "ok", "version": "5.0.0"}


@app.post("/api/login")
def login(payload: LoginRequest):
    if not verify_access_code(payload.access_code):
        raise HTTPException(status_code=401, detail="Invalid access code.")
    return {"token": create_token(), "token_type": "bearer"}


@app.get("/api/symbols")
def symbols(_: dict = Depends(require_owner)):
    return {"symbols": sorted(SUPPORTED_SYMBOLS)}


@app.get("/api/roadmap/{symbol}")
def roadmap(symbol: str, _: dict = Depends(require_owner)):
    return snapshot_payload(symbol.upper())


@app.get("/api/diagnostics/{symbol}")
def diagnostics(symbol: str, _: dict = Depends(require_owner)):
    return get_diagnostics(symbol)


@app.get("/api/history/{symbol}")
def history(symbol: str, hours: int = 24, limit: int = 100, _: dict = Depends(require_owner)):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=min(max(hours, 1), 168))
    with SessionLocal() as db:
        rows = db.execute(
            select(MarketSnapshot)
            .where(
                MarketSnapshot.symbol == symbol.upper(),
                MarketSnapshot.captured_at >= cutoff,
            )
            .order_by(MarketSnapshot.captured_at.desc())
            .limit(min(max(limit, 1), 500))
        ).scalars().all()

    return {
        "symbol": symbol.upper(),
        "snapshots": [{
            "captured_at": row.captured_at.isoformat(),
            "spot": row.spot,
            "bias": row.bias,
            "conviction": row.conviction,
            "bullish_score": row.bullish_score,
            "bearish_score": row.bearish_score,
            "bullish_status": row.bullish_status,
            "bearish_status": row.bearish_status,
            "vwap": row.vwap,
            "ema9": row.ema9,
            "ema21": row.ema21,
            "call_wall": row.call_wall,
            "put_wall": row.put_wall,
            "plus_gex": row.plus_gex,
            "minus_gex": row.minus_gex,
        } for row in rows],
    }


@app.get("/api/events/{symbol}")
def events(symbol: str, limit: int = 50, _: dict = Depends(require_owner)):
    with SessionLocal() as db:
        rows = db.execute(
            select(ScenarioEvent)
            .where(ScenarioEvent.symbol == symbol.upper())
            .order_by(ScenarioEvent.created_at.desc())
            .limit(min(max(limit, 1), 200))
        ).scalars().all()

    return {
        "symbol": symbol.upper(),
        "events": [{
            "id": row.id,
            "created_at": row.created_at.isoformat(),
            "event_type": row.event_type,
            "direction": row.direction,
            "title": row.title,
            "message": row.message,
            "price": row.price,
            "conviction": row.conviction,
            "delivered": row.delivered,
        } for row in rows],
    }


@app.get("/api/morning-brief/{symbol}")
def morning_brief(symbol: str, _: dict = Depends(require_owner)):
    symbol = symbol.upper()
    current = snapshot_payload(symbol)
    official = latest_structure(symbol)
    metrics = current.get("metrics", {})

    changes = []
    if official:
        if official.get("call_wall_change") is not None:
            changes.append(
                f"Official call wall moved {official['call_wall_change']:+.2f} from the previous file."
            )
        if official.get("put_wall_change") is not None:
            changes.append(
                f"Official put wall moved {official['put_wall_change']:+.2f} from the previous file."
            )
        if official.get("call_oi_change") is not None:
            changes.append(f"Official call OI changed by {official['call_oi_change']:+,}.")
        if official.get("put_oi_change") is not None:
            changes.append(f"Official put OI changed by {official['put_oi_change']:+,}.")

    return {
        "symbol": symbol,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "headline": current["bias"],
        "briefing": current["briefing"],
        "official_prior_day": official,
        "changes": changes,
        "levels": current["levels"],
        "expected_move": current["expected_move"],
        "bullish_score": metrics.get("bullish_score"),
        "bearish_score": metrics.get("bearish_score"),
    }


@app.post("/api/collect")
def collect(
    x_cron_secret: str | None = Header(default=None),
):
    expected = os.getenv("CRON_SECRET")
    if expected and x_cron_secret != expected:
        raise HTTPException(status_code=401, detail="Invalid cron secret.")
    return collect_all()


@app.post("/api/occ/import-latest")
def occ_import_latest(
    x_cron_secret: str | None = Header(default=None),
):
    expected = os.getenv("CRON_SECRET")
    if expected and x_cron_secret != expected:
        raise HTTPException(status_code=401, detail="Invalid cron secret.")
    return import_latest_occ()


@app.post("/api/occ/upload")
async def occ_upload(
    trade_date: str,
    file: UploadFile = File(...),
    _: dict = Depends(require_owner),
):
    content = await file.read()
    return import_occ_bytes(
        content=content,
        trade_date=trade_date,
        source=f"manual-upload:{file.filename}",
    )
