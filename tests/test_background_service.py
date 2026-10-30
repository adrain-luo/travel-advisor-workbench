"""Background integration fixtures: no WeChat or business-data access."""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import io

from PIL import Image
import pytest

from backend.store import Store
from backend.background.service import BackgroundService, EXPECTED_ACCOUNT, EXPECTED_FRIEND


class FixtureNative:
    def __init__(self):
        self.rows = []
        self.snapshots = {}
        self.discovery_calls = 0
        self.retrieval_calls = 0
        self.fail_media = False
        self.on_discover = None
        self.invalid = False

    def bind(self):
        if self.invalid:
            raise ValueError('ACCOUNT_OR_PROCESS_CHANGED')
        return {'account_native_id': EXPECTED_ACCOUNT, 'friend_native_id': EXPECTED_FRIEND}

    def discover(self, kind, scope, cursor, limit):
        self.discovery_calls += 1
        if cursor is None:
            sid = str(len(self.snapshots))
            self.snapshots[sid] = list(self.rows)
            offset = 0
        else:
            sid, offset = cursor['sid'], cursor['offset']
            if sid not in self.snapshots:
                raise ValueError('CURSOR_SNAPSHOT_UNAVAILABLE')
        selected = self.snapshots[sid][offset:offset + limit]
        if self.on_discover:
            self.on_discover()
        return {'items': selected, 'cursor': {'sid': sid, 'offset': offset + len(selected)},
            'snapshot_id': sid, 'exhausted': offset + len(selected) >= len(self.snapshots[sid]),
            'observed_range': {}, 'coverage': 'UNKNOWN'}

    def retrieve(self, attachment, staging):
        self.retrieval_calls += 1
        if self.fail_media:
            return {'state': 'RETRY', 'reason': 'NETWORK_TEMPORARY'}
        out = io.BytesIO()
        Image.new('RGB', (4, 5), 'blue').save(out, format='PNG')
        path = staging / 'fixture.png'; path.write_bytes(out.getvalue())
        return {'state': 'SAVED', 'path': str(path), 'sha256': hashlib.sha256(out.getvalue()).hexdigest(),
                'mime': 'image/png', 'quality': 'fixture'}


PRODUCT = '旅游线路报价499元，含酒店住宿，11月8日出团。'


def item(ident, text=PRODUCT, *, media=False):
    return {'event_key': str(ident), 'native_id': str(ident), 'native_post_id': str(ident),
        'native_revision': hashlib.sha256((str(ident) + text + str(media)).encode()).hexdigest(),
        'author_id': EXPECTED_FRIEND, 'text': text, 'identity_verified': True, 'source_kind': 'moments',
        'publication_time': '2025-06-01T12:00:00+08:00', 'source_time_raw': '1748750400',
        'attachments': [{'native_id': 'media-' + str(ident), 'media_index': 0, 'type': 'image',
            'mime': 'image/png', 'name': 'fixture.png', 'private_ref': 'opaque-reference'}] if media else []}


@pytest.fixture
def setup(tmp_path):
    store = Store(tmp_path / 'isolated')
    adapter = FixtureNative()
    service = BackgroundService(store, adapter)
    service.bind()
    source = next(s for s in service.summary()['sources'] if s['kind'] == 'moments')
    return store, adapter, service, source


def complete_initial_history(service, source):
    job = service.create_job({'source_id': source['id'], 'mode': 'history'})
    service.run_once(job['id'])
    assert service.store.get('background_jobs', job['id'])['state'] == 'COMPLETED_LOCAL'
    return job


def test_same_second_large_ids_repeat_and_manual_revision(setup):
    store, adapter, service, source = setup
    adapter.rows = [item(18446744073709551615, media=True), item(18446744073709551614, media=True)]
    complete_initial_history(service, source)
    job = service.create_job({'source_id': source['id'], 'mode': 'continuous'})
    service.run_once(job['id'])
    originals = store.all('materials')
    assert len(originals) == 2 and all(isinstance(p['native_id'], str) for p in originals)
    corrected = next(p for p in originals if p['native_id'] == '18446744073709551615')
    service.classify('materials', corrected['id'], {'label': 'travel_promotion', 'evidence': 'manual fixture'})
    service.run_once(job['id'])
    assert len(store.all('materials')) == 2
    adapter.rows[0] = item(18446744073709551615, PRODUCT + '修订团费399元。', media=True)
    service.run_once(job['id'])
    assert len(store.all('materials')) == 2
    revised = store.get('materials', corrected['id'])
    assert revised['text'] == PRODUCT + '修订团费399元。' and revised['classification']['origin'] == 'manual'
    with store.connect() as db:
        assert db.execute('SELECT count(*) FROM source_events').fetchone()[0] == 3


