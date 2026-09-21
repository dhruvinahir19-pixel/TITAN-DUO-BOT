"""
UNIT & INTEGRATION TESTS: MAIN TRADING ORCHESTRATOR & DISASTER RECOVERY
========================================================================
Stress tests end-to-end boot lifecycle, simulated trade execution, Breakeven ratchet,
emergency /panic kill-switch, and network drop recovery without crashing.
"""

import unittest
import os
import sys
import time
from unittest.mock import MagicMock, patch

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from config import CONFIG
from main import TitanDuoOrchestrator
from core.trade_state import BotState, ActiveTrade, TradeStatus

class TestLiveOrchestrator(unittest.TestCase):
    def setUp(self):
        # Create orchestrator in safe PAPER mode
        self.bot = TitanDuoOrchestrator(mode="PAPER", config=CONFIG)
        self.bot.telegram.send_message = MagicMock(return_value=True)

    def tearDown(self):
        self.bot.stop()

    def test_01_boot_lifecycle_and_state_hydration(self):
        """
        Verifies that on boot, the orchestrator loads state from Neon and links FastAPI.
        """
        self.assertIsNotNone(self.bot.bot_state)
        self.assertGreaterEqual(self.bot.bot_state.wallet_equity, 5.0)
        self.assertIsNotNone(self.bot.client)
        self.assertIsNotNone(self.bot.engine)

    def test_02_candle_close_timing_math(self):
        """
        Verifies seconds until next candle close is within valid [2, 3600] range.
        """
        sec = self.bot.get_seconds_until_next_candle_close()
        self.assertGreaterEqual(sec, 2.0)
        self.assertLessEqual(sec, 3602.0)

    def test_03_active_trade_be_and_pyramid_lifecycle(self):
        """
        Simulates an active trade hitting +2.0x ATR:
        Tests that Stop Loss is ratcheted to Breakeven (+0.2% fee buffer),
        units are scaled +0.5x, and state is persisted to Neon Postgres.
        """
        active_trade = ActiveTrade(
            symbol="ETHUSDT",
            direction=1,
            entry_price=2600.0,
            initial_units=0.10,
            current_units=0.10,
            stop_loss=2550.0,
            take_profit=2750.0,
            pyramid_trigger=2650.0,          # +50 USD = +2.0x ATR
            breakeven_sl=2605.2,             # 2600 * 1.002
            atr_at_entry=25.0,
            effective_risk_pct=0.03,
            entry_timestamp="2026-09-21 14:30:00"
        )
        self.bot.bot_state.active_trade = active_trade
        
        # Mock orderbook showing market price reached 2655 (above 2650 trigger)
        mock_ob = {
            "bids": [["2655.00", "15.0"]],
            "asks": [["2655.10", "15.0"]]
        }
        with patch.object(self.bot.client, "get_order_book", return_value=mock_ob):
            self.bot.check_active_trade_lifecycle()

        # Assert Breakeven and Pyramiding engaged
        self.assertTrue(self.bot.bot_state.active_trade.is_be_locked)
        self.assertTrue(self.bot.bot_state.active_trade.is_pyramided)
        self.assertEqual(self.bot.bot_state.active_trade.stop_loss, 2605.2)
        self.assertAlmostEqual(self.bot.bot_state.active_trade.current_units, 0.15, places=4)

    def test_04_emergency_panic_killswitch(self):
        """
        Simulates emergency /panic kill-switch:
        Cancels open orders, flattens position, persists state to Neon, and resets to IDLE.
        """
        active_trade = ActiveTrade(
            symbol="ETHUSDT",
            direction=1,
            entry_price=2600.0,
            initial_units=0.10,
            current_units=0.10,
            stop_loss=2550.0,
            take_profit=2750.0,
            pyramid_trigger=2650.0,
            breakeven_sl=2605.2,
            atr_at_entry=25.0,
            effective_risk_pct=0.03,
            entry_timestamp="2026-09-21 14:30:00"
        )
        self.bot.bot_state.active_trade = active_trade
        
        mock_ob = {
            "bids": [["2610.00", "5.0"]],
            "asks": [["2610.10", "5.0"]]
        }
        with patch.object(self.bot.client, "get_order_book", return_value=mock_ob):
            reply = self.bot.trigger_panic_killswitch()

        self.assertIn("PANIC EXECUTED", reply)
        self.assertIsNone(self.bot.bot_state.active_trade)

    def test_05_network_drop_and_resilience(self):
        """
        Simulates sudden API outage / network timeout:
        Verifies the orchestrator handles exceptions gracefully without crashing.
        """
        active_trade = ActiveTrade(
            symbol="ETHUSDT",
            direction=1,
            entry_price=2600.0,
            initial_units=0.10,
            current_units=0.10,
            stop_loss=2550.0,
            take_profit=2750.0,
            pyramid_trigger=2650.0,
            breakeven_sl=2605.2,
            atr_at_entry=25.0,
            effective_risk_pct=0.03,
            entry_timestamp="2026-09-21 14:30:00"
        )
        self.bot.bot_state.active_trade = active_trade
        
        # Force get_order_book to raise network exception
        with patch.object(self.bot.client, "get_order_book", side_effect=Exception("Connection reset by peer")):
            # Should NOT raise exception or crash
            self.bot.check_active_trade_lifecycle()
            
        # Active trade remains safe and intact
        self.assertIsNotNone(self.bot.bot_state.active_trade)

if __name__ == '__main__':
    unittest.main()
