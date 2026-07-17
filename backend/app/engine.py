from __future__ import annotations

from datetime import datetime, timezone
from time import monotonic

from .analytics import enrich_chain, compute_structure
from .intraday import calculate_intraday_state, evaluate_acceptance, get_intraday_bars
from .models import MarketRoadmap
from .providers import get_market_snapshot, validate_symbol


CACHE_SECONDS = 90
_CACHE = {}
_LAST_DIAGNOSTICS = {}


def side(price: float, spot: float) -> str:
    return "near" if abs(price - spot) / max(spot, 1) < 0.001 else (
        "above" if price > spot else "below"
    )


def strength(price: float, spot: float, base: int) -> int:
    proximity = max(0, 18 - int(abs(price - spot) / max(spot, 1) * 1000))
    return min(99, base + proximity)


def _safe_round(value, digits=3):
    return round(value, digits) if isinstance(value, float) else value


def build_live(symbol: str) -> MarketRoadmap:
    symbol = validate_symbol(symbol)

    spot, raw_chain, source, provider_attempts = get_market_snapshot(symbol)
    chain = enrich_chain(raw_chain, spot)
    if chain.empty:
        raise RuntimeError("Provider returned no usable option contracts.")

    intraday_error = None
    intraday = {}
    bars = None

    try:
        bars = get_intraday_bars(symbol)
        intraday = calculate_intraday_state(bars)
        spot = float(intraday["last_close"])
    except Exception as exc:
        intraday_error = str(exc)

    structure = compute_structure(chain, spot)
    expected = structure["expected_move"]
    upper = structure["upper_transition"]
    lower = structure["lower_transition"]

    upside_trigger = max(value for value in [spot, upper] if value is not None)
    downside_trigger = min(value for value in [spot, lower] if value is not None)

    bull_reasons = []
    bear_reasons = []
    bull_cautions = []
    bear_cautions = []

    bull_score = 35
    bear_score = 35

    # Structural confirmations
    if upper is not None:
        if spot >= upper:
            bull_score += 18
            bull_reasons.append("Spot is above the positive transition.")
        else:
            bull_reasons.append("Positive transition remains the upside control line.")

    if lower is not None:
        if spot <= lower:
            bear_score += 18
            bear_reasons.append("Spot is below the lower transition.")
        else:
            bear_reasons.append("Lower transition remains the downside control line.")

    if structure["plus_gex"] is not None and structure["plus_gex"] > spot:
        bull_score += 12
        bull_reasons.append("Positive GEX remains overhead as a target.")

    if structure["minus_gex"] is not None and structure["minus_gex"] < spot:
        bear_score += 12
        bear_reasons.append("Negative GEX remains below spot.")

    if structure["call_wall"] is not None and structure["call_wall"] > spot:
        bull_score += 8
        bull_reasons.append("Call wall defines the next resistance or magnet.")

    if structure["put_wall"] is not None and structure["put_wall"] < spot:
        bear_score += 8
        bear_reasons.append("Put wall defines the next support or acceleration zone.")

    if structure["regime"] == "Call Dominated":
        bull_score += 10
        bull_reasons.append("Modeled gamma is call dominated.")
        bear_cautions.append("Call gamma may suppress initial downside volatility.")
    elif structure["regime"] == "Put Dominated":
        bear_score += 10
        bear_reasons.append("Modeled gamma is put dominated.")
        bull_cautions.append("Put gamma increases downside instability.")

    # Intraday confirmations
    bullish_acceptance = False
    bearish_acceptance = False

    if bars is not None and intraday:
        bullish_acceptance = evaluate_acceptance(
            bars, float(upside_trigger), "bullish", bars_required=2
        )
        bearish_acceptance = evaluate_acceptance(
            bars, float(downside_trigger), "bearish", bars_required=2
        )

        if intraday["above_vwap"]:
            bull_score += 10
            bull_reasons.append("Price is above session VWAP.")
        else:
            bear_score += 10
            bear_reasons.append("Price is below session VWAP.")

        if intraday["ema_bullish"]:
            bull_score += 8
            bull_reasons.append("9 EMA is above the 21 EMA.")
        else:
            bear_score += 8
            bear_reasons.append("9 EMA is below the 21 EMA.")

        if intraday["momentum_up"]:
            bull_score += 4
            bull_reasons.append("Latest 5-minute close shows positive momentum.")
        if intraday["momentum_down"]:
            bear_score += 4
            bear_reasons.append("Latest 5-minute close shows negative momentum.")

        if bullish_acceptance:
            bull_score += 15
            bull_reasons.append("Two completed 5-minute candles accepted above the trigger.")

        if bearish_acceptance:
            bear_score += 15
            bear_reasons.append("Two completed 5-minute candles accepted below the trigger.")

        if spot > intraday["opening_range_high"]:
            bull_score += 6
            bull_reasons.append("Price is above the opening range high.")

        if spot < intraday["opening_range_low"]:
            bear_score += 6
            bear_reasons.append("Price is below the opening range low.")
    else:
        bull_cautions.append("Intraday confirmation data is unavailable.")
        bear_cautions.append("Intraday confirmation data is unavailable.")

    bull_score = min(96, bull_score)
    bear_score = min(96, bear_score)

    bull_status = "active" if bullish_acceptance and bull_score >= 70 else "forming"
    bear_status = "active" if bearish_acceptance and bear_score >= 70 else "forming"

    if bull_status == "active" and bear_status != "active":
        bias = f"Bullish scenario ACTIVE above {upside_trigger:.2f}"
        conviction = bull_score
    elif bear_status == "active" and bull_status != "active":
        bias = f"Bearish scenario ACTIVE below {downside_trigger:.2f}"
        conviction = bear_score
    elif bull_score >= bear_score + 8:
        bias = f"Bullish setup forming above {upside_trigger:.2f}"
        conviction = bull_score
    elif bear_score >= bull_score + 8:
        bias = f"Bearish setup forming below {downside_trigger:.2f}"
        conviction = bear_score
    else:
        bias = "No confirmed setup — wait for acceptance"
        conviction = max(bull_score, bear_score)

    levels = []
    for name, price, role, base in [
        ("Call Wall", structure["call_wall"], "Resistance / magnet", 72),
        ("+GEX", structure["plus_gex"], "Positive gamma concentration", 74),
        ("Upper Transition", upper, "Bullish control line", 68),
        ("Lower Transition", lower, "Bearish control line", 68),
        ("-GEX", structure["minus_gex"], "Negative gamma concentration", 74),
        ("Put Wall", structure["put_wall"], "Support / acceleration", 72),
    ]:
        if price is not None:
            levels.append(
                {
                    "name": name,
                    "price": round(float(price), 2),
                    "role": role,
                    "strength": strength(float(price), spot, base),
                    "side": side(float(price), spot),
                }
            )

    flow = []
    strike_frame = structure["strikes"]
    strike_frame = strike_frame[
        (strike_frame.strike >= spot * 0.94)
        & (strike_frame.strike <= spot * 1.06)
    ]

    for row in strike_frame.itertuples(index=False):
        flow.append(
            {
                "strike": round(float(row.strike), 2),
                "net_gex": round(float(row.net_gex), 2),
                "net_dex": round(float(row.net_dex), 2),
                "call_oi": float(row.call_oi),
                "put_oi": float(row.put_oi),
                "call_volume": float(row.call_volume),
                "put_volume": float(row.put_volume),
                "volume_diff": float(row.call_volume - row.put_volume),
            }
        )

    metrics = {
        "net_gex": structure["net_gex"],
        "net_dex": structure["net_dex"],
        "call_oi": structure["call_oi"],
        "put_oi": structure["put_oi"],
        "call_volume": structure["call_volume"],
        "put_volume": structure["put_volume"],
        "put_call_oi_ratio": structure["put_call_oi_ratio"],
        "put_call_volume_ratio": structure["put_call_volume_ratio"],
        "call_oi_centroid": structure["call_oi_centroid"],
        "put_oi_centroid": structure["put_oi_centroid"],
        "call_volume_centroid": structure["call_volume_centroid"],
        "put_volume_centroid": structure["put_volume_centroid"],
        "bullish_score": bull_score,
        "bearish_score": bear_score,
        "vwap": intraday.get("vwap"),
        "ema9": intraday.get("ema9"),
        "ema21": intraday.get("ema21"),
        "opening_range_high": intraday.get("opening_range_high"),
        "opening_range_low": intraday.get("opening_range_low"),
        "session_high": intraday.get("session_high"),
        "session_low": intraday.get("session_low"),
        "session_open": intraday.get("session_open"),
        "intraday_bars": intraday.get("bars"),
        "last_bar_time": intraday.get("last_bar_time"),
    }
    metrics = {key: _safe_round(value) for key, value in metrics.items()}

    bull_target1 = structure["plus_gex"] or expected["high"]
    bull_target2 = structure["call_wall"] or expected["high"]
    bear_target1 = structure["minus_gex"] or expected["low"]
    bear_target2 = structure["put_wall"] or expected["low"]

    if bull_status == "active":
        briefing = (
            f"BULLISH SCENARIO ACTIVE. {symbol} has two 5-minute closes above "
            f"{upside_trigger:.2f}. Price is "
            f"{'above' if intraday.get('above_vwap') else 'below'} VWAP. "
            f"Target 1 is {float(bull_target1):.2f}; invalidation is {downside_trigger:.2f}."
        )
    elif bear_status == "active":
        briefing = (
            f"BEARISH SCENARIO ACTIVE. {symbol} has two 5-minute closes below "
            f"{downside_trigger:.2f}. Price is "
            f"{'below' if not intraday.get('above_vwap') else 'above'} VWAP. "
            f"Target 1 is {float(bear_target1):.2f}; invalidation is {upside_trigger:.2f}."
        )
    else:
        briefing = (
            f"No confirmed trade yet. {symbol} is in a "
            f"{structure['regime'].lower()} structure using {source}. "
            f"Bullish activation requires two completed 5-minute closes above "
            f"{upside_trigger:.2f}; bearish activation requires two closes below "
            f"{downside_trigger:.2f}."
        )

    warnings = [
        "Options and intraday data may be delayed or incomplete.",
        "Dealer positioning is estimated from public open interest and modeled Greeks.",
        "Conviction is a rules-based score, not a measured probability of profit.",
    ]
    if intraday_error:
        warnings.append(f"Intraday confirmation unavailable: {intraday_error}")

    _LAST_DIAGNOSTICS[symbol] = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "provider_attempts": provider_attempts,
        "intraday": intraday,
        "intraday_error": intraday_error,
        "bullish_acceptance": bullish_acceptance,
        "bearish_acceptance": bearish_acceptance,
        "bullish_score": bull_score,
        "bearish_score": bear_score,
    }

    return MarketRoadmap.model_validate(
        {
            "symbol": symbol,
            "spot": round(spot, 2),
            "source": f"{source} + Yahoo 5m chart",
            "is_live": True,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "regime": structure["regime"],
            "bias": bias,
            "conviction": conviction,
            "expected_move": {
                "low": round(expected["low"], 2),
                "high": round(expected["high"], 2),
                "points": round(expected["points"], 2),
                "expiration": expected["expiration"],
            },
            "levels": levels,
            "scenarios": [
                {
                    "id": "bullish-continuation",
                    "name": "Bullish continuation",
                    "direction": "bullish",
                    "status": bull_status,
                    "trigger_price": round(upside_trigger, 2),
                    "trigger": (
                        f"Two completed 5-minute closes above {upside_trigger:.2f}, "
                        "price above VWAP, and 9 EMA above 21 EMA."
                    ),
                    "target1": round(float(bull_target1), 2),
                    "target2": round(float(bull_target2), 2),
                    "invalidation": round(float(downside_trigger), 2),
                    "conviction": bull_score,
                    "reasons": bull_reasons or ["No bullish confirmations yet."],
                    "cautions": bull_cautions or ["Avoid entries already extended into resistance."],
                },
                {
                    "id": "bearish-breakdown",
                    "name": "Bearish breakdown",
                    "direction": "bearish",
                    "status": bear_status,
                    "trigger_price": round(downside_trigger, 2),
                    "trigger": (
                        f"Two completed 5-minute closes below {downside_trigger:.2f}, "
                        "price below VWAP, and 9 EMA below 21 EMA."
                    ),
                    "target1": round(float(bear_target1), 2),
                    "target2": round(float(bear_target2), 2),
                    "invalidation": round(float(upside_trigger), 2),
                    "conviction": bear_score,
                    "reasons": bear_reasons or ["No bearish confirmations yet."],
                    "cautions": bear_cautions or ["Avoid chasing after a large expansion move."],
                },
            ],
            "briefing": briefing,
            "warnings": warnings,
            "flow": flow,
            "metrics": metrics,
        }
    )


