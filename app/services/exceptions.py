"""
Service-layer exceptions (L2 re-exports).

Canonical home is `app.core.exceptions` (L0) — these exceptions are part of the
core error language that L2/L3/L4 all speak. This module re-exports them so
existing code that does `from app.services.exceptions import NotFoundError`
keeps working.
"""
from __future__ import annotations

from app.core.exceptions import NotFoundError, ServiceError, ValidationError

__all__ = ["NotFoundError", "ServiceError", "ValidationError"]
