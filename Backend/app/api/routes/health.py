"""System health check and service status endpoint."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from ... import mail
from ...infrastructure.local_audio import list_local_tracks
from ..dependencies import API

router = APIRouter(tags=["health"])


@router.get(f"{API}/health")
def health(request: Request):
    config = request.app.state.settings
    storage = request.app.state.store
    if not storage.ping():
        raise HTTPException(503, "Storage is unavailable.")
    has_spotify = bool(config.spotify_client_id and config.spotify_client_secret)
    return {
        "status": "ok",
        "storage": storage.kind,
        "ai_configured": bool(config.groq_api_key),
        "mail_configured": mail.mail_ready(config),
        "spotify_configured": has_spotify,
        "music_api_configured": has_spotify or bool(config.lastfm_api_key),
        "local_track_count": len(list_local_tracks()),
    }
