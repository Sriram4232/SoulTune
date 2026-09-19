"""Playlist utilities: diversification, energy-paced ordering, and track identity."""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter

from ..core.normalization import normalize
from ..core.scoring import known_number


def track_identity(track: dict) -> tuple[str, str]:
    """Canonical (artist, title) pair for deduplication."""
    title = re.sub(r"[\[(][^\])]*(?:remaster|version|edit)[^\])]*[\])]", "", track.get("title", ""), flags=re.I)
    title = re.sub(r"\s*[-–]\s*(?:\d{4}\s*)?(?:remaster(?:ed)?|radio edit|album version).*$", "", title, flags=re.I)
    return normalize(track.get("artist", "")), normalize(title)


def diversify(
    tracks: list[dict],
    size: int,
    prefer_local: bool = False,
    varied: bool = True,
    seed: str = "",
    previous_ids: set | None = None,
    all_languages: bool = False,
) -> list[dict]:
    """Select a diverse subset of tracks, capping per-artist, per-genre, and per-language counts."""
    def order(track):
        jitter = int(hashlib.sha256(f"{seed}:{track['id']}".encode()).hexdigest()[:8], 16) / 0xffffffff * .06 if seed else 0
        repeat_penalty = .20 if track["id"] in (previous_ids or set()) else 0
        if prefer_local:
            source = 2 if track["source"] == "local" else 1 if track["source"] != "mock" else 0
        else:
            source = 2 if track["source"] in {"spotify", "lastfm"} else 1 if track["source"] == "local" else 0
        return source, track["score"] + jitter - repeat_penalty

    ranked = sorted(tracks, key=order, reverse=True)
    artists: Counter = Counter()
    genres: Counter = Counter()
    languages: Counter = Counter()
    seen: set = set()
    chosen = []
    deferred = []
    genre_cap = max(5, math.ceil(size / 3)) if varied else size
    has_multiple_langs = len({t.get("language") for t in tracks if t.get("language") not in {"unknown", ""}}) > 1
    lang_cap = max(2, math.ceil(size / 3)) if (all_languages or has_multiple_langs) else size

    for track in ranked:
        artist, title = track_identity(track)
        if (artist, title) in seen or (artist != "unknown artist" and artists[artist] >= 2):
            continue
        genre = next(iter(track.get("genres", [])), "unknown")
        if genre != "unknown" and genres[genre] >= genre_cap:
            deferred.append(track)
            continue
        lang = track.get("language", "unknown")
        if lang != "unknown" and languages[lang] >= lang_cap:
            deferred.append(track)
            continue
        chosen.append(track)
        seen.add((artist, title))
        artists[artist] += 1
        genres[genre] += 1
        languages[lang] += 1
        if len(chosen) == size:
            return chosen

    # Relax caps if needed to fill requested playlist size
    for track in deferred:
        artist, title = track_identity(track)
        if (artist, title) not in seen and (artist == "unknown artist" or artists[artist] < 2):
            chosen.append(track)
            seen.add((artist, title))
            artists[artist] += 1
            if len(chosen) == size:
                break
    return chosen


def order_tracks(tracks: list[dict], profile: dict) -> list[dict]:
    """Re-order tracks for smooth energy pacing."""
    if len(tracks) < 2:
        return tracks
    remaining = list(tracks)
    ordered = []
    count = len(tracks)
    for index in range(count):
        position = index / max(count - 1, 1)
        if profile["activity"] in {"workout", "party"}:
            target = profile["energy"] - .14 + .23 * math.sin(math.pi * position)
        elif profile["activity"] in {"sleeping", "meditating"}:
            target = profile["energy"] + .08 - .16 * position
        else:
            target = profile["energy"] - .10 + .15 * math.sin(math.pi * position)
        previous_artist = normalize(ordered[-1]["artist"]) if ordered else None

        def cost(track: dict) -> float:
            energy = known_number(track, "energy")
            transition = abs((energy if energy is not None else profile["energy"]) - target)
            repeat = .2 if previous_artist and normalize(track["artist"]) == previous_artist else 0
            return transition + repeat - .05 * track["score"]

        chosen = min(remaining, key=cost)
        ordered.append(chosen)
        remaining.remove(chosen)
    return ordered
