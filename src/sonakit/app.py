from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from sonakit.api.router import api_router
from sonakit.capabilities import CAPABILITY_MODULES
from sonakit.core.config import get_settings
from sonakit.core.errors import CapabilityError
from sonakit.core.logging import configure_logging

settings = get_settings()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    for capability in CAPABILITY_MODULES:
        if capability.validate_runtime is not None:
            capability.validate_runtime()
        logger.info("event=capability.ready capability=%s", capability.name)
    yield


configure_logging()
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "API-first reusable media capabilities. Each capability exposes an independent HTTP "
        "contract while sharing security and observability infrastructure."
    ),
    openapi_tags=[
        {"name": "Platform", "description": "Health and capability discovery."},
        {
            "name": "Image Watermark",
            "description": "Render request-specific multilingual text onto an image.",
        },
        {
            "name": "Image Compression",
            "description": "Reduce encoded image size while preserving format and dimensions.",
        },
        {
            "name": "Image Conversion",
            "description": "Convert JPEG, PNG, and WebP images between supported formats.",
        },
        {
            "name": "QR Code",
            "description": "Generate PNG QR codes and recognize QR codes in images.",
        },
        {
            "name": "Video Thumbnail",
            "description": "Extract a JPEG cover frame from a remote HTTP(S) video.",
        },
    ],
    swagger_ui_parameters={"displayRequestDuration": True, "tryItOutEnabled": True},
    lifespan=lifespan,
)

if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[
            "Content-Disposition",
            "X-Image-Width",
            "X-Image-Height",
            "X-Watermark-Font-Size",
            "X-Watermark-Layout",
            "X-Watermark-Count",
            "X-Watermark-Position",
            "X-Source-Bytes",
            "X-Output-Bytes",
            "X-Compression-Ratio",
            "X-Frame-Time-Seconds",
            "X-Frame-Strategy",
            "X-Source-Duration-Seconds",
        ],
    )


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or uuid4().hex
    request.state.request_id = request_id[:128]
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    return response


@app.exception_handler(CapabilityError)
async def capability_error_handler(request: Request, exc: CapabilityError) -> JSONResponse:
    logger.warning(
        "event=capability.failed code=%s status=%d path=%s request_id=%s",
        exc.code,
        exc.status_code,
        request.url.path,
        request.state.request_id,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": exc.code, "detail": exc.detail, "request_id": request.state.request_id},
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "code": "validation_error",
            "detail": jsonable_encoder(exc.errors()),
            "request_id": request.state.request_id,
        },
    )


@app.exception_handler(HTTPException)
async def http_error_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "code": "http_error",
            "detail": exc.detail,
            "request_id": request.state.request_id,
        },
        headers=exc.headers,
    )


@app.exception_handler(Exception)
async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception(
        "event=request.failed code=internal_error path=%s request_id=%s",
        request.url.path,
        request.state.request_id,
        exc_info=exc,
    )
    return JSONResponse(
        status_code=500,
        content={
            "code": "internal_error",
            "detail": "An unexpected internal error occurred.",
            "request_id": request.state.request_id,
        },
    )


@app.get("/", include_in_schema=False)
def root() -> dict[str, str]:
    return {"service": settings.app_name, "version": settings.app_version, "docs": "/docs"}


app.include_router(api_router)
