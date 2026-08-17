"""Explicit capability registry used by application composition and startup checks."""

from sonakit.capabilities.image_compression import module as image_compression
from sonakit.capabilities.image_conversion import module as image_conversion
from sonakit.capabilities.image_watermark import module as image_watermark
from sonakit.capabilities.qr_code import module as qr_code

CAPABILITY_MODULES = (
    image_watermark,
    image_compression,
    image_conversion,
    qr_code,
)

__all__ = ["CAPABILITY_MODULES"]
