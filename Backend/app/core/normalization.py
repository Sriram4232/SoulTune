"""Text, genre, and mood normalization utilities."""
from __future__ import annotations

import re
import unicodedata
from typing import Any

GENRES: dict[str, list[str]] = {
    "lofi": ["lofi", "lo-fi", "lo fi"],
    "indie": ["indie"],
    "ambient": ["ambient"],
    "electronic": ["electronic", "electronica", "edm"],
    "jazz": ["jazz"],
    "classical": ["classical", "orchestral"],
    "pop": ["pop"],
    "rock": ["rock"],
    "hip-hop": ["hip-hop", "hip hop", "rap"],
    "r&b": ["r&b", "rnb", "rhythm and blues"],
    "folk": ["folk"],
    "acoustic": ["acoustic"],
    "soul": ["soul"],
    "metal": ["metal"],
    "house": ["house"],
    "techno": ["techno"],
    "reggae": ["reggae"],
    "country": ["country"],
    "bollywood": ["bollywood"],
    "tollywood": ["tollywood", "telugu film", "telugu movies"],
    "kollywood": ["kollywood", "tamil film", "tamil movies"],
    "k-pop": ["k-pop", "kpop"],
    "latin": ["latin", "reggaeton"],
    "blues": ["blues"],
}

MOODS: dict[str, list[str]] = {
    "focused": ["focused", "focus", "concentrate", "concentration", "productive"],
    "calm": ["calm", "relaxed", "relaxing", "relax", "chill", "peaceful", "gentle", "mellow", "melody", "melodic"],
    "happy": ["happy", "happier", "joyful", "cheerful", "uplifting", "positive", "upbeat"],
    "energetic": ["energetic", "energy", "intense", "hype", "pumped", "powerful", "upbeat", "mass", "mass songs", "mass hits", "party songs", "high energy"],
    "melancholic": ["sad", "sadness", "melancholic", "melancholy", "heartbroken", "heartbreak", "blue"],
    "dreamy": ["dreamy", "atmospheric", "ethereal", "floating"],
    "romantic": ["romantic", "romance", "love", "love songs"],
    "nostalgic": ["nostalgic", "nostalgia", "throwback", "retro"],
    "sleepy": ["sleepy", "sleep", "sleeping", "bedtime", "drowsy"],
    "confident": ["confident", "confidence", "bold", "empowered"],
}

MASS_INDICATORS: set[str] = {"mass", "mass songs", "mass hits", "high energy", "pumped", "powerful", "intense"}

ACTIVITIES: dict[str, tuple] = {
    "coding": (["coding", "code", "programming", "developer"], .52, .52, .28, .80, 80, 125, ["lofi", "indie", "ambient"], "focused"),
    "studying": (["study", "studying", "reading", "homework", "exam", "working", "work", "deep work"], .38, .50, .20, .88, 65, 110, ["lofi", "classical", "ambient"], "focused"),
    "workout": (["workout", "gym", "exercise", "training", "lifting", "running", "run"], .86, .72, .75, .25, 115, 175, ["electronic", "rock", "hip-hop"], "energetic"),
    "party": (["party", "dancing", "dance", "celebrate", "celebration"], .82, .85, .88, .20, 110, 145, ["pop", "house", "electronic"], "happy"),
    "driving": (["drive", "driving", "road trip", "roadtrip", "commute"], .65, .65, .58, .35, 90, 140, ["indie", "rock", "pop"], "confident"),
    "relaxing": (["unwind", "relax", "relaxing", "chill", "sunset", "rain", "rainy"], .32, .55, .30, .60, 60, 105, ["acoustic", "jazz", "lofi"], "calm"),
    "sleeping": (["sleep", "sleeping", "bedtime", "fall asleep"], .15, .48, .12, .95, 40, 85, ["ambient", "classical"], "sleepy"),
    "meditating": (["meditation", "meditate", "meditating", "yoga", "breathing"], .18, .56, .12, .95, 40, 85, ["ambient", "classical"], "calm"),
}

LANGUAGES: set[str] = {
    "english", "hindi", "tamil", "telugu", "punjabi", "bengali", "malayalam",
    "kannada", "marathi", "spanish", "korean", "japanese", "french", "german", "portuguese", "arabic"
}

GLOBAL_DIVERSE_LANGUAGES: list[str] = [
    "english", "hindi", "spanish", "telugu", "tamil", "punjabi", "korean", "japanese", "french"
]

MOOD_VALUES: dict[str, tuple[float, float]] = {
    "focused": (.50, .52),
    "calm": (.30, .56),
    "happy": (.67, .85),
    "energetic": (.84, .70),
    "melancholic": (.35, .25),
    "dreamy": (.34, .56),
    "romantic": (.40, .70),
    "nostalgic": (.48, .56),
    "sleepy": (.14, .45),
    "confident": (.75, .76)
}


def normalize(value: Any) -> str:
    return re.sub(r"[^\w\s]", " ", unicodedata.normalize("NFKC", str(value)).casefold()).strip()


def contains_term(text: str, term: str) -> bool:
    return re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", text) is not None


def canonical_genre(genre: str) -> str:
    value = genre.strip().lower()
    return next((key for key, aliases in GENRES.items() if value in aliases), value)


def title_case(s: str) -> str:
    return s.replace("-", " ").title() if s else s


def clamp(value: float) -> float:
    return round(max(0.0, min(1.0, value)), 3)


def union_unique(current: list, values: list) -> list:
    return list(dict.fromkeys([*current, *values]))


def extract_negative_clauses(text: str) -> tuple[str, list[str]]:
    positive = text
    clauses = []
    pattern = r"\b(?:no|not|without|avoid|excluding|exclude|remove|skip|don't want|do not want)\s+([^.!?;]+)"
    for match in reversed(list(re.finditer(pattern, text))):
        clause = re.split(r"\b(?:but|with|instead|then|add|include|make|give|more|please)\b", match.group(1), maxsplit=1)[0].strip(" ,")
        if clause:
            clauses.append(clause)
            end = match.start(1) + len(clause)
            positive = positive[:match.start()] + " " * (end - match.start()) + positive[end:]
    return positive, clauses
