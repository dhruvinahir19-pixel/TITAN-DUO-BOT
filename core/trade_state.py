"""
TITAN DUO v4.0 APEX - STATE MACHINE & TRADE DATA STRUCTURES
===========================================================
Defines the state lifecycle of the bot, active trade objects,
and clean serialization methods for Neon Postgres and in-memory caches.
"""

from enum import Enum
from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any
import json

class TradeStatus(str, Enum):
    IDLE = "IDLE"
    SUBMITTING_ENTRY = "SUBMITTING_ENTRY"
    IN_TRADE = "IN_TRADE"
    BE_LOCKED = "BE_LOCKED"
    PYRAMIDED = "PYRAMIDED"
    EXITED = "EXITED"

class ExitReason(str, Enum):
    STOP_LOSS = "SL"
    BREAKEVEN = "BE"
    TAKE_PROFIT = "TP"
    TIME_STOP = "TIME"
    OPPOSING_SIGNAL = "OPPOSING_SIGNAL"
    MANUAL_PANIC = "MANUAL_PANIC"
    ABORTED_CHASE = "ABORTED_CHASE"

@dataclass
class ActiveTrade:
    symbol: str
    direction: int                      # +1 for LONG, -1 for SHORT
    entry_price: float
    initial_units: float
    current_units: float
    stop_loss: float
    take_profit: float
    pyramid_trigger: float
    breakeven_sl: float
    atr_at_entry: float
    effective_risk_pct: float
    entry_timestamp: str
    entry_bar_idx: int = 0
    is_be_locked: bool = False
    is_pyramided: bool = False
    status: TradeStatus = TradeStatus.IN_TRADE
    order_id: Optional[str] = None
    exchange_sl_order_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d['status'] = self.status.value
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ActiveTrade":
        data_copy = dict(data)
        if isinstance(data_copy.get('status'), str):
            data_copy['status'] = TradeStatus(data_copy['status'])
        return cls(**data_copy)

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    @classmethod
    def from_json(cls, json_str: str) -> "ActiveTrade":
        return cls.from_dict(json.loads(json_str))

@dataclass
class BotState:
    wallet_equity: float = 100.0
    consecutive_losses: int = 0
    consecutive_wins: int = 0
    last_loss_bar: int = -9999
    last_loss_timestamp: Optional[str] = None
    active_trade: Optional[ActiveTrade] = None
    is_paused: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "wallet_equity": self.wallet_equity,
            "consecutive_losses": self.consecutive_losses,
            "consecutive_wins": self.consecutive_wins,
            "last_loss_bar": self.last_loss_bar,
            "last_loss_timestamp": self.last_loss_timestamp,
            "active_trade": self.active_trade.to_dict() if self.active_trade else None,
            "is_paused": self.is_paused
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BotState":
        active_trade_data = data.get("active_trade")
        active_trade = ActiveTrade.from_dict(active_trade_data) if active_trade_data else None
        return cls(
            wallet_equity=float(data.get("wallet_equity", 100.0)),
            consecutive_losses=int(data.get("consecutive_losses", 0)),
            consecutive_wins=int(data.get("consecutive_wins", 0)),
            last_loss_bar=int(data.get("last_loss_bar", -9999)),
            last_loss_timestamp=data.get("last_loss_timestamp"),
            active_trade=active_trade,
            is_paused=bool(data.get("is_paused", False))
        )
