from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

HexColor = Annotated[str, StringConstraints(pattern=r"^#[0-9A-Fa-f]{6}$")]


class ErrorCorrection(StrEnum):
    LOW = "L"
    MEDIUM = "M"
    QUARTILE = "Q"
    HIGH = "H"


class GenerateQrCodeRequest(BaseModel):
    text: Annotated[str, StringConstraints(min_length=1, max_length=2048)] = Field(
        examples=["https://example.com/order/4W9X2"]
    )
    error_correction: ErrorCorrection = Field(
        default=ErrorCorrection.MEDIUM,
        description="QR error-correction level: L, M, Q, or H.",
    )
    box_size: int = Field(default=10, ge=1, le=20, description="Pixels per QR module.")
    border: int = Field(default=4, ge=0, le=20, description="Quiet-zone width in modules.")
    dark_color: HexColor = Field(default="#000000", description="Foreground color.")
    light_color: HexColor = Field(default="#FFFFFF", description="Background color.")


class QrCodeResult(BaseModel):
    text: str
    points: list[list[float]]


class RecognizeQrCodeResponse(BaseModel):
    count: int
    codes: list[QrCodeResult]
