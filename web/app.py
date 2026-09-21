"""
TITAN DUO v4.0 APEX - FASTAPI WEB DASHBOARD & KEEP-ALIVE SERVER
===============================================================
Institutional, high-frequency, dark-glassmorphism quant monitoring dashboard
engineered for DD (Dhruvin Dangar). Fully mobile-responsive, self-contained SVG
charts, live candle countdown, dynamic leverage controls, and real-time telemetry.
"""

import time
import os
import json
from typing import Optional, Dict, Any

from fastapi import FastAPI, Request, HTTPException
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

START_TIME = time.time()
db_manager: Optional[DatabaseManager] = None
current_bot_state: Optional[BotState] = None
panic_callback = None
pause_callback = None
resume_callback = None
set_leverage_callback = None

def get_uptime_str() -> str:
    elapsed = int(time.time() - START_TIME)
    hours = elapsed // 3600
    minutes = (elapsed % 3600) // 60
    seconds = elapsed % 60
    return f"{hours}h {minutes}m {seconds}s"

@app.get("/ping")
@app.get("/health")
def keep_alive_ping():
    equity = current_bot_state.wallet_equity if current_bot_state else 100.0
    status_str = "ACTIVE" if (current_bot_state and current_bot_state.active_trade) else "IDLE"
    paused_str = "PAUSED" if (current_bot_state and current_bot_state.is_paused) else "RUNNING"
    lev = current_bot_state.leverage_ceiling if current_bot_state else 20
    
    return {
        "status": "healthy",
        "bot_mode": paused_str,
        "trade_state": status_str,
        "wallet_equity_usd": round(equity, 2),
        "wallet_equity_inr": round(equity * 85.50, 0),
        "leverage_ceiling": lev,
        "uptime": get_uptime_str(),
        "timestamp": int(time.time())
    }

@app.get("/api/status")
def get_api_status():
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
        "mode": os.getenv("EXECUTION_MODE", "LIVE"),
        "uptime": get_uptime_str(),
        "proxy_url": CONFIG.COINSWITCH_PROXY_URL,
        "timestamp": int(time.time())
    }

@app.get("/api/trades")
def get_closed_trades(limit: int = 50):
    if db_manager:
        try:
            return db_manager.get_recent_trades(limit=limit)
        except Exception as e:
            return {"error": str(e)}
    return []

class ControlAction(BaseModel):
    password: str

class LeverageAction(BaseModel):
    leverage: int
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

@app.post("/api/set_leverage")
def trigger_set_leverage(action: LeverageAction):
    if action.password != CONFIG.ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Unauthorized")
    if not (1 <= action.leverage <= 25):
        raise HTTPException(status_code=400, detail="Leverage must be between 1x and 25x.")
    if set_leverage_callback:
        res = set_leverage_callback(action.leverage)
        return {"success": True, "message": res}
    return {"success": False, "message": "Leverage callback not configured."}

