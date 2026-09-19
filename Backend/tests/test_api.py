"""End-to-end API contracts, privacy boundaries, and real local-audio fallback."""
import csv
import io
import json
import time
import wave

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app import mail
from app.security import token_hash

API = '/api/v1'
SENT_CODES = {}

@pytest.fixture(autouse=True)
def email_delivery(monkeypatch):
    SENT_CODES.clear()
    monkeypatch.setattr(mail, 'mail_ready', lambda config: True)
    monkeypatch.setattr(mail, 'send_otp', lambda config, email, code: SENT_CODES.__setitem__(email, code))
    monkeypatch.setenv('OTP_SECRET', 'test-only-secret-never-used-in-production-42')


def verify_email(client, email='listener@example.com'):
    response = client.post(API + '/auth/verify-otp', json={'code': SENT_CODES[email]})
    assert response.status_code == 200, response.text
    client.headers['X-CSRF-Token'] = response.json()['csrf_token']
    return response



@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv('LOCAL_MUSIC_DIR', str(tmp_path / 'music'))
    monkeypatch.delenv('GROQ_API_KEY', raising=False)
    monkeypatch.delenv('LASTFM_API_KEY', raising=False)
    return create_app(Settings(database_path=tmp_path / 'test.sqlite3', mongodb_uri=''))


@pytest.fixture
def client(app):
    with TestClient(app) as session:
        yield session


def guest(client):
    response = client.post(API + '/auth/guest')
    assert response.status_code == 201, response.text
    client.headers['X-CSRF-Token'] = response.json()['csrf_token']
    return response.json()


def register(client, email='listener@example.com'):
    response = client.post(API + '/auth/register', json={
        'name': 'Listener', 'email': email, 'password': 'A-long-password-42',
    })
    assert response.status_code == 201, response.text
    assert response.json()['otp_required'] is True
    return verify_email(client, email)


def generate(client, description='Rainy evening coding, focused but not sleepy, indie and lofi'):
    response = client.post(API + '/playlists/generate', json={'description': description, 'playlist_size': 15})
    assert response.status_code == 201, response.text
    return response.json()


def test_login_has_identical_unknown_user_and_bad_password_errors(client):
    register(client)
    client.post(API + '/auth/logout')
    wrong_password = client.post(API + '/auth/login', json={'email': 'listener@example.com', 'password': 'incorrect'})
    wrong_user = client.post(API + '/auth/login', json={'email': 'missing@example.com', 'password': 'incorrect'})
    assert wrong_password.status_code == wrong_user.status_code == 401
    assert wrong_password.json() == wrong_user.json() == {'detail': 'Credentials are incorrect.'}
    assert 'set-cookie' not in wrong_password.headers


def test_cookie_password_storage_and_session_revocation(client, app):
    response = register(client)
    cookie = response.headers['set-cookie'].lower()
    assert 'httponly' in cookie and 'samesite=lax' in cookie and 'max-age=' in cookie
    user = response.json()['user']
    assert 'password_hash' not in user
    stored = app.state.store.get('user', user['id'])
    assert stored['password_hash'].startswith('scrypt$')
    assert 'A-long-password-42' not in stored['password_hash']
    token = client.cookies.get('curator_session')
    assert client.post(API + '/auth/logout').status_code == 200
    client.cookies.set('curator_session', token)
    assert client.get(API + '/auth/me').status_code == 401


def test_expired_session_is_rejected(client, app):
    guest(client)
    key = token_hash(client.cookies.get('curator_session'))
    session = app.state.store.get('session', key)
    session['expires_at'] = time.time() - 1
    app.state.store.put('session', key, session, owner=session['user_id'], expires_at=session['expires_at'])
    assert client.get(API + '/auth/me').status_code == 401


def test_csrf_origin_validation_and_request_size(client):
    auth = guest(client)
    client.headers.pop('X-CSRF-Token')
    assert client.put(API + '/profile', json={'name': 'Changed'}).status_code == 403
    client.headers['X-CSRF-Token'] = auth['csrf_token']
    assert client.put(API + '/profile', json={'name': 'Changed'}, headers={'Origin': 'https://attacker.invalid'}).status_code == 403
    assert client.post(API + '/auth/login', json={'email': 'x', 'password': 'x'}, headers={'Origin': 'https://attacker.invalid'}).status_code == 403
    response = client.post(API + '/playlists/generate', content='x' * 40000, headers={'Content-Type': 'application/json'})
    assert response.status_code == 413


