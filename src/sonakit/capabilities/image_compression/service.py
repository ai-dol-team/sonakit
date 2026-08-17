from __future__ import annotations

import logging
from dataclasses import dataclass

from PIL import Image

from sonakit.media.images import (
    ImageFormat,
    decode_image,
    encode_image,
    image_processing_semaphore,
)

from .models import CompressionOptions

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CompressedImage:
    content: bytes
    width: int
    height: int
    source_format: ImageFormat
    source_bytes: int

    @property
    def output_bytes(self) -> int:
        return len(self.content)

    @property
    def compression_ratio(self) -> float:
        return self.output_bytes / self.source_bytes


def compress_image(data: bytes, options: CompressionOptions) -> CompressedImage:
    with image_processing_semaphore:
        decoded = decode_image(data)
        image = decoded.image
        width, height = image.size

        if decoded.source_format == ImageFormat.PNG and options.png_colors is not None:
            image = _quantize_png(image, options.png_colors, decoded.had_alpha)

        output = encode_image(
            image,
            decoded.source_format,
            quality=options.quality,
            optimize=options.optimize,
            progressive=options.progressive and decoded.source_format == ImageFormat.JPEG,
        )

    result = CompressedImage(
        content=output,
        width=width,
        height=height,
        source_format=decoded.source_format,
        source_bytes=len(data),
    )
    logger.info(
        "image_compression_completed source_format=%s width=%d height=%d "
        "source_bytes=%d output_bytes=%d ratio=%.6f",
        result.source_format.value,
        result.width,
        result.height,
        result.source_bytes,
        result.output_bytes,
        result.compression_ratio,
    )
    return result


def _quantize_png(image: Image.Image, colors: int, had_alpha: bool) -> Image.Image:
    if had_alpha:
        quantized = image.convert("RGBA").quantize(
            colors=colors,
            method=Image.Quantize.FASTOCTREE,
            dither=Image.Dither.FLOYDSTEINBERG,
        )
        return quantized.convert("RGBA")

    quantized = image.convert("RGB").quantize(
        colors=colors,
        method=Image.Quantize.MAXCOVERAGE,
        dither=Image.Dither.FLOYDSTEINBERG,
    )
    return quantized.convert("RGB")
