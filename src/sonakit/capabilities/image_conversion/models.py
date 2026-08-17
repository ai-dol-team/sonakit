from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class TargetFormat(StrEnum):
    JPEG = "jpeg"
    PNG = "png"
    WEBP = "webp"


class ConversionOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_format: TargetFormat
    quality: int = Field(default=90, ge=1, le=100)
    background_color: str = Field(default="#FFFFFF", pattern=r"^#[0-9A-Fa-f]{6}$")
