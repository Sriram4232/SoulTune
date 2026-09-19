"""Configuration facade delegating to ``app.config.settings``.

Maintained for backward compatibility.
"""

from __future__ import annotations

from .config.settings import (
    BACKEND_ROOT,
    PROJECT_ROOT,
    Settings,
    settings,
)

__all__ = [
    "BACKEND_ROOT",
    "PROJECT_ROOT",
    "Settings",
    "settings",
]
