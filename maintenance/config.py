"""A karbantartó program beállításai a .env fájlból / környezeti változókból."""

from datetime import datetime

from pydantic_settings import BaseSettings, SettingsConfigDict


class MaintenanceSettings(BaseSettings):
    """A karbantartó vezérlő beállításai. A titkok (API-kulcs) csak a .env-ben vannak."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    render_api_key: str
    render_service_id: str
    render_postgres_id: str
    backend_url: str = "https://okoshuto.onrender.com"
    expiry_warning_days: int = 7
    planned_maintenance_at: datetime | None = None
    http_timeout: float = 30.0
    max_retries: int = 3