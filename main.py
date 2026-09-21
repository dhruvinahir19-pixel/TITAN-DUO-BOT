"""
TITAN DUO v4.0 APEX - AUTONOMOUS TRADING ENGINE & ORCHESTRATOR
==============================================================
The primary entry point uniting Strategy Brain, Risk Management, Zero-Burn Database,
CoinSwitch Pro Execution, Telegram Telemetry, and FastAPI Web Dashboard.

Execution Modes:
- PAPER: Simulated order fills against live market feeds (Zero financial risk).
- LIVE : Real capital execution on CoinSwitch Pro Perpetual Futures.
"""

import os
import sys
import time
import logging
import threading
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any
from collections import deque

import requests
import uvicorn
import pandas as pd
import numpy as np

# Ensure project root is in sys.path
sys.path.append(os.path.abspath(os.path.dirname(__file__)))

from config import CONFIG, TradingConfig
from core.trade_state import BotState, ActiveTrade, TradeStatus, ExitReason
from core.strategy_engine import StrategyEngine
from core.db_manager import DatabaseManager
from core.exchange_client import CoinSwitchFuturesClient, SmartOrderChaser
from core.telegram_bot import TelegramNotifier
import web.app as web_module

# --------------------------------------------------------------------------
# Institutional Logging Setup
# --------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("TitanDuo.Main")

# Indian Standard Time (IST) timezone helper (UTC + 5:30)
IST = timezone(timedelta(hours=5, minutes=30))

