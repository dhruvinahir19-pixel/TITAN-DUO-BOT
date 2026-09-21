"""
TITAN DUO v4.0 APEX - COMPLETE STRATEGY ENGINE
==============================================
The primary execution orchestrator combining Indicators, Risk Management,
Signal Generation, Dynamic Pyramiding, and Portfolio Governance.
"""

from typing import Dict, Any, Optional
import pandas as pd
import numpy as np

from config import CONFIG, TradingConfig
from core.trade_state import BotState, ActiveTrade, TradeStatus, ExitReason
from core.risk_manager import RiskManager
from core.signal_generator import SignalGenerator, SignalResult

class StrategyEngine:
    def __init__(self, config: TradingConfig = CONFIG):
        self.config = config
        self.risk_manager = RiskManager(config)
        self.signal_generator = SignalGenerator(config)

    def process_bar_lifecycle(
        self,
        bot_state: BotState,
        symbol: str,
        high: float,
        low: float,
        open_price: float,
        close_price: float,
        bar_idx: int,
        opposing_signal: bool = False
    ) -> Dict[str, Any]:
        """
        Processes a single price bar for an active position:
        1. Checks +2.0x ATR Pyramid Trigger & Breakeven Ratchet.
        2. Evaluates Stop Loss, Take Profit, Time Stop, or Opposing Signal exits.
        3. Returns status update, fee deductions, and realized PnL if exited.
        """
        pos = bot_state.active_trade
        if pos is None:
            return {"action": "NONE"}

        held_bars = bar_idx - pos.entry_bar_idx
        exit_price = 0.0
        exit_reason = None
        action_events = []

        # Step 1: Risk-Free Pyramiding Trigger (+2.0x ATR)
        if not pos.is_pyramided:
            if pos.direction == 1 and high >= pos.pyramid_trigger:
                # Ratchet SL to Breakeven (+0.2% fee buffer)
                new_sl = max(pos.stop_loss, pos.entry_price * (1.0 + self.config.BE_FEE_BUFFER_PCT))
                pos.stop_loss = new_sl
                pos.is_be_locked = True
                
                # Add +0.5x position tranche
                added_units, total_units = self.risk_manager.calculate_pyramid_tranche(pos.initial_units)
                pos.current_units = total_units
                pos.is_pyramided = True
                pos.status = TradeStatus.PYRAMIDED
                action_events.append({
                    "event": "PYRAMID_ADDED",
                    "added_units": added_units,
                    "new_total_units": total_units,
                    "ratcheted_sl": new_sl
                })
            elif pos.direction == -1 and low <= pos.pyramid_trigger:
                new_sl = min(pos.stop_loss, pos.entry_price * (1.0 - self.config.BE_FEE_BUFFER_PCT))
                pos.stop_loss = new_sl
                pos.is_be_locked = True
                
                added_units, total_units = self.risk_manager.calculate_pyramid_tranche(pos.initial_units)
                pos.current_units = total_units
                pos.is_pyramided = True
                pos.status = TradeStatus.PYRAMIDED
                action_events.append({
                    "event": "PYRAMID_ADDED",
                    "added_units": added_units,
                    "new_total_units": total_units,
                    "ratcheted_sl": new_sl
                })

        # Step 2: Exit Evaluation
        if pos.direction == 1:  # LONG
            if low <= pos.stop_loss:
                exit_price = pos.stop_loss
                exit_reason = ExitReason.BREAKEVEN if pos.is_be_locked else ExitReason.STOP_LOSS
            elif high >= pos.take_profit:
                exit_price = pos.take_profit
                exit_reason = ExitReason.TAKE_PROFIT
            elif held_bars >= self.config.MAX_HOLD_BARS:
                exit_price = open_price
                exit_reason = ExitReason.TIME_STOP
            elif opposing_signal:
                exit_price = open_price
                exit_reason = ExitReason.OPPOSING_SIGNAL
        else:  # SHORT
            if high >= pos.stop_loss:
                exit_price = pos.stop_loss
                exit_reason = ExitReason.BREAKEVEN if pos.is_be_locked else ExitReason.STOP_LOSS
            elif low <= pos.take_profit:
                exit_price = pos.take_profit
                exit_reason = ExitReason.TAKE_PROFIT
            elif held_bars >= self.config.MAX_HOLD_BARS:
                exit_price = open_price
                exit_reason = ExitReason.TIME_STOP
            elif opposing_signal:
                exit_price = open_price
                exit_reason = ExitReason.OPPOSING_SIGNAL

        # Step 3: Trade Closure Accounting
        if exit_price > 0.0:
            # Gross PnL
            gross_pnl = pos.current_units * (exit_price - pos.entry_price) * pos.direction
            # Exchange Taker Fee (0.05% entry + 0.05% exit = 0.10% total)
            fee = (pos.entry_price + exit_price) * pos.current_units * self.config.TAKER_FEE_PCT
            net_pnl = gross_pnl - fee
            
            # Update Bot Wallet & Streaks
            bot_state.wallet_equity += net_pnl
            if net_pnl < 0:
                bot_state.last_loss_bar = bar_idx
                bot_state.consecutive_losses += 1
                bot_state.consecutive_wins = 0
            else:
                bot_state.consecutive_losses = 0
                bot_state.consecutive_wins += 1

            closed_trade_data = {
                "symbol": pos.symbol,
                "direction": "LONG" if pos.direction == 1 else "SHORT",
                "entry_price": pos.entry_price,
                "exit_price": exit_price,
                "units": pos.current_units,
                "gross_pnl": gross_pnl,
                "fee": fee,
                "net_pnl": net_pnl,
                "exit_reason": exit_reason.value if exit_reason else "UNKNOWN",
                "held_bars": held_bars,
                "pyramided": pos.is_pyramided,
                "ending_wallet": bot_state.wallet_equity
            }
            bot_state.active_trade = None
            
            return {
                "action": "TRADE_EXITED",
                "closed_trade": closed_trade_data,
                "events": action_events
            }

        return {
            "action": "POSITION_HELD",
            "events": action_events
        }

    def open_trade_from_signal(
        self,
        bot_state: BotState,
        signal: SignalResult,
        bar_idx: int,
        timestamp: str
    ) -> Optional[ActiveTrade]:
        """
        Creates and registers a new active trade from a validated signal.
        """
        if not signal.has_signal or signal.governor_blocked:
            return None

        levels = self.risk_manager.calculate_trade_levels(
            symbol=signal.symbol,
            direction=signal.direction,
            entry_price=signal.entry_price,
            atr=signal.atr
        )

        sizing = self.risk_manager.calculate_position_size(
            wallet_equity=bot_state.wallet_equity,
            entry_price=signal.entry_price,
            stop_loss=levels['stop_loss'],
            consec_losses=bot_state.consecutive_losses,
            consec_wins=bot_state.consecutive_wins
        )

        if sizing['units'] <= 0:
            return None

        active_trade = ActiveTrade(
            symbol=signal.symbol,
            direction=signal.direction,
            entry_price=signal.entry_price,
            initial_units=sizing['units'],
            current_units=sizing['units'],
            stop_loss=levels['stop_loss'],
            take_profit=levels['take_profit'],
            pyramid_trigger=levels['pyramid_trigger'],
            breakeven_sl=levels['breakeven_sl'],
            atr_at_entry=signal.atr,
            effective_risk_pct=sizing['effective_risk_pct'],
            entry_timestamp=timestamp,
            entry_bar_idx=bar_idx,
            status=TradeStatus.IN_TRADE
        )

        bot_state.active_trade = active_trade
        return active_trade
