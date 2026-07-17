from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
import os
from typing import Any

import pandas as pd
import requests

from .instruments import get_instrument


class MarketDataProvider(ABC):
    name: str

    @abstractmethod
    def available(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def bars(self, symbol: str, interval: str = "5m", lookback_days: int = 5) -> pd.DataFrame:
        raise NotImplementedError


class DatabentoProvider(MarketDataProvider):
    name = "Databento"

    def available(self) -> bool:
        return bool(os.getenv("DATABENTO_API_KEY"))

    def bars(self, symbol: str, interval: str = "5m", lookback_days: int = 5) -> pd.DataFrame:
        if not self.available():
            raise RuntimeError("DATABENTO_API_KEY is not configured.")

        import databento as db

        instrument = get_instrument(symbol)
        if instrument.dataset is None:
            raise RuntimeError(f"No Databento dataset configured for {symbol}.")

        schema_map = {
            "1m": "ohlcv-1m",
            "5m": "ohlcv-1m",
            "1h": "ohlcv-1h",
            "1d": "ohlcv-1d",
        }
        schema = schema_map.get(interval, "ohlcv-1m")
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=max(lookback_days, 1))

        client = db.Historical(os.environ["DATABENTO_API_KEY"])
        store = client.timeseries.get_range(
            dataset=instrument.dataset,
            schema=schema,
            symbols=[instrument.provider_symbol],
            stype_in="continuous",
            start=start,
            end=end,
        )
        frame = store.to_df().reset_index()
        if frame.empty:
            raise RuntimeError(f"Databento returned no bars for {symbol}.")

        rename = {
            "ts_event": "timestamp",
            "open": "open",
            "high": "high",
            "low": "low",
            "close": "close",
            "volume": "volume",
        }
        frame = frame.rename(columns=rename)
        required = ["timestamp", "open", "high", "low", "close", "volume"]
        missing = [column for column in required if column not in frame.columns]
        if missing:
            raise RuntimeError(f"Databento response missing columns: {missing}")

        result = frame[required].copy()
        result["timestamp"] = pd.to_datetime(result["timestamp"], utc=True)
        for column in ["open", "high", "low", "close", "volume"]:
            result[column] = pd.to_numeric(result[column], errors="coerce")
        result = result.dropna(subset=["open", "high", "low", "close"])

        if interval == "5m" and not result.empty:
            result = (
                result.set_index("timestamp")
                .resample("5min")
                .agg({
                    "open": "first",
                    "high": "max",
                    "low": "min",
                    "close": "last",
                    "volume": "sum",
                })
                .dropna(subset=["open", "high", "low", "close"])
                .reset_index()
            )
        return result


class YahooChartProvider(MarketDataProvider):
    name = "Yahoo Chart"

    def available(self) -> bool:
        return True

    def bars(self, symbol: str, interval: str = "5m", lookback_days: int = 5) -> pd.DataFrame:
        instrument = get_instrument(symbol)
        yahoo_symbols = {
            "ES": "ES=F", "MES": "MES=F", "NQ": "NQ=F", "MNQ": "MNQ=F",
            "RTY": "RTY=F", "M2K": "M2K=F", "CL": "CL=F", "GC": "GC=F",
        }
        provider_symbol = yahoo_symbols.get(symbol.upper(), instrument.provider_symbol)

        yahoo_interval = {"1m": "1m", "5m": "5m", "1h": "60m", "1d": "1d"}.get(interval, "5m")
        range_value = "5d" if interval in {"1m", "5m"} else ("1mo" if interval == "1h" else "1y")
        url = (
            f"https://query1.finance.yahoo.com/v8/finance/chart/{provider_symbol}"
            f"?range={range_value}&interval={yahoo_interval}&includePrePost=true"
        )
        response = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        results = ((payload.get("chart") or {}).get("result") or [])
        if not results:
            raise RuntimeError(f"Yahoo returned no chart data for {symbol}.")

        result = results[0]
        timestamps = result.get("timestamp") or []
        quotes = ((result.get("indicators") or {}).get("quote") or [])
        if not timestamps or not quotes:
            raise RuntimeError(f"Yahoo returned no bars for {symbol}.")

        quote = quotes[0]
        frame = pd.DataFrame({
            "timestamp": pd.to_datetime(timestamps, unit="s", utc=True),
            "open": quote.get("open", []),
            "high": quote.get("high", []),
            "low": quote.get("low", []),
            "close": quote.get("close", []),
            "volume": quote.get("volume", []),
        })
        for column in ["open", "high", "low", "close", "volume"]:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        return frame.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)


PROVIDERS = [DatabentoProvider(), YahooChartProvider()]


def get_bars(symbol: str, interval: str = "5m", lookback_days: int = 5) -> tuple[pd.DataFrame, str, list[dict[str, Any]]]:
    attempts = []
    for provider in PROVIDERS:
        if not provider.available():
            attempts.append({"provider": provider.name, "ok": False, "message": "Not configured"})
            continue
        try:
            frame = provider.bars(symbol, interval=interval, lookback_days=lookback_days)
            attempts.append({"provider": provider.name, "ok": True, "rows": len(frame)})
            return frame, provider.name, attempts
        except Exception as exc:
            attempts.append({"provider": provider.name, "ok": False, "message": str(exc)})
    raise RuntimeError(f"All bar providers failed: {attempts}")
