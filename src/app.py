"""
Angel One Webhook Server
────────────────────────
Pages:
  /           → Dashboard
  /option     → NIFTY Option selector
  /login      → Manual token refresh

API:
  POST /webhook          → TradingView alert receiver
  GET  /api/status       → Bot status JSON
  GET  /api/trades       → Today's trade log
  POST /api/set_option   → Set active option instrument
  POST /api/manual_order → Manual BUY/SELL from dashboard
  GET  /api/search       → Search option strikes
  GET  /api/token_status → Check token validity
"""

import os
import json
import logging
from datetime import datetime
from pathlib import Path
from flask import Flask, request, jsonify, render_template_string
from zoneinfo import ZoneInfo

from src.angel_client import AngelClient
from src.position_tracker import PositionTracker

logger = logging.getLogger(__name__)
IST    = ZoneInfo("Asia/Kolkata")

app     = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", "changeme")

# Singletons — initialised at startup
DRY_RUN   = os.environ.get("DRY_RUN", "true").lower() == "true"
TV_SECRET = os.environ.get("TV_SECRET", "")
LOT_SIZE  = int(os.environ.get("LOT_SIZE", 25))

client  = AngelClient()
tracker = PositionTracker()

# Active instrument (set via /option page or env)
active = {
    "symbol_token":   os.environ.get("SYMBOL_TOKEN", ""),
    "trading_symbol": os.environ.get("TRADING_SYMBOL", ""),
    "strike":         os.environ.get("STRIKE", ""),
    "option_type":    os.environ.get("OPTION_TYPE", "CE"),
    "expiry":         os.environ.get("EXPIRY", ""),
    "lotsize":        LOT_SIZE,
}

TRADE_LOG = Path("logs/trades.json")