def fallback(symbol: str, error: Exception) -> MarketRoadmap:
    previous = _LAST_DIAGNOSTICS.get(symbol, {})
    previous["last_error"] = str(error)
    _LAST_DIAGNOSTICS[symbol] = previous

    return MarketRoadmap.model_validate(
        {
            "symbol": symbol,
            "spot": 600.0,
            "source": "Fallback",
            "is_live": False,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "regime": "Data Unavailable",
            "bias": "Live feed unavailable — do not use for trading",
            "conviction": 0,
            "expected_move": {
                "low": 596.0,
                "high": 604.0,
                "points": 4.0,
                "expiration": None,
            },
            "levels": [],
            "scenarios": [
                {
                    "id": "data-warning",
                    "name": "Waiting for live data",
                    "direction": "neutral",
                    "status": "forming",
                    "trigger_price": 600.0,
                    "trigger": "Restore the market-data connection.",
                    "target1": 600.0,
                    "target2": None,
                    "invalidation": 600.0,
                    "conviction": 0,
                    "reasons": ["No usable live chain returned."],
                    "cautions": [str(error)],
                }
            ],
            "briefing": "The API is online, but the market-data pipeline failed.",
            "warnings": [str(error)],
            "flow": [],
            "metrics": {},
        }
    )


def get_roadmap(symbol: str = "SPY"):
    symbol = symbol.upper().strip()
    cached = _CACHE.get(symbol)
    if cached and monotonic() - cached[0] < CACHE_SECONDS:
        return cached[1]

    try:
        result = build_live(symbol)
    except Exception as error:
        result = fallback(symbol, error)

    _CACHE[symbol] = (monotonic(), result)
    return result


def get_diagnostics(symbol: str = "SPY"):
    symbol = symbol.upper().strip()
    if symbol not in _LAST_DIAGNOSTICS:
        get_roadmap(symbol)
    return _LAST_DIAGNOSTICS.get(symbol, {"message": "No diagnostics available."})
