"""
Pydantic-модели данных, которыми обмениваются слои приложения.

Репозиторий (app/database/repository.py) превращает строки SQLite в эти модели,
а бот и Mini App работают уже с ними, ничего не зная про SQL.
"""

from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    """Represents a message stored in the ephemeral chat buffer."""

    id: Optional[int] = None
    chat_id: int
    chat_title: str
    topic_id: Optional[int] = None  # message_thread_id for forum topics
    message_id: int
    user_id: int
    user_name: str
    username: Optional[str] = None
    text: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def telegram_link(self) -> Optional[str]:
        """Прямая ссылка на сообщение: https://t.me/c/<chat>/<msg> или .../<topic>/<msg>.

        Работает только для супергрупп (ID начинается с -100): Telegram строит ссылку
        из ID без этого префикса. У обычных групп ссылок на сообщения нет вообще,
        поэтому для них возвращаем None, а не URL, который никуда не ведёт.
        """
        chat_id = str(self.chat_id)
        if not chat_id.startswith("-100"):
            return None
        clean_chat_id = chat_id.removeprefix("-100")
        # General-топик (id = 1) открывается обычной ссылкой, без номера топика
        if self.topic_id and self.topic_id > 1:
            return f"https://t.me/c/{clean_chat_id}/{self.topic_id}/{self.message_id}"
        return f"https://t.me/c/{clean_chat_id}/{self.message_id}"


class UserChatState(BaseModel):
    """Tracks user's read position in a chat or topic for unread summaries."""

    user_id: int
    chat_id: int
    topic_id: Optional[int] = None
    last_read_message_id: int = 0
    last_summary_at: Optional[datetime] = None


class UserApiKey(BaseModel):
    """Stores encrypted Gemini API key for external users (BYOK)."""

    user_id: int
    encrypted_key: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
