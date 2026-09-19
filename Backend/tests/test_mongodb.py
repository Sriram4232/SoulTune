"""Opt-in integration test using a uniquely named, disposable Mongo database."""
import os
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app import mail
from app.config import Settings
from app.main import create_app
from app.storage import MongoStore


@pytest.mark.skipif(os.getenv('RUN_MONGODB_TESTS') != '1', reason='Live MongoDB tests are opt-in')
def test_live_mongodb_otp_atomicity_and_collection_persistence(monkeypatch, tmp_path):
    name = 'ctest_' + uuid4().hex
    settings = Settings(mongodb_database=name, otp_secret='isolated-integration-test-secret-32-characters')
    if not settings.mongodb_uri:
        pytest.skip('No MongoDB connection configured')
    monkeypatch.setenv('GROQ_API_KEY', '')
    monkeypatch.setenv('LASTFM_API_KEY', '')
    monkeypatch.setenv('LOCAL_MUSIC_DIR', str(tmp_path / 'empty'))
    delivered = {}
    monkeypatch.setattr(mail, 'mail_ready', lambda config: True)
    monkeypatch.setattr(mail, 'send_otp', lambda config, email, code: delivered.update(code=code))
    store = MongoStore(settings.mongodb_uri, name)
    try:
        challenge = {'binding': 'browser', 'code_hash': 'hash', 'attempts': 0, 'consumed': False}
        store.put('otp', 'atomic-test', challenge, owner='atomic-test', expires_at=time.time() + 60)
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: store.consume_otp('atomic-test', 'browser', 'hash'), range(8)))
        assert sum(result is not None for result in results) == 1
        with TestClient(create_app(settings)) as client:
            response = client.post('/api/v1/auth/register', json={'name': 'Integration test', 'email': 'integration@example.test', 'password': 'Disposable-test-password-42'})
            assert response.status_code == 201 and response.json()['otp_required']
            assert client.get('/api/v1/auth/me').status_code == 401
            response = client.post('/api/v1/auth/verify-otp', json={'code': delivered['code']})
            assert response.status_code == 200
            client.headers['X-CSRF-Token'] = response.json()['csrf_token']
            assert client.get('/api/v1/playlists').json() == {'playlists': []}
            queue = client.post('/api/v1/queue/generate', json={'description': 'Happy road trip'}).json()
            collection = client.post('/api/v1/playlists', json={'name': 'Test collection'}).json()
            result = client.post('/api/v1/playlists/' + collection['id'] + '/tracks', json={'source_id': queue['id'], 'track_id': queue['tracks'][0]['id'], 'revision': collection['revision']})
            assert result.status_code == 200 and len(result.json()['tracks']) == 1
            assert client.patch('/api/v1/playlists/' + collection['id'], json={'name': 'Stale', 'revision': collection['revision']}).status_code == 409
            assert len(client.get('/api/v1/playlists').json()['playlists']) == 1
        # Verify data survives a new connection.
        assert len(store.get('playlist', collection['id'])['tracks']) == 1
    finally:
        assert name.startswith('ctest_') and len(name) == len('ctest_') + 32
        assert name != Settings().mongodb_database
        store.client.drop_database(name)
        store.close()
