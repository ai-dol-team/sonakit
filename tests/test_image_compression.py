from __future__ import annotations

import io

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from PIL import Image

from sonakit.capabilities.image_compression import MODULE
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


def _image_bytes(
    image_format: str,
    *,
    mode: str = "RGB",
    color: tuple[int, ...] = (24, 96, 180),
) -> bytes:
    output = io.BytesIO()
    Image.new(mode, (96, 64), color).save(output, format=image_format, quality=96)
    return output.getvalue()


def _indexed_transparent_png() -> bytes:
    image = Image.new("P", (32, 24), 0)
    image.putpalette([255, 0, 0, 0, 255, 0] + [0, 0, 0] * 254)
    image.info["transparency"] = 0
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


@pytest.mark.parametrize(
    ("image_format", "media_type"),
    [("JPEG", "image/jpeg"), ("PNG", "image/png"), ("WEBP", "image/webp")],
)
def test_compress_preserves_format_and_dimensions(
    client: TestClient, image_format: str, media_type: str
) -> None:
    source = _image_bytes(image_format)

    response = client.post(
        "/api/v1/image/compress",
        files={"file": (f"source.{image_format.lower()}", source, media_type)},
        data={"quality": "70"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == media_type
    assert response.headers["x-source-format"] == image_format
    assert response.headers["x-output-format"] == image_format
    assert response.headers["x-image-width"] == "96"
    assert response.headers["x-image-height"] == "64"
    assert response.headers["x-source-bytes"] == str(len(source))
    assert response.headers["x-output-bytes"] == str(len(response.content))
    assert float(response.headers["x-compression-ratio"]) > 0
    output = Image.open(io.BytesIO(response.content))
    assert output.format == image_format
    assert output.size == (96, 64)


@pytest.mark.parametrize("png_colors", [None, 16])
def test_compress_png_preserves_transparency(
    client: TestClient, png_colors: int | None
) -> None:
    source = _image_bytes("PNG", mode="RGBA", color=(10, 20, 30, 0))
    data = {} if png_colors is None else {"png_colors": str(png_colors)}

    response = client.post(
        "/api/v1/image/compress",
        files={"file": ("transparent.png", source, "image/png")},
        data=data,
    )

    assert response.status_code == 200
    output = Image.open(io.BytesIO(response.content)).convert("RGBA")
    assert output.getpixel((0, 0))[3] == 0


def test_compress_preserves_indexed_png_transparency(client: TestClient) -> None:
    response = client.post(
        "/api/v1/image/compress",
        files={"file": ("indexed.png", _indexed_transparent_png(), "image/png")},
    )

    assert response.status_code == 200
    output = Image.open(io.BytesIO(response.content)).convert("RGBA")
    assert output.getpixel((0, 0))[3] == 0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("quality", "0"),
        ("quality", "101"),
        ("png_colors", "1"),
        ("png_colors", "257"),
        ("optimize", "invalid"),
    ],
)
def test_compress_rejects_invalid_parameters(
    client: TestClient, field: str, value: str
) -> None:
    response = client.post(
        "/api/v1/image/compress",
        files={"file": ("source.png", _image_bytes("PNG"), "image/png")},
        data={field: value},
    )

    assert response.status_code == 422


def test_compress_rejects_corrupt_image(client: TestClient) -> None:
    response = client.post(
        "/api/v1/image/compress",
        files={"file": ("broken.jpg", b"not an image", "image/jpeg")},
    )

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_image"
