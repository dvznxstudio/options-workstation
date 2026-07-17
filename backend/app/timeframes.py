from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import pandas as pd


@dataclass(frozen=True)
class TimeframeConfig:
    name: str
    max_days_to_expiry: int
    strike_distance_pct: float
    bar_interval: str
    lookback_days: int
    acceptance_bars: int


CONFIGS = {
    "today": TimeframeConfig("today", 2, 0.035, "5m", 5, 2),
    "week": TimeframeConfig("week", 10, 0.09, "1h", 30, 2),
    "month": TimeframeConfig("month", 45, 0.18, "1d", 365, 2),
}


def get_config(timeframe: str) -> TimeframeConfig:
    normalized = timeframe.lower().strip()
    if normalized not in CONFIGS:
        raise ValueError("Timeframe must be today, week, month, or combined.")
    return CONFIGS[normalized]


def filter_option_chain(chain: pd.DataFrame, spot: float, timeframe: str) -> pd.DataFrame:
    config = get_config(timeframe)
    df = chain.copy()
    now = datetime.now(timezone.utc).date()

    expiration_dates = pd.to_datetime(df["expiration"], errors="coerce").dt.date
    days = expiration_dates.map(lambda value: (value - now).days if pd.notna(value) else 9999)

    low = spot * (1.0 - config.strike_distance_pct)
    high = spot * (1.0 + config.strike_distance_pct)

    filtered = df[
        (days >= 0)
        & (days <= config.max_days_to_expiry)
        & (pd.to_numeric(df["strike"], errors="coerce") >= low)
        & (pd.to_numeric(df["strike"], errors="coerce") <= high)
    ].copy()

    # Never let a sparse filter produce nonsense; expand to nearest expiration and 25 nearest strikes.
    if len(filtered) < 20:
        valid = df.copy()
        valid["_days"] = days
        valid["_distance"] = (pd.to_numeric(valid["strike"], errors="coerce") - spot).abs()
        nearest_days = valid[valid["_days"] >= 0]["_days"].min()
        valid = valid[valid["_days"] == nearest_days].sort_values("_distance")
        nearest_strikes = valid["strike"].drop_duplicates().head(25)
        filtered = valid[valid["strike"].isin(nearest_strikes)].drop(columns=["_days", "_distance"])

    return filtered.reset_index(drop=True)


def level_relevance(price: float | None, spot: float, timeframe: str) -> bool:
    if price is None:
        return False
    config = get_config(timeframe)
    return abs(price - spot) / max(spot, 1.0) <= config.strike_distance_pct * 1.15
