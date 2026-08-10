import tempfile
import unittest

from sqlalchemy import text

from app.core.storage.database import DatabaseManager


class DatabaseReliabilityTests(unittest.TestCase):
    def test_sqlite_connections_wait_for_transient_write_locks(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = DatabaseManager(temp_dir)
            try:
                with manager._engine.connect() as connection:
                    timeout_ms = connection.execute(
                        text("PRAGMA busy_timeout")
                    ).scalar_one()
                    journal_mode = connection.execute(
                        text("PRAGMA journal_mode")
                    ).scalar_one()
                self.assertEqual(timeout_ms, 30_000)
                self.assertNotEqual(str(journal_mode).lower(), "wal")
            finally:
                manager.close()


if __name__ == "__main__":
    unittest.main()
