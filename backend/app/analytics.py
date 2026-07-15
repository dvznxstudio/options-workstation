from __future__ import annotations
from datetime import datetime, timezone
import math
import numpy as np
import pandas as pd

SQRT_TWO = math.sqrt(2.0)
SQRT_TWO_PI = math.sqrt(2.0 * math.pi)

def normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / SQRT_TWO))

def normal_pdf(value: float) -> float:
    return math.exp(-0.5 * value * value) / SQRT_TWO_PI

def years_to_expiration(expiration: str) -> float:
    expiry = datetime.strptime(expiration, "%Y-%m-%d").replace(hour=16, minute=0, tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    return max((expiry - now).total_seconds(), 60.0) / (365.0 * 24.0 * 3600.0)

def greeks(spot: float, strike: float, time_years: float, iv: float, option_type: str,
           rate: float = 0.043, dividend_yield: float = 0.012) -> tuple[float, float]:
    spot = max(float(spot), 1e-9)
    strike = max(float(strike), 1e-9)
    time_years = max(float(time_years), 1e-9)
    iv = max(float(iv), 1e-4)
    d1 = (math.log(spot / strike) + (rate - dividend_yield + 0.5 * iv * iv) * time_years) / (iv * math.sqrt(time_years))
    gamma = math.exp(-dividend_yield * time_years) * normal_pdf(d1) / (spot * iv * math.sqrt(time_years))
    delta = math.exp(-dividend_yield * time_years) * (
        normal_cdf(d1) if option_type == "call" else normal_cdf(d1) - 1.0
    )
    return float(delta), float(gamma)

def enrich_chain(chain: pd.DataFrame, spot: float) -> pd.DataFrame:
    df = chain.copy()
    for col in ["strike","bid","ask","last","volume","open_interest","implied_volatility"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
    deltas, gammas = [], []
    for row in df.itertuples(index=False):
        delta, gamma = greeks(
            spot=spot,
            strike=float(row.strike),
            time_years=years_to_expiration(str(row.expiration)),
            iv=float(row.implied_volatility),
            option_type=str(row.option_type),
        )
        deltas.append(delta)
        gammas.append(gamma)
    df["delta"] = deltas
    df["gamma"] = gammas
    df["mid"] = np.where((df["bid"] > 0) & (df["ask"] > 0), (df["bid"] + df["ask"]) / 2.0, df["last"])
    sign = np.where(df["option_type"].eq("call"), 1.0, -1.0)
    df["gex"] = df["gamma"] * df["open_interest"] * 100.0 * spot * spot * 0.01 * sign
    df["dex"] = df["delta"] * df["open_interest"] * 100.0
    return df

def aggregate(chain: pd.DataFrame) -> pd.DataFrame:
    calls = chain[chain["option_type"].eq("call")]
    puts = chain[chain["option_type"].eq("put")]
    total = chain.groupby("strike", as_index=False).agg(
        net_gex=("gex","sum"), net_dex=("dex","sum"),
        total_oi=("open_interest","sum"), total_volume=("volume","sum"))
    call_group = calls.groupby("strike", as_index=False).agg(
        call_oi=("open_interest","sum"), call_volume=("volume","sum"))
    put_group = puts.groupby("strike", as_index=False).agg(
        put_oi=("open_interest","sum"), put_volume=("volume","sum"))
    return total.merge(call_group,on="strike",how="left").merge(put_group,on="strike",how="left").fillna(0).sort_values("strike")

def expected_move(chain: pd.DataFrame, spot: float) -> dict:
    expirations = sorted(chain["expiration"].dropna().unique().tolist())
    if not expirations:
        return {"low": spot, "high": spot, "points": 0.0, "expiration": None}
    expiration = expirations[0]
    subset = chain[chain["expiration"].eq(expiration)].copy()
    nearest_index = (subset["strike"] - spot).abs().idxmin()
    nearest_strike = float(subset.loc[nearest_index, "strike"])
    atm = subset[subset["strike"].eq(nearest_strike)]
    points = max(float(atm.loc[atm["option_type"].eq("call"),"mid"].sum()) + float(atm.loc[atm["option_type"].eq("put"),"mid"].sum()), 0.0)
    return {"low": spot-points, "high": spot+points, "points": points, "expiration": expiration}

def transition_levels(strikes: pd.DataFrame, spot: float) -> tuple[float|None, float|None]:
    df = strikes.sort_values("strike")
    signs = np.sign(df["net_gex"].to_numpy())
    transitions = []
    for i in range(1, len(df)):
        if signs[i] != signs[i-1] and signs[i] != 0:
            transitions.append(float(df.iloc[i]["strike"]))
    below = [x for x in transitions if x <= spot]
    above = [x for x in transitions if x >= spot]
    return (max(below) if below else None, min(above) if above else None)

def centroid(df: pd.DataFrame, weight_col: str) -> float|None:
    weight = pd.to_numeric(df[weight_col], errors="coerce").fillna(0.0)
    total = float(weight.sum())
    return None if total <= 0 else float((df["strike"] * weight).sum() / total)

def compute_structure(chain: pd.DataFrame, spot: float) -> dict:
    strikes = aggregate(chain)
    calls = chain[chain["option_type"].eq("call")]
    puts = chain[chain["option_type"].eq("put")]
    positive = strikes[strikes["net_gex"] > 0]
    negative = strikes[strikes["net_gex"] < 0]
    plus_gex = float(positive.loc[positive["net_gex"].idxmax(),"strike"]) if not positive.empty else None
    minus_gex = float(negative.loc[negative["net_gex"].idxmin(),"strike"]) if not negative.empty else None
    call_wall = float(calls.groupby("strike")["gex"].sum().idxmax()) if not calls.empty else None
    put_group = puts.groupby("strike")["gex"].sum()
    put_wall = float(put_group.idxmin()) if not put_group.empty else None
    lower_transition, upper_transition = transition_levels(strikes, spot)
    total_call_gex = float(calls["gex"].sum())
    total_put_gex = abs(float(puts["gex"].sum()))
    regime = "Call Dominated" if total_call_gex > total_put_gex*1.15 else ("Put Dominated" if total_put_gex > total_call_gex*1.15 else "Balanced Gamma")
    call_oi = int(calls["open_interest"].sum()); put_oi = int(puts["open_interest"].sum())
    call_volume = int(calls["volume"].sum()); put_volume = int(puts["volume"].sum())
    return {
        "strikes": strikes, "net_gex": float(strikes["net_gex"].sum()),
        "net_dex": float(strikes["net_dex"].sum()), "plus_gex": plus_gex,
        "minus_gex": minus_gex, "call_wall": call_wall, "put_wall": put_wall,
        "lower_transition": lower_transition, "upper_transition": upper_transition,
        "regime": regime, "expected_move": expected_move(chain, spot),
        "call_oi": call_oi, "put_oi": put_oi, "call_volume": call_volume,
        "put_volume": put_volume,
        "put_call_oi_ratio": (put_oi/call_oi) if call_oi else None,
        "put_call_volume_ratio": (put_volume/call_volume) if call_volume else None,
        "call_oi_centroid": centroid(calls,"open_interest"),
        "put_oi_centroid": centroid(puts,"open_interest"),
        "call_volume_centroid": centroid(calls,"volume"),
        "put_volume_centroid": centroid(puts,"volume"),
    }
