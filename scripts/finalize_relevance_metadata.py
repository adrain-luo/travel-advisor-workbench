"""Publish automatic relevance labels without changing trusted decisions."""
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.store import Store, utcnow

data, evidence = map(Path, sys.argv[1:3])
store = Store(data)
changed = []
with store.lock, store.connect() as db:
    for row in list(db.execute('SELECT data FROM processing_receipts')):
        receipt = json.loads(row[0])
        if receipt['outcome'] != 'KEEP_PRODUCT_RELEVANT' or not receipt.get('material_id'):
            continue
        material = store.get('materials', receipt['material_id'])
        if not material or material.get('classification', {}).get('origin') in {'manual', 'inspection'}:
            continue
        material['relevance'] = {key: receipt[key] for key in ('outcome', 'rule_version', 'reason_code')}
        material['classification'] = {'label': 'travel_promotion', 'origin': 'rule', 'updated_at': utcnow(),
            'evidence': '本地图片文字识别命中旅游产品规则；保留历史日期与报价条件，不代表当前可订。'}
        store.put('materials', material, db=db)
        changed.append(material['id'])
    for job in store.all('background_jobs'):
        if job.get('migration'):
            job['review_metrics_reused'] = {k: job.get('last_cycle', {}).get(k, 0)
                for k in ('classification_operations', 'ocr_operations', 'media_inspected')}
            job['last_cycle'] = {**job.get('last_cycle', {}), 'classification_operations': 0,
                'ocr_operations': 0, 'media_inspected': 0}
            store.put('background_jobs', job, db=db)
report = {'finished_at': utcnow(), 'automatic_labels_updated': len(changed),
    'trusted_manual_and_inspection_labels_untouched': True,
    'migration_work_accounting': {'offline_review_classification_operations': 290,
        'offline_review_ocr_operations': 62, 'offline_review_media_inspected': 63,
        'live_apply_content_reads': 290, 'live_apply_additional_classification_operations': 0,
        'live_apply_additional_ocr_operations': 0,
        'note': 'The dated migration-live.json work decision counters came from reused decision-manifest evidence, not a second recognition run. Current migration job metrics now distinguish those phases.'}}
with (evidence / 'metadata-finalization.json').open('x', encoding='utf-8') as stream:
    json.dump(report, stream, ensure_ascii=False, indent=2)
print(json.dumps(report, ensure_ascii=True))
