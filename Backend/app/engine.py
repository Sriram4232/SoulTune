"""Music curation engine facade.

This module re-exports the modular engine components from:
- ``app.core`` (models, normalization, heuristics, scoring)
- ``app.infrastructure`` (local audio, Spotify, Last.fm, Groq)
- ``app.services`` (mood parsing, curation pipeline, story generator, playlist utilities)

Maintained for backward compatibility and test runner monkeypatching.
"""

from __future__ import annotations

import httpx

# Core
from .core.heuristics import (
    matches_constraints,
    parse_description,
)
from .core.models import MoodProfile
from .core.normalization import (
    ACTIVITIES,
    GENRES,
    GLOBAL_DIVERSE_LANGUAGES,
    LANGUAGES,
    MOODS,
    canonical_genre,
    normalize,
    title_case,
)
from .core.scoring import WEIGHTS, known_number, score_track

# Infrastructure
from .infrastructure.groq_client import (
    _groq_model_cache,
    chat_completion,
    groq_available,
)
from .infrastructure.lastfm import (
    _cache as _lastfm_cache,
    lastfm_candidates,
    remote_candidates,
)
from .infrastructure.local_audio import (
    list_local_tracks,
    rescan_library,
    resolve_media,
)
from .infrastructure.spotify import spotify_candidates

# Services
from .services.curation_service import curate, mock_tracks
from .services.mood_parser import DEFAULT_PROFILE, parse_profile
from .services.playlist_service import (
    diversify,
    order_tracks,
    track_identity,
)
from .services.story_service import (
    build_deterministic_story,
    generate_track_stories,
)

# Compatibility aliases
_known_number = known_number
order_by_energy = order_tracks
parse_heuristic_profile = parse_description
_lastfm_circuit_until = 0.0

__all__ = [
    "ACTIVITIES",
    "DEFAULT_PROFILE",
    "GENRES",
    "GLOBAL_DIVERSE_LANGUAGES",
    "LANGUAGES",
    "MOODS",
    "MoodProfile",
    "WEIGHTS",
    "_groq_model_cache",
    "_known_number",
    "_lastfm_cache",
    "_lastfm_circuit_until",
    "build_deterministic_story",
    "canonical_genre",
    "chat_completion",
    "curate",
    "diversify",
    "generate_track_stories",
    "groq_available",
    "httpx",
    "known_number",
    "lastfm_candidates",
    "list_local_tracks",
    "matches_constraints",
    "mock_tracks",
    "normalize",
    "order_by_energy",
    "order_tracks",
    "parse_description",
    "parse_heuristic_profile",
    "parse_profile",
    "remote_candidates",
    "rescan_library",
    "resolve_media",
    "score_track",
    "spotify_candidates",
    "title_case",
    "track_identity",
]
