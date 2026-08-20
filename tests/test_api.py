from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from sonakit.app import app
from sonakit.capabilities.video_thumbnail import service as video_thumbnail_service
from sonakit.core.config import get_settings


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    real_which = video_thumbnail_service.shutil.which
    monkeypatch.setattr(
        video_thumbnail_service.shutil,
        "which",
        lambda binary: (
            f"/test/{binary}" if binary in {"ffmpeg", "ffprobe"} else real_which(binary)
        ),
    )
    with TestClient(app) as test_client:
        yield test_client


def _image_bytes(image_format: str = "PNG") -> bytes:
    output = BytesIO()
    Image.new("RGB", (640, 360), (35, 95, 125)).save(output, format=image_format)
    return output.getvalue()


def test_platform_health_and_capability_registry(client: TestClient) -> None:
    health = client.get("/api/v1/health", headers={"X-Request-ID": "integration-test"})
    capabilities = client.get("/api/v1/capabilities")

    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    assert health.headers["x-request-id"] == "integration-test"
    assert {item["name"] for item in capabilities.json()["capabilities"]} == {
        "image_watermark",
        "image_compression",
        "image_conversion",
        "qr_code",
        "video_thumbnail",
    }


def test_watermark_accepts_different_text_for_each_request(client: TestClient) -> None:
    source = _image_bytes()
    english = client.post(
        "/api/v1/image/watermark",
        files={"file": ("source.bin", source, "application/octet-stream")},
        data={"text": "Order 4W9X2", "position": "top_left"},
    )
    hindi = client.post(
        "/api/v1/image/watermark",
        files={"file": ("source.png", source, "image/png")},
        data={"text": "ऑर्डर ८७३", "position": "top_left"},
    )

    assert english.status_code == 200
    assert hindi.status_code == 200
    assert english.content != hindi.content
    for response in (english, hindi):
        assert response.headers["content-type"] == "image/png"
        assert response.headers["x-image-width"] == "640"
        assert response.headers["x-image-height"] == "360"
        assert response.headers["x-watermark-layout"] == "tiled"
        assert int(response.headers["x-watermark-count"]) > 1
        assert "x-watermark-position" not in response.headers
        assert response.headers["x-request-id"]


def test_watermark_single_layout_uses_position(client: TestClient) -> None:
    response = client.post(
        "/api/v1/image/watermark",
        files={"file": ("source.png", _image_bytes(), "image/png")},
        data={
            "text": "Single watermark",
            "layout": "single",
            "position": "top_left",
            "rotation_degrees": "0",
        },
    )

    assert response.status_code == 200
    assert response.headers["x-watermark-layout"] == "single"
    assert response.headers["x-watermark-count"] == "1"
    assert response.headers["x-watermark-position"] == "top_left"


def test_watermark_error_contract_and_actual_format_detection(client: TestClient) -> None:
    invalid_parameter = client.post(
        "/api/v1/image/watermark",
        files={"file": ("source.png", _image_bytes(), "image/png")},
        data={"text": "Dynamic text", "color": "white"},
    )
    unsupported = client.post(
        "/api/v1/image/watermark",
        files={"file": ("fake.png", _image_bytes("GIF"), "image/png")},
        data={"text": "Dynamic text"},
    )

    assert invalid_parameter.status_code == 422
    assert invalid_parameter.json()["code"] == "validation_error"
    assert invalid_parameter.json()["request_id"]
    assert unsupported.status_code == 415
    assert unsupported.json()["code"] == "unsupported_image_format"


def test_watermark_rejects_upload_over_limit(client: TestClient) -> None:
    settings = get_settings()
    response = client.post(
        "/api/v1/image/watermark",
        files={
            "file": (
                "oversized.png",
                b"x" * (settings.max_upload_bytes + 1),
                "image/png",
            )
        },
        data={"text": "Dynamic text"},
    )

    assert response.status_code == 413
    assert response.json()["code"] == "image_too_large"


def test_openapi_contains_all_public_endpoints(client: TestClient) -> None:
    swagger = client.get("/docs")
    openapi = client.get("/openapi.json")
    paths = set(openapi.json()["paths"])

    assert swagger.status_code == 200
    assert "Swagger UI" in swagger.text
    assert openapi.status_code == 200
    assert paths == {
        "/api/v1/health",
        "/api/v1/capabilities",
        "/api/v1/image/watermark",
        "/api/v1/image/compress",
        "/api/v1/image/convert",
        "/api/v1/qrcode/generate",
        "/api/v1/qrcode/recognize",
        "/api/v1/video/thumbnail",
    }

    watermark_operation = openapi.json()["paths"]["/api/v1/image/watermark"]["post"]
    request_schema = watermark_operation["requestBody"]["content"]["multipart/form-data"][
        "schema"
    ]
    component_name = request_schema["$ref"].rsplit("/", 1)[-1]
    properties = openapi.json()["components"]["schemas"][component_name]["properties"]
    assert properties["layout"]["default"] == "tiled"
    assert properties["font_size"]["default"] == 16
    assert properties["font_weight"]["default"] == 600
    assert properties["letter_spacing"]["default"] == 1.1
    assert properties["opacity"]["default"] == 0.5
    assert properties["rotation_degrees"]["default"] == -28
    assert properties["tile_width"]["default"] == 150
    assert properties["tile_height"]["default"] == 81
