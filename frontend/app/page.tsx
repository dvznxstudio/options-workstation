"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

type Tab = "roadmap" | "levels" | "flow" | "alerts";
type Level = { name:string; price:number; role:string; strength:number; side:"above"|"below"|"near" };
type Scenario = { id:string; name:string; direction:"bullish"|"bearish"|"neutral"; status:"forming"|"active"|"invalidated"; trigger_price:number; trigger:string; target1:number; target2?:number|null; invalidation:number; conviction:number; reasons:string[]; cautions:string[] };
type FlowPoint = { strike:number; net_gex:number; net_dex:number; call_oi:number; put_oi:number; call_volume:number; put_volume:number; volume_diff:number };
type Roadmap = { symbol:string; spot:number; source:string; is_live:boolean; updated_at:string; regime:string; bias:string; conviction:number; expected_move:{low:number;high:number;points:number;expiration?:string|null}; levels:Level[]; scenarios:Scenario[]; briefing:string; warnings:string[]; flow:FlowPoint[]; metrics:Record<string,number|string|null> };
type AlertRule = { id:string; name:string; type:"above"|"below"; price:number; enabled:boolean; fired:boolean };

const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "").replace(/\/$/, "");
const TOKEN_KEY = "ow_personal_token";
const ALERTS_KEY = "ow_personal_alerts";

function fmt(value:number|string|null|undefined):string {
  if (typeof value !== "number") return value == null ? "—" : String(value);
  const a = Math.abs(value);
  if (a >= 1_000_000_000) return `${(value/1_000_000_000).toFixed(2)}B`;
  if (a >= 1_000_000) return `${(value/1_000_000).toFixed(2)}M`;
  if (a >= 1_000) return `${(value/1_000).toFixed(1)}K`;
  return value.toFixed(2);
}

