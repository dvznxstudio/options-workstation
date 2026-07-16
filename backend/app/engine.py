from datetime import datetime, timezone
from time import monotonic
from .analytics import enrich_chain, compute_structure
from .models import MarketRoadmap
from .provider import get_spot, get_expirations, get_chain, validate_symbol

CACHE_SECONDS=120
_CACHE={}

def side(price, spot):
    return "near" if abs(price-spot)/max(spot,1)<0.001 else ("above" if price>spot else "below")

def strength(price, spot, base):
    return min(99, base + max(0,18-int(abs(price-spot)/max(spot,1)*1000)))

def build_live(symbol: str) -> MarketRoadmap:
    symbol=validate_symbol(symbol); spot=get_spot(symbol)
    chain=enrich_chain(get_chain(symbol,get_expirations(symbol,2)),spot)
    if chain.empty: raise RuntimeError("No usable option contracts.")
    st=compute_structure(chain,spot); exp=st["expected_move"]
    upper,lower=st["upper_transition"],st["lower_transition"]
    up=max(x for x in [spot,upper] if x is not None); down=min(x for x in [spot,lower] if x is not None)
    bull,bear=42,38; br=[]; sr=[]; bc=[]; sc=[]
    if upper is not None: br.append("Spot is above the positive transition." if spot>=upper else "Positive transition is the upside control line."); bull += 22 if spot>=upper else 0
    if st["plus_gex"] is not None and st["plus_gex"]>spot: bull+=18; br.append("Positive GEX remains overhead as a target.")
    if st["call_wall"] is not None and st["call_wall"]>spot: bull+=15; br.append("Call wall defines resistance.")
    if lower is not None: sr.append("Spot is below the lower transition." if spot<=lower else "Lower transition is the downside control line."); bear += 22 if spot<=lower else 0
    if st["minus_gex"] is not None and st["minus_gex"]<spot: bear+=18; sr.append("Negative GEX lies below spot.")
    if st["put_wall"] is not None and st["put_wall"]<spot: bear+=15; sr.append("Put wall defines support or acceleration.")
    if st["regime"]=="Call Dominated": bull+=16; br.append("Modeled gamma is call dominated."); sc.append("Call gamma may suppress downside volatility.")
    elif st["regime"]=="Put Dominated": bear+=16; sr.append("Modeled gamma is put dominated."); bc.append("Put gamma increases downside risk.")
    bull,bear=min(92,bull),min(92,bear)
    if bull>=bear+8: bias=f"Bullish only with acceptance above {up:.2f}"; conviction=bull
    elif bear>=bull+8: bias=f"Bearish only with acceptance below {down:.2f}"; conviction=bear
    else: bias="Balanced roadmap — wait for transition confirmation"; conviction=max(bull,bear)
    levels=[]
    for name,price,role,base in [
      ("Call Wall",st["call_wall"],"Resistance / magnet",72),("+GEX",st["plus_gex"],"Positive gamma concentration",74),
      ("Upper Transition",upper,"Bullish control line",68),("Lower Transition",lower,"Bearish control line",68),
      ("-GEX",st["minus_gex"],"Negative gamma concentration",74),("Put Wall",st["put_wall"],"Support / acceleration",72)]:
        if price is not None: levels.append({"name":name,"price":round(float(price),2),"role":role,"strength":strength(float(price),spot,base),"side":side(float(price),spot)})
    flow=[]
    ss=st["strikes"][(st["strikes"].strike>=spot*0.94)&(st["strikes"].strike<=spot*1.06)]
    for r in ss.itertuples(index=False):
        flow.append({"strike":round(float(r.strike),2),"net_gex":round(float(r.net_gex),2),"net_dex":round(float(r.net_dex),2),
        "call_oi":float(r.call_oi),"put_oi":float(r.put_oi),"call_volume":float(r.call_volume),"put_volume":float(r.put_volume),
        "volume_diff":float(r.call_volume-r.put_volume)})
    metrics={k:(round(v,3) if isinstance(v,float) else v) for k,v in {
      "net_gex":st["net_gex"],"net_dex":st["net_dex"],"call_oi":st["call_oi"],"put_oi":st["put_oi"],
      "call_volume":st["call_volume"],"put_volume":st["put_volume"],"put_call_oi_ratio":st["put_call_oi_ratio"],
      "put_call_volume_ratio":st["put_call_volume_ratio"],"call_oi_centroid":st["call_oi_centroid"],
      "put_oi_centroid":st["put_oi_centroid"],"call_volume_centroid":st["call_volume_centroid"],
      "put_volume_centroid":st["put_volume_centroid"]}.items()}
    return MarketRoadmap.model_validate({
      "symbol":symbol,"spot":round(spot,2),"source":"Yahoo Finance via yfinance","is_live":True,
      "updated_at":datetime.now(timezone.utc).isoformat(),"regime":st["regime"],"bias":bias,"conviction":conviction,
      "expected_move":{"low":round(exp["low"],2),"high":round(exp["high"],2),"points":round(exp["points"],2),"expiration":exp["expiration"]},
      "levels":levels,
      "scenarios":[
        {"id":"bullish-continuation","name":"Bullish continuation","direction":"bullish","status":"forming","trigger_price":round(up,2),
         "trigger":f"5-minute acceptance above {up:.2f}, above VWAP, with improving call participation.",
         "target1":round(float(st["plus_gex"] or exp["high"]),2),"target2":round(float(st["call_wall"] or exp["high"]),2),
         "invalidation":round(down,2),"conviction":bull,"reasons":br or ["No strong bullish alignment yet."],"cautions":bc or ["Avoid chasing into resistance."]},
        {"id":"bearish-breakdown","name":"Bearish breakdown","direction":"bearish","status":"forming","trigger_price":round(down,2),
         "trigger":f"5-minute acceptance below {down:.2f}, below VWAP, with expanding put participation.",
         "target1":round(float(st["minus_gex"] or exp["low"]),2),"target2":round(float(st["put_wall"] or exp["low"]),2),
         "invalidation":round(up,2),"conviction":bear,"reasons":sr or ["No strong bearish alignment yet."],"cautions":sc or ["Avoid chasing after expansion."]}],
      "briefing":f"{symbol} is in a {st['regime'].lower()} structure. Expected range: {exp['low']:.2f} to {exp['high']:.2f}. Upside requires acceptance above {up:.2f}; downside requires acceptance below {down:.2f}.",
      "warnings":["Free options data may be delayed or incomplete.","Dealer positioning is estimated from public open interest and modeled Greeks.","Conviction is a model score, not a measured probability."],
      "flow":flow,"metrics":metrics})

