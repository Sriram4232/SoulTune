import asyncio
import copy
import json
from collections import Counter
from pathlib import Path

import httpx
import pytest

from app import engine, music


def test_catalogue_and_scoring_are_explainable():
    tracks = engine.mock_tracks()
    assert len(tracks) == 400 and len({t['id'] for t in tracks}) == 400
    assert all(t['source'] == 'mock' and t['preview_url'] is None for t in tracks)
    profile = engine.parse_description('A focused coding session with indie music, no rap and no sad songs')
    valid = [t for t in tracks if engine.matches_constraints(t, profile)]
    assert valid and all('hip-hop' not in t['genres'] and t['valence'] >= .4 for t in valid)
    scored = [engine.score_track(t, profile) for t in valid]
    for track in scored:
        expected = sum(engine.WEIGHTS[k] * v for k, v in track['score_breakdown'].items())
        assert track['score'] == pytest.approx(expected, abs=.0002)
        assert 'fictional' in track['explanation']
    selected = engine.diversify(scored, 15)
    assert max(Counter(t['artist'] for t in selected).values()) <= 2
    assert len({engine.track_identity(t) for t in selected}) == len(selected)


def test_preferences_and_refinements_retain_hard_constraints():
    profile = engine.parse_description('Focus, from the 80s, 90 to 120 BPM', preferences={
        'genres': ['jazz'], 'languages': ['english'], 'excluded_genres': ['rap'],
        'excluded_artists': ['Example Artist'], 'allow_explicit': False,
    })
    assert profile['preferred_genres'] == ['jazz']
    assert profile['release_year_min'] == 1980 and profile['release_year_max'] == 1989
    assert 'hip-hop' in profile['excluded_genres']
    refined = engine.parse_description('Make it happier and a little more energetic', profile)
    for key in ['languages', 'excluded_artists', 'excluded_genres', 'tempo_min', 'tempo_max', 'release_year_min', 'release_year_max']:
        assert refined[key] == profile[key]
    assert refined['energy'] > profile['energy'] and refined['valence'] > profile['valence']
    assert 'focused' in refined['secondary_moods']


def test_unknown_features_do_not_pass_strict_constraints():
    track = copy.deepcopy(engine.mock_tracks()[0])
    track.update(tempo=None, instrumentalness=None, language='unknown', release_year=None, explicit=None)
    for description in ['only instrumental', 'under 100 BPM', 'English songs', 'music from the 80s', 'clean music']:
        assert not engine.matches_constraints(track, engine.parse_description(description)), description


def test_disabling_personalization_keeps_exclusions_but_ignores_taste():
    profile = engine.parse_description('Something for this moment', preferences={
        'personalization': False, 'genres': ['metal'], 'languages': ['telugu'],
        'activities': ['workout'], 'excluded_artists': ['Skip Artist'], 'excluded_genres': ['rap'],
    })
    assert not profile['preferred_genres'] and not profile['languages']
    assert profile['activity'] == 'listening'
    assert profile['excluded_artists'] == ['skip artist'] and profile['excluded_genres'] == ['hip-hop']


def test_api_outage_preserves_local_playback_and_constraints(monkeypatch, tmp_path):
    monkeypatch.setenv('LOCAL_MUSIC_DIR', str(tmp_path))
    monkeypatch.setenv('GROQ_API_KEY', 'test-key')
    monkeypatch.setenv('LASTFM_API_KEY', 'test-key')
    track_path = tmp_path / 'Local Artist - Quiet Focus.mp3'
    track_path.write_bytes(b'Fixture: metadata discovery only')
    track_path.with_suffix('.json').write_text(json.dumps({
        'genres': ['indie'], 'mood_tags': ['focused'], 'energy': .55, 'valence': .6,
        'tempo': 100, 'explicit': False, 'language': 'english',
    }))
    class FailedClient:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def get(self, *args, **kwargs): raise httpx.ConnectError('Provider unreachable')
        async def post(self, *args, **kwargs): raise httpx.ReadTimeout('Provider timed out')
    monkeypatch.setattr(engine.httpx, 'AsyncClient', FailedClient)
    monkeypatch.setattr(engine, '_lastfm_cache', {})
    monkeypatch.setattr(engine, '_lastfm_circuit_until', 0)
    result = asyncio.run(engine.curate('Indie for coding, no rap', preferences={'allow_explicit': False}))
    assert result['parser'] == 'offline'
    local = [t for t in result['tracks'] if t['source'] == 'local']
    assert local and music.resolve_media(local[0]['id']) == track_path
    assert all('hip-hop' not in t['genres'] for t in result['tracks'])
    assert any('unavailable' in warning for warning in result['warnings'])


