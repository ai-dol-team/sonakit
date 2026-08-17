from __future__ import annotations

import io
import threading
import warnings
from dataclasses import dataclass
from enum import StrEnum

from PIL import Image, ImageCms, ImageOps, UnidentifiedImageError

from sonakit.core.config import get_settings
from sonakit.core.errors import (
    ImageTooLargeError,
    InvalidImageError,
    UnsupportedImageFormatError,
)


class ImageFormat(StrEnum):
    JPEG = "JPEG"
    PNG = "PNG"
    WEBP = "WEBP"

    @property
    def media_type(self) -> str:
        return {
            ImageFormat.JPEG: "image/jpeg",
            ImageFormat.PNG: "image/png",
            ImageFormat.WEBP: "image/webp",
        }[self]

    @property
    def extension(self) -> str:
        return {ImageFormat.JPEG: "jpg", ImageFormat.PNG: "png", ImageFormat.WEBP: "webp"}[
            self
        ]


@dataclass(slots=True)
class DecodedImage:
    image: Image.Image
    source_format: ImageFormat
    had_alpha: bool


_settings = get_settings()
image_processing_semaphore = threading.BoundedSemaphore(_settings.image_concurrency)


def ensure_upload_size(data: bytes) -> None:
    if len(data) > _settings.max_upload_bytes:
        raise ImageTooLargeError(
            "The uploaded file exceeds the "
            f"{_settings.max_upload_bytes // (1024 * 1024)} MiB limit."
        )


def decode_image(data: bytes) -> DecodedImage:
    ensure_upload_size(data)
    if not data:
        raise InvalidImageError("The uploaded file is empty.")

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as source:
                try:
                    source_format = ImageFormat(source.format)
                except (TypeError, ValueError) as exc:
                    raise UnsupportedImageFormatError() from exc

                frame_count = getattr(source, "n_frames", 1)
                if frame_count != 1:
                    raise InvalidImageError("Animated images are not supported.")

                width, height = source.size
                if width <= 0 or height <= 0:
                    raise InvalidImageError("The image dimensions are invalid.")
                if (
                    width > _settings.max_image_dimension
                    or height > _settings.max_image_dimension
                ):
                    raise ImageTooLargeError(
                        f"An image side exceeds the {_settings.max_image_dimension}px limit."
                    )
                if width * height > _settings.max_image_pixels:
                    raise ImageTooLargeError(
                        f"The decoded image exceeds the {_settings.max_image_pixels:,} pixel limit."
                    )

                source.load()
                had_alpha = source.mode in {"RGBA", "LA"} or "transparency" in source.info
                oriented = ImageOps.exif_transpose(source)
                normalized = _convert_to_srgb(oriented, preserve_alpha=had_alpha)
                normalized.load()
                clean = normalized.copy()
                clean.info.clear()
                return DecodedImage(clean, source_format, had_alpha)
    except (ImageTooLargeError, InvalidImageError, UnsupportedImageFormatError):
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ImageTooLargeError("The decoded image dimensions exceed the allowed limit.") from exc
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
        raise InvalidImageError() from exc


def _convert_to_srgb(image: Image.Image, *, preserve_alpha: bool) -> Image.Image:
    alpha = image.convert("RGBA").getchannel("A") if preserve_alpha else None
    icc_profile = image.info.get("icc_profile")
    if not icc_profile:
        return image.convert("RGBA") if preserve_alpha else image.copy()

    try:
        input_profile = ImageCms.ImageCmsProfile(io.BytesIO(icc_profile))
        output_profile = ImageCms.createProfile("sRGB")
        converted = ImageCms.profileToProfile(
            image.convert("RGB"),
            input_profile,
            output_profile,
            outputMode="RGB",
        )
        if alpha is not None:
            converted.putalpha(alpha)
        return converted
    except (ImageCms.PyCMSError, OSError, ValueError) as exc:
        raise InvalidImageError("The image contains an invalid ICC color profile.") from exc


def flatten_alpha(image: Image.Image, background_color: str) -> Image.Image:
    rgba = image.convert("RGBA")
    background = Image.new("RGBA", rgba.size, background_color)
    background.alpha_composite(rgba)
    return background.convert("RGB")


def encode_image(
    image: Image.Image,
    output_format: ImageFormat,
    *,
    quality: int = 90,
    optimize: bool = True,
    progressive: bool = False,
    background_color: str = "#FFFFFF",
) -> bytes:
    output = io.BytesIO()
    save_options: dict[str, object] = {}
    prepared = image

    if output_format == ImageFormat.JPEG:
        prepared = flatten_alpha(image, background_color)
        save_options.update(quality=quality, optimize=optimize, progressive=progressive)
    elif output_format == ImageFormat.PNG:
        prepared = image.convert("RGBA") if image.mode in {"RGBA", "LA"} else image.convert("RGB")
        save_options.update(optimize=optimize)
    elif output_format == ImageFormat.WEBP:
        prepared = image.convert("RGBA") if image.mode in {"RGBA", "LA"} else image.convert("RGB")
        save_options.update(quality=quality, method=6)

    prepared.save(output, format=output_format.value, **save_options)
    return output.getvalue()