def test_independent_history_incremental_late_arrival_and_pause(setup):
    store, adapter, service, source = setup
    complete_initial_history(service, source)
    adapter.rows = [item('10'), item('11')]
    history = service.create_job({'source_id': source['id'], 'mode': 'history', 'batch_size': 1, 'reprocess': True})
    service.run_once(history['id'])
    history_cursor = store.get('background_jobs', history['id'])['cursor']
    continuous = service.create_job({'source_id': source['id'], 'mode': 'continuous'})
    service.run_once(continuous['id'])
    assert store.get('background_jobs', history['id'])['cursor'] == history_cursor
    adapter.rows.insert(0, item('9', PRODUCT + '补到的历史线路。'))
    service.run_once(continuous['id'])
    assert len(store.all('materials')) == 3
    adapter.on_discover = lambda: service.action(history['id'], 'pause')
    service.run_once(history['id'])
    assert store.get('background_jobs', history['id'])['state'] == 'PAUSED'
    assert {c['job_id'] for c in store.all('checkpoints')} >= {history['id'], continuous['id']}


def test_media_retry_after_history_is_complete_and_blobs_deduplicate(setup):
    store, adapter, service, source = setup
    adapter.rows = [item('1', media=True), item('2', media=True)]
    history = service.create_job({'source_id': source['id'], 'mode': 'history'})
    service.run_once(history['id'])
    assert store.get('background_jobs', history['id'])['state'] == 'COMPLETED_LOCAL'
    media = next(j for j in store.all('background_jobs') if j['mode'] == 'media')
    adapter.fail_media = True
    service.run_once(media['id'])
    assert all(a['state'] == 'RETRY' for a in store.all('attachments'))
    scheduled = store.get('background_jobs', media['id'])['next_run_at']
    assert (datetime.fromisoformat(scheduled) - datetime.now(timezone.utc)).total_seconds() > 20
    adapter.fail_media = False
    service.action(media['id'], 'retry')
    service.run_once(media['id'])
    assert all(a['media_state'] == 'VALIDATED' for a in store.all('attachments'))
    with store.connect() as db:
        assert db.execute('SELECT count(*) FROM blobs').fetchone()[0] == 1
    assert len(store.all('materials')) == 2
    assert store.get('background_jobs', history['id'])['state'] == 'COMPLETED_LOCAL'


def test_restart_cursor_reconciliation_and_account_invalidation(setup):
    store, adapter, service, source = setup
    adapter.rows = [item('1'), item('2')]
    job = service.create_job({'source_id': source['id'], 'mode': 'history', 'batch_size': 1})
    service.run_once(job['id'])
    adapter2 = FixtureNative(); adapter2.rows = list(adapter.rows)
    resumed = BackgroundService(Store(store.root), adapter2)
    resumed.run_once(job['id'])
    assert store.get('background_jobs', job['id'])['cursor'] is None
    resumed.run_once(job['id'])
    resumed.run_once(job['id'])
    assert len(store.all('materials')) == 2
    continuous = resumed.create_job({'source_id': source['id'], 'mode': 'continuous'})
    store.put('background_jobs', {**continuous, 'cursor': {'snapshot_id': 'old-session', 'offset': 1}})
    adapter2.invalid = True
    resumed.run_once(continuous['id'])
    assert store.get('background_jobs', continuous['id'])['state'] == 'BLOCKED'
    assert resumed.summary()['binding']['state'] == 'BLOCKED'
    assert store.get('background_jobs', continuous['id'])['cursor'] is None


def test_empty_poll_does_not_verify_new_content_and_reject_scope(setup):
    store, adapter, service, source = setup
    complete_initial_history(service, source)
    job = service.create_job({'source_id': source['id'], 'mode': 'continuous',
                              'range': {'start': '2025-01-01'}})
    assert job['requested_range'] == {'start': None, 'end': None}
    service.run_once(job['id'])
    assert service.summary()['capabilities']['new_content']['status'] == 'IMPLEMENTED'
    assert store.get('background_jobs', job['id'])['new_event_evidence'] == []
    with pytest.raises(ValueError):
        service.create_job({'source_id': 'old-unapproved-source'})


