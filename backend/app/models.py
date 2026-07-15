from typing import Literal
from pydantic import BaseModel

class Level(BaseModel):
    name: str
    price: float
    role: str
    strength: int

class Scenario(BaseModel):
    id: str
    name: str
    direction: Literal["bullish", "bearish", "neutral"]
    status: Literal["forming", "active", "invalidated"]
    trigger: str
    target1: float
    target2: float | None = None
    invalidation: float
    confidence: int
    reasons: list[str]
    caution: list[str]

class ExpectedMove(BaseModel):
    low: float
    high: float

class MarketRoadmap(BaseModel):
    symbol: str
    spot: float
    regime: str
    bias: str
    confidence: int
    updatedAt: str
    expectedMove: ExpectedMove
    levels: list[Level]
    scenarios: list[Scenario]
    briefing: str
