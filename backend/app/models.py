from typing import Literal
from pydantic import BaseModel

class Level(BaseModel):
    name: str
    price: float
    role: str
    strength: int
    side: Literal["above", "below", "near"]

class Scenario(BaseModel):
    id: str
    name: str
    direction: Literal["bullish", "bearish", "neutral"]
    status: Literal["forming", "active", "invalidated"]
    trigger_price: float
    trigger: str
    target1: float
    target2: float | None = None
    invalidation: float
    conviction: int
    reasons: list[str]
    cautions: list[str]

class ExpectedMove(BaseModel):
    low: float
    high: float
    points: float
    expiration: str | None = None

class FlowPoint(BaseModel):
    strike: float
    net_gex: float
    net_dex: float
    call_oi: float
    put_oi: float
    call_volume: float
    put_volume: float
    volume_diff: float

class MarketRoadmap(BaseModel):
    symbol: str
    spot: float
    source: str
    is_live: bool
    updated_at: str
    regime: str
    bias: str
    conviction: int
    expected_move: ExpectedMove
    levels: list[Level]
    scenarios: list[Scenario]
    briefing: str
    warnings: list[str]
    flow: list[FlowPoint]
    metrics: dict[str, float | int | str | None]
