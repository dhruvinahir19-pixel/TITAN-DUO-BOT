"""
UNIT TESTS: TECHNICAL INDICATORS
=================================
Verifies mathematical correctness of Pine-compatible EMA, ATR, ADX, Donchian, and Chop Governor.
"""

import unittest
import numpy as np
import pandas as pd
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.indicators import (
    calc_ema_numba,
    calc_atr_numba,
    calc_adx_numba,
    calc_rsi_numba,
    calc_wpr_numba,
    calc_donchian_channels,
    calc_crossover_chop_count
)

class TestIndicators(unittest.TestCase):
    def setUp(self):
        np.random.seed(42)
        n = 500
        self.close = 2000.0 + np.cumsum(np.random.randn(n) * 10.0)
        self.high = self.close + np.random.uniform(5.0, 20.0, n)
        self.low = self.close - np.random.uniform(5.0, 20.0, n)
        self.volume = np.random.uniform(100.0, 1000.0, n)

    def test_ema_numba_validity(self):
        ema20 = calc_ema_numba(self.close, 20)
        self.assertEqual(len(ema20), len(self.close))
        self.assertEqual(ema20[0], self.close[0])
        # All values should be valid floats
        self.assertFalse(np.isnan(ema20).any())

    def test_atr_numba_bounds(self):
        atr14 = calc_atr_numba(self.high, self.low, self.close, 14)
        self.assertEqual(len(atr14), len(self.close))
        self.assertEqual(atr14[0], self.high[0] - self.low[0])
        # ATR must be strictly positive
        self.assertTrue((atr14 > 0).all())

    def test_adx_numba_bounds(self):
        adx14 = calc_adx_numba(self.high, self.low, self.close, 14)
        self.assertEqual(len(adx14), len(self.close))
        # ADX must be bounded between 0 and 100
        self.assertTrue((adx14 >= 0.0).all())
        self.assertTrue((adx14 <= 100.0).all())

    def test_wpr_numba_bounds(self):
        wpr14 = calc_wpr_numba(self.close, 14)
        self.assertEqual(len(wpr14), len(self.close))
        valid_wpr = wpr14[13:]
        # WPR is bounded between -100 and 0
        self.assertTrue((valid_wpr >= -100.0).all())
        self.assertTrue((valid_wpr <= 0.0).all())

    def test_donchian_channels_shift(self):
        upper, lower = calc_donchian_channels(self.high, self.low, period=48)
        self.assertEqual(len(upper), len(self.high))
        # At index 48, upper must be the max of high from 0 to 47
        expected_high_48 = np.max(self.high[:48])
        self.assertAlmostEqual(upper[48], expected_high_48, places=5)
        expected_low_48 = np.min(self.low[:48])
        self.assertAlmostEqual(lower[48], expected_low_48, places=5)

    def test_crossover_chop_count(self):
        n = 100
        fast = np.zeros(n)
        slow = np.zeros(n)
        for i in range(20):
            fast[i] = 10.0 if i % 2 == 0 else -10.0
            slow[i] = 0.0
            
        chop = calc_crossover_chop_count(fast, slow, window=20)
        self.assertGreaterEqual(chop[19], 15)

if __name__ == '__main__':
    unittest.main()
