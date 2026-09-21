"""
TITAN DUO v4.0 APEX - RISK MANAGEMENT & SIZING MODULE
=====================================================
Calculates exact mathematical position sizing, dynamic streak scaling,
hard leverage caps, stop loss, take profit, risk-free pyramiding levels,
and exchange-enforced decimal precision formatting.
"""

import math
from typing import Tuple, Dict, Any, Optional
from config import CONFIG, TradingConfig

class RiskManager:
    def __init__(self, config: TradingConfig = CONFIG):
        self.config = config

    def calculate_effective_risk_pct(self, consec_losses: int, consec_wins: int) -> float:
        """
        Calculates the active risk percentage based on the account's winning/losing streak.
        - 0 losses, < 2 wins: 3.0% (Base Apex Tier)
        - 0 losses, >= 2 wins: 3.75% (Momentum boost: 1.25x)
        - 1 loss: 1.50% (50% reduction)
        - 2+ losses: 0.75% (Preservation mode: 75% reduction)
        """
        if consec_losses == 0:
            if consec_wins >= 2:
                return self.config.WIN_STREAK_BOOST_PCT
            return self.config.BASE_RISK_PCT
        elif consec_losses == 1:
            return self.config.LOSS_STREAK_TIER1_PCT
        else:
            return self.config.LOSS_STREAK_TIER2_PCT

    def calculate_trade_levels(self, symbol: str, direction: int, entry_price: float, atr: float) -> Dict[str, float]:
        """
        Calculates Stop Loss, Take Profit, Pyramid Trigger, and Breakeven Ratchet levels.
        direction: +1 for LONG, -1 for SHORT.
        """
        tp_mult = self.config.ETH_TP_ATR_MULT if "ETH" in symbol else self.config.BTC_TP_ATR_MULT
        
        if direction == 1:  # LONG
            stop_loss = entry_price - (self.config.SL_ATR_MULT * atr)
            take_profit = entry_price + (tp_mult * atr)
            pyramid_trigger = entry_price + (self.config.BE_TRIGGER_ATR_MULT * atr)
            breakeven_sl = entry_price * (1.0 + self.config.BE_FEE_BUFFER_PCT)
        else:  # SHORT
            stop_loss = entry_price + (self.config.SL_ATR_MULT * atr)
            take_profit = entry_price - (tp_mult * atr)
            pyramid_trigger = entry_price - (self.config.BE_TRIGGER_ATR_MULT * atr)
            breakeven_sl = entry_price * (1.0 - self.config.BE_FEE_BUFFER_PCT)
            
        return {
            "entry_price": float(entry_price),
            "stop_loss": float(stop_loss),
            "take_profit": float(take_profit),
            "pyramid_trigger": float(pyramid_trigger),
            "breakeven_sl": float(breakeven_sl),
            "unit_risk": float(abs(entry_price - stop_loss))
        }

    def format_order_quantity(self, symbol: str, raw_units: float) -> float:
        """
        Exchange Precision Invariant:
        CoinSwitch Pro Futures rules:
        - BTCUSDT: quantity_precision = 3 (step size = 0.001)
        - ETHUSDT: quantity_precision = 2 (step size = 0.01)
        Always uses math.floor to prevent exceeding margin or account risk.
        """
        prec = 3 if "BTC" in symbol.upper() else 2
        factor = 10 ** prec
        floored = math.floor(raw_units * factor) / factor
        return float(floored)

    def format_price(self, symbol: str, price: float) -> float:
        """
        Formats order prices to 2 decimal places (standard USD perpetual tick size).
        """
        return round(float(price), 2)

    def validate_order_constraints(self, symbol: str, units: float, price: float) -> Tuple[bool, str]:
        """
        Validates minimum contract size and minimum exchange notional value ($5.00 USD).
        """
        min_qty = 0.001 if "BTC" in symbol.upper() else 0.01
        if units < min_qty:
            return False, f"Units ({units}) below exchange minimum ({min_qty}) for {symbol}"
            
        notional = units * price
        if notional < 5.00:
            return False, f"Order notional (${notional:,.2f}) below exchange minimum of $5.00 USD"
            
        return True, "VALID"

    def calculate_position_size(
        self,
        wallet_equity: float,
        entry_price: float,
        stop_loss: float,
        consec_losses: int,
        consec_wins: int,
        leverage_ceiling: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Calculates unit quantity ensuring risk budget is respected and
        effective leverage NEVER exceeds the leverage ceiling.
        """
        if wallet_equity < self.config.MIN_WALLET_BALANCE_USDT:
            return {
                "units": 0.0,
                "notional_value": 0.0,
                "effective_risk_pct": 0.0,
                "risk_amount_usdt": 0.0,
                "leverage_capped": False,
                "reason": "Wallet equity below minimum threshold"
            }
            
        unit_risk = abs(entry_price - stop_loss)
        if unit_risk <= 0:
            raise ValueError(f"Invalid stop loss price: {stop_loss} for entry: {entry_price}")
            
        effective_risk_pct = self.calculate_effective_risk_pct(consec_losses, consec_wins)
        risk_capital = wallet_equity * effective_risk_pct
        raw_units = risk_capital / unit_risk
        notional_value = raw_units * entry_price
        
        # Effective Leverage Ceiling check (e.g. 5x base, or user specified ceiling)
        effective_cap = leverage_ceiling if leverage_ceiling else self.config.MAX_EFFECTIVE_LEVERAGE
        max_allowable_notional = wallet_equity * effective_cap
        leverage_capped = False
        
        if notional_value > max_allowable_notional:
            raw_units = max_allowable_notional / entry_price
            notional_value = max_allowable_notional
            leverage_capped = True
            
        return {
            "units": float(raw_units),
            "notional_value": float(notional_value),
            "effective_risk_pct": float(effective_risk_pct),
            "risk_amount_usdt": float(risk_capital),
            "leverage_capped": leverage_capped,
            "effective_leverage": float(notional_value / wallet_equity)
        }

    def calculate_pyramid_tranche(self, initial_units: float) -> Tuple[float, float]:
        """
        Calculates the +0.5x pyramid addition and the new aggregate position size.
        Returns (added_units, total_units).
        """
        added_units = initial_units * self.config.PYRAMID_TRANCHE_MULT
        total_units = initial_units + added_units
        return float(added_units), float(total_units)
