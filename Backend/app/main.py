"""HTTP application entrypoint.

This module delegates application creation to the modular API layer in ``app.api``,
providing full backward compatibility for existing scripts, runners, and tests.
"""

from __future__ import annotations

from .api.app import create_app
from .api.dependencies import (
    API,
    AUTH_ERROR,
    public_playlist,
    public_user,
    utcnow,
)
from .api.middleware import BodyLimitMiddleware
from .config import Settings, settings as default_settings

# Primary application instance for uvicorn (e.g., uvicorn app.main:app)
app = create_app()

__all__ = [
    "API",
    "AUTH_ERROR",
    "BodyLimitMiddleware",
    "Settings",
    "app",
    "create_app",
    "default_settings",
    "public_playlist",
    "public_user",
    "utcnow",
]
