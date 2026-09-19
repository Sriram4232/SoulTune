"""Local music discovery facade.

Delegates to ``app.infrastructure.local_audio``. Maintained for backward compatibility.
"""

from __future__ import annotations

from .infrastructure.local_audio import (
    ALLOWED_EXTENSIONS,
    MAX_LOCAL_TRACKS,
    PROJECT_ROOT,
    invalidate_cache,
    list_local_tracks,
    music_directory,
    rescan_library,
    resolve_media,
)

__all__ = [
    "ALLOWED_EXTENSIONS",
    "MAX_LOCAL_TRACKS",
    "PROJECT_ROOT",
    "invalidate_cache",
    "list_local_tracks",
    "music_directory",
    "rescan_library",
    "resolve_media",
]