# ─────────────────────────────────────────────────────────────────────────────
# DASHBOARD
# ─────────────────────────────────────────────────────────────────────────────
DASH_HTML = """<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Angel One Webhook</title>
<style>
:root{--bg:#0d0f14;--sf:#161920;--sf2:#1c2030;--br:#1e2330;
  --g:#00e676;--r:#ff5252;--y:#ffd740;--b:#3b82f6;--o:#f97316;
  --tx:#e8eaf0;--mu:#6b7280;--fn:'JetBrains Mono','Fira Code',monospace;}
*{box-sizing:border-box;margin:0;padding:0;}
body{background:var(--bg);color:var(--tx);font-family:var(--fn);font-size:13px;}
header{padding:14px 24px;border-bottom:1px solid var(--br);display:flex;align-items:center;gap:12px;flex-wrap:wrap;}
header h1{font-size:16px;letter-spacing:2px;color:var(--o);}
.badge{padding:3px 10px;border-radius:4px;font-size:11px;font-weight:700;letter-spacing:1px;}
.live{background:#00e67622;color:var(--g);border:1px solid var(--g);}
.dry{background:#ffd74022;color:var(--y);border:1px solid var(--y);}
.warn{background:#f9731622;color:var(--o);border:1px solid var(--o);}
.stopped{background:#ff525222;color:var(--r);border:1px solid var(--r);}
main{max-width:1100px;margin:0 auto;padding:24px;}
.active-opt{background:var(--sf);border:1px solid var(--br);border-radius:8px;padding:16px 20px;margin-bottom:20px;}
.active-opt .lbl{font-size:10px;color:var(--mu);letter-spacing:1px;text-transform:uppercase;margin-bottom:6px;}
.active-opt .sym{font-size:20px;font-weight:700;color:var(--y);}
.active-opt .meta{font-size:12px;color:var(--mu);margin-top:4px;}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:20px;}
.card{background:var(--sf);border:1px solid var(--br);border-radius:8px;padding:14px 16px;}
.lbl{font-size:10px;color:var(--mu);letter-spacing:1px;text-transform:uppercase;margin-bottom:5px;}
.val{font-size:20px;font-weight:700;}
.gn{color:var(--g);}.rd{color:var(--r);}.yw{color:var(--y);}
.controls{display:flex;gap:10px;margin-bottom:20px;flex-wrap:wrap;}
.btn{padding:8px 18px;border-radius:6px;font-family:var(--fn);font-size:13px;font-weight:700;
  cursor:pointer;border:none;text-decoration:none;display:inline-block;}
.btn-g{background:var(--g);color:#000;}.btn-r{background:var(--r);color:#fff;}
.btn-b{background:var(--b);color:#fff;}.btn-o{background:var(--sf2);color:var(--tx);border:1px solid var(--br);}
.token-box{background:var(--sf);border:1px solid var(--br);border-radius:8px;padding:14px 18px;margin-bottom:20px;}
.token-ok{color:var(--g);}.token-warn{color:var(--y);}
table{width:100%;border-collapse:collapse;}
th{text-align:left;font-size:10px;color:var(--mu);letter-spacing:1px;padding:7px 10px;border-bottom:1px solid var(--br);}
td{padding:8px 10px;border-bottom:1px solid var(--br);}
.tb{color:var(--g);font-weight:700;}.ts{color:var(--r);font-weight:700;}
#toast{position:fixed;bottom:20px;right:20px;background:var(--sf);border:1px solid var(--br);
  padding:10px 18px;border-radius:6px;font-size:12px;display:none;z-index:99;}
</style></head><body>
<header>
  <h1>🔔 ANGEL ONE WEBHOOK</h1>
  <span id="mode-badge" class="badge dry">DRY RUN</span>
  <span id="tok-badge"  class="badge warn">TOKEN ?</span>
</header>
<main>
  <!-- Token status -->
  <div class="token-box">
    <div class="lbl">SMARTAPI TOKEN STATUS</div>
    <div id="tok-status" style="font-size:13px;margin-top:6px;">Checking...</div>
    <div style="margin-top:10px;font-size:12px;color:var(--mu)">
      Token auto-renews daily at midnight via TOTP — no manual login needed.
      If renewal fails: <a href="/refresh_token" style="color:var(--b)">Force Refresh</a>
    </div>
  </div>

  <!-- Active option -->
  <div class="active-opt">
    <div class="lbl">ACTIVE OPTION</div>
    <div class="sym" id="a-sym">—</div>
    <div class="meta" id="a-meta">No option selected — go to Option Selector</div>
    <div style="margin-top:12px;display:flex;gap:10px;flex-wrap:wrap;">
      <a href="/option"       class="btn btn-b">⚙️ Select Option</a>
      <a href="/webhook_log" class="btn btn-o" style="font-size:12px">📋 Webhook Log</a>
    </div>
  </div>

  <!-- Stats -->
  <div class="stats">
    <div class="card"><div class="lbl">LTP</div><div class="val yw" id="s-ltp">—</div></div>
    <div class="card"><div class="lbl">Position</div><div class="val yw" id="s-pos">FLAT</div></div>
    <div class="card"><div class="lbl">Entry Price</div><div class="val" id="s-entry">—</div></div>
    <div class="card"><div class="lbl">Today PnL</div><div class="val" id="s-pnl">₹0</div></div>
    <div class="card"><div class="lbl">Lot Size</div><div class="val" id="s-lot">—</div></div>
    <div class="card"><div class="lbl">Last Signal</div><div class="val" id="s-sig">—</div></div>
  </div>

  <!-- Manual controls -->
  <div class="controls">
    <button class="btn btn-g" id="btn-buy"  onclick="order('BUY')">▲ BUY (Manual)</button>
    <button class="btn btn-r" id="btn-sell" onclick="order('SELL')" disabled>▼ SELL (Manual)</button>
  </div>

  <!-- Webhook info -->
  <div class="card" style="margin-bottom:20px">
    <div class="lbl" style="margin-bottom:12px">TRADINGVIEW WEBHOOK URLS</div>

    <!-- Essential Plan -->
    <div style="background:var(--sf2);border:1px solid var(--br);border-radius:6px;padding:12px 14px;margin-bottom:10px">
      <div style="font-size:10px;color:var(--y);letter-spacing:1px;font-weight:700;margin-bottom:8px">
        ⭐ ESSENTIAL PLAN — Use two separate URLs (no JSON needed)
      </div>
      <div style="margin-bottom:6px">
        <span style="font-size:10px;color:var(--g);font-weight:700">BUY ALERT</span> — paste this as Webhook URL:
        <div id="buy-url" style="color:var(--g);font-size:11px;word-break:break-all;background:#00e67611;border-radius:4px;padding:5px 8px;margin-top:4px;cursor:pointer" onclick="copyUrl('buy-url')" title="Click to copy">—</div>
      </div>
      <div>
        <span style="font-size:10px;color:var(--r);font-weight:700">SELL ALERT</span> — paste this as Webhook URL:
        <div id="sell-url" style="color:var(--r);font-size:11px;word-break:break-all;background:#ff525211;border-radius:4px;padding:5px 8px;margin-top:4px;cursor:pointer" onclick="copyUrl('sell-url')" title="Click to copy">—</div>
      </div>
      <div style="font-size:10px;color:var(--mu);margin-top:8px">
        💡 Leave the Message field in TradingView as-is — no changes needed there.
        Click a URL above to copy it.
      </div>
    </div>

    <!-- Pro Plan -->
    <div style="background:var(--sf2);border:1px solid var(--br);border-radius:6px;padding:10px 14px">
      <div style="font-size:10px;color:var(--mu);letter-spacing:1px;font-weight:700;margin-bottom:6px">
        PRO / PREMIUM PLAN — Single URL + JSON message
      </div>
      <div style="font-size:11px;color:var(--mu)">
        Webhook URL: <span id="webhook-url" style="color:var(--y)">—</span><br>
        BUY message:  <code style="color:var(--g)">{"action":"BUY","secret":"YOUR_TV_SECRET"}</code><br>
        SELL message: <code style="color:var(--r)">{"action":"SELL","secret":"YOUR_TV_SECRET"}</code>
      </div>
    </div>
    <div id="copy-toast" style="display:none;font-size:11px;color:var(--g);margin-top:6px">✅ Copied to clipboard!</div>
  </div>

  <!-- Trade log -->
  <div class="card">
    <div class="lbl" style="margin-bottom:10px">TODAY'S TRADES</div>
    <table>
      <thead><tr><th>Time</th><th>Symbol</th><th>Side</th><th>Price</th><th>Qty</th><th>PnL</th><th>Mode</th></tr></thead>
      <tbody id="trade-body"><tr><td colspan="7" style="color:var(--mu);text-align:center;padding:20px">No trades today</td></tr></tbody>
    </table>
  </div>
</main>
<div id="toast"></div>
<script>
function toast(m,c='var(--g)'){const e=document.getElementById('toast');e.textContent=m;e.style.color=c;e.style.display='block';setTimeout(()=>e.style.display='none',3000);}

async function refresh(){
  const [s,t,tk]=await Promise.all([
    fetch('/api/status').then(r=>r.json()).catch(()=>({})),
    fetch('/api/trades').then(r=>r.json()).catch(()=>({trades:[]})),
    fetch('/api/token_status').then(r=>r.json()).catch(()=>({})),
  ]);

  // Mode badge
  document.getElementById('mode-badge').textContent = s.dry_run?'DRY RUN':'LIVE';
  document.getElementById('mode-badge').className   = 'badge '+(s.dry_run?'dry':'live');

  // Token status
  const tokEl = document.getElementById('tok-status');
  const tokBadge = document.getElementById('tok-badge');
  if(tk.valid){
    tokEl.innerHTML = '<span class="token-ok">✅ Valid — generated '+tk.token_date+' | Auto-renews at midnight via TOTP</span>';
    tokBadge.textContent='TOKEN OK'; tokBadge.className='badge live';
  } else {
    tokEl.innerHTML = '<span class="token-warn">⚠️ '+tk.message+' — <a href="/refresh_token" style="color:var(--b)">click to refresh</a></span>';
    tokBadge.textContent='TOKEN EXPIRED'; tokBadge.className='badge stopped';
  }

  // Active option
  document.getElementById('a-sym').textContent  = s.trading_symbol||'—';
  document.getElementById('a-meta').textContent = s.trading_symbol
    ? ('Strike: '+s.strike+' | Type: '+s.option_type+' | Expiry: '+s.expiry+' | Token: '+s.symbol_token)
    : 'No option selected — click Select Option';

  // Stats
  if(s.ltp){
    document.getElementById('s-ltp').textContent = s.ltp.toFixed(2);
    document.getElementById('s-ltp').className   = 'val yw';
  } else if(s.ltp_error){
    document.getElementById('s-ltp').textContent = 'ERR';
    document.getElementById('s-ltp').title       = s.ltp_error;
    document.getElementById('s-ltp').className   = 'val rd';
  } else {
    document.getElementById('s-ltp').textContent = s.symbol_token ? 'Loading...' : '—';
    document.getElementById('s-ltp').className   = 'val';
  }
  document.getElementById('s-pos').textContent   = s.position;
  document.getElementById('s-entry').textContent = s.entry_price ? s.entry_price.toFixed(2) : '—';
  document.getElementById('s-lot').textContent   = s.lotsize||'—';
  document.getElementById('s-sig').textContent   = s.last_signal||'—';
  const p=document.getElementById('s-pnl');
  p.textContent='₹'+(s.today_pnl||0).toLocaleString('en-IN');
  p.className='val '+(s.today_pnl>0?'gn':s.today_pnl<0?'rd':'yw');

  // Buttons
  document.getElementById('btn-buy').disabled  = s.position==='LONG';
  document.getElementById('btn-sell').disabled = s.position==='FLAT';

  // Webhook URL
  // Populate webhook URLs
  const base    = window.location.origin;
  const tvSecret = '{{ tv_secret }}';  // filled from server
  document.getElementById('webhook-url').textContent = base+'/webhook';
  document.getElementById('buy-url').textContent     = base+'/webhook/buy?secret='+tvSecret;
  document.getElementById('sell-url').textContent    = base+'/webhook/sell?secret='+tvSecret;

  // Trades
  if(t.trades&&t.trades.length){
    document.getElementById('trade-body').innerHTML=t.trades.slice().reverse().map(r=>
      `<tr><td>${r.time.slice(0,19).replace('T',' ')}</td>
      <td style="color:var(--y)">${r.symbol||'—'}</td>
      <td class="${r.side==='BUY'?'tb':'ts'}">${r.side}</td>
      <td>${r.price}</td><td>${r.quantity}</td>
      <td style="color:${r.pnl>=0?'var(--g)':'var(--r)'}">${r.pnl>0?'+':''}₹${(+r.pnl).toLocaleString('en-IN')}</td>
      <td style="color:var(--mu)">${r.dry_run?'DRY':'LIVE'}</td></tr>`
    ).join('');
  }
}

async function order(side){
  const r=await fetch('/api/manual_order',{method:'POST',
    headers:{'Content-Type':'application/json'},body:JSON.stringify({side})});
  const d=await r.json();
  if(d.status==='ok') toast((side==='BUY'?'🟢':'🔴')+' '+side+' placed');
  else toast('❌ '+d.error,'var(--r)');
  refresh();
}

refresh(); setInterval(refresh, 20000);

function copyUrl(id){
  const text = document.getElementById(id).textContent;
  navigator.clipboard.writeText(text).then(()=>{
    document.getElementById('copy-toast').style.display='block';
    setTimeout(()=>document.getElementById('copy-toast').style.display='none',2000);
  });
}
</script></body></html>"""

