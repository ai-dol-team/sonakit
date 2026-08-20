from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import Response

from sonakit.capabilities.video_thumbnail.models import VideoThumbnailRequest
from sonakit.capabilities.video_thumbnail.service import VideoThumbnailService, validate_runtime
from sonakit.core.capabilities import CapabilityModule
from sonakit.core.openapi import ErrorResponse

router = APIRouter()
video_thumbnail_service = VideoThumbnailService()

_THUMBNAIL_HEADERS = {
    "X-Frame-Time-Seconds": {
        "description": "Timestamp of the extracted frame in seconds.",
        "schema": {"type": "number"},
    },
    "X-Frame-Strategy": {
        "description": "Selection strategy used for the returned frame.",
        "schema": {"type": "string"},
    },
    "X-Source-Duration-Seconds": {
        "description": "Source video duration in seconds.",
        "schema": {"type": "number"},
    },
}


@router.post(
    "/thumbnail",
    response_class=Response,
    summary="Extract a video cover frame",
    description="Extract one JPEG frame from a server-accessible HTTP(S) video URL.",
    responses={
        200: {
            "description": "JPEG thumbnail image.",
            "content": {"image/jpeg": {"schema": {"type": "string", "format": "binary"}}},
            "headers": _THUMBNAIL_HEADERS,
        },
        422: {
            "model": ErrorResponse,
            "description": "Video URL or extraction parameters are invalid.",
        },
        502: {"model": ErrorResponse, "description": "The remote video could not be processed."},
        503: {"model": ErrorResponse, "description": "ffmpeg or ffprobe is unavailable."},
        504: {"model": ErrorResponse, "description": "Video probing or extraction timed out."},
    },
)
async def create_thumbnail(request: VideoThumbnailRequest) -> Response:
    result = await video_thumbnail_service.create_thumbnail(request)
    return Response(
        content=result.content,
        media_type="image/jpeg",
        headers={
            "Content-Disposition": 'inline; filename="thumbnail.jpg"',
            "X-Frame-Time-Seconds": f"{result.frame_time_seconds:.3f}",
            "X-Frame-Strategy": result.strategy,
            "X-Source-Duration-Seconds": f"{result.duration_seconds:.3f}",
        },
    )


module = CapabilityModule(
    name="video_thumbnail",
    description="Extract JPEG cover frames from remote HTTP(S) videos.",
    prefix="/video",
    router=router,
    tags=("Video Thumbnail",),
    validate_runtime=validate_runtime,
)
