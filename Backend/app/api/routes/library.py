"""Local library listing, rescanning, and audio streaming routes."""

from __future__ import annotations

import mimetypes

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse

from ...infrastructure import local_audio
from ...infrastructure.local_audio import list_local_tracks, resolve_media
from ..dependencies import API, authenticated, rate

router = APIRouter(tags=["library"])


@router.get(f"{API}/library")
def library(auth: tuple = Depends(authenticated)):
    return {"tracks": list_local_tracks()}


@router.post(f"{API}/library/rescan")
def rescan(request: Request, auth: tuple = Depends(authenticated)):
    rate(request, "rescan", 10, 60, auth[0]["id"])
    if hasattr(local_audio, "rescan_library"):
        return {"tracks": local_audio.rescan_library()}
    return {"tracks": local_audio.list_local_tracks()}


@router.get(f"{API}/media/{{track_id}}")
def local_media(track_id: str, auth: tuple = Depends(authenticated)):
    if len(track_id) > 200:
        raise HTTPException(404, "Audio file not found.")
    path = resolve_media(track_id)
    if path is None or not path.is_file():
        raise HTTPException(404, "Audio file not found. Rescan your local library.")
    media_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
    return FileResponse(path, media_type=media_type, filename=path.name, content_disposition_type="inline")
