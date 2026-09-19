"""Rule-based offline parsing and hard constraint validation."""
from __future__ import annotations

import copy
import re
from typing import Any

from .models import MoodProfile
from .normalization import (
    ACTIVITIES,
    GENRES,
    LANGUAGES,
    MASS_INDICATORS,
    MOOD_VALUES,
    MOODS,
    canonical_genre,
    clamp,
    contains_term,
    extract_negative_clauses,
    normalize,
    union_unique,
)
from .scoring import known_number


def parse_description(
    description: str,
    previous_profile: dict | None = None,
    preferences: dict | None = None,
) -> dict:
    """Deterministic intent parsing, including additive follow-up constraints."""
    prior = MoodProfile.model_validate(previous_profile or {}).model_dump()
    profile = copy.deepcopy(prior)
    text = description.lower().replace("’", "'")
    positive, negative = extract_negative_clauses(text)
    initial = previous_profile is None
    prefs = preferences or {}
    personalize = prefs.get("personalization", True)

    if initial:
        genres = prefs.get("genres", prefs.get("favorite_genres", prefs.get("preferred_genres", []))) if personalize else []
        if isinstance(genres, list):
            profile["preferred_genres"] = [canonical_genre(g) for g in genres if isinstance(g, str)][:25]
        excluded = prefs.get("excluded_artists", [])
        if isinstance(excluded, list):
            profile["excluded_artists"] = [str(a).lower()[:100] for a in excluded][:40]
        if prefs.get("allow_explicit") is False or prefs.get("explicit_content") is False:
            profile["allow_explicit"] = False
        if personalize and isinstance(prefs.get("languages"), list):
            profile["languages"] = [str(x).lower() for x in prefs["languages"]][:20]
        profile["excluded_genres"] = [canonical_genre(g) for g in prefs.get("excluded_genres", [])][:25]

    negative_parts = [part.strip() for clause in negative for part in re.split(r"\s+(?:and\s+no|or\s+no|and|or)\s+|,\s*", clause) if part.strip()]
    for clause in negative_parts:
        known = False
        if re.search(r"\b(?:heavy|aggressive|harsh)\b", clause):
            profile["excluded_genres"] = union_unique(profile["excluded_genres"], ["metal", "hard rock", "hardcore"])
            known = True
        for genre, aliases in GENRES.items():
            if any(contains_term(clause, alias) for alias in aliases):
                profile["excluded_genres"] = union_unique(profile["excluded_genres"], [genre])
                known = True
        for mood, aliases in MOODS.items():
            if any(contains_term(clause, alias) for alias in aliases):
                profile["avoid"] = union_unique(profile["avoid"], [mood])
                known = True
        for language in LANGUAGES:
            if contains_term(clause, language):
                profile["excluded_languages"] = union_unique(profile["excluded_languages"], [language])
                known = True
        if re.search(r" (vocals?|lyrics?|singing|singers?) ", clause):
            if not re.search(r" (explicit|dirty|offensive) ", clause):
                profile["only_instrumental"] = True
                profile["instrumental_preference"] = 1.0
            known = True
        if re.search(r" (explicit|profanity|swearing|offensive) ", clause):
            profile["allow_explicit"] = False
            profile["require_clean"] = True
            known = True
        artist_match = re.search(r"(?:songs?\s+(?:by|from)|artists?|tracks?\s+(?:by|from)|music\s+by)\s+(.+)", clause)
        if artist_match:
            artists = re.split(r"\s*,\s*|\s+or\s+", artist_match.group(1))
            profile["excluded_artists"] = union_unique(profile["excluded_artists"], [a.strip(" '\"") for a in artists if a.strip()])
        elif not known:
            candidate = re.sub(r"\b(?:any|songs?|tracks?|music|please)\b", "", clause).strip(" '\",")
            if candidate and len(candidate) <= 100:
                profile["excluded_artists"] = union_unique(profile["excluded_artists"], [candidate])

    activities = [name for name, data in ACTIVITIES.items() if any(contains_term(positive, alias) for alias in data[0])]
    if initial and not activities and personalize:
        activities = [str(activity).lower() for activity in prefs.get("activities", []) if str(activity).lower() in ACTIVITIES][:1]
    if activities:
        activity = activities[0]
        data = ACTIVITIES[activity]
        profile.update(activity=activity, energy=data[1], valence=data[2], danceability=data[3], instrumental_preference=data[4], primary_mood=data[8])
        if not profile["tempo_hard"]:
            profile.update(tempo_min=data[5], tempo_max=data[6])
        if initial and not profile["preferred_genres"]:
            profile["preferred_genres"] = list(data[7])

    found_moods = [mood for mood, aliases in MOODS.items() if any(contains_term(positive, alias) for alias in aliases)]
    profile["avoid"] = [m for m in profile["avoid"] if m not in found_moods]
    if found_moods:
        mood = found_moods[0]
        profile["primary_mood"] = mood
        profile["secondary_moods"] = union_unique(found_moods[1:], profile["secondary_moods"])[:10]
        if initial and not activities:
            profile["energy"], profile["valence"] = MOOD_VALUES[mood]

    # If user used "mass" / power / high-energy indicators, avoid soft/romantic/calm moods
    if any(contains_term(positive, indicator) for indicator in MASS_INDICATORS):
        profile["avoid"] = union_unique(profile["avoid"], ["calm", "romantic", "melancholic", "sleepy"])
        profile["energy"] = max(profile.get("energy", 0.7), 0.72)
        profile["danceability"] = max(profile.get("danceability", 0.6), 0.65)

    genres = [genre for genre, aliases in GENRES.items() if any(contains_term(positive, alias) for alias in aliases)]
    if genres:
        if initial or re.search(r"\b(?:only|just|switch to|instead|replace)\b", positive):
            profile["preferred_genres"] = genres
        else:
            profile["preferred_genres"] = union_unique(genres, profile["preferred_genres"])
        profile["excluded_genres"] = [g for g in profile["excluded_genres"] if g not in genres]
        if any(re.search(r"\b(?:only|just)\s+" + re.escape(alias) + r"\b|\b" + re.escape(alias) + r"\s+only\b", positive) for aliases in GENRES.values() for alias in aliases):
            profile["only_genres"] = genres
        elif profile["only_genres"]:
            profile["only_genres"] = union_unique(profile["only_genres"], genres)

    mentioned_languages = [language for language in sorted(LANGUAGES) if contains_term(positive, language)]
    if mentioned_languages:
        profile["languages"] = mentioned_languages
        profile["all_languages"] = False
        profile["excluded_languages"] = [x for x in profile["excluded_languages"] if x not in mentioned_languages]
    if re.search(r"\b(?:any|all|different|mixed|every)\s+languages?\b|\bmultilingual\b", positive):
        profile["languages"] = []
        profile["all_languages"] = True

    if re.search(r"\b(?:instrumentals?|instrumental only|only instrumental|no vocals)\b", positive) and not re.search(r"\bmore instrumental\b", positive):
        profile["only_instrumental"] = True
        profile["instrumental_preference"] = 1.0
    if "more instrumental" in positive or re.search(r"\b(?:less|fewer) (?:vocals|lyrics)\b", positive):
        profile["instrumental_preference"] = clamp(profile["instrumental_preference"] + .2)
    if re.search(r"\b(?:allow|include|with|add|bring back) vocals\b", positive):
        profile["only_instrumental"] = False
        profile["instrumental_preference"] = .3
    if re.search(r"\b(?:clean|family friendly|kid friendly)\b", positive):
        profile["allow_explicit"] = False
        profile["require_clean"] = True
    if re.search(r"\b(?:allow|include|enable) explicit\b", positive):
        profile["allow_explicit"] = True
        profile["require_clean"] = False

    step = .08 if re.search(r"\b(?:slightly|little|bit)\b", positive) else .16
    if re.search(r"\b(?:more energetic|higher energy|more energy|increase energy|faster|upbeat|pump it up)\b", positive):
        profile["energy"] = clamp(prior["energy"] + step) if not initial else max(profile["energy"], .72)
        if not profile["tempo_hard"] and not initial:
            profile["tempo_min"] = min(280, profile["tempo_min"] + 8)
            profile["tempo_max"] = min(300, profile["tempo_max"] + 8)
    if re.search(r"\b(?:less energetic|lower energy|less energy|reduce energy|slower|calmer|more relaxed|more chill)\b", positive):
        profile["energy"] = clamp(prior["energy"] - step)
        if not profile["tempo_hard"]:
            profile["tempo_min"] = max(20, profile["tempo_min"] - 8)
            profile["tempo_max"] = max(profile["tempo_min"], profile["tempo_max"] - 8)
    if re.search(r"\b(?:happier|more happy|more upbeat|more cheerful|more positive|more uplifting)\b", positive):
        profile["valence"] = clamp(prior["valence"] + step)
        profile["primary_mood"] = "happy"
    if re.search(r"\b(?:sadder|more melancholic|darker|less happy)\b", positive):
        profile["valence"] = clamp(prior["valence"] - step)
        profile["primary_mood"] = "melancholic"
    if "melancholic" in profile["avoid"]:
        profile["valence"] = max(profile["valence"], .58)
    if "sleepy" in profile["avoid"]:
        profile["energy"] = max(profile["energy"], .48)

    bpm_range = re.search(r"\b(\d{2,3})\s*(?:-|–|to|and)\s*(\d{2,3})\s*(?:bpm|beats per minute)\b", text)
    if bpm_range:
        low, high = map(int, bpm_range.groups())
        if 20 <= low <= high <= 300:
            profile.update(tempo_min=low, tempo_max=high, tempo_hard=True)
    else:
        upper = re.search(r"\b(?:under|below|at most|max(?:imum)?|up to)\s*(\d{2,3})\s*bpm\b", text)
        lower = re.search(r"\b(?:over|above|at least|min(?:imum)?)\s*(\d{2,3})\s*bpm\b", text)
        exact = re.search(r"\b(\d{2,3})\s*bpm\b", text)
        if upper and 20 <= int(upper.group(1)) <= 300:
            profile.update(tempo_min=20, tempo_max=int(upper.group(1)), tempo_hard=True)
        elif lower and 20 <= int(lower.group(1)) <= 300:
            profile.update(tempo_min=int(lower.group(1)), tempo_max=300, tempo_hard=True)
        elif exact and 20 <= int(exact.group(1)) <= 300:
            profile.update(tempo_min=int(exact.group(1)), tempo_max=int(exact.group(1)), tempo_hard=True)
    if re.search(r"\b(?:any tempo|remove (?:the )?bpm|no tempo limit)\b", text):
        profile.update(tempo_min=20, tempo_max=300, tempo_hard=False)

    decade = re.search(r"\b((?:19|20)\d0|[2-9]0)['’]?s\b", positive)
    year_range = re.search(r"\b((?:19|20)\d{2})\s*(?:-|–|to|through|and)\s*((?:19|20)\d{2})\b", positive)
    if year_range:
        first, last = map(int, year_range.groups())
        if first <= last:
            profile.update(release_year_min=first, release_year_max=last)
    elif decade:
        year = int(decade.group(1))
        if year < 100:
            year += 1900 if year >= 30 else 2000
        profile.update(release_year_min=year, release_year_max=year + 9)
    else:
        year = re.search(r"\b(?:from|in|released in)\s+((?:19|20)\d{2})\b", positive)
        if year:
            profile.update(release_year_min=int(year.group(1)), release_year_max=int(year.group(1)))
    if re.search(r"\b(?:any era|all eras|any decade|any year|remove (?:the )?(?:year|decade|era) (?:filter|constraint|limit))\b", positive):
        profile.update(release_year_min=None, release_year_max=None)

    profile["preferred_genres"] = [g for g in profile["preferred_genres"] if g not in profile["excluded_genres"]]
    if not initial and prior["primary_mood"] != profile["primary_mood"] and prior["primary_mood"] not in {"balanced", *profile["avoid"]}:
        profile["secondary_moods"] = union_unique(profile["secondary_moods"], [prior["primary_mood"]])[:10]
    profile["secondary_moods"] = [m for m in profile["secondary_moods"] if m not in profile["avoid"] and m != profile["primary_mood"]]
    if profile["primary_mood"] in profile["avoid"]:
        profile["primary_mood"] = "happy" if "melancholic" in profile["avoid"] else "balanced"
    profile["keywords"] = union_unique(profile["keywords"], [word for word in re.findall(r"[a-z]+", positive) if len(word) > 3 and word not in {"please", "music", "songs", "playlist", "make", "some", "more", "with", "want", "give"}])[-30:]
    return MoodProfile.model_validate(profile).model_dump()


