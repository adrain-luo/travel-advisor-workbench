"""Workbench API integration uses only synthetic isolated source adapters."""
from fastapi.testclient import TestClient

from backend.store import Store
from test_background_service import FixtureNative, item


def test_background_gate_is_independent_and_routes_preserve_old_sources(tmp_path, monkeypatch):
    from backend import app as module
    monkeypatch.delenv('TRAVEL_ENABLE_FOREGROUND_COLLECTION', raising=False)
    data = Store(tmp_path / 'data')
    old = data.put('sources', {'display_name': '历史测试来源', 'kind': 'group'}, 'fixture-old')
    monkeypatch.setattr(module, 'store', data)
    with TestClient(module.app) as client:
        adapter = FixtureNative(); adapter.rows = [item('18446744073709551615', media=True)]
        from backend.background.service import BackgroundService
        module.background_service = BackgroundService(data, adapter)
        assert client.get('/api/state').json()['settings']['foreground_collection_enabled'] is False
        assert client.post('/api/background/bind').status_code == 200
        state = client.get('/api/background').json()
        assert len(state['sources']) == 2
        assert data.get('sources', old['id']) == old
        source = next(s for s in state['sources'] if s['kind'] == 'moments')
        response = client.post('/api/background/jobs', json={'source_id': source['id'], 'mode': 'history'})
        assert response.status_code == 200
        job = response.json()
        module.background_service.run_once(job['id'])
        material = data.all('materials')[0]
        pending = material['attachments'][0]
        assert client.get('/api/attachments/' + pending['id']).status_code in {200, 409}
        correction = client.post('/api/classifications/materials/' + material['id'],
            json={'label': 'other', 'evidence': '测试夹具修正'})
        assert correction.status_code == 200 and correction.json()['classification']['origin'] == 'manual'
        assert data.get('materials', material['id']) is None
        receipt = module.background_service.pipeline.receipts(source['id'])[0]
        assert receipt['outcome'] == 'SKIP_IRRELEVANT' and receipt['classification']['origin'] == 'manual'
        assert client.post('/api/background/jobs/' + job['id'] + '/pause').json()['state'] == 'PAUSED'
        resumed = client.post('/api/background/jobs/' + job['id'] + '/resume')
        assert resumed.status_code == 200 and resumed.json()['state'] == 'COMPLETED_LOCAL'
        assert client.post('/api/background/shutdown').json()['stopped'] is True


def test_inspection_labels_require_exact_saved_bytes_and_preserve_manual(setup):
    store, adapter, service, source = setup
    adapter.rows = [item('1', media=True)]
    adapter.rows[0]['source_kind'] = 'moments'
    job = service.create_job({'source_id': source['id'], 'mode': 'history'})
    service.run_once(job['id'])
    media = next(j for j in store.all('background_jobs') if j['mode'] == 'media')
    service.run_once(media['id'])
    post = store.all('materials')[0]; asset = post['attachments'][0]
    service.classify('materials', post['id'], {'label': 'travel_promotion', 'evidence': 'manual correction'})
    outcome = service.apply_inspection([{'native_post_id': '1', 'label': 'travel_sharing', 'evidence': 'review',
        'images': [{'index': 0, 'sha256': asset['sha256'], 'label': 'scenic_personal', 'evidence': 'photo'}]}])
    assert outcome == {'posts': 0, 'images': 1, 'manual_corrections_preserved': 1}
    assert store.get('materials', post['id'])['classification']['label'] == 'travel_promotion'
    assert store.get('attachments', asset['id'])['classification']['origin'] == 'inspection'


from test_background_service import setup
