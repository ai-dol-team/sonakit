from collections.abc import Callable
from dataclasses import dataclass

from fastapi import APIRouter


@dataclass(frozen=True, slots=True)
class CapabilityModule:
    name: str
    description: str
    prefix: str
    router: APIRouter
    tags: tuple[str, ...]
    validate_runtime: Callable[[], None] | None = None

