from datetime import datetime, timezone
import math, numpy as np, pandas as pd

SQRT_TWO = math.sqrt(2.0)
SQRT_TWO_PI = math.sqrt(2.0 * math.pi)

def normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / SQRT_TWO))

def normal_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / SQRT_TWO_PI

def years_to_expiration(expiration: str) -> float:
    expiry = datetime.strptime(expiration, "%Y-%m-%d").replace(hour=16, tzinfo=timezone.utc)
    return max((expiry - datetime.now(timezone.utc)).total_seconds(), 60.0) / (365 * 24 * 3600)

def greeks(spot: float, strike: float, t: float, iv: float, option_type: str,
           rate: float = 0.043, dividend_yield: float = 0.012) -> tuple[float, float]:
    spot, strike, t, iv = max(spot,1e-9), max(strike,1e-9), max(t,1e-9), max(iv,1e-4)
    d1 = (math.log(spot/strike) + (rate-dividend_yield+0.5*iv*iv)*t) / (iv*math.sqrt(t))
    gamma = math.exp(-dividend_yield*t) * normal_pdf(d1) / (spot*iv*math.sqrt(t))
    delta = math.exp(-dividend_yield*t) * (normal_cdf(d1) if option_type=="call" else normal_cdf(d1)-1.0)
    return float(delta), float(gamma)

def enrich_chain(chain: pd.DataFrame, spot: float) -> pd.DataFrame:
    df = chain.copy()
    for c in ["strike","bid","ask","last","volume","open_interest","implied_volatility"]:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    df = df[(df["strike"]>0) & (df["implied_volatility"]>0)].copy()
    deltas, gammas = [], []
    for r in df.itertuples(index=False):
        d, g = greeks(spot, float(r.strike), years_to_expiration(str(r.expiration)),
                      float(r.implied_volatility), str(r.option_type))
        deltas.append(d); gammas.append(g)
    df["delta"], df["gamma"] = deltas, gammas
    df["mid"] = np.where((df["bid"]>0)&(df["ask"]>0),(df["bid"]+df["ask"])/2,df["last"])
    sign = np.where(df["option_type"].eq("call"),1.0,-1.0)
    df["gex"] = df["gamma"]*df["open_interest"]*100*spot*spot*0.01*sign
    df["dex"] = df["delta"]*df["open_interest"]*100
    return df

def aggregate(chain: pd.DataFrame) -> pd.DataFrame:
    calls, puts = chain[chain.option_type=="call"], chain[chain.option_type=="put"]
    total = chain.groupby("strike",as_index=False).agg(net_gex=("gex","sum"),net_dex=("dex","sum"),
        total_oi=("open_interest","sum"),total_volume=("volume","sum"))
    cg = calls.groupby("strike",as_index=False).agg(call_oi=("open_interest","sum"),call_volume=("volume","sum"))
    pg = puts.groupby("strike",as_index=False).agg(put_oi=("open_interest","sum"),put_volume=("volume","sum"))
    return total.merge(cg,on="strike",how="left").merge(pg,on="strike",how="left").fillna(0).sort_values("strike")

def expected_move(chain: pd.DataFrame, spot: float) -> dict:
    exps = sorted(chain.expiration.dropna().unique().tolist())
    if not exps: return {"low":spot,"high":spot,"points":0.0,"expiration":None}
    exp = exps[0]; sub = chain[chain.expiration==exp].copy()
    strike = float(sub.loc[(sub.strike-spot).abs().idxmin(),"strike"])
    atm = sub[sub.strike==strike]
    points = max(float(atm.loc[atm.option_type=="call","mid"].sum()) +
                 float(atm.loc[atm.option_type=="put","mid"].sum()), 0.0)
    return {"low":spot-points,"high":spot+points,"points":points,"expiration":exp}

def transitions(strikes: pd.DataFrame, spot: float):
    ordered = strikes.sort_values("strike"); signs = np.sign(ordered.net_gex.to_numpy()); vals=[]
    for i in range(1,len(ordered)):
        if signs[i] != signs[i-1] and signs[i] != 0: vals.append(float(ordered.iloc[i].strike))
    below=[x for x in vals if x<=spot]; above=[x for x in vals if x>=spot]
    return (max(below) if below else None, min(above) if above else None)

def centroid(df: pd.DataFrame, weight_col: str):
    w = pd.to_numeric(df[weight_col],errors="coerce").fillna(0.0); total=float(w.sum())
    return None if total<=0 else float((df.strike*w).sum()/total)

def compute_structure(chain: pd.DataFrame, spot: float) -> dict:
    s = aggregate(chain); calls=chain[chain.option_type=="call"]; puts=chain[chain.option_type=="put"]
    pos=s[s.net_gex>0]; neg=s[s.net_gex<0]
    plus=float(pos.loc[pos.net_gex.idxmax(),"strike"]) if not pos.empty else None
    minus=float(neg.loc[neg.net_gex.idxmin(),"strike"]) if not neg.empty else None
    call_wall=float(calls.groupby("strike").gex.sum().idxmax()) if not calls.empty else None
    pg=puts.groupby("strike").gex.sum(); put_wall=float(pg.idxmin()) if not pg.empty else None
    lower, upper = transitions(s, spot)
    cg=float(calls.gex.sum()); pgabs=abs(float(puts.gex.sum()))
    regime="Call Dominated" if cg>pgabs*1.15 else ("Put Dominated" if pgabs>cg*1.15 else "Balanced Gamma")
    coi,poi=int(calls.open_interest.sum()),int(puts.open_interest.sum())
    cv,pv=int(calls.volume.sum()),int(puts.volume.sum())
    return {"strikes":s,"net_gex":float(s.net_gex.sum()),"net_dex":float(s.net_dex.sum()),
      "plus_gex":plus,"minus_gex":minus,"call_wall":call_wall,"put_wall":put_wall,
      "lower_transition":lower,"upper_transition":upper,"regime":regime,
      "expected_move":expected_move(chain,spot),"call_oi":coi,"put_oi":poi,
      "call_volume":cv,"put_volume":pv,"put_call_oi_ratio":poi/coi if coi else None,
      "put_call_volume_ratio":pv/cv if cv else None,
      "call_oi_centroid":centroid(calls,"open_interest"),
      "put_oi_centroid":centroid(puts,"open_interest"),
      "call_volume_centroid":centroid(calls,"volume"),
      "put_volume_centroid":centroid(puts,"volume")}
