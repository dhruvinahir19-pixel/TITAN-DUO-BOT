"""
TITAN DUO v4.0 APEX - CONFIGURATION SPECIFICATION
=================================================
Centralized institutional configuration for BTCUSDT (4h) & ETHUSDT (1h)
execution on CoinSwitch Pro Perpetual Futures.
"""

import os
from dataclasses import dataclass
from dotenv import load_dotenv

# Load environment variables from .env if present
load_dotenv()

@dataclass(frozen=True)
class TradingConfig:
    # --- Strategy Identity ---
    STRATEGY_NAME: str = "TITAN_DUO_APEX"
    VERSION: str = "4.2.0"
    
    # --- Database & Infrastructure ---
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")
    COINSWITCH_API_KEY: str = os.getenv("COINSWITCH_API_KEY", "")
    COINSWITCH_SECRET_KEY: str = os.getenv("COINSWITCH_SECRET_KEY", "")
    COINSWITCH_PROXY_URL: str = os.getenv("COINSWITCH_PROXY_URL", "")
    
    # --- Telegram & Web Dashboard ---
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")
    ADMIN_PASSWORD: str = os.getenv("ADMIN_PASSWORD", "titan_apex_2026")
    WEB_PORT: int = int(os.getenv("PORT", "8000"))
    
    # --- Target Instruments & Timeframes ---
    PRIMARY_SYMBOL: str = "ETHUSDT"        # 1-Hour candles
    SECONDARY_SYMBOL: str = "BTCUSDT"      # 4-Hour candles
    
    # --- Base Capital & Risk Allocation (Apex Tier) ---
    BASE_RISK_PCT: float = 0.03            # 3.0% base equity risk per trade
    WIN_STREAK_BOOST_PCT: float = 0.0375   # 3.75% risk after 2 consecutive wins (1.25x boost)
    LOSS_STREAK_TIER1_PCT: float = 0.015   # 1.50% risk after 1 loss (50% reduction)
    LOSS_STREAK_TIER2_PCT: float = 0.0075  # 0.75% risk after 2+ losses (Preservation mode)
    
    # --- Leverage & Account Safety Governors ---
    MAX_EFFECTIVE_LEVERAGE: float = 5.0    # Hard ceiling: Notional position <= 5.0x Equity
    MIN_WALLET_BALANCE_USDT: float = 5.0   # Minimum balance to allow new trade execution
    MAX_SLIPPAGE_PCT: float = 0.0035       # 0.35% max slippage ceiling for Limit Order Chaser
    MAX_CANDLE_RANGE_ATR_MULT: float = 4.0 # Black Swan filter: reject candles > 4.0x ATR
    MAX_SPREAD_PCT: float = 0.0015         # 0.15% maximum allowable bid-ask spread
    
    # --- Trade Multipliers & Targets (ATR-Based) ---
    SL_ATR_MULT: float = 2.0               # Stop loss distance: 2.0x ATR
    ETH_TP_ATR_MULT: float = 5.0           # ETH Take Profit distance: 5.0x ATR
    BTC_TP_ATR_MULT: float = 4.5           # BTC Take Profit distance: 4.5x ATR
    MAX_HOLD_BARS: int = 48                # Time stop: close trade if held >= 48 bars
    
    # --- Breakeven Ratchet & Asymmetric Pyramiding ---
    BE_TRIGGER_ATR_MULT: float = 2.0       # Move SL to BE once trade hits +2.0x ATR
    BE_FEE_BUFFER_PCT: float = 0.002       # 0.20% buffer above entry (covers 0.10% RT fees + slippage)
    PYRAMID_TRANCHE_MULT: float = 0.50     # Add +0.5x original units when BE is triggered
    
    # --- Regime Governors & Cooldowns ---
    LOSS_COOLDOWN_BARS: int = 16           # Must wait at least 16 hourly bars after an SL exit
    CHOP_WINDOW_BARS: int = 72             # 72-hour window for EMA crossover detection
    MAX_CHOP_CROSSES: int = 2              # Reject breakout entry if EMA20/EMA50 crosses > 2
    
    # --- Technical Indicator Parameters ---
    # ETH (1-Hour)
    ETH_DONCHIAN_PERIOD: int = 48          # 48-hour Donchian Channel
    ETH_ADX_PERIOD: int = 14               # 14-period ADX
    ETH_ADX_MIN: float = 22.0              # Trend strength filter: ADX >= 22.0
    ETH_ATR_PERIOD: int = 14               # 14-period ATR
    ETH_RSI_PERIOD: int = 14               # 14-period RSI
    ETH_WPR_PERIOD: int = 14               # 14-period Williams %R
    ETH_VOL_SMA_PERIOD: int = 20           # 20-period Volume SMA
    ETH_VOL_SURGE_MULT: float = 1.2        # Volume surge filter: Volume > 1.2x SMA
    
    # BTC (4-Hour)
    BTC_DONCHIAN_PERIOD: int = 12          # 12 periods of 4h = 48-hour Donchian Channel
    BTC_ADX_PERIOD: int = 14               # 14-period ADX
    BTC_ADX_MIN: float = 18.0              # Trend strength filter: ADX >= 18.0
    BTC_ATR_PERIOD: int = 14               # 14-period ATR
    
    # --- Exchange Fee Accounting (CoinSwitch Pro / Binance VIP0) ---
    TAKER_FEE_PCT: float = 0.0005          # 0.05% per fill (0.10% round-trip)
    MAKER_FEE_PCT: float = 0.0002          # 0.02% per limit fill
    ESTIMATED_SLIPPAGE_PCT: float = 0.0002 # 0.02% (2 bps) slippage buffer
    
    # --- Indian Standard Time (IST) Offsets ---
    # UTC Hourly candles close at XX:30:00 IST
    # Bot wakes up at XX:30:02 IST (2 seconds buffer for candle completion)
    CANDLE_CLOSE_MINUTE_IST: int = 30
    EXECUTION_DELAY_SECONDS: int = 2
    ORDER_CHASER_POLL_INTERVAL: int = 10   # Check pending limit order every 10 seconds

# Global immutable configuration instance
CONFIG = TradingConfig()
