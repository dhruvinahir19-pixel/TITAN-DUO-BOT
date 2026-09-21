"""
TITAN DUO v4.0 APEX - CORE PACKAGE
"""

from core.indicators import (
    calc_ema_numba,
    calc_atr_numba,
    calc_adx_numba,
    calc_rsi_numba,
    calc_wpr_numba,
    calc_donchian_channels,
    calc_crossover_chop_count
)
from core.risk_manager import RiskManager
from core.signal_generator import SignalGenerator, SignalResult
from core.trade_state import BotState, ActiveTrade, TradeStatus, ExitReason
from core.strategy_engine import StrategyEngine

__all__ = [
    "calc_ema_numba",
    "calc_atr_numba",
    "calc_adx_numba",
    "calc_rsi_numba",
    "calc_wpr_numba",
    "calc_donchian_channels",
    "calc_crossover_chop_count",
    "RiskManager",
    "SignalGenerator",
    "SignalResult",
    "BotState",
    "ActiveTrade",
    "TradeStatus",
    "ExitReason",
    "StrategyEngine"
]
