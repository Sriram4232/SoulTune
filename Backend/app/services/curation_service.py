"""End-to-end music curation pipeline coordinator."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from functools import lru_cache
from pathlib import Path

from ..core.heuristics import matches_constraints
from ..core.scoring import score_track
from ..infrastructure.local_audio import list_local_tracks
from ..infrastructure.lastfm import remote_candidates
from .mood_parser import parse_profile
from .story_service import generate_track_stories
from .playlist_service import diversify, order_tracks

logger = logging.getLogger("curator.curation")


@lru_cache(maxsize=1)
def mock_tracks() -> list[dict]:
    path = Path(__file__).resolve().parents[2] / "data" / "mock_tracks.json"
    return json.loads(path.read_text(encoding="utf-8"))


async def curate(
    description: str,
    playlist_size: int = 10,
    previous_profile: dict | None = None,
    preferences: dict | None = None,
) -> dict:
    """Run the full curation pipeline: parse → gather → filter → score → diversify → order → narrate."""
    profile, parser, warnings = await parse_profile(description, previous_profile, preferences)

    # Gather candidates from local library and remote APIs concurrently
    local, (remote, remote_warnings) = await asyncio.gather(
        asyncio.to_thread(list_local_tracks),
        remote_candidates(profile),
    )
    warnings.extend(remote_warnings)
    candidates = local + remote

    # Fall back to mock tracks when no API keys are configured and no local tracks exist
    if not candidates and not (
        os.getenv("SPOTIFY_CLIENT_ID", "").strip() and os.getenv("SPOTIFY_CLIENT_SECRET", "").strip()
    ) and not os.getenv("LASTFM_API_KEY", "").strip():
        candidates = mock_tracks()

    # Deduplicate by track id
    unique = {}
    for candidate in candidates:
        unique.setdefault(candidate["id"], candidate)

    # Filter by constraints and excluded track ids
    excluded_ids = set((preferences or {}).get("_excluded_track_ids", []))
    valid = [
        track for track in unique.values()
        if track["id"] not in excluded_ids and matches_constraints(track, profile)
    ]

    # Score and rank
    ranked = [score_track(track, profile) for track in valid]

    # Diversify and order
    target_size = max(1, min(10, playlist_size))
    selected = diversify(
        ranked,
        target_size,
        prefer_local=not remote or bool(remote_warnings),
        varied=(preferences or {}).get("diversity", True),
        seed=(preferences or {}).get("_selection_seed", ""),
        previous_ids=set((preferences or {}).get("_previous_track_ids", [])),
        all_languages=profile.get("all_languages", False),
    )
    selected = order_tracks(selected, profile)[:10]

    # Generate vivid narrative descriptions
    await generate_track_stories(selected, profile, description)

    # Build result warnings
    sources = {track["source"] for track in selected}
    if "mock" in sources:
        warnings.append("Demo recommendations use fictional songs and synthetic features. Add downloaded audio to fallback_songs for playback.")
    if any(track.get("explicit") is None for track in selected):
        warnings.append("Some songs have no content rating. Ask for clean music to include only songs verified as non-explicit.")
    if not local:
        warnings.append("Your fallback library is empty. Add MP3, WAV, OGG, M4A, FLAC, AAC or WebM files to fallback_songs, then refresh the library.")
    if len(selected) < target_size:
        warnings.append(f"Only {len(selected)} tracks satisfy your constraints and artist limits; the requested {target_size} could not be filled without relaxing them.")
    if remote and not any(track["source"] in {"spotify", "lastfm"} for track in selected):
        warnings.append("Online results lacked matches for all strict constraints; compatible local or demo metadata was used.")
    if local and not any(track["source"] == "local" for track in selected):
        warnings.append("Local songs need matching metadata to satisfy this request. Optional sidecar JSON can supply tempo, mood, language and explicit-content information.")

    activity_name = {
        "coding": "Code & Concentrate", "studying": "Deep Focus",
        "workout": "Find Your Momentum", "party": "After Hours",
        "driving": "Open Road", "relaxing": "Slow the World",
        "sleeping": "Drift into Quiet", "meditating": "Room to Breathe",
    }.get(profile["activity"])
    name = activity_name or f"{profile['primary_mood'].title()} Frequencies"

    return {
        "profile": profile,
        "tracks": selected,
        "name": name,
        "source": next(iter(sources)) if len(sources) == 1 else "mixed" if sources else "none",
        "parser": parser,
        "warnings": list(dict.fromkeys(warnings)),
    }
