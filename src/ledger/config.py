"""App settings, read from environment variables (prefix LEDGER_) or a .env file.

C# analogy: this is your appsettings.json + IOptions<T>.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LEDGER_", env_file=".env")

    database_url: str = "sqlite:///./ledger.db"
    debug: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
