import copy
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.storage import DuplicateUser, SQLiteStore


@pytest.fixture
def store(tmp_path):
    db = SQLiteStore(tmp_path / 'store.sqlite3')
    db.create_user({'id': 'u', 'email': 'one@example.com', 'password_hash': 'old', 'auth_version': 0, 'preferences': {}})
    return db


def test_atomic_password_rotation_is_not_overwritten_by_profile_update(store):
    assert store.rotate_password('u', 'new', 0)['auth_version'] == 1
    store.update_profile('u', {'name': 'Updated', 'preferences': {'genres': ['indie']}})
    assert store.get('user', 'u')['password_hash'] == 'new'
    assert store.rotate_password('u', 'stale-password', 0) is None
    assert store.get('user', 'u')['password_hash'] == 'new'


def test_stale_playlist_writes_cannot_overwrite_or_resurrect(store):
    first = {'id': 'p', 'owner_id': 'u', '_revision': 1, 'name': 'First'}
    assert store.save_playlist(first, 0)
    updated = {**first, '_revision': 2, 'name': 'Newer'}
    assert store.save_playlist(updated, 1)
    assert not store.save_playlist({**first, '_revision': 2, 'name': 'Stale'}, 1)
    assert store.get('playlist', 'p')['name'] == 'Newer'
    store.delete('playlist', 'p')
    assert not store.save_playlist(updated, 1)
    store.delete_user('u')
    assert not store.save_playlist(first, 0)


def test_concurrent_rate_limit_and_unique_account(store):
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: store.rate_limit('shared', 5, 60)[0], range(16)))
    assert sum(results) == 5
    with pytest.raises(DuplicateUser):
        store.create_user({'id': 'v', 'email': 'one@example.com'})


def test_concurrent_otp_is_only_consumed_once(store):
    challenge = {'binding': 'browser', 'code_hash': 'correct-hash', 'attempts': 0, 'consumed': False}
    store.put('otp', 'u', challenge, owner='u', expires_at=time.time() + 600)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: store.consume_otp('u', 'browser', 'correct-hash'), range(8)))
    assert sum(result is not None for result in results) == 1


def test_concurrent_incorrect_otp_guesses_stop_at_five(store):
    store.put('otp', 'u', {'binding': 'browser', 'code_hash': 'correct-hash', 'attempts': 0, 'consumed': False}, owner='u', expires_at=time.time() + 600)
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: store.consume_otp('u', 'browser', 'wrong-hash'), range(16)))
    assert store.get('otp', 'u')['attempts'] == 5
    assert store.consume_otp('u', 'browser', 'correct-hash') is None
