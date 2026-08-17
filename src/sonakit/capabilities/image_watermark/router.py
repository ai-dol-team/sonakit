import logging
from typing import Annotated, Literal

from fastapi import APIRouter, File, Form, Response, UploadFile
from starlette.concurrency import run_in_threadpool

from sonakit.capabilities.image_watermark.models import WatermarkLayout, WatermarkPosition
from sonakit.capabilities.image_watermark.service import (
    WatermarkOptions,
    apply_watermark,
    validate_runtime,
)
from sonakit.core.capabilities import CapabilityModule
from sonakit.core.config import get_settings
from sonakit.core.errors import ImageTooLargeError
from sonakit.core.openapi import (
    IMAGE_BINARY_CONTENT,
    IMAGE_DIMENSION_HEADERS,
    IMAGE_ERROR_RESPONSES,
)

router = APIRouter()
logger = logging.getLogger(__name__)
settings = get_settings()
_HEX_COLOR = r"^#[0-9A-Fa-f]{6}$"


@router.post(
    "/watermark",
    response_class=Response,
    summary="Apply a multilingual text watermark",
    description=(
        "Render the text supplied in this request. The service does not translate text or require "
        "a locale; it selects an embedded Noto font from the actual Unicode writing system."
    ),
    responses={
        200: {
            "description": "Watermarked image in the detected source format.",
            "content": IMAGE_BINARY_CONTENT,
            "headers": {
                **IMAGE_DIMENSION_HEADERS,
                "X-Watermark-Font-Size": {
                    "description": "Actual font size after fit-to-cell shrinking.",
                    "schema": {"type": "integer"},
                },
                "X-Watermark-Layout": {
                    "description": "Applied layout: tiled or single.",
                    "schema": {"type": "string"},
                },
                "X-Watermark-Count": {
                    "description": "Number of visible watermark text instances.",
                    "schema": {"type": "integer"},
                },
                "X-Watermark-Position": {
                    "description": "Nine-grid position; returned only for layout=single.",
                    "schema": {"type": "string"},
                },
            },
        },
        **IMAGE_ERROR_RESPONSES,
    },
)
async def create_watermark(
    file: Annotated[UploadFile, File(description="JPEG, PNG, or static WebP image")],
    text: Annotated[
        str,
        Form(
            min_length=1,
            max_length=128,
            description=(
                "Request-specific single-line watermark text; NFC-normalized by the service."
            ),
            examples=["订单 4W9X2"],
        ),
    ],
    layout: Annotated[
        WatermarkLayout,
        Form(description="Tiled coverage or a single positioned watermark."),
    ] = WatermarkLayout.TILED,
    position: Annotated[
        WatermarkPosition,
        Form(description="Nine-grid anchor used only when layout=single."),
    ] = (
        WatermarkPosition.BOTTOM_RIGHT
    ),
    font_size: Annotated[
        int,
        Form(ge=8, le=512, description="Requested font size in pixels."),
    ] = 16,
    font_weight: Annotated[
        Literal[400, 600],
        Form(description="Embedded Noto font weight: regular 400 or semibold 600."),
    ] = 600,
    letter_spacing: Annotated[
        float,
        Form(ge=0, le=20, description="Extra spacing between Unicode grapheme clusters in pixels."),
    ] = 1.1,
    color: Annotated[str, Form(pattern=_HEX_COLOR, description="Text color as #RRGGBB.")] = (
        "#FFFFFF"
    ),
    opacity: Annotated[
        float,
        Form(ge=0.05, le=1.0, description="Opacity applied to text and stroke."),
    ] = 0.5,
    rotation_degrees: Annotated[
        float,
        Form(ge=-180, le=180, description="Clockwise text rotation in degrees."),
    ] = -28,
    tile_width: Annotated[
        int,
        Form(ge=32, le=4096, description="Width of each tiled watermark cell in pixels."),
    ] = 150,
    tile_height: Annotated[
        int,
        Form(ge=24, le=4096, description="Height of each tiled watermark cell in pixels."),
    ] = 81,
    margin: Annotated[
        int | None,
        Form(ge=0, le=4096, description="Inset margin in pixels; omit for automatic sizing."),
    ] = None,
    offset_x: Annotated[
        int,
        Form(ge=-10000, le=10000, description="Horizontal offset; positive moves right."),
    ] = 0,
    offset_y: Annotated[
        int,
        Form(ge=-10000, le=10000, description="Vertical offset; positive moves down."),
    ] = 0,
    stroke_color: Annotated[
        str,
        Form(pattern=_HEX_COLOR, description="Stroke color as #RRGGBB."),
    ] = "#000000",
    stroke_width: Annotated[
        int,
        Form(ge=0, le=32, description="Stroke width in pixels; zero disables the stroke."),
    ] = 0,
) -> Response:
    contents = await file.read(settings.max_upload_bytes + 1)
    if len(contents) > settings.max_upload_bytes:
        raise ImageTooLargeError(
            f"The uploaded file exceeds the {settings.max_upload_bytes // (1024 * 1024)} MiB limit."
        )

    options = WatermarkOptions(
        text=text,
        layout=layout,
        position=position,
        font_size=font_size,
        font_weight=font_weight,
        letter_spacing=letter_spacing,
        color=color,
        opacity=opacity,
        rotation_degrees=rotation_degrees,
        tile_width=tile_width,
        tile_height=tile_height,
        margin=margin,
        offset_x=offset_x,
        offset_y=offset_y,
        stroke_color=stroke_color,
        stroke_width=stroke_width,
    )
    result = await run_in_threadpool(apply_watermark, contents, options)
    logger.info(
        "event=image.watermark.completed source_format=%s width=%d height=%d text_length=%d "
        "script=%s font_size=%d font_weight=%d layout=%s watermark_count=%d "
        "input_bytes=%d output_bytes=%d duration_ms=%.3f",
        result.source_format,
        result.width,
        result.height,
        result.text_length,
        result.script,
        result.font_size,
        font_weight,
        result.layout.value,
        result.watermark_count,
        len(contents),
        len(result.image_bytes),
        result.duration_ms,
    )
    headers = {
        "Content-Disposition": f'inline; filename="watermarked.{result.extension}"',
        "X-Image-Width": str(result.width),
        "X-Image-Height": str(result.height),
        "X-Watermark-Font-Size": str(result.font_size),
        "X-Watermark-Layout": result.layout.value,
        "X-Watermark-Count": str(result.watermark_count),
    }
    if result.layout == WatermarkLayout.SINGLE:
        headers["X-Watermark-Position"] = result.position.value
    return Response(
        result.image_bytes,
        media_type=result.media_type,
        headers=headers,
    )


module = CapabilityModule(
    name="image_watermark",
    description="Apply single-line multilingual text watermarks to images.",
    prefix="/image",
    router=router,
    tags=("Image Watermark",),
    validate_runtime=validate_runtime,
)
