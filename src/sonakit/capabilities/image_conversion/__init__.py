from sonakit.core.capabilities import CapabilityModule

from .router import router

MODULE = CapabilityModule(
    name="image_conversion",
    description="Convert JPEG, PNG, and WebP images to a selected output format.",
    prefix="/image",
    router=router,
    tags=("Image Conversion",),
)
capability = MODULE
module = MODULE

__all__ = ["MODULE", "capability", "module", "router"]
