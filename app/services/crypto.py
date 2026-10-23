"""
Шифрование пользовательских API-ключей Gemini (BYOK) через Fernet.

Ключи внешних пользователей лежат в таблице `user_api_keys` только в зашифрованном
виде (см. app/database/repository.py). Утащив файл базы без ENCRYPTION_KEY,
злоумышленник увидит лишь строки вида `gAAAAA...`.
Сам ENCRYPTION_KEY заранее проверяется в app/config.py, поэтому здесь нет никаких
«запасных» ключей: нет ключа — бот просто не запустится.
"""

import logging

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

logger = logging.getLogger(__name__)


class KeyCipher:
    """Симметричное шифрование строк одним секретным ключом.

    «Симметричное» — значит один и тот же ключ и шифрует, и расшифровывает.
    Fernet — это AES плюс подпись (HMAC): подделанную или обрезанную строку
    он не расшифрует в мусор, а честно бросит InvalidToken.
    """

    def __init__(self, key: str):
        """Принимает Fernet-ключ (44 символа base64) и готовит шифровальщик."""
        self._fernet = Fernet(key)

    def encrypt(self, plain_text: str) -> str:
        """Шифрует строку и возвращает токен Fernet текстом — чтобы положить в колонку TEXT."""
        return self._fernet.encrypt(plain_text.encode("utf-8")).decode("utf-8")

    def decrypt(self, encrypted_text: str) -> str | None:
        """Расшифровывает токен обратно в строку.

        Возвращает None, если токен не подходит к текущему ENCRYPTION_KEY
        (ключ сменили или запись повреждена) — тогда пользователю нужно заново сделать /set_key.
        """
        try:
            return self._fernet.decrypt(encrypted_text.encode("utf-8")).decode("utf-8")
        except InvalidToken:
            logger.error("Не удалось расшифровать API-ключ: запись повреждена или сменился ENCRYPTION_KEY.")
            return None


# Один экземпляр на всё приложение — так же, как `settings` и `repository`
cipher = KeyCipher(settings.encryption_key.get_secret_value())
