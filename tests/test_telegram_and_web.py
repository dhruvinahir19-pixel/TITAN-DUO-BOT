"""
UNIT & INTEGRATION TESTS: TELEGRAM BOT & FASTAPI WEB DASHBOARD
==============================================================
Verifies message formatting, command processing, and FastAPI endpoint routes (/ping, /api/status, /).
"""

import unittest
import os
import sys
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from config import CONFIG
from core.trade_state import BotState, ActiveTrade, TradeStatus
from core.telegram_bot import TelegramNotifier
import web.app as web_module

class TestTelegramAndWeb(unittest.TestCase):
    def setUp(self):
        self.telegram = TelegramNotifier(CONFIG)
        self.client = TestClient(web_module.app)
        
        # Inject state into web app
        web_module.current_bot_state = BotState(
            wallet_equity=150.0,
            consecutive_losses=0,
            consecutive_wins=2
        )

    def test_01_telegram_trade_opened_formatting(self):
        trade = ActiveTrade(
            symbol="ETHUSDT",
            direction=1,
            entry_price=2650.0,
            initial_units=0.1,
            current_units=0.1,
            stop_loss=2597.0,
            take_profit=2782.5,
            pyramid_trigger=2703.0,
            breakeven_sl=2655.3,
            atr_at_entry=26.5,
            effective_risk_pct=0.03,
            entry_timestamp="2026-09-21 14:30:00"
        )
        with patch.object(self.telegram, 'send_message', return_value=True) as mock_send:
            self.telegram.notify_trade_opened(trade, wallet_equity=100.0)
            mock_send.assert_called_once()
            msg = mock_send.call_args[0][0]
            self.assertIn("NEW TRADE OPENED", msg)
            self.assertIn("ETHUSDT", msg)
            self.assertIn("$2,650.00", msg)
            self.assertIn("2.0x ATR", msg)

    def test_02_telegram_breakeven_locked_formatting(self):
        trade = ActiveTrade(
            symbol="ETHUSDT",
            direction=1,
            entry_price=2650.0,
            initial_units=0.1,
            current_units=0.1,
            stop_loss=2655.3,
            take_profit=2782.5,
            pyramid_trigger=2703.0,
            breakeven_sl=2655.3,
            atr_at_entry=26.5,
            effective_risk_pct=0.03,
            entry_timestamp="2026-09-21 14:30:00",
            is_be_locked=True
        )
        with patch.object(self.telegram, 'send_message', return_value=True) as mock_send:
            self.telegram.notify_breakeven_locked(trade)
            mock_send.assert_called_once()
            msg = mock_send.call_args[0][0]
            self.assertIn("BREAKEVEN RATIO LOCKED", msg)
            self.assertIn("100% RISK-FREE", msg)
            self.assertIn("$2,655.30", msg)

    def test_03_telegram_trade_closed_formatting(self):
        closed_trade = {
            "symbol": "ETHUSDT",
            "direction": "LONG",
            "entry_price": 2650.0,
            "exit_price": 2782.5,
            "units": 0.15,
            "gross_pnl": 19.88,
            "fee": 0.41,
            "net_pnl": 19.47,
            "exit_reason": "TP",
            "held_bars": 12,
            "ending_wallet": 119.47
        }
        with patch.object(self.telegram, 'send_message', return_value=True) as mock_send:
            self.telegram.notify_trade_closed(closed_trade)
            mock_send.assert_called_once()
            msg = mock_send.call_args[0][0]
            self.assertIn("PROFITABLE TRADE", msg)
            self.assertIn("$+19.47 USD", msg)
            self.assertIn("$119.47 USD", msg)

    def test_04_fastapi_ping_endpoint(self):
        """
        Tests the /ping keep-alive endpoint used by cron-job.org.
        """
        response = self.client.get("/ping")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "healthy")
        self.assertEqual(data["wallet_equity_usd"], 150.0)
        self.assertIn("uptime", data)

    def test_05_fastapi_dashboard_html_render(self):
        """
        Tests that root GET / serves the HTML dashboard.
        """
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("TITAN DUO v4.0 APEX", response.text)
        self.assertIn("TOTAL WALLET EQUITY", response.text)

    def test_06_fastapi_api_status_endpoint(self):
        """
        Tests GET /api/status JSON endpoint.
        """
        response = self.client.get("/api/status")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("state", data)
        self.assertEqual(data["state"]["wallet_equity"], 150.0)

    def test_07_fastapi_password_protected_controls(self):
        """
        Verifies that control endpoints reject incorrect passwords with 401.
        """
        # Unauthorized attempt
        bad_resp = self.client.post("/api/pause", json={"password": "wrong_password"})
        self.assertEqual(bad_resp.status_code, 401)

        # Authorized attempt
        web_module.pause_callback = MagicMock()
        good_resp = self.client.post("/api/pause", json={"password": CONFIG.ADMIN_PASSWORD})
        self.assertEqual(good_resp.status_code, 200)
        web_module.pause_callback.assert_called_once()

if __name__ == '__main__':
    unittest.main()
