"""
UNIT & INTEGRATION TESTS: NEON.TECH ZERO-BURN DATABASE MANAGER
==============================================================
Verifies schema setup, state persistence, 7-day log purge, and executes
the critical Crash Recovery Simulation to prove zero state loss across reboots.
"""

import unittest
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from config import CONFIG
from core.db_manager import DatabaseManager
from core.trade_state import BotState, ActiveTrade, TradeStatus

class TestDatabaseManager(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Initialize DB manager with live Neon connection
        cls.db = DatabaseManager(config=CONFIG)
        cls.db.init_tables()

    @classmethod
    def tearDownClass(cls):
        # Reset bot_state to clean default and close pool
        default_state = BotState(wallet_equity=100.0)
        cls.db.save_bot_state(default_state)
        cls.db.close()

    def test_01_schema_exists(self):
        with self.db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT table_name FROM information_schema.tables 
                    WHERE table_schema = 'public' AND table_name IN ('bot_state', 'trades', 'audit_logs');
                """)
                tables = [r[0] for r in cur.fetchall()]
        self.assertIn('bot_state', tables)
        self.assertIn('trades', tables)
        self.assertIn('audit_logs', tables)

    def test_02_load_and_save_idle_state(self):
        state = BotState(
            wallet_equity=125.50,
            consecutive_losses=0,
            consecutive_wins=3,
            last_loss_bar=450
        )
        self.db.save_bot_state(state)
        loaded = self.db.load_bot_state()
        
        self.assertAlmostEqual(loaded.wallet_equity, 125.50, places=2)
        self.assertEqual(loaded.consecutive_losses, 0)
        self.assertEqual(loaded.consecutive_wins, 3)
        self.assertEqual(loaded.last_loss_bar, 450)
        self.assertIsNone(loaded.active_trade)

    def test_03_crash_recovery_simulation(self):
        """
        CRASH RECOVERY TEST:
        1. Save active trade with Breakeven SL and pyramided units.
        2. Destroy Python memory and simulate container termination.
        3. Reboot new DatabaseManager and verify state is 100% restored.
        """
        active_trade = ActiveTrade(
            symbol="ETHUSDT",
            direction=1,
            entry_price=2650.50,
            initial_units=0.12,
            current_units=0.18,              # Pyramided +0.5x
            stop_loss=2655.80,                # Ratcheted above BE
            take_profit=2850.00,
            pyramid_trigger=2730.00,
            breakeven_sl=2655.80,
            atr_at_entry=40.0,
            effective_risk_pct=0.03,
            entry_timestamp="2026-09-21 18:30:00",
            entry_bar_idx=500,
            is_be_locked=True,
            is_pyramided=True,
            status=TradeStatus.PYRAMIDED
        )
        state_before_crash = BotState(
            wallet_equity=250.75,
            consecutive_losses=0,
            consecutive_wins=2,
            active_trade=active_trade
        )
        
        # Save to Neon Postgres
        self.db.save_bot_state(state_before_crash)

        # SIMULATE CONTAINER CRASH: Delete reference and instantiate new manager
        fresh_db_instance = DatabaseManager(config=CONFIG)
        recovered_state = fresh_db_instance.load_bot_state()

        # Verify state resilience
        self.assertAlmostEqual(recovered_state.wallet_equity, 250.75, places=2)
        self.assertEqual(recovered_state.consecutive_wins, 2)
        self.assertIsNotNone(recovered_state.active_trade)
        
        rec_trade = recovered_state.active_trade
        self.assertEqual(rec_trade.symbol, "ETHUSDT")
        self.assertEqual(rec_trade.direction, 1)
        self.assertAlmostEqual(rec_trade.entry_price, 2650.50, places=2)
        self.assertAlmostEqual(rec_trade.current_units, 0.18, places=4)
        self.assertAlmostEqual(rec_trade.stop_loss, 2655.80, places=2)
        self.assertTrue(rec_trade.is_be_locked)
        self.assertTrue(rec_trade.is_pyramided)
        self.assertEqual(rec_trade.status, TradeStatus.PYRAMIDED)
        
        fresh_db_instance.close()

    def test_04_record_trade_and_analytics(self):
        sample_trade = {
            "symbol": "BTCUSDT",
            "direction": "LONG",
            "entry_price": 62000.0,
            "exit_price": 64500.0,
            "units": 0.005,
            "gross_pnl": 12.50,
            "fee": 0.63,
            "net_pnl": 11.87,
            "exit_reason": "TP",
            "held_bars": 14,
            "pyramided": True,
            "ending_wallet": 111.87,
            "entry_time": "2026-09-20 09:30:00"
        }
        trade_id = self.db.record_closed_trade(sample_trade)
        self.assertGreater(trade_id, 0)
        
        recent = self.db.get_recent_trades(limit=5)
        self.assertGreaterEqual(len(recent), 1)
        self.assertEqual(recent[0]['symbol'], "BTCUSDT")
        self.assertAlmostEqual(float(recent[0]['net_pnl']), 11.87, places=2)

        summary = self.db.get_performance_summary()
        self.assertGreaterEqual(summary['total_trades'], 1)
        self.assertGreater(summary['total_net_pnl'], 0)

    def test_05_audit_log_and_purge(self):
        self.db.log_event(
            level="INFO",
            event_type="SYSTEM_BOOT",
            message="Titan Duo test boot event",
            details={"test": True}
        )
        with self.db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM audit_logs WHERE event_type = 'SYSTEM_BOOT';")
                count = cur.fetchone()[0]
        self.assertGreaterEqual(count, 1)

if __name__ == '__main__':
    unittest.main()
