from __future__ import annotations

from datetime import datetime, timezone
import os

from sqlalchemy import select

from .database import MarketSnapshot, ScenarioEvent, SessionLocal, utc_now
from .decision_engine import get_decision_roadmap
from .notifications import send_email
from .occ_importer import latest_structure


def _level(data: dict, name: str):
    for level in data.get("levels", []):
        if level.get("name") == name:
            return level.get("price")
    return None


def _scenario(data: dict, direction: str):
    for scenario in data.get("scenarios", []):
        if scenario.get("direction") == direction:
            return scenario
    return {}


def snapshot_payload(symbol: str) -> dict:
    roadmap = get_decision_roadmap(symbol, "today")
    data = roadmap.model_dump()
    occ = latest_structure(symbol)
    if occ:
        data["official_prior_day"] = occ
        data["metrics"]["official_call_wall"] = occ.get("call_wall")
        data["metrics"]["official_put_wall"] = occ.get("put_wall")
        data["metrics"]["official_call_wall_change"] = occ.get("call_wall_change")
        data["metrics"]["official_put_wall_change"] = occ.get("put_wall_change")
        data["metrics"]["official_call_oi_change"] = occ.get("call_oi_change")
        data["metrics"]["official_put_oi_change"] = occ.get("put_oi_change")
    return data


def _event_candidates(current: dict, previous: MarketSnapshot | None) -> list[dict]:
    events = []
    bullish = _scenario(current, "bullish")
    bearish = _scenario(current, "bearish")

    previous_bull = previous.bullish_status if previous else None
    previous_bear = previous.bearish_status if previous else None

    if bullish.get("status") == "active" and previous_bull != "active":
        events.append({
            "event_type": "scenario_active",
            "direction": "bullish",
            "title": f"{current['symbol']} bullish scenario active",
            "message": current["briefing"],
            "price": current["spot"],
            "conviction": bullish.get("conviction"),
        })

    if bearish.get("status") == "active" and previous_bear != "active":
        events.append({
            "event_type": "scenario_active",
            "direction": "bearish",
            "title": f"{current['symbol']} bearish scenario active",
            "message": current["briefing"],
            "price": current["spot"],
            "conviction": bearish.get("conviction"),
        })

    if previous:
        prior_bias = previous.bias.lower()
        current_bias = current["bias"].lower()
        if ("bullish" in prior_bias and "bearish" in current_bias) or (
            "bearish" in prior_bias and "bullish" in current_bias
        ):
            events.append({
                "event_type": "roadmap_flip",
                "direction": "neutral",
                "title": f"{current['symbol']} roadmap changed direction",
                "message": f"Previous: {previous.bias}\nCurrent: {current['bias']}",
                "price": current["spot"],
                "conviction": current["conviction"],
            })

        old_conviction = previous.conviction or 0
        if current["conviction"] - old_conviction >= 15:
            events.append({
                "event_type": "conviction_jump",
                "direction": "neutral",
                "title": f"{current['symbol']} conviction increased",
                "message": f"Conviction increased from {old_conviction} to {current['conviction']}.",
                "price": current["spot"],
                "conviction": current["conviction"],
            })

    return events


def collect_symbol(symbol: str) -> dict:
    data = snapshot_payload(symbol)
    bullish = _scenario(data, "bullish")
    bearish = _scenario(data, "bearish")
    metrics = data.get("metrics", {})

    with SessionLocal() as db:
        previous = db.execute(
            select(MarketSnapshot)
            .where(MarketSnapshot.symbol == symbol)
            .order_by(MarketSnapshot.captured_at.desc())
            .limit(1)
        ).scalar_one_or_none()

        snapshot = MarketSnapshot(
            symbol=symbol,
            captured_at=utc_now(),
            spot=data["spot"],
            source=data["source"],
            regime=data["regime"],
            bias=data["bias"],
            conviction=data["conviction"],
            bullish_score=metrics.get("bullish_score"),
            bearish_score=metrics.get("bearish_score"),
            bullish_status=bullish.get("status"),
            bearish_status=bearish.get("status"),
            vwap=metrics.get("vwap"),
            ema9=metrics.get("ema9"),
            ema21=metrics.get("ema21"),
            opening_range_high=metrics.get("opening_range_high"),
            opening_range_low=metrics.get("opening_range_low"),
            call_wall=_level(data, "Call Wall"),
            put_wall=_level(data, "Put Wall"),
            plus_gex=_level(data, "+GEX"),
            minus_gex=_level(data, "-GEX"),
            upper_transition=_level(data, "Upper Transition"),
            lower_transition=_level(data, "Lower Transition"),
            expected_low=data["expected_move"].get("low"),
            expected_high=data["expected_move"].get("high"),
            net_gex=metrics.get("net_gex"),
            net_dex=metrics.get("net_dex"),
            payload=data,
        )
        db.add(snapshot)

        created_events = []
        for candidate in _event_candidates(data, previous):
            event = ScenarioEvent(
                symbol=symbol,
                created_at=utc_now(),
                event_type=candidate["event_type"],
                direction=candidate["direction"],
                title=candidate["title"],
                message=candidate["message"],
                price=candidate["price"],
                conviction=candidate["conviction"],
                delivered=False,
                metadata_json={},
            )
            db.add(event)
            db.flush()

            delivered, delivery_message = send_email(event.title, event.message)
            event.delivered = delivered
            event.metadata_json = {"delivery": delivery_message}
            created_events.append({
                "id": event.id,
                "event_type": event.event_type,
                "title": event.title,
                "delivered": delivered,
            })

        db.commit()

    return {
        "symbol": symbol,
        "captured_at": snapshot.captured_at.isoformat(),
        "spot": snapshot.spot,
        "bias": snapshot.bias,
        "events": created_events,
    }


def collect_all() -> dict:
    symbols = [
        item.strip().upper()
        for item in os.getenv("SUPPORTED_SYMBOLS", "SPY,QQQ,IWM").split(",")
        if item.strip()
    ]
    results = []
    for symbol in symbols:
        try:
            results.append(collect_symbol(symbol))
        except Exception as exc:
            results.append({"symbol": symbol, "error": str(exc)})
    return {"results": results}
