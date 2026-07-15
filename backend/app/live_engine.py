from __future__ import annotations
from datetime import datetime, timezone
import math
import numpy as np
import pandas as pd
import yfinance as yf
from scipy.stats import norm

SUPPORTED={'SPY','QQQ','IWM'}

def _years(expiration:str)->float:
    expiry=datetime.strptime(expiration,'%Y-%m-%d').replace(hour=16,tzinfo=timezone.utc)
    return max((expiry-datetime.now(timezone.utc)).total_seconds(),60)/(365*24*3600)

def _greeks(spot:float,strike:float,t:float,iv:float,kind:str):
    iv=max(float(iv),.0001);t=max(float(t),1e-9)
    d1=(math.log(spot/strike)+(0.043-0.012+.5*iv*iv)*t)/(iv*math.sqrt(t))
    gamma=math.exp(-0.012*t)*norm.pdf(d1)/(spot*iv*math.sqrt(t))
    delta=math.exp(-0.012*t)*(norm.cdf(d1) if kind=='call' else norm.cdf(d1)-1)
    return float(delta),float(gamma)

def _centroid(frame:pd.DataFrame,weight:str):
    total=float(frame[weight].fillna(0).sum())
    return None if total<=0 else float((frame.strike*frame[weight].fillna(0)).sum()/total)