# ─────────────────────────────────────────────────────────────────────────────
# OPTION SELECTOR PAGE
# ─────────────────────────────────────────────────────────────────────────────
OPTION_HTML = """<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Option Selector</title>
<style>
:root{--bg:#0d0f14;--sf:#161920;--sf2:#1c2030;--br:#1e2330;
  --g:#00e676;--r:#ff5252;--y:#ffd740;--b:#3b82f6;--o:#f97316;
  --tx:#e8eaf0;--mu:#6b7280;--fn:'JetBrains Mono','Fira Code',monospace;}
*{box-sizing:border-box;margin:0;padding:0;}
body{background:var(--bg);color:var(--tx);font-family:var(--fn);font-size:13px;}
header{padding:14px 24px;border-bottom:1px solid var(--br);display:flex;align-items:center;gap:12px;}
header h1{font-size:16px;letter-spacing:2px;color:var(--o);}
a.back{color:var(--mu);text-decoration:none;font-size:12px;}
main{max-width:900px;margin:0 auto;padding:24px;}
.row{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:16px;align-items:flex-end;}
.field{display:flex;flex-direction:column;gap:5px;}
.field label{font-size:10px;color:var(--mu);letter-spacing:1px;text-transform:uppercase;}
input,select{background:var(--sf2);border:1px solid var(--br);border-radius:6px;
  color:var(--tx);font-family:var(--fn);font-size:13px;padding:8px 12px;}
input:focus,select:focus{outline:none;border-color:var(--b);}
.btn{padding:8px 20px;border-radius:6px;font-family:var(--fn);font-size:13px;
  font-weight:700;cursor:pointer;border:none;}
.btn-b{background:var(--b);color:#fff;}.btn-g{background:var(--g);color:#000;}
.card{background:var(--sf);border:1px solid var(--br);border-radius:8px;padding:16px;margin-bottom:14px;}
table{width:100%;border-collapse:collapse;font-size:12px;}
th{text-align:left;font-size:10px;color:var(--mu);letter-spacing:1px;padding:6px 10px;border-bottom:1px solid var(--br);}
td{padding:9px 10px;border-bottom:1px solid var(--br);}
tr:hover td{background:#ffffff05;}
.use-btn{padding:4px 14px;border-radius:4px;font-size:11px;font-weight:700;
  cursor:pointer;border:none;background:var(--g);color:#000;}
#status{font-size:12px;margin-top:10px;min-height:16px;}
#active-info{background:#00e67611;border:1px solid var(--g);border-radius:6px;
  padding:12px 16px;margin-bottom:16px;display:none;font-size:12px;}
.hint{font-size:11px;color:var(--mu);margin-bottom:16px;line-height:1.7;}
#toast{position:fixed;bottom:20px;right:20px;background:var(--sf);border:1px solid var(--br);
  padding:10px 18px;border-radius:6px;font-size:12px;display:none;z-index:99;}
</style></head><body>
<header>
  <a class="back" href="/">← Dashboard</a>
  <h1>⚙️ OPTION SELECTOR</h1>
</header>
<main>
  <!-- Spot price bar -->
  <div id="spot-bar" style="background:var(--sf);border:1px solid var(--br);border-radius:8px;
    padding:12px 18px;margin-bottom:14px;display:flex;gap:24px;flex-wrap:wrap;align-items:center;">
    <div>
      <div style="font-size:10px;color:var(--mu);letter-spacing:1px;text-transform:uppercase;margin-bottom:3px">NIFTY SPOT</div>
      <div id="spot-val" style="font-size:22px;font-weight:700;color:var(--y)">—</div>
    </div>
    <div>
      <div style="font-size:10px;color:var(--mu);letter-spacing:1px;text-transform:uppercase;margin-bottom:3px">ATM STRIKE</div>
      <div id="atm-val" style="font-size:22px;font-weight:700;color:var(--g)">—</div>
    </div>
    <div>
      <div style="font-size:10px;color:var(--mu);letter-spacing:1px;text-transform:uppercase;margin-bottom:3px">SHOWING RANGE</div>
      <div id="range-val" style="font-size:16px;font-weight:700;color:var(--b)">ATM ± 500</div>
    </div>
    <div style="margin-left:auto;font-size:11px;color:var(--mu);line-height:1.6">
      Strikes auto-filtered ±500 from spot.<br>
      Enter a specific strike to override.
    </div>
  </div>

  <div class="hint">
    Select a NIFTY option → click <strong>USE</strong> → webhook trades that option.<br>
    ⚠️ NIFTY weekly options expire every <strong>Tuesday</strong> — re-select strike each week.
  </div>

  <div id="active-info">
    <strong style="color:var(--g)">✅ ACTIVE OPTION:</strong>
    <span id="ai-text">—</span>
  </div>

  <!-- Tuesday expiry banner -->
  <div id="expiry-banner" style="background:#ffd74022;border:1px solid var(--y);border-radius:6px;
    padding:10px 16px;margin-bottom:14px;font-size:12px;display:none;">
    📅 <strong style="color:var(--y)">NIFTY Weekly Expiry:</strong>
    <span id="nearest-expiry" style="color:var(--g)">—</span>
    <span style="color:var(--mu);margin-left:8px">(expires every Tuesday — update strike weekly)</span>
  </div>

  <div class="row">
    <div class="field">
      <label>Underlying</label>
      <select id="underlying">
        <option value="NIFTY">NIFTY (lot=65)</option>
        <option value="BANKNIFTY">BANKNIFTY (lot=30)</option>
        <option value="FINNIFTY">FINNIFTY (lot=40)</option>
      </select>
    </div>
    <div class="field">
      <label>Option Type</label>
      <select id="opt-type"><option value="CE">CE (Call)</option><option value="PE">PE (Put)</option></select>
    </div>
    <div class="field">
      <label>Expiry (Tuesday)</label>
      <select id="expiry-sel" style="min-width:140px">
        <option value="">Loading...</option>
      </select>
    </div>
    <div class="field">
      <label>Strike</label>
      <input id="strike" placeholder="e.g. 23500" style="width:110px">
    </div>
    <div class="field">
      <label>Lot Size</label>
      <input id="lotsize" value="65" style="width:70px">
    </div>
    <div class="field" style="justify-content:flex-end">
      <button class="btn btn-b" onclick="search()">🔍 SEARCH</button>
    </div>
  </div>

  <div id="status" style="color:var(--mu)"></div>

  <div class="card" id="results-card" style="display:none">
    <table>
      <thead><tr><th>Symbol</th><th>Token</th><th>Strike</th><th>Expiry</th><th>Lot</th><th></th></tr></thead>
      <tbody id="results-body"></tbody>
    </table>
  </div>

  <!-- Manual entry -->
  <div class="card">
    <div style="font-size:10px;color:var(--mu);letter-spacing:1px;text-transform:uppercase;margin-bottom:12px">MANUAL ENTRY (if search doesn't find it)</div>
    <div class="row">
      <div class="field"><label>Symbol Token</label><input id="m-token" placeholder="e.g. 35003" style="width:130px"></div>
      <div class="field"><label>Trading Symbol</label><input id="m-sym" placeholder="e.g. NIFTY13JUN2426000CE" style="width:230px"></div>
      <div class="field"><label>Strike</label><input id="m-strike" placeholder="26000" style="width:100px"></div>
      <div class="field"><label>Type</label><select id="m-type"><option>CE</option><option>PE</option></select></div>
      <div class="field"><label>Expiry</label><input id="m-expiry" placeholder="2026-06-13" style="width:120px"></div>
      <div class="field" style="justify-content:flex-end">
        <button class="btn btn-g" onclick="applyManual()">✅ SET ACTIVE</button>
      </div>
    </div>
  </div>
</main>
<div id="toast"></div>
<script>
function toast(m,c='var(--g)'){const e=document.getElementById('toast');e.textContent=m;e.style.color=c;e.style.display='block';setTimeout(()=>e.style.display='none',3000);}

async function loadExpiries(){
  try {
    const r = await fetch('/api/expiries');
    const d = await r.json();
    if(d.expiries && d.expiries.length){
      const sel = document.getElementById('expiry-sel');
      sel.innerHTML = d.expiries.map((e,i)=>
        `<option value="${e}" ${i===0?'selected':''}>${e}${i===0?' ← nearest':''}</option>`
      ).join('');
      document.getElementById('nearest-expiry').textContent = d.nearest + ' (this Tuesday)';
      document.getElementById('expiry-banner').style.display='block';
    }
  } catch(e){ console.log('Expiry load failed:', e); }
}

let lastSpot = null;
let lastAtm  = null;

async function search(){
  const underlying = document.getElementById('underlying').value;
  const optType    = document.getElementById('opt-type').value;
  const strike     = document.getElementById('strike').value;
  const expiry     = document.getElementById('expiry-sel').value;
  document.getElementById('status').textContent='Fetching NIFTY spot & searching...';
  document.getElementById('results-card').style.display='none';

  const r = await fetch(`/api/search?underlying=${underlying}&type=${optType}&strike=${strike}&expiry=${expiry}&range=500`);
  const d = await r.json();

  // Update spot bar
  if(d.spot){
    lastSpot = d.spot;
    lastAtm  = d.atm;
    document.getElementById('spot-val').textContent  = d.spot.toLocaleString('en-IN', {maximumFractionDigits:2});
    document.getElementById('atm-val').textContent   = d.atm.toLocaleString('en-IN');
    document.getElementById('range-val').textContent = `${(d.atm-500).toLocaleString('en-IN')} – ${(d.atm+500).toLocaleString('en-IN')}`;
  } else if(d.spot_error){
    document.getElementById('spot-val').textContent  = 'N/A';
    document.getElementById('atm-val').textContent   = '—';
    document.getElementById('range-val').textContent = 'Login to see spot';
  }

  if(d.error){ document.getElementById('status').textContent='❌ Error: '+d.error; return; }

  const spotInfo = d.spot ? ` | NIFTY @ ${d.spot.toFixed(0)} | ATM ${d.atm}` : '';
  document.getElementById('status').textContent =
    `${d.results.length} contracts${strike?' for strike '+strike:' within ±500 of ATM'}${spotInfo}`;

  if(!d.results.length){
    document.getElementById('status').textContent='No contracts found — try different expiry or change strike';
    return;
  }

  document.getElementById('results-body').innerHTML = d.results.map(x=>{
    const isAtm   = lastAtm && x.strike === lastAtm;
    const isNear  = lastAtm && Math.abs(x.strike - lastAtm) <= 100;
    const rowStyle = isAtm ? 'background:#ffd74011' : '';
    const atmTag   = isAtm ? ' <span style="color:var(--y);font-size:10px">ATM</span>' : '';
    return `<tr style="${rowStyle}">
      <td style="color:var(--y)">${x.trading_symbol}${atmTag}</td>
      <td style="color:var(--mu);font-size:11px">${x.symbol_token}</td>
      <td style="${isAtm?'color:var(--y);font-weight:700':''}">
        ${x.strike.toLocaleString('en-IN')}
        ${lastAtm?'<span style="font-size:10px;color:var(--mu);margin-left:4px">('+
          (x.strike>lastAtm?'+':'')+(x.strike-lastAtm).toFixed(0)+')</span>':''}
      </td>
      <td style="color:var(--g)">${x.expiry_display}</td>
      <td>${x.lotsize}</td>
      <td><button class="use-btn" onclick="apply('${x.symbol_token}','${x.trading_symbol}',
        ${x.strike},'${document.getElementById('opt-type').value}',
        '${x.expiry}',${x.lotsize})">USE</button></td>
    </tr>`;
  }).join('');
  document.getElementById('results-card').style.display='block';
}

async function apply(token, sym, strike, type, expiry, lot){
  const lotOverride = parseInt(document.getElementById('lotsize').value)||lot;
  const r = await fetch('/api/set_option',{method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({symbol_token:token, trading_symbol:sym,
      strike, option_type:type, expiry, lotsize:lotOverride})});
  const d = await r.json();
  if(d.status==='ok'){
    document.getElementById('active-info').style.display='block';
    document.getElementById('ai-text').textContent = sym+' | token='+token+' | lot='+lotOverride;
    toast('✅ '+sym+' set as active option');
  } else {
    toast('❌ '+d.error,'var(--r)');
  }
}

async function applyManual(){
  const r = await fetch('/api/set_option',{method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({
      symbol_token:   document.getElementById('m-token').value.trim(),
      trading_symbol: document.getElementById('m-sym').value.trim(),
      strike:         parseFloat(document.getElementById('m-strike').value)||0,
      option_type:    document.getElementById('m-type').value,
      expiry:         document.getElementById('m-expiry').value.trim(),
      lotsize:        parseInt(document.getElementById('lotsize').value)||25,
    })});
  const d = await r.json();
  if(d.status==='ok') toast('✅ Manual option set');
  else toast('❌ '+d.error,'var(--r)');
}

// Load Tuesday expiries and current active on page load
loadExpiries();
fetch('/api/status').then(r=>r.json()).then(d=>{
  if(d.trading_symbol){
    document.getElementById('active-info').style.display='block';
    document.getElementById('ai-text').textContent = d.trading_symbol+' | token='+d.symbol_token;
  }
});
</script></body></html>"""

