from __future__ import annotations

from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class VideoThumbnailRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    video_url: str = Field(min_length=1, max_length=4096)
    prefer_first_frame: bool = True
    fallback_random_window_seconds: float = Field(default=3.0, ge=0.1, le=3.0)
    max_output_width: int = Field(default=1080, ge=320, le=1080)
    frame_selection_strategy: Literal["near_start", "random_cover"] = "near_start"
    random_min_ratio: float = Field(default=0.15, ge=0.0, le=0.95)
    random_max_ratio: float = Field(default=0.85, ge=0.0, le=0.98)
    random_candidate_count: int = Field(default=3, ge=1, le=5)

    @field_validator("video_url")
    @classmethod
    def validate_video_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("video_url must be an absolute HTTP(S) URL")
        return value

    @model_validator(mode="after")
    def validate_random_range(self) -> VideoThumbnailRequest:
        if self.random_min_ratio > self.random_max_ratio:
            raise ValueError("random_min_ratio must be less than or equal to random_max_ratio")
        return self
