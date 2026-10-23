import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone

from app.database.db import init_db
from app.database.models import ChatMessage
from app.database.repository import MessageRepository
from app.services.crypto import cipher


async def test_all():
    test_db = f"test_storage_{uuid.uuid4().hex[:6]}.db"

    print("[*] Initializing test database...")
    await init_db(test_db)
    repo = MessageRepository(test_db)

    try:
        # 1. Test Message Saving & Deduplication
        print("[*] Testing message save and deduplication...")
        now = datetime.now(timezone.utc)
        msg1 = ChatMessage(
            chat_id=-1001234567890,
            chat_title="Закулисье",
            topic_id=42,
            message_id=101,
            user_id=555,
            user_name="Ксения",
            username="ksupyl",
            text="Всем привет! Обсуждаем релиз нового курса по Python.",
            created_at=now - timedelta(hours=5),
        )
        inserted1 = await repo.save_message(msg1)
        assert inserted1 is True, "First message should be inserted"

        # Duplicate message_id in the same chat should be ignored
        inserted_dup = await repo.save_message(msg1)
        assert inserted_dup is False, "Duplicate message should not be inserted"

        msg2 = ChatMessage(
            chat_id=-1001234567890,
            chat_title="Закулисье",
            topic_id=42,
            message_id=102,
            user_id=666,
            user_name="Иван",
            username="ivan_dev",
            text="Отличная идея, я подготовлю тесты к субботе.",
            created_at=now - timedelta(hours=3),
        )
        await repo.save_message(msg2)

        msg3_old = ChatMessage(
            chat_id=-1001234567890,
            chat_title="Закулисье",
            topic_id=42,
            message_id=99,
            user_id=777,
            user_name="Архивариус",
            username=None,
            text="Это старое сообщение, которое должно удалиться по TTL.",
            created_at=now - timedelta(hours=50),
        )
        await repo.save_message(msg3_old)

        # 2. Test Fetching Messages Since Message ID
        print("[*] Testing get_messages_since...")
        since_msgs = await repo.get_messages_since(
            chat_id=-1001234567890, start_message_id=101, topic_id=42
        )
        assert len(since_msgs) == 2, f"Expected 2 messages, got {len(since_msgs)}"
        assert since_msgs[0].message_id == 101
        assert since_msgs[1].message_id == 102
        assert since_msgs[0].telegram_link == "https://t.me/c/1234567890/42/101"
        print(f"[OK] Deep link verified: {since_msgs[0].telegram_link}")

        # Время из базы возвращается с поясом UTC и совпадает с записанным (до секунды)
        assert since_msgs[0].created_at.tzinfo is not None, "created_at must be timezone-aware"
        assert since_msgs[0].created_at == msg1.created_at.replace(microsecond=0)
        print("[OK] created_at round-trip keeps UTC timezone")

        # У обычных групп (не супер-) ссылок на сообщения не бывает
        basic_group_msg = msg1.model_copy(update={"chat_id": -4001234567})
        assert basic_group_msg.telegram_link is None, "Basic groups must not get t.me/c links"
        print("[OK] No link for basic groups")

        # 3. Test Forward Finding (matching by text and approximate date)
        print("[*] Testing find_message_by_forward...")
        unix_time = int((now - timedelta(hours=3)).timestamp())
        found = await repo.find_message_by_forward(
            text="Отличная идея, я подготовлю тесты к субботе.", unix_timestamp=unix_time
        )
        assert found is not None, "Message should be found by forward matching"
        assert found.message_id == 102
        print(f"[OK] Found message by forward: id={found.message_id}, author={found.user_name}")

        # 4. Test User Read State & Unread Summary
        print("[*] Testing user state and unread messages...")
        user_id = 999
        # Initially no state, gets all messages
        unread_before, _ = await repo.get_unread_messages(
            user_id=user_id, chat_id=-1001234567890, topic_id=42
        )
        assert len(unread_before) == 3, f"Expected 3 unread, got {len(unread_before)}"

        # Mark as read up to message 101
        await repo.update_user_state(
            user_id=user_id, chat_id=-1001234567890, topic_id=42, last_read_message_id=101
        )
        unread_after, start_id = await repo.get_unread_messages(
            user_id=user_id, chat_id=-1001234567890, topic_id=42
        )
        assert start_id == 101
        assert len(unread_after) == 1
        assert unread_after[0].message_id == 102
        print(f"[OK] Unread messages correctly updated: {len(unread_after)} new message(s)")

        # 5. Test Ephemeral Cleanup (TTL)
        print("[*] Testing ephemeral buffer TTL cleanup...")
        deleted = await repo.cleanup_old_messages(ttl_hours=48)
        assert deleted == 1, f"Expected 1 deleted message older than 48h, got {deleted}"
        remaining = await repo.get_messages_since(chat_id=-1001234567890, start_message_id=0)
        assert len(remaining) == 2, f"Expected 2 remaining messages, got {len(remaining)}"
        print(f"[OK] TTL cleanup deleted {deleted} message(s) successfully.")

        # 6. Test BYOK Encryption & Storage
        print("[*] Testing BYOK encryption and key storage...")
        fake_key = "AIzaSyFakeSecretGeminiKey12345"
        encrypted = cipher.encrypt(fake_key)
        assert encrypted != fake_key
        decrypted = cipher.decrypt(encrypted)
        assert decrypted == fake_key, "Decrypted key must match original"

        await repo.save_user_api_key(user_id=user_id, encrypted_key=encrypted)
        saved_enc = await repo.get_user_api_key(user_id=user_id)
        assert saved_enc == encrypted
        assert cipher.decrypt(saved_enc) == fake_key
        print("[OK] BYOK Fernet encryption and storage verified.")

        # 7. Test Active Chats Listing
        print("[*] Testing active chats and topics listing...")
        active_chats = await repo.get_active_chats_and_topics()
        assert len(active_chats) == 1
        assert active_chats[0]["chat_title"] == "Закулисье"
        assert active_chats[0]["topic_id"] == 42
        print("[OK] Active chats discovery verified.")

        print("SUCCESS: All storage, TTL and encryption tests passed!")
    finally:
        # Cleanup temporary test database files
        for suffix in ["", "-wal", "-shm"]:
            f = f"{test_db}{suffix}"
            if os.path.exists(f):
                try:
                    os.remove(f)
                except Exception:
                    pass


if __name__ == "__main__":
    asyncio.run(test_all())
