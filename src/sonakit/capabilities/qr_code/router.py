from __future__ import annotations

from typing import Annotated

import anyio
from fastapi import APIRouter, File, UploadFile
from fastapi.responses import Response

from sonakit.capabilities.qr_code.models import (
    GenerateQrCodeRequest,
    RecognizeQrCodeResponse,
)
from sonakit.capabilities.qr_code.service import generate_qr_code, recognize_qr_codes
from sonakit.core.config import get_settings
from sonakit.core.openapi import IMAGE_DIMENSION_HEADERS, IMAGE_ERROR_RESPONSES, ErrorResponse

router = APIRouter()


@router.post(
    "/generate",
    response_class=Response,
    description="Generate a PNG QR code from request-specific Unicode text.",
    responses={
        200: {
            "description": "Generated QR code PNG.",
            "content": {"image/png": {"schema": {"type": "string", "format": "binary"}}},
            "headers": IMAGE_DIMENSION_HEADERS,
        },
        400: {"model": ErrorResponse, "description": "Text does not fit a QR code."},
        422: {"model": ErrorResponse, "description": "JSON parameters failed validation."},
    },
    summary="Generate a QR code",
)
async def generate(request: GenerateQrCodeRequest) -> Response:
    result = await anyio.to_thread.run_sync(generate_qr_code, request)
    return Response(
        content=result.content,
        media_type="image/png",
        headers={
            "Content-Disposition": 'inline; filename="qrcode.png"',
            "X-Image-Width": str(result.width),
            "X-Image-Height": str(result.height),
        },
    )


@router.post(
    "/recognize",
    response_model=RecognizeQrCodeResponse,
    summary="Recognize QR codes in an image",
    description="Recognize one or more QR codes and return decoded text with corner coordinates.",
    responses=IMAGE_ERROR_RESPONSES,
)
async def recognize(
    file: Annotated[UploadFile, File(description="JPEG, PNG, or static WebP image")],
) -> RecognizeQrCodeResponse:
    max_bytes = get_settings().max_upload_bytes
    data = await file.read(max_bytes + 1)
    codes = await anyio.to_thread.run_sync(recognize_qr_codes, data)
    return RecognizeQrCodeResponse(count=len(codes), codes=codes)