def matches_constraints(track: dict, profile: dict) -> bool:
    genres = {canonical_genre(g) for g in track.get("genres", [])}
    excluded = {canonical_genre(g) for g in profile["excluded_genres"]}
    if genres & excluded:
        return False
    if profile["only_genres"] and not genres.intersection(profile["only_genres"]):
        return False
    artist = normalize(track.get("artist", ""))
    if any(normalize(excluded_artist) in artist for excluded_artist in profile["excluded_artists"] if normalize(excluded_artist)):
        return False
    if profile["tempo_hard"]:
        tempo = known_number(track, "tempo")
        if tempo is None or not profile["tempo_min"] <= tempo <= profile["tempo_max"]:
            return False
    release_year = known_number(track, "release_year")
    if profile["release_year_min"] is not None and (release_year is None or release_year < profile["release_year_min"]):
        return False
    if profile["release_year_max"] is not None and (release_year is None or release_year > profile["release_year_max"]):
        return False
    instrumental = known_number(track, "instrumentalness")
    if profile["only_instrumental"]:
        if instrumental is None or instrumental < .8:
            return False
    language = track.get("language", "unknown").lower()
    if language in profile["excluded_languages"]:
        return False
    if profile["languages"]:
        source = track.get("source", "")
        if language not in profile["languages"] and language != "instrumental":
            if language != "unknown" or source in {"local", "mock"}:
                return False
    if profile.get("require_clean") and track.get("explicit") is not False:
        return False
    if not profile["allow_explicit"] and track.get("explicit") is True:
        return False
    tags = set(track.get("mood_tags", []))
    requested_moods = {profile["primary_mood"], *profile["secondary_moods"]}
    if track.get("source") == "local" and tags and profile["primary_mood"] != "balanced" and not tags.intersection(requested_moods):
        return False
    if not tags.intersection(requested_moods) and profile["primary_mood"] != "balanced":
        conflicts = {
            "energetic": {"sleepy", "melancholic", "calm"},
            "happy": {"melancholic", "sleepy"},
            "calm": {"energetic", "aggressive"},
            "sleepy": {"energetic", "confident", "aggressive"},
            "focused": {"sleepy", "aggressive"},
        }.get(profile["primary_mood"], set())
        if tags.intersection(conflicts):
            return False
    if tags.intersection(profile["avoid"]):
        return False
    if "melancholic" in profile["avoid"]:
        valence = known_number(track, "valence")
        if valence is not None and valence < .4:
            return False
    if "sleepy" in profile["avoid"]:
        energy = known_number(track, "energy")
        if energy is not None and energy < .3:
            return False
    return True