def test_input_validation_never_echoes_password(client):
    response = client.post(API + '/auth/register', json={'name': 'A', 'email': 'invalid', 'password': 'secret'})
    assert response.status_code == 422
    assert 'secret' not in response.text
    guest(client)
    assert client.post(API + '/playlists/generate', json={'description': '   ', 'playlist_size': 99}).status_code == 422
    assert client.put(API + '/profile', json={'is_admin': True}).status_code == 422


def test_generation_refinement_history_export_and_save(client):
    guest(client)
    playlist = generate(client)
    assert 10 <= len(playlist['tracks']) <= 20
    assert playlist['version'] == 1 and len(playlist['messages']) == 2
    assert len({track['id'] for track in playlist['tracks']}) == len(playlist['tracks'])
    assert all(0 <= track['score'] <= 1 and track['explanation'] for track in playlist['tracks'])
    url = API + '/playlists/' + playlist['id']
    response = client.post(url + '/refine', json={'message': 'Make it happier and slightly more energetic, no rap'})
    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated['version'] == 2 and len(updated['messages']) == 4
    assert updated['description'] == playlist['description']
    assert updated['profile']['energy'] > playlist['profile']['energy']
    assert updated['profile']['valence'] > playlist['profile']['valence']
    assert updated['profile']['activity'] == playlist['profile']['activity']
    assert client.patch(url, json={'name': 'My focus queue', 'revision': updated['revision']}).json()['name'] == 'My focus queue'
    assert client.patch(url, json={'saved': True}).status_code == 400
    history = client.get(API + '/sessions/' + playlist['session_id'] + '/history').json()
    assert len(history['messages']) == 4
    assert client.get(url + '/export?format=json').json()['id'] == playlist['id']
    csv_response = client.get(url + '/export?format=csv')
    assert csv_response.status_code == 200 and 'attachment;' in csv_response.headers['content-disposition']
    assert len(list(csv.reader(io.StringIO(csv_response.text.lstrip('\ufeff'))))) == len(updated['tracks']) + 1
    assert client.get(API + '/playlists').json()['playlists'] == []
    assert client.get(API + '/queue').json()['queue']['id'] == playlist['id']


def test_user_cannot_read_mutate_export_or_refine_another_users_playlist(client):
    guest(client)
    playlist = generate(client)
    client.cookies.clear()
    guest(client)
    url = API + '/playlists/' + playlist['id']
    assert client.get(url).status_code == 404
    assert client.patch(url, json={'saved': True}).status_code == 404
    assert client.delete(url).status_code == 404
    assert client.get(url + '/export?format=json').status_code == 404
    assert client.post(url + '/refine', json={'message': 'Happier'}).status_code == 404
    assert client.get(API + '/sessions/' + playlist['session_id'] + '/history').status_code == 404
    assert client.get(API + '/playlists').json() == {'playlists': []}


def test_profile_survives_signout_and_restart(tmp_path, monkeypatch):
    settings = Settings(database_path=tmp_path / 'persistent.sqlite3', mongodb_uri='')
    with TestClient(create_app(settings)) as client:
        register(client)
        assert client.put(API + '/profile', json={'name': 'A music fan', 'preferences': {'languages': ['telugu'], 'playlist_size': 12}, 'onboarding_completed': True}).status_code == 200
        client.post(API + '/auth/logout')
    later = time.time() + 61
    monkeypatch.setattr(time, 'time', lambda: later)
    with TestClient(create_app(settings)) as client:
        response = client.post(API + '/auth/login', json={'email': 'listener@example.com', 'password': 'A-long-password-42'})
        assert response.status_code == 200
        user = verify_email(client).json()['user']
        assert user['name'] == 'A music fan'
        assert user['preferences']['languages'] == ['telugu']
        assert user['onboarding_completed'] is True


def test_password_change_rotates_session_and_account_delete_removes_data(client, app):
    register(client)
    playlist = generate(client)
    old_token = client.cookies.get('curator_session')
    response = client.post(API + '/auth/change-password', json={'current_password': 'A-long-password-42', 'new_password': 'A-new-password-42'})
    assert response.status_code == 200
    assert client.cookies.get('curator_session') != old_token
    assert app.state.store.get('session', token_hash(old_token)) is None
    client.headers['X-CSRF-Token'] = response.json()['csrf_token']
    assert client.request('DELETE', API + '/account', json={'password': 'A-new-password-42'}).status_code == 200
    assert app.state.store.get('playlist', playlist['id']) is None
    assert client.get(API + '/auth/me').status_code == 401