# ─────────────────────────────────────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    html = DASH_HTML.replace("{{ tv_secret }}", TV_SECRET)
    return render_template_string(html)

@app.route("/option")
def option_page(): return render_template_string(OPTION_HTML)

@app.route("/refresh_token")
def refresh_token():
    try:
        client._login()
        return ("<h2 style='font-family:monospace;color:#00e676'>✅ Token refreshed!</h2>"
                f"<p>New token date: {client.token_date}</p><p><a href='/'>← Dashboard</a></p>")
    except Exception as e:
        return f"<pre>Token refresh failed: {e}</pre>", 500

# ── Webhook helpers ───────────────────────────────────────────────────────────

def _log_wh(action, status, note="", ip="?"):
    try:
        lp    = Path("logs/webhook_calls.json")
        calls = json.loads(lp.read_text()) if lp.exists() else []
        calls.append({"time": datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S"),
                      "action": action, "status": status, "ip": ip, "note": note})
        lp.write_text(json.dumps(calls[-100:], indent=2))
    except Exception as e:
        logger.error(f"Webhook log error: {e}")


def _handle_wh(action: str, secret: str = "", ip: str = "?"):
    """Core logic shared by all webhook routes."""
    logger.info(f"Webhook: action={action} ip={ip}")
    if TV_SECRET and secret != TV_SECRET:
        logger.warning(f"Webhook rejected — bad secret from {ip}")
        _log_wh(action or "?", "rejected", "Invalid secret", ip)
        return jsonify({"error": "unauthorized"}), 401
    if action not in ("BUY", "SELL"):
        _log_wh(action or "?", "error", "unknown action", ip)
        return jsonify({"error": f"unknown action '{action}'"}), 400
    if not active["symbol_token"]:
        _log_wh(action, "error", "No option selected", ip)
        return jsonify({"error": "No option selected — go to /option first"}), 400
    result   = _execute_order(action)
    res_data = result.get_json()
    _log_wh(action, res_data.get("status","?"),
            res_data.get("error","") or ("dry_run" if DRY_RUN else "live"), ip)
    return result


