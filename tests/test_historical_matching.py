"""
END-TO-END VERIFICATION: 45-MONTH HISTORICAL AUDIT MATCHING
===========================================================
Executes the production StrategyEngine across the full 45-month dataset
(32,592 hourly candles from Jan 1, 2023 to Sep 19, 2026).
Asserts 100% exact parity with the verified institutional research benchmarks.
"""

import unittest
import numpy as np
import pandas as pd
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from config import CONFIG
from core.trade_state import BotState
from core.strategy_engine import StrategyEngine

DATA_DIR = "/home/user/crypto_research/data"

class TestHistoricalMatching(unittest.TestCase):
    def test_full_45_month_benchmark_parity(self):
        # Load continuous 45-month data (32,592 bars)
        df_eth = pd.read_parquet(f"{DATA_DIR}/ETHUSDT_45m_1h.parquet")
        df_btc = pd.read_parquet(f"{DATA_DIR}/BTCUSDT_45m_1h.parquet")
        n = len(df_eth)
        
        engine = StrategyEngine(CONFIG)
        bot_state = BotState(wallet_equity=100.0)
        
        # 1. Pre-calculate indicators using production SignalGenerator
        eth_ind = engine.signal_generator.calculate_eth_indicators(df_eth)
        eth_l_sig, eth_s_sig = engine.signal_generator.evaluate_eth_signals_vectorized(eth_ind)
        
        # 2. Resample BTC to 4h and calculate BTC indicators
        df_btc_4h = df_btc.resample('4h').agg({
            'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'
        }).dropna()
        btc_ind_4h = engine.signal_generator.calculate_btc_indicators(df_btc_4h)
        btc_l_sig_4h, btc_s_sig_4h = engine.signal_generator.evaluate_btc_signals_vectorized(btc_ind_4h)
        
        df_btc_4h['l_sig'] = btc_l_sig_4h
        df_btc_4h['s_sig'] = btc_s_sig_4h
        df_btc_4h['atr'] = btc_ind_4h['atr']
        
        # Re-index BTC 4h signals to 1h time grid (shifted by 1 bar to prevent lookahead)
        df_btc_mapped = df_btc_4h[['l_sig', 's_sig', 'atr']].shift(1).reindex(df_btc.index, method='ffill').fillna(False)
        btc_l_sig = df_btc_mapped['l_sig'].values
        btc_s_sig = df_btc_mapped['s_sig'].values
        btc_atr = df_btc_mapped['atr'].values
        
        eth_high = df_eth['high'].values.astype(np.float64)
        eth_low = df_eth['low'].values.astype(np.float64)
        eth_open = df_eth['open'].values.astype(np.float64)
        eth_close = df_eth['close'].values.astype(np.float64)
        eth_atr = eth_ind['atr']
        
        btc_high = df_btc['high'].values.astype(np.float64)
        btc_low = df_btc['low'].values.astype(np.float64)
        btc_open = df_btc['open'].values.astype(np.float64)
        btc_close = df_btc['close'].values.astype(np.float64)
        
        trades = []
        equity_curve = [100.0]
        
        # 3. Step through 32,592 hourly bars sequentially
        for i in range(1, n):
            # Manage open trade
            if bot_state.active_trade is not None:
                sym = bot_state.active_trade.symbol
                h = eth_high[i] if "ETH" in sym else btc_high[i]
                l = eth_low[i] if "ETH" in sym else btc_low[i]
                o = eth_open[i] if "ETH" in sym else btc_open[i]
                c = eth_close[i] if "ETH" in sym else btc_close[i]
                
                opp_sig = False
                if bot_state.active_trade.direction == 1:
                    opp_sig = (eth_s_sig[i-1] if "ETH" in sym else btc_s_sig[i-1])
                else:
                    opp_sig = (eth_l_sig[i-1] if "ETH" in sym else btc_l_sig[i-1])
                    
                res = engine.process_bar_lifecycle(
                    bot_state=bot_state,
                    symbol=sym,
                    high=h,
                    low=l,
                    open_price=o,
                    close_price=c,
                    bar_idx=i,
                    opposing_signal=opp_sig
                )
                if res['action'] == "TRADE_EXITED":
                    trades.append(res['closed_trade'])
                    equity_curve.append(bot_state.wallet_equity)

            # Check for new entry signal
            if bot_state.active_trade is None and i < n - 1:
                sig_res = engine.signal_generator.check_new_signal(
                    bot_state=bot_state,
                    eth_l_sig_last=bool(eth_l_sig[i-1]),
                    eth_s_sig_last=bool(eth_s_sig[i-1]),
                    eth_atr_last=float(eth_atr[i-1]),
                    eth_next_open=float(eth_open[i]),
                    btc_l_sig_last=bool(btc_l_sig[i-1]),
                    btc_s_sig_last=bool(btc_s_sig[i-1]),
                    btc_atr_last=float(btc_atr[i-1]),
                    btc_next_open=float(btc_open[i]),
                    current_bar_idx=i,
                    timestamp=str(df_eth.index[i])
                )
                
                if sig_res.has_signal and not sig_res.governor_blocked:
                    engine.open_trade_from_signal(
                        bot_state=bot_state,
                        signal=sig_res,
                        bar_idx=i,
                        timestamp=str(df_eth.index[i])
                    )

        # 4. Metric Calculations
        total_trades = len(trades)
        wins = [t for t in trades if t['net_pnl'] > 0]
        losses = [t for t in trades if t['net_pnl'] < 0]
        win_rate = len(wins) / total_trades if total_trades > 0 else 0.0
        gross_profit = sum(t['net_pnl'] for t in wins)
        gross_loss = abs(sum(t['net_pnl'] for t in losses))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0.0
        
        # Max Drawdown calculation
        eq = np.array(equity_curve)
        peak = np.maximum.accumulate(eq)
        dd = (peak - eq) / peak
        max_dd = np.max(dd)

        print("\n" + "=" * 65)
        print("TITAN DUO v4.0 APEX - PRODUCTION ENGINE VALIDATION RESULTS")
        print("=" * 65)
        print(f"Total Bars Simulated : {n:,} continuous hours (45 Months)")
        print(f"Starting Wallet      : $100.00 (₹8,500 INR)")
        print(f"Ending Wallet        : ${bot_state.wallet_equity:,.2f} USD")
        print(f"Total Multiplier     : {bot_state.wallet_equity / 100.0:.1f}x Growth")
        print(f"Total Closed Trades  : {total_trades}")
        print(f"Win Rate             : {win_rate * 100:.2f}% ({len(wins)} Wins / {len(losses)} Losses)")
        print(f"Profit Factor (Net)  : {profit_factor:.3f}")
        print(f"Max Portfolio DD     : {max_dd * 100:.2f}%")
        print("=" * 65)

        # 5. Parity Assertions
        self.assertEqual(total_trades, 454)
        self.assertAlmostEqual(win_rate, 0.55066, places=4)
        self.assertAlmostEqual(profit_factor, 1.777, places=2)
        self.assertAlmostEqual(bot_state.wallet_equity, 5365.87, delta=1.0)
        self.assertLess(max_dd, 0.205)

if __name__ == '__main__':
    unittest.main()
