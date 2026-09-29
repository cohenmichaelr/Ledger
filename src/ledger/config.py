"""App settings, read from environment variables (prefix LEDGER_) or a .env file.

C# analogy: this is your appsettings.json + IOptions<T>.
"""

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LEDGER_", env_file=".env")

    database_url: str = "sqlite:///./ledger.db"
    debug: bool = False

    @field_validator("database_url")
    @classmethod
    def use_psycopg_driver(cls, url: str) -> str:
        # Hosts like Neon hand out postgresql://... (or postgres://...) URLs. SQLAlchemy would
        # pick the psycopg2 driver for those; we install psycopg 3, so name it explicitly.
        for prefix in ("postgresql://", "postgres://"):
            if url.startswith(prefix):
                return "postgresql+psycopg://" + url.removeprefix(prefix)
        return url


@lru_cache
def get_settings() -> Settings:
    return Settings()