# ── Webhook routes ─────────────────────────────────────────────────────────────

@app.route("/webhook", methods=["POST", "GET"])
def webhook():
    """
    Universal webhook — all TradingView plans.
    Pro/Premium  → POST with JSON body: {"action":"BUY","secret":"..."}
    Essential    → GET/POST with URL params: /webhook?action=BUY&secret=...
    """
    ip   = request.headers.get("X-Forwarded-For", request.remote_addr)
    data = {}
    try: data = request.get_json(force=True) or {}
    except Exception: pass
    action = (data.get("action") or request.args.get("action") or "").upper()
    secret = data.get("secret") or request.args.get("secret") or ""
    return _handle_wh(action, secret, ip)


@app.route("/webhook/buy", methods=["POST", "GET"])
def webhook_buy():
    """
    Dedicated BUY endpoint for TradingView Essential plan.
    Set this as Webhook URL in your BUY alert:
      https://YOUR-APP.up.railway.app/webhook/buy?secret=YOUR_TV_SECRET
    No JSON message needed — the URL carries the action.
    """
    ip     = request.headers.get("X-Forwarded-For", request.remote_addr)
    secret = request.args.get("secret", "")
    return _handle_wh("BUY", secret, ip)


@app.route("/webhook/sell", methods=["POST", "GET"])
def webhook_sell():
    """
    Dedicated SELL endpoint for TradingView Essential plan.
    Set this as Webhook URL in your SELL alert:
      https://YOUR-APP.up.railway.app/webhook/sell?secret=YOUR_TV_SECRET
    No JSON message needed — the URL carries the action.
    """
    ip     = request.headers.get("X-Forwarded-For", request.remote_addr)
    secret = request.args.get("secret", "")
    return _handle_wh("SELL", secret, ip)

