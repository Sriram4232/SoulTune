"""Storage package: SQLite and MongoDB repositories."""
from __future__ import annotations

from ...config.settings import Settings
from .base import DuplicateUser, merge_profile
from .sqlite_store import SQLiteStore
from .mongo_store import MongoStore


def create_store(settings: Settings) -> SQLiteStore | MongoStore:
    if settings.mongodb_uri:
        return MongoStore(settings.mongodb_uri, settings.mongodb_database)
    return SQLiteStore(settings.database_path)


__all__ = ["DuplicateUser", "merge_profile", "SQLiteStore", "MongoStore", "create_store"]
