"""
TITAN DUO v4.0 APEX - TELEGRAM BOT NOTIFIER & TWO-WAY CONTROLLER
================================================================
Delivers real-time mobile push notifications for trades, risk-free ratchets,
and pyramiding additions, while providing interactive command controls (/status, /panic).
"""

import logging
import threading
import time
from typing import Optional, Dict, Any, Callable

import requests
from config import CONFIG, TradingConfig
from core.trade_state import BotState, ActiveTrade, TradeStatus

logger = logging.getLogger("TitanDuo.Telegram")

class TelegramNotifier:
    def __init__(self, config: TradingConfig = CONFIG):
        self.config = config
        self.token = config.TELEGRAM_BOT_TOKEN
        self.chat_id = config.TELEGRAM_CHAT_ID
        self.base_url = f"https://api.telegram.org/bot{self.token}" if self.token else ""
        self.usdt_inr_rate = 85.50  # Default indicative exchange rate

        self._polling_active = False
        self._polling_thread: Optional[threading.Thread] = None
        self._last_update_id = 0
        self._command_handler_callback: Optional[Callable[[str], str]] = None

    def send_message(self, text: str) -> bool:
        """
        Sends formatted Markdown notification to the authorized Telegram chat.
        """
        if not self.base_url or not self.chat_id:
            logger.warning("Telegram token or chat ID missing. Skipping notification.")
            return False

        url = f"{self.base_url}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True
        }
        try:
            resp = requests.post(url, json=payload, timeout=8)
            if resp.status_code == 200:
                return True
            else:
                logger.error(f"Telegram send failed ({resp.status_code}): {resp.text}")
                return False
        except Exception as e:
            logger.error(f"Telegram error: {e}")
            return False

    def notify_trade_opened(self, trade: ActiveTrade, wallet_equity: float):
        """
        Alert: New position opened.
        """
        direction_emoji = "🟢 *LONG (BUY)*" if trade.direction == 1 else "🔴 *SHORT (SELL)*"
        notional_usd = trade.initial_units * trade.entry_price
        notional_inr = notional_usd * self.usdt_inr_rate
        tp_mult = self.config.ETH_TP_ATR_MULT if "ETH" in trade.symbol else self.config.BTC_TP_ATR_MULT

        msg = (
            f"🚀 *TITAN DUO v4.0 APEX: NEW TRADE OPENED*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🪙 *Pair*: `{trade.symbol}`\n"
            f"📈 *Direction*: {direction_emoji}\n"
            f"💵 *Entry Price*: `${trade.entry_price:,.2f}`\n"
            f"📦 *Position Size*: `{trade.initial_units:.4f}` (~`${notional_usd:,.2f}` / `₹{notional_inr:,.0f}`)\n"
            f"🛡️ *Initial Stop Loss*: `${trade.stop_loss:,.2f}` (2.0x ATR)\n"
            f"🎯 *Take Profit*: `${trade.take_profit:,.2f}` ({tp_mult}x ATR)\n"
            f"⚡ *Pyramid Trigger*: `${trade.pyramid_trigger:,.2f}` (+2.0x ATR)\n"
            f"⚖️ *Account Risk*: `{trade.effective_risk_pct * 100:.2f}%` of `${wallet_equity:,.2f}`\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔒 Native Stop Loss placed directly on CoinSwitch matching engine."
        )
        self.send_message(msg)

    def notify_breakeven_locked(self, trade: ActiveTrade):
        """
        Alert: Price reached +2.0x ATR -> Stop Loss ratcheted to Breakeven (+fees).
        """
        msg = (
            f"🛡️ *TITAN DUO: BREAKEVEN RATIO LOCKED (100% RISK-FREE)*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🪙 *Pair*: `{trade.symbol}`\n"
            f"🎯 *Trigger*: Price moved *+2.0x ATR* into profit!\n"
            f"🛡️ *New Stop Loss*: `${trade.stop_loss:,.2f}` (Entry + 0.20% fee buffer)\n"
            f"💎 *Capital at Risk*: *$0.00 USD (Net Zero Risk)*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"✅ All CoinSwitch round-trip fees (0.10%) are covered. This trade cannot lose money."
        )
        self.send_message(msg)

    def notify_pyramid_added(self, trade: ActiveTrade, added_units: float):
        """
        Alert: Asymmetric Pyramiding tranche added.
        """
        notional_usd = trade.current_units * trade.entry_price
        msg = (
            f"🚀 *TITAN DUO: ASYMMETRIC PYRAMID ADDED (+0.5x)*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🪙 *Pair*: `{trade.symbol}`\n"
            f"➕ *Added Tranche*: `+{added_units:.4f}` units\n"
            f"📦 *Total Position*: `{trade.current_units:.4f}` (~`${notional_usd:,.2f}`)\n"
            f"🛡️ *Stop Loss*: Locked at Breakeven `${trade.stop_loss:,.2f}`\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔥 Running with 1.5x leverage completely on house money for maximum compound yield!"
        )
        self.send_message(msg)

    def notify_trade_closed(self, closed_trade: Dict[str, Any]):
        """
        Alert: Trade officially closed on exchange.
        """
        pnl = closed_trade["net_pnl"]
        ending_wallet = closed_trade["ending_wallet"]
        pnl_emoji = "🎉 *PROFITABLE TRADE*" if pnl >= 0 else "🛑 *CONTROLLED LOSS*"
        pnl_inr = pnl * self.usdt_inr_rate
        wallet_inr = ending_wallet * self.usdt_inr_rate

        msg = (
            f"{pnl_emoji}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🪙 *Pair*: `{closed_trade['symbol']}` ({closed_trade['direction']})\n"
            f"🚪 *Exit Reason*: `{closed_trade['exit_reason']}`\n"
            f"💵 *Exit Price*: `${closed_trade['exit_price']:,.2f}`\n"
            f"⏳ *Held Duration*: `{closed_trade['held_bars']} bars`\n"
            f"💰 *Gross PnL*: `${closed_trade['gross_pnl']:+,.2f}`\n"
            f"🧾 *CoinSwitch Fees*: `-${closed_trade['fee']:,.2f}`\n"
            f"💎 *Net PnL*: `${pnl:+,.2f} USD` (`{pnl_inr:+,.0f} INR`)\n"
            f"💼 *Updated Balance*: `${ending_wallet:,.2f} USD` (`₹{wallet_inr:,.0f} INR`)\n"
            f"━━━━━━━━━━━━━━━━━━━━━━"
        )
        self.send_message(msg)

    def notify_panic_triggered(self, symbol: str, closed_price: float, net_pnl: float):
        """
        Alert: Panic Kill-Switch manually invoked.
        """
        msg = (
            f"🚨 *TITAN DUO: EMERGENCY PANIC KILL-SWITCH TRIGGERED*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"All pending limit and stop orders CANCELLED.\n"
            f"Active `{symbol}` position MARKET-CLOSED at `${closed_price:,.2f}`.\n"
            f"Realized PnL: `${net_pnl:+,.2f} USD`\n"
            f"Portfolio safely flattened to 100% USDT cash."
        )
        self.send_message(msg)

    def notify_daily_digest(self, state: BotState, summary: Dict[str, Any]):
        """
        Alert: Daily 00:00 UTC performance summary.
        """
        wallet_inr = state.wallet_equity * self.usdt_inr_rate
        pos_str = f"`{state.active_trade.symbol} {state.active_trade.direction}`" if state.active_trade else "None (IDLE Cash)"

        msg = (
            f"🌙 *TITAN DUO: DAILY 24H PERFORMANCE DIGEST*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💼 *Total Equity*: `${state.wallet_equity:,.2f} USD` (`₹{wallet_inr:,.0f} INR`)\n"
            f"📊 *Win Rate*: `{summary.get('win_rate_pct', 0):.1f}%` ({summary.get('win_count', 0)}W / {summary.get('loss_count', 0)}L)\n"
            f"📈 *Profit Factor*: `{summary.get('profit_factor', 0):.2f}`\n"
            f"📦 *Active Position*: {pos_str}\n"
            f"🔥 *Winning Streak*: `{state.consecutive_wins}` | *Loss Streak*: `{state.consecutive_losses}`\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"System 100% healthy. Render keep-alive online."
        )
        self.send_message(msg)

    # --------------------------------------------------------------------------
    # Two-Way Interactive Command Processing
    # --------------------------------------------------------------------------

    def register_command_handler(self, handler: Callable[[str], str]):
        """
        Registers callback function to handle bot control commands.
        """
        self._command_handler_callback = handler

    def start_polling(self):
        """
        Starts lightweight Telegram update poller in a daemon background thread.
        """
        if self._polling_active:
            return
        self._polling_active = True
        self._polling_thread = threading.Thread(target=self._poll_updates_loop, daemon=True)
        self._polling_thread.start()
        logger.info("Telegram command polling thread started.")

    def stop_polling(self):
        """
        Stops the polling thread gracefully.
        """
        self._polling_active = False

    def _poll_updates_loop(self):
        """
        Long-polling loop fetching incoming updates from Telegram servers.
        """
        while self._polling_active:
            try:
                url = f"{self.base_url}/getUpdates"
                params = {"offset": self._last_update_id + 1, "timeout": 5}
                resp = requests.get(url, params=params, timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                    for update in data.get("result", []):
                        self._last_update_id = update["update_id"]
                        msg = update.get("message", {})
                        text = msg.get("text", "").strip()
                        sender_id = str(msg.get("chat", {}).get("id", ""))
                        
                        # Strict Security Check: Verify sender matches authorized chat ID
                        if sender_id != str(self.chat_id):
                            logger.warning(f"Unauthorized command attempt from user ID {sender_id}: {text}")
                            continue

                        if text.startswith("/"):
                            self._handle_user_command(text)
            except Exception as e:
                time.sleep(2)

    def _handle_user_command(self, command_text: str):
        """
        Dispatches incoming user command with full argument string.
        """
        command_clean = command_text.strip()
        cmd = command_clean.split()[0].lower()
        if self._command_handler_callback:
            reply = self._command_handler_callback(command_clean)
            self.send_message(reply)
        else:
            if cmd in ("/start", "/help"):
                help_msg = (
                    f"🤖 *TITAN DUO v4.0 APEX COMMANDS*\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"📊 `/status` — Live portfolio balance & active trade\n"
                    f"🎯 `/levels` — View active Stop Loss & Take Profit\n"
                    f"⚙️ `/setleverage <5-25>` — Update exchange leverage ceiling\n"
                    f"⏸️ `/pause` — Temporarily stop taking new trades\n"
                    f"▶️ `/resume` — Resume autonomous trading\n"
                    f"🚨 `/panic` — Emergency market-close & cancel all\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━"
                )
                self.send_message(help_msg)