def test_invalid_groq_output_falls_back(monkeypatch):
    monkeypatch.setenv('GROQ_API_KEY', 'test-key')
    class InvalidClient:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, *args, **kwargs):
            return httpx.Response(200, json={'choices': [{'message': {'content': '{"energy":999}'}}]}, request=httpx.Request('POST', 'https://test.invalid'))
    monkeypatch.setattr(engine.httpx, 'AsyncClient', InvalidClient)
    profile, parser, warnings = asyncio.run(engine.parse_profile('focused coding, no rap', None, None))
    assert parser == 'offline' and 'hip-hop' in profile['excluded_genres'] and warnings


def test_local_media_rejects_arbitrary_paths_and_ignores_bad_sidecars(monkeypatch, tmp_path):
    monkeypatch.setenv('LOCAL_MUSIC_DIR', str(tmp_path))
    (tmp_path / 'Song.mp3').write_bytes(b'fixture')
    (tmp_path / 'Song.json').write_text('{bad json')
    (tmp_path / 'private.txt').write_text('secret')
    tracks = music.list_local_tracks()
    assert len(tracks) == 1 and tracks[0]['energy'] is None
    for identifier in ['../../private.txt', str(tmp_path / 'private.txt'), 'local_' + '0' * 24]:
        assert music.resolve_media(identifier) is None


def test_download_folder_tags_and_real_catalogue_selection(monkeypatch, tmp_path):
    monkeypatch.setenv('LOCAL_MUSIC_DIR', str(tmp_path))
    monkeypatch.delenv('GROQ_API_KEY', raising=False)
    monkeypatch.delenv('LASTFM_API_KEY', raising=False)
    monkeypatch.delenv('SPOTIFY_CLIENT_ID', raising=False)
    monkeypatch.delenv('SPOTIFY_CLIENT_SECRET', raising=False)
    for folder, title in [('Energetic songs', 'Power'), ('sad songs', 'Heartbreak')]:
        directory = tmp_path / folder
        directory.mkdir()
        (directory / f'Artist - {title}.mp3').write_bytes(b'metadata fixture')
    tracks = music.rescan_library()
    assert next(track for track in tracks if track['title'] == 'Power')['mood_tags'] == ['energetic']
    result = asyncio.run(engine.curate('An energetic workout, no heavy music', preferences={'allow_explicit': False}))
    assert [track['title'] for track in result['tracks']] == ['Power']
    assert result['tracks'][0]['energy'] is None and result['tracks'][0]['source'] == 'local'
    assert 'metal' in result['profile']['excluded_genres']


def test_clean_request_is_strict_but_default_rating_filter_allows_unknown():
    track = copy.deepcopy(engine.mock_tracks()[0])
    track['explicit'] = None
    assert engine.matches_constraints(track, engine.parse_description('Music for this moment', preferences={'allow_explicit': False}))
    assert not engine.matches_constraints(track, engine.parse_description('Clean music'))
    track['explicit'] = True
    assert not engine.matches_constraints(track, engine.parse_description('Music for this moment', preferences={'allow_explicit': False}))


def test_refinement_can_restore_a_mood_and_just_a_little_is_not_genre_only():
    prior = engine.parse_description('Relaxing music, no sad songs')
    refined = engine.parse_description('Actually make it sad with just a little more indie', prior)
    assert refined['primary_mood'] == 'melancholic'
    assert 'melancholic' not in refined['avoid']
    assert not refined['only_genres']


def test_retired_groq_model_uses_alternate_and_preserves_missing_fields(monkeypatch):
    monkeypatch.setenv('GROQ_API_KEY', 'fixture-key')
    monkeypatch.setenv('GROQ_MODEL', 'retired-model')
    monkeypatch.setenv('GROQ_FALLBACK_MODEL', 'openai/gpt-oss-20b')
    monkeypatch.setattr(engine, '_groq_model_cache', {})
    models = []
    class ModelClient:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, url, **kwargs):
            model = kwargs['json']['model']
            models.append(model)
            payload = {'error': {'code': 'model_not_found'}} if model == 'retired-model' else {'choices': [{'message': {'content': '{"primary_mood":"focused"}'}}]}
            return httpx.Response(404 if model == 'retired-model' else 200, json=payload, request=httpx.Request('POST', url))
    monkeypatch.setattr(engine.httpx, 'AsyncClient', ModelClient)
    profile, parser, warnings = asyncio.run(engine.parse_profile('Coding, no rap, 90 to 120 BPM', None, None))
    assert models == ['retired-model', 'openai/gpt-oss-20b']
    assert parser == 'groq' and warnings
    assert profile['activity'] == 'coding' and profile['tempo_min'] == 90
    assert 'hip-hop' in profile['excluded_genres']
