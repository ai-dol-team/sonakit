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

from .models import CompressionOptions
from .service import compress_image

router = APIRouter()


@router.post(
    "/compress",
    summary="Compress an image",
    response_class=Response,
    description="Compress an image while preserving its detected format and pixel dimensions.",
    responses={
        200: {
            "description": "Compressed image in the source format.",
            "content": IMAGE_BINARY_CONTENT,
            "headers": {
                **IMAGE_DIMENSION_HEADERS,
                "X-Source-Format": {"schema": {"type": "string"}},
                "X-Output-Format": {"schema": {"type": "string"}},
                "X-Source-Bytes": {"schema": {"type": "integer"}},
                "X-Output-Bytes": {"schema": {"type": "integer"}},
                "X-Compression-Ratio": {"schema": {"type": "number"}},
            },
        },
        **IMAGE_ERROR_RESPONSES,
    },
)
async def compress(
    file: Annotated[UploadFile, File(description="JPEG, PNG, or static WebP image")],
    quality: Annotated[int, Form(ge=1, le=100, description="JPEG/WebP quality.")] = 80,
    optimize: Annotated[bool, Form(description="Enable encoder optimization.")] = True,
    progressive: Annotated[bool, Form(description="Use progressive JPEG encoding.")] = True,
    png_colors: Annotated[
        int | None,
        Form(ge=2, le=256, description="Optional lossy PNG palette size."),
    ] = None,
) -> Response:
    settings = get_settings()
    data = await file.read(settings.max_upload_bytes + 1)
    options = CompressionOptions(
        quality=quality,
        optimize=optimize,
        progressive=progressive,
        png_colors=png_colors,
    )
    result = await to_thread.run_sync(compress_image, data, options)

    headers = {
        "Content-Disposition": (
            f'inline; filename="compressed.{result.source_format.extension}"'
        ),
        "X-Image-Width": str(result.width),
        "X-Image-Height": str(result.height),
        "X-Source-Format": result.source_format.value,
        "X-Output-Format": result.source_format.value,
        "X-Source-Bytes": str(result.source_bytes),
        "X-Output-Bytes": str(result.output_bytes),
        "X-Compression-Ratio": f"{result.compression_ratio:.6f}",
    }
    return Response(
        content=result.content,
        media_type=result.source_format.media_type,
        headers=headers,
    )
