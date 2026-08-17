from __future__ import annotations

from typing import Annotated

from anyio import to_thread
from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import Response

from sonakit.core.config import get_settings
from sonakit.core.openapi import (
    IMAGE_BINARY_CONTENT,
    IMAGE_DIMENSION_HEADERS,
    IMAGE_ERROR_RESPONSES,
)

from .models import ConversionOptions, TargetFormat
from .service import convert_image

router = APIRouter()


@router.post(
    "/convert",
    summary="Convert an image",
    response_class=Response,
    description="Convert an image to JPEG, PNG, or WebP without changing pixel dimensions.",
    responses={
        200: {
            "description": "Converted image in the requested format.",
            "content": IMAGE_BINARY_CONTENT,
            "headers": {
                **IMAGE_DIMENSION_HEADERS,
                "X-Source-Format": {"schema": {"type": "string"}},
                "X-Output-Format": {"schema": {"type": "string"}},
                "X-Source-Bytes": {"schema": {"type": "integer"}},
                "X-Output-Bytes": {"schema": {"type": "integer"}},
                "X-Size-Ratio": {"schema": {"type": "number"}},
            },
        },
        **IMAGE_ERROR_RESPONSES,
    },
)
async def convert(
    file: Annotated[UploadFile, File(description="JPEG, PNG, or static WebP image")],
    target_format: Annotated[TargetFormat, Form(description="jpeg, png, or webp")],
    quality: Annotated[int, Form(ge=1, le=100, description="JPEG/WebP quality.")] = 90,
    background_color: Annotated[
        str,
        Form(
            pattern=r"^#[0-9A-Fa-f]{6}$",
            description="Background used when flattening transparency to JPEG.",
        ),
    ] = "#FFFFFF",
) -> Response:
    settings = get_settings()
    data = await file.read(settings.max_upload_bytes + 1)
    options = ConversionOptions(
        target_format=target_format,
        quality=quality,
        background_color=background_color,
    )
    result = await to_thread.run_sync(convert_image, data, options)

    headers = {
        "Content-Disposition": f'inline; filename="converted.{result.output_format.extension}"',
        "X-Image-Width": str(result.width),
        "X-Image-Height": str(result.height),
        "X-Source-Format": result.source_format.value,
        "X-Output-Format": result.output_format.value,
        "X-Source-Bytes": str(result.source_bytes),
        "X-Output-Bytes": str(result.output_bytes),
        "X-Size-Ratio": f"{result.size_ratio:.6f}",
    }
    return Response(
        content=result.content,
        media_type=result.output_format.media_type,
        headers=headers,
    )
