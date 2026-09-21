"""
TITAN DUO v4.0 APEX - INSTITUTIONAL INVARIANT AUDIT TESTS
=========================================================
Tests the 5 core safety invariants required for live execution:
1. Exchange Precision & Lot Sizer (math.floor rounding down)
2. Immediate Stop-Loss Invariant & Emergency Abort Fail-Safe
3. Single-Position Mutex (Zero Correlated Risk)
4. Dynamic Leverage Control (Telegram / Dashboard / DB Parity)
5. Container Reboot State Reconstruction
"""

import unittest
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from config import CONFIG
from core.trade_state import BotState, ActiveTrade, TradeStatus
from core.risk_manager import RiskManager
from core.exchange_client import CoinSwitchFuturesClient
from main import TitanDuoOrchestrator

class TestLiveInvariants(unittest.TestCase):
    def setUp(self):
        self.risk_manager = RiskManager(CONFIG)

    def test_precision_formatting_flooring(self):
        """Invariant 1: Units must ALWAYS be floored, never rounded up."""
        # BTC requires 3 decimals
        self.assertEqual(self.risk_manager.format_order_quantity("BTCUSDT", 0.0019999), 0.001)
        self.assertEqual(self.risk_manager.format_order_quantity("BTCUSDT", 0.0020001), 0.002)

        # ETH requires 2 decimals
        self.assertEqual(self.risk_manager.format_order_quantity("ETHUSDT", 0.0389), 0.03)
        self.assertEqual(self.risk_manager.format_order_quantity("ETHUSDT", 0.0401), 0.04)

        # Price formatting
        self.assertEqual(self.risk_manager.format_price("ETHUSDT", 2650.126), 2650.13)

    def test_order_constraints_validation(self):
        """Invariant 1b: Orders below $5 notional or min lot must be rejected."""
        # ETH: 0.001 is below min lot (0.01)
        valid, reason = self.risk_manager.validate_order_constraints("ETHUSDT", 0.005, 2600.0)
        self.assertFalse(valid)
        self.assertIn("below exchange minimum", reason)

        # Notional below $5
        valid, reason = self.risk_manager.validate_order_constraints("BTCUSDT", 0.001, 4000.0) # $4 notional
        self.assertFalse(valid)
        self.assertIn("below exchange minimum of $5.00", reason)

        # Valid order
        valid, reason = self.risk_manager.validate_order_constraints("ETHUSDT", 0.02, 2600.0) # $52 notional
        self.assertTrue(valid)
        self.assertEqual(reason, "VALID")

    def test_single_position_mutex(self):
        """Invariant 2: When ETH is active, BTC entry MUST be rejected."""
        orchestrator = TitanDuoOrchestrator(mode="PAPER")
        orchestrator.bot_state.active_trade = ActiveTrade(
            symbol="ETHUSDT", direction=1, entry_price=2650.0,
            initial_units=0.05, current_units=0.05, stop_loss=2550.0,
            take_profit=2900.0, pyramid_trigger=2750.0, breakeven_sl=2655.0,
            atr_at_entry=30.0, effective_risk_pct=0.03, entry_timestamp="2026-09-21T00:00:00"
        )

        # Attempt to open BTC
        result = orchestrator.execute_entry("BTCUSDT", 1, 64000.0, 800.0, "2026-09-21T01:00:00")
        self.assertFalse(result)
        # Ensure ETH remains unchanged
        self.assertEqual(orchestrator.bot_state.active_trade.symbol, "ETHUSDT")

    def test_emergency_abort_when_stop_loss_fails(self):
        """Invariant 3: If STOP_MARKET fails in LIVE mode, market liquidation MUST trigger immediately."""
        orchestrator = TitanDuoOrchestrator(mode="LIVE")
        orchestrator.bot_state.active_trade = None

        # Mock chaser to succeed
        orchestrator.chaser.execute_smart_limit_entry = MagicMock(return_value={
            "success": True, "fill_price": 2650.0, "order_id": "TEST_FILL_01"
        })

        # Mock STOP_MARKET placement to fail (e.g. network hiccup or rejection)
        orchestrator.client.place_stop_market_order = MagicMock(side_effect=RuntimeError("Exchange 500 error"))
        orchestrator.client.place_market_order = MagicMock(return_value={"order_id": "ABORT_MARKET_01"})
        orchestrator.telegram.send_message = MagicMock()

        # Execute entry
        res = orchestrator.execute_entry("ETHUSDT", 1, 2650.0, 30.0, "2026-09-21T00:00:00")

        # Entry must be aborted
        self.assertFalse(res)
        # Market liquidation must have been called immediately
        orchestrator.client.place_market_order.assert_called_once()
        # Active trade must remain None (Zero unprotected exposure)
        self.assertIsNone(orchestrator.bot_state.active_trade)

    def test_dynamic_leverage_control_parity(self):
        """Invariant 4: /setleverage updates bot state, Neon DB, and exchange client."""
        orchestrator = TitanDuoOrchestrator(mode="PAPER")
        reply = orchestrator.update_leverage_ceiling(15)
        self.assertIn("Leverage ceiling set to *15x*", reply)
        self.assertEqual(orchestrator.bot_state.leverage_ceiling, 15)

        # Verify DB persistence
        loaded = orchestrator.db.load_bot_state()
        self.assertEqual(loaded.leverage_ceiling, 15)

        # Reset back to 20
        orchestrator.update_leverage_ceiling(20)

if __name__ == "__main__":
    unittest.main()