def fallback(symbol: str, error: Exception) -> MarketRoadmap:
    return MarketRoadmap.model_validate({"symbol":symbol,"spot":600.0,"source":"Fallback","is_live":False,
      "updated_at":datetime.now(timezone.utc).isoformat(),"regime":"Data Unavailable",
      "bias":"Live feed unavailable — do not use for trading","conviction":0,
      "expected_move":{"low":596.0,"high":604.0,"points":4.0,"expiration":None},
      "levels":[],"scenarios":[{"id":"data-warning","name":"Waiting for live data","direction":"neutral","status":"forming",
      "trigger_price":600.0,"trigger":"Restore the market-data connection.","target1":600.0,"target2":None,
      "invalidation":600.0,"conviction":0,"reasons":["No usable live chain returned."],"cautions":[str(error)]}],
      "briefing":"The API is online, but the free market-data provider is unavailable.","warnings":[str(error)],"flow":[],"metrics":{}})

def get_roadmap(symbol="SPY"):
    symbol=symbol.upper().strip(); cached=_CACHE.get(symbol)
    if cached and monotonic()-cached[0]<CACHE_SECONDS: return cached[1]
    try: result=build_live(symbol)
    except Exception as error: result=fallback(symbol,error)
    _CACHE[symbol]=(monotonic(),result)
    return result