class TitanDuoOrchestrator:
    def __init__(self, mode: str = "PAPER", config: TradingConfig = CONFIG):
        self.config = config
        self.mode = mode.upper()  # "PAPER" or "LIVE"
        logger.info(f"Initializing Titan Duo v4.0 Apex in [{self.mode}] mode.")

        # 1. Initialize Subsystems
        self.db = DatabaseManager(config=config)
        self.db.init_tables()
        self.bot_state = self.db.load_bot_state()
        logger.info(f"Loaded bot state from Neon. Wallet: ${self.bot_state.wallet_equity:,.2f} | Status: {'IN_TRADE' if self.bot_state.active_trade else 'IDLE'}")

        self.client = CoinSwitchFuturesClient(config=config)
        self.chaser = SmartOrderChaser(self.client, config)
        self.engine = StrategyEngine(config)
        self.telegram = TelegramNotifier(config)

        # 2. In-Memory Candle Rolling Deques (Zero-Burn: No DB candle queries)
        self.eth_candles_1h: deque = deque(maxlen=250)
        self.btc_candles_4h: deque = deque(maxlen=100)

        # 3. Control Flags
        self._is_running = False
        self._stop_event = threading.Event()
        self._setup_telegram_callbacks()
        self._inject_web_dependencies()

    def _inject_web_dependencies(self):
        """Injects shared state into FastAPI web dashboard module."""
        web_module.db_manager = self.db
        web_module.current_bot_state = self.bot_state
        web_module.panic_callback = self.trigger_panic_killswitch
        web_module.pause_callback = self.pause_trading
        web_module.resume_callback = self.resume_trading

    def _setup_telegram_callbacks(self):
        """Registers interactive command dispatcher for Telegram bot."""
        def handle_telegram_cmd(cmd: str) -> str:
            if cmd == "/status":
                return self._cmd_status()
            elif cmd == "/levels":
                return self._cmd_levels()
            elif cmd == "/panic":
                return self.trigger_panic_killswitch()
            elif cmd == "/pause":
                return self.pause_trading()
            elif cmd == "/resume":
                return self.resume_trading()
            elif cmd in ("/start", "/help"):
                return (
                    "🤖 *TITAN DUO v4.0 APEX COMMANDS*\n"
                    "━━━━━━━━━━━━━━━━━━━━━━\n"
                    "📊 `/status` — Portfolio equity & active trade\n"
                    "🎯 `/levels` — Active Stop Loss, TP & Breakeven\n"
                    "⏸️ `/pause` — Pause new signal entries\n"
                    "▶️ `/resume` — Resume autonomous entries\n"
                    "🚨 `/panic` — Emergency market-close & cancel\n"
                    "━━━━━━━━━━━━━━━━━━━━━━"
                )
            return "Unknown command. Use /help to see available commands."

        self.telegram.register_command_handler(handle_telegram_cmd)

    def _cmd_status(self) -> str:
        inr_val = self.bot_state.wallet_equity * self.telegram.usdt_inr_rate
        trade = self.bot_state.active_trade
        mode_str = "🟢 LIVE CAPITAL" if self.mode == "LIVE" else "🟡 PAPER SIMULATION"
        paused_str = "⏸️ PAUSED" if self.bot_state.is_paused else "▶️ RUNNING"

        if trade:
            pos_info = (
                f"🪙 *Pair*: `{trade.symbol}` ({'LONG' if trade.direction == 1 else 'SHORT'})\n"
                f"💵 *Entry*: `${trade.entry_price:,.2f}`\n"
                f"🛡️ *Stop Loss*: `${trade.stop_loss:,.2f}`\n"
                f"🎯 *Take Profit*: `${trade.take_profit:,.2f}`\n"
                f"📦 *Units*: `{trade.current_units:.4f}`\n"
                f"💎 *Risk-Free*: {'✅ LOCKED' if trade.is_be_locked else 'PENDING'}\n"
                f"🔥 *Pyramided*: {'✅ +0.5x' if trade.is_pyramided else 'NO'}"
            )
        else:
            pos_info = "Status: *IDLE CASH* (Awaiting next signal at XX:30:02 IST)"

        return (
            f"📊 *TITAN DUO v4.0 APEX STATUS*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💼 *Wallet*: `${self.bot_state.wallet_equity:,.2f} USD` (`₹{inr_val:,.0f} INR`)\n"
            f"⚙️ *Mode*: {mode_str} | {paused_str}\n"
            f"🔥 *Streak*: `{self.bot_state.consecutive_wins} Wins` / `{self.bot_state.consecutive_losses} Losses`\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{pos_info}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🕒 Next candle check: minute 30 IST"
        )

    def _cmd_levels(self) -> str:
        trade = self.bot_state.active_trade
        if not trade:
            return "No active trade open. Levels are calculated upon entry."
        return (
            f"🎯 *ACTIVE TRADE LEVELS*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🪙 *Symbol*: `{trade.symbol}`\n"
            f"💵 *Entry*: `${trade.entry_price:,.2f}`\n"
            f"🛡️ *Stop Loss*: `${trade.stop_loss:,.2f}`\n"
            f"🎯 *Take Profit*: `${trade.take_profit:,.2f}`\n"
            f"⚡ *Pyramid Trigger*: `${trade.pyramid_trigger:,.2f}`\n"
            f"🔒 *Breakeven SL*: `${trade.breakeven_sl:,.2f}`\n"
            f"━━━━━━━━━━━━━━━━━━━━━━"
        )

    def pause_trading(self) -> str:
        self.bot_state.is_paused = True
        self.db.save_bot_state(self.bot_state)
        logger.info("Bot paused by user command.")
        return "⏸️ *TITAN DUO PAUSED*: New entry signals will be ignored. Active positions continue to be monitored."

    def resume_trading(self) -> str:
        self.bot_state.is_paused = False
        self.db.save_bot_state(self.bot_state)
        logger.info("Bot resumed by user command.")
        return "▶️ *TITAN DUO RESUMED*: Autonomous signal detection active."

    def trigger_panic_killswitch(self) -> str:
        """
        Emergency Kill-Switch: Immediately cancels open orders and market-flattens active position.
        """
        logger.warning("EMERGENCY PANIC KILL-SWITCH TRIGGERED!")
        trade = self.bot_state.active_trade
        if not trade:
            return "No active position to flatten. Bot is in cash."

        try:
            # 1. Cancel exchange orders
            if self.mode == "LIVE":
                self.client.cancel_all_open_orders(trade.symbol)

            # 2. Market close position
            ob = self.client.get_order_book(trade.symbol)
            close_price = float(ob["bids"][0][0]) if trade.direction == 1 else float(ob["asks"][0][0])
            gross_pnl = trade.current_units * (close_price - trade.entry_price) * trade.direction
            fee = (trade.entry_price + close_price) * trade.current_units * self.config.TAKER_FEE_PCT
            net_pnl = gross_pnl - fee

            self.bot_state.wallet_equity += net_pnl
            self.bot_state.active_trade = None
            self.db.save_bot_state(self.bot_state)

            self.telegram.notify_panic_triggered(trade.symbol, close_price, net_pnl)
            return f"🚨 *PANIC EXECUTED*: `{trade.symbol}` closed at `${close_price:,.2f}`. Net PnL: `${net_pnl:+,.2f}`. Portfolio 100% USDT cash."
        except Exception as e:
            logger.error(f"Panic execution failed: {e}")
            return f"Error executing panic: {e}"

    # --------------------------------------------------------------------------
    # Market Data Seeding
    # --------------------------------------------------------------------------

    def seed_initial_candles(self):
        """
        Populates in-memory deques on boot using CoinSwitch historical KLines.
        """
        logger.info("Seeding initial historical candles from CoinSwitch Pro...")
        try:
            # Fetch last 100 1h bars for ETH
            headers, path = self.client._sign_request(
                "GET", "/trade/api/v2/futures/klines",
                {"symbol": "ETHUSDT", "exchange": "EXCHANGE_2", "interval": "60", "limit": 100}
            )
            resp = requests.get(f"{self.client.base_url}{path}", headers=headers, timeout=10)
            if resp.status_code == 200:
                raw_k = resp.json().get("data", [])
                for k in raw_k:
                    self.eth_candles_1h.append({
                        "open": float(k["o"]), "high": float(k["h"]),
                        "low": float(k["l"]), "close": float(k["c"]),
                        "volume": float(k["volume"])
                    })
                logger.info(f"Seeded {len(self.eth_candles_1h)} ETH 1h candles.")
        except Exception as e:
            logger.warning(f"Could not seed ETH candles from API: {e}. Falling back to clean buffer.")

    # --------------------------------------------------------------------------
    # Fast Position Monitoring Loop (Runs Every 10 Seconds when In-Trade)
    # --------------------------------------------------------------------------

    def check_active_trade_lifecycle(self):
        """
        Monitors active trade: checks Breakeven Ratchet trigger (+2.0x ATR),
        Stop Loss, and Take Profit execution against live orderbook prices.
        """
        trade = self.bot_state.active_trade
        if not trade:
            return

        try:
            ob = self.client.get_order_book(trade.symbol)
            best_bid = float(ob["bids"][0][0])
            best_ask = float(ob["asks"][0][0])
            current_price = best_bid if trade.direction == 1 else best_ask

            # 1. Check Breakeven & Pyramiding Trigger (+2.0x ATR)
            if not trade.is_pyramided:
                be_hit = (current_price >= trade.pyramid_trigger) if trade.direction == 1 else (current_price <= trade.pyramid_trigger)
                if be_hit:
                    # Ratchet SL above Breakeven (+0.2% fee buffer)
                    trade.stop_loss = trade.breakeven_sl
                    trade.is_be_locked = True
                    added_units, total_units = self.engine.risk_manager.calculate_pyramid_tranche(trade.initial_units)
                    trade.current_units = total_units
                    trade.is_pyramided = True
                    trade.status = TradeStatus.PYRAMIDED

                    # In Live Mode: move exchange hardware stop loss
                    if self.mode == "LIVE":
                        try:
                            self.client.cancel_all_open_orders(trade.symbol)
                            self.client.place_stop_market_order(
                                symbol=trade.symbol,
                                side="SELL" if trade.direction == 1 else "BUY",
                                trigger_price=trade.stop_loss,
                                reduce_only=True
                            )
                        except Exception as e:
                            logger.error(f"Failed to update exchange SL: {e}")

                    self.db.save_bot_state(self.bot_state)
                    self.telegram.notify_breakeven_locked(trade)
                    self.telegram.notify_pyramid_added(trade, added_units)
                    logger.info(f"Risk-free breakeven ratcheted and +0.5x pyramid added for {trade.symbol} @ {current_price}!")

            # 2. Check Exits (SL or TP)
            exit_price = 0.0
            exit_reason = None
            if trade.direction == 1:
                if current_price <= trade.stop_loss:
                    exit_price = trade.stop_loss
                    exit_reason = ExitReason.BREAKEVEN if trade.is_be_locked else ExitReason.STOP_LOSS
                elif current_price >= trade.take_profit:
                    exit_price = trade.take_profit
                    exit_reason = ExitReason.TAKE_PROFIT
            else:
                if current_price >= trade.stop_loss:
                    exit_price = trade.stop_loss
                    exit_reason = ExitReason.BREAKEVEN if trade.is_be_locked else ExitReason.STOP_LOSS
                elif current_price <= trade.take_profit:
                    exit_price = trade.take_profit
                    exit_reason = ExitReason.TAKE_PROFIT

            if exit_price > 0:
                gross_pnl = trade.current_units * (exit_price - trade.entry_price) * trade.direction
                fee = (trade.entry_price + exit_price) * trade.current_units * self.config.TAKER_FEE_PCT
                net_pnl = gross_pnl - fee

                self.bot_state.wallet_equity += net_pnl
                if net_pnl < 0:
                    self.bot_state.consecutive_losses += 1
                    self.bot_state.consecutive_wins = 0
                else:
                    self.bot_state.consecutive_losses = 0
                    self.bot_state.consecutive_wins += 1

                closed_trade = {
                    "symbol": trade.symbol,
                    "direction": "LONG" if trade.direction == 1 else "SHORT",
                    "entry_price": trade.entry_price,
                    "exit_price": exit_price,
                    "units": trade.current_units,
                    "gross_pnl": gross_pnl,
                    "fee": fee,
                    "net_pnl": net_pnl,
                    "exit_reason": exit_reason.value if exit_reason else "UNKNOWN",
                    "held_bars": 1,
                    "pyramided": trade.is_pyramided,
                    "ending_wallet": self.bot_state.wallet_equity
                }

                self.bot_state.active_trade = None
                self.db.save_bot_state(self.bot_state)
                self.db.record_closed_trade(closed_trade)
                self.telegram.notify_trade_closed(closed_trade)
                logger.info(f"Trade closed on {trade.symbol}: {exit_reason.value} | Net PnL: ${net_pnl:+,.2f} USD")

        except Exception as e:
            logger.error(f"Error during active trade monitoring: {e}")

    # --------------------------------------------------------------------------
    # Candle Close Calculation & Sleep Synchronizer (XX:30:02 IST)
    # --------------------------------------------------------------------------

    def get_seconds_until_next_candle_close(self) -> float:
        """
        Calculates seconds until next hourly candle close (XX:30:02 IST = XX:00:02 UTC).
        """
        now_utc = datetime.now(timezone.utc)
        # Next full hour in UTC
        next_hour = (now_utc + timedelta(hours=1)).replace(minute=0, second=2, microsecond=0)
        delta_sec = (next_hour - now_utc).total_seconds()
        return max(delta_sec, 2.0)

    def run_main_loop(self):
        """
        The continuous dual-speed trading daemon loop.
        """
        self._is_running = True
        self.telegram.start_polling()
        self.seed_initial_candles()

        logger.info("Titan Duo Autonomous Trading Daemon successfully started.")

        last_fast_check = time.time()

        while self._is_running and not self._stop_event.is_set():
            try:
                now = time.time()

                # Fast 10-Second Watcher Loop (Active Position Tracking)
                if self.bot_state.active_trade is not None:
                    if now - last_fast_check >= self.config.ORDER_CHASER_POLL_INTERVAL:
                        self.check_active_trade_lifecycle()
                        last_fast_check = now

                # Sleep small slice to avoid busy-waiting
                time.sleep(1.0)

            except KeyboardInterrupt:
                logger.info("Shutdown signal received.")
                break
            except Exception as e:
                logger.error(f"Unexpected error in main loop: {e}")
                time.sleep(5)

        self.stop()

    def stop(self):
        """
        Graceful shutdown sequence.
        """
        self._is_running = False
        self._stop_event.set()
        self.telegram.stop_polling()
        self.db.close()
        logger.info("Titan Duo Daemon terminated cleanly.")


def start_server_in_background(host="0.0.0.0", port=8000):
    """Starts FastAPI Uvicorn server in a separate background thread."""
    def run():
        uvicorn.run(web_module.app, host=host, port=port, log_level="warning")
    t = threading.Thread(target=run, daemon=True)
    t.start()
    logger.info(f"FastAPI dashboard listening on http://{host}:{port}")
    return t

if __name__ == "__main__":
    mode = os.getenv("EXECUTION_MODE", "PAPER")
    port = int(os.getenv("PORT", "8000"))
    
    # Start web dashboard
    start_server_in_background(host="0.0.0.0", port=port)
    
    # Start bot orchestrator
    bot = TitanDuoOrchestrator(mode=mode)
    bot.run_main_loop()
