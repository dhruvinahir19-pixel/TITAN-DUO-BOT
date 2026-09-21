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
from typing import Optional, Dict, Any, List
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
        logger.info(f"Loaded bot state from Neon. Wallet: ${self.bot_state.wallet_equity:,.2f} | Leverage: {self.bot_state.leverage_ceiling}x | Status: {'IN_TRADE' if self.bot_state.active_trade else 'IDLE'}")

        self.client = CoinSwitchFuturesClient(config=config)
        self.chaser = SmartOrderChaser(self.client, config)
        self.engine = StrategyEngine(config)
        self.telegram = TelegramNotifier(config)

        # 2. Sync Real Wallet Balance on Startup if in LIVE Mode
        if self.mode == "LIVE":
            self.sync_real_wallet_balance()

        # 3. Control Flags
        self._is_running = False
        self._stop_event = threading.Event()
        self._last_evaluated_hour: Optional[int] = None
        self._setup_telegram_callbacks()
        self._inject_web_dependencies()

    def sync_real_wallet_balance(self) -> float:
        """
        Queries CoinSwitch Futures USDT balance and syncs internal wallet equity.
        """
        try:
            wb = self.client.get_wallet_balance()
            for asset_item in wb.get("base_asset_balances", []):
                if asset_item.get("base_asset") == "USDT":
                    bal_str = asset_item.get("balances", {}).get("total_balance", "0")
                    real_bal = float(bal_str)
                    if real_bal > 0:
                        logger.info(f"Live CoinSwitch Futures balance detected: ${real_bal:,.2f} USDT")
                        self.bot_state.wallet_equity = real_bal
                        self.db.save_bot_state(self.bot_state)
                        return real_bal
        except Exception as e:
            logger.warning(f"Could not sync live wallet balance: {e}. Keeping current: ${self.bot_state.wallet_equity:,.2f}")
        return self.bot_state.wallet_equity

    def _inject_web_dependencies(self):
        """Injects shared state into FastAPI web dashboard module."""
        web_module.db_manager = self.db
        web_module.current_bot_state = self.bot_state
        web_module.panic_callback = self.trigger_panic_killswitch
        web_module.pause_callback = self.pause_trading
        web_module.resume_callback = self.resume_trading
        web_module.set_leverage_callback = self.update_leverage_ceiling

    def _setup_telegram_callbacks(self):
        """Registers interactive command dispatcher for Telegram bot."""
        def handle_telegram_cmd(cmd_text: str) -> str:
            parts = cmd_text.split()
            cmd = parts[0].lower()
            if cmd == "/status":
                return self._cmd_status()
            elif cmd == "/levels":
                return self._cmd_levels()
            elif cmd == "/setleverage":
                if len(parts) > 1 and parts[1].isdigit():
                    return self.update_leverage_ceiling(int(parts[1]))
                return "⚠️ Usage: `/setleverage <5-25>` (e.g. `/setleverage 20`)"
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
                    "⚙️ `/setleverage <5-25>` — Update exchange leverage ceiling\n"
                    "⏸️ `/pause` — Pause new signal entries\n"
                    "▶️ `/resume` — Resume autonomous entries\n"
                    "🚨 `/panic` — Emergency market-close & cancel\n"
                    "━━━━━━━━━━━━━━━━━━━━━━"
                )
            return "Unknown command. Use /help to see available commands."

        self.telegram.register_command_handler(handle_telegram_cmd)

    def update_leverage_ceiling(self, leverage: int) -> str:
        """
        Dynamically updates leverage ceiling via Telegram or Web Dashboard.
        Applies setting to CoinSwitch Pro and persists in Neon database.
        """
        if not (1 <= leverage <= 25):
            return "⚠️ Invalid leverage: must be between 1x and 25x."

        self.bot_state.leverage_ceiling = leverage
        self.db.save_bot_state(self.bot_state)

        # If bot is idle, update leverage on CoinSwitch exchange
        exchange_msg = ""
        if self.mode == "LIVE" and self.bot_state.active_trade is None:
            try:
                self.client.set_leverage("ETHUSDT", leverage)
                self.client.set_leverage("BTCUSDT", leverage)
                exchange_msg = f" (Updated on CoinSwitch Pro to {leverage}x)"
            except Exception as e:
                exchange_msg = f" (CoinSwitch update notice: {e})"

        logger.info(f"Leverage ceiling set to {leverage}x by user command.")
        return f"✅ *LEVERAGE UPDATED*: Leverage ceiling set to *{leverage}x*{exchange_msg}. Saved to database."

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
            f"⚡ *Leverage*: `{self.bot_state.leverage_ceiling}x`\n"
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
            
            if self.mode == "LIVE":
                opposing_side = "SELL" if trade.direction == 1 else "BUY"
                self.client.place_market_order(trade.symbol, opposing_side, trade.current_units, reduce_only=True)

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
    # Order Execution & Stop-Loss Invariant
    # --------------------------------------------------------------------------

    def execute_entry(
        self,
        symbol: str,
        direction: int,
        entry_price: float,
        atr: float,
        timestamp: str
    ) -> bool:
        """
        Executes order entry with:
        1. Single-Position Mutex (Zero Correlated Risk)
        2. Decimal Precision Sizing
        3. Dynamic Pegged Limit Order Chaser
        4. Hardware STOP_MARKET Placement
        5. Emergency Immediate Liquidation Fail-Safe if SL fails
        """
        # Mutex Check: Strictly one open position at a time
        if self.bot_state.active_trade is not None:
            logger.warning(f"Rejecting entry for {symbol}: Position already open in {self.bot_state.active_trade.symbol}")
            return False

        levels = self.engine.risk_manager.calculate_trade_levels(symbol, direction, entry_price, atr)
        sizing = self.engine.risk_manager.calculate_position_size(
            wallet_equity=self.bot_state.wallet_equity,
            entry_price=entry_price,
            stop_loss=levels['stop_loss'],
            consec_losses=self.bot_state.consecutive_losses,
            consec_wins=self.bot_state.consecutive_wins,
            leverage_ceiling=self.bot_state.leverage_ceiling
        )

        raw_units = sizing['units']
        units = self.engine.risk_manager.format_order_quantity(symbol, raw_units)
        is_valid, reason = self.engine.risk_manager.validate_order_constraints(symbol, units, entry_price)

        if not is_valid:
            logger.warning(f"Order constraints not met for {symbol}: {reason}")
            return False

        if self.mode == "LIVE":
            # 1. Place limit order with SmartOrderChaser
            chase_result = self.chaser.execute_smart_limit_entry(
                symbol=symbol,
                direction=direction,
                quantity=units,
                signal_candle_close=entry_price
            )

            if not chase_result.get("success"):
                logger.warning(f"Order entry aborted: {chase_result.get('reason')}")
                return False

            fill_price = chase_result.get("fill_price", entry_price)
            levels = self.engine.risk_manager.calculate_trade_levels(symbol, direction, fill_price, atr)

            # 2. CRITICAL INVARIANT: Immediate Hardware Stop-Loss Order Placement
            sl_side = "SELL" if direction == 1 else "BUY"
            sl_price = self.engine.risk_manager.format_price(symbol, levels['stop_loss'])
            sl_order_id = None

            try:
                sl_res = self.client.place_stop_market_order(
                    symbol=symbol,
                    side=sl_side,
                    trigger_price=sl_price,
                    reduce_only=True
                )
                sl_order_id = sl_res.get("order_id")
                logger.info(f"Hardware STOP_MARKET placed on CoinSwitch @ {sl_price} (ID: {sl_order_id})")
            except Exception as sl_err:
                logger.critical(f"FATAL: Stop-Loss order placement failed on exchange: {sl_err}")
                # EMERGENCY ABORT FAIL-SAFE: Liquidate immediately via Market Order
                try:
                    self.client.place_market_order(symbol, sl_side, units, reduce_only=True)
                    self.telegram.send_message(
                        f"🚨 *CRITICAL FAIL-SAFE ACTIVATED*\n"
                        f"Stop-Loss order rejected by CoinSwitch ({sl_err})!\n"
                        f"Position for `{symbol}` was IMMEDIATELY LIQUIDATED at market to prevent unhedged capital exposure."
                    )
                except Exception as abort_err:
                    logger.critical(f"FATAL: Emergency liquidation failed: {abort_err}")
                    self.telegram.send_message(f"🚨🚨 *FATAL*: Stop-Loss failed AND market liquidation failed: {abort_err}")
                return False

            active_trade = ActiveTrade(
                symbol=symbol,
                direction=direction,
                entry_price=fill_price,
                initial_units=units,
                current_units=units,
                stop_loss=levels['stop_loss'],
                take_profit=levels['take_profit'],
                pyramid_trigger=levels['pyramid_trigger'],
                breakeven_sl=levels['breakeven_sl'],
                atr_at_entry=atr,
                effective_risk_pct=sizing['effective_risk_pct'],
                entry_timestamp=timestamp,
                status=TradeStatus.IN_TRADE,
                order_id=chase_result.get("order_id"),
                exchange_sl_order_id=sl_order_id
            )
        else:
            # PAPER SIMULATION MODE
            active_trade = ActiveTrade(
                symbol=symbol,
                direction=direction,
                entry_price=entry_price,
                initial_units=units,
                current_units=units,
                stop_loss=levels['stop_loss'],
                take_profit=levels['take_profit'],
                pyramid_trigger=levels['pyramid_trigger'],
                breakeven_sl=levels['breakeven_sl'],
                atr_at_entry=atr,
                effective_risk_pct=sizing['effective_risk_pct'],
                entry_timestamp=timestamp,
                status=TradeStatus.IN_TRADE
            )

        self.bot_state.active_trade = active_trade
        self.db.save_bot_state(self.bot_state)
        self.telegram.notify_trade_opened(active_trade, self.bot_state.wallet_equity)
        logger.info(f"Position successfully established for {symbol} ({'LONG' if direction == 1 else 'SHORT'}) @ {active_trade.entry_price}")
        return True

    def get_seconds_until_next_candle_close(self) -> float:
        """
        Calculates seconds until next hourly candle close (XX:30:02 IST = XX:00:02 UTC).
        """
        now_utc = datetime.now(timezone.utc)
        next_hour = (now_utc + timedelta(hours=1)).replace(minute=0, second=2, microsecond=0)
        delta_sec = (next_hour - now_utc).total_seconds()
        return max(delta_sec, 2.0)

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
                                trigger_price=self.engine.risk_manager.format_price(trade.symbol, trade.stop_loss),
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
                if self.mode == "LIVE":
                    try:
                        self.client.cancel_all_open_orders(trade.symbol)
                        opposing_side = "SELL" if trade.direction == 1 else "BUY"
                        self.client.place_market_order(trade.symbol, opposing_side, trade.current_units, reduce_only=True)
                    except Exception as e:
                        logger.error(f"Live market close error: {e}")

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
    # Hourly Candle Evaluation (Minute 30 IST / Minute 00 UTC)
    # --------------------------------------------------------------------------

    def evaluate_hourly_candle(self):
        """
        Executes at XX:30:02 IST (when 1h candle closes).
        Queries fresh candles from CoinSwitch, calculates indicators,
        and executes entries if signals trigger.
        """
        now_dt = datetime.now(timezone.utc)
        logger.info(f"Evaluating hourly candle at {now_dt.strftime('%Y-%m-%d %H:%M:%S UTC')}...")

        if self.bot_state.is_paused:
            logger.info("Bot is PAUSED. Skipping candle evaluation.")
            return

        if self.bot_state.active_trade is not None:
            logger.info(f"Single-Position Mutex Active: Already in trade on {self.bot_state.active_trade.symbol}. Skipping scan.")
            return

        try:
            # 1. Fetch ETH 1h candles
            resp_eth = self.client._send_request(
                "GET", "/trade/api/v2/futures/klines",
                params={"symbol": "ETHUSDT", "exchange": "EXCHANGE_2", "interval": "60", "limit": 220}
            )
            if resp_eth.status_code != 200:
                logger.error(f"Failed to fetch ETH klines: {resp_eth.text}")
                return

            raw_eth = resp_eth.json().get("data", [])
            eth_records = [
                {"open": float(k["o"]), "high": float(k["h"]), "low": float(k["l"]), "close": float(k["c"]), "volume": float(k["volume"])}
                for k in reversed(raw_eth)
            ]
            df_eth = pd.DataFrame(eth_records)
            ind_eth = self.engine.signal_generator.calculate_eth_indicators(df_eth)
            l_sig_eth, s_sig_eth = self.engine.signal_generator.evaluate_eth_signals_vectorized(ind_eth)

            eth_has_long = bool(l_sig_eth[-1])
            eth_has_short = bool(s_sig_eth[-1])
            eth_close = float(df_eth["close"].iloc[-1])
            eth_atr = float(ind_eth["atr"][-1])

            # Check ETH Signal
            if eth_has_long or eth_has_short:
                direction = 1 if eth_has_long else -1
                timestamp_str = now_dt.isoformat()
                logger.info(f"ETH Signal Triggered! Direction: {'LONG' if direction == 1 else 'SHORT'} @ {eth_close}")
                self.execute_entry("ETHUSDT", direction, eth_close, eth_atr, timestamp_str)
                return

            # 2. If no ETH signal, check BTC 4h candles
            resp_btc = self.client._send_request(
                "GET", "/trade/api/v2/futures/klines",
                params={"symbol": "BTCUSDT", "exchange": "EXCHANGE_2", "interval": "240", "limit": 50}
            )
            if resp_btc.status_code == 200:
                raw_btc = resp_btc.json().get("data", [])
                btc_records = [
                    {"open": float(k["o"]), "high": float(k["h"]), "low": float(k["l"]), "close": float(k["c"]), "volume": float(k["volume"])}
                    for k in reversed(raw_btc)
                ]
                df_btc = pd.DataFrame(btc_records)
                ind_btc = self.engine.signal_generator.calculate_btc_indicators(df_btc)
                l_sig_btc, s_sig_btc = self.engine.signal_generator.evaluate_btc_signals_vectorized(ind_btc)

                btc_has_long = bool(l_sig_btc[-1])
                btc_has_short = bool(s_sig_btc[-1])
                btc_close = float(df_btc["close"].iloc[-1])
                btc_atr = float(ind_btc["atr"][-1])

                if btc_has_long or btc_has_short:
                    direction = 1 if btc_has_long else -1
                    timestamp_str = now_dt.isoformat()
                    logger.info(f"BTC Signal Triggered! Direction: {'LONG' if direction == 1 else 'SHORT'} @ {btc_close}")
                    self.execute_entry("BTCUSDT", direction, btc_close, btc_atr, timestamp_str)
                    return

            logger.info("Hourly scan complete: No breakout signals. Portfolio remains 100% USDT Cash.")

        except Exception as e:
            logger.error(f"Error evaluating hourly candle: {e}")

    # --------------------------------------------------------------------------
    # Main Daemon Loop
    # --------------------------------------------------------------------------

    def run_main_loop(self):
        """
        The continuous dual-speed trading daemon loop.
        """
        self._is_running = True
        self.telegram.start_polling()

        logger.info("Titan Duo Autonomous Trading Daemon successfully started.")

        last_fast_check = time.time()

        while self._is_running and not self._stop_event.is_set():
            try:
                now_utc = datetime.now(timezone.utc)
                now_ts = time.time()

                # 1. Fast 10-Second Watcher Loop (Active Position Tracking)
                if self.bot_state.active_trade is not None:
                    if now_ts - last_fast_check >= self.config.ORDER_CHASER_POLL_INTERVAL:
                        self.check_active_trade_lifecycle()
                        last_fast_check = now_ts

                # 2. Hourly Candle Evaluation at XX:00:02 UTC (= XX:30:02 IST)
                if now_utc.minute == 0 and now_utc.second >= 2 and self._last_evaluated_hour != now_utc.hour:
                    self._last_evaluated_hour = now_utc.hour
                    self.evaluate_hourly_candle()

                time.sleep(1.0)

            except KeyboardInterrupt:
                logger.info("Shutdown signal received.")
                break
            except Exception as e:
                logger.error(f"Unexpected error in main loop: {e}")
                time.sleep(5)

        self.stop()

    def stop(self):
        """Graceful shutdown sequence."""
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
    
    start_server_in_background(host="0.0.0.0", port=port)
    bot = TitanDuoOrchestrator(mode=mode)
    bot.run_main_loop()
