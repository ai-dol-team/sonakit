"""Explicit capability registry used by application composition and startup checks."""

from sonakit.capabilities.image_compression import module as image_compression
from sonakit.capabilities.image_conversion import module as image_conversion
from sonakit.capabilities.image_watermark import module as image_watermark
from sonakit.capabilities.qr_code import module as qr_code
from sonakit.capabilities.video_thumbnail import module as video_thumbnail

CAPABILITY_MODULES = (
    image_watermark,
    image_compression,
    image_conversion,
    qr_code,
    video_thumbnail,
)

__all__ = ["CAPABILITY_MODULES"]