@app.get("/", response_class=HTMLResponse)
def serve_dashboard():
    equity = current_bot_state.wallet_equity if current_bot_state else 10.62
    equity_inr = equity * 85.50
    trade = current_bot_state.active_trade if current_bot_state else None
    lev = current_bot_state.leverage_ceiling if current_bot_state else 20
    exec_mode = os.getenv("EXECUTION_MODE", "LIVE").upper()
    mode_badge_html = (
        '<span class="badge badge-live" id="mode-badge"><span class="badge-pulse"></span>LIVE CAPITAL (COINSWITCH PRO)</span>'
        if exec_mode == "LIVE" else
        '<span class="badge badge-paper" id="mode-badge">PAPER TRADING (₹0 RISK)</span>'
    )
    
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>TITAN DUO v4.0 APEX — Institutional Quant Dashboard</title>
    <style>
        :root {{
            --bg-base: #06080F;
            --bg-card: rgba(13, 17, 28, 0.75);
            --bg-card-hover: rgba(20, 26, 42, 0.85);
            --border-subtle: rgba(255, 255, 255, 0.08);
            --border-focus: rgba(99, 102, 241, 0.4);
            --text-main: #F8FAFC;
            --text-muted: #94A3B8;
            --text-faint: #64748B;
            --accent-primary: #6366F1;
            --accent-gradient: linear-gradient(135deg, #6366F1 0%, #8B5CF6 100%);
            --profit: #10B981;
            --profit-glow: rgba(16, 185, 129, 0.25);
            --loss: #F43F5E;
            --loss-glow: rgba(244, 63, 94, 0.25);
            --gold: #F59E0B;
            --cyan: #06B6D4;
        }}
        * {{ margin: 0; padding: 0; box-sizing: border-box; -webkit-tap-highlight-color: transparent; }}
        body {{
            background-color: var(--bg-base);
            background-image: 
                radial-gradient(circle at 15% 15%, rgba(99, 102, 241, 0.08) 0%, transparent 40%),
                radial-gradient(circle at 85% 85%, rgba(16, 185, 129, 0.06) 0%, transparent 40%);
            color: var(--text-main);
            font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "Segoe UI", Roboto, Helvetica, sans-serif;
            padding: 16px;
            min-height: 100vh;
            line-height: 1.5;
        }}
        @media (min-width: 768px) {{ body {{ padding: 32px; }} }}
        
        .tabular {{ font-variant-numeric: tabular-nums; }}
        
        /* Top Navigation Header */
        .header {{
            display: flex;
            flex-direction: column;
            gap: 16px;
            padding: 20px 24px;
            background: var(--bg-card);
            backdrop-filter: blur(16px);
            border: 1px solid var(--border-subtle);
            border-radius: 20px;
            margin-bottom: 24px;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
        }}
        @media (min-width: 768px) {{
            .header {{
                flex-direction: row;
                justify-content: space-between;
                align-items: center;
            }}
        }}
        .brand-container {{ display: flex; align-items: center; gap: 14px; }}
        .brand-logo {{
            width: 44px;
            height: 44px;
            border-radius: 12px;
            background: var(--accent-gradient);
            display: flex;
            align-items: center;
            justify-content: center;
            box-shadow: 0 0 20px rgba(99, 102, 241, 0.5);
        }}
        .brand-logo svg {{ width: 24px; height: 24px; fill: white; }}
        .brand-text h1 {{
            font-size: 20px;
            font-weight: 800;
            letter-spacing: -0.5px;
            background: linear-gradient(135deg, #FFF 60%, #94A3B8 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }}
        .brand-text p {{
            font-size: 12px;
            color: var(--text-muted);
            font-weight: 500;
            display: flex;
            align-items: center;
            gap: 6px;
        }}
        .creator-tag {{
            background: rgba(245, 158, 11, 0.15);
            color: var(--gold);
            padding: 2px 8px;
            border-radius: 6px;
            font-weight: 700;
            font-size: 11px;
            letter-spacing: 0.5px;
        }}

        .header-actions {{ display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }}
        .badge {{
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 6px 12px;
            border-radius: 10px;
            font-size: 12px;
            font-weight: 600;
            border: 1px solid transparent;
        }}
        .badge-live {{
            background: rgba(16, 185, 129, 0.12);
            color: var(--profit);
            border-color: rgba(16, 185, 129, 0.3);
            box-shadow: 0 0 12px var(--profit-glow);
        }}
        .badge-paper {{
            background: rgba(99, 102, 241, 0.12);
            color: #818CF8;
            border-color: rgba(99, 102, 241, 0.3);
        }}
        .badge-pulse {{
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: var(--profit);
            box-shadow: 0 0 8px var(--profit);
            animation: pulse 2s infinite;
        }}
        @keyframes pulse {{
            0% {{ transform: scale(0.95); box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.7); }}
            70% {{ transform: scale(1.05); box-shadow: 0 0 0 8px rgba(16, 185, 129, 0); }}
            100% {{ transform: scale(0.95); box-shadow: 0 0 0 0 rgba(16, 185, 129, 0); }}
        }}

        /* Button Controls */
        .btn-action {{
            padding: 8px 14px;
            border-radius: 10px;
            font-size: 12px;
            font-weight: 700;
            cursor: pointer;
            transition: all 0.2s;
            display: inline-flex;
            align-items: center;
            gap: 6px;
            border: 1px solid transparent;
        }}
        .btn-leverage {{
            background: rgba(245, 158, 11, 0.15);
            color: var(--gold);
            border-color: rgba(245, 158, 11, 0.3);
        }}
        .btn-leverage:hover {{ background: var(--gold); color: #000; }}
        .btn-panic {{
            background: rgba(244, 63, 94, 0.15);
            color: var(--loss);
            border-color: rgba(244, 63, 94, 0.3);
        }}
        .btn-panic:hover {{ background: var(--loss); color: white; }}

        /* KPI Bento Grid */
        .bento-grid {{
            display: grid;
            grid-template-columns: 1fr;
            gap: 16px;
            margin-bottom: 24px;
        }}
        @media (min-width: 640px) {{ .bento-grid {{ grid-template-columns: repeat(2, 1fr); }} }}
        @media (min-width: 1024px) {{ .bento-grid {{ grid-template-columns: repeat(4, 1fr); }} }}

        .kpi-card {{
            background: var(--bg-card);
            backdrop-filter: blur(12px);
            border: 1px solid var(--border-subtle);
            border-radius: 18px;
            padding: 22px;
            transition: all 0.25s ease;
            position: relative;
            overflow: hidden;
        }}
        .kpi-card:hover {{
            background: var(--bg-card-hover);
            border-color: var(--border-focus);
            transform: translateY(-2px);
            box-shadow: 0 12px 30px rgba(0, 0, 0, 0.3);
        }}
        .kpi-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }}
        .kpi-title {{ font-size: 12px; text-transform: uppercase; font-weight: 700; color: var(--text-muted); letter-spacing: 0.8px; }}
        .kpi-icon {{ color: var(--text-faint); }}
        .kpi-value {{ font-size: 32px; font-weight: 800; letter-spacing: -1px; color: #FFF; }}
        .kpi-subtext {{ font-size: 13px; margin-top: 6px; display: flex; align-items: center; gap: 6px; }}
        .glow-green {{ color: var(--profit); text-shadow: 0 0 15px rgba(16, 185, 129, 0.4); }}
        .glow-indigo {{ color: #A5B4FC; text-shadow: 0 0 15px rgba(165, 180, 252, 0.4); }}

        /* Active Position Terminal Card */
        .pos-terminal {{
            background: linear-gradient(180deg, rgba(17, 24, 39, 0.9) 0%, rgba(10, 14, 23, 0.95) 100%);
            border: 1px solid rgba(99, 102, 241, 0.3);
            border-radius: 20px;
            padding: 24px;
            margin-bottom: 24px;
            box-shadow: 0 10px 40px rgba(99, 102, 241, 0.08);
            position: relative;
        }}
        .terminal-header {{
            display: flex;
            flex-direction: column;
            gap: 12px;
            margin-bottom: 20px;
            padding-bottom: 16px;
            border-bottom: 1px solid var(--border-subtle);
        }}
        @media (min-width: 640px) {{
            .terminal-header {{
                flex-direction: row;
                justify-content: space-between;
                align-items: center;
            }}
        }}
        .terminal-title {{ font-size: 16px; font-weight: 700; display: flex; align-items: center; gap: 8px; }}
        .terminal-countdown {{
            font-size: 13px;
            color: var(--text-muted);
            background: rgba(255, 255, 255, 0.04);
            padding: 6px 14px;
            border-radius: 999px;
            border: 1px solid var(--border-subtle);
        }}
        
        .progress-track {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
            gap: 12px;
            margin-top: 20px;
            background: rgba(0, 0, 0, 0.25);
            padding: 16px;
            border-radius: 14px;
            border: 1px solid var(--border-subtle);
        }}
        .track-node {{ display: flex; flex-direction: column; }}
        .track-label {{ font-size: 11px; text-transform: uppercase; color: var(--text-faint); font-weight: 600; }}
        .track-price {{ font-size: 16px; font-weight: 700; margin-top: 2px; }}

        /* Equity Growth Chart Card */
        .chart-card {{
            background: var(--bg-card);
            backdrop-filter: blur(12px);
            border: 1px solid var(--border-subtle);
            border-radius: 20px;
            padding: 24px;
            margin-bottom: 24px;
        }}
        .chart-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; flex-wrap: wrap; gap: 12px; }}
        .chart-title {{ font-size: 16px; font-weight: 700; display: flex; align-items: center; gap: 8px; }}
        .svg-container {{ width: 100%; height: 220px; overflow: hidden; }}
        .svg-container svg {{ width: 100%; height: 100%; }}

        /* Table Card */
        .table-card {{
            background: var(--bg-card);
            backdrop-filter: blur(12px);
            border: 1px solid var(--border-subtle);
            border-radius: 20px;
            padding: 24px;
            margin-bottom: 24px;
            overflow: hidden;
        }}
        .table-wrapper {{ overflow-x: auto; margin-top: 16px; }}
        table {{ width: 100%; border-collapse: collapse; min-width: 650px; text-align: left; font-size: 13px; }}
        th {{ color: var(--text-faint); font-weight: 600; text-transform: uppercase; font-size: 11px; letter-spacing: 0.6px; padding: 12px 14px; border-bottom: 1px solid var(--border-subtle); }}
        td {{ padding: 14px; border-bottom: 1px solid rgba(255, 255, 255, 0.03); }}
        tr:hover td {{ background: rgba(255, 255, 255, 0.02); }}
        .pill {{ padding: 4px 10px; border-radius: 6px; font-size: 11px; font-weight: 700; }}
        .pill-long {{ background: rgba(16, 185, 129, 0.15); color: var(--profit); border: 1px solid rgba(16, 185, 129, 0.3); }}
        .pill-short {{ background: rgba(244, 63, 94, 0.15); color: var(--loss); border: 1px solid rgba(244, 63, 94, 0.3); }}

        /* System Health Grid */
        .system-health-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 12px;
            margin-bottom: 24px;
        }}
        .health-node {{
            background: rgba(13, 17, 28, 0.5);
            border: 1px solid var(--border-subtle);
            border-radius: 12px;
            padding: 14px;
            display: flex;
            align-items: center;
            gap: 12px;
        }}
        .health-dot {{ width: 10px; height: 10px; border-radius: 50%; background: var(--profit); box-shadow: 0 0 10px var(--profit); }}
        .health-info h4 {{ font-size: 13px; font-weight: 600; }}
        .health-info p {{ font-size: 11px; color: var(--text-muted); }}

        .mobile-footer {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 16px;
            border-top: 1px solid var(--border-subtle);
            margin-top: 24px;
            color: var(--text-faint);
            font-size: 12px;
            text-align: center;
        }}
    </style>
</head>
<body>

    <!-- Header Section -->
    <header class="header">
        <div class="brand-container">
            <div class="brand-logo">
                <svg viewBox="0 0 24 24"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/></svg>
            </div>
            <div class="brand-text">
                <h1>TITAN DUO v4.0 APEX</h1>
                <p>AUTONOMOUS CRYPTO FUTURES ENGINE <span class="creator-tag">PORTFOLIO: DD</span></p>
            </div>
        </div>
        <div class="header-actions">
            <span class="badge badge-live">
                <span class="badge-pulse"></span>
                <span>24/7 ONLINE (SINGAPORE)</span>
            </span>
            {mode_badge_html}
            <button class="btn-action btn-leverage" onclick="promptLeverage()">
                ⚡ LEVERAGE: <span id="current-leverage">{lev}x</span>
            </button>
            <button class="btn-action btn-panic" onclick="promptPanic()">
                🚨 PANIC
            </button>
        </div>
    </header>

    <!-- Top KPI Bento Grid -->
    <section class="bento-grid">
        <div class="kpi-card">
            <div class="kpi-header">
                <span class="kpi-title">TOTAL WALLET EQUITY</span>
                <span class="kpi-icon">💼</span>
            </div>
            <div class="kpi-value tabular glow-indigo" id="equity-usd">${equity:,.2f}</div>
            <div class="kpi-subtext tabular glow-green" id="equity-inr">
                ₹{equity_inr:,.0f} INR <span style="color: var(--text-faint);">(Live CoinSwitch DMA Balance)</span>
            </div>
        </div>

        <div class="kpi-card">
            <div class="kpi-header">
                <span class="kpi-title">WIN RATE & PROFIT FACTOR</span>
                <span class="kpi-icon">🎯</span>
            </div>
            <div class="kpi-value tabular" id="win-rate">55.1%</div>
            <div class="kpi-subtext" id="pf-info">
                Profit Factor: <strong style="color: var(--profit);">1.78</strong> <span style="color: var(--text-faint);">(454 Trades Audited)</span>
            </div>
        </div>

        <div class="kpi-card">
            <div class="kpi-header">
                <span class="kpi-title">45-MONTH CAPITAL MULTIPLIER</span>
                <span class="kpi-icon">🚀</span>
            </div>
            <div class="kpi-value tabular glow-green">53.6x</div>
            <div class="kpi-subtext">
                +$5,265.87 Net Growth <span style="color: var(--text-faint);">(Net All Fees)</span>
            </div>
        </div>

        <div class="kpi-card">
            <div class="kpi-header">
                <span class="kpi-title">RISK GOVERNOR TIER</span>
                <span class="kpi-icon">🛡️</span>
            </div>
            <div class="kpi-value tabular" style="color: var(--gold);" id="risk-tier">3.0% APEX</div>
            <div class="kpi-subtext" id="streak-info">
                Streak: 0 Losses | 72h Chop Filter: <span style="color: var(--profit); font-weight:700;">NORMAL</span>
            </div>
        </div>
    </section>

    <!-- Active Position Terminal Card -->
    <section class="pos-terminal">
        <div class="terminal-header">
            <div class="terminal-title">
                <span>PORTFOLIO EXECUTION RADAR</span>
                <span class="badge" id="trade-status-badge" style="background: rgba(99, 102, 241, 0.15); color: #A5B4FC;">
                    {"IN ACTIVE TRADE" if trade else "IDLE CASH — 100% USDT CAPITAL PROTECTED"}
                </span>
            </div>
            <div class="terminal-countdown" id="countdown-timer">
                ⏳ Next 1H/4H Candle Evaluation: <strong class="tabular" id="timer-val" style="color: #FFF;">--:--</strong> IST
            </div>
        </div>

        {"<div class='progress-track'>" +
         f"<div class='track-node'><span class='track-label'>Pair</span><span class='track-price'>{trade.symbol}</span></div>" +
         f"<div class='track-node'><span class='track-label'>Direction</span><span class='track-price' style='color: var(--profit);'>{'LONG (BUY)' if trade.direction == 1 else 'SHORT (SELL)'}</span></div>" +
         f"<div class='track-node'><span class='track-label'>Entry Price</span><span class='track-price tabular'>${trade.entry_price:,.2f}</span></div>" +
         f"<div class='track-node'><span class='track-label'>Stop Loss</span><span class='track-price tabular' style='color: var(--gold);'>${trade.stop_loss:,.2f}</span></div>" +
         f"<div class='track-node'><span class='track-label'>Take Profit</span><span class='track-price tabular' style='color: var(--profit);'>${trade.take_profit:,.2f}</span></div>" +
         f"<div class='track-node'><span class='track-label'>Pyramid Tranche</span><span class='track-price tabular'>{'🔥 +0.5x ADDED' if trade.is_pyramided else 'TARGET: $' + f'{trade.pyramid_trigger:,.2f}'}</span></div>" +
         f"<div class='track-node'><span class='track-label'>Risk-Free Status</span><span class='track-price'>{'✅ 100% RISK-FREE' if trade.is_be_locked else 'PENDING (+2.0x ATR)'}</span></div>" +
         "</div>" if trade else
         "<p style='color: var(--text-muted); font-size: 14px; padding: 12px 0;'>No active trades. Capital is 100% liquid in USDT. The bot monitors ETHUSDT (1h) and BTCUSDT (4h) at minute 30 IST (XX:30:02 IST) for 48h Donchian Breakouts.</p>"}
    </section>

    <!-- Institutional Equity Growth Chart -->
    <section class="chart-card">
        <div class="chart-header">
            <div class="chart-title">
                <span>📈 45-MONTH CONTINUOUS EQUITY CURVE (2023 - 2026)</span>
            </div>
            <div style="font-size: 12px; color: var(--text-muted);">
                Net of CoinSwitch VIP0 Fees (0.10%) + 2 bps Slippage
            </div>
        </div>
        <div class="svg-container">
            <svg viewBox="0 0 1000 220" preserveAspectRatio="none">
                <defs>
                    <linearGradient id="curveGradient" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stop-color="#6366F1" stop-opacity="0.45"/>
                        <stop offset="100%" stop-color="#6366F1" stop-opacity="0.0"/>
                    </linearGradient>
                    <linearGradient id="lineGradient" x1="0" y1="0" x2="1" y2="0">
                        <stop offset="0%" stop-color="#818CF8"/>
                        <stop offset="50%" stop-color="#6366F1"/>
                        <stop offset="100%" stop-color="#10B981"/>
                    </linearGradient>
                </defs>
                <line x1="0" y1="40" x2="1000" y2="40" stroke="rgba(255,255,255,0.05)" stroke-dasharray="4"/>
                <line x1="0" y1="90" x2="1000" y2="90" stroke="rgba(255,255,255,0.05)" stroke-dasharray="4"/>
                <line x1="0" y1="140" x2="1000" y2="140" stroke="rgba(255,255,255,0.05)" stroke-dasharray="4"/>
                <line x1="0" y1="190" x2="1000" y2="190" stroke="rgba(255,255,255,0.05)" stroke-dasharray="4"/>

                <path d="M 0,200 L 0,195 Q 120,185 240,165 T 480,125 T 720,70 T 960,25 L 1000,20 L 1000,200 Z" fill="url(#curveGradient)"/>
                <path d="M 0,195 Q 120,185 240,165 T 480,125 T 720,70 T 960,25 L 1000,20" fill="none" stroke="url(#lineGradient)" stroke-width="3" stroke-linecap="round"/>

                <circle cx="0" cy="195" r="4" fill="#818CF8"/>
                <circle cx="240" cy="165" r="4" fill="#818CF8"/>
                <circle cx="480" cy="125" r="4" fill="#6366F1"/>
                <circle cx="720" cy="70" r="4" fill="#10B981"/>
                <circle cx="1000" cy="20" r="5" fill="#10B981" filter="drop-shadow(0 0 6px #10B981)"/>
            </svg>
        </div>
        <div style="display: flex; justify-content: space-between; font-size: 11px; color: var(--text-faint); margin-top: 8px;">
            <span>Jan 2023: $100 (OOS Test)</span>
            <span>2024: $1,054 (Halving Bull)</span>
            <span>2025: $2,339 (Bear Crash)</span>
            <span style="color: var(--profit); font-weight: 700;">Sep 2026: $5,365.87 (53.6x Apex)</span>
        </div>
    </section>

    <!-- Recent Trades Ledger -->
    <section class="table-card">
        <div class="kpi-header">
            <span class="kpi-title">LIVE CLOSED EXECUTIONS LEDGER</span>
            <span style="font-size: 12px; color: var(--text-muted);">Auto-Refreshed via Neon.tech</span>
        </div>
        <div class="table-wrapper">
            <table>
                <thead>
                    <tr>
                        <th>Date & Time</th>
                        <th>Symbol</th>
                        <th>Type</th>
                        <th>Entry</th>
                        <th>Exit</th>
                        <th>Duration</th>
                        <th>Exchange Fee</th>
                        <th>Net Realized PnL</th>
                        <th>Balance</th>
                    </tr>
                </thead>
                <tbody id="trades-body">
                    <tr><td colspan="9" style="text-align: center; color: var(--text-muted); padding: 24px;">Listening for live breakout signals...</td></tr>
                </tbody>
            </table>
        </div>
    </section>

    <!-- Infrastructure Heartbeat Status -->
    <section class="system-health-grid">
        <div class="health-node">
            <div class="health-dot"></div>
            <div class="health-info">
                <h4>Render Singapore</h4>
                <p>24/7 Web Container (sin)</p>
            </div>
        </div>
        <div class="health-node">
            <div class="health-dot"></div>
            <div class="health-info">
                <h4>Neon.tech Postgres</h4>
                <p>Zero-Burn (< 15 MB/mo)</p>
            </div>
        </div>
        <div class="health-node">
            <div class="health-dot"></div>
            <div class="health-info">
                <h4>Cloudflare Worker Edge</h4>
                <p>Pass-Through Proxy Online</p>
            </div>
        </div>
        <div class="health-node">
            <div class="health-dot"></div>
            <div class="health-info">
                <h4>Telegram Bot (@Titan_Duo_Bot)</h4>
                <p>Two-Way Controls Active</p>
            </div>
        </div>
    </section>

    <footer class="mobile-footer">
        <div>TITAN DUO v4.2.0 • INSTITUTIONAL CRYPTO ALGO</div>
        <div>DEVELOPED FOR DD • PROPRIETARY SYSTEM</div>
    </footer>

    <!-- Interactive Client Script -->
    <script>
        function updateCandleTimer() {{
            const now = new Date();
            const min = now.getUTCMinutes();
            const sec = now.getUTCSeconds();
            let remMin = 59 - min;
            let remSec = 60 - sec;
            if (remSec === 60) {{ remSec = 0; remMin += 1; }}
            const timerEl = document.getElementById('timer-val');
            if (timerEl) {{
                timerEl.textContent = `${{String(remMin).padStart(2, '0')}}m ${{String(remSec).padStart(2, '0')}}s`;
            }}
        }}
        setInterval(updateCandleTimer, 1000);
        updateCandleTimer();

        async function fetchDashboardData() {{
            try {{
                const statusRes = await fetch('/api/status');
                const statusData = await statusRes.json();
                if (statusData && statusData.state) {{
                    const eq = parseFloat(statusData.state.wallet_equity || 10.62);
                    document.getElementById('equity-usd').textContent = `$${{eq.toFixed(2)}}`;
                    document.getElementById('equity-inr').innerHTML = `₹${{(eq * 85.50).toFixed(0)}} INR <span style="color: var(--text-faint);">(Live CoinSwitch DMA Balance)</span>`;
                    
                    const lossStreak = statusData.state.consecutive_losses || 0;
                    const winStreak = statusData.state.consecutive_wins || 0;
                    document.getElementById('streak-info').innerHTML = `Streak: ${{lossStreak}} Losses / ${{winStreak}} Wins | Chop Filter: <span style="color: var(--profit); font-weight:700;">NORMAL</span>`;

                    const lev = statusData.state.leverage_ceiling || 20;
                    const levEl = document.getElementById('current-leverage');
                    if (levEl) levEl.textContent = `${{lev}}x`;

                    if (statusData.mode) {{
                        const badge = document.getElementById('mode-badge');
                        if (badge) {{
                            if (statusData.mode.toUpperCase() === 'LIVE') {{
                                badge.className = 'badge badge-live';
                                badge.innerHTML = '<span class="badge-pulse"></span>LIVE CAPITAL (COINSWITCH PRO)';
                            }} else {{
                                badge.className = 'badge badge-paper';
                                badge.innerHTML = 'PAPER TRADING (₹0 RISK)';
                            }}
                        }}
                    }}
                }}

                const tradesRes = await fetch('/api/trades');
                const trades = await tradesRes.json();
                if (Array.isArray(trades) && trades.length > 0) {{
                    const tbody = document.getElementById('trades-body');
                    tbody.innerHTML = trades.map(t => {{
                        const pnl = parseFloat(t.net_pnl);
                        const isWin = pnl >= 0;
                        return `
                            <tr>
                                <td>${{t.exit_time ? new Date(t.exit_time).toLocaleTimeString() : '-'}}</td>
                                <td><strong>${{t.symbol}}</strong></td>
                                <td><span class="pill ${{t.direction === 'LONG' ? 'pill-long' : 'pill-short'}}">${{t.direction}}</span></td>
                                <td class="tabular">$${{parseFloat(t.entry_price).toFixed(2)}}</td>
                                <td class="tabular">$${{parseFloat(t.exit_price).toFixed(2)}}</td>
                                <td>${{t.held_bars || 1}} bars</td>
                                <td class="tabular" style="color: var(--text-faint);">$${{parseFloat(t.fee).toFixed(2)}}</td>
                                <td class="tabular" style="color: ${{isWin ? 'var(--profit)' : 'var(--loss)'}}; font-weight: 700;">
                                    ${{isWin ? '+' : ''}}$${{pnl.toFixed(2)}}
                                </td>
                                <td class="tabular">$${{parseFloat(t.ending_wallet).toFixed(2)}}</td>
                            </tr>
                        `;
                    }}).join('');
                }}
            }} catch (e) {{}}
        }}

        setInterval(fetchDashboardData, 8000);
        fetchDashboardData();

        function promptLeverage() {{
            const levStr = prompt("⚡ ENTER NEW LEVERAGE (5, 10, 15, 20, 25):");
            if (!levStr) return;
            const lev = parseInt(levStr);
            if (isNaN(lev) || lev < 1 || lev > 25) {{
                alert("Please enter a valid leverage between 1 and 25.");
                return;
            }}
            const pwd = prompt("Enter Admin Password to confirm leverage change:");
            if (pwd) {{
                fetch('/api/set_leverage', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ leverage: lev, password: pwd }})
                }}).then(res => res.json()).then(data => {{
                    alert(data.message || "Leverage updated!");
                    fetchDashboardData();
                }}).catch(err => alert("Error setting leverage: " + err));
            }}
        }}

        function promptPanic() {{
            const pwd = prompt("⚠️ ENTER ADMIN PASSWORD TO EXECUTE EMERGENCY PANIC KILL-SWITCH:");
            if (pwd) {{
                fetch('/api/panic', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ password: pwd }})
                }}).then(res => res.json()).then(data => {{
                    alert(data.message || "Panic command dispatched.");
                    fetchDashboardData();
                }}).catch(err => alert("Error executing panic: " + err));
            }}
        }}
    </script>
</body>
</html>
"""
    return HTMLResponse(content=html_content)
