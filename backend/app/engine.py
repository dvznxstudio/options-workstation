from datetime import datetime, timezone
from .models import MarketRoadmap

def build_roadmap(symbol: str = "SPY") -> MarketRoadmap:
    spot = 603.42
    positive_transition = 602.50
    lower_control = 601.80
    plus_gex = 606.00
    call_wall = 608.00
    put_wall = 598.00
    above_control = spot > positive_transition

    payload = {
        "symbol": symbol.upper(),
        "spot": spot,
        "regime": "Positive Gamma",
        "bias": "Bullish above 602.50" if above_control else "Neutral below control",
        "confidence": 71 if above_control else 54,
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "expectedMove": {"low": 598.80, "high": 607.90},
        "briefing": (
            "Price is holding above the positive transition while the strongest positive gamma "
            "remains overhead. The highest-quality setup is continuation only after acceptance "
            "above 604.20. A loss of 601.80 changes the roadmap."
        ),
        "levels": [
            {"name": "Call Wall", "price": call_wall, "role": "Resistance / magnet", "strength": 92},
            {"name": "+GEX", "price": plus_gex, "role": "Primary upside target", "strength": 88},
            {"name": "Positive Transition", "price": positive_transition, "role": "Bullish control line", "strength": 84},
            {"name": "Put Wall", "price": put_wall, "role": "Support / acceleration", "strength": 90}
        ],
        "scenarios": [
            {
                "id": "bull-continuation",
                "name": "Bullish continuation",
                "direction": "bullish",
                "status": "forming",
                "trigger": "5-minute acceptance above 604.20 with call-volume expansion",
                "target1": plus_gex,
                "target2": call_wall,
                "invalidation": positive_transition,
                "confidence": 72,
                "reasons": [
                    "Spot is above positive transition",
                    "Positive GEX target remains overhead",
                    "Call OI centroid is above spot"
                ],
                "caution": ["Do not chase directly into the call wall"]
            },
            {
                "id": "bear-breakdown",
                "name": "Failed structure breakdown",
                "direction": "bearish",
                "status": "forming",
                "trigger": f"Loss of {lower_control:.2f} with put-volume differential expanding",
                "target1": 600.00,
                "target2": put_wall,
                "invalidation": 603.00,
                "confidence": 61,
                "reasons": [
                    "Break would place price below the control zone",
                    "Put wall provides the next major concentration"
                ],
                "caution": ["Positive gamma may initially suppress volatility"]
            }
        ]
    }
    return MarketRoadmap.model_validate(payload)
