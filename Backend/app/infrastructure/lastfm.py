"""Last.fm API integration: tag-based track search with caching and circuit breaker."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import logging
import os
import time
from urllib.parse import urlparse

import httpx

from ..core.normalization import GENRES, LANGUAGES, MOODS, canonical_genre

logger = logging.getLogger("curator.lastfm")

_cache: dict[str, tuple[float, list[dict]]] = {}
_circuit_until = 0.0


def _get_cache() -> dict[str, tuple[float, list[dict]]]:
    try:
        import app.engine as eng
        if hasattr(eng, "_lastfm_cache") and isinstance(eng._lastfm_cache, dict):
            return eng._lastfm_cache
    except (ImportError, AttributeError):
        pass
    return _cache


def _get_circuit() -> float:
    try:
        import app.engine as eng
        if hasattr(eng, "_lastfm_circuit_until"):
            return float(eng._lastfm_circuit_until)
    except (ImportError, AttributeError, TypeError):
        pass
    return _circuit_until


def _set_circuit(val: float) -> None:
    global _circuit_until
    _circuit_until = val
    try:
        import app.engine as eng
        if hasattr(eng, "_lastfm_circuit_until"):
            eng._lastfm_circuit_until = val
    except (ImportError, AttributeError):
        pass


# --- Track parsing ---

def _parse_track(item: dict, tag: str) -> dict | None:
    title = str(item.get("name", ""))[:200].strip()
    artist_data = item.get("artist", {})
    artist = str(artist_data.get("name", "") if isinstance(artist_data, dict) else artist_data)[:200].strip()
    if not title or not artist:
        return None
    external = item.get("url")
    parsed = urlparse(str(external))
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"www.last.fm", "last.fm"}:
        external = None
    elif external:
        external = "https://" + str(external).split("://", 1)[1]
    try:
        duration = float(item.get("duration", 0)) or None
    except (ValueError, TypeError):
        duration = None
    return {
        "id": "lastfm_" + hashlib.sha256((artist.casefold() + "/" + title.casefold()).encode()).hexdigest()[:24],
        "title": title, "artist": artist, "album": "", "genres": [canonical_genre(tag)] if tag in GENRES else [],
        "mood_tags": [tag] if tag in MOODS else [], "activity_tags": [],
        "tempo": None, "energy": None, "valence": None, "danceability": None, "instrumentalness": None,
        "popularity": None, "release_year": None, "language": tag.lower() if tag.lower() in LANGUAGES else "unknown", "duration_seconds": duration,
        "explicit": None, "image_url": None, "preview_url": None, "external_url": external, "source": "lastfm",
        "metadata_notes": "Last.fm title, artist and community tag. Audio features are unavailable; this is a listening link, not a stream.",
    }


# --- Candidate search ---

async def lastfm_candidates(profile: dict) -> tuple[list[dict], list[str]]:
    key = os.getenv("LASTFM_API_KEY", "").strip()
    if not key:
        return [], []
    tags = (profile["preferred_genres"] or [profile["primary_mood"]])[:3]
    if tags == ["balanced"]:
        tags = ["indie", "pop", "jazz"]
    cache = _get_cache()
    cached = [track for tag in tags for track in cache.get(tag, (0, []))[1]]
    now = time.monotonic()
    if now < _get_circuit():
        return copy.deepcopy(cached), ["Last.fm is unavailable; using cached metadata and the local fallback library."]
    missing = [tag for tag in tags if tag not in cache or now - cache[tag][0] > 3600]
    if not missing:
        return copy.deepcopy(cached), []

    async def fetch(client: httpx.AsyncClient, tag: str) -> tuple[str, list[dict]]:
        response = await client.get("https://ws.audioscrobbler.com/2.0/", params={"method": "tag.gettoptracks", "tag": tag, "api_key": key, "format": "json", "limit": 60})
        response.raise_for_status()
        data = response.json()
        if data.get("error"):
            raise ValueError("Music API unavailable")
        items = data.get("tracks", {}).get("track", [])
        if not isinstance(items, list):
            raise ValueError("Invalid music response")
        tracks = [track for item in items[:60] if isinstance(item, dict) and (track := _parse_track(item, tag))]
        return tag, tracks

    async with httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=2.5)) as client:
        results = await asyncio.gather(*(fetch(client, tag) for tag in missing), return_exceptions=True)
    failed = False
    for result in results:
        if isinstance(result, Exception):
            failed = True
        else:
            tag, tracks = result
            cache[tag] = (now, tracks)
    if failed:
        _set_circuit(now + 60)
    if len(cache) > 50:
        oldest = sorted(cache, key=lambda tag: cache[tag][0])[:len(cache) - 50]
        for tag in oldest:
            cache.pop(tag, None)
    result_tracks = [track for tag in tags for track in cache.get(tag, (0, []))[1]]
    warnings = ["Last.fm is unavailable; local songs, cached metadata and demo recommendations remain available."] if failed else []
    return copy.deepcopy(result_tracks), warnings


# --- Remote candidates selector ---

async def remote_candidates(profile: dict) -> tuple[list[dict], list[str]]:
    """Try Spotify first, then Last.fm, based on configured keys."""
    spotify_id = os.getenv("SPOTIFY_CLIENT_ID", "").strip()
    spotify_secret = os.getenv("SPOTIFY_CLIENT_SECRET", "").strip()
    if spotify_id and spotify_secret:
        from .spotify import spotify_candidates
        return await spotify_candidates(profile)
    lastfm_key = os.getenv("LASTFM_API_KEY", "").strip()
    if lastfm_key:
        return await lastfm_candidates(profile)
    return [], []
