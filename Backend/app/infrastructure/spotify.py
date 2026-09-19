"""Spotify Web API integration: token management, search, and track parsing."""

from __future__ import annotations

import asyncio
import base64
import copy
import hashlib
import logging
import os
import time
from typing import Any

import httpx

from ..core.normalization import GENRES, GLOBAL_DIVERSE_LANGUAGES, LANGUAGES, MOODS, canonical_genre

logger = logging.getLogger("curator.spotify")

# --- Module-level state ---
_token_data: dict[str, Any] = {"token": "", "expires_at": 0.0}
_cache: dict[str, tuple[float, list[dict]]] = {}
_circuit_until = 0.0


# --- Token management ---

async def _get_token(client: httpx.AsyncClient) -> str | None:
    client_id = os.getenv("SPOTIFY_CLIENT_ID", "").strip()
    client_secret = os.getenv("SPOTIFY_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        return None
    now = time.monotonic()
    if _token_data.get("token") and _token_data.get("expires_at", 0) > now + 60:
        return _token_data["token"]
    auth = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    try:
        response = await client.post(
            "https://accounts.spotify.com/api/token",
            headers={"Authorization": f"Basic {auth}", "Content-Type": "application/x-www-form-urlencoded"},
            data={"grant_type": "client_credentials"},
        )
        response.raise_for_status()
        data = response.json()
        token = data.get("access_token")
        if token:
            _token_data["token"] = token
            _token_data["expires_at"] = now + float(data.get("expires_in", 3600))
        return token
    except Exception as exc:
        logger.warning("Spotify token acquisition failed: %s", exc)
        return None


# --- Track parsing ---

def _parse_track(item: dict, target_genre: str = "", target_mood: str = "", target_lang: str = "") -> dict | None:
    title = str(item.get("name", ""))[:200].strip()
    artists_list = item.get("artists", [])
    artist = ", ".join(str(a.get("name", "")).strip() for a in artists_list if a.get("name"))[:200].strip()
    if not title or not artist:
        return None
    external = item.get("external_urls", {}).get("spotify")
    if external and not (str(external).startswith("https://open.spotify.com/") or str(external).startswith("http://open.spotify.com/")):
        external = None
    album_data = item.get("album", {})
    album_name = str(album_data.get("name", ""))[:200].strip()
    images = album_data.get("images", [])
    image_url = images[0].get("url") if images and isinstance(images, list) and isinstance(images[0], dict) else None
    release_date = str(album_data.get("release_date", "")).strip()
    release_year = int(release_date[:4]) if len(release_date) >= 4 and release_date[:4].isdigit() else None
    duration_ms = item.get("duration_ms")
    duration = round(float(duration_ms) / 1000, 1) if duration_ms and duration_ms > 0 else None
    popularity_val = item.get("popularity")
    popularity = round(float(popularity_val) / 100, 2) if popularity_val is not None else None
    explicit_val = item.get("explicit") if isinstance(item.get("explicit"), bool) else None
    spotify_id = str(item.get("id", ""))
    track_id = "spotify_" + (spotify_id if spotify_id else hashlib.sha256(f"{artist}:{title}".encode()).hexdigest()[:24])

    lang = target_lang.lower() if target_lang else "unknown"
    genres = [canonical_genre(target_genre)] if target_genre and target_genre in GENRES else []
    mood_tags = [target_mood] if target_mood and target_mood in MOODS else []

    return {
        "id": track_id,
        "title": title, "artist": artist, "album": album_name, "genres": genres,
        "mood_tags": mood_tags, "activity_tags": [],
        "tempo": None, "energy": None, "valence": None, "danceability": None, "instrumentalness": None,
        "popularity": popularity, "release_year": release_year, "language": lang, "duration_seconds": duration,
        "explicit": explicit_val, "image_url": image_url, "preview_url": item.get("preview_url"),
        "external_url": external, "source": "spotify",
        "metadata_notes": "Spotify verified track with cover art and release metadata. Direct link to Spotify.",
    }


# --- Candidate search ---

async def spotify_candidates(profile: dict) -> tuple[list[dict], list[str]]:
    global _circuit_until
    client_id = os.getenv("SPOTIFY_CLIENT_ID", "").strip()
    client_secret = os.getenv("SPOTIFY_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        return [], []

    now = time.monotonic()
    if now < _circuit_until:
        return [], ["Spotify is temporarily unavailable; using cached metadata and the local fallback library."]

    queries: list[tuple[str, str, str, str]] = []

    year_filter = ""
    if profile.get("release_year_min") and profile.get("release_year_max"):
        if profile["release_year_min"] == profile["release_year_max"]:
            year_filter = f" year:{profile['release_year_min']}"
        else:
            year_filter = f" year:{profile['release_year_min']}-{profile['release_year_max']}"
    elif profile.get("release_year_min"):
        year_filter = f" year:{profile['release_year_min']}-2026"

    mood = profile["primary_mood"] if profile.get("primary_mood") != "balanced" else ""
    pref_genres = profile.get("preferred_genres", [])
    languages = profile.get("languages", [])
    is_all_languages = profile.get("all_languages", False)

    if is_all_languages:
        genre_term = f" {pref_genres[0]}" if pref_genres else ""
        for lang in GLOBAL_DIVERSE_LANGUAGES:
            term = f"{lang}{genre_term} {mood}".strip() if (mood or genre_term) else f"{lang} top hits"
            queries.append((f"{term}{year_filter}", pref_genres[0] if pref_genres else "", mood, lang))
    elif languages:
        for lang in languages[:4]:
            if pref_genres:
                for genre in pref_genres[:3]:
                    queries.append((f"{lang} {genre}{year_filter}", genre, mood, lang))
            if mood and mood != "balanced":
                queries.append((f"{lang} {mood}{year_filter}", "", mood, lang))
            queries.append((f"{lang} hits{year_filter}", "", mood, lang))
            queries.append((f"{lang} top songs{year_filter}", "", mood, lang))
            keyword_terms = " ".join(k for k in profile.get("keywords", []) if len(k) > 3 and k not in {lang, mood} and k.isalpha())[:40]
            if keyword_terms:
                queries.append((f"{lang} {keyword_terms}{year_filter}", "", mood, lang))
    else:
        if pref_genres:
            for genre in pref_genres[:3]:
                term = f"{genre} {mood}".strip() if mood else f"{genre} music"
                queries.append((f"{term}{year_filter}", genre, mood, ""))
        elif mood:
            activity = profile["activity"] if profile.get("activity") != "listening" else ""
            term = f"{mood} {activity}".strip() if activity else f"{mood} songs"
            queries.append((f"{term}{year_filter}", "", mood, ""))
        else:
            activity = profile["activity"] if profile.get("activity") != "listening" else "music"
            queries.append((f"{activity} hits{year_filter}", "", "", ""))

    queries = queries[:8]

    cached_tracks = []
    missing_queries = []
    for q, g, m, l in queries:
        cache_key = f"{q}:{g}:{m}:{l}"
        if cache_key in _cache and (now - _cache[cache_key][0] < 3600):
            cached_tracks.extend(_cache[cache_key][1])
        else:
            missing_queries.append((cache_key, q, g, m, l))

    if not missing_queries:
        return copy.deepcopy(cached_tracks), []

    async def fetch_query(client: httpx.AsyncClient, token: str, cache_key: str, q: str, g: str, m: str, l: str):
        response = await client.get(
            "https://api.spotify.com/v1/search",
            headers={"Authorization": f"Bearer {token}"},
            params={"q": q, "type": "track", "limit": 10},
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as err:
            logger.error("Spotify search failed (status %s) for query %s: %s", err.response.status_code, q, err.response.text)
            raise
        data = response.json()
        items = data.get("tracks", {}).get("items", [])
        tracks = [t for item in items if isinstance(item, dict) and (t := _parse_track(item, g, m, l))]
        return cache_key, tracks

    failed = False
    new_tracks = []
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(6.0, connect=3.0)) as client:
            token = await _get_token(client)
            if not token:
                raise ValueError("Unable to obtain Spotify token")
            results = await asyncio.gather(
                *(fetch_query(client, token, ck, q, g, m, l) for ck, q, g, m, l in missing_queries),
                return_exceptions=True
            )
            for res in results:
                if isinstance(res, Exception):
                    failed = True
                    logger.warning("Spotify search query failed: %s", res)
                else:
                    cache_key, tracks = res
                    _cache[cache_key] = (now, tracks)
                    new_tracks.extend(tracks)
    except Exception as exc:
        failed = True
        logger.warning("Spotify candidate fetching failed: %s", exc)

    if failed and not new_tracks and not cached_tracks:
        _circuit_until = now + 60

    if len(_cache) > 100:
        oldest = sorted(_cache, key=lambda k: _cache[k][0])[:len(_cache) - 100]
        for k in oldest:
            _cache.pop(k, None)

    all_tracks = cached_tracks + new_tracks
    seen = set()
    deduped = []
    for t in all_tracks:
        if t["id"] not in seen:
            seen.add(t["id"])
            deduped.append(t)

    warnings = ["Spotify is temporarily unavailable; local songs and fallback recommendations were used."] if failed and not deduped else []
    return copy.deepcopy(deduped), warnings
