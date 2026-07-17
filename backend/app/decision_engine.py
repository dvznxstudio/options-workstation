from __future__ import annotations

from datetime import datetime, timezone
from time import monotonic

from .analytics import compute_structure, enrich_chain
from .intraday import calculate_intraday_state, evaluate_acceptance
from .leadership import futures_leadership
from .market_providers import get_bars
from .models import MarketRoadmap
from .providers import get_market_snapshot, validate_symbol
from .timeframes import CONFIGS, filter_option_chain, get_config, level_relevance


_CACHE: dict[str, tuple[float, MarketRoadmap]] = {}
CACHE_SECONDS = 90


def _side(price: float, spot: float) -> str:
    distance = abs(price - spot) / max(spot, 1)
    if distance < 0.001:
        return "near"
    return "above" if price > spot else "below"


def _strength(price: float, spot: float, base: int, timeframe: str) -> int:
    config = get_config(timeframe)
    relative = abs(price - spot) / max(spot, 1)
    distance_penalty = int((relative / config.strike_distance_pct) * 30)
    return max(20, min(99, base - distance_penalty + 20))


def _bars_state(symbol: str, timeframe: str) -> tuple[dict, object, str, list]:
    config = get_config(timeframe)
    bars, provider, attempts = get_bars(
        symbol,
        interval=config.bar_interval,
        lookback_days=config.lookback_days,
    )
    normalized = bars.copy()
    normalized["timestamp_et"] = normalized["timestamp"].dt.tz_convert("America/New_York")
    normalized["session_date"] = normalized["timestamp_et"].dt.date
    state = calculate_intraday_state(normalized)
    return state, normalized, provider, attempts


