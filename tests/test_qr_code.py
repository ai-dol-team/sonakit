from __future__ import annotations

import io

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from PIL import Image

from sonakit.capabilities.qr_code import MODULE
from sonakit.core.errors import CapabilityError


@pytest.fixture(scope="module")
def client() -> TestClient:
    app = FastAPI()
    app.include_router(MODULE.router, prefix=f"/api/v1{MODULE.prefix}")

    @app.exception_handler(CapabilityError)
    async def handle_capability_error(request: Request, exc: CapabilityError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": exc.code, "detail": exc.detail},
        )

    MODULE.validate_runtime and MODULE.validate_runtime()
    with TestClient(app) as test_client:
        yield test_client


def _blank_png() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (320, 240), "white").save(output, format="PNG")
    return output.getvalue()


def test_generate_returns_png_with_dimensions(client: TestClient) -> None:
    response = client.post(
        "/api/v1/qrcode/generate",
        json={"text": "SonaKit", "box_size": 6, "border": 4},
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.headers["content-disposition"] == 'inline; filename="qrcode.png"'
    image = Image.open(io.BytesIO(response.content))
    assert image.format == "PNG"
    assert response.headers["x-image-width"] == str(image.width)
    assert response.headers["x-image-height"] == str(image.height)


@pytest.mark.parametrize("error_correction", ["L", "M", "Q", "H"])
def test_generate_supports_each_error_correction_level(
    client: TestClient, error_correction: str
) -> None:
    response = client.post(
        "/api/v1/qrcode/generate",
        json={"text": "https://example.com", "error_correction": error_correction},
    )

    assert response.status_code == 200


def test_generate_and_recognize_unicode_round_trip(client: TestClient) -> None:
    text = "SonaKit 二维码 हिन्दी தமிழ் తెలుగు"
    generated = client.post(
        "/api/v1/qrcode/generate",
        json={"text": text, "box_size": 12, "error_correction": "M"},
    )
    assert generated.status_code == 200

    recognized = client.post(
        "/api/v1/qrcode/recognize",
        files={"file": ("qrcode.png", generated.content, "image/png")},
    )

    assert recognized.status_code == 200
    payload = recognized.json()
    assert payload["count"] == 1
    assert payload["codes"][0]["text"] == text
    assert len(payload["codes"][0]["points"]) == 4
    assert all(len(point) == 2 for point in payload["codes"][0]["points"])


@pytest.mark.parametrize(
    "payload",
    [
        {"text": ""},
        {"text": "x" * 2049},
        {"text": "ok", "error_correction": "Z"},
        {"text": "ok", "box_size": 0},
        {"text": "ok", "box_size": 21},
        {"text": "ok", "border": -1},
        {"text": "ok", "border": 21},
        {"text": "ok", "dark_color": "black"},
        {"text": "ok", "light_color": "#FFFF"},
    ],
)
def test_generate_rejects_invalid_parameters(
    client: TestClient, payload: dict[str, object]
) -> None:
    response = client.post("/api/v1/qrcode/generate", json=payload)

    assert response.status_code == 422


def test_recognize_rejects_image_without_qr_code(client: TestClient) -> None:
    response = client.post(
        "/api/v1/qrcode/recognize",
        files={"file": ("blank.png", _blank_png(), "image/png")},
    )

    assert response.status_code == 400
    assert response.json()["code"] == "qr_code_not_found"


def test_recognize_rejects_corrupt_image(client: TestClient) -> None:
    response = client.post(
        "/api/v1/qrcode/recognize",
        files={"file": ("broken.png", b"not an image", "image/png")},
    )

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_image"


def test_recognize_rejects_missing_file(client: TestClient) -> None:
    response = client.post("/api/v1/qrcode/recognize")

    assert response.status_code == 422
