from datetime import datetime, timezone
import re, time
from typing import Any
import pandas as pd
import requests
import yfinance as yf

SUPPORTED_SYMBOLS = {"SPY","QQQ","IWM"}
HEADERS = {
    "User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36",
    "Accept":"application/json,text/plain,*/*",
}
OCC_PATTERN = re.compile(r"^(?P<root>[A-Z]+)(?P<date>\d{6})(?P<type>[CP])(?P<strike>\d{8})$")

def validate_symbol(symbol: str) -> str:
    symbol=symbol.upper().strip()
    if symbol not in SUPPORTED_SYMBOLS:
        raise ValueError(f"Supported symbols: {', '.join(sorted(SUPPORTED_SYMBOLS))}")
    return symbol

def request_json(url: str, timeout: int=20) -> dict:
    last=None
    for attempt in range(3):
        try:
            r=requests.get(url,headers=HEADERS,timeout=timeout)
            r.raise_for_status()
            return r.json()
        except Exception as exc:
            last=exc
            if attempt<2: time.sleep(0.75*(attempt+1))
    raise RuntimeError(f"Request failed for {url}: {last}")

def parse_occ_symbol(contract: str):
    match=OCC_PATTERN.match(str(contract).replace(" ","").upper())
    if not match: return None
    expiration=datetime.strptime(match.group("date"),"%y%m%d").strftime("%Y-%m-%d")
    option_type="call" if match.group("type")=="C" else "put"
    strike=int(match.group("strike"))/1000.0
    return expiration,option_type,strike

def cboe_snapshot(symbol: str):
    payload=request_json(f"https://cdn.cboe.com/api/global/delayed_quotes/options/{symbol}.json")
    data=payload.get("data") or {}
    options=data.get("options") or []
    if not options: raise RuntimeError("Cboe returned no option contracts.")
    spot=next((float(x) for x in [data.get("current_price"),data.get("last_trade_price"),data.get("close")] if x not in (None,"")),None)
    if not spot: raise RuntimeError("Cboe returned no underlying price.")
    rows=[]
    for item in options:
        parsed=parse_occ_symbol(item.get("option") or item.get("symbol") or item.get("contract_symbol"))
        if not parsed: continue
        expiration,option_type,strike=parsed
        rows.append({
            "symbol":symbol,"expiration":expiration,"option_type":option_type,"strike":strike,
            "bid":item.get("bid",0),"ask":item.get("ask",0),
            "last":item.get("last_trade_price",item.get("last",0)),
            "volume":item.get("volume",0),"open_interest":item.get("open_interest",0),
            "implied_volatility":item.get("iv",item.get("implied_volatility",0)),
            "delta":item.get("delta",0),"gamma":item.get("gamma",0)})
    chain=pd.DataFrame(rows)
    if chain.empty: raise RuntimeError("Cboe contracts could not be normalized.")
    expirations=sorted(chain.expiration.unique().tolist())[:2]
    return spot,chain[chain.expiration.isin(expirations)].reset_index(drop=True),"Cboe delayed options"

def yahoo_direct_snapshot(symbol: str):
    base=f"https://query1.finance.yahoo.com/v7/finance/options/{symbol}"
    first=request_json(base)
    results=((first.get("optionChain") or {}).get("result") or [])
    if not results:
        raise RuntimeError(f"Yahoo direct returned no result: {(first.get('optionChain') or {}).get('error')}")
    root=results[0]; quote=root.get("quote") or {}
    spot=quote.get("regularMarketPrice") or quote.get("postMarketPrice") or quote.get("previousClose")
    expirations=root.get("expirationDates") or []
    if not spot or not expirations: raise RuntimeError("Yahoo direct returned incomplete quote/expiration data.")
    frames=[]
    for ts in expirations[:2]:
        payload=first if ts==expirations[0] else request_json(f"{base}?date={ts}")
        result=(((payload.get("optionChain") or {}).get("result") or [{}])[0])
        blocks=result.get("options") or []
        if not blocks: continue
        block=blocks[0]
        expiration=datetime.fromtimestamp(int(ts),tz=timezone.utc).strftime("%Y-%m-%d")
        for option_type,contracts in (("call",block.get("calls") or []),("put",block.get("puts") or [])):
            rows=[]
            for item in contracts:
                rows.append({
                    "symbol":symbol,"expiration":expiration,"option_type":option_type,
                    "strike":item.get("strike",0),"bid":item.get("bid",0),"ask":item.get("ask",0),
                    "last":item.get("lastPrice",0),"volume":item.get("volume",0),
                    "open_interest":item.get("openInterest",0),
                    "implied_volatility":item.get("impliedVolatility",0),"delta":0,"gamma":0})
            if rows: frames.append(pd.DataFrame(rows))
    if not frames: raise RuntimeError("Yahoo direct returned no normalized contracts.")
    return float(spot),pd.concat(frames,ignore_index=True),"Yahoo direct options"

def yfinance_snapshot(symbol: str):
    ticker=yf.Ticker(symbol)
    history=ticker.history(period="5d",interval="1d",auto_adjust=False)
    if history.empty or history["Close"].dropna().empty:
        raise RuntimeError("yfinance returned no price.")
    spot=float(history["Close"].dropna().iloc[-1])
    expirations=list(ticker.options)[:2]
    if not expirations: raise RuntimeError("yfinance returned no expirations.")
    frames=[]
    for expiration in expirations:
        chain=ticker.option_chain(expiration)
        for option_type,source in (("call",chain.calls),("put",chain.puts)):
            if source.empty: continue
            frames.append(pd.DataFrame({
                "symbol":symbol,"expiration":expiration,"option_type":option_type,
                "strike":source.get("strike",0),"bid":source.get("bid",0),"ask":source.get("ask",0),
                "last":source.get("lastPrice",0),"volume":source.get("volume",0),
                "open_interest":source.get("openInterest",0),
                "implied_volatility":source.get("impliedVolatility",0),"delta":0,"gamma":0}))
    if not frames: raise RuntimeError("yfinance returned no contracts.")
    return spot,pd.concat(frames,ignore_index=True),"Yahoo Finance via yfinance"

def get_market_snapshot(symbol: str):
    symbol=validate_symbol(symbol)
    attempts=[]
    for name,provider in [("cboe",cboe_snapshot),("yahoo_direct",yahoo_direct_snapshot),("yfinance",yfinance_snapshot)]:
        started=time.monotonic()
        try:
            spot,chain,source=provider(symbol)
            attempts.append({"provider":name,"ok":True,"elapsed_ms":round((time.monotonic()-started)*1000),
                             "contracts":int(len(chain)),"message":source})
            return spot,chain,source,attempts
        except Exception as exc:
            attempts.append({"provider":name,"ok":False,"elapsed_ms":round((time.monotonic()-started)*1000),
                             "contracts":0,"message":str(exc)})
    raise RuntimeError("All market-data providers failed. " + " | ".join(f"{a['provider']}: {a['message']}" for a in attempts))
