"""Az alkalmazás beállításai, környezeti változókból vagy a .env fájlból."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """A backend összes környezetfüggő beállítása egy helyen."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    database_url: str = "sqlite:///./okoshuto.db"
    log_level: str = "INFO"
    maintenance_mode: bool = False
    maintenance_token: str = ""


@lru_cache
def get_settings() -> Settings:
    """Egyszer beolvassa a beállításokat, utána ugyanazt adja vissza."""
    return Settings()