def build_live_roadmap(symbol:str='SPY')->dict:
    symbol=symbol.upper().strip()
    if symbol not in SUPPORTED: raise RuntimeError('Supported symbols: SPY, QQQ, IWM')
    ticker=yf.Ticker(symbol)
    hist=ticker.history(period='1d',interval='1m',auto_adjust=False)
    if hist.empty: hist=ticker.history(period='5d',interval='1d',auto_adjust=False)
    if hist.empty: raise RuntimeError('No current price returned')
    spot=float(hist['Close'].dropna().iloc[-1]); expirations=list(ticker.options)[:2]
    if not expirations: raise RuntimeError('No option expirations returned')
    rows=[]
    for expiration in expirations:
        oc=ticker.option_chain(expiration)
        for kind,frame in (('call',oc.calls),('put',oc.puts)):
            for _,r in frame.iterrows():
                rows.append({'expiration':expiration,'kind':kind,'strike':float(r.get('strike',0)),'bid':float(r.get('bid',0) or 0),'ask':float(r.get('ask',0) or 0),'last':float(r.get('lastPrice',0) or 0),'volume':float(r.get('volume',0) or 0),'oi':float(r.get('openInterest',0) or 0),'iv':float(r.get('impliedVolatility',0) or 0)})
    df=pd.DataFrame(rows)
    if df.empty: raise RuntimeError('No options chain returned')
    ds=[];gs=[]
    for r in df.itertuples(index=False):
        d,g=_greeks(spot,r.strike,_years(r.expiration),r.iv,r.kind);ds.append(d);gs.append(g)
    df['delta']=ds;df['gamma']=gs;df['mid']=np.where((df.bid>0)&(df.ask>0),(df.bid+df.ask)/2,df.last)
    sign=np.where(df.kind.eq('call'),1.,-1.);df['gex']=df.gamma*df.oi*100*spot*spot*.01*sign;df['dex']=df.delta*df.oi*100
    calls=df[df.kind.eq('call')];puts=df[df.kind.eq('put')]
    total=df.groupby('strike',as_index=False).agg(net_gex=('gex','sum'),net_dex=('dex','sum'),total_oi=('oi','sum'),total_volume=('volume','sum'))
    cg=calls.groupby('strike',as_index=False).agg(call_oi=('oi','sum'),call_volume=('volume','sum'))
    pg=puts.groupby('strike',as_index=False).agg(put_oi=('oi','sum'),put_volume=('volume','sum'))
    strikes=total.merge(cg,on='strike',how='left').merge(pg,on='strike',how='left').fillna(0).sort_values('strike')
    pos=strikes[strikes.net_gex>0];neg=strikes[strikes.net_gex<0]
    plus=float(pos.loc[pos.net_gex.idxmax(),'strike']) if not pos.empty else None
    minus=float(neg.loc[neg.net_gex.idxmin(),'strike']) if not neg.empty else None
    call_wall=float(calls.groupby('strike').gex.sum().idxmax()) if not calls.empty else None
    put_wall=float(puts.groupby('strike').gex.sum().idxmin()) if not puts.empty else None
    sg=np.sign(strikes.net_gex.to_numpy());trans=[float(strikes.iloc[i].strike) for i in range(1,len(strikes)) if sg[i]!=sg[i-1] and sg[i]!=0]
    lower=max([x for x in trans if x<=spot],default=None);upper=min([x for x in trans if x>=spot],default=None)
    near=df[df.expiration.eq(expirations[0])];atm=float(near.loc[(near.strike-spot).abs().idxmin(),'strike']);a=near[near.strike.eq(atm)]
    em=float(a.loc[a.kind.eq('call'),'mid'].sum()+a.loc[a.kind.eq('put'),'mid'].sum())
    call_gex=float(calls.gex.sum());put_gex=abs(float(puts.gex.sum()))
    regime='Call Dominated' if call_gex>put_gex*1.15 else 'Put Dominated' if put_gex>call_gex*1.15 else 'Balanced Gamma'
    bull=upper or spot;bear=lower or spot
    bs=45+(20 if regime=='Call Dominated' else 0)+(15 if plus and plus>spot else 0)
    dscr=42+(20 if regime=='Put Dominated' else 0)+(15 if minus and minus<spot else 0)
    bias=f'Bullish only above {bull:.2f}' if bs>dscr+7 else f'Bearish only below {bear:.2f}' if dscr>bs+7 else 'Balanced roadmap — wait for confirmation'
    levels=[]
    for n,p,role in [('Call Wall',call_wall,'Resistance / magnet'),('+GEX',plus,'Positive gamma concentration'),('Upper Transition',upper,'Bullish control line'),('Lower Transition',lower,'Bearish control line'),('-GEX',minus,'Negative gamma concentration'),('Put Wall',put_wall,'Support / acceleration')]:
        if p is not None: levels.append({'name':n,'price':round(p,2),'role':role,'strength':max(50,min(96,int(92-abs(p-spot)/max(spot,1)*1000))),'side':'near' if abs(p-spot)/spot<.001 else 'above' if p>spot else 'below'})
    metrics={'net_gex':round(float(strikes.net_gex.sum()),2),'net_dex':round(float(strikes.net_dex.sum()),2),'call_oi':int(calls.oi.sum()),'put_oi':int(puts.oi.sum()),'call_volume':int(calls.volume.sum()),'put_volume':int(puts.volume.sum()),'put_call_oi_ratio':round(float(puts.oi.sum()/calls.oi.sum()),3) if calls.oi.sum() else None,'put_call_volume_ratio':round(float(puts.volume.sum()/calls.volume.sum()),3) if calls.volume.sum() else None,'call_oi_centroid':round(_centroid(calls,'oi'),2) if _centroid(calls,'oi') else None,'put_oi_centroid':round(_centroid(puts,'oi'),2) if _centroid(puts,'oi') else None,'call_volume_centroid':round(_centroid(calls,'volume'),2) if _centroid(calls,'volume') else None,'put_volume_centroid':round(_centroid(puts,'volume'),2) if _centroid(puts,'volume') else None}
    flow=[]
    window=strikes[(strikes.strike>=spot*.94)&(strikes.strike<=spot*1.06)]
    for r in window.itertuples(index=False): flow.append({'strike':round(float(r.strike),2),'net_gex':round(float(r.net_gex),2),'net_dex':round(float(r.net_dex),2),'call_oi':round(float(r.call_oi),2),'put_oi':round(float(r.put_oi),2),'call_volume':round(float(r.call_volume),2),'put_volume':round(float(r.put_volume),2),'volume_diff':round(float(r.call_volume-r.put_volume),2)})
    return {'symbol':symbol,'spot':round(spot,2),'source':'Yahoo Finance via yfinance','is_live':True,'updated_at':datetime.now(timezone.utc).isoformat(),'regime':regime,'bias':bias,'conviction':min(90,max(bs,dscr)),'expected_move':{'low':round(spot-em,2),'high':round(spot+em,2),'points':round(em,2),'expiration':expirations[0]},'levels':levels,'briefing':f'{symbol} is in a {regime.lower()} structure. The expected range is {spot-em:.2f} to {spot+em:.2f}. Upside requires acceptance above {bull:.2f}; downside requires acceptance below {bear:.2f}.','scenarios':[{'id':'bull','name':'Bullish continuation','direction':'bullish','status':'forming','trigger_price':round(bull,2),'trigger':f'5-minute acceptance above {bull:.2f}, above VWAP, with improving call-side volume.','target1':round(plus or spot+em,2),'target2':round(call_wall or spot+em,2),'invalidation':round(bear,2),'conviction':min(90,bs),'reasons':['Positive structure must remain accepted above the control level.','Positive GEX and call wall define upside reaction zones.'],'cautions':['Do not chase directly into resistance.']},{'id':'bear','name':'Bearish breakdown','direction':'bearish','status':'forming','trigger_price':round(bear,2),'trigger':f'5-minute acceptance below {bear:.2f}, below VWAP, with expanding put-side volume.','target1':round(minus or spot-em,2),'target2':round(put_wall or spot-em,2),'invalidation':round(bull,2),'conviction':min(90,dscr),'reasons':['Negative structure requires acceptance below the control level.','Negative GEX and put wall define downside reaction zones.'],'cautions':['Positive gamma can suppress the first breakdown attempt.']}],'warnings':['Free options data may be delayed or incomplete.','Dealer positioning is estimated from open interest and modeled Greeks.','Conviction is a model score, not a measured probability of profit.'],'metrics':metrics,'flow':flow}