def build_timeframe(symbol: str, timeframe: str) -> MarketRoadmap:
    symbol = validate_symbol(symbol)
    config = get_config(timeframe)

    spot, raw_chain, options_source, option_attempts = get_market_snapshot(symbol)
    filtered_chain = filter_option_chain(raw_chain, spot, timeframe)
    chain = enrich_chain(filtered_chain, spot)
    if chain.empty:
        raise RuntimeError(f"No relevant {timeframe} option contracts remain after filtering.")

    bar_error = None
    bars = None
    bar_state = {}
    bar_provider = "unavailable"
    bar_attempts = []
    try:
        bar_state, bars, bar_provider, bar_attempts = _bars_state(symbol, timeframe)
        spot = float(bar_state["last_close"])
    except Exception as exc:
        bar_error = str(exc)

    structure = compute_structure(chain, spot)
    leadership = futures_leadership(
        symbol,
        interval="5m" if timeframe == "today" else ("1h" if timeframe == "week" else "1d"),
    )

    upper = structure["upper_transition"]
    lower = structure["lower_transition"]

    relevant_levels = {
        "Call Wall": structure["call_wall"],
        "+GEX": structure["plus_gex"],
        "Upper Transition": upper,
        "Lower Transition": lower,
        "-GEX": structure["minus_gex"],
        "Put Wall": structure["put_wall"],
    }

    # Remove distant mathematical outputs from the actionable map.
    relevant_levels = {
        name: price
        for name, price in relevant_levels.items()
        if level_relevance(price, spot, timeframe)
    }

    overhead = sorted([float(v) for v in relevant_levels.values() if v is not None and v >= spot])
    below = sorted([float(v) for v in relevant_levels.values() if v is not None and v <= spot], reverse=True)

    upside_trigger = overhead[0] if overhead else spot
    downside_trigger = below[0] if below else spot

    evidence = {
        "options_positioning": 50,
        "price_structure": 50,
        "trend_alignment": 50,
        "futures_leadership": 50,
        "data_quality": 50,
    }
    bull_reasons, bear_reasons = [], []
    bull_cautions, bear_cautions = [], []

    if structure["regime"] == "Call Dominated":
        evidence["options_positioning"] = 72
        bull_reasons.append("Relevant-expiration gamma is call dominated.")
    elif structure["regime"] == "Put Dominated":
        evidence["options_positioning"] = 28
        bear_reasons.append("Relevant-expiration gamma is put dominated.")

    bullish_acceptance = bearish_acceptance = False
    if bar_state and bars is not None:
        above_vwap = bool(bar_state["above_vwap"])
        ema_bullish = bool(bar_state["ema_bullish"])
        evidence["price_structure"] = 72 if above_vwap else 28
        evidence["trend_alignment"] = 72 if ema_bullish else 28

        if above_vwap:
            bull_reasons.append(f"Price is above the {timeframe} VWAP reference.")
        else:
            bear_reasons.append(f"Price is below the {timeframe} VWAP reference.")

        if ema_bullish:
            bull_reasons.append("Fast EMA is above slow EMA.")
        else:
            bear_reasons.append("Fast EMA is below slow EMA.")

        bullish_acceptance = evaluate_acceptance(
            bars, upside_trigger, "bullish", config.acceptance_bars
        )
        bearish_acceptance = evaluate_acceptance(
            bars, downside_trigger, "bearish", config.acceptance_bars
        )
    else:
        bull_cautions.append(f"{timeframe.title()} price confirmation unavailable.")
        bear_cautions.append(f"{timeframe.title()} price confirmation unavailable.")

    if leadership.get("available"):
        leader_score = int(leadership["score"])
        evidence["futures_leadership"] = leader_score
        if leadership["direction"] == "bullish":
            bull_reasons.append(
                f"{leadership['leader']} futures are providing bullish confirmation."
            )
        elif leadership["direction"] == "bearish":
            bear_reasons.append(
                f"{leadership['leader']} futures are providing bearish confirmation."
            )

    successful_sources = sum(1 for attempt in option_attempts + bar_attempts if attempt.get("ok"))
    evidence["data_quality"] = min(95, 45 + successful_sources * 15)

    bullish_score = round(
        evidence["options_positioning"] * 0.25
        + evidence["price_structure"] * 0.25
        + evidence["trend_alignment"] * 0.20
        + evidence["futures_leadership"] * 0.20
        + evidence["data_quality"] * 0.10
    )
    bearish_score = round(
        (100 - evidence["options_positioning"]) * 0.25
        + (100 - evidence["price_structure"]) * 0.25
        + (100 - evidence["trend_alignment"]) * 0.20
        + (100 - evidence["futures_leadership"]) * 0.20
        + evidence["data_quality"] * 0.10
    )

    bull_status = "active" if bullish_acceptance and bullish_score >= 65 else "forming"
    bear_status = "active" if bearish_acceptance and bearish_score >= 65 else "forming"

    if bull_status == "active" and bull_status != bear_status:
        bias = f"{timeframe.title()} bullish scenario ACTIVE"
        conviction = bullish_score
    elif bear_status == "active" and bull_status != bear_status:
        bias = f"{timeframe.title()} bearish scenario ACTIVE"
        conviction = bearish_score
    elif bullish_score >= bearish_score + 8:
        bias = f"{timeframe.title()} bullish setup forming"
        conviction = bullish_score
    elif bearish_score >= bullish_score + 8:
        bias = f"{timeframe.title()} bearish setup forming"
        conviction = bearish_score
    else:
        bias = f"{timeframe.title()} neutral — wait for confirmation"
        conviction = max(bullish_score, bearish_score)

    roles = {
        "Call Wall": "Resistance / upside magnet",
        "+GEX": "Positive gamma concentration",
        "Upper Transition": "Bullish control line",
        "Lower Transition": "Bearish control line",
        "-GEX": "Negative gamma concentration",
        "Put Wall": "Support / downside magnet",
    }
    levels = [
        {
            "name": name,
            "price": round(float(price), 2),
            "role": roles[name],
            "strength": _strength(float(price), spot, 72, timeframe),
            "side": _side(float(price), spot),
        }
        for name, price in relevant_levels.items()
        if price is not None
    ]

    expected = structure["expected_move"]
    bull_targets = overhead[1:3] if len(overhead) > 1 else [expected["high"]]
    bear_targets = below[1:3] if len(below) > 1 else [expected["low"]]

    while len(bull_targets) < 2:
        bull_targets.append(expected["high"])
    while len(bear_targets) < 2:
        bear_targets.append(expected["low"])

    flow = []
    for row in structure["strikes"].itertuples(index=False):
        flow.append({
            "strike": round(float(row.strike), 2),
            "net_gex": round(float(row.net_gex), 2),
            "net_dex": round(float(row.net_dex), 2),
            "call_oi": float(row.call_oi),
            "put_oi": float(row.put_oi),
            "call_volume": float(row.call_volume),
            "put_volume": float(row.put_volume),
            "volume_diff": float(row.call_volume - row.put_volume),
        })

    briefing = (
        f"{timeframe.title()} engine uses expirations within {config.max_days_to_expiry} days "
        f"and strikes within approximately {config.strike_distance_pct:.0%} of spot. "
        f"{bias}. Bullish activation is above {upside_trigger:.2f}; "
        f"bearish activation is below {downside_trigger:.2f}."
    )

    metrics = {
        "timeframe": timeframe,
        "max_days_to_expiry": config.max_days_to_expiry,
        "strike_distance_pct": config.strike_distance_pct,
        "contracts_used": len(chain),
        "options_positioning_score": evidence["options_positioning"],
        "price_structure_score": evidence["price_structure"],
        "trend_alignment_score": evidence["trend_alignment"],
        "futures_leadership_score": evidence["futures_leadership"],
        "data_quality_score": evidence["data_quality"],
        "bullish_score": bullish_score,
        "bearish_score": bearish_score,
        "vwap": bar_state.get("vwap"),
        "ema9": bar_state.get("ema9"),
        "ema21": bar_state.get("ema21"),
        "opening_range_high": bar_state.get("opening_range_high"),
        "opening_range_low": bar_state.get("opening_range_low"),
        "net_gex": structure["net_gex"],
        "net_dex": structure["net_dex"],
        "futures_leadership": leadership,
    }

    warnings = [
        "Dealer positioning remains an estimate derived from public or licensed market data.",
        "A confidence score is evidence alignment, not a guaranteed probability of profit.",
        f"Distant levels outside the {timeframe} relevance window are intentionally hidden.",
    ]
    if bar_error:
        warnings.append(bar_error)

    return MarketRoadmap.model_validate({
        "symbol": symbol,
        "spot": round(spot, 2),
        "source": f"{options_source} + {bar_provider}",
        "is_live": True,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "regime": structure["regime"],
        "bias": bias,
        "conviction": conviction,
        "expected_move": {
            "low": round(float(expected["low"]), 2),
            "high": round(float(expected["high"]), 2),
            "points": round(float(expected["points"]), 2),
            "expiration": expected["expiration"],
        },
        "levels": levels,
        "scenarios": [
            {
                "id": f"{timeframe}-bullish",
                "name": f"{timeframe.title()} bullish continuation",
                "direction": "bullish",
                "status": bull_status,
                "trigger_price": round(float(upside_trigger), 2),
                "trigger": f"Acceptance above {upside_trigger:.2f} with trend and futures confirmation.",
                "target1": round(float(bull_targets[0]), 2),
                "target2": round(float(bull_targets[1]), 2),
                "invalidation": round(float(downside_trigger), 2),
                "conviction": bullish_score,
                "reasons": bull_reasons or ["No strong bullish confirmations yet."],
                "cautions": bull_cautions or ["Wait for acceptance; do not chase an extended move."],
            },
            {
                "id": f"{timeframe}-bearish",
                "name": f"{timeframe.title()} bearish continuation",
                "direction": "bearish",
                "status": bear_status,
                "trigger_price": round(float(downside_trigger), 2),
                "trigger": f"Acceptance below {downside_trigger:.2f} with trend and futures confirmation.",
                "target1": round(float(bear_targets[0]), 2),
                "target2": round(float(bear_targets[1]), 2),
                "invalidation": round(float(upside_trigger), 2),
                "conviction": bearish_score,
                "reasons": bear_reasons or ["No strong bearish confirmations yet."],
                "cautions": bear_cautions or ["Wait for acceptance; do not chase an extended move."],
            },
        ],
        "briefing": briefing,
        "warnings": warnings,
        "flow": flow,
        "metrics": metrics,
    })


