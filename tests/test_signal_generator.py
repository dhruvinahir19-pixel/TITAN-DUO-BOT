"""
UNIT TESTS: SIGNAL GENERATOR & PORTFOLIO GOVERNORS
==================================================
Verifies Single-Trade Portfolio Rule, 16-Hour Loss Cooldown,
Chop filters, and state machine transitions.
"""

import unittest
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.signal_generator import SignalGenerator, SignalResult
from core.trade_state import BotState, ActiveTrade, TradeStatus
from config import CONFIG

class TestSignalGenerator(unittest.TestCase):
    def setUp(self):
        self.sg = SignalGenerator(CONFIG)

    def test_single_active_trade_governor(self):
        # When bot already has an active trade, new signals MUST be rejected
        active_pos = ActiveTrade(
            symbol="ETHUSDT",
            direction=1,
            entry_price=2000.0,
            initial_units=0.1,
            current_units=0.1,
            stop_loss=1900.0,
            take_profit=2250.0,
            pyramid_trigger=2100.0,
            breakeven_sl=2004.0,
            atr_at_entry=50.0,
            effective_risk_pct=0.03,
            entry_timestamp="2026-09-21 14:30:00"
        )
        state = BotState(wallet_equity=100.0, active_trade=active_pos)
        
        res = self.sg.check_new_signal(
            bot_state=state,
            eth_l_sig_last=True, eth_s_sig_last=False, eth_atr_last=50.0, eth_next_open=2000.0,
            btc_l_sig_last=False, btc_s_sig_last=False, btc_atr_last=500.0, btc_next_open=60000.0,
            current_bar_idx=100
        )
        self.assertFalse(res.has_signal)
        self.assertTrue(res.governor_blocked)
        self.assertIn("Active trade already open", res.block_reason)

    def test_16_hour_loss_cooldown_governor(self):
        # If last loss was at bar 100, bar 110 (10 bars later) is STILL in cooldown
        state = BotState(wallet_equity=100.0, last_loss_bar=100, active_trade=None)
        
        res = self.sg.check_new_signal(
            bot_state=state,
            eth_l_sig_last=True, eth_s_sig_last=False, eth_atr_last=50.0, eth_next_open=2000.0,
            btc_l_sig_last=False, btc_s_sig_last=False, btc_atr_last=500.0, btc_next_open=60000.0,
            current_bar_idx=110  # Only 10 bars since loss (16 required)
        )
        self.assertFalse(res.has_signal)
        self.assertTrue(res.governor_blocked)
        self.assertIn("In loss cooldown", res.block_reason)

        # But at bar 116 (exactly 16 bars later), signal MUST pass!
        res_pass = self.sg.check_new_signal(
            bot_state=state,
            eth_l_sig_last=True, eth_s_sig_last=False, eth_atr_last=50.0, eth_next_open=2000.0,
            btc_l_sig_last=False, btc_s_sig_last=False, btc_atr_last=500.0, btc_next_open=60000.0,
            current_bar_idx=116
        )
        self.assertTrue(res_pass.has_signal)
        self.assertFalse(res_pass.governor_blocked)
        self.assertEqual(res_pass.symbol, "ETHUSDT")

    def test_eth_primary_priority(self):
        # When both ETH and BTC signal simultaneously, ETH takes priority
        state = BotState(wallet_equity=100.0, last_loss_bar=-9999, active_trade=None)
        res = self.sg.check_new_signal(
            bot_state=state,
            eth_l_sig_last=True, eth_s_sig_last=False, eth_atr_last=50.0, eth_next_open=2500.0,
            btc_l_sig_last=True, btc_s_sig_last=False, btc_atr_last=600.0, btc_next_open=65000.0,
            current_bar_idx=500
        )
        self.assertTrue(res.has_signal)
        self.assertEqual(res.symbol, "ETHUSDT")

    def test_state_json_serialization(self):
        state = BotState(
            wallet_equity=1450.25,
            consecutive_losses=1,
            consecutive_wins=0,
            last_loss_bar=340
        )
        state_dict = state.to_dict()
        restored_state = BotState.from_dict(state_dict)
        self.assertEqual(restored_state.wallet_equity, 1450.25)
        self.assertEqual(restored_state.consecutive_losses, 1)
        self.assertEqual(restored_state.last_loss_bar, 340)

if __name__ == '__main__':
    unittest.main()
