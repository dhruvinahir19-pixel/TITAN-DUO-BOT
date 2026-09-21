"""
TITAN DUO v4.0 APEX - CORE INDICATOR LIBRARY
============================================
Pine Script-compatible mathematical technical indicator implementations:
- RMA (Wilder's Running Moving Average: alpha = 1 / length)
- EMA (Exponential Moving Average: alpha = 2 / (length + 1))
- ATR (Wilder's Average True Range via RMA)
- ADX (Wilder's Average Directional Index via RMA)
- RSI (Wilder's Relative Strength Index via RMA)
- WPR (Close-based Williams %R)
- CCI (Commodity Channel Index via Mean Absolute Deviation)
- Donchian Channels (Rolling High / Low shifted 1)
- 72-Hour Crossover Chop Governor
"""

import numpy as np
import pandas as pd
from numba import njit

@njit
def calc_rma_numba(values: np.ndarray, length: int) -> np.ndarray:
    """
    Wilder's Running Moving Average (Pine ta.rma).
    alpha = 1 / length, initial seed is values[0].
    """
    n = len(values)
    out = np.empty(n, dtype=np.float64)
    alpha = 1.0 / length
    out[0] = values[0]
    for i in range(1, n):
        out[i] = alpha * values[i] + (1.0 - alpha) * out[i - 1]
    return out

@njit
def calc_ema_numba(values: np.ndarray, length: int) -> np.ndarray:
    """
    Exponential Moving Average (Pine ta.ema).
    alpha = 2 / (length + 1), initial seed is values[0].
    """
    n = len(values)
    ema = np.empty(n, dtype=np.float64)
    alpha = 2.0 / (length + 1.0)
    ema[0] = values[0]
    for i in range(1, n):
        ema[i] = alpha * values[i] + (1.0 - alpha) * ema[i - 1]
    return ema

@njit
def calc_atr_numba(high: np.ndarray, low: np.ndarray, close: np.ndarray, length: int = 14) -> np.ndarray:
    """
    Wilder's Average True Range (Pine ta.atr) using Wilder's RMA.
    """
    n = len(close)
    tr = np.empty(n, dtype=np.float64)
    tr[0] = high[0] - low[0]
    for i in range(1, n):
        hl = high[i] - low[i]
        hc = abs(high[i] - close[i - 1])
        lc = abs(low[i] - close[i - 1])
        tr[i] = max(hl, max(hc, lc))
    return calc_rma_numba(tr, length)

@njit
def calc_adx_numba(high: np.ndarray, low: np.ndarray, close: np.ndarray, length: int = 14) -> np.ndarray:
    """
    Wilder's Average Directional Index (Pine ta.dmi / ADX).
    """
    n = len(close)
    up_move = np.zeros(n, dtype=np.float64)
    down_move = np.zeros(n, dtype=np.float64)
    for i in range(1, n):
        up = high[i] - high[i - 1]
        down = low[i - 1] - low[i]
        if up > down and up > 0:
            up_move[i] = up
        if down > up and down > 0:
            down_move[i] = down
            
    atr = calc_atr_numba(high, low, close, length)
    plus_di = 100.0 * calc_rma_numba(up_move, length) / np.maximum(atr, 1e-9)
    minus_di = 100.0 * calc_rma_numba(down_move, length) / np.maximum(atr, 1e-9)
    
    dx = np.zeros(n, dtype=np.float64)
    for i in range(n):
        denom = plus_di[i] + minus_di[i]
        if denom > 0:
            dx[i] = 100.0 * abs(plus_di[i] - minus_di[i]) / denom
    adx = calc_rma_numba(dx, length)
    return adx

@njit
def calc_rsi_numba(close: np.ndarray, length: int = 14) -> np.ndarray:
    """
    Wilder's Relative Strength Index (Pine ta.rsi).
    """
    n = len(close)
    up = np.zeros(n, dtype=np.float64)
    down = np.zeros(n, dtype=np.float64)
    for i in range(1, n):
        diff = close[i] - close[i - 1]
        if diff > 0.0:
            up[i] = diff
        elif diff < 0.0:
            down[i] = -diff
            
    up_rma = calc_rma_numba(up, length)
    down_rma = calc_rma_numba(down, length)
    
    rsi = np.empty(n, dtype=np.float64)
    for i in range(n):
        if down_rma[i] == 0.0:
            rsi[i] = 100.0 if up_rma[i] != 0.0 else 50.0
        elif up_rma[i] == 0.0:
            rsi[i] = 0.0
        else:
            rs = up_rma[i] / down_rma[i]
            rsi[i] = 100.0 - (100.0 / (1.0 + rs))
    return rsi

@njit
def calc_wpr_numba(close: np.ndarray, length: int = 14) -> np.ndarray:
    """
    Williams %R calculated on Close (Pine ta.wpr close-based).
    """
    n = len(close)
    wpr = np.empty(n, dtype=np.float64)
    for i in range(n):
        if i < length - 1:
            wpr[i] = np.nan
            continue
        max_val = close[i]
        min_val = close[i]
        for j in range(i - length + 1, i + 1):
            if close[j] > max_val:
                max_val = close[j]
            if close[j] < min_val:
                min_val = close[j]
        rng = max_val - min_val
        if rng == 0.0:
            wpr[i] = -50.0
        else:
            wpr[i] = 100.0 * (close[i] - max_val) / rng
    return wpr

def calc_donchian_channels(high: np.ndarray, low: np.ndarray, period: int = 48) -> tuple[np.ndarray, np.ndarray]:
    """
    Calculates Donchian Channel Upper (highest high) and Lower (lowest low).
    Shifted by 1 period so that the breakout compares the closed candle against PRIOR bars.
    """
    upper = pd.Series(high).rolling(period).max().shift(1).values
    lower = pd.Series(low).rolling(period).min().shift(1).values
    return upper, lower

def calc_crossover_chop_count(ema_fast: np.ndarray, ema_slow: np.ndarray, window: int = 72) -> np.ndarray:
    """
    Counts the number of EMA crossovers within a rolling window of bars.
    High crossover frequency (> 2 crosses in 72h) indicates choppy sideways oscillation.
    """
    n = len(ema_fast)
    cross = (ema_fast[:-1] > ema_slow[:-1]) != (ema_fast[1:] > ema_slow[1:])
    cross_arr = np.zeros(n, dtype=np.int32)
    cross_arr[1:] = cross.astype(np.int32)
    chop_count = pd.Series(cross_arr).rolling(window).sum().fillna(0).values
    return chop_count
