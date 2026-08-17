from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SONAKIT_", case_sensitive=False)

    app_name: str = "SonaKit"
    app_version: str = "0.1.0"
    host: str = "0.0.0.0"
    port: int = 62793
    log_level: str = "INFO"
    cors_origins: list[str] = Field(default_factory=list)
    max_upload_bytes: int = 10 * 1024 * 1024
    max_image_pixels: int = 40_000_000
    max_image_dimension: int = 16_384
    image_concurrency: int = 2


@lru_cache
def get_settings() -> Settings:
    return Settings()

