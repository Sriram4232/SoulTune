"""Infrastructure layer: external system clients, storage, and I/O adapters."""

from .local_audio import (
    list_local_tracks,
    resolve_media,
    rescan_library,
    music_directory,
)
from .groq_client import chat_completion, groq_available, resolve_model
from .spotify import spotify_candidates
from .lastfm import lastfm_candidates, remote_candidates
from .mail import MailUnavailable, code_hash, mail_ready, send_otp
from .storage import SQLiteStore, MongoStore, DuplicateUser, create_store

__all__ = [
    "list_local_tracks", "resolve_media", "rescan_library", "music_directory",
    "chat_completion", "groq_available", "resolve_model",
    "spotify_candidates", "lastfm_candidates", "remote_candidates",
    "MailUnavailable", "code_hash", "mail_ready", "send_otp",
    "SQLiteStore", "MongoStore", "DuplicateUser", "create_store",
]
