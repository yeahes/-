# app/core/storage/database.py
import os
import logging
from contextlib import contextmanager
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from .models import Base
from .constants import CACHE_CONFIG

logger = logging.getLogger(__name__)


class DatabaseManager:
    """数据库管理类，负责数据库连接和会话管理"""

    def __init__(self, app_data_path: str):
        self.db_path = os.path.join(app_data_path, CACHE_CONFIG["db_filename"])
        self.db_url = f"sqlite:///{self.db_path}"
        self._engine = None
        self._session_maker = None
        self.init_db()

    def init_db(self):
        """初始化数据库连接和表结构"""
        try:
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
            self._engine = create_engine(
                self.db_url,
                connect_args={
                    "check_same_thread": False,
                    "timeout": 30.0,
                },
                pool_pre_ping=True,
                pool_size=5,
                max_overflow=10,
                pool_recycle=3600,
            )
            Base.metadata.create_all(self._engine)
            self._ensure_llm_cache_unique_lookup()
            self._session_maker = sessionmaker(bind=self._engine)
            # logger.info(f"Database initialized at {self.db_path}")
        except Exception as e:
            logger.error(f"Failed to initialize database: {str(e)}")
            raise

    def _ensure_llm_cache_unique_lookup(self) -> None:
        """Migrate old LLM cache rows/indexes to one key per model request."""
        # Older releases created a non-unique lookup index and could write the
        # same request more than once.  Deduplicate before replacing it so the
        # unique index can be installed for existing user databases as well as
        # new databases. SQLite serializes the DDL transaction across processes.
        with self._engine.begin() as connection:
            indexes = connection.execute(
                text("PRAGMA index_list('llm_cache')")
            ).fetchall()
            for index in indexes:
                if str(index[1]) == "idx_llm_lookup" and bool(index[2]):
                    return
            connection.execute(
                text(
                    """
                    DELETE FROM llm_cache
                    WHERE id NOT IN (
                        SELECT MAX(id)
                        FROM llm_cache
                        GROUP BY content_hash, model_name
                    )
                    """
                )
            )
            connection.execute(text("DROP INDEX IF EXISTS idx_llm_lookup"))
            connection.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS "
                    "idx_llm_lookup ON llm_cache (content_hash, model_name)"
                )
            )

    def close(self):
        """关闭数据库连接"""
        if self._engine:
            self._engine.dispose()
            self._engine = None
            self._session_maker = None

    @contextmanager
    def get_session(self):
        """获取数据库会话的上下文管理器"""
        if not self._engine or not self._session_maker:
            self.init_db()

        session = self._session_maker()
        try:
            yield session
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"Database session error: {str(e)}")
            raise
        finally:
            session.close()