def build_combined(symbol: str) -> MarketRoadmap:
    roadmaps = {name: build_timeframe(symbol, name) for name in CONFIGS}
    today, week, month = roadmaps["today"], roadmaps["week"], roadmaps["month"]

    scores = {
        name: {
            "bias": roadmap.bias,
            "conviction": roadmap.conviction,
            "bullish": roadmap.metrics.get("bullish_score"),
            "bearish": roadmap.metrics.get("bearish_score"),
        }
        for name, roadmap in roadmaps.items()
    }
    bullish_average = round(sum(float(v["bullish"] or 50) for v in scores.values()) / 3)
    bearish_average = round(sum(float(v["bearish"] or 50) for v in scores.values()) / 3)

    if bullish_average >= bearish_average + 8:
        bias = "Multi-timeframe bullish alignment"
        conviction = bullish_average
    elif bearish_average >= bullish_average + 8:
        bias = "Multi-timeframe bearish alignment"
        conviction = bearish_average
    else:
        bias = "Mixed timeframes — tactical trades only"
        conviction = max(bullish_average, bearish_average)

    if "bearish" in today.bias.lower() and "bullish" in week.bias.lower() and "bullish" in month.bias.lower():
        interpretation = "Short-term weakness inside a bullish higher-timeframe structure."
    elif "bullish" in today.bias.lower() and "bearish" in week.bias.lower() and "bearish" in month.bias.lower():
        interpretation = "Short-term strength inside a bearish higher-timeframe structure."
    else:
        interpretation = bias

    metrics = dict(today.metrics)
    metrics.update({
        "timeframe": "combined",
        "today": scores["today"],
        "week": scores["week"],
        "month": scores["month"],
        "bullish_score": bullish_average,
        "bearish_score": bearish_average,
        "combined_interpretation": interpretation,
    })

    return MarketRoadmap.model_validate({
        **today.model_dump(),
        "bias": bias,
        "conviction": conviction,
        "briefing": (
            f"{interpretation} Today: {today.bias} ({today.conviction}). "
            f"Week: {week.bias} ({week.conviction}). Month: {month.bias} ({month.conviction})."
        ),
        "metrics": metrics,
        "warnings": list(dict.fromkeys(today.warnings + week.warnings + month.warnings)),
    })


def get_decision_roadmap(symbol: str, timeframe: str = "today") -> MarketRoadmap:
    key = f"{symbol.upper()}:{timeframe.lower()}"
    cached = _CACHE.get(key)
    if cached and monotonic() - cached[0] < CACHE_SECONDS:
        return cached[1]

    result = build_combined(symbol) if timeframe.lower() == "combined" else build_timeframe(symbol, timeframe)
    _CACHE[key] = (monotonic(), result)
    return result
