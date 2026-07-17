from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from io import BytesIO
import os
import re
from typing import Iterable

import pandas as pd
import requests
from sqlalchemy import delete, select

from .database import DailyStructure, OccOpenInterest, SessionLocal, utc_now


ALIASES = {
    "symbol": ["symbol", "underlying", "underlying_symbol", "root", "product_symbol"],
    "expiration": ["expiration", "expiration_date", "expiry", "exp_date"],
    "option_type": ["option_type", "put_call", "call_put", "cp_flag", "type"],
    "strike": ["strike", "strike_price"],
    "open_interest": ["open_interest", "openinterest", "oi"],
    "contract": ["contract", "option_symbol", "series", "osi_symbol"],
}
OSI_PATTERN = re.compile(r"^(?P<root>[A-Z]+)(?P<date>\d{6})(?P<type>[CP])(?P<strike>\d{8})$")


def _find_column(frame: pd.DataFrame, logical: str) -> str | None:
    normalized = {str(column).strip().lower().replace(" ", "_"): column for column in frame.columns}
    for alias in ALIASES[logical]:
        if alias in normalized:
            return normalized[alias]
    return None


def _normalize_type(value) -> str:
    text = str(value).strip().upper()
    if text.startswith("C"):
        return "call"
    if text.startswith("P"):
        return "put"
    raise ValueError(f"Unknown option type: {value}")


def _parse_contract(value: str):
    compact = str(value).replace(" ", "").upper()
    match = OSI_PATTERN.match(compact)
    if not match:
        return None
    return {
        "symbol": match.group("root"),
        "expiration": datetime.strptime(match.group("date"), "%y%m%d").strftime("%Y-%m-%d"),
        "option_type": "call" if match.group("type") == "C" else "put",
        "strike": int(match.group("strike")) / 1000.0,
    }


def read_occ_csv(content: bytes) -> pd.DataFrame:
    frame = pd.read_csv(BytesIO(content), low_memory=False)
    frame.columns = [str(column).strip() for column in frame.columns]

    contract_col = _find_column(frame, "contract")
    symbol_col = _find_column(frame, "symbol")
    expiration_col = _find_column(frame, "expiration")
    type_col = _find_column(frame, "option_type")
    strike_col = _find_column(frame, "strike")
    oi_col = _find_column(frame, "open_interest")

    if oi_col is None:
        raise ValueError("Could not find an open-interest column in the OCC file.")

    rows = []
    for item in frame.to_dict("records"):
        parsed = _parse_contract(item.get(contract_col)) if contract_col else None
        try:
            symbol = parsed["symbol"] if parsed else str(item[symbol_col]).strip().upper()
            expiration = parsed["expiration"] if parsed else pd.to_datetime(item[expiration_col]).strftime("%Y-%m-%d")
            option_type = parsed["option_type"] if parsed else _normalize_type(item[type_col])
            strike = parsed["strike"] if parsed else float(item[strike_col])
            open_interest = int(float(item[oi_col] or 0))
        except Exception:
            continue

        if not symbol or strike <= 0 or open_interest < 0:
            continue

        rows.append({
            "symbol": symbol,
            "expiration": expiration,
            "option_type": option_type,
            "strike": strike,
            "open_interest": open_interest,
        })

    normalized = pd.DataFrame(rows)
    if normalized.empty:
        raise ValueError("No valid OCC option rows were found.")
    return normalized


def import_occ_bytes(content: bytes, trade_date: str, source: str) -> dict:
    frame = read_occ_csv(content)
    supported = set(os.getenv("SUPPORTED_SYMBOLS", "SPY,QQQ,IWM").upper().split(","))
    frame = frame[frame["symbol"].isin(supported)].copy()

    with SessionLocal() as db:
        db.execute(delete(OccOpenInterest).where(OccOpenInterest.trade_date == trade_date))
        imported_at = utc_now()
        objects = [
            OccOpenInterest(
                trade_date=trade_date,
                symbol=row.symbol,
                expiration=row.expiration,
                option_type=row.option_type,
                strike=float(row.strike),
                open_interest=int(row.open_interest),
                source=source,
                imported_at=imported_at,
            )
            for row in frame.itertuples(index=False)
        ]
        db.add_all(objects)
        db.commit()

    structures = []
    for symbol in sorted(frame["symbol"].unique()):
        structures.append(build_daily_structure(symbol, trade_date))

    return {
        "trade_date": trade_date,
        "rows": len(frame),
        "symbols": sorted(frame["symbol"].unique().tolist()),
        "structures": structures,
    }


