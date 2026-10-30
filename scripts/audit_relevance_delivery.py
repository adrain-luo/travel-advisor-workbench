"""Read-only final checks against original business hashes and the live ledger."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import zipfile

root = Path(__file__).resolve().parents[1]
evidence = root / '.local/relevance-20261028T100157Z'
data = Path(sys.argv[1])
original = json.loads((root / '.local/integration-20261028/business-before.json').read_text(encoding='utf-8-sig'))
plan = json.loads((evidence / 'decision-manifest.json').read_text(encoding='utf-8'))
db = sqlite3.connect((data / 'workbench.sqlite3').as_uri() + '?mode=ro', uri=True)
records = {(k, ident): raw for k, ident, raw in db.execute('SELECT kind,id,data FROM records')}
receipts = [json.loads(r[0]) for r in db.execute('SELECT data FROM processing_receipts')]
skipped = {r['event_key'] for r in receipts if r['outcome'] == 'SKIP_IRRELEVANT'}
removed_ids = {d['material_id'] for d in plan['decisions'] if d['outcome'] != 'KEEP_PRODUCT_RELEVANT' and not d['protection_reasons']}
removed_ids.update(d['material_id'] for d in plan['decisions'] if d['event_key'] in skipped and not d['protection_reasons'])
record_errors = [r['kind'] + '/' + r['id'] for r in original['records']
    if hashlib.sha256(records.get((r['kind'], r['id']), '').encode()).hexdigest() != r['sha256']]
with zipfile.ZipFile(original['backup']) as archive:
    original_files = json.loads(archive.read('manifest.json'))['files']
file_errors = [name for name, info in original_files.items() if name != 'workbench.sqlite3'
    and (not (data / name).is_file() or hashlib.sha256((data / name).read_bytes()).hexdigest() != info['sha256'])]
active_skip = [ident for (kind, ident), raw in records.items() if kind == 'materials' and json.loads(raw).get('event_key') in skipped]
remaining_revisions = sum(ident in removed_ids for (ident,) in db.execute("SELECT id FROM revisions WHERE kind='materials'"))
reference_hits = []
for (kind, ident), raw in records.items():
    if kind in {'products', 'cases', 'recommendations', 'weekly', 'exports'} and any(removed in raw for removed in removed_ids):
        reference_hits.append(kind + '/' + ident)
minimal = all(not {'text', 'attachments', 'private_ref', 'private_source_ref', 'body'}.intersection(r) for r in receipts if r['outcome'] == 'SKIP_IRRELEVANT')
result = {'checked_at': datetime.now(timezone.utc).isoformat(), 'original_business_records_checked': len(original['records']),
    'original_business_record_mismatches': record_errors, 'original_files_checked': len(original_files) - 1,
    'original_file_mismatches': file_errors, 'receipt_outcomes': dict(Counter(r['outcome'] for r in receipts)),
    'skipped_active_materials': active_skip, 'removed_material_revisions_remaining': remaining_revisions,
    'removed_material_business_reference_hits': reference_hits, 'skipped_receipts_have_no_body_or_media': minimal,
    'integrity': db.execute('PRAGMA integrity_check').fetchone()[0],
    'active_jobs': [{k: value.get(k) for k in ('id', 'source_id', 'mode', 'state', 'interval_seconds', 'last_error')}
        for (kind, _), raw in records.items() if kind == 'background_jobs' and (value := json.loads(raw))['state'] in {'WAITING', 'QUEUED', 'RUNNING', 'RETRY'}]}
db.close()
assert not record_errors and not file_errors and not active_skip and not remaining_revisions and not reference_hits and minimal
with (evidence / (sys.argv[2] if len(sys.argv) > 2 else 'delivery-audit.json')).open('x', encoding='utf-8') as stream:
    json.dump(result, stream, ensure_ascii=False, indent=2)
print(json.dumps({k: v for k, v in result.items() if k != 'active_jobs'}, ensure_ascii=True))
