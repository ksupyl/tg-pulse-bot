import base64
import hashlib
import logging
from typing import Optional
from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

logger = logging.getLogger(__name__)


def generate_fernet_key() -> str:
    """Generate a fresh base64-encoded 32-byte Fernet key."""
    return Fernet.generate_key().decode("utf-8")


class KeyCipher:
    """Helper for symmetric encryption/decryption of user BYOK Gemini API keys."""

    def __init__(self, key_str: Optional[str] = None):
        key = key_str or settings.encryption_key
        if not key:
            # Fallback to a deterministic key derived from bot_token if encryption_key is unset
            seed = settings.bot_token or "tg-pulse-bot-default-secret-seed"
            derived_32_bytes = hashlib.sha256(seed.encode("utf-8")).digest()
            self._fernet = Fernet(base64.urlsafe_b64encode(derived_32_bytes))
            logger.warning(
                "ENCRYPTION_KEY is not set in .env. Using fallback key derived from BOT_TOKEN."
            )
        else:
            try:
                self._fernet = Fernet(key.encode("utf-8"))
            except Exception as e:
                logger.error(f"Invalid ENCRYPTION_KEY provided: {e}. Falling back.")
                derived_32_bytes = hashlib.sha256(key.encode("utf-8")).digest()
                self._fernet = Fernet(base64.urlsafe_b64encode(derived_32_bytes))

    def encrypt(self, plain_text: str) -> str:
        """Encrypt plain text and return base64-encoded encrypted string."""
        if not plain_text:
            return ""
        return self._fernet.encrypt(plain_text.encode("utf-8")).decode("utf-8")

    def decrypt(self, encrypted_text: str) -> Optional[str]:
        """Decrypt cipher text back to plain text."""
        if not encrypted_text:
            return None
        try:
            return self._fernet.decrypt(encrypted_text.encode("utf-8")).decode("utf-8")
        except InvalidToken:
            logger.error("Failed to decrypt API key: Invalid token or changed encryption key.")
            return None


cipher = KeyCipher()
