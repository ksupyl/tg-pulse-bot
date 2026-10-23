"""
Репозиторий — единственное место с SQL-запросами к буферу сообщений,
состоянию прочтения и BYOK-ключам.

Бот и Mini App вызывают методы `repository` и получают Pydantic-модели
из app/database/models.py, ничего не зная про SQLite. Соединение и схема
таблиц живут в app/database/db.py.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple, Dict, Any
import aiosqlite

from app.database.db import get_db_connection
from app.database.models import ChatMessage, UserChatState

logger = logging.getLogger(__name__)

# Время в SQLite храним текстом в UTC: "2026-10-23 14:05:00".
# Формат совпадает с CURRENT_TIMESTAMP самого SQLite и правильно сравнивается
# как обычная строка — на этом держатся TTL-очистка и поиск по времени.
DB_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def _to_db_time(dt: datetime) -> str:
    """Переводит datetime в строку UTC для записи в SQLite.

    Время с любым часовым поясом сначала приводим к UTC, иначе московские 14:00
    записались бы как 14:00 UTC и TTL-очистка сдвинулась бы на 3 часа.
    «Голое» время без пояса считаем уже UTC — так его отдаёт сам SQLite.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime(DB_TIME_FORMAT)


def _from_db_time(value: str) -> datetime:
    """Читает строку из SQLite обратно в datetime с явным поясом UTC.

    Без .replace(tzinfo=...) получилось бы «голое» время, и первое же сравнение
    с datetime.now(timezone.utc) упало бы с TypeError.
    """
    return datetime.strptime(value, DB_TIME_FORMAT).replace(tzinfo=timezone.utc)


def _row_to_message(row: aiosqlite.Row) -> ChatMessage:
    """Собирает ChatMessage из строки таблицы messages — одно место вместо копипасты в каждом SELECT."""
    return ChatMessage(
        id=row["id"],
        chat_id=row["chat_id"],
        chat_title=row["chat_title"],
        topic_id=row["topic_id"],
        message_id=row["message_id"],
        user_id=row["user_id"],
        user_name=row["user_name"],
        username=row["username"],
        text=row["text"],
        created_at=_from_db_time(row["created_at"]),
    )


