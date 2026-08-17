from __future__ import annotations

import io

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from PIL import Image

from sonakit.capabilities.image_conversion import MODULE
from sonakit.core.errors import CapabilityError


@pytest.fixture(scope="module")
def client() -> TestClient:
    app = FastAPI()
    app.include_router(MODULE.router, prefix=f"/api/v1{MODULE.prefix}")

    @app.exception_handler(CapabilityError)
    async def handle_capability_error(
        _request: Request, exc: CapabilityError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": exc.code, "detail": exc.detail},
        )

    with TestClient(app) as test_client:
        yield test_client


def _png(*, alpha: int = 255) -> bytes:
    output = io.BytesIO()
    Image.new("RGBA", (80, 60), (15, 90, 170, alpha)).save(output, format="PNG")
    return output.getvalue()


@pytest.mark.parametrize(
    ("target_format", "pillow_format", "media_type"),
    [
        ("jpeg", "JPEG", "image/jpeg"),
        ("png", "PNG", "image/png"),
        ("webp", "WEBP", "image/webp"),
    ],
)
def test_convert_outputs_requested_format(
    client: TestClient,
    target_format: str,
    pillow_format: str,
    media_type: str,
) -> None:
    source = _png()

    response = client.post(
        "/api/v1/image/convert",
        files={"file": ("source.png", source, "image/png")},
        data={"target_format": target_format, "quality": "85"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == media_type
    assert response.headers["x-source-format"] == "PNG"
    assert response.headers["x-output-format"] == pillow_format
    assert response.headers["x-image-width"] == "80"
    assert response.headers["x-image-height"] == "60"
    assert response.headers["x-source-bytes"] == str(len(source))
    assert response.headers["x-output-bytes"] == str(len(response.content))
    assert float(response.headers["x-size-ratio"]) > 0
    output = Image.open(io.BytesIO(response.content))
    assert output.format == pillow_format
    assert output.size == (80, 60)


def test_convert_to_jpeg_flattens_alpha_on_selected_background(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/v1/image/convert",
        files={"file": ("transparent.png", _png(alpha=0), "image/png")},
        data={"target_format": "jpeg", "background_color": "#00FF00", "quality": "100"},
    )

    assert response.status_code == 200
    red, green, blue = Image.open(io.BytesIO(response.content)).convert("RGB").getpixel((40, 30))
    assert red < 10
    assert green > 245
    assert blue < 10


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("target_format", "gif"),
        ("quality", "0"),
        ("quality", "101"),
        ("background_color", "white"),
        ("background_color", "#FFF"),
    ],
)
def test_convert_rejects_invalid_parameters(
    client: TestClient, field: str, value: str
) -> None:
    data = {"target_format": "png", field: value}
    response = client.post(
        "/api/v1/image/convert",
        files={"file": ("source.png", _png(), "image/png")},
        data=data,
    )

    assert response.status_code == 422


def test_convert_requires_target_format(client: TestClient) -> None:
    response = client.post(
        "/api/v1/image/convert",
        files={"file": ("source.png", _png(), "image/png")},
    )

    assert response.status_code == 422


def test_convert_rejects_corrupt_image(client: TestClient) -> None:
    response = client.post(
        "/api/v1/image/convert",
        files={"file": ("broken.png", b"not an image", "image/png")},
        data={"target_format": "webp"},
    )

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_image"