def test_atomic_cursor_event_and_attachment_rollback(setup):
    store, adapter, service, source = setup
    job = service.create_job({'source_id': source['id'], 'mode': 'history'})
    bad = item('2'); bad['author_id'] = 'unrelated'
    with pytest.raises(ValueError):
        store.ingest_background_page(source, [item('1', media=True), bad], {'cursor': 'bad'}, job)
    assert not store.all('materials') and not store.all('attachments') and not store.all('checkpoints')
    with store.connect() as db:
        assert db.execute('SELECT count(*) FROM source_events').fetchone()[0] == 0


def test_history_first_import_does_not_hide_new_continuous_evidence(setup, monkeypatch):
    """History wins the import race; continuous still verifies the same new event."""
    import backend.store as store_module
    import backend.background.service as service_module
    store, adapter, service, source = setup
    clock = ['2026-10-28T12:00:00+00:00']
    monkeypatch.setattr(store_module, 'utcnow', lambda: clock[0])
    monkeypatch.setattr(service_module, 'utcnow', lambda: clock[0])
    already_stored = item('before-activation')
    # Deliberately ahead-dated cached row: it must not turn into new evidence.
    already_stored['publication_time'] = '2026-10-28T12:00:20+00:00'
    adapter.rows = [already_stored]
    history = service.create_job({'source_id': source['id'], 'mode': 'history'})
    service.run_once(history['id'])
    clock[0] = '2026-10-28T12:00:10+00:00'
    continuous = service.create_job({'source_id': source['id'], 'mode': 'continuous'})
    newly_published = item('after-activation')
    newly_published['publication_time'] = '2026-10-28T12:00:20+00:00'
    adapter.rows = [already_stored, newly_published]
    clock[0] = '2026-10-28T12:00:30+00:00'
    assert service.action(history['id'], 'resume')['state'] == 'COMPLETED_LOCAL'
    history = service.create_job({'source_id': source['id'], 'mode': 'history', 'reprocess': True})
    service.run_once(history['id'])
    assert len(store.all('materials')) == 2
    clock[0] = '2026-10-28T12:00:40+00:00'
    service.run_once(continuous['id'])
    evidence = store.get('background_jobs', continuous['id'])['new_event_evidence']
    assert [value['event_key'] for value in evidence] == ['after-activation']
    assert evidence[0]['first_discovered_at'] == '2026-10-28T12:00:30+00:00'
    assert evidence[0]['observation'] == 'processing_receipt_reconciled'
    assert service.summary()['per_source']['moments']['new_content']['status'] == 'VERIFIED'
    assert service.summary()['per_source']['chat']['new_content']['status'] == 'IMPLEMENTED'
    clock[0] = '2026-10-28T12:00:50+00:00'
    service.run_once(continuous['id'])
    assert store.get('background_jobs', continuous['id'])['new_event_evidence'] == evidence
    with store.connect() as db:
        assert db.execute('SELECT count(*) FROM source_events').fetchone()[0] == 2


def test_prior_parse_gap_retains_snapshot_and_observed_range_across_pages(setup):
    store, adapter, service, source = setup
    complete_initial_history(service, source)
    adapter.rows = [item('1'), item('2')]
    releases = []
    adapter.release_snapshot = releases.append
    discover = adapter.discover

    def pages(kind, scope, cursor, limit):
        page = discover(kind, scope, cursor, limit)
        page['observed_range'] = {'min_epoch': 100, 'max_epoch': 200} if cursor is None else {'start_epoch': 50, 'end_epoch': 80}
        page['parse_issues'] = [{'native_tid': 'missing', 'code': 'MALFORMED_RECORD'}] if cursor is None else []
        return page

    adapter.discover = pages
    job = service.create_job({'source_id': source['id'], 'mode': 'history', 'batch_size': 1, 'reprocess': True})
    service.run_once(job['id'])
    service.run_once(job['id'])
    result = store.get('background_jobs', job['id'])
    assert result['state'] == 'BLOCKED' and len(result['parse_gaps']) == 1
    assert result['observed_range'] == {'min_epoch': 50, 'max_epoch': 200}
    assert releases == [] and len(store.all('materials')) == 2
    continuous = service.create_job({'source_id': source['id'], 'mode': 'continuous', 'batch_size': 1})
    service.run_once(continuous['id'])
    service.run_once(continuous['id'])
    partial = store.get('background_jobs', continuous['id'])
    assert partial['state'] == 'WAITING' and partial['last_error'] == 'NATIVE_RECORD_PARSE_GAPS'
    retained = partial['parse_gap_snapshot_id']
    adapter.rows.append(item('3'))
    for _ in range(3):
        service.run_once(continuous['id'])
    assert len(store.all('materials')) == 3 and releases == [retained]
