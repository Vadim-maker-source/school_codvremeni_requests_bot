from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BACKEND_DIR / "data"


class Settings(BaseSettings):
    app_name: str = "Школьный сервис заявок"
    environment: str = "local"

    database_url: str | None = None

    session_ttl_hours: int = 12
    cookie_secure: bool = False
    cookie_name: str = "shkola_session"
    csrf_cookie_name: str = "shkola_csrf"

    allowed_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    login_max_attempts: int = 10
    login_window_seconds: int = 300

    telegram_bot_token: str | None = None
    telegram_bot_username: str = ''
    notifications_enabled: bool = False
    notifications_poll_seconds: int = 3
    notifications_max_attempts: int = 5

    bootstrap_admin_login: str = "admin"
    bootstrap_admin_password: str | None = None
    bootstrap_operator_login: str = "operator"
    bootstrap_operator_password: str | None = None

    model_config = SettingsConfigDict(
        env_file=str(BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    @property
    def database_url_resolved(self) -> str:
        url = (self.database_url or "").strip()
        if not url:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            return f"sqlite:///{(DATA_DIR / 'requests.db').as_posix()}"

        if url.startswith("sqlite:///") and not url.startswith("sqlite:////"):
            raw_path = url[len("sqlite:///") :]
            path = Path(raw_path)
            if not path.is_absolute():
                DATA_DIR.mkdir(parents=True, exist_ok=True)
                path = (BACKEND_DIR / path).resolve()
            return f"sqlite:///{path.as_posix()}"
        return url

    @property
    def is_sqlite(self) -> bool:
        return self.database_url_resolved.startswith("sqlite:")

    @property
    def allowed_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]

    @property
    def telegram_configured(self) -> bool:
        return bool((self.telegram_bot_token or "").strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
