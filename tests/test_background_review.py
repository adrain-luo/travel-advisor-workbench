"""Exact-source image review checks using isolated synthetic records only."""
import copy

import pytest

from backend.background.relevance import KEEP_PRODUCT_RELEVANT as KEEP, SKIP_IRRELEVANT as SKIP
from test_background_service import item, setup


@pytest.fixture
def reviewed(setup):
    store, adapter, service, source = setup
    adapter.rows = [item('review-fixture', media=True)]
    history = service.create_job({'source_id': source['id'], 'mode': 'history'})
    service.run_once(history['id'])
    media = next(j for j in store.all('background_jobs') if j['mode'] == 'media')
    service.run_once(media['id'])
    service.create_job({'source_id': source['id'], 'mode': 'continuous'})
    material = store.all('materials')[0]
    assert material['attachments'][0]['media_state'] == 'VALIDATED'
    entry = {'material_id': material['id'], 'source_id': source['id'],
             'event_key': material['event_key'], 'label': 'travel_promotion',
             'asset_sha256': [a['sha256'] for a in material['attachments']],
             'evidence': 'Synthetic image review evidence.'}
    return store, adapter, service, source, material, entry


@pytest.mark.parametrize('field,value', [('material_id', 'missing-material'),
    ('source_id', 'another-source'), ('event_key', 'another-event'), ('label', 'invalid-label')])
def test_review_rejects_wrong_record_scope_without_changes(reviewed, field, value):
    store, adapter, service, source, material, entry = reviewed
    before_receipts = service.pipeline.receipts(source['id'])
    entry[field] = value
    with pytest.raises(ValueError, match='RELEVANCE_REVIEW_SCOPE_MISMATCH'):
        service.apply_relevance_review([entry])
    assert store.get('materials', material['id']) == material
    assert service.pipeline.receipts(source['id']) == before_receipts


@pytest.mark.parametrize('field,value', [('account_native_id', 'another-account'),
    ('native_id', 'another-friend'), ('acquisition_mode', 'foreground')])
def test_review_rejects_source_outside_selected_binding(reviewed, field, value):
    store, adapter, service, source, material, entry = reviewed
    store.put('sources', {**source, field: value})
    with pytest.raises(ValueError, match='RELEVANCE_REVIEW_SCOPE_MISMATCH'):
        service.apply_relevance_review([entry])
    assert store.get('materials', material['id']) == material


@pytest.mark.parametrize('field,value', [('account_id', 'another-account'),
    ('acquisition_mode', 'manual_upload'), ('identity_verified', False)])
def test_review_preserves_material_outside_background_scope(reviewed, field, value):
    store, adapter, service, source, material, entry = reviewed
    changed = store.put('materials', {**material, field: value})
    with pytest.raises(ValueError, match='RELEVANCE_REVIEW_SCOPE_MISMATCH'):
        service.apply_relevance_review([entry])
    assert store.get('materials', material['id']) == changed


@pytest.mark.parametrize('mode', ['empty', 'wrong', 'duplicate'])
def test_review_requires_exact_image_hash_multiset(reviewed, mode):
    store, adapter, service, source, material, entry = reviewed
    entry['asset_sha256'] = [] if mode == 'empty' else ['0' * 64] if mode == 'wrong' else entry['asset_sha256'] * 2
    with pytest.raises(ValueError, match='RELEVANCE_REVIEW_IMAGE_MISMATCH'):
        service.apply_relevance_review([entry])
    assert store.get('materials', material['id']) == material
    assert service.pipeline.receipts(source['id'])[0]['outcome'] == KEEP


def test_negative_review_removes_active_material_and_persists_inspection_receipt(reviewed):
    store, adapter, service, source, material, entry = reviewed
    before_calls = adapter.discovery_calls, adapter.retrieval_calls
    entry['label'] = 'other'
    assert service.apply_relevance_review([entry]) == {'applied': 1, 'manual_decisions_preserved': 0}
    assert store.get('materials', material['id']) is None
    assert not store.all('attachments')
    receipt = service.pipeline.receipts(source['id'])[0]
    assert receipt['outcome'] == SKIP
    assert receipt['classification']['label'] == 'other'
    assert receipt['classification']['origin'] == 'inspection'
    assert receipt['material_id'] is None
    assert (adapter.discovery_calls, adapter.retrieval_calls) == before_calls
    # A later native revision retains reviewed judgment even after its card is gone.
    changed = item('review-fixture', '旅游线路报价799元，含酒店住宿，12月1日出团。', media=True)
    prepared, decision = service.pipeline.prepare(source, changed, retrieve=False)
    assert prepared['classification']['origin'] == 'inspection'
    assert decision['outcome'] == SKIP


def test_positive_review_updates_inspection_evidence_without_manual_origin(reviewed):
    store, adapter, service, source, material, entry = reviewed
    before_calls = adapter.discovery_calls, adapter.retrieval_calls
    assert service.apply_relevance_review([entry]) == {'applied': 1, 'manual_decisions_preserved': 0}
    current = store.get('materials', material['id'])
    assert current['text'] == material['text'] and current['attachments'] == material['attachments']
    assert current['classification']['label'] == 'travel_promotion'
    assert current['classification']['origin'] == 'inspection'
    receipt = service.pipeline.receipts(source['id'])[0]
    assert receipt['outcome'] == KEEP and receipt['classification']['origin'] == 'inspection'
    assert (adapter.discovery_calls, adapter.retrieval_calls) == before_calls


def test_review_preserves_existing_manual_decision_and_receipt(reviewed):
    store, adapter, service, source, material, entry = reviewed
    service.classify('materials', material['id'], {'label': 'travel_promotion', 'evidence': 'Manual fixture choice.'})
    before = copy.deepcopy(store.get('materials', material['id']))
    receipt = copy.deepcopy(service.pipeline.receipts(source['id']))
    entry['label'] = 'other'
    assert service.apply_relevance_review([entry]) == {'applied': 0, 'manual_decisions_preserved': 1}
    assert store.get('materials', material['id']) == before
    assert service.pipeline.receipts(source['id']) == receipt