# ── API routes ────────────────────────────────────────────────────────────────

@app.route("/api/status")
def api_status():
    # Try get LTP — log error clearly so we can debug
    ltp       = None
    ltp_error = None
    if active["symbol_token"] and client.jwt_token:
        try:
            ltp = client.get_ltp("NFO", active["trading_symbol"], active["symbol_token"])
        except Exception as e:
            ltp_error = str(e)
            logger.error(f"LTP fetch error: {e}")
    return jsonify({
        **tracker.status(),
        **active,
        "ltp":          ltp,
        "ltp_error":    ltp_error,
        "last_signal":  getattr(tracker, "_last_signal", None),
        "token_date":   client.token_date,
        "timestamp":    datetime.now(IST).isoformat(),
    })

@app.route("/api/token_status")
def api_token_status():
    today = datetime.now(IST).strftime("%Y-%m-%d")
    valid = bool(client.jwt_token) and client.token_date == today
    return jsonify({
        "valid":      valid,
        "token_date": client.token_date,
        "message":    "Token valid" if valid else f"Token date {client.token_date} != today {today}",
    })

@app.route("/api/trades")
def api_trades():
    return jsonify({"trades": tracker.today_trades()})

@app.route("/api/set_option", methods=["POST"])
def api_set_option():
    data = request.get_json() or {}
    if not data.get("symbol_token") or not data.get("trading_symbol"):
        return jsonify({"status": "error", "error": "symbol_token and trading_symbol required"}), 400
    active.update({
        "symbol_token":   str(data["symbol_token"]),
        "trading_symbol": data["trading_symbol"],
        "strike":         data.get("strike", ""),
        "option_type":    data.get("option_type", "CE"),
        "expiry":         data.get("expiry", ""),
        "lotsize":        int(data.get("lotsize", LOT_SIZE)),
    })
    logger.info(f"Active option set: {active}")
    return jsonify({"status": "ok", **active})

