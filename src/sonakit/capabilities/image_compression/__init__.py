from sonakit.core.capabilities import CapabilityModule

from .router import router

MODULE = CapabilityModule(
    name="image_compression",
    description="Compress JPEG, PNG, and WebP images while preserving their format and dimensions.",
    prefix="/image",
    router=router,
    tags=("Image Compression",),
)
capability = MODULE
module = MODULE

__all__ = ["MODULE", "capability", "module", "router"]
