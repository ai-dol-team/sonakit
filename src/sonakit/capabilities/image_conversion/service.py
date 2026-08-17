from __future__ import annotations

import logging
from dataclasses import dataclass

from sonakit.media.images import (
    ImageFormat,
    decode_image,
    encode_image,
    image_processing_semaphore,
)

from .models import ConversionOptions, TargetFormat

logger = logging.getLogger(__name__)

_TARGET_IMAGE_FORMATS = {
    TargetFormat.JPEG: ImageFormat.JPEG,
    TargetFormat.PNG: ImageFormat.PNG,
    TargetFormat.WEBP: ImageFormat.WEBP,
}


@dataclass(frozen=True, slots=True)
class ConvertedImage:
    content: bytes
    width: int
    height: int
    source_format: ImageFormat
    output_format: ImageFormat
    source_bytes: int

    @property
    def output_bytes(self) -> int:
        return len(self.content)

    @property
    def size_ratio(self) -> float:
        return self.output_bytes / self.source_bytes


def convert_image(data: bytes, options: ConversionOptions) -> ConvertedImage:
    with image_processing_semaphore:
        decoded = decode_image(data)
        width, height = decoded.image.size
        output_format = _TARGET_IMAGE_FORMATS[options.target_format]
        output = encode_image(
            decoded.image,
            output_format,
            quality=options.quality,
            optimize=True,
            background_color=options.background_color,
        )

    result = ConvertedImage(
        content=output,
        width=width,
        height=height,
        source_format=decoded.source_format,
        output_format=output_format,
        source_bytes=len(data),
    )
    logger.info(
        "image_conversion_completed source_format=%s output_format=%s width=%d height=%d "
        "source_bytes=%d output_bytes=%d ratio=%.6f",
        result.source_format.value,
        result.output_format.value,
        result.width,
        result.height,
        result.source_bytes,
        result.output_bytes,
        result.size_ratio,
    )
    return result
