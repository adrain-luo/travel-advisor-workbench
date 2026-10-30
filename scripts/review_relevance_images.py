"""Record exact saved-image review judgments and apply them through the gate."""
import json
from pathlib import Path
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.background.inspection import inspect_record
from backend.background.relevance import decide, RULE_VERSION

evidence = ROOT / '.local/relevance-20261028T100157Z'
bad = {'ef26045d077244d2bae1b81242f74b5a', '74970e42858d4d198defd26a69ee6517'}
def request(path, body=None):
    req = urllib.request.Request('http://127.0.0.1:8765/api/' + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=60) as stream:
        return json.load(stream)

if '--apply' in sys.argv:
    entries = json.loads((evidence / 'image-review-exact.json').read_text(encoding='utf-8'))['entries']
    before = request('state')
    result = request('background/relevance-review', entries)
    after = request('state')
    result.update(materials_before=len(before['materials']), materials_after=len(after['materials']),
        bad_ids_absent=not bool(bad & {m['id'] for m in after['materials']}),
        source_counts={s['kind']: s['processing']['counts'] for s in after['background']['sources']})
    with (evidence / 'image-review-applied.json').open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps(result, ensure_ascii=True))
else:
    plan = json.loads((evidence / 'decision-manifest.json').read_text(encoding='utf-8'))
    selected = {d['material_id'] for d in plan['decisions'] if d['reason_code'] == 'OCR_PRODUCT_EVIDENCE'}
    materials = {m['id']: m for m in request('state')['materials']}
    assert len(selected) == 6 and selected <= set(materials)
    entries, checks = [], []
    for ident in sorted(selected):
        m = materials[ident]
        entries.append({'material_id': ident, 'source_id': m['source_id'], 'event_key': m['event_key'],
            'asset_sha256': sorted(a['sha256'] for a in m.get('attachments', []) if a.get('sha256')),
            'label': 'other' if ident in bad else 'travel_promotion',
            'evidence': '已核读原始图片：业务规划或软件服务示意图，未提供具体旅游产品信息。' if ident in bad else
                '已核读原始图片：包含具体旅游产品行程、报价或报名条件。',
            'review_origin': 'assistant_saved_image_inspection'})
        if ident in bad:
            transient = inspect_record(m, allowed_root=Path(sys.argv[1]))
            decision = decide(m, inspection=transient)
            checks.append({'material_id': ident, 'outcome': decision['outcome'], 'reason_code': decision['reason_code'],
                'metrics': decision['metrics']})
    report = {'rule_version': RULE_VERSION, 'reviewed_occurrences': 6, 'distinct_images': len({h for e in entries for h in e['asset_sha256']}),
        'positive_occurrences': 4, 'negative_occurrences': 2, 'entries': entries,
        'actual_negative_ocr_regression': checks, 'source_bodies_or_ocr_text_retained': False,
        'general_visual_accuracy_claimed': False}
    with (evidence / ('image-review-guard-v4.json' if '--rerun-v4' in sys.argv else 'image-review-guard-v3.json' if '--rerun' in sys.argv else 'image-review-exact.json')).open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    print(json.dumps({k: v for k, v in report.items() if k != 'entries'}, ensure_ascii=True))