export default function Home() {
  const [token,setToken] = useState("");
  const [accessCode,setAccessCode] = useState("");
  const [loginError,setLoginError] = useState("");
  const [tab,setTab] = useState<Tab>("roadmap");
  const [symbol,setSymbol] = useState("SPY");
  const [data,setData] = useState<Roadmap|null>(null);
  const [error,setError] = useState("");
  const [loading,setLoading] = useState(false);
  const [alerts,setAlerts] = useState<AlertRule[]>([]);
  const [newAlertPrice,setNewAlertPrice] = useState("");
  const [newAlertType,setNewAlertType] = useState<"above"|"below">("above");

  useEffect(() => {
    setToken(window.localStorage.getItem(TOKEN_KEY) ?? "");
    const raw = window.localStorage.getItem(ALERTS_KEY);
    if (raw) { try { setAlerts(JSON.parse(raw)); } catch {} }
  }, []);

  useEffect(() => { window.localStorage.setItem(ALERTS_KEY, JSON.stringify(alerts)); }, [alerts]);

  const login = async (event:FormEvent) => {
    event.preventDefault();
    setLoginError("");
    if (!API_URL) { setLoginError("Vercel is missing NEXT_PUBLIC_API_URL."); return; }
    try {
      const response = await fetch(`${API_URL}/api/login`, {
        method:"POST",
        headers:{"Content-Type":"application/json"},
        body:JSON.stringify({access_code:accessCode})
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.detail ?? `Login failed (${response.status})`);
      window.localStorage.setItem(TOKEN_KEY, body.token);
      setToken(body.token);
      setAccessCode("");
    } catch (e) { setLoginError(e instanceof Error ? e.message : "Unable to sign in."); }
  };

  const logout = useCallback(() => {
    window.localStorage.removeItem(TOKEN_KEY);
    setToken(""); setData(null);
  }, []);

  const load = useCallback(async () => {
    if (!token || !API_URL) return;
    setLoading(true); setError("");
    try {
      const response = await fetch(`${API_URL}/api/roadmap/${symbol}`, { headers:{Authorization:`Bearer ${token}`}, cache:"no-store" });
      const body = await response.json().catch(() => ({}));
      if (response.status === 401) { logout(); throw new Error("Session expired. Sign in again."); }
      if (!response.ok) throw new Error(body.detail ?? `API error ${response.status}`);
      setData(body as Roadmap);
    } catch (e) { setError(e instanceof Error ? e.message : "Unable to load market data."); }
    finally { setLoading(false); }
  }, [token,symbol,logout]);

  useEffect(() => {
    if (!token) return;
    load();
    const id = window.setInterval(load, 120000);
    return () => window.clearInterval(id);
  }, [token,load]);

  useEffect(() => {
    if (!data) return;
    const next = alerts.map(rule => {
      if (!rule.enabled || rule.fired) return rule;
      const hit = rule.type === "above" ? data.spot >= rule.price : data.spot <= rule.price;
      if (!hit) return rule;
      if ("Notification" in window && Notification.permission === "granted") {
        new Notification(`${data.symbol} alert`, {body:`${rule.name}. Current price: ${data.spot.toFixed(2)}`});
      }
      return {...rule,fired:true};
    });
    if (JSON.stringify(next) !== JSON.stringify(alerts)) setAlerts(next);
  }, [data,alerts]);

  const sortedFlow = useMemo(() => data ? [...data.flow].sort((a,b)=>Math.abs(b.volume_diff)-Math.abs(a.volume_diff)) : [], [data]);

  if (!token) return (
    <main className="center loginShell">
      <form className="loginCard" onSubmit={login}>
        <span className="brandMark large">OW</span>
        <h1>Options Workstation</h1><p>Private personal access</p>
        <input type="password" placeholder="Access code" value={accessCode} onChange={e=>setAccessCode(e.target.value)} />
        {loginError && <div className="formError">{loginError}</div>}
        <button className="primary" type="submit">Open workstation</button>
        <small className="apiStatus">API: {API_URL || "not configured"}</small>
      </form>
    </main>
  );

  if (loading && !data) return <main className="center"><div className="loader"/><h1>Loading Trade GPS</h1></main>;
  if (!data) return <main className="center"><h1>Data connection issue</h1><p>{error}</p><button className="primary" onClick={load}>Try again</button><button className="ghost" onClick={logout}>Sign out</button></main>;

  const addAlert = () => {
    const price = Number(newAlertPrice); if (!Number.isFinite(price) || price<=0) return;
    setAlerts(v=>[...v,{id:crypto.randomUUID(),name:`${symbol} ${newAlertType} ${price.toFixed(2)}`,type:newAlertType,price,enabled:true,fired:false}]);
    setNewAlertPrice("");
  };

  return <main>
    <header className="topbar"><div className="brand"><span className="brandMark">OW</span><div><h1>Options Workstation</h1><p>Personal Trade GPS</p></div></div>
      <div className="headerActions"><select value={symbol} onChange={e=>setSymbol(e.target.value)}><option>SPY</option><option>QQQ</option><option>IWM</option></select><button className="refresh" onClick={load}>{loading?"…":"↻"}</button><button className="ghost compact" onClick={logout}>Exit</button></div>
    </header>
    {!data.is_live && <div className="warningBanner">Live data unavailable. Do not use fallback values for trading.</div>}
    <section className="hero"><div><span className="symbol">{data.symbol}</span><strong className="spot">${data.spot.toFixed(2)}</strong><p>{data.bias}</p></div><div className={`score ${data.is_live?"":"scoreOff"}`}><strong>{data.conviction}</strong><span>conviction</span></div></section>
    <nav className="tabs">{(["roadmap","levels","flow","alerts"] as Tab[]).map(x=><button key={x} className={tab===x?"active":""} onClick={()=>setTab(x)}>{x}</button>)}</nav>

    {tab==="roadmap" && <>
      <section className="metrics"><article><span>Regime</span><strong>{data.regime}</strong><small>{data.source}</small></article><article><span>Expected Low</span><strong>${data.expected_move.low.toFixed(2)}</strong></article><article><span>Expected High</span><strong>${data.expected_move.high.toFixed(2)}</strong></article><article><span>Updated</span><strong>{new Date(data.updated_at).toLocaleTimeString([], {hour:"2-digit",minute:"2-digit"})}</strong></article></section>
      <section className="panel briefing"><h2>Trade GPS briefing</h2><p>{data.briefing}</p></section>
      <section><h2>Scenario roadmap</h2><div className="scenarioGrid">{data.scenarios.map(s=><article className={`scenario ${s.direction}`} key={s.id}><div className="scenarioHead"><div><span>{s.status}</span><h3>{s.name}</h3></div><b>{s.conviction}</b></div><div className="trigger"><span>Activation trigger</span><p>{s.trigger}</p></div><div className="targets"><div><span>Target 1</span><strong>${s.target1.toFixed(2)}</strong></div><div><span>Target 2</span><strong>{s.target2?`$${s.target2.toFixed(2)}`:"—"}</strong></div><div><span>Invalidation</span><strong>${s.invalidation.toFixed(2)}</strong></div></div><div className="reasons">{s.reasons.map(r=><p key={r}>✓ {r}</p>)}{s.cautions.map(c=><p className="caution" key={c}>⚠ {c}</p>)}</div></article>)}</div></section>
    </>}

    {tab==="levels" && <section><h2>Institutional level map</h2><div className="metrics"><article><span>Net GEX</span><strong>{fmt(data.metrics.net_gex)}</strong></article><article><span>Net DEX</span><strong>{fmt(data.metrics.net_dex)}</strong></article><article><span>Put / Call OI</span><strong>{fmt(data.metrics.put_call_oi_ratio)}</strong></article><article><span>Put / Call Volume</span><strong>{fmt(data.metrics.put_call_volume_ratio)}</strong></article></div><div className="levels">{data.levels.map(l=><article className="level" key={`${l.name}-${l.price}`}><div><strong>{l.name}</strong><span>{l.role} · {l.side} spot</span></div><b>${l.price.toFixed(2)}</b><div className="bar"><i style={{width:`${l.strength}%`}}/></div></article>)}</div></section>}

    {tab==="flow" && <section><h2>Flow and concentration</h2><div className="tableWrap"><table><thead><tr><th>Strike</th><th>Net GEX</th><th>Call OI</th><th>Put OI</th><th>Vol Diff</th></tr></thead><tbody>{sortedFlow.slice(0,24).map(r=><tr key={r.strike}><td>${r.strike.toFixed(2)}</td><td>{fmt(r.net_gex)}</td><td>{fmt(r.call_oi)}</td><td>{fmt(r.put_oi)}</td><td className={r.volume_diff>=0?"positive":"negative"}>{fmt(r.volume_diff)}</td></tr>)}</tbody></table></div></section>}

    {tab==="alerts" && <section><h2>Personal alerts</h2><div className="panel alertBuilder"><div className="alertForm"><select value={newAlertType} onChange={e=>setNewAlertType(e.target.value as "above"|"below")}><option value="above">Price above</option><option value="below">Price below</option></select><input inputMode="decimal" placeholder="Price" value={newAlertPrice} onChange={e=>setNewAlertPrice(e.target.value)}/><button className="primary" onClick={addAlert}>Add alert</button></div><button className="ghost" onClick={()=>"Notification" in window && Notification.requestPermission()}>Enable browser notifications</button></div><div className="alertList">{alerts.length===0&&<p>No personal alerts yet.</p>}{alerts.map(a=><article className="alertRow" key={a.id}><div><strong>{a.name}</strong><span>{a.fired?"Triggered":a.enabled?"Watching":"Paused"}</span></div><div><button className="ghost compact" onClick={()=>setAlerts(v=>v.map(x=>x.id===a.id?{...x,enabled:!x.enabled,fired:false}:x))}>{a.enabled?"Pause":"Enable"}</button><button className="danger compact" onClick={()=>setAlerts(v=>v.filter(x=>x.id!==a.id))}>Delete</button></div></article>)}</div></section>}

    <section className="warnings">{data.warnings.map(w=><p key={w}>• {w}</p>)}</section><footer>Personal research tool. Wait for confirmation and use defined risk.</footer>
  </main>;
}
