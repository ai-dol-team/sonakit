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
    video_thumbnail_concurrency: int = Field(default=2, ge=1, le=32)
    video_thumbnail_max_duration_seconds: int = Field(default=1_800, ge=1, le=86_400)
    video_thumbnail_max_random_window_seconds: float = Field(default=3.0, ge=0.1, le=60.0)
    video_thumbnail_max_output_width: int = Field(default=1_080, ge=320, le=4_096)
    video_thumbnail_ffprobe_timeout_seconds: int = Field(default=15, ge=1, le=180)
    video_thumbnail_ffmpeg_timeout_seconds: int = Field(default=30, ge=1, le=180)
    video_thumbnail_total_timeout_seconds: int = Field(default=60, ge=1, le=600)
    video_thumbnail_jpeg_quality: int = Field(default=2, ge=2, le=31)


@lru_cache
def get_settings() -> Settings:
    return Settings()
