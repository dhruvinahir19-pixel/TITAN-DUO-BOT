"""
TITAN DUO v4.0 APEX - SIGNAL GENERATION & REGIME GATING ENGINE
==============================================================
Evaluates multi-timeframe breakout signals for ETHUSDT (1h) and BTCUSDT (4h),
enforcing the 72-Hour Crossover Chop Governor, Single Active Trade Rule,
and 16-Hour Loss Cooldown Governor.
"""

from typing import Optional, Dict, Any
from dataclasses import dataclass
import numpy as np
import pandas as pd

from config import CONFIG, TradingConfig
from core.indicators import (
    calc_ema_numba,
    calc_atr_numba,
    calc_adx_numba,
    calc_rsi_numba,
    calc_wpr_numba,
    calc_donchian_channels,
    calc_crossover_chop_count
)
from core.trade_state import BotState

@dataclass
class SignalResult:
    has_signal: bool
    symbol: Optional[str] = None
    direction: int = 0                  # +1 for LONG, -1 for SHORT
    entry_price: float = 0.0
    atr: float = 0.0
    timestamp: Optional[str] = None
    governor_blocked: bool = False
    block_reason: Optional[str] = None

class SignalGenerator:
    def __init__(self, config: TradingConfig = CONFIG):
        self.config = config

    def calculate_eth_indicators(self, df_eth: pd.DataFrame) -> Dict[str, np.ndarray]:
        """
        Calculates all required technical indicators for ETH 1h candles.
        """
        close = df_eth['close'].values.astype(np.float64)
        high = df_eth['high'].values.astype(np.float64)
        low = df_eth['low'].values.astype(np.float64)
        vol = df_eth['volume'].values.astype(np.float64)
        
        atr = calc_atr_numba(high, low, close, self.config.ETH_ATR_PERIOD)
        adx = calc_adx_numba(high, low, close, self.config.ETH_ADX_PERIOD)
        ema20 = calc_ema_numba(close, 20)
        ema50 = calc_ema_numba(close, 50)
        ema100 = calc_ema_numba(close, 100)
        ema200 = calc_ema_numba(close, 200)
        rsi = calc_rsi_numba(close, self.config.ETH_RSI_PERIOD)
        wpr = calc_wpr_numba(close, self.config.ETH_WPR_PERIOD)
        vol_sma = pd.Series(vol).rolling(self.config.ETH_VOL_SMA_PERIOD).mean().values
        
        chop_count = calc_crossover_chop_count(ema20, ema50, self.config.CHOP_WINDOW_BARS)
        don_h, don_l = calc_donchian_channels(high, low, self.config.ETH_DONCHIAN_PERIOD)
        
        return {
            'close': close, 'high': high, 'low': low, 'vol': vol,
            'atr': atr, 'adx': adx,
            'ema20': ema20, 'ema50': ema50, 'ema100': ema100, 'ema200': ema200,
            'rsi': rsi, 'wpr': wpr, 'vol_sma': vol_sma,
            'chop_count': chop_count, 'don_h': don_h, 'don_l': don_l
        }

    def evaluate_eth_signals_vectorized(self, ind: Dict[str, np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
        """
        Returns boolean arrays (long_signals, short_signals) for ETH across the entire historical series.
        """
        c = ind['close']
        don_h = ind['don_h']
        don_l = ind['don_l']
        ema100 = ind['ema100']
        ema50 = ind['ema50']
        ema200 = ind['ema200']
        chop = ind['chop_count']
        adx = ind['adx']
        vol = ind['vol']
        vol_sma = ind['vol_sma']
        rsi = ind['rsi']
        wpr = ind['wpr']
        
        l_sig = (c > don_h) & (c > ema100) & (ema50 > ema200) & \
                (chop <= self.config.MAX_CHOP_CROSSES) & (adx >= self.config.ETH_ADX_MIN) & \
                (vol > self.config.ETH_VOL_SURGE_MULT * vol_sma) & \
                (rsi > 50.0) & (wpr > -40.0)
                
        s_sig = (c < don_l) & (c < ema100) & (ema50 < ema200) & \
                (chop <= self.config.MAX_CHOP_CROSSES) & (adx >= self.config.ETH_ADX_MIN) & \
                (vol > self.config.ETH_VOL_SURGE_MULT * vol_sma) & \
                (rsi < 50.0) & (wpr < -60.0)
                
        return l_sig, s_sig

    def calculate_btc_indicators(self, df_btc_4h: pd.DataFrame) -> Dict[str, np.ndarray]:
        """
        Calculates all required technical indicators for BTC 4h candles.
        """
        close = df_btc_4h['close'].values.astype(np.float64)
        high = df_btc_4h['high'].values.astype(np.float64)
        low = df_btc_4h['low'].values.astype(np.float64)
        
        atr = calc_atr_numba(high, low, close, self.config.BTC_ATR_PERIOD)
        adx = calc_adx_numba(high, low, close, self.config.BTC_ADX_PERIOD)
        ema20 = calc_ema_numba(close, 20)
        ema50 = calc_ema_numba(close, 50)
        don_h, don_l = calc_donchian_channels(high, low, self.config.BTC_DONCHIAN_PERIOD)
        
        return {
            'close': close, 'high': high, 'low': low,
            'atr': atr, 'adx': adx,
            'ema20': ema20, 'ema50': ema50,
            'don_h': don_h, 'don_l': don_l
        }

    def evaluate_btc_signals_vectorized(self, ind: Dict[str, np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
        """
        Returns boolean arrays (long_signals, short_signals) for BTC across the entire historical series.
        """
        c = ind['close']
        don_h = ind['don_h']
        don_l = ind['don_l']
        ema20 = ind['ema20']
        ema50 = ind['ema50']
        adx = ind['adx']
        
        l_sig = (c > don_h) & (c > ema50) & (ema20 > ema50) & (adx >= self.config.BTC_ADX_MIN)
        s_sig = (c < don_l) & (c < ema50) & (ema20 < ema50) & (adx >= self.config.BTC_ADX_MIN)
        
        return l_sig, s_sig

    def check_new_signal(
        self,
        bot_state: BotState,
        eth_l_sig_last: bool,
        eth_s_sig_last: bool,
        eth_atr_last: float,
        eth_next_open: float,
        btc_l_sig_last: bool,
        btc_s_sig_last: bool,
        btc_atr_last: float,
        btc_next_open: float,
        current_bar_idx: int,
        timestamp: Optional[str] = None
    ) -> SignalResult:
        """
        Unified dispatch: Evaluates signals with all protective governors applied.
        """
        # Governor 1: Bot Paused
        if bot_state.is_paused:
            return SignalResult(has_signal=False, governor_blocked=True, block_reason="Bot is paused by user")

        # Governor 2: Single Active Trade Rule
        if bot_state.active_trade is not None:
            return SignalResult(has_signal=False, governor_blocked=True, block_reason="Active trade already open")

        # Governor 3: 16-Hour Loss Cooldown
        bars_since_loss = current_bar_idx - bot_state.last_loss_bar
        if bars_since_loss < self.config.LOSS_COOLDOWN_BARS:
            return SignalResult(
                has_signal=False,
                governor_blocked=True,
                block_reason=f"In loss cooldown: {bars_since_loss}/{self.config.LOSS_COOLDOWN_BARS} bars"
            )

        # Primary Instrument Priority: ETH (1h)
        if eth_l_sig_last:
            return SignalResult(
                has_signal=True, symbol="ETHUSDT", direction=1,
                entry_price=eth_next_open, atr=eth_atr_last, timestamp=timestamp
            )
        if eth_s_sig_last:
            return SignalResult(
                has_signal=True, symbol="ETHUSDT", direction=-1,
                entry_price=eth_next_open, atr=eth_atr_last, timestamp=timestamp
            )

        # Secondary Instrument: BTC (4h)
        if btc_l_sig_last:
            return SignalResult(
                has_signal=True, symbol="BTCUSDT", direction=1,
                entry_price=btc_next_open, atr=btc_atr_last, timestamp=timestamp
            )
        if btc_s_sig_last:
            return SignalResult(
                has_signal=True, symbol="BTCUSDT", direction=-1,
                entry_price=btc_next_open, atr=btc_atr_last, timestamp=timestamp
            )

        return SignalResult(has_signal=False)
