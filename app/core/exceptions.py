"""
Core exceptions (L0).
Moved up from app.services.exceptions so that L0 core modules can raise them
without reverse-importing the services layer.
L2 services should also raise these (canonical) - app.services.exceptions
re-exports them for backward compat with any code that still imports there.
"""
from __future__ import annotations


class ServiceError(Exception):
    """Base for all service errors."""


class NotFoundError(ServiceError):
    """Resource not found in DB or file store."""

    def __init__(self, resource: str, key: str | int | None = None) -> None:
        msg = f"{resource} not found"
        if key is not None:
            msg += f": {key}"
        super().__init__(msg)
        self.resource = resource
        self.key = key


class ValidationError(ServiceError):
    """Caller-supplied data is invalid (e.g. wrong status enum)."""
