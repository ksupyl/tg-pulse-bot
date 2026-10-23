"""
Общие заготовки (фикстуры) для всех тестов pytest.

pytest сам находит этот файл и выполняет его раньше тестов. Здесь мы:
1. подставляем фейковые секреты в окружение — ДО импорта приложения, потому что
   app/config.py создаёт settings прямо при импорте, а переменные окружения важнее .env.
   Так тесты не зависят от настоящего .env и никогда не видят реальные токены;
2. даём каждому тесту чистую временную базу и фабрику тестовых сообщений.
"""

import os
from datetime import datetime, timezone

import pytest
from cryptography.fernet import Fernet

os.environ.update(
    {
        "BOT_TOKEN": "123456:test-token",
        "ENCRYPTION_KEY": Fernet.generate_key().decode(),
        "DEFAULT_GEMINI_KEY": "test-gemini-key",
        "ALLOWED_USERS": "111",
    }
)

# Импорты приложения — строго после подмены окружения выше, поэтому noqa: E402
from app.database.db import init_db  # noqa: E402
from app.database.models import ChatMessage  # noqa: E402
from app.database.repository import MessageRepository  # noqa: E402

SUPERGROUP_ID = -1001234567890


@pytest.fixture
async def repo(tmp_path) -> MessageRepository:
    """Репозиторий на чистой базе — своей для каждого теста.

    tmp_path — встроенная фикстура pytest: уникальная временная папка, которую
    pytest убирает сам. Тесты не видят данных друг друга и не мусорят в проекте.
    """
    db_path = str(tmp_path / "test.db")
    await init_db(db_path)
    return MessageRepository(db_path)


@pytest.fixture
def make_message():
    """Фабрика тестовых сообщений: в тесте указываешь только то, что важно именно ему.

    make_message(message_id=102, user_id=666) — остальные поля возьмутся из defaults.
    """

    def _make(**overrides) -> ChatMessage:
        defaults = {
            "chat_id": SUPERGROUP_ID,
            "chat_title": "Закулисье",
            "topic_id": 42,
            "message_id": 101,
            "user_id": 555,
            "user_name": "Ксения",
            "username": "ksupyl",
            "text": "Всем привет! Обсуждаем релиз нового курса по Python.",
            "created_at": datetime.now(timezone.utc),
        }
        return ChatMessage(**(defaults | overrides))

    return _make
