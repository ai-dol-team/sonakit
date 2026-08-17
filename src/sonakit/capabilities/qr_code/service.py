from __future__ import annotations

import io
from dataclasses import dataclass

import cv2
import numpy as np
import qrcode
from PIL import Image
from qrcode.constants import (
    ERROR_CORRECT_H,
    ERROR_CORRECT_L,
    ERROR_CORRECT_M,
    ERROR_CORRECT_Q,
)

from sonakit.capabilities.qr_code.models import (
    ErrorCorrection,
    GenerateQrCodeRequest,
    QrCodeResult,
)
from sonakit.core.errors import CapabilityError
from sonakit.media.images import decode_image, image_processing_semaphore

_ERROR_CORRECTION = {
    ErrorCorrection.LOW: ERROR_CORRECT_L,
    ErrorCorrection.MEDIUM: ERROR_CORRECT_M,
    ErrorCorrection.QUARTILE: ERROR_CORRECT_Q,
    ErrorCorrection.HIGH: ERROR_CORRECT_H,
}


@dataclass(frozen=True, slots=True)
class GeneratedQrCode:
    content: bytes
    width: int
    height: int


def generate_qr_code(request: GenerateQrCodeRequest) -> GeneratedQrCode:
    qr = qrcode.QRCode(
        version=None,
        error_correction=_ERROR_CORRECTION[request.error_correction],
        box_size=request.box_size,
        border=request.border,
    )
    qr.add_data(request.text)

    try:
        qr.make(fit=True)
    except qrcode.exceptions.DataOverflowError as exc:
        raise CapabilityError(
            "qr_code_data_too_large",
            "The text is too large for the selected QR error-correction level.",
            400,
        ) from exc

    image = qr.make_image(
        fill_color=request.dark_color,
        back_color=request.light_color,
    ).convert("RGB")
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    return GeneratedQrCode(output.getvalue(), image.width, image.height)


def recognize_qr_codes(data: bytes) -> list[QrCodeResult]:
    with image_processing_semaphore:
        decoded = decode_image(data)
        bgr = _to_bgr(decoded.image)
        detector = cv2.QRCodeDetector()

        results = _decode_multiple(detector, bgr)
        if not results:
            results = _decode_single(detector, bgr)

    if not results:
        raise CapabilityError(
            "qr_code_not_found",
            "No readable QR code was found in the image.",
            400,
        )
    return results


def _to_bgr(image: Image.Image) -> np.ndarray:
    rgb = np.asarray(image.convert("RGB"))
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


def _decode_multiple(detector: cv2.QRCodeDetector, image: np.ndarray) -> list[QrCodeResult]:
    try:
        detected, decoded_texts, points, _ = detector.detectAndDecodeMulti(image)
    except cv2.error:
        return []

    if not detected or points is None:
        return []

    return [
        QrCodeResult(text=text, points=_normalize_points(code_points))
        for text, code_points in zip(decoded_texts, points, strict=False)
        if text
    ]


def _decode_single(detector: cv2.QRCodeDetector, image: np.ndarray) -> list[QrCodeResult]:
    try:
        text, points, _ = detector.detectAndDecode(image)
    except cv2.error:
        return []

    if not text or points is None:
        return []
    return [QrCodeResult(text=text, points=_normalize_points(points))]


def _normalize_points(points: np.ndarray) -> list[list[float]]:
    array = np.asarray(points, dtype=float).reshape(-1, 2)
    return [[round(float(x), 3), round(float(y), 3)] for x, y in array]
