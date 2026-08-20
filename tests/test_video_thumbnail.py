from __future__ import annotations

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from sonakit.capabilities.video_thumbnail import module
from sonakit.capabilities.video_thumbnail import service as video_thumbnail_runtime
from sonakit.capabilities.video_thumbnail.models import VideoThumbnailRequest
from sonakit.capabilities.video_thumbnail.router import video_thumbnail_service
from sonakit.capabilities.video_thumbnail.service import (
    VideoThumbnail,
    VideoThumbnailService,
    validate_runtime,
)
from sonakit.core.config import Settings
from sonakit.core.errors import CapabilityError


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(module.router, prefix=f"/api/v1{module.prefix}")

    @app.exception_handler(CapabilityError)
    async def handle_capability_error(_request: Request, exc: CapabilityError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": exc.code, "detail": exc.detail},
        )

    with TestClient(app) as test_client:
        yield test_client


def test_thumbnail_returns_jpeg_and_frame_metadata(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def create_thumbnail(_: VideoThumbnailRequest) -> VideoThumbnail:
        return VideoThumbnail(b"jpeg-bytes", 12.345, "random_cover", 60.0)

    monkeypatch.setattr(video_thumbnail_service, "create_thumbnail", create_thumbnail)
    response = client.post(
        "/api/v1/video/thumbnail",
        json={
            "video_url": "https://media.example.com/video.mp4",
            "frame_selection_strategy": "random_cover",
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers["content-disposition"] == 'inline; filename="thumbnail.jpg"'
    assert response.headers["x-frame-time-seconds"] == "12.345"
    assert response.headers["x-frame-strategy"] == "random_cover"
    assert response.headers["x-source-duration-seconds"] == "60.000"
    assert response.content == b"jpeg-bytes"


@pytest.mark.parametrize(
    "payload",
    [
        {"video_url": "file:///tmp/video.mp4"},
        {"video_url": "https://media.example.com/video.mp4", "max_output_width": 200},
        {
            "video_url": "https://media.example.com/video.mp4",
            "random_min_ratio": 0.9,
            "random_max_ratio": 0.2,
        },
        {"video_url": "https://media.example.com/video.mp4", "unexpected": True},
    ],
)
def test_thumbnail_rejects_invalid_request(client: TestClient, payload: dict[str, object]) -> None:
    response = client.post("/api/v1/video/thumbnail", json=payload)

    assert response.status_code == 422


def test_thumbnail_reports_missing_processor(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def create_thumbnail(_: VideoThumbnailRequest) -> VideoThumbnail:
        raise CapabilityError(
            "video_processor_unavailable",
            "Required video processor 'ffprobe' is unavailable.",
            503,
        )

    monkeypatch.setattr(video_thumbnail_service, "create_thumbnail", create_thumbnail)
    response = client.post(
        "/api/v1/video/thumbnail",
        json={"video_url": "https://media.example.com/video.mp4"},
    )

    assert response.status_code == 503
    assert response.json()["code"] == "video_processor_unavailable"


def test_thumbnail_reports_remote_processing_failure(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def create_thumbnail(_: VideoThumbnailRequest) -> VideoThumbnail:
        raise CapabilityError(
            "video_thumbnail_failed", "A video frame could not be extracted.", 502
        )

    monkeypatch.setattr(video_thumbnail_service, "create_thumbnail", create_thumbnail)
    response = client.post(
        "/api/v1/video/thumbnail",
        json={"video_url": "https://media.example.com/video.mp4"},
    )

    assert response.status_code == 502
    assert response.json()["code"] == "video_thumbnail_failed"


def test_thumbnail_runtime_requires_both_processors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(video_thumbnail_runtime.shutil, "which", lambda _: None)

    with pytest.raises(RuntimeError, match="ffmpeg, ffprobe"):
        validate_runtime()


@pytest.mark.anyio
async def test_thumbnail_retries_candidate_frames_after_extraction_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = VideoThumbnailService()
    request = VideoThumbnailRequest(video_url="https://media.example.com/video.mp4")
    attempts: list[float] = []

    async def probe_duration(_: str, __: dict[str, str], ___: float) -> float:
        return 10.0

    async def extract_frame(
        _: str, second: float, __: int, ___: dict[str, str], ____: float
    ) -> bytes:
        attempts.append(second)
        if len(attempts) == 1:
            raise CapabilityError("video_thumbnail_failed", "Frame unavailable.", 502)
        return b"jpeg"

    monkeypatch.setattr(service, "_probe_duration", probe_duration)
    monkeypatch.setattr(service, "_extract_frame", extract_frame)
    result = await service.create_thumbnail(request)

    assert len(attempts) == 2
    assert result.content == b"jpeg"
    assert result.strategy == "near_start"


@pytest.mark.anyio
async def test_thumbnail_does_not_retry_after_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    service = VideoThumbnailService()
    request = VideoThumbnailRequest(video_url="https://media.example.com/video.mp4")
    attempts = 0

    async def probe_duration(_: str, __: dict[str, str], ___: float) -> float:
        return 10.0

    async def extract_frame(
        _: str, __: float, ___: int, ____: dict[str, str], _____: float
    ) -> bytes:
        nonlocal attempts
        attempts += 1
        raise CapabilityError("video_thumbnail_timed_out", "Video frame extraction timed out.", 504)

    monkeypatch.setattr(service, "_probe_duration", probe_duration)
    monkeypatch.setattr(service, "_extract_frame", extract_frame)

    with pytest.raises(CapabilityError, match="timed out") as error:
        await service.create_thumbnail(request)

    assert error.value.status_code == 504
    assert attempts == 1


@pytest.mark.anyio
async def test_thumbnail_deadline_covers_capacity_queue() -> None:
    service = VideoThumbnailService(
        Settings(video_thumbnail_concurrency=1, video_thumbnail_total_timeout_seconds=1)
    )
    await service._semaphore.acquire()
    try:
        with pytest.raises(CapabilityError, match="total processing deadline") as error:
            await service.create_thumbnail(
                VideoThumbnailRequest(video_url="https://media.example.com/video.mp4")
            )
    finally:
        service._semaphore.release()

    assert error.value.status_code == 504


@pytest.mark.anyio
async def test_thumbnail_timeout_cleanup_tolerates_exited_process() -> None:
    class ExitedProcess:
        returncode = None

        def kill(self) -> None:
            raise ProcessLookupError

        async def communicate(self) -> tuple[bytes, bytes]:
            return b"", b""

    await VideoThumbnailService._terminate_process(ExitedProcess())  # type: ignore[arg-type]


def test_random_cover_candidates_stay_within_requested_window() -> None:
    service = VideoThumbnailService()
    request = VideoThumbnailRequest(
        video_url="https://media.example.com/video.mp4",
        frame_selection_strategy="random_cover",
        random_min_ratio=0.2,
        random_max_ratio=0.8,
        random_candidate_count=3,
    )

    candidates = service._build_candidates(request, 100.0)

    assert len(candidates) >= 4
    assert all(0 <= second < 100 for second, _ in candidates)
    assert any(strategy == "random_cover" for _, strategy in candidates)
