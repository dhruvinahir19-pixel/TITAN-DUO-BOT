"""
TITAN DUO v4.0 APEX - ZERO-BURN DATABASE MANAGER (NEON.TECH)
============================================================
Provides connection-pooled, fault-tolerant persistence for bot state,
closed trades, and audit logging with automatic 7-day log purging.
Engineered for < 15 MB/month bandwidth to prevent hitting Neon limits.
"""

import json
import logging
import time
from typing import Optional, Dict, Any, List
from contextlib import contextmanager

import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor

from config import CONFIG, TradingConfig
from core.trade_state import BotState, ActiveTrade

logger = logging.getLogger("TitanDuo.DB")

class DatabaseManager:
    def __init__(self, database_url: Optional[str] = None, config: TradingConfig = CONFIG):
        self.config = config
        self.database_url = database_url or config.DATABASE_URL
        if not self.database_url:
            raise ValueError("DATABASE_URL is not set. Please provide a valid Neon connection string.")
            
        self._pool: Optional[pool.ThreadedConnectionPool] = None
        self._init_pool()

    def _init_pool(self, max_retries: int = 3, retry_delay: float = 2.0):
        """
        Initializes the connection pool with retry backoff for Neon serverless cold starts.
        """
        for attempt in range(1, max_retries + 1):
            try:
                # Strip channel_binding if present to avoid driver mismatch
                clean_url = self.database_url.replace('&channel_binding=require', '')
                clean_url = clean_url.replace('?channel_binding=require', '')
                clean_url = clean_url.replace('&amp;channel_binding=require', '')
                
                self._pool = pool.ThreadedConnectionPool(
                    minconn=1,
                    maxconn=3,
                    dsn=clean_url
                )
                logger.info("Neon Postgres connection pool initialized successfully.")
                return
            except Exception as e:
                logger.warning(f"Connection pool init failed (Attempt {attempt}/{max_retries}): {e}")
                if attempt == max_retries:
                    raise
                time.sleep(retry_delay * attempt)

    @contextmanager
    def get_connection(self):
        """
        Context manager for acquiring and safely releasing pooled connections.
        """
        if self._pool is None:
            self._init_pool()
            
        conn = None
        try:
            conn = self._pool.getconn()
            yield conn
        finally:
            if conn and self._pool:
                self._pool.putconn(conn)

    def init_tables(self):
        """
        Creates optimized schema for bot_state, trades, and audit_logs.
        Performs safe auto-migrations.
        """
        schema_sql = """
        -- Table 1: Bot State (Always exactly 1 row)
        CREATE TABLE IF NOT EXISTS bot_state (
            id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
            wallet_equity NUMERIC(16, 4) NOT NULL DEFAULT 100.0,
            consecutive_losses INTEGER NOT NULL DEFAULT 0,
            consecutive_wins INTEGER NOT NULL DEFAULT 0,
            last_loss_bar INTEGER NOT NULL DEFAULT -9999,
            last_loss_timestamp TIMESTAMPTZ,
            active_trade JSONB,
            is_paused BOOLEAN NOT NULL DEFAULT FALSE,
            leverage_ceiling INTEGER NOT NULL DEFAULT 20,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        -- Safe Migration: Ensure leverage_ceiling column exists if table was created previously
        ALTER TABLE bot_state ADD COLUMN IF NOT EXISTS leverage_ceiling INTEGER NOT NULL DEFAULT 20;

        -- Table 2: Closed Trades History
        CREATE TABLE IF NOT EXISTS trades (
            id SERIAL PRIMARY KEY,
            symbol VARCHAR(20) NOT NULL,
            direction VARCHAR(10) NOT NULL,
            entry_price NUMERIC(16, 6) NOT NULL,
            exit_price NUMERIC(16, 6) NOT NULL,
            units NUMERIC(18, 8) NOT NULL,
            gross_pnl NUMERIC(16, 4) NOT NULL,
            fee NUMERIC(16, 4) NOT NULL,
            net_pnl NUMERIC(16, 4) NOT NULL,
            exit_reason VARCHAR(30) NOT NULL,
            held_bars INTEGER NOT NULL,
            pyramided BOOLEAN NOT NULL DEFAULT FALSE,
            ending_wallet NUMERIC(16, 4) NOT NULL,
            entry_time TIMESTAMPTZ,
            exit_time TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        -- Table 3: Audit & System Event Logs
        CREATE TABLE IF NOT EXISTS audit_logs (
            id SERIAL PRIMARY KEY,
            level VARCHAR(10) NOT NULL,
            event_type VARCHAR(50) NOT NULL,
            message TEXT NOT NULL,
            details JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        -- Ensure initial bot_state row exists
        INSERT INTO bot_state (id, wallet_equity, consecutive_losses, consecutive_wins, last_loss_bar, is_paused, leverage_ceiling)
        VALUES (1, 100.0, 0, 0, -9999, FALSE, 20)
        ON CONFLICT (id) DO NOTHING;
        """
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(schema_sql)
            conn.commit()
        logger.info("Database schema initialized and verified.")

    def load_bot_state(self) -> BotState:
        """
        Loads current state from bot_state table. Rebuilds active trade object if present.
        """
        query = """
        SELECT wallet_equity, consecutive_losses, consecutive_wins,
               last_loss_bar, last_loss_timestamp, active_trade, is_paused, leverage_ceiling
        FROM bot_state
        WHERE id = 1;
        """
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query)
                row = cur.fetchone()
                
        if not row:
            self.init_tables()
            return BotState(wallet_equity=100.0, leverage_ceiling=20)

        active_trade = None
        if row['active_trade']:
            active_trade = ActiveTrade.from_dict(row['active_trade'])

        return BotState(
            wallet_equity=float(row['wallet_equity']),
            consecutive_losses=int(row['consecutive_losses']),
            consecutive_wins=int(row['consecutive_wins']),
            last_loss_bar=int(row['last_loss_bar']),
            last_loss_timestamp=str(row['last_loss_timestamp']) if row['last_loss_timestamp'] else None,
            active_trade=active_trade,
            is_paused=bool(row['is_paused']),
            leverage_ceiling=int(row.get('leverage_ceiling', 20))
        )

    def save_bot_state(self, state: BotState) -> bool:
        """
        Upserts the single bot state row. Writes happen ONLY upon state changes.
        """
        query = """
        INSERT INTO bot_state (
            id, wallet_equity, consecutive_losses, consecutive_wins,
            last_loss_bar, last_loss_timestamp, active_trade, is_paused, leverage_ceiling, updated_at
        ) VALUES (
            1, %s, %s, %s, %s, %s, %s, %s, %s, NOW()
        )
        ON CONFLICT (id) DO UPDATE SET
            wallet_equity = EXCLUDED.wallet_equity,
            consecutive_losses = EXCLUDED.consecutive_losses,
            consecutive_wins = EXCLUDED.consecutive_wins,
            last_loss_bar = EXCLUDED.last_loss_bar,
            last_loss_timestamp = EXCLUDED.last_loss_timestamp,
            active_trade = EXCLUDED.active_trade,
            is_paused = EXCLUDED.is_paused,
            leverage_ceiling = EXCLUDED.leverage_ceiling,
            updated_at = NOW();
        """
        active_trade_json = json.dumps(state.active_trade.to_dict()) if state.active_trade else None
        
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (
                    state.wallet_equity,
                    state.consecutive_losses,
                    state.consecutive_wins,
                    state.last_loss_bar,
                    state.last_loss_timestamp,
                    active_trade_json,
                    state.is_paused,
                    state.leverage_ceiling
                ))
            conn.commit()
        return True

    def record_closed_trade(self, trade_data: Dict[str, Any]) -> int:
        """
        Appends a closed trade to the trades history table.
        """
        query = """
        INSERT INTO trades (
            symbol, direction, entry_price, exit_price, units,
            gross_pnl, fee, net_pnl, exit_reason, held_bars,
            pyramided, ending_wallet, entry_time, exit_time
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW()
        ) RETURNING id;
        """
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (
                    trade_data['symbol'],
                    trade_data['direction'],
                    trade_data['entry_price'],
                    trade_data['exit_price'],
                    trade_data['units'],
                    trade_data['gross_pnl'],
                    trade_data['fee'],
                    trade_data['net_pnl'],
                    trade_data['exit_reason'],
                    trade_data['held_bars'],
                    trade_data['pyramided'],
                    trade_data['ending_wallet'],
                    trade_data.get('entry_time')
                ))
                trade_id = cur.fetchone()[0]
            conn.commit()
        return trade_id

    def log_event(self, level: str, event_type: str, message: str, details: Optional[Dict[str, Any]] = None):
        """
        Appends a system audit log and automatically purges records older than 7 days.
        """
        insert_query = """
        INSERT INTO audit_logs (level, event_type, message, details, created_at)
        VALUES (%s, %s, %s, %s, NOW());
        """
        purge_query = """
        DELETE FROM audit_logs WHERE created_at < NOW() - INTERVAL '7 days';
        """
        details_json = json.dumps(details) if details else None
        
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(insert_query, (level, event_type, message, details_json))
                    # Auto-purge older logs
                    cur.execute(purge_query)
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to write audit log: {e}")

    def get_recent_trades(self, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Returns recent closed trades for the web dashboard.
        """
        query = """
        SELECT id, symbol, direction, entry_price, exit_price, units,
               gross_pnl, fee, net_pnl, exit_reason, held_bars, pyramided,
               ending_wallet, entry_time, exit_time
        FROM trades
        ORDER BY exit_time DESC
        LIMIT %s;
        """
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query, (limit,))
                rows = cur.fetchall()
        return [dict(r) for r in rows]

    def get_performance_summary(self) -> Dict[str, Any]:
        """
        Calculates aggregate statistics from the trades table.
        """
        query = """
        SELECT 
            COUNT(*) AS total_trades,
            COALESCE(SUM(CASE WHEN net_pnl > 0 THEN 1 ELSE 0 END), 0) AS win_count,
            COALESCE(SUM(CASE WHEN net_pnl < 0 THEN 1 ELSE 0 END), 0) AS loss_count,
            COALESCE(SUM(gross_pnl), 0) AS total_gross_pnl,
            COALESCE(SUM(fee), 0) AS total_fees,
            COALESCE(SUM(net_pnl), 0) AS total_net_pnl,
            COALESCE(SUM(CASE WHEN net_pnl > 0 THEN net_pnl ELSE 0 END), 0) AS gross_profit,
            COALESCE(ABS(SUM(CASE WHEN net_pnl < 0 THEN net_pnl ELSE 0 END)), 0) AS gross_loss
        FROM trades;
        """
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query)
                res = cur.fetchone()

        total = res['total_trades']
        wins = res['win_count']
        win_rate = (wins / total * 100.0) if total > 0 else 0.0
        gross_loss = float(res['gross_loss'])
        gross_profit = float(res['gross_profit'])
        pf = (gross_profit / gross_loss) if gross_loss > 0 else (99.0 if gross_profit > 0 else 0.0)

        return {
            "total_trades": int(total),
            "win_count": int(wins),
            "loss_count": int(res['loss_count']),
            "win_rate_pct": float(win_rate),
            "total_fees_paid": float(res['total_fees']),
            "total_net_pnl": float(res['total_net_pnl']),
            "profit_factor": float(pf)
        }

    def close(self):
        """
        Gracefully terminates all pooled database connections.
        """
        if self._pool:
            self._pool.closeall()
            logger.info("Neon database connection pool closed.")
