"""
Конфигурация приложения — единственное место, где читается `.env`.

Остальные модули (БД, шифрование, бот, веб) импортируют готовый объект `settings`
и не знают, откуда взялись значения. Если обязательного секрета нет или он кривой,
приложение падает сразу при старте, а не через неделю на первом пользователе
(принцип fail fast).
"""

from typing import Annotated

from cryptography.fernet import Fernet
from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Настройки бота из переменных окружения и файла `.env`.

    Переменные окружения важнее `.env`: так ключи можно подставить снаружи
    (в Docker или в тестах), не трогая файл.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        # Лишние переменные в .env (например, старый WHITELIST_ENABLED) не роняют запуск
        extra="ignore",
        # Без этого pydantic при ошибке печатает ВСЕ прочитанные значения,
        # включая токены, — прямо в консоль и в логи сервера
        hide_input_in_errors=True,
    )

    # --- Секреты ---
    # SecretStr прячет значение при print() и в логах: вместо токена будет '**********'.
    # Настоящее значение достаётся только явно, через .get_secret_value()
    bot_token: SecretStr = Field(alias="BOT_TOKEN")
    encryption_key: SecretStr = Field(alias="ENCRYPTION_KEY")
    # Общий ключ Gemini для админов. Необязателен: без него бот работает только по BYOK
    default_gemini_key: SecretStr | None = Field(default=None, alias="DEFAULT_GEMINI_KEY")

    # --- Доступ ---
    # ID админов через запятую: "123, 456". Только они тратят общий default_gemini_key,
    # остальные пользуются ботом со своим ключом через /set_key.
    # NoDecode запрещает pydantic-settings ждать здесь JSON ("[123, 456]") —
    # строку мы разбираем сами в split_allowed_users
    allowed_users: Annotated[set[int], NoDecode] = Field(default_factory=set, alias="ALLOWED_USERS")

    # --- Хранилище и TTL ---
    database_path: str = Field(default="tg_pulse.db", alias="DATABASE_PATH")
    buffer_ttl_hours: int = Field(default=48, alias="BUFFER_TTL_HOURS")

    @field_validator("encryption_key")
    @classmethod
    def validate_fernet_key(cls, value: SecretStr) -> SecretStr:
        """Проверяет, что ENCRYPTION_KEY — настоящий Fernet-ключ (32 байта в base64).

        Проверяем при старте, чтобы кривой ключ не всплыл позже ошибкой
        на первом же /set_key у живого пользователя.
        """
        try:
            Fernet(value.get_secret_value())
        except ValueError:
            # from None — чтобы в трейсбеке не светилось исходное исключение со значением ключа
            raise ValueError(
                "ENCRYPTION_KEY невалиден. Сгенерируй новый: "
                'python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
            ) from None
        return value

    @field_validator("allowed_users", mode="before")
    @classmethod
    def split_allowed_users(cls, value: object) -> object:
        """Режет строку "123, 456" на элементы; в int их превратит уже сам pydantic.

        Мусор вроде "@ksupyl" не пропускается молча, а роняет запуск с ошибкой —
        иначе админ не понял бы, почему бот не даёт ему общий ключ.
        """
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    def is_admin(self, user_id: int) -> bool:
        """Возвращает True, если пользователю можно тратить общий DEFAULT_GEMINI_KEY."""
        return user_id in self.allowed_users


settings = Settings()
