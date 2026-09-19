"""Queue generation and conversational refinement routes."""

from __future__ import annotations

import copy
import json
from uuid import uuid4, uuid5, NAMESPACE_URL

from fastapi import APIRouter, Depends, HTTPException, Request

from ...core.models import Generate, Refine
from ...core.security import token_hash
from ...services.curation_service import curate
from ..dependencies import (
    API, authenticated, check_revision, owned_playlist, public_playlist, rate, save_playlist, utcnow,
)

router = APIRouter(tags=["queue"])


@router.get(f"{API}/queue")
def get_queue(request: Request, auth: tuple = Depends(authenticated)):
    key = str(uuid5(NAMESPACE_URL, auth[0]["id"] + ":mood-queue"))
    item = request.app.state.store.get("playlist", key)
    return {"queue": public_playlist(item) if item else None}


@router.post(f"{API}/playlists/generate", status_code=201)
@router.post(f"{API}/queue/generate", status_code=201)
async def generate(body: Generate, request: Request, auth: tuple = Depends(authenticated)):
    user, _ = auth
    playlist_id = str(uuid5(NAMESPACE_URL, user["id"] + ":mood-queue"))
    fingerprint = token_hash(json.dumps([body.description, body.playlist_size], ensure_ascii=False))
    existing = request.app.state.store.get("playlist", playlist_id)
    if existing and body.request_id and existing.get("queue_request_id") == str(body.request_id):
        if existing.get("request_fingerprint") != fingerprint:
            raise HTTPException(409, "This creation request was already used for a different playlist.")
        return public_playlist(existing)
    rate(request, "curation", 20, 60, user["id"])
    preferences = copy.deepcopy(user["preferences"])
    preferences["_selection_seed"] = str(body.request_id or uuid4())
    result = await curate(body.description, playlist_size=body.playlist_size, preferences=preferences)
    now = utcnow()
    count = len(result["tracks"])
    playlist = {
        "id": playlist_id, "owner_id": user["id"], "session_id": str(uuid4()),
        "kind": "queue", "queue_request_id": str(body.request_id or uuid4()),
        "_revision": existing.get("_revision", 0) if existing else 0,
        "request_fingerprint": fingerprint,
        "name": result["name"], "description": body.description, "profile": result["profile"],
        "tracks": result["tracks"], "messages": [
            {"role": "user", "content": body.description, "created_at": now},
            {"role": "assistant", "content": f"I curated {count} tracks for your moment. Explore why each song fits, or tell me what to change.", "created_at": now},
        ], "version": 1, "saved": False, "created_at": now, "updated_at": now,
        "source": result["source"], "parser": result["parser"], "warnings": result.get("warnings", []),
        "playlist_size": min(10, body.playlist_size), "feedback": {},
    }
    try:
        return save_playlist(request, playlist)
    except HTTPException as exc:
        existing = request.app.state.store.get("playlist", playlist_id)
        if exc.status_code == 409 and existing and body.request_id and existing.get("queue_request_id") == str(body.request_id):
            return public_playlist(existing)
        raise


@router.post(f"{API}/playlists/{{playlist_id}}/refine")
async def refine(playlist_id: str, body: Refine, request: Request, auth: tuple = Depends(authenticated)):
    # pyrefly: ignore [missing-import]
    from app.services.curation_service import curate
    user, _ = auth
    playlist = owned_playlist(request, playlist_id, user)
    if playlist.get("kind") == "collection":
        raise HTTPException(400, "Refine your mood queue, then add the songs you want to this playlist.")
    check_revision(playlist, body.revision)
    rate(request, "curation", 20, 60, user["id"])
    if len(playlist["messages"]) >= 200:
        raise HTTPException(400, "This conversation has reached its limit. Start a new playlist to continue.")
    preferences = copy.deepcopy(user["preferences"])
    preferences["_excluded_track_ids"] = [
        track_id for track_id, feedback in playlist.get("feedback", {}).items()
        if feedback in {"dislike", "remove"}
    ]
    preferences["_selection_seed"] = playlist_id + ":" + str(playlist["version"] + 1)
    if any(word in body.message.casefold() for word in ("refresh", "different songs", "new songs", "regenerate")):
        preferences["_previous_track_ids"] = [track["id"] for track in playlist["tracks"]]
    result = await curate(
        body.message, playlist_size=min(10, playlist.get("playlist_size", 10)),
        previous_profile=playlist["profile"], preferences=preferences,
    )
    playlist.update({key: result[key] for key in ("profile", "tracks", "source", "parser", "warnings")})
    for track in playlist["tracks"]:
        if track["id"] in playlist.get("feedback", {}):
            track["feedback"] = playlist["feedback"][track["id"]]
    playlist["version"] += 1
    now = utcnow()
    playlist["messages"].extend([
        {"role": "user", "content": body.message, "created_at": now},
        {"role": "assistant", "content": f"Updated your playlist to version {playlist['version']} with {len(playlist['tracks'])} tracks, keeping your previous preferences in mind.", "created_at": now},
    ])
    return save_playlist(request, playlist)


@router.get(f"{API}/sessions/{{session_id}}/history")
def history(session_id: str, request: Request, auth: tuple = Depends(authenticated)):
    items = request.app.state.store.list_owned("playlist", auth[0]["id"])
    playlist = next((item for item in items if item["session_id"] == session_id), None)
    if not playlist:
        raise HTTPException(404, "Conversation not found.")
    return {"session_id": session_id, "playlist_id": playlist["id"], "messages": playlist["messages"], "profile": playlist["profile"]}