def import_latest_occ() -> dict:
    template = os.getenv("OCC_OI_URL_TEMPLATE")
    if not template:
        raise RuntimeError(
            "OCC_OI_URL_TEMPLATE is not configured. Upload the official OCC CSV through "
            "/api/occ/upload or set a URL template containing {date}."
        )

    trade_date = (date.today() - timedelta(days=1))
    while trade_date.weekday() >= 5:
        trade_date -= timedelta(days=1)

    date_text = trade_date.strftime("%Y-%m-%d")
    url = template.format(
        date=date_text,
        yyyymmdd=trade_date.strftime("%Y%m%d"),
        mmddyyyy=trade_date.strftime("%m%d%Y"),
    )
    response = requests.get(url, timeout=45)
    response.raise_for_status()
    return import_occ_bytes(response.content, date_text, url)


def build_daily_structure(symbol: str, trade_date: str) -> dict:
    with SessionLocal() as db:
        rows = db.execute(
            select(OccOpenInterest).where(
                OccOpenInterest.symbol == symbol,
                OccOpenInterest.trade_date == trade_date,
            )
        ).scalars().all()

        if not rows:
            return {"symbol": symbol, "trade_date": trade_date, "status": "no_data"}

        frame = pd.DataFrame([{
            "strike": row.strike,
            "option_type": row.option_type,
            "open_interest": row.open_interest,
        } for row in rows])

        calls = frame[frame["option_type"] == "call"]
        puts = frame[frame["option_type"] == "put"]

        call_by_strike = calls.groupby("strike")["open_interest"].sum()
        put_by_strike = puts.groupby("strike")["open_interest"].sum()

        call_wall = float(call_by_strike.idxmax()) if not call_by_strike.empty else None
        put_wall = float(put_by_strike.idxmax()) if not put_by_strike.empty else None

        total_call = int(calls["open_interest"].sum())
        total_put = int(puts["open_interest"].sum())

        existing = db.execute(
            select(DailyStructure).where(
                DailyStructure.symbol == symbol,
                DailyStructure.trade_date == trade_date,
            )
        ).scalar_one_or_none()
        if existing:
            db.delete(existing)
            db.flush()

        structure = DailyStructure(
            trade_date=trade_date,
            symbol=symbol,
            created_at=utc_now(),
            spot_reference=None,
            call_wall=call_wall,
            put_wall=put_wall,
            plus_gex=None,
            minus_gex=None,
            net_gex=None,
            total_call_oi=total_call,
            total_put_oi=total_put,
            payload={
                "put_call_oi_ratio": total_put / total_call if total_call else None,
                "top_call_strikes": call_by_strike.nlargest(10).to_dict(),
                "top_put_strikes": put_by_strike.nlargest(10).to_dict(),
            },
        )
        db.add(structure)
        db.commit()

    return {
        "symbol": symbol,
        "trade_date": trade_date,
        "call_wall": call_wall,
        "put_wall": put_wall,
        "total_call_oi": total_call,
        "total_put_oi": total_put,
    }


def latest_structure(symbol: str) -> dict | None:
    with SessionLocal() as db:
        current = db.execute(
            select(DailyStructure)
            .where(DailyStructure.symbol == symbol)
            .order_by(DailyStructure.trade_date.desc())
            .limit(2)
        ).scalars().all()

    if not current:
        return None

    latest = current[0]
    previous = current[1] if len(current) > 1 else None
    return {
        "trade_date": latest.trade_date,
        "call_wall": latest.call_wall,
        "put_wall": latest.put_wall,
        "total_call_oi": latest.total_call_oi,
        "total_put_oi": latest.total_put_oi,
        "put_call_oi_ratio": (
            latest.total_put_oi / latest.total_call_oi if latest.total_call_oi else None
        ),
        "call_wall_change": (
            latest.call_wall - previous.call_wall
            if previous and latest.call_wall is not None and previous.call_wall is not None
            else None
        ),
        "put_wall_change": (
            latest.put_wall - previous.put_wall
            if previous and latest.put_wall is not None and previous.put_wall is not None
            else None
        ),
        "call_oi_change": latest.total_call_oi - previous.total_call_oi if previous else None,
        "put_oi_change": latest.total_put_oi - previous.total_put_oi if previous else None,
    }
