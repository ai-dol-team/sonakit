from typing import Any

from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    code: str = Field(examples=["invalid_image"])
    detail: str | list[dict[str, Any]]
    request_id: str = Field(examples=["d8d40b646b11434491d4bd66d81b55d5"])


IMAGE_BINARY_CONTENT = {
    "image/jpeg": {"schema": {"type": "string", "format": "binary"}},
    "image/png": {"schema": {"type": "string", "format": "binary"}},
    "image/webp": {"schema": {"type": "string", "format": "binary"}},
}

IMAGE_DIMENSION_HEADERS = {
    "X-Image-Width": {
        "description": "Output image width in pixels.",
        "schema": {"type": "integer"},
    },
    "X-Image-Height": {
        "description": "Output image height in pixels.",
        "schema": {"type": "integer"},
    },
}

IMAGE_ERROR_RESPONSES = {
    400: {"model": ErrorResponse, "description": "Invalid image or capability request."},
    413: {"model": ErrorResponse, "description": "Upload or decoded image exceeds a limit."},
    415: {"model": ErrorResponse, "description": "Detected image format is unsupported."},
    422: {"model": ErrorResponse, "description": "Request parameters failed validation."},
}
