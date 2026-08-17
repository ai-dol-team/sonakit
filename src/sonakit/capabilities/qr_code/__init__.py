from sonakit.capabilities.qr_code.router import router
from sonakit.core.capabilities import CapabilityModule


def validate_runtime() -> None:
    # Avoid OpenCV creating its own worker pool inside the API worker.
    import cv2

    cv2.setNumThreads(1)


MODULE = CapabilityModule(
    name="qr_code",
    description="Generate QR code images and recognize QR codes from uploaded images.",
    prefix="/qrcode",
    router=router,
    tags=("QR Code",),
    validate_runtime=validate_runtime,
)

module = MODULE

__all__ = ["MODULE", "module"]