@app.route("/api/search")
def api_search():
    underlying = request.args.get("underlying", "NIFTY")
    opt_type   = request.args.get("type", "CE")
    strike     = request.args.get("strike", "")
    expiry     = request.args.get("expiry", "")
    rang       = int(request.args.get("range", 500))   # ±range from spot
    try:
        from src.instrument_lookup import search_options, get_next_tuesday_expiries

        # ── Get NIFTY spot price for ±range filter ────────────────────────────
        spot      = None
        spot_error = None
        if client.jwt_token:
            try:
                spot = client.get_nifty_spot()
                logger.info(f"NIFTY spot for search: {spot}")
            except Exception as e:
                spot_error = str(e)
                logger.warning(f"Could not fetch NIFTY spot: {e}")

        # ── Fetch all contracts for this expiry ───────────────────────────────
        results = search_options(underlying=underlying, option_type=opt_type,
                                 strike=float(strike) if strike else 0, limit=500)

        # Filter by expiry
        if expiry:
            results = [r for r in results if r.get("expiry_display","") == expiry.upper()]

        # Filter ±range from spot (only when no specific strike given)
        if spot and not strike:
            atm     = round(spot / 50) * 50    # round to nearest 50
            lo, hi  = atm - rang, atm + rang
            filtered = [r for r in results if lo <= r["strike"] <= hi]
            if filtered:
                results  = filtered
                logger.info(f"Filtered to ±{rang} of spot {spot:.0f} (ATM={atm}): {len(results)} contracts")

        expiries = get_next_tuesday_expiries(count=6)
        return jsonify({
            "results":    results[:60],
            "expiries":   expiries,
            "spot":       spot,
            "spot_error": spot_error,
            "atm":        round(spot / 50) * 50 if spot else None,
            "range":      rang,
        })
    except Exception as e:
        logger.error(f"Search error: {e}")
        return jsonify({"results": [], "expiries": [], "error": str(e)})

