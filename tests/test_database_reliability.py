import os
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import text

from app.core.storage.cache_manager import CacheManager
from app.core.storage.database import DatabaseManager
from app.core.storage.models import LLMCache


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

    def test_llm_cache_same_key_is_updated_deterministically(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = CacheManager(temp_dir)
            try:
                cache.set_llm_result(
                    "cache-key",
                    "first",
                    "test-model",
                    temperature=0.2,
                    task="test-task",
                )
                cache.set_llm_result(
                    "cache-key",
                    "second",
                    "test-model",
                    temperature=0.2,
                    task="test-task",
                )

                self.assertEqual(
                    cache.get_llm_result(
                        "cache-key",
                        "test-model",
                        temperature=0.2,
                        task="test-task",
                    ),
                    "second",
                )
                with cache.db_manager.get_session() as session:
                    self.assertEqual(session.query(LLMCache).count(), 1)
            finally:
                cache.db_manager.close()

    def test_llm_cache_migrates_duplicate_rows_to_a_unique_lookup(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = os.path.join(temp_dir, "cache.db")
            connection = sqlite3.connect(db_path)
            try:
                connection.execute(
                    """
                    CREATE TABLE llm_cache (
                        id INTEGER PRIMARY KEY,
                        prompt TEXT NOT NULL,
                        result TEXT NOT NULL,
                        model_name VARCHAR(100) NOT NULL,
                        params JSON,
                        content_hash VARCHAR(32) NOT NULL,
                        created_at DATETIME
                    )
                    """
                )
                connection.execute(
                    "CREATE INDEX idx_llm_lookup "
                    "ON llm_cache (content_hash, model_name)"
                )
                connection.executemany(
                    """
                    INSERT INTO llm_cache
                        (prompt, result, model_name, params, content_hash)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    [
                        ("old", "first", "model", "{}", "same-hash"),
                        ("old", "latest", "model", "{}", "same-hash"),
                    ],
                )
                connection.commit()
            finally:
                connection.close()

            manager = DatabaseManager(temp_dir)
            try:
                with manager.get_session() as session:
                    rows = session.query(LLMCache).all()
                    self.assertEqual([row.result for row in rows], ["latest"])
                    index_rows = session.execute(
                        text("PRAGMA index_list('llm_cache')")
                    ).fetchall()
                    lookup = [row for row in index_rows if row[1] == "idx_llm_lookup"]
                    self.assertEqual(len(lookup), 1)
                    self.assertEqual(int(lookup[0][2]), 1)
            finally:
                manager.close()

    def test_two_cache_managers_upsert_one_shared_key_without_duplicates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            first = CacheManager(temp_dir)
            second = CacheManager(temp_dir)
            barrier = threading.Barrier(2)

            def write(cache, value):
                barrier.wait(timeout=5)
                cache.set_llm_result(
                    "shared-key",
                    value,
                    "test-model",
                    temperature=0.2,
                    task="shared-task",
                )

            try:
                with ThreadPoolExecutor(max_workers=2) as executor:
                    futures = [
                        executor.submit(write, first, "first"),
                        executor.submit(write, second, "second"),
                    ]
                    for future in futures:
                        future.result(timeout=10)

                first.set_llm_result(
                    "shared-key",
                    "final",
                    "test-model",
                    temperature=0.2,
                    task="shared-task",
                )
                self.assertEqual(
                    second.get_llm_result(
                        "shared-key",
                        "test-model",
                        temperature=0.2,
                        task="shared-task",
                    ),
                    "final",
                )
                with first.db_manager.get_session() as session:
                    self.assertEqual(session.query(LLMCache).count(), 1)
            finally:
                first.db_manager.close()
                second.db_manager.close()


if __name__ == "__main__":
    unittest.main()
