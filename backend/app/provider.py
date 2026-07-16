import pandas as pd
import yfinance as yf

SUPPORTED_SYMBOLS = {"SPY", "QQQ", "IWM"}

def validate_symbol(symbol: str) -> str:
    symbol = symbol.upper().strip()
    if symbol not in SUPPORTED_SYMBOLS:
        raise ValueError(f"Supported symbols: {', '.join(sorted(SUPPORTED_SYMBOLS))}")
    return symbol

def get_spot(symbol: str) -> float:
    ticker = yf.Ticker(symbol)
    history = ticker.history(period="1d", interval="1m", auto_adjust=False, prepost=True)
    if history.empty:
        history = ticker.history(period="5d", interval="1d", auto_adjust=False)
    closes = history.get("Close")
    if closes is None or closes.dropna().empty:
        raise RuntimeError(f"No current price returned for {symbol}.")
    return float(closes.dropna().iloc[-1])

def get_expirations(symbol: str, count: int = 2) -> list[str]:
    expirations = list(yf.Ticker(symbol).options)
    if not expirations:
        raise RuntimeError(f"No option expirations returned for {symbol}.")
    return expirations[:count]

def _frame(symbol: str, expiration: str, option_type: str, source: pd.DataFrame) -> pd.DataFrame:
    if source.empty:
        return pd.DataFrame()
    def col(name: str):
        return source[name] if name in source.columns else pd.Series(0.0, index=source.index)
    return pd.DataFrame({
        "symbol": symbol,
        "expiration": expiration,
        "option_type": option_type,
        "strike": col("strike"),
        "bid": col("bid"),
        "ask": col("ask"),
        "last": col("lastPrice"),
        "volume": col("volume"),
        "open_interest": col("openInterest"),
        "implied_volatility": col("impliedVolatility"),
    })

def get_chain(symbol: str, expirations: list[str]) -> pd.DataFrame:
    ticker = yf.Ticker(symbol)
    frames = []
    for expiration in expirations:
        chain = ticker.option_chain(expiration)
        calls = _frame(symbol, expiration, "call", chain.calls)
        puts = _frame(symbol, expiration, "put", chain.puts)
        if not calls.empty: frames.append(calls)
        if not puts.empty: frames.append(puts)
    if not frames:
        raise RuntimeError(f"No options chain returned for {symbol}.")
    return pd.concat(frames, ignore_index=True)
