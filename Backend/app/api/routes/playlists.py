"""Playlist CRUD, track management, feedback, and export routes."""

from __future__ import annotations

import copy
import csv
import io
import json
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from ...core.models import AddTrack, CreatePlaylist, Feedback, PlaylistUpdate
from ...core.security import token_hash
from ..dependencies import (
    API, authenticated, check_revision, owned_playlist, public_playlist, save_playlist, utcnow,
)

router = APIRouter(tags=["playlists"])


def _find_track(request: Request, body: AddTrack, user: dict):
    if body.source_id:
        source = owned_playlist(request, body.source_id, user)
        track = next((track for track in source["tracks"] if track["id"] == body.track_id), None)
    else:
        saved = request.app.state.store.get("saved_song", token_hash(user["id"] + ":" + body.track_id))
        track = saved.get("track") if saved else None
        if not track:
            from ...infrastructure.local_audio import list_local_tracks
            track = next((track for track in list_local_tracks() if track["id"] == body.track_id), None)
    if not track:
        raise HTTPException(404, "Song is no longer available in this source. Refresh and try again.")
    return copy.deepcopy(track)


@router.get(f"{API}/playlists")
def list_playlists(request: Request, auth: tuple = Depends(authenticated)):
    user, _ = auth
    items = request.app.state.store.list_owned("playlist", user["id"])
    return {
        "playlists": [
            public_playlist(item)
            for item in sorted(items, key=lambda item: item["updated_at"], reverse=True)
            if item.get("kind") != "queue"
        ]
    }


@router.post(f"{API}/playlists", status_code=201)
def create_playlist(body: CreatePlaylist, request: Request, auth: tuple = Depends(authenticated)):
    now = utcnow()
    playlist = {
        "id": str(uuid4()), "owner_id": auth[0]["id"], "session_id": str(uuid4()),
        "kind": "collection", "name": body.name, "description": body.description.strip(),
        "profile": None, "tracks": [], "messages": [], "version": 1, "saved": True,
        "created_at": now, "updated_at": now, "source": "collection", "parser": "manual",
        "warnings": [], "feedback": {},
    }
    return save_playlist(request, playlist)


@router.get(f"{API}/playlists/{{playlist_id}}")
def get_playlist(playlist_id: str, request: Request, auth: tuple = Depends(authenticated)):
    return public_playlist(owned_playlist(request, playlist_id, auth[0]))


@router.patch(f"{API}/playlists/{{playlist_id}}")
def update_playlist(playlist_id: str, body: PlaylistUpdate, request: Request, auth: tuple = Depends(authenticated)):
    playlist = owned_playlist(request, playlist_id, auth[0])
    if playlist.get("kind") == "queue" and body.saved:
        raise HTTPException(400, "Create a named playlist and add the songs you want to keep.")
    check_revision(playlist, body.revision)
    playlist.update(body.model_dump(exclude_none=True, exclude={"revision"}))
    return save_playlist(request, playlist)


@router.delete(f"{API}/playlists/{{playlist_id}}")
def delete_playlist(playlist_id: str, request: Request, auth: tuple = Depends(authenticated)):
    playlist = owned_playlist(request, playlist_id, auth[0])
    if playlist.get("kind") == "queue":
        playlist.update(tracks=[], messages=[], feedback={}, warnings=[], description="", name="Your mood queue")
        save_playlist(request, playlist)
        return {"message": "Queue cleared."}
    request.app.state.store.put("deleted_playlist", playlist_id, {"id": playlist_id}, owner=auth[0]["id"])
    request.app.state.store.delete("playlist", playlist_id)
    return {"message": "Playlist deleted."}


@router.post(f"{API}/playlists/{{playlist_id}}/tracks")
def add_track(playlist_id: str, body: AddTrack, request: Request, auth: tuple = Depends(authenticated)):
    playlist = owned_playlist(request, playlist_id, auth[0])
    if playlist.get("kind") == "queue":
        raise HTTPException(400, "Choose one of your playlists to store this song.")
    check_revision(playlist, body.revision)
    if any(track["id"] == body.track_id for track in playlist["tracks"]):
        return public_playlist(playlist)
    if len(playlist["tracks"]) >= 500:
        raise HTTPException(400, "This playlist has reached its 500-song limit.")
    track = _find_track(request, body, auth[0])
    track.pop("feedback", None)
    playlist["tracks"].append(track)
    playlist.setdefault("feedback", {}).pop(body.track_id, None)
    return save_playlist(request, playlist)


@router.post(f"{API}/playlists/{{playlist_id}}/feedback")
def feedback(playlist_id: str, body: Feedback, request: Request, auth: tuple = Depends(authenticated)):
    playlist = owned_playlist(request, playlist_id, auth[0])
    check_revision(playlist, body.revision)
    track = next((track for track in playlist["tracks"] if track["id"] == body.track_id), None)
    if not track:
        raise HTTPException(404, "Track not found in this playlist.")
    playlist.setdefault("feedback", {})[body.track_id] = body.feedback
    if body.feedback in {"remove", "dislike"}:
        playlist["tracks"] = [track for track in playlist["tracks"] if track["id"] != body.track_id]
    else:
        track["feedback"] = body.feedback
    return save_playlist(request, playlist)


@router.get(f"{API}/saved-songs")
def saved_songs(request: Request, auth: tuple = Depends(authenticated)):
    return {"tracks": [item["track"] for item in request.app.state.store.list_owned("saved_song", auth[0]["id"])]}


@router.post(f"{API}/saved-songs", status_code=201)
def save_song(body: AddTrack, request: Request, auth: tuple = Depends(authenticated)):
    track = _find_track(request, body, auth[0])
    track.pop("feedback", None)
    key = token_hash(auth[0]["id"] + ":" + body.track_id)
    request.app.state.store.put("saved_song", key, {"track": track}, owner=auth[0]["id"])
    return {"track": track}


@router.delete(f"{API}/saved-songs/{{track_id}}")
def unsave_song(track_id: str, request: Request, auth: tuple = Depends(authenticated)):
    request.app.state.store.delete("saved_song", token_hash(auth[0]["id"] + ":" + track_id))
    return {"message": "Song removed from saved songs."}


@router.get(f"{API}/playlists/{{playlist_id}}/export")
def export_playlist(playlist_id: str, request: Request, format: Literal["json", "csv"] = "json", auth: tuple = Depends(authenticated)):
    playlist = public_playlist(owned_playlist(request, playlist_id, auth[0]))
    headers = {"Content-Disposition": f'attachment; filename="playlist-{playlist_id}.{format}"'}
    if format == "json":
        return Response(json.dumps(playlist, ensure_ascii=False, indent=2), media_type="application/json", headers=headers)
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["Position", "Title", "Artist", "Album", "Genres", "Match score", "Why this song", "Source", "URL"])

    def safe_cell(value) -> str:
        value = str(value or "")
        if value.lstrip().startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r", "\n")):
            return "'" + value
        return value

    for position, track in enumerate(playlist["tracks"], 1):
        writer.writerow([safe_cell(value) for value in (
            position, track.get("title"), track.get("artist"), track.get("album"),
            ", ".join(track.get("genres", [])), track.get("total_score", track.get("score", "")),
            track.get("explanation"), track.get("source"), track.get("external_url"),
        )])
    return Response("\ufeff" + output.getvalue(), media_type="text/csv; charset=utf-8", headers=headers)
