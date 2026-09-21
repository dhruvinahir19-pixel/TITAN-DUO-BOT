"""
TITAN DUO v4.0 APEX - FASTAPI WEB DASHBOARD & KEEP-ALIVE SERVER
===============================================================
Serves real-time dark-mode web monitoring dashboard and exposes the
/ping keep-alive endpoint for cron-job.org and UptimeRobot.
"""

import time
import os
import json
from typing import Optional, Dict, Any

from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from config import CONFIG
from core.trade_state import BotState, ActiveTrade
from core.db_manager import DatabaseManager

app = FastAPI(
    title="Titan Duo v4.0 Apex Dashboard",
    version="4.2.0",
    docs_url=None,
    redoc_url=None
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global in-memory state references (injected by main orchestrator)
START_TIME = time.time()
db_manager: Optional[DatabaseManager] = None
current_bot_state: Optional[BotState] = None
panic_callback = None
pause_callback = None
resume_callback = None

def get_uptime_str() -> str:
    elapsed = int(time.time() - START_TIME)
    hours = elapsed // 3600
    minutes = (elapsed % 3600) // 60
    seconds = elapsed % 60
    return f"{hours}h {minutes}m {seconds}s"

@app.get("/ping")
@app.get("/health")
def keep_alive_ping():
    """
    Keep-alive endpoint invoked by cron-job.org every 9 minutes
    to prevent Render.com free containers from sleeping.
    """
    equity = current_bot_state.wallet_equity if current_bot_state else 100.0
    status_str = "ACTIVE" if (current_bot_state and current_bot_state.active_trade) else "IDLE"
    paused_str = "PAUSED" if (current_bot_state and current_bot_state.is_paused) else "RUNNING"
    
    return {
        "status": "healthy",
        "bot_mode": paused_str,
        "trade_state": status_str,
        "wallet_equity_usd": round(equity, 2),
        "wallet_equity_inr": round(equity * 85.50, 0),
        "uptime": get_uptime_str(),
        "timestamp": int(time.time())
    }

@app.get("/api/status")
def get_api_status():
    """
    Returns real-time bot state, active trade details, and performance summary.
    """
    state_dict = current_bot_state.to_dict() if current_bot_state else {}
    summary = {}
    if db_manager:
        try:
            summary = db_manager.get_performance_summary()
        except Exception:
            pass

    return {
        "state": state_dict,
        "summary": summary,
        "uptime": get_uptime_str(),
        "proxy_url": CONFIG.COINSWITCH_PROXY_URL,
        "timestamp": int(time.time())
    }

@app.get("/api/trades")
def get_closed_trades(limit: int = 50):
    """
    Returns recent closed trades history.
    """
    if db_manager:
        try:
            return db_manager.get_recent_trades(limit=limit)
        except Exception as e:
            return {"error": str(e)}
    return []

class ControlAction(BaseModel):
    password: str

@app.post("/api/panic")
def trigger_panic(action: ControlAction):
    if action.password != CONFIG.ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Unauthorized: Invalid password.")
    if panic_callback:
        res = panic_callback()
        return {"success": True, "message": "Emergency panic triggered", "result": res}
    return {"success": False, "message": "Panic callback not configured."}

@app.post("/api/pause")
def trigger_pause(action: ControlAction):
    if action.password != CONFIG.ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Unauthorized")
    if pause_callback:
        pause_callback()
        return {"success": True, "message": "Bot paused successfully."}
    return {"success": False}

@app.post("/api/resume")
def trigger_resume(action: ControlAction):
    if action.password != CONFIG.ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Unauthorized")
    if resume_callback:
        resume_callback()
        return {"success": True, "message": "Bot resumed successfully."}
    return {"success": False}

@app.get("/", response_class=HTMLResponse)
def serve_dashboard():
    """
    Dark-mode, responsive institutional web dashboard.
    """
    equity = current_bot_state.wallet_equity if current_bot_state else 100.0
    equity_inr = equity * 85.50
    trade = current_bot_state.active_trade if current_bot_state else None
    
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Titan Duo v4.0 Apex — Dashboard</title>
    <style>
        :root {{
            --bg: #090D16;
            --surface: #111827;
            --border: #1F2937;
            --text-primary: #F9FAFB;
            --text-muted: #9CA3AF;
            --accent: #6366F1;
            --green: #10B981;
            --red: #EF4444;
            --gold: #F59E0B;
        }}
        * {{ margin: 0; padding: 0; box-sizing: border-box; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }}
        body {{ background-color: var(--bg); color: var(--text-primary); padding: 24px; min-height: 100vh; }}
        .header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; padding-bottom: 16px; border-bottom: 1px solid var(--border); }}
        .title-group h1 {{ font-size: 22px; font-weight: 700; color: #FFF; }}
        .title-group p {{ font-size: 13px; color: var(--text-muted); margin-top: 4px; }}
        .badge {{ padding: 4px 10px; border-radius: 9999px; font-size: 12px; font-weight: 600; text-transform: uppercase; }}
        .badge-online {{ background: rgba(16, 185, 129, 0.15); color: var(--green); border: 1px solid rgba(16, 185, 129, 0.3); }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 16px; margin-bottom: 24px; }}
        .card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 20px; }}
        .card-label {{ font-size: 13px; color: var(--text-muted); font-weight: 500; }}
        .card-value {{ font-size: 28px; font-weight: 700; margin: 8px 0 4px; color: #FFF; }}
        .card-sub {{ font-size: 13px; color: var(--text-muted); }}
        .card-sub.green {{ color: var(--green); }}
        .active-pos-card {{ background: linear-gradient(180deg, #161F30 0%, #111827 100%); border: 1px solid #374151; border-radius: 12px; padding: 24px; margin-bottom: 24px; }}
        .pos-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }}
        .pos-details {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 16px; }}
        .pos-field .label {{ font-size: 12px; color: var(--text-muted); text-transform: uppercase; }}
        .pos-field .val {{ font-size: 18px; font-weight: 600; margin-top: 4px; }}
        .table-card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 20px; }}
        .table-title {{ font-size: 16px; font-weight: 600; margin-bottom: 16px; }}
        table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
        th {{ text-align: left; color: var(--text-muted); padding: 10px 12px; border-bottom: 1px solid var(--border); }}
        td {{ padding: 12px; border-bottom: 1px solid #1A2234; }}
        .pill {{ padding: 2px 8px; border-radius: 4px; font-weight: 600; font-size: 11px; }}
        .pill-long {{ background: rgba(16, 185, 129, 0.15); color: var(--green); }}
        .pill-short {{ background: rgba(239, 68, 68, 0.15); color: var(--red); }}
        .pulse-dot {{ width: 8px; height: 8px; border-radius: 50%; background: var(--green); display: inline-block; margin-right: 6px; box-shadow: 0 0 10px var(--green); }}
    </style>
</head>
<body>
    <div class="header">
        <div class="title-group">
            <h1>TITAN DUO v4.0 APEX</h1>
            <p>CoinSwitch Pro Autonomous Perpetual Futures System</p>
        </div>
        <div>
            <span class="badge badge-online"><span class="pulse-dot"></span> 24/7 ONLINE</span>
        </div>
    </div>

    <div class="grid">
        <div class="card">
            <div class="card-label">TOTAL WALLET EQUITY</div>
            <div class="card-value">${equity:,.2f}</div>
            <div class="card-sub green">₹{equity_inr:,.0f} INR (Apex 3.0% Tier)</div>
        </div>
        <div class="card">
            <div class="card-label">ACTIVE INSTRUMENTS</div>
            <div class="card-value">ETH & BTC</div>
            <div class="card-sub">ETH 1H (Primary) | BTC 4H (Secondary)</div>
        </div>
        <div class="card">
            <div class="card-label">RISK GOVERNORS</div>
            <div class="card-value">ACTIVE</div>
            <div class="card-sub">Single Portfolio | 72h Chop | 16h Cooldown</div>
        </div>
        <div class="card">
            <div class="card-label">SERVER UPTIME</div>
            <div class="card-value">{get_uptime_str()}</div>
            <div class="card-sub">Render Singapore | cron-job.org Awake</div>
        </div>
    </div>

    <div class="active-pos-card">
        <div class="pos-header">
            <h3>ACTIVE PORTFOLIO STATUS</h3>
            <span class="badge" style="background: rgba(99, 102, 241, 0.15); color: #818CF8; border: 1px solid rgba(99, 102, 241, 0.3);">
                {"IN TRADE" if trade else "IDLE CASH (LISTENING)"}
            </span>
        </div>
        {"<div class='pos-details'>" +
         f"<div class='pos-field'><div class='label'>Symbol</div><div class='val'>{trade.symbol}</div></div>" +
         f"<div class='pos-field'><div class='label'>Direction</div><div class='val'>{'LONG' if trade.direction == 1 else 'SHORT'}</div></div>" +
         f"<div class='pos-field'><div class='label'>Entry Price</div><div class='val'>${trade.entry_price:,.2f}</div></div>" +
         f"<div class='pos-field'><div class='label'>Stop Loss</div><div class='val' style='color: var(--gold);'>${trade.stop_loss:,.2f}</div></div>" +
         f"<div class='pos-field'><div class='label'>Take Profit</div><div class='val' style='color: var(--green);'>${trade.take_profit:,.2f}</div></div>" +
         f"<div class='pos-field'><div class='label'>Position Size</div><div class='val'>{trade.current_units:.4f} units</div></div>" +
         f"<div class='pos-field'><div class='label'>Risk-Free BE</div><div class='val'>{'✅ LOCKED' if trade.is_be_locked else 'PENDING (+2.0x ATR)'}</div></div>" +
         f"<div class='pos-field'><div class='label'>Pyramid Status</div><div class='val'>{'🔥 +0.5x ADDED' if trade.is_pyramided else 'NOT PYRAMIDED'}</div></div>" +
         "</div>" if trade else
         "<p style='color: var(--text-muted); font-size: 14px;'>No active positions. Capital is 100% in safe USDT cash. Monitoring candle close at minute 30 IST (XX:30:02 IST) for Donchian breakout signals.</p>"}
    </div>

    <div class="table-card">
        <div class="table-title">RECENT EXECUTIONS & SYSTEM AUDIT</div>
        <table id="trades-table">
            <thead>
                <tr>
                    <th>Timestamp</th>
                    <th>Pair</th>
                    <th>Direction</th>
                    <th>Entry Price</th>
                    <th>Exit Price</th>
                    <th>Net PnL (USD)</th>
                    <th>CoinSwitch Fees</th>
                    <th>Exit Reason</th>
                </tr>
            </thead>
            <tbody id="trades-body">
                <tr><td colspan="8" style="text-align: center; color: var(--text-muted); padding: 24px;">Listening for initial live execution signals...</td></tr>
            </tbody>
        </table>
    </div>

    <script>
        async function refreshData() {{
            try {{
                const res = await fetch('/api/trades');
                const trades = await res.json();
                if (Array.isArray(trades) && trades.length > 0) {{
                    const tbody = document.getElementById('trades-body');
                    tbody.innerHTML = trades.map(t => `
                        <tr>
                            <td>${{t.exit_time ? new Date(t.exit_time).toLocaleString() : '-'}}</td>
                            <td><strong>${{t.symbol}}</strong></td>
                            <td><span class="pill ${{t.direction === 'LONG' ? 'pill-long' : 'pill-short'}}">${{t.direction}}</span></td>
                            <td>$${{parseFloat(t.entry_price).toFixed(2)}}</td>
                            <td>$${{parseFloat(t.exit_price).toFixed(2)}}</td>
                            <td style="color: ${{parseFloat(t.net_pnl) >= 0 ? 'var(--green)' : 'var(--red)'}}; font-weight: 600;">
                                ${{parseFloat(t.net_pnl) >= 0 ? '+' : ''}}${{parseFloat(t.net_pnl).toFixed(2)}}
                            </td>
                            <td>$${{parseFloat(t.fee).toFixed(2)}}</td>
                            <td>${{t.exit_reason}}</td>
                        </tr>
                    `).join('');
                }}
            }} catch(e) {{}}
        }}
        refreshData();
        setInterval(refreshData, 15000);
    </script>
</body>
</html>
"""
    return HTMLResponse(content=html_content)