@app.route("/api/expiries")
def api_expiries():
    """Return next 6 Tuesday expiry dates."""
    try:
        from src.instrument_lookup import get_next_tuesday_expiries, get_nearest_tuesday_expiry
        return jsonify({
            "nearest": get_nearest_tuesday_expiry(),
            "expiries": get_next_tuesday_expiries(count=6),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/manual_order", methods=["POST"])
def api_manual_order():
    data = request.get_json() or {}
    side = data.get("side", "").upper()
    if side not in ("BUY", "SELL"):
        return jsonify({"status": "error", "error": "side must be BUY or SELL"}), 400
    if not active["symbol_token"]:
        return jsonify({"status": "error", "error": "No option selected"}), 400
    return _execute_order(side)

@app.route("/webhook_log")
def webhook_log():
    """Show last 20 webhook calls received — for debugging TradingView connection."""
    try:
        log = json.loads(Path("logs/webhook_calls.json").read_text()) if Path("logs/webhook_calls.json").exists() else []
    except Exception:
        log = []
    rows = "".join(
        f"<tr style='border-bottom:1px solid #1e2330'>"
        f"<td style='padding:8px;color:#6b7280'>{e['time']}</td>"
        f"<td style='padding:8px;color:#ffd740'>{e['action']}</td>"
        f"<td style='padding:8px;color:{'#00e676' if e['status']=='ok' else '#ff5252'}'>{e['status']}</td>"
        f"<td style='padding:8px;color:#6b7280;font-size:11px'>{e.get('ip','?')}</td>"
        f"<td style='padding:8px;color:#6b7280;font-size:11px'>{e.get('note','')}</td>"
        f"</tr>"
        for e in reversed(log[-20:])
    )
    return f"""<!DOCTYPE html><html><head><meta charset='UTF-8'>
    <meta http-equiv='refresh' content='10'>
    <title>Webhook Log</title>
    <style>body{{background:#0d0f14;color:#e8eaf0;font-family:monospace;padding:24px}}
    a{{color:#3b82f6}}table{{width:100%;border-collapse:collapse}}
    th{{text-align:left;color:#6b7280;font-size:11px;padding:6px 8px;border-bottom:1px solid #1e2330}}</style>
    </head><body>
    <h2 style='color:#00e676;margin-bottom:4px'>🔔 Webhook Call Log</h2>
    <p style='color:#6b7280;font-size:12px;margin-bottom:16px'>
      Auto-refreshes every 10s — shows last 20 webhook calls received from TradingView.<br>
      <a href='/'>← Dashboard</a> &nbsp;|&nbsp;
      <a href='/webhook_log'>🔄 Refresh</a>
    </p>
    <table><thead><tr><th>TIME (IST)</th><th>ACTION</th><th>STATUS</th><th>IP</th><th>NOTE</th></tr></thead>
    <tbody>{rows or "<tr><td colspan='5' style='padding:20px;color:#6b7280;text-align:center'>No webhook calls received yet — fire a TradingView alert or use the test below</td></tr>"}</tbody>
    </table>
    <div style='margin-top:24px;background:#161920;border:1px solid #1e2330;border-radius:8px;padding:16px'>
      <div style='font-size:11px;color:#6b7280;margin-bottom:8px'>TEST WEBHOOK (simulates TradingView alert):</div>
      <button onclick="testWh('BUY')"  style='background:#00e676;color:#000;border:none;padding:8px 18px;border-radius:6px;font-weight:700;cursor:pointer;margin-right:8px'>▲ Test BUY</button>
      <button onclick="testWh('SELL')" style='background:#ff5252;color:#fff;border:none;padding:8px 18px;border-radius:6px;font-weight:700;cursor:pointer'>▼ Test SELL</button>
      <span id='tres' style='margin-left:12px;font-size:12px'></span>
    </div>
    <script>
    async function testWh(action){{
      const r = await fetch('/webhook',{{method:'POST',
        headers:{{'Content-Type':'application/json'}},
        body:JSON.stringify({{action,secret:'{os.environ.get("TV_SECRET","")}'}})}});
      const d = await r.json();
      document.getElementById('tres').textContent = JSON.stringify(d);
      setTimeout(()=>location.reload(), 1000);
    }}
    </script></body></html>"""

@app.route("/favicon.ico")
def favicon(): return "", 204

# ── Order execution ────────────────────────────────────────────────────────────

def _execute_order(action: str):
    """Core order logic used by both webhook and manual order."""
    position = tracker.position

    if action == "BUY" and position == "LONG":
        return jsonify({"status": "skipped", "reason": "Already LONG"})
    if action == "SELL" and position == "FLAT":
        return jsonify({"status": "skipped", "reason": "No open position to sell"})

    try:
        # Get current LTP — retry once on failure
        ltp = 0.0
        for attempt in range(2):
            try:
                ltp = client.get_ltp("NFO", active["trading_symbol"], active["symbol_token"])
                break
            except Exception as e:
                logger.warning(f"LTP fetch attempt {attempt+1} failed: {e}")
                if attempt == 0:
                    # Try refreshing token then retry
                    try: client.ensure_token()
                    except Exception: pass
        if ltp == 0:
            logger.warning(f"Could not get LTP for {active['trading_symbol']} — order will proceed with price=0 (MARKET order)")

        lot = active["lotsize"]
        logger.info(
            f"{'[DRY] ' if DRY_RUN else ''}{action} {lot} x "
            f"{active['trading_symbol']} @ LTP={ltp}"
        )

        order_result = {}
        if not DRY_RUN:
            order_result = client.place_order(
                symbol_token     = active["symbol_token"],
                trading_symbol   = active["trading_symbol"],
                transaction_type = action,
                quantity         = lot,
                exchange         = "NFO",
                product_type     = "INTRADAY",
            )

        # Update position tracker
        if action == "BUY":
            tracker.on_buy(active["trading_symbol"], active["symbol_token"], ltp or 0, lot)
        else:
            tracker.on_sell(ltp or 0)

        tracker._last_signal = action
        return jsonify({"status": "ok", "action": action, "ltp": ltp,
                        "dry_run": DRY_RUN, "order": order_result})

    except Exception as e:
        logger.error(f"Order execution error: {e}")
        return jsonify({"status": "error", "error": str(e)}), 500
