"""Imported mode must never instantiate native adapters or execute retained jobs."""
import json
import pytest
from backend.store import Store
from backend.background.service import BackgroundService


def test_imported_mode_does_not_start_or_expire(tmp_path, monkeypatch):
    monkeypatch.delenv('TRAVEL_ENABLE_LIVE_COLLECTION', raising=False)
    store = Store(tmp_path / 'imported')
    (store.root / 'imported-installation.json').write_text('{}')
    job = store.put('background_jobs', {'state': 'RUNNING', 'source_id': 'detached', 'mode': 'history'}, 'old-job')
    service = BackgroundService(store)
    monkeypatch.setattr(service.pipeline, 'expire', lambda: pytest.fail('Imported data must not expire on startup'))
    service.start()
    assert service.thread is None and service._adapter is None
    assert store.get('background_jobs', job['id'])['state'] == 'RUNNING'
    assert service.summary()['live_collection_enabled'] is False
    for operation in (service.bind, lambda: service.create_job({'source_id': 'detached'}), lambda: service.run_once(job['id']),
                      lambda: service.action(job['id'], 'resume')):
        with pytest.raises(ValueError, match='LIVE_COLLECTION_DISABLED'):
            operation()
    assert service._adapter is None


def test_live_collection_requires_opt_in_and_fresh_local_fields(tmp_path, monkeypatch):
    store = Store(tmp_path / 'new')
    path = store.root / 'live-binding.json'
    config = {'fresh_local_binding': True, 'account_native_id': 'local-account', 'account_display_name': '本机账号',
              'friend_native_id': 'local-source', 'friend_display_name': '本机来源'}
    path.write_text(json.dumps(config), encoding='utf-8')
    monkeypatch.delenv('TRAVEL_ENABLE_LIVE_COLLECTION', raising=False)
    assert not BackgroundService(store).collection_enabled
    monkeypatch.setenv('TRAVEL_ENABLE_LIVE_COLLECTION', '1')
    service = BackgroundService(store)
    assert service.collection_enabled
    assert service.expected_account == 'local-account' and service.expected_friend == 'local-source'
    assert service._adapter is None
    config['fresh_local_binding'] = False
    path.write_text(json.dumps(config), encoding='utf-8')
    assert not BackgroundService(store).collection_enabled
    path.write_text('{bad json', encoding='utf-8')
    assert not BackgroundService(store).collection_enabled


def test_protection_scope_uses_fresh_local_binding_not_fixture_constants(tmp_path):
    from backend.background.migration import protected_materials
    store = Store(tmp_path / 'scope')
    store.put('sources', {'kind': 'moments', 'acquisition_mode': 'background', 'native_id': 'new-friend',
                         'account_native_id': 'new-account', 'account_id': 'business-account'}, 'source')
    store.put('materials', {'source_id': 'source', 'source_kind': 'moments', 'acquisition_mode': 'background',
                           'author_id': 'new-friend', 'account_id': 'business-account', 'event_key': 'native-event',
                           'source_revision_hash': 'revision', 'identity_verified': True}, 'material')
    assert 'material' in protected_materials(store)
    assert 'material' not in protected_materials(store, expected_account='new-account', expected_friend='new-friend')


def test_fresh_binding_does_not_reuse_imported_source_or_receipts(tmp_path):
    from test_background_service import FixtureNative
    from backend.background.service import EXPECTED_ACCOUNT, EXPECTED_FRIEND
    store = Store(tmp_path / 'fresh')
    old_id = 'background-moments-' + EXPECTED_FRIEND
    old = store.put('sources', {'kind': 'moments', 'acquisition_mode': 'background', 'native_id': EXPECTED_FRIEND,
                               'account_native_id': EXPECTED_ACCOUNT, 'account_id': 'old-owner', 'imported': True}, old_id)
    service = BackgroundService(store, FixtureNative())
    service.bind()
    current = next(s for s in service.summary()['sources'] if s['kind'] == 'moments')
    assert current['id'].startswith('local-background-') and current['id'] != old_id
    assert store.get('sources', old_id) == old
    with pytest.raises(ValueError, match='SOURCE_NOT_AUTHORIZED'):
        service.create_job({'source_id': old_id})


def test_imported_candidate_media_is_readable_and_never_expires(tmp_path, monkeypatch):
    import hashlib
    from backend import app as module
    from backend.store import encode
    store = Store(tmp_path / 'candidate')
    monkeypatch.setattr(module, 'store', store)
    blob = store.save_blob(b'imported-document-fixture')
    asset = {**blob, 'state': 'STAGED', 'name': 'fixture.txt', 'mime': 'text/plain'}
    candidate = {'id': 'candidate', 'source_id': 'source', 'imported': True, 'executable': False,
                 'outcome': 'PENDING_RELEVANCE', 'reason_code': 'MEDIA_INSPECTION_REQUIRED', 'created_at': '2020-01-01',
                 'expires_at': None, 'item': {'event_key': 'event', 'attachments': [asset]}}
    with store.connect() as db:
        db.execute('INSERT INTO pending_candidates VALUES(?,?,?)', ('candidate', 'source', encode(candidate)))
    service = BackgroundService(store)
    service.pipeline.expire()
    public = service.pipeline.public_candidates()['items'][0]
    assert public['imported'] and public['attachments'][0]['url'].endswith('/candidate/attachments/0')
    response = module.imported_candidate_attachment('candidate', 0)
    assert response.path.read_bytes() == b'imported-document-fixture'
    (store.root / blob['path']).write_bytes(b'tampered')
    with pytest.raises(module.HTTPException) as error:
        module.imported_candidate_attachment('candidate', 0)
    assert error.value.status_code == 404


@pytest.mark.parametrize('changed_field', ['friend_native_id', 'account_native_id'])
def test_changed_binding_blocks_old_jobs_before_native_access(tmp_path, changed_field):
    from test_background_service import FixtureNative
    from backend.background.service import EXPECTED_ACCOUNT, EXPECTED_FRIEND
    store = Store(tmp_path / 'changed-binding')
    adapter = FixtureNative()
    service = BackgroundService(store, adapter)
    service.bind()
    source = next(s for s in service.summary()['sources'] if s['kind'] == 'moments')
    job = service.create_job({'source_id': source['id'], 'mode': 'history'})
    service._injected_adapter = False
    service.live_config = {'account_native_id': EXPECTED_ACCOUNT, 'friend_native_id': EXPECTED_FRIEND,
                           'account_display_name': 'local', 'friend_display_name': 'local'}
    service.live_config[changed_field] = 'changed-local-identity'
    with pytest.raises(ValueError, match='SOURCE_NOT_AUTHORIZED'):
        service.action(job['id'], 'resume')
    service.run_once(job['id'])
    assert store.get('background_jobs', job['id'])['state'] == 'BLOCKED'
    assert store.get('background_jobs', job['id'])['last_error'] == 'SOURCE_NOT_AUTHORIZED'
    assert adapter.discovery_calls == 0 and adapter.retrieval_calls == 0
    assert store.all('materials') == []
