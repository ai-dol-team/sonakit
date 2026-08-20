from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import random
import shutil
from contextlib import suppress
from dataclasses import dataclass
from time import perf_counter
from typing import Literal
from urllib.parse import urlsplit

from sonakit.capabilities.video_thumbnail.models import VideoThumbnailRequest
from sonakit.core.config import Settings, get_settings
from sonakit.core.errors import CapabilityError

logger = logging.getLogger(__name__)

FrameStrategy = Literal["near_start", "random_early_window", "random_cover"]


@dataclass(frozen=True, slots=True)
class VideoThumbnail:
    content: bytes
    frame_time_seconds: float
    strategy: FrameStrategy
    duration_seconds: float


class VideoThumbnailService:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._semaphore = asyncio.Semaphore(max(1, self._settings.video_thumbnail_concurrency))
        self._random = random.SystemRandom()

    async def create_thumbnail(self, request: VideoThumbnailRequest) -> VideoThumbnail:
        url_metadata = _url_metadata(request.video_url)
        deadline = (
            asyncio.get_running_loop().time() + self._settings.video_thumbnail_total_timeout_seconds
        )
        try:
            async with asyncio.timeout(self._settings.video_thumbnail_total_timeout_seconds):
                async with self._semaphore:
                    return await self._create_thumbnail_under_slot(request, url_metadata, deadline)
        except TimeoutError as exc:
            raise CapabilityError(
                "video_thumbnail_deadline_exceeded",
                "Video thumbnail request exceeded its total processing deadline.",
                504,
            ) from exc

    async def _create_thumbnail_under_slot(
        self,
        request: VideoThumbnailRequest,
        url_metadata: dict[str, str],
        deadline: float,
    ) -> VideoThumbnail:
        duration_seconds = await self._probe_duration(request.video_url, url_metadata, deadline)
        candidates = self._build_candidates(request, duration_seconds)
        last_error: CapabilityError | None = None
        for second, strategy in candidates:
            try:
                content = await self._extract_frame(
                    request.video_url,
                    second,
                    request.max_output_width,
                    url_metadata,
                    deadline,
                )
            except CapabilityError as error:
                if error.status_code in {503, 504}:
                    raise
                last_error = error
                logger.warning(
                    "event=video_thumbnail.attempt_failed host=%s url_hash=%s "
                    "frame_time_seconds=%.3f "
                    "strategy=%s code=%s",
                    url_metadata["host"],
                    url_metadata["url_hash"],
                    second,
                    strategy,
                    error.code,
                )
                continue

            logger.info(
                "event=video_thumbnail.completed host=%s url_hash=%s frame_time_seconds=%.3f "
                "strategy=%s duration_seconds=%.3f output_bytes=%d",
                url_metadata["host"],
                url_metadata["url_hash"],
                second,
                strategy,
                duration_seconds,
                len(content),
            )
            return VideoThumbnail(content, second, strategy, duration_seconds)

        if last_error is not None:
            raise last_error
        raise CapabilityError("video_thumbnail_failed", "No video frame could be extracted.", 502)

    async def _probe_duration(
        self,
        video_url: str,
        url_metadata: dict[str, str],
        deadline: float,
    ) -> float:
        started_at = perf_counter()
        process = await self._start_process(
            "ffprobe",
            "-v",
            "error",
            "-protocol_whitelist",
            "http,https,tcp,tls",
            "-select_streams",
            "v:0",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            video_url,
        )
        stdout, _ = await self._communicate(
            process,
            self._settings.video_thumbnail_ffprobe_timeout_seconds,
            deadline,
            "video_probe_timed_out",
            "Video probing timed out.",
        )
        if process.returncode != 0:
            raise CapabilityError("video_probe_failed", "The video could not be probed.", 502)

        try:
            payload = json.loads(stdout.decode("utf-8"))
            duration_seconds = float((payload.get("format") or {}).get("duration"))
        except (UnicodeDecodeError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise CapabilityError(
                "video_duration_unavailable", "Video duration is unavailable.", 502
            ) from exc

        if not math.isfinite(duration_seconds) or duration_seconds <= 0:
            raise CapabilityError("video_duration_invalid", "Video duration is invalid.", 422)
        if duration_seconds > self._settings.video_thumbnail_max_duration_seconds:
            raise CapabilityError(
                "video_duration_exceeded",
                "Video duration exceeds the allowed limit.",
                422,
            )

        logger.info(
            "event=video_thumbnail.probed host=%s url_hash=%s duration_seconds=%.3f "
            "duration_ms=%.3f",
            url_metadata["host"],
            url_metadata["url_hash"],
            duration_seconds,
            (perf_counter() - started_at) * 1000,
        )
        return duration_seconds

    async def _extract_frame(
        self,
        video_url: str,
        second: float,
        max_output_width: int,
        url_metadata: dict[str, str],
        deadline: float,
    ) -> bytes:
        width = min(max(320, max_output_width), self._settings.video_thumbnail_max_output_width)
        coarse_seek = max(0.0, second - min(1.5, second * 0.5))
        fine_seek = max(0.0, second - coarse_seek)
        process = await self._start_process(
            "ffmpeg",
            "-v",
            "error",
            "-protocol_whitelist",
            "http,https,tcp,tls",
            "-ss",
            f"{coarse_seek:.3f}",
            "-i",
            video_url,
            "-ss",
            f"{fine_seek:.3f}",
            "-frames:v",
            "1",
            "-vf",
            f"scale='min(iw,{width})':-2",
            "-q:v",
            str(self._settings.video_thumbnail_jpeg_quality),
            "-f",
            "image2pipe",
            "-vcodec",
            "mjpeg",
            "pipe:1",
        )
        stdout, stderr = await self._communicate(
            process,
            self._settings.video_thumbnail_ffmpeg_timeout_seconds,
            deadline,
            "video_thumbnail_timed_out",
            "Video frame extraction timed out.",
        )
        if process.returncode != 0 or not stdout:
            raise CapabilityError(
                "video_thumbnail_failed", "A video frame could not be extracted.", 502
            )

        logger.debug(
            "event=video_thumbnail.frame_extracted host=%s url_hash=%s frame_time_seconds=%.3f "
            "output_width=%d output_bytes=%d stderr_bytes=%d",
            url_metadata["host"],
            url_metadata["url_hash"],
            second,
            width,
            len(stdout),
            len(stderr),
        )
        return stdout

    async def _start_process(self, binary: str, *arguments: str) -> asyncio.subprocess.Process:
        try:
            return await asyncio.create_subprocess_exec(
                binary,
                *arguments,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise CapabilityError(
                "video_processor_unavailable",
                f"Required video processor '{binary}' is unavailable.",
                503,
            ) from exc

    async def _communicate(
        self,
        process: asyncio.subprocess.Process,
        attempt_timeout_seconds: int,
        deadline: float,
        attempt_timeout_code: str,
        attempt_timeout_detail: str,
    ) -> tuple[bytes, bytes]:
        remaining_seconds = deadline - asyncio.get_running_loop().time()
        if remaining_seconds <= 0:
            await self._terminate_process(process)
            raise CapabilityError(
                "video_thumbnail_deadline_exceeded",
                "Video thumbnail request exceeded its total processing deadline.",
                504,
            )

        deadline_limited = remaining_seconds <= attempt_timeout_seconds
        try:
            return await asyncio.wait_for(
                process.communicate(),
                timeout=min(attempt_timeout_seconds, remaining_seconds),
            )
        except TimeoutError as exc:
            await self._terminate_process(process)
            if deadline_limited:
                raise CapabilityError(
                    "video_thumbnail_deadline_exceeded",
                    "Video thumbnail request exceeded its total processing deadline.",
                    504,
                ) from exc
            raise CapabilityError(attempt_timeout_code, attempt_timeout_detail, 504) from exc
        except BaseException:
            await self._terminate_process(process)
            raise

    @staticmethod
    async def _terminate_process(process: asyncio.subprocess.Process) -> None:
        if process.returncode is None:
            with suppress(ProcessLookupError):
                process.kill()
        await process.communicate()

    def _build_candidates(
        self,
        request: VideoThumbnailRequest,
        duration_seconds: float,
    ) -> list[tuple[float, FrameStrategy]]:
        if request.frame_selection_strategy == "random_cover":
            return self._build_random_cover_candidates(request, duration_seconds)
        return self._build_near_start_candidates(request, duration_seconds)

    def _build_near_start_candidates(
        self,
        request: VideoThumbnailRequest,
        duration_seconds: float,
    ) -> list[tuple[float, FrameStrategy]]:
        candidates: list[tuple[float, FrameStrategy]] = []
        if request.prefer_first_frame:
            candidates.extend([(0.1, "near_start"), (0.3, "near_start"), (0.5, "near_start")])

        early_window = min(
            max(0.6, request.fallback_random_window_seconds),
            self._settings.video_thumbnail_max_random_window_seconds,
            max(0.6, duration_seconds * 0.1),
            duration_seconds,
        )
        if early_window > 0:
            second = self._random.uniform(0.1, early_window)
            candidates.append((second, "random_early_window"))
        return self._normalize_candidates(candidates, duration_seconds)

    def _build_random_cover_candidates(
        self,
        request: VideoThumbnailRequest,
        duration_seconds: float,
    ) -> list[tuple[float, FrameStrategy]]:
        min_second = duration_seconds * request.random_min_ratio
        max_second = duration_seconds * request.random_max_ratio
        if max_second - min_second < 0.2:
            return [(self._safe_second(duration_seconds * 0.5, duration_seconds), "random_cover")]

        segment_size = (max_second - min_second) / request.random_candidate_count
        candidates: list[tuple[float, FrameStrategy]] = []
        for index in range(request.random_candidate_count):
            start = min_second + (segment_size * index)
            end = (
                max_second
                if index == request.random_candidate_count - 1
                else start + segment_size
            )
            candidates.append((self._random.uniform(start, end), "random_cover"))

        candidates.append(((min_second + max_second) * 0.5, "random_cover"))
        candidates.append((min(0.5, duration_seconds * 0.25), "near_start"))
        return self._normalize_candidates(candidates, duration_seconds)

    def _normalize_candidates(
        self,
        candidates: list[tuple[float, FrameStrategy]],
        duration_seconds: float,
    ) -> list[tuple[float, FrameStrategy]]:
        normalized: list[tuple[float, FrameStrategy]] = []
        seen: set[float] = set()
        for second, strategy in candidates:
            safe_second = self._safe_second(second, duration_seconds)
            if safe_second not in seen:
                seen.add(safe_second)
                normalized.append((safe_second, strategy))
        return normalized or [(self._safe_second(0.1, duration_seconds), "near_start")]

    @staticmethod
    def _safe_second(second: float, duration_seconds: float) -> float:
        return round(min(max(0.0, second), max(0.0, duration_seconds - 0.05)), 3)


def _url_metadata(video_url: str) -> dict[str, str]:
    parsed = urlsplit(video_url)
    return {
        "host": parsed.hostname or "unknown",
        "url_hash": hashlib.sha256(video_url.encode("utf-8")).hexdigest()[:12],
    }


def validate_runtime() -> None:
    missing = [binary for binary in ("ffmpeg", "ffprobe") if shutil.which(binary) is None]
    if missing:
        raise RuntimeError(f"Video thumbnail capability requires: {', '.join(missing)}")
