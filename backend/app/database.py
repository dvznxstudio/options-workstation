from __future__ import annotations

from datetime import datetime, timezone
import os

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    Integer,
    JSON,
    String,
    Text,
    create_engine,
    select,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./options_workstation.db")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)
elif DATABASE_URL.startswith("postgresql://") and "+psycopg" not in DATABASE_URL:
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, pool_pre_ping=True, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class MarketSnapshot(Base):
    __tablename__ = "market_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(12), index=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    spot: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(160))
    regime: Mapped[str] = mapped_column(String(80))
    bias: Mapped[str] = mapped_column(Text)
    conviction: Mapped[int] = mapped_column(Integer)
    bullish_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bearish_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bullish_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    bearish_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    vwap: Mapped[float | None] = mapped_column(Float, nullable=True)
    ema9: Mapped[float | None] = mapped_column(Float, nullable=True)
    ema21: Mapped[float | None] = mapped_column(Float, nullable=True)
    opening_range_high: Mapped[float | None] = mapped_column(Float, nullable=True)
    opening_range_low: Mapped[float | None] = mapped_column(Float, nullable=True)
    call_wall: Mapped[float | None] = mapped_column(Float, nullable=True)
    put_wall: Mapped[float | None] = mapped_column(Float, nullable=True)
    plus_gex: Mapped[float | None] = mapped_column(Float, nullable=True)
    minus_gex: Mapped[float | None] = mapped_column(Float, nullable=True)
    upper_transition: Mapped[float | None] = mapped_column(Float, nullable=True)
    lower_transition: Mapped[float | None] = mapped_column(Float, nullable=True)
    expected_low: Mapped[float | None] = mapped_column(Float, nullable=True)
    expected_high: Mapped[float | None] = mapped_column(Float, nullable=True)
    net_gex: Mapped[float | None] = mapped_column(Float, nullable=True)
    net_dex: Mapped[float | None] = mapped_column(Float, nullable=True)
    payload: Mapped[dict] = mapped_column(JSON)


class ScenarioEvent(Base):
    __tablename__ = "scenario_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(12), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    direction: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(200))
    message: Mapped[str] = mapped_column(Text)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    conviction: Mapped[int | None] = mapped_column(Integer, nullable=True)
    delivered: Mapped[bool] = mapped_column(Boolean, default=False)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)


class OccOpenInterest(Base):
    __tablename__ = "occ_open_interest"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trade_date: Mapped[str] = mapped_column(String(10), index=True)
    symbol: Mapped[str] = mapped_column(String(12), index=True)
    expiration: Mapped[str] = mapped_column(String(10), index=True)
    option_type: Mapped[str] = mapped_column(String(4))
    strike: Mapped[float] = mapped_column(Float)
    open_interest: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(200))
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class DailyStructure(Base):
    __tablename__ = "daily_structures"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trade_date: Mapped[str] = mapped_column(String(10), index=True)
    symbol: Mapped[str] = mapped_column(String(12), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    spot_reference: Mapped[float | None] = mapped_column(Float, nullable=True)
    call_wall: Mapped[float | None] = mapped_column(Float, nullable=True)
    put_wall: Mapped[float | None] = mapped_column(Float, nullable=True)
    plus_gex: Mapped[float | None] = mapped_column(Float, nullable=True)
    minus_gex: Mapped[float | None] = mapped_column(Float, nullable=True)
    net_gex: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_call_oi: Mapped[int] = mapped_column(Integer)
    total_put_oi: Mapped[int] = mapped_column(Integer)
    payload: Mapped[dict] = mapped_column(JSON)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
