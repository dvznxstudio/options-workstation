from __future__ import annotations

from datetime import datetime, timezone
import math
import time
from typing import Any

import pandas as pd
import requests


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/126 Safari/537.36"
    ),
    "Accept": "application/json,text/plain,*/*",
}


def _request_json(url: str, timeout: int = 20) -> dict:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = requests.get(url, headers=HEADERS, timeout=timeout)
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(0.6 * (attempt + 1))
    raise RuntimeError(f"Intraday request failed: {last_error}")


def get_intraday_bars(symbol: str) -> pd.DataFrame:
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        "?range=5d&interval=5m&includePrePost=false&events=div%2Csplits"
    )
    payload = _request_json(url)
    results = ((payload.get("chart") or {}).get("result") or [])
    if not results:
        error = (payload.get("chart") or {}).get("error")
        raise RuntimeError(f"No intraday chart result: {error}")

    result = results[0]
    timestamps = result.get("timestamp") or []
    indicators = result.get("indicators") or {}
    quote_list = indicators.get("quote") or []
    if not timestamps or not quote_list:
        raise RuntimeError("Intraday chart returned no candles.")

    quote = quote_list[0]
    frame = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(timestamps, unit="s", utc=True),
            "open": quote.get("open", []),
            "high": quote.get("high", []),
            "low": quote.get("low", []),
            "close": quote.get("close", []),
            "volume": quote.get("volume", []),
        }
    )

    for column in ["open", "high", "low", "close", "volume"]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

    frame = frame.dropna(subset=["open", "high", "low", "close"]).copy()
    if frame.empty:
        raise RuntimeError("Intraday candles were empty after normalization.")

    frame["timestamp_et"] = frame["timestamp"].dt.tz_convert("America/New_York")
    frame["session_date"] = frame["timestamp_et"].dt.date

    latest_date = frame["session_date"].max()
    session = frame[frame["session_date"] == latest_date].copy()
    session = session[
        (session["timestamp_et"].dt.time >= pd.Timestamp("09:30").time())
        & (session["timestamp_et"].dt.time <= pd.Timestamp("16:00").time())
    ].copy()

    if session.empty:
        session = frame.tail(78).copy()

    return session.reset_index(drop=True)


def calculate_intraday_state(frame: pd.DataFrame) -> dict[str, Any]:
    df = frame.copy()
    typical_price = (df["high"] + df["low"] + df["close"]) / 3.0
    volume = df["volume"].fillna(0.0)

    cumulative_volume = volume.cumsum()
    cumulative_value = (typical_price * volume).cumsum()
    df["vwap"] = cumulative_value / cumulative_volume.replace(0, float("nan"))
    df["vwap"] = df["vwap"].ffill().fillna(df["close"])

    df["ema9"] = df["close"].ewm(span=9, adjust=False).mean()
    df["ema21"] = df["close"].ewm(span=21, adjust=False).mean()

    opening = df.head(6)  # first 30 minutes
    opening_high = float(opening["high"].max())
    opening_low = float(opening["low"].min())

    latest = df.iloc[-1]
    prior = df.iloc[-2] if len(df) > 1 else latest

    last_close = float(latest["close"])
    vwap = float(latest["vwap"])
    ema9 = float(latest["ema9"])
    ema21 = float(latest["ema21"])

    above_vwap = last_close > vwap
    ema_bullish = ema9 > ema21
    momentum_up = last_close > float(prior["close"])
    momentum_down = last_close < float(prior["close"])

    session_high = float(df["high"].max())
    session_low = float(df["low"].min())
    session_open = float(df.iloc[0]["open"])

    return {
        "last_close": round(last_close, 4),
        "vwap": round(vwap, 4),
        "ema9": round(ema9, 4),
        "ema21": round(ema21, 4),
        "opening_range_high": round(opening_high, 4),
        "opening_range_low": round(opening_low, 4),
        "session_high": round(session_high, 4),
        "session_low": round(session_low, 4),
        "session_open": round(session_open, 4),
        "above_vwap": above_vwap,
        "ema_bullish": ema_bullish,
        "momentum_up": momentum_up,
        "momentum_down": momentum_down,
        "last_bar_time": latest["timestamp_et"].isoformat(),
        "bars": int(len(df)),
    }


def evaluate_acceptance(
    frame: pd.DataFrame,
    trigger: float,
    direction: str,
    bars_required: int = 2,
) -> bool:
    if frame.empty:
        return False

    closes = frame["close"].dropna().tail(bars_required)
    if len(closes) < bars_required:
        return False

    if direction == "bullish":
        return bool((closes > trigger).all())
    return bool((closes < trigger).all())
