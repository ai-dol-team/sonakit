from dataclasses import dataclass


@dataclass(slots=True)
class CapabilityError(Exception):
    code: str
    detail: str
    status_code: int = 400

    def __str__(self) -> str:
        return self.detail


class InvalidImageError(CapabilityError):
    def __init__(self, detail: str = "The uploaded image is invalid or corrupted.") -> None:
        super().__init__("invalid_image", detail, 400)


class ImageTooLargeError(CapabilityError):
    def __init__(self, detail: str) -> None:
        super().__init__("image_too_large", detail, 413)


class UnsupportedImageFormatError(CapabilityError):
    def __init__(self, detail: str = "Only JPEG, PNG, and WebP images are supported.") -> None:
        super().__init__("unsupported_image_format", detail, 415)

