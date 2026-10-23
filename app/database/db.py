import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator, Optional

import aiosqlite

from app.config import settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def get_db_connection(db_path: Optional[str] = None) -> AsyncGenerator[aiosqlite.Connection, None]:
    """Async context manager that yields an aiosqlite connection with production pragmas."""
    path = db_path or settings.database_path
    Path(path).parent.mkdir(parents=True, exist_ok=True)

    async with aiosqlite.connect(path) as db:
        db.row_factory = aiosqlite.Row
        # WAL mode allows concurrent reads during writes
        await db.execute("PRAGMA journal_mode=WAL;")
        await db.execute("PRAGMA synchronous=NORMAL;")
        await db.execute("PRAGMA foreign_keys=ON;")
        yield db


async def init_db(db_path: Optional[str] = None) -> None:
    """Initialize database schema, tables, and indexes."""
    async with get_db_connection(db_path) as db:
        await db.executescript("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            chat_title TEXT NOT NULL,
            topic_id INTEGER,
            message_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            user_name TEXT NOT NULL,
            username TEXT,
            text TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(chat_id, message_id)
        );

        CREATE INDEX IF NOT EXISTS idx_messages_chat_topic_msg
            ON messages(chat_id, topic_id, message_id);

        CREATE INDEX IF NOT EXISTS idx_messages_created_at
            ON messages(created_at);

        -- Старый индекс по полному тексту хранил вторую копию всех сообщений.
        -- CREATE IF NOT EXISTS не удаляет то, что уже лежит в существующей базе, поэтому DROP явно
        DROP INDEX IF EXISTS idx_messages_text_date;

        -- Для поиска оригинала пересланного сообщения: автор + точное время отправки
        CREATE INDEX IF NOT EXISTS idx_messages_user_date
            ON messages(user_id, created_at);

        CREATE TABLE IF NOT EXISTS user_chat_state (
            user_id INTEGER NOT NULL,
            chat_id INTEGER NOT NULL,
            topic_id INTEGER NOT NULL DEFAULT 0,
            last_read_message_id INTEGER NOT NULL DEFAULT 0,
            last_summary_at TIMESTAMP,
            PRIMARY KEY (user_id, chat_id, topic_id)
        );

        CREATE TABLE IF NOT EXISTS user_api_keys (
            user_id INTEGER PRIMARY KEY,
            encrypted_key TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """)
        await db.commit()
    logger.info("Database initialized successfully.")
