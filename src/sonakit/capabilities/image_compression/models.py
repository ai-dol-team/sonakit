from pydantic import BaseModel, ConfigDict, Field


class CompressionOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quality: int = Field(default=80, ge=1, le=100)
    optimize: bool = True
    progressive: bool = True
    png_colors: int | None = Field(default=None, ge=2, le=256)


class CompressionResult(BaseModel):
    width: int
    height: int
    source_format: str
    output_format: str
    source_bytes: int
    output_bytes: int

    @property
    def compression_ratio(self) -> float:
        return self.output_bytes / self.source_bytes