def test_actual_audio_scanning_range_and_no_path_traversal(client, tmp_path):
    root = tmp_path / 'music'
    root.mkdir()
    audio_file = root / 'Test Artist - Focus.wav'
    with wave.open(str(audio_file), 'wb') as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(8000)
        stream.writeframes(b'\x00\x00' * 8000)
    audio_file.with_suffix('.json').write_text(json.dumps({'genres': ['lofi'], 'energy': 0.5, 'explicit': False, 'mood_tags': ['focused'], 'language': 'instrumental'}))
    (root / 'secret.txt').write_text('private')
    assert client.get(API + '/library').status_code == 401
    guest(client)
    tracks = client.post(API + '/library/rescan').json()['tracks']
    assert len(tracks) == 1 and tracks[0]['title'] == 'Focus'
    assert tracks[0]['source'] == 'local' and str(tmp_path) not in json.dumps(tracks)
    response = client.get(tracks[0]['preview_url'], headers={'Range': 'bytes=0-43'})
    assert response.status_code == 206
    assert response.content[:4] == b'RIFF' and len(response.content) == 44
    assert client.get(API + '/media/secret.txt').status_code == 404
    audio_file.unlink()
    assert client.get(tracks[0]['preview_url']).status_code == 404


def test_csv_formula_injection_is_escaped(client, app):
    guest(client)
    playlist = generate(client)
    stored = app.state.store.get('playlist', playlist['id'])
    stored['tracks'][0]['title'] = '=1+1'
    app.state.store.put('playlist', playlist['id'], stored, owner=stored['owner_id'])
    response = client.get(API + '/playlists/' + playlist['id'] + '/export?format=csv')
    rows = list(csv.reader(io.StringIO(response.text.lstrip('\ufeff'))))
    assert rows[1][1] == "'=1+1"


def test_login_rate_limit_is_enforced(client):
    for _ in range(10):
        assert client.post(API + '/auth/login', json={'email': 'unknown@example.com', 'password': 'bad'}).status_code == 401
    response = client.post(API + '/auth/login', json={'email': 'unknown@example.com', 'password': 'bad'})
    assert response.status_code == 429 and int(response.headers['retry-after']) > 0


def test_otp_required_single_use_browser_bound_and_no_default_playlist(client, app):
    response = client.post(API + '/auth/register', json={'name': 'Listener', 'email': 'listener@example.com', 'password': 'A-long-password-42'})
    assert response.json()['otp_required'] is True
    assert 'curator_session' not in client.cookies
    assert client.get(API + '/auth/me').status_code == 401
    code = SENT_CODES['listener@example.com']
    assert code not in response.text
    binding_cookie = client.cookies.get('curator_login')
    with TestClient(app) as stranger:
        assert stranger.post(API + '/auth/verify-otp', json={'code': code}).status_code == 400
    verified = verify_email(client)
    assert verified.json()['user']['email'] == 'listener@example.com'
    assert client.get(API + '/playlists').json() == {'playlists': []}
    assert client.get(API + '/queue').json() == {'queue': None}
    assert client.get(API + '/saved-songs').json() == {'tracks': []}
    client.cookies.set('curator_login', binding_cookie, path=API + '/auth')
    assert client.post(API + '/auth/verify-otp', json={'code': code}).status_code == 400


def test_otp_attempt_limit_expiry_resend_and_password_change(client, app, monkeypatch):
    client.post(API + '/auth/register', json={'name': 'Listener', 'email': 'listener@example.com', 'password': 'A-long-password-42'})
    code = SENT_CODES['listener@example.com']
    wrong = '000000' if code != '000000' else '999999'
    for _ in range(5):
        assert client.post(API + '/auth/verify-otp', json={'code': wrong}).status_code == 400
    assert client.post(API + '/auth/verify-otp', json={'code': code}).status_code == 400
    assert client.post(API + '/auth/resend-otp').status_code == 429
    now = time.time() + 61
    monkeypatch.setattr(time, 'time', lambda: now)
    old_cookie = client.cookies.get('curator_login')
    assert client.post(API + '/auth/resend-otp').status_code == 200
    new_cookie = client.cookies.get('curator_login')
    assert old_cookie != new_cookie
    user = app.state.store.user_by_email('listener@example.com')
    challenge = app.state.store.get('otp', user['id'])
    assert challenge['attempts'] == 0
    assert 'code' not in challenge and SENT_CODES['listener@example.com'] not in str(challenge)
    now += 601
    assert client.post(API + '/auth/verify-otp', json={'code': SENT_CODES['listener@example.com']}).status_code == 400


