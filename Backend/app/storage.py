"""Storage facade delegating to ``app.infrastructure.storage``.

Maintained for backward compatibility.
"""

from __future__ import annotations

from .infrastructure.storage import (
    DuplicateUser,
    MongoStore,
    SQLiteStore,
    create_store,
    merge_profile,
)

# Compatibility alias
_merge_profile = merge_profile

__all__ = [
    "DuplicateUser",
    "MongoStore",
    "SQLiteStore",
    "_merge_profile",
    "create_store",
    "merge_profile",
]
