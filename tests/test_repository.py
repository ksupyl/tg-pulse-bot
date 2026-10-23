"""Тесты слоя данных: буфер сообщений, поиск пересылок, состояние прочтения, TTL, BYOK-ключи."""

from datetime import datetime, timedelta, timezone

import pytest

# Тот же чат, что make_message ставит по умолчанию (conftest.py не импортируют — его грузит сам pytest)
SUPERGROUP_ID = -1001234567890

# --- Буфер сообщений ---


async def test_save_message_ignores_duplicates(repo, make_message):
    msg = make_message()
    assert await repo.save_message(msg) is True
    # Тот же (chat_id, message_id) — INSERT OR IGNORE молча пропускает
    assert await repo.save_message(msg) is False


async def test_get_messages_since_is_ordered_and_inclusive(repo, make_message):
    for message_id in (103, 101, 102):  # пишем вразнобой
        await repo.save_message(make_message(message_id=message_id))
    messages = await repo.get_messages_since(chat_id=SUPERGROUP_ID, start_message_id=102)
    assert [m.message_id for m in messages] == [102, 103]


async def test_created_at_roundtrip_keeps_utc(repo, make_message):
    sent_at = datetime(2026, 10, 23, 14, 5, 7, 123456, tzinfo=timezone.utc)
    await repo.save_message(make_message(created_at=sent_at))
    [saved] = await repo.get_messages_since(chat_id=SUPERGROUP_ID, start_message_id=0)
    # Микросекунды SQLite не хранит, а пояс UTC должен вернуться
    assert saved.created_at == sent_at.replace(microsecond=0)
    assert saved.created_at.tzinfo is not None


async def test_created_at_other_timezone_is_stored_as_utc(repo, make_message):
    moscow = timezone(timedelta(hours=3))
    await repo.save_message(make_message(created_at=datetime(2026, 10, 23, 17, 0, tzinfo=moscow)))
    [saved] = await repo.get_messages_since(chat_id=SUPERGROUP_ID, start_message_id=0)
    assert saved.created_at == datetime(2026, 10, 23, 14, 0, tzinfo=timezone.utc)


# --- Поиск оригинала пересланного сообщения ---


async def test_find_forwarded_message_by_user_id(repo, make_message):
    original = make_message(message_id=102, user_id=666, user_name="Иван")
    await repo.save_message(original)
    found = await repo.find_forwarded_message(sent_at=original.created_at, user_id=666)
    assert found is not None and found.message_id == 102


async def test_find_forwarded_message_by_hidden_user_name(repo, make_message):
    # Автор скрыл пересылки — в forward_origin есть только имя, без ID
    original = make_message(message_id=102, user_id=666, user_name="Иван")
    await repo.save_message(original)
    found = await repo.find_forwarded_message(sent_at=original.created_at, user_name="Иван")
    assert found is not None and found.message_id == 102


@pytest.mark.parametrize(
    ("user_id", "shift"),
    [(555, timedelta(0)), (666, timedelta(seconds=1)), (None, timedelta(0))],
    ids=["wrong-author", "wrong-time", "no-author"],
)
async def test_find_forwarded_message_returns_none_instead_of_guessing(repo, make_message, user_id, shift):
    original = make_message(user_id=666, user_name="Иван")
    await repo.save_message(original)
    found = await repo.find_forwarded_message(sent_at=original.created_at + shift, user_id=user_id)
    assert found is None


# --- Состояние прочтения («Что нового?») ---


async def test_unread_messages_start_after_last_read(repo, make_message):
    for message_id in (101, 102, 103):
        await repo.save_message(make_message(message_id=message_id))

    unread, start_id = await repo.get_unread_messages(user_id=999, chat_id=SUPERGROUP_ID, topic_id=42)
    assert start_id == 0 and len(unread) == 3

    await repo.update_user_state(user_id=999, chat_id=SUPERGROUP_ID, topic_id=42, last_read_message_id=102)
    unread, start_id = await repo.get_unread_messages(user_id=999, chat_id=SUPERGROUP_ID, topic_id=42)
    assert start_id == 102
    assert [m.message_id for m in unread] == [103]


async def test_read_position_never_moves_back(repo):
    await repo.update_user_state(user_id=999, chat_id=SUPERGROUP_ID, last_read_message_id=200)
    await repo.update_user_state(user_id=999, chat_id=SUPERGROUP_ID, last_read_message_id=150)
    state = await repo.get_user_state(user_id=999, chat_id=SUPERGROUP_ID)
    assert state.last_read_message_id == 200
    assert state.last_summary_at.tzinfo is not None


# --- TTL-очистка ---


async def test_cleanup_removes_only_messages_older_than_ttl(repo, make_message):
    now = datetime.now(timezone.utc)
    await repo.save_message(make_message(message_id=1, created_at=now - timedelta(hours=50)))
    await repo.save_message(make_message(message_id=2, created_at=now - timedelta(hours=47)))

    assert await repo.cleanup_old_messages(ttl_hours=48) == 1
    remaining = await repo.get_messages_since(chat_id=SUPERGROUP_ID, start_message_id=0)
    assert [m.message_id for m in remaining] == [2]


# --- Чаты и топики для Mini App ---


async def test_active_chats_are_grouped_by_topic(repo, make_message):
    await repo.save_message(make_message(message_id=1, topic_id=42))
    await repo.save_message(make_message(message_id=2, topic_id=42))
    await repo.save_message(make_message(message_id=3, topic_id=7))
    chats = await repo.get_active_chats_and_topics()
    assert {c["topic_id"]: c["message_count"] for c in chats} == {42: 2, 7: 1}


# --- BYOK-ключи ---


async def test_user_api_key_save_overwrite_delete(repo):
    await repo.save_user_api_key(user_id=999, encrypted_key="gAAAA-first")
    # Повторный /set_key перезаписывает старый ключ, а не добавляет второй
    await repo.save_user_api_key(user_id=999, encrypted_key="gAAAA-second")
    assert await repo.get_user_api_key(999) == "gAAAA-second"

    assert await repo.delete_user_api_key(999) is True
    assert await repo.get_user_api_key(999) is None
