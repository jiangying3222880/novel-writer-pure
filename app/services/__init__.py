"""
Service layer for the PySide6 app (v3.4 layered architecture).

Re-exports the service modules and the common exception types so callers
can write `from app.services import project_service, ServiceError` instead
of having to know the internal submodule layout.
"""
from __future__ import annotations

from app.services import (
    anti_ai,
    book_service,
    character_tracker,
    chapter_service,
    conversation_service,
    memory,
    memory_manager,
    pressure,
    project_service,
    setting_service,
)
from app.services.exceptions import (
    NotFoundError,
    ServiceError,
    ValidationError,
)

__all__ = [
    # Service modules
    "anti_ai",
    "book_service",
    "character_tracker",
    "chapter_service",
    "conversation_service",
    "memory",
    "memory_manager",
    "pressure",
    "project_service",
    "setting_service",
    # Exception types
    "NotFoundError",
    "ServiceError",
    "ValidationError",
]
