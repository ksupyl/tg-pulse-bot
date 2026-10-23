"""Тесты прямых ссылок на сообщения (ChatMessage.telegram_link)."""

import pytest


@pytest.mark.parametrize(
    ("chat_id", "topic_id", "expected"),
    [
        (-1001234567890, 42, "https://t.me/c/1234567890/42/101"),
        (-1001234567890, None, "https://t.me/c/1234567890/101"),
        (-1001234567890, 1, "https://t.me/c/1234567890/101"),
        (-4001234567, None, None),
    ],
    ids=["forum-topic", "supergroup", "general-topic", "basic-group-has-no-links"],
)
def test_telegram_link(make_message, chat_id, topic_id, expected):
    msg = make_message(chat_id=chat_id, topic_id=topic_id, message_id=101)
    assert msg.telegram_link == expected
