"""Reproduce the 400 deliberately fictional metadata-only demo records.

These values illustrate the ranker; they are not measured acoustic features,
real recordings, or a claim that any music service carries these songs.
"""

import json
import random
from pathlib import Path

GENRES = [
    ("lofi", .40, .53, .43, .95, 87), ("indie", .57, .59, .50, .16, 112),
    ("ambient", .19, .51, .16, .98, 64), ("electronic", .76, .68, .80, .65, 128),
    ("jazz", .43, .58, .47, .88, 101), ("classical", .35, .53, .20, .99, 89),
    ("pop", .69, .77, .77, .10, 118), ("rock", .79, .60, .52, .10, 130),
    ("hip-hop", .74, .60, .82, .08, 98), ("r&b", .49, .62, .70, .12, 94),
    ("folk", .40, .58, .35, .15, 96), ("acoustic", .31, .64, .35, .45, 91),
    ("soul", .53, .70, .62, .12, 108), ("metal", .92, .44, .39, .12, 157),
    ("house", .77, .72, .88, .77, 125), ("techno", .84, .60, .83, .96, 134),
    ("reggae", .55, .78, .74, .15, 90), ("country", .52, .61, .46, .12, 112),
    ("bollywood", .64, .70, .74, .11, 119), ("k-pop", .76, .80, .82, .09, 128),
]
ADJECTIVES = ["Amber", "Velvet", "Silver", "Quiet", "Neon", "Paper", "Golden", "Hidden", "Midnight", "Open", "Distant", "Soft", "Electric", "Tender", "Lucid", "Crimson", "Misty", "Slow", "Crystal", "Violet"]
NOUNS = ["Window", "Horizon", "Signal", "Tide", "Skyline", "Satellite", "Garden", "Current", "Letter", "Daylight", "Echo", "Orbit", "Morning", "Memory", "Avenue", "River", "Motion", "Cloud", "Rhythm", "Field"]
ARTISTS = ["Juniper Theory", "North Window", "Moonwell", "Hollow Maps", "Amber Cinema", "Paper Pilot", "Soft Coordinates", "Violet Circuit", "Glass Meadow", "Slow Almanac", "Parallel Atlas", "Quiet Harbour", "Neon Orchard", "Silver Season", "Warm Frequency", "Hidden Coast", "Moss Signal", "Dawn Index", "Distant Rooms", "Velvet Transit"]


def build_catalog() -> list[dict]:
    randomizer = random.Random(271828)
    tracks = []
    for genre_index, (genre, energy, valence, dance, instrumental, tempo) in enumerate(GENRES):
        for index in range(20):
            # Each genre has both low/high moods and recordings across decades.
            e = round(min(.99, max(.05, energy + randomizer.uniform(-.22, .18))), 2)
            v = round(min(.99, max(.05, valence + randomizer.uniform(-.38, .21))), 2)
            inst = round(min(1, max(0, instrumental + randomizer.uniform(-.12, .08))), 2)
            mood = ["energetic" if e >= .68 else "calm" if e < .43 else "focused"]
            mood.append("happy" if v >= .67 else "melancholic" if v < .40 else "dreamy")
            if genre in {"lofi", "ambient", "classical", "jazz"}:
                mood.append("focused")
            if e < .27:
                mood.append("sleepy")
            if index % 4 == 0:
                mood.append("nostalgic")
            if index % 7 == 0:
                mood.append("romantic")
            activities = []
            if inst >= .7 and .25 <= e <= .68:
                activities += ["coding", "studying"]
            if e > .66:
                activities += ["workout", "party"]
            if e < .25:
                activities += ["sleeping", "meditating"]
            if e < .55:
                activities.append("relaxing")
            if .42 < e < .83:
                activities.append("driving")
            language = "instrumental" if inst >= .8 else "hindi" if genre == "bollywood" else "korean" if genre == "k-pop" else ["english", "english", "hindi", "spanish", "english", "tamil", "punjabi"][index % 7]
            tracks.append({
                "id": f"demo_{genre_index * 20 + index + 1:04d}",
                "title": f"{ADJECTIVES[index]} {NOUNS[(index + genre_index * 3) % 20]}",
                "artist": f"{ARTISTS[(index // 2 + genre_index * 3) % 20]} {genre_index + 1:02d}",
                "album": f"Illustrative {genre.title()} Sessions",
                "genres": [genre], "mood_tags": list(dict.fromkeys(mood)), "activity_tags": activities,
                "tempo": round(tempo + randomizer.uniform(-22, 22)), "energy": e, "valence": v,
                "danceability": round(min(1, max(0, dance + randomizer.uniform(-.15, .15))), 2),
                "instrumentalness": inst, "popularity": round(randomizer.uniform(.15, .95), 2),
                "release_year": [1981, 1984, 1987, 1989, 1992, 1995, 1998, 2001, 2003, 2005, 2007, 2009, 2011, 2014, 2017, 2019, 2021, 2023, 2024, 2025][index],
                "language": language, "duration_seconds": randomizer.randrange(155, 336),
                "explicit": index % 6 == 0 and genre in {"hip-hop", "rock", "metal", "r&b"},
                "image_url": None, "preview_url": None, "external_url": None, "source": "mock",
                "metadata_notes": "Fictional demo song and artist. All features are synthetic illustration values; no audio is provided.",
            })
    return tracks


if __name__ == "__main__":
    destination = Path(__file__).with_name("mock_tracks.json")
    destination.write_text(json.dumps(build_catalog(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote 400 fictional demo records to {destination.name}")
