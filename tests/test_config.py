"""Тесты конфига: бот не стартует с кривыми секретами и не выбалтывает их в ошибках."""

import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from app.config import Settings

FAKE_TOKEN = "123456:DO-NOT-LEAK"
VALID_KEY = Fernet.generate_key().decode()


@pytest.fixture
def clean_env(monkeypatch):
    """Убирает тестовые секреты из окружения (их ставит conftest), чтобы грузить конфиг с нуля.

    monkeypatch — встроенная фикстура pytest: всё, что она поменяла, вернётся обратно после теста.
    """
    for name in ("BOT_TOKEN", "ENCRYPTION_KEY", "DEFAULT_GEMINI_KEY", "ALLOWED_USERS"):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


# _env_file=None во всех тестах ниже — чтобы Settings не подхватил настоящий .env


def test_missing_encryption_key_fails_fast(clean_env):
    with pytest.raises(ValidationError, match="ENCRYPTION_KEY"):
        Settings(_env_file=None, BOT_TOKEN=FAKE_TOKEN)


def test_invalid_encryption_key_fails_with_hint(clean_env):
    with pytest.raises(ValidationError, match="Сгенерируй новый"):
        Settings(_env_file=None, BOT_TOKEN=FAKE_TOKEN, ENCRYPTION_KEY="garbage")


def test_validation_error_does_not_leak_secrets(clean_env):
    # Без hide_input_in_errors pydantic напечатал бы FAKE_TOKEN прямо в тексте ошибки
    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None, BOT_TOKEN=FAKE_TOKEN)
    assert FAKE_TOKEN not in str(exc_info.value)


def test_secrets_are_masked_in_repr(clean_env):
    settings = Settings(_env_file=None, BOT_TOKEN=FAKE_TOKEN, ENCRYPTION_KEY=VALID_KEY)
    assert FAKE_TOKEN not in repr(settings)
    assert VALID_KEY not in repr(settings)


def test_allowed_users_from_env_and_is_admin(clean_env):
    # Через переменную окружения, как в реальном .env: проверяем и NoDecode, и разбор по запятым
    clean_env.setenv("ALLOWED_USERS", "123, 456")
    settings = Settings(_env_file=None, BOT_TOKEN=FAKE_TOKEN, ENCRYPTION_KEY=VALID_KEY)
    assert settings.is_admin(123) and settings.is_admin(456)
    assert not settings.is_admin(999)


def test_allowed_users_rejects_garbage(clean_env):
    clean_env.setenv("ALLOWED_USERS", "123, @ksupyl")
    with pytest.raises(ValidationError, match="ALLOWED_USERS"):
        Settings(_env_file=None, BOT_TOKEN=FAKE_TOKEN, ENCRYPTION_KEY=VALID_KEY)
