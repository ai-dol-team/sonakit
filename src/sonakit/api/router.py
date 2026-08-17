from fastapi import APIRouter

from sonakit.capabilities import CAPABILITY_MODULES

api_router = APIRouter(prefix="/api/v1")

for capability in CAPABILITY_MODULES:
    api_router.include_router(
        capability.router,
        prefix=capability.prefix,
        tags=list(capability.tags),
    )


@api_router.get("/health", tags=["Platform"], summary="Service health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@api_router.get("/capabilities", tags=["Platform"], summary="List capabilities")
def capabilities() -> dict[str, list[dict[str, str]]]:
    return {
        "capabilities": [
            {"name": item.name, "description": item.description} for item in CAPABILITY_MODULES
        ]
    }
