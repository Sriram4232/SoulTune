"""Vivid 3-sentence track narrative generator using Groq with deterministic fallback."""

from __future__ import annotations

import json
import logging

from ..core.scoring import known_number
from ..core.normalization import title_case
from ..infrastructure.groq_client import chat_completion, groq_available

logger = logging.getLogger("curator.story")


def _deterministic_story(track: dict, profile: dict) -> str:
    """Build a rich deterministic 3-sentence story when Groq is unavailable."""
    mood = profile.get("primary_mood", "balanced")
    activity = profile.get("activity", "listening")
    energy = known_number(track, "energy")
    valence = known_number(track, "valence")
    genres = track.get("genres", [])
    genre_label = title_case(genres[0]) if genres else "eclectic"
    lang = track.get("language", "unknown")
    lang_note = f" A {lang.title()}-language track." if lang not in ("unknown", "") else ""

    # Atmospheric sentence based on energy/valence
    if energy is not None and valence is not None:
        if energy >= 0.75 and valence >= 0.60:
            atm = "This is a high-energy, feel-good track that pulses with momentum."
        elif energy >= 0.75:
            atm = "This track hits hard — intense and driving, built for moments where you need to push through."
        elif energy <= 0.40 and valence <= 0.40:
            atm = "A quiet, introspective piece that sits with you — the kind of song for when the world slows down."
        elif energy <= 0.40:
            atm = "Soft and unhurried, this track wraps around you like a slow exhale."
        elif valence >= 0.70:
            atm = f"Warm and uplifting, this is the kind of {genre_label} track that lifts the room without trying."
        else:
            atm = f"A steady, composed {genre_label} track — neither urgent nor slow, just right."
    elif energy is not None:
        atm = f"{'High-energy' if energy >= 0.65 else 'Laid-back'} and {genre_label}-flavoured — it sets a clear mood without overstating it."
    else:
        atm = f"A {genre_label} track that fits the texture of your moment."

    # Situation/context sentence
    situation_map = {
        "coding":     "Perfect for deep focus — the kind of track that fades into the background so your brain can stay in flow.",
        "studying":   "Ideal for a study session — low distraction, steady rhythm, keeps your concentration intact.",
        "workout":    "Made for movement — the tempo and drive give your workout the extra push it needs.",
        "party":      "Crowd-pleaser energy — the type of song that makes a room feel like it's exactly where it should be.",
        "driving":    "Built for an open road — it unfolds at the pace of a good drive, windows down, no destination.",
        "relaxing":   "The kind of track you put on when you need the day to slow down — easy and unhurried.",
        "sleeping":   "Gentle and fading — designed to let your mind drift without pulling it back.",
        "meditating": "Still and centred — it creates space without filling it.",
        "listening":  f"An excellent pick for a {mood} moment — the kind of song you end up playing twice.",
    }
    situation = situation_map.get(activity, situation_map["listening"])

    # Mood-fit sentence
    mood_map = {
        "energetic":   "It was chosen because it matches the high-energy, powerful vibe you were after.",
        "calm":        "Selected because its gentle tone matches the calm, unhurried feeling you described.",
        "happy":       "Picked for its positive charge — it captures the upbeat spirit of your request.",
        "melancholic": "Chosen for its deeper emotional texture — it sits with sadness without being heavy.",
        "focused":     "Selected for its low-distraction, steady character — keeps you in the zone.",
        "romantic":    "Picked for its warmth and intimacy — the right soundtrack for a soft, close moment.",
        "nostalgic":   "Chosen because it carries a sense of memory — the way good music makes you feel like you've been here before.",
        "dreamy":      "Selected for its atmospheric, floating quality — it blurs the edges of the moment.",
        "confident":   "Picked because it has that bold, forward-moving feel — music that walks with you.",
        "sleepy":      "Chosen because it's gentle enough to let you drift without pulling you back.",
        "balanced":    "A well-rounded pick that fits the general feel of your request.",
    }
    mood_fit = mood_map.get(mood, mood_map["balanced"])

    return f"{atm} {situation}{lang_note} {mood_fit}"


build_deterministic_story = _deterministic_story


async def generate_track_stories(tracks: list[dict], profile: dict, description: str) -> None:
    """Generate vivid narrative 'story' descriptions for each selected track.

    Mutates each track dict in-place by adding a 'story' key.
    Falls back to deterministic descriptions if Groq is unavailable.
    """
    # Always assign deterministic stories first
    for track in tracks:
        track["story"] = _deterministic_story(track, profile)

    if not groq_available() or not tracks:
        return

    # Build a compact payload — one JSON entry per track
    track_list = [
        {
            "id": t["id"],
            "title": t["title"],
            "artist": t["artist"],
            "genres": t.get("genres", []),
            "mood_tags": t.get("mood_tags", []),
            "language": t.get("language", "unknown"),
            "energy_pct": round((known_number(t, "energy") or 0.5) * 100),
            "valence_pct": round((known_number(t, "valence") or 0.5) * 100),
            "tempo": round(known_number(t, "tempo") or 0),
        }
        for t in tracks
    ]
    system_msg = (
        "You are a music curator writing vivid, human descriptions for song recommendations. "
        "For each track, write EXACTLY 3 sentences:\n"
        "1. The atmosphere/character of the song — what it sounds like, the texture and feel.\n"
        "2. The situation or moment it is perfect for — be specific (e.g. 'driving at night', 'rainy afternoon indoors', 'pre-workout pump-up').\n"
        "3. Why it was chosen for the user's specific mood request — reference the mood, activity, or energy level.\n"
        "Keep each description vivid, natural, and personal. No bullet points. No metadata stats. "
        "Return a JSON object with key 'tracks', which is an array of objects with 'id' and 'story' fields ONLY. "
        "Never include any other fields. Do not reference Spotify, sources, or technical details."
    )
    user_msg = json.dumps({
        "user_request": description,
        "mood": profile.get("primary_mood", "balanced"),
        "activity": profile.get("activity", "listening"),
        "tracks": track_list,
    })

    try:
        result = await chat_completion(
            system=system_msg,
            user=user_msg,
            temperature=0.7,
            max_tokens=3000,
            json_mode=True,
            timeout_seconds=14.0,
        )
        data = result["data"]
        story_map = {
            item["id"]: item.get("story", "").strip()
            for item in data.get("tracks", [])
            if "id" in item and item.get("story")
        }
        for track in tracks:
            if track["id"] in story_map and len(story_map[track["id"]]) > 30:
                track["story"] = story_map[track["id"]]
    except Exception as exc:
        logger.debug("Groq story generation failed (deterministic fallback used): %s", exc)
