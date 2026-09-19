"""Track scoring, weights, and feature similarity algorithms."""
from __future__ import annotations

import math
from typing import Any

from .normalization import canonical_genre, clamp

WEIGHTS: dict[str, float] = {
    "mood": .30,
    "energy": .20,
    "valence": .15,
    "genre": .10,
    "tempo": .10,
    "activity": .10,
    "popularity": .05
}


def known_number(track: dict, field: str) -> float | None:
    value = track.get(field)
    return float(value) if isinstance(value, (int, float)) and math.isfinite(value) else None


def similarity(track: dict, field: str, target: float) -> float:
    value = known_number(track, field)
    return 1 - abs(target - value) if value is not None else .5


def score_track(track: dict, profile: dict) -> dict:
    moods = {profile["primary_mood"], *profile["secondary_moods"]}
    tags = set(track.get("mood_tags", []))
    if moods & tags:
        mood_score = 1.0 if profile["primary_mood"] in tags else .8
    elif tags & {"happy", "confident"} and profile["primary_mood"] == "energetic":
        mood_score = .75
    elif tags & {"calm", "dreamy"} and profile["primary_mood"] == "focused":
        mood_score = .75
    elif tags:
        mood_score = (similarity(track, "energy", profile["energy"]) + similarity(track, "valence", profile["valence"])) / 2 * .7
    else:
        mood_score = .5

    preferred = set(profile["preferred_genres"])
    genres = {canonical_genre(g) for g in track.get("genres", [])}
    genre_score = 1.0 if not preferred or preferred & genres else .25 if genres else .5

    tempo = known_number(track, "tempo")
    center = (profile["tempo_min"] + profile["tempo_max"]) / 2
    tempo_score = max(0.0, 1 - abs(tempo - center) / 100) if tempo is not None else .5

    activity = profile["activity"]
    if activity in track.get("activity_tags", []):
        activity_score = 1.0
    elif activity in {"coding", "studying", "meditating", "sleeping"}:
        activity_score = .65 * similarity(track, "instrumentalness", profile["instrumental_preference"]) + .35 * similarity(track, "energy", profile["energy"])
    elif activity in {"party", "workout"}:
        activity_score = .6 * similarity(track, "danceability", profile["danceability"]) + .4 * similarity(track, "energy", profile["energy"])
    else:
        activity_score = similarity(track, "energy", profile["energy"])

    popularity = known_number(track, "popularity")
    breakdown = {
        "mood": mood_score,
        "energy": similarity(track, "energy", profile["energy"]),
        "valence": similarity(track, "valence", profile["valence"]),
        "genre": genre_score,
        "tempo": tempo_score,
        "activity": activity_score,
        "popularity": popularity if popularity is not None else .5
    }

    result = dict(track)
    result["score_breakdown"] = {key: round(clamp(value), 4) for key, value in breakdown.items()}
    result["score"] = round(sum(WEIGHTS[key] * value for key, value in result["score_breakdown"].items()), 4)

    known_fields = [name for name in ("tempo", "energy", "valence", "instrumentalness") if known_number(track, name) is not None]
    result["metadata_coverage"] = round(len(known_fields) / 4, 2)

    # Multi-sentence deterministic explanation
    sentences = []
    energy = known_number(track, "energy")
    valence = known_number(track, "valence")
    instrumentalness = known_number(track, "instrumentalness")
    source = track.get("source")

    # 1. Mood / genre fit
    if moods & tags:
        matched = ", ".join(sorted(moods & tags))
        sentences.append(f"This track carries a strong {matched} energy that directly matches your request.")
    elif preferred & genres:
        matched = ", ".join(sorted(preferred & genres))
        sentences.append(f"It sits squarely in the {matched} sound you asked for.")
    elif tags:
        sentences.append(f"Its {', '.join(sorted(tags))} character was the closest available fit for your mood.")
    else:
        sentences.append("This track was selected as a strong overall candidate for your mood and activity.")

    # 2. Energy / vibe
    if energy is not None:
        pct = round(energy * 100)
        target_pct = round(profile["energy"] * 100)
        if pct >= 75:
            sentences.append(f"At {pct}% energy it's high-intensity — it drives you forward (your target: {target_pct}%).")
        elif pct >= 50:
            sentences.append(f"It has balanced {pct}% energy — engaging but never overwhelming (your target: {target_pct}%).")
        else:
            sentences.append(f"With {pct}% energy it's laid-back and undemanding — perfect for focus or winding down (your target: {target_pct}%).")
    elif profile.get("activity") not in {"listening", None}:
        sentences.append(f"Its overall feel suits a {profile.get('activity', 'listening')} session.")

    # 3. Emotional tone (valence)
    if valence is not None:
        pct = round(valence * 100)
        if pct >= 70:
            sentences.append(f"The tone skews positive and uplifting ({pct}% valence) — expect it to lift the room.")
        elif pct <= 35:
            sentences.append(f"It has a deeper, introspective tone ({pct}% valence) — fits reflective or melancholic moods.")

    # 4. Tempo character
    if tempo is not None:
        tempo_label = "fast-paced" if tempo > 130 else "mid-tempo" if tempo > 90 else "slow-groove"
        in_range = profile["tempo_min"] <= tempo <= profile["tempo_max"]
        sentences.append(f"At {round(tempo)} BPM it's a {tempo_label} track{' — right in your tempo target range' if in_range else ''}.")

    # 5. Instrumental nature
    if instrumentalness is not None and instrumentalness > 0.7:
        sentences.append("It's predominantly instrumental — no lyrics to pull focus away.")

    # 6. Language / genre context
    lang = track.get("language", "unknown")
    track_genres = [g for g in track.get("genres", []) if g != "unknown"]
    if lang not in ("unknown", "") and profile.get("languages") and lang in profile["languages"]:
        sentences.append(f"It's in {lang.title()} — matching your language preference.")
    if track_genres and not (preferred & genres):
        sentences.append(f"Genre: {', '.join(track_genres)}.")

    # 7. Release year
    year = track.get("release_year")
    if year:
        sentences.append(f"Released in {year}.")

    # 8. Match confidence
    score = result["score"]
    if score >= 0.80:
        sentences.append("Overall, it's a high-confidence match.")
    elif score >= 0.65:
        sentences.append("It's a solid pick with a few trade-offs.")
    else:
        sentences.append("It's a partial fit — try refining your request if this misses the mark.")

    # 9. Source context
    if source == "mock":
        sentences.append("Note: demo track with fictional metadata — no real audio.")
    elif source == "local":
        note = "Playing from your downloaded local library."
        if len(known_fields) < 4:
            note += " Some audio features are estimated; match is approximate."
        sentences.append(note)
    elif source == "spotify":
        sentences.append("Verified on Spotify — direct listening link available.")
    else:
        sentences.append("Found via Last.fm — listening link available; audio features estimated.")

    result["explanation"] = " ".join(sentences)
    return result
