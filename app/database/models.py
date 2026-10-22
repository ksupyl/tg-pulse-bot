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
    def clean_chat_id(self) -> str:
        """Strip -100 prefix for Telegram web link generation."""
        s = str(self.chat_id)
        if s.startswith("-100"):
            return s[4:]
        if s.startswith("-"):
            return s[1:]
        return s

    @property
    def telegram_link(self) -> str:
        """Generate direct deep link to the message in Telegram."""
        clean = self.clean_chat_id
        if self.topic_id and self.topic_id > 1:
            return f"https://t.me/c/{clean}/{self.topic_id}/{self.message_id}"
        return f"https://t.me/c/{clean}/{self.message_id}"


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
