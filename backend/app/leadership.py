from __future__ import annotations

import pandas as pd

from .market_providers import get_bars


PAIR_MAP = {
    "SPY": ("ES", "MES"),
    "QQQ": ("NQ", "MNQ"),
    "IWM": ("RTY", "M2K"),
}


def _state(frame: pd.DataFrame) -> dict:
    if frame.empty:
        raise RuntimeError("No bars available.")
    df = frame.copy().sort_values("timestamp")
    close = df["close"].astype(float)
    volume = df["volume"].fillna(0).astype(float)

    typical = (df["high"].astype(float) + df["low"].astype(float) + close) / 3
    cumulative_volume = volume.cumsum()
    vwap = ((typical * volume).cumsum() / cumulative_volume.replace(0, float("nan"))).ffill()
    ema9 = close.ewm(span=9, adjust=False).mean()
    ema21 = close.ewm(span=21, adjust=False).mean()

    last = float(close.iloc[-1])
    first = float(close.iloc[max(0, len(close) - 12)])
    change_pct = ((last / first) - 1.0) * 100 if first else 0.0

    score = 50
    reasons = []
    if last > float(vwap.iloc[-1]):
        score += 15
        reasons.append("above VWAP")
    else:
        score -= 15
        reasons.append("below VWAP")
    if float(ema9.iloc[-1]) > float(ema21.iloc[-1]):
        score += 15
        reasons.append("EMA 9 above EMA 21")
    else:
        score -= 15
        reasons.append("EMA 9 below EMA 21")
    if change_pct > 0:
        score += min(15, int(abs(change_pct) * 8))
        reasons.append("positive short-term return")
    elif change_pct < 0:
        score -= min(15, int(abs(change_pct) * 8))
        reasons.append("negative short-term return")

    return {
        "price": round(last, 4),
        "vwap": round(float(vwap.iloc[-1]), 4),
        "ema9": round(float(ema9.iloc[-1]), 4),
        "ema21": round(float(ema21.iloc[-1]), 4),
        "change_pct": round(change_pct, 3),
        "score": max(0, min(100, score)),
        "reasons": reasons,
    }


def futures_leadership(etf_symbol: str, interval: str = "5m") -> dict:
    pairs = PAIR_MAP.get(etf_symbol.upper())
    if not pairs:
        return {"available": False, "message": "No futures pair configured."}

    results = []
    attempts = []
    for future_symbol in pairs:
        try:
            bars, provider, provider_attempts = get_bars(
                future_symbol,
                interval=interval,
                lookback_days=5 if interval == "5m" else 30,
            )
            results.append({
                "symbol": future_symbol,
                "provider": provider,
                **_state(bars),
            })
            attempts.extend(provider_attempts)
        except Exception as exc:
            attempts.append({"symbol": future_symbol, "ok": False, "message": str(exc)})

    if not results:
        return {"available": False, "attempts": attempts}

    leader = max(results, key=lambda item: abs(item["score"] - 50))
    direction = "bullish" if leader["score"] > 55 else ("bearish" if leader["score"] < 45 else "neutral")

    return {
        "available": True,
        "direction": direction,
        "leader": leader["symbol"],
        "score": leader["score"],
        "contracts": results,
        "attempts": attempts,
    }
