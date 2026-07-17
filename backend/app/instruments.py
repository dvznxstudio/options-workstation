from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Instrument:
    symbol: str
    asset_class: str
    provider_symbol: str
    dataset: str | None
    benchmark: str | None
    description: str


INSTRUMENTS = {
    "SPY": Instrument("SPY", "etf", "SPY", "OPRA.PILLAR", "ES", "S&P 500 ETF"),
    "QQQ": Instrument("QQQ", "etf", "QQQ", "OPRA.PILLAR", "NQ", "Nasdaq-100 ETF"),
    "IWM": Instrument("IWM", "etf", "IWM", "OPRA.PILLAR", "RTY", "Russell 2000 ETF"),
    "ES": Instrument("ES", "future", "ES.v.0", "GLBX.MDP3", "SPY", "E-mini S&P 500"),
    "MES": Instrument("MES", "future", "MES.v.0", "GLBX.MDP3", "SPY", "Micro E-mini S&P 500"),
    "NQ": Instrument("NQ", "future", "NQ.v.0", "GLBX.MDP3", "QQQ", "E-mini Nasdaq-100"),
    "MNQ": Instrument("MNQ", "future", "MNQ.v.0", "GLBX.MDP3", "QQQ", "Micro E-mini Nasdaq-100"),
    "RTY": Instrument("RTY", "future", "RTY.v.0", "GLBX.MDP3", "IWM", "E-mini Russell 2000"),
    "M2K": Instrument("M2K", "future", "M2K.v.0", "GLBX.MDP3", "IWM", "Micro E-mini Russell 2000"),
    "CL": Instrument("CL", "future", "CL.v.0", "GLBX.MDP3", None, "WTI Crude Oil"),
    "GC": Instrument("GC", "future", "GC.v.0", "GLBX.MDP3", None, "Gold"),
}


def get_instrument(symbol: str) -> Instrument:
    normalized = symbol.upper().strip()
    if normalized not in INSTRUMENTS:
        raise ValueError(f"Unsupported symbol: {normalized}")
    return INSTRUMENTS[normalized]


def supported_symbols() -> list[str]:
    return sorted(INSTRUMENTS)
