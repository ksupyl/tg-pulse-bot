"""Тесты шифрования BYOK-ключей (KeyCipher)."""

from cryptography.fernet import Fernet

from app.services.crypto import KeyCipher

GEMINI_KEY = "AIzaSyFakeSecretGeminiKey12345"


def make_cipher() -> KeyCipher:
    """Шифровальщик со свежим случайным ключом — каждый вызов даёт «другой сейф»."""
    return KeyCipher(Fernet.generate_key().decode())


def test_encrypt_decrypt_roundtrip():
    cipher = make_cipher()
    encrypted = cipher.encrypt(GEMINI_KEY)
    assert GEMINI_KEY not in encrypted
    assert cipher.decrypt(encrypted) == GEMINI_KEY


def test_decrypt_with_other_key_returns_none():
    # Так выглядит смена ENCRYPTION_KEY: старые записи больше не расшифровываются
    encrypted = make_cipher().encrypt(GEMINI_KEY)
    assert make_cipher().decrypt(encrypted) is None


def test_decrypt_tampered_token_returns_none():
    # Меняем один символ в середине токена — подпись HMAC больше не сходится
    cipher = make_cipher()
    encrypted = cipher.encrypt(GEMINI_KEY)
    middle = len(encrypted) // 2
    replacement = "A" if encrypted[middle] != "A" else "B"
    tampered = encrypted[:middle] + replacement + encrypted[middle + 1 :]
    assert cipher.decrypt(tampered) is None