def test_mail_failure_never_creates_authenticated_session(client, app, monkeypatch):
    monkeypatch.setattr(mail, 'mail_ready', lambda config: False)
    assert client.post(API + '/auth/register', json={'name': 'Listener', 'email': 'listener@example.com', 'password': 'A-long-password-42'}).status_code == 503
    assert app.state.store.user_by_email('listener@example.com') is None
    assert client.get(API + '/auth/me').status_code == 401
    monkeypatch.setattr(mail, 'mail_ready', lambda config: True)
    def fail(*args):
        raise mail.MailUnavailable('Delivery unavailable.')
    monkeypatch.setattr(mail, 'send_otp', fail)
    assert client.post(API + '/auth/register', json={'name': 'Listener', 'email': 'listener@example.com', 'password': 'A-long-password-42'}).status_code == 503
    assert 'curator_session' not in client.cookies
    user = app.state.store.user_by_email('listener@example.com')
    assert app.state.store.get('otp', user['id']) is None


def test_login_after_password_verification_still_requires_otp(client, app, monkeypatch):
    register(client)
    client.post(API + '/auth/logout')
    later = time.time() + 61
    monkeypatch.setattr(time, 'time', lambda: later)
    response = client.post(API + '/auth/login', json={'email': 'listener@example.com', 'password': 'A-long-password-42'})
    assert response.json()['otp_required']
    assert client.get(API + '/playlists').status_code == 401
    verify_email(client)
    assert client.get(API + '/playlists').json() == {'playlists': []}


def test_one_queue_named_collections_saved_songs_and_track_removal(client):
    guest(client)
    first = generate(client, 'Energetic music for a workout')
    song = first['tracks'][0]
    collection = client.post(API + '/playlists', json={'name': 'My favorites'}).json()
    assert collection['tracks'] == [] and collection['kind'] == 'collection'
    added = client.post(API + '/playlists/' + collection['id'] + '/tracks', json={
        'source_id': first['id'], 'track_id': song['id'], 'revision': collection['revision'],
    }).json()
    assert len(added['tracks']) == 1
    assert client.post(API + '/saved-songs', json={'source_id': first['id'], 'track_id': song['id']}).status_code == 201
    second = generate(client, 'Soft acoustic relaxing music')
    assert second['id'] == first['id'] and len(second['messages']) == 2
    assert second['description'] != first['description']
    collections = client.get(API + '/playlists').json()['playlists']
    assert len(collections) == 1 and collections[0]['tracks'][0]['id'] == song['id']
    assert client.get(API + '/saved-songs').json()['tracks'][0]['id'] == song['id']
    removed = client.post(API + '/playlists/' + collection['id'] + '/feedback', json={'track_id': song['id'], 'feedback': 'remove', 'revision': added['revision']}).json()
    assert removed['tracks'] == []
    # A saved song remains addable after the mood queue has changed.
    assert client.post(API + '/playlists/' + collection['id'] + '/tracks', json={'track_id': song['id'], 'revision': removed['revision']}).status_code == 200
    client.delete(API + '/playlists/' + collection['id'])
    assert client.get(API + '/saved-songs').json()['tracks']
    assert client.delete(API + '/saved-songs/' + song['id']).status_code == 200
    assert client.get(API + '/saved-songs').json()['tracks'] == []


def test_queue_hide_survives_refinement_and_stale_mutation_is_rejected(client):
    guest(client)
    queue = generate(client)
    url = API + '/playlists/' + queue['id']
    song = queue['tracks'][0]['id']
    hidden = client.post(url + '/feedback', json={'track_id': song, 'feedback': 'dislike', 'revision': queue['revision']}).json()
    assert song not in [track['id'] for track in hidden['tracks']]
    assert client.patch(url, json={'name': 'Stale name', 'revision': queue['revision']}).status_code == 409
    refined = client.post(url + '/refine', json={'message': 'More energetic', 'revision': hidden['revision']}).json()
    assert song not in [track['id'] for track in refined['tracks']]
    scores = [track['score'] for track in refined['tracks']]
    assert scores == sorted(scores, reverse=True)


def test_queue_creation_retry_is_idempotent_and_other_accounts_are_empty(client):
    from uuid import uuid4
    guest(client)
    body = {'description': 'Happy road trip', 'request_id': str(uuid4())}
    first = client.post(API + '/queue/generate', json=body).json()
    retry = client.post(API + '/queue/generate', json=body).json()
    assert first['id'] == retry['id'] and first['revision'] == retry['revision']
    assert client.post(API + '/queue/generate', json={**body, 'description': 'A different request'}).status_code == 409
    client.cookies.clear()
    guest(client)
    assert client.get(API + '/queue').json() == {'queue': None}
    assert client.get(API + '/playlists').json() == {'playlists': []}
    assert client.post(API + '/saved-songs', json={'source_id': first['id'], 'track_id': first['tracks'][0]['id']}).status_code == 404