class MessageRepository:
    """Repository handling all database operations for messages, state and BYOK keys."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path

    # -------------------------------------------------------------
    # Message Storage & Retrieval
    # -------------------------------------------------------------
    async def save_message(self, msg: ChatMessage) -> bool:
        """Save a new incoming message to the ephemeral buffer. Returns True if inserted."""
        query = """
        INSERT OR IGNORE INTO messages
            (chat_id, chat_title, topic_id, message_id, user_id, user_name, username, text, created_at)
        VALUES
            (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        async with get_db_connection(self.db_path) as db:
            cursor = await db.execute(
                query,
                (
                    msg.chat_id,
                    msg.chat_title,
                    msg.topic_id,
                    msg.message_id,
                    msg.user_id,
                    msg.user_name,
                    msg.username,
                    msg.text,
                    _to_db_time(msg.created_at),
                ),
            )
            await db.commit()
            return cursor.rowcount > 0

    async def get_messages_since(
        self,
        chat_id: int,
        start_message_id: int,
        topic_id: Optional[int] = None,
        inclusive: bool = True,
        limit: int = 500,
    ) -> List[ChatMessage]:
        """Fetch messages starting from start_message_id up to the most recent."""
        op = ">=" if inclusive else ">"
        conditions = ["chat_id = ?", f"message_id {op} ?"]
        params: List[Any] = [chat_id, start_message_id]

        if topic_id is not None:
            conditions.append("topic_id = ?")
            params.append(topic_id)

        query = f"""
        SELECT id, chat_id, chat_title, topic_id, message_id, user_id, user_name, username, text, created_at
        FROM messages
        WHERE {" AND ".join(conditions)}
        ORDER BY message_id ASC
        LIMIT ?
        """
        params.append(limit)

        async with get_db_connection(self.db_path) as db:
            async with db.execute(query, params) as cursor:
                rows = await cursor.fetchall()
                return [_row_to_message(row) for row in rows]

    async def find_forwarded_message(
        self,
        sent_at: datetime,
        user_id: Optional[int] = None,
        user_name: Optional[str] = None,
    ) -> Optional[ChatMessage]:
        """Находит в буфере оригинал сообщения, которое пользователь переслал боту.

        При пересылке из группы Telegram не сообщает ни чат, ни message_id —
        только автора и точное время отправки (message.forward_origin). По этой паре и ищем:
        - user_id — если автор не скрывает пересылки (MessageOriginUser.sender_user.id);
        - user_name — если скрывает (MessageOriginHiddenUser), там есть только имя.

        sent_at должен совпасть до секунды, поэтому слушатель обязан сохранять
        message.date от Telegram, а не время получения на сервере.
        Метод НЕ проверяет доступ: бот сам должен убедиться, что пользователь
        состоит в найденном чате, иначе через пересылку можно подсмотреть чужой.
        Возвращает None, если автор не указан или сообщения нет в буфере.
        """
        # Без автора искать только по времени опасно: в ту же секунду могли писать в любом чате
        if user_id is not None:
            author_condition, author_value = "user_id = ?", user_id
        elif user_name:
            author_condition, author_value = "user_name = ?", user_name
        else:
            return None

        query = f"""
        SELECT id, chat_id, chat_title, topic_id, message_id, user_id, user_name, username, text, created_at
        FROM messages
        WHERE {author_condition} AND created_at = ?
        ORDER BY id DESC
        LIMIT 1
        """
        async with get_db_connection(self.db_path) as db:
            async with db.execute(query, (author_value, _to_db_time(sent_at))) as cursor:
                row = await cursor.fetchone()
                return _row_to_message(row) if row else None

    # -------------------------------------------------------------
    # User Read State ("What's new?" scenario)
    # -------------------------------------------------------------
    async def get_user_state(
        self, user_id: int, chat_id: int, topic_id: Optional[int] = None
    ) -> Optional[UserChatState]:
        """Get the user's last read message ID for a given chat / topic."""
        tid = topic_id if topic_id is not None else 0
        query = """
        SELECT user_id, chat_id, topic_id, last_read_message_id, last_summary_at
        FROM user_chat_state
        WHERE user_id = ? AND chat_id = ? AND topic_id = ?
        """
        async with get_db_connection(self.db_path) as db:
            async with db.execute(query, (user_id, chat_id, tid)) as cursor:
                row = await cursor.fetchone()
                if not row:
                    return None
                return UserChatState(
                    user_id=row["user_id"],
                    chat_id=row["chat_id"],
                    topic_id=None if row["topic_id"] == 0 else row["topic_id"],
                    last_read_message_id=row["last_read_message_id"],
                    last_summary_at=_from_db_time(row["last_summary_at"])
                    if row["last_summary_at"]
                    else None,
                )

    async def update_user_state(
        self, user_id: int, chat_id: int, last_read_message_id: int, topic_id: Optional[int] = None
    ) -> None:
        """Update user's last read message ID and summary timestamp."""
        tid = topic_id if topic_id is not None else 0
        now_str = _to_db_time(datetime.now(timezone.utc))
        query = """
        INSERT INTO user_chat_state (user_id, chat_id, topic_id, last_read_message_id, last_summary_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(user_id, chat_id, topic_id) DO UPDATE SET
            last_read_message_id = MAX(last_read_message_id, excluded.last_read_message_id),
            last_summary_at = excluded.last_summary_at
        """
        async with get_db_connection(self.db_path) as db:
            await db.execute(query, (user_id, chat_id, tid, last_read_message_id, now_str))
            await db.commit()

    async def get_unread_messages(
        self, user_id: int, chat_id: int, topic_id: Optional[int] = None, limit: int = 500
    ) -> Tuple[List[ChatMessage], int]:
        """Fetch all messages posted since the user's last summary."""
        state = await self.get_user_state(user_id=user_id, chat_id=chat_id, topic_id=topic_id)
        start_id = state.last_read_message_id if state else 0
        messages = await self.get_messages_since(
            chat_id=chat_id,
            start_message_id=start_id,
            topic_id=topic_id,
            inclusive=False,
            limit=limit,
        )
        return messages, start_id

    # -------------------------------------------------------------
    # Ephemeral Buffer TTL Cleanup (152-ФЗ / GDPR compliance)
    # -------------------------------------------------------------
    async def cleanup_old_messages(self, ttl_hours: int = 48) -> int:
        """Delete messages older than ttl_hours from SQLite buffer. Returns deleted row count."""
        if ttl_hours <= 0:
            return 0  # Cleanup disabled

        cutoff_dt = datetime.now(timezone.utc) - timedelta(hours=ttl_hours)
        cutoff_str = _to_db_time(cutoff_dt)
        query = "DELETE FROM messages WHERE created_at < ?"

        async with get_db_connection(self.db_path) as db:
            cursor = await db.execute(query, (cutoff_str,))
            await db.commit()
            deleted_count = cursor.rowcount
            if deleted_count > 0:
                logger.info(f"Ephemeral cleanup: removed {deleted_count} messages older than {cutoff_str}")
            return deleted_count

    # -------------------------------------------------------------
    # Chat & Topic Discovery (for Mini App dashboard & menus)
    # -------------------------------------------------------------
    async def get_active_chats_and_topics(self) -> List[Dict[str, Any]]:
        """Get list of all tracked chats and their topics with message counts."""
        query = """
        SELECT
            chat_id,
            chat_title,
            topic_id,
            COUNT(id) as message_count,
            MAX(message_id) as latest_message_id,
            MAX(created_at) as latest_activity
        FROM messages
        GROUP BY chat_id, topic_id
        ORDER BY latest_activity DESC
        """
        async with get_db_connection(self.db_path) as db:
            async with db.execute(query) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    # -------------------------------------------------------------
    # BYOK (Bring Your Own Key) User Key Management
    # -------------------------------------------------------------
    async def save_user_api_key(self, user_id: int, encrypted_key: str) -> None:
        """Store or update user's encrypted Gemini API key."""
        now_str = _to_db_time(datetime.now(timezone.utc))
        query = """
        INSERT INTO user_api_keys (user_id, encrypted_key, created_at)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            encrypted_key = excluded.encrypted_key,
            created_at = excluded.created_at
        """
        async with get_db_connection(self.db_path) as db:
            await db.execute(query, (user_id, encrypted_key, now_str))
            await db.commit()

    async def get_user_api_key(self, user_id: int) -> Optional[str]:
        """Fetch user's encrypted Gemini API key."""
        query = "SELECT encrypted_key FROM user_api_keys WHERE user_id = ?"
        async with get_db_connection(self.db_path) as db:
            async with db.execute(query, (user_id,)) as cursor:
                row = await cursor.fetchone()
                return row["encrypted_key"] if row else None

    async def delete_user_api_key(self, user_id: int) -> bool:
        """Delete user's custom API key."""
        query = "DELETE FROM user_api_keys WHERE user_id = ?"
        async with get_db_connection(self.db_path) as db:
            cursor = await db.execute(query, (user_id,))
            await db.commit()
            return cursor.rowcount > 0


repository = MessageRepository()
