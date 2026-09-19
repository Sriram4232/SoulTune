"""Local, user-owned audio discovery. No network is required for this library.

Only opaque ids are exposed to the API. A metadata sidecar can be named either
``Artist - Title.mp3.json`` or ``Artist - Title.json``. Unknown audio features
remain null; they are never presented as measurements made by the application.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import threading
from pathlib import Path
from typing import Any

ALLOWED_EXTENSIONS = frozenset({".mp3", ".wav", ".ogg", ".m4a", ".flac", ".aac", ".webm"})
PROJECT_ROOT = Path(__file__).resolve().parents[3]
_media_paths: dict[str, Path] = {}
_metadata_cache: dict[str, tuple[tuple, dict]] = {}
_scan_lock = threading.RLock()
MAX_LOCAL_TRACKS = 2000


def music_directory() -> Path:
    configured = os.getenv("LOCAL_MUSIC_DIR", "").strip()
    path = Path(configured).expanduser() if configured else PROJECT_ROOT / "fallback_songs"
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.absolute()


def _is_link(path: Path) -> bool:
    try:
        return path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())
    except OSError:
        return True


def _safe_file(path: Path, root: Path) -> bool:
    """Reject links/junctions and ensure every path remains inside the library."""
    try:
        if _is_link(root) or not path.is_file() or _is_link(path):
            return False
        path.resolve(strict=True).relative_to(root.resolve(strict=True))
        relative = path.relative_to(root)
        current = root
        for segment in relative.parts[:-1]:
            current = current / segment
            if _is_link(current):
                return False
        return True
    except (OSError, ValueError, RuntimeError):
        return False


def _text(value: Any, fallback: str = "", limit: int = 200) -> str:
    if isinstance(value, list):
        value = value[0] if value else fallback
    if value is None:
        return fallback
    return re.sub(r"[\x00-\x1f\x7f]", "", str(value)).strip()[:limit] or fallback


def _number(value: Any, low: float, high: float) -> float | None:
    try:
        result = float(value)
        return result if math.isfinite(result) and low <= result <= high else None
    except (ValueError, TypeError):
        return None


def _list(value: Any) -> list[str]:
    if isinstance(value, str):
        value = re.split(r"[,;/]", value)
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(_text(item).lower() for item in value[:20] if _text(item)))


def _sidecar(path: Path, root: Path) -> tuple[dict, tuple]:
    for sidecar in (path.with_suffix(path.suffix + ".json"), path.with_suffix(".json")):
        try:
            if not _safe_file(sidecar, root) or sidecar.stat().st_size > 65536:
                continue
            stat = sidecar.stat()
            data = json.loads(sidecar.read_text(encoding="utf-8-sig"))
            if isinstance(data, dict):
                return data, (str(sidecar), stat.st_mtime_ns, stat.st_size)
        except (OSError, ValueError, UnicodeError):
            continue
    return {}, ()


def _embedded_tags(path: Path) -> dict:
    try:
        import mutagen

        audio = mutagen.File(path, easy=True)
        if audio is None:
            return {}
        tags = audio.tags or {}
        return {
            "title": tags.get("title"),
            "artist": tags.get("artist"),
            "album": tags.get("album"),
            "genres": tags.get("genre"),
            "release_year": _text(tags.get("date"))[:4],
            "language": _text(tags.get("language")),
            "duration_seconds": getattr(audio.info, "length", None),
            "tempo": _text(tags.get("bpm")),
        }
    except Exception:
        # Malformed or unsupported audio metadata must never break the library.
        return {}


def _track(path: Path, root: Path, identifier: str) -> dict:
    sidecar, sidecar_stamp = _sidecar(path, root)
    stat = path.stat()
    stamp = (stat.st_mtime_ns, stat.st_size, *sidecar_stamp)
    cached = _metadata_cache.get(str(path))
    if cached and cached[0] == stamp:
        return dict(cached[1])

    data = _embedded_tags(path)
    data.update(sidecar)
    # Use the listener's folder labels as tags, without inventing audio measurements.
    folder_label = " ".join(path.relative_to(root).parts[:-1]).casefold()
    folder_moods = {"energetic": "energetic", "love": "romantic", "melody": "calm", "sad": "melancholic", "vibe": "happy"}
    inferred_moods = [mood for label, mood in folder_moods.items() if re.search(r"\b" + label + r"\b", folder_label)]
    if not data.get("mood_tags"):
        data["mood_tags"] = inferred_moods
    if not _text(data.get("language")):
        tag_text = " ".join(_list(data.get("genres")))
        for language in ("english", "hindi", "telugu", "tamil", "kannada", "malayalam", "punjabi", "bengali"):
            if re.search(r"\b" + language + r"(?:\b|music)", tag_text):
                data["language"] = language
                break
    stem = path.stem
    artist, title = stem.split(" - ", 1) if " - " in stem else ("Unknown artist", stem)
    year = _number(data.get("release_year"), 1000, 2100)
    track = {
        "id": identifier,
        "title": _text(data.get("title"), title),
        "artist": _text(data.get("artist"), artist),
        "album": _text(data.get("album"), "Local collection"),
        "genres": _list(data.get("genres")),
        "mood_tags": _list(data.get("mood_tags")),
        "activity_tags": _list(data.get("activity_tags")),
        "tempo": _number(data.get("tempo"), 20, 300),
        "energy": _number(data.get("energy"), 0, 1),
        "valence": _number(data.get("valence"), 0, 1),
        "danceability": _number(data.get("danceability"), 0, 1),
        "instrumentalness": _number(data.get("instrumentalness"), 0, 1),
        "popularity": _number(data.get("popularity"), 0, 1),
        "release_year": int(year) if year else None,
        "language": _text(data.get("language"), "unknown").lower(),
        "duration_seconds": _number(data.get("duration_seconds"), 0, 86400),
        "explicit": data.get("explicit") if isinstance(data.get("explicit"), bool) else None,
        "image_url": None,
        "preview_url": f"/api/v1/media/{identifier}",
        "external_url": None,
        "source": "local",
        "metadata_notes": "Local audio. Mood tags may come from your folder labels; other metadata comes from embedded tags or sidecar JSON. Unprovided features are unknown.",
        "score": None,
        "score_breakdown": {},
        "explanation": "A downloaded song from your local fallback library. Available without music APIs.",
    }
    _metadata_cache[str(path)] = (stamp, dict(track))
    return track


def list_local_tracks() -> list[dict]:
    """Scan on each library request so newly downloaded songs appear immediately."""
    with _scan_lock:
        root = music_directory()
        paths: dict[str, Path] = {}
        tracks: list[dict] = []
        if root.is_dir() and not _is_link(root):
            for directory, subdirs, filenames in os.walk(root, followlinks=False):
                current = Path(directory)
                depth = len(current.relative_to(root).parts)
                subdirs[:] = sorted(
                    name for name in subdirs
                    if depth < 5 and not _is_link(current / name) and not name.startswith(".")
                )
                for name in sorted(filenames):
                    path = current / name
                    if path.suffix.lower() not in ALLOWED_EXTENSIONS or not _safe_file(path, root):
                        continue
                    try:
                        identity = str(root.resolve()).casefold() + "/" + path.relative_to(root).as_posix()
                        identifier = "local_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
                        tracks.append(_track(path, root, identifier))
                        paths[identifier] = path
                    except (OSError, ValueError):
                        continue
                    if len(tracks) >= MAX_LOCAL_TRACKS:
                        break
                if len(tracks) >= MAX_LOCAL_TRACKS:
                    break
        _media_paths.clear()
        _media_paths.update(paths)
        for stale in set(_metadata_cache) - {str(path) for path in paths.values()}:
            _metadata_cache.pop(stale, None)
        return tracks


def resolve_media(identifier: str) -> Path | None:
    """Resolve only an allowlisted library id, never a user-supplied pathname."""
    if not re.fullmatch(r"local_[a-f0-9]{24}", identifier):
        return None
    with _scan_lock:
        list_local_tracks()
        path = _media_paths.get(identifier)
        if path and path.suffix.lower() in ALLOWED_EXTENSIONS and _safe_file(path, music_directory()):
            return path
        return None


def rescan_library() -> list[dict]:
    with _scan_lock:
        _metadata_cache.clear()
        return list_local_tracks()


def invalidate_cache() -> None:
    with _scan_lock:
        _metadata_cache.clear()
        _media_paths.clear()
