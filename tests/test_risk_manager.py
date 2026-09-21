"""
UNIT TESTS: RISK MANAGER & POSITION SIZING
==========================================
Verifies streak risk scaling, 5.0x hard leverage cap, and Breakeven / Pyramid math.
"""

import unittest
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.risk_manager import RiskManager
from config import CONFIG

class TestRiskManager(unittest.TestCase):
    def setUp(self):
        self.rm = RiskManager(CONFIG)

    def test_streak_risk_scaling(self):
        # 0 losses, 0 wins -> Base 3.0%
        self.assertAlmostEqual(self.rm.calculate_effective_risk_pct(0, 0), 0.03)
        # 0 losses, 1 win -> Base 3.0%
        self.assertAlmostEqual(self.rm.calculate_effective_risk_pct(0, 1), 0.03)
        # 0 losses, 2 wins -> Boosted 3.75%
        self.assertAlmostEqual(self.rm.calculate_effective_risk_pct(0, 2), 0.0375)
        # 1 loss -> Scaled down 50% to 1.50%
        self.assertAlmostEqual(self.rm.calculate_effective_risk_pct(1, 0), 0.015)
        # 2 losses -> Preservation mode 0.75%
        self.assertAlmostEqual(self.rm.calculate_effective_risk_pct(2, 0), 0.0075)
        # 5 losses -> Preservation mode 0.75%
        self.assertAlmostEqual(self.rm.calculate_effective_risk_pct(5, 0), 0.0075)

    def test_normal_position_sizing(self):
        # Wallet: $100. Entry: $2,000. SL: $1,960. (Unit risk: $40)
        # 3% risk of $100 = $3.00.
        # Expected units: 3.00 / 40 = 0.075
        # Notional value: 0.075 * 2000 = $150.00 (1.5x leverage)
        res = self.rm.calculate_position_size(
            wallet_equity=100.0,
            entry_price=2000.0,
            stop_loss=1960.0,
            consec_losses=0,
            consec_wins=0
        )
        self.assertAlmostEqual(res['units'], 0.075, places=5)
        self.assertAlmostEqual(res['notional_value'], 150.0, places=2)
        self.assertFalse(res['leverage_capped'])
        self.assertAlmostEqual(res['effective_leverage'], 1.5, places=2)

    def test_hard_5x_leverage_ceiling(self):
        # Extreme tight stop: Entry $2,000, SL $1,999 (Unit risk: $1)
        # Uncapped risk of $3.00 / $1 = 3.0 units ($6,000 notional = 60x leverage!)
        # Hard cap of 5.0x must engage: max notional = $100 * 5.0 = $500.00
        # Capped units: $500 / 2000 = 0.25 units
        res = self.rm.calculate_position_size(
            wallet_equity=100.0,
            entry_price=2000.0,
            stop_loss=1999.0,
            consec_losses=0,
            consec_wins=0
        )
        self.assertTrue(res['leverage_capped'])
        self.assertAlmostEqual(res['notional_value'], 500.0, places=2)
        self.assertAlmostEqual(res['units'], 0.25, places=4)
        self.assertAlmostEqual(res['effective_leverage'], 5.0, places=2)

    def test_trade_levels_long(self):
        # Entry $2,500, ATR $50
        levels = self.rm.calculate_trade_levels("ETHUSDT", 1, 2500.0, 50.0)
        self.assertEqual(levels['stop_loss'], 2500.0 - (2.0 * 50.0))       # 2400.0
        self.assertEqual(levels['take_profit'], 2500.0 + (5.0 * 50.0))     # 2750.0
        self.assertEqual(levels['pyramid_trigger'], 2500.0 + (2.0 * 50.0)) # 2600.0
        # Breakeven SL: 2500 * 1.002 = 2505.0 (+0.2% buffer covers 0.10% fees)
        self.assertAlmostEqual(levels['breakeven_sl'], 2505.0, places=2)

    def test_trade_levels_short(self):
        # Entry $2,500, ATR $50
        levels = self.rm.calculate_trade_levels("ETHUSDT", -1, 2500.0, 50.0)
        self.assertEqual(levels['stop_loss'], 2500.0 + (2.0 * 50.0))       # 2600.0
        self.assertEqual(levels['take_profit'], 2500.0 - (5.0 * 50.0))     # 2250.0
        self.assertEqual(levels['pyramid_trigger'], 2500.0 - (2.0 * 50.0)) # 2400.0
        # Breakeven SL: 2500 * 0.998 = 2495.0
        self.assertAlmostEqual(levels['breakeven_sl'], 2495.0, places=2)

    def test_pyramid_tranche_math(self):
        added, total = self.rm.calculate_pyramid_tranche(1.0)
        self.assertAlmostEqual(added, 0.5, places=4)
        self.assertAlmostEqual(total, 1.5, places=4)

if __name__ == '__main__':
    unittest.main()
