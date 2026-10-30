"""Reversible, exact-source migration; caller pauses and owns the workbench."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.store import Store, utcnow
from backend.background.pipeline import RelevancePipeline
from backend.background.migration import protected_materials, gc_unreferenced_blobs
from backend.background.service import BackgroundService


def write_new(path, value):
    with path.open('x', encoding='utf-8') as out:
        json.dump(value, out, ensure_ascii=False, indent=2)


def migrate(evidence, data, *, live=False):
    plan = json.loads((evidence / 'decision-manifest.json').read_text(encoding='utf-8'))
    baseline = json.loads((evidence / 'baseline.json').read_text(encoding='utf-8'))
    store = Store(data)
    if live and any(j['state'] in {'RUNNING', 'QUEUED', 'WAITING', 'RETRY'} for j in store.all('background_jobs')):
        raise ValueError('MIGRATION_REQUIRES_PAUSED_JOBS')
    before = {m['id']: m for m in store.all('materials')}
    before_blobs = {p.relative_to(store.root).as_posix() for p in (store.root / 'blobs').rglob('*') if p.is_file()}
    decisions = {d['material_id']: d for d in plan['decisions']}
    protected = protected_materials(store)
    # New manual changes since the rollback snapshot are exceptions, never overwritten.
    with store.connect() as db:
        for row in db.execute("SELECT id,data FROM records WHERE kind='materials'"):
            expected = baseline['record_hashes'].get('materials/' + row[0])
            if row[0] in decisions and expected != hashlib.sha256(row[1].encode()).hexdigest():
                protected.setdefault(row[0], []).append('CHANGED_AFTER_MIGRATION_BACKUP')
    service = BackgroundService(store)
    adapter = service.adapter if live else None
    pipeline = RelevancePipeline(store, adapter)
    sources = [s for s in store.all('sources') if s['id'] in {d['source_id'] for d in plan['decisions']}]
    results = []
    try:
        if live:
            binding = adapter.bind()
            write_new(evidence / 'migration-binding.json', {k: v for k, v in binding.items() if k in
                {'account_native_id', 'friend_native_id', 'client_version', 'state'}})
        for source in sources:
            selected = [m for m in before.values() if m['id'] in decisions and m['source_id'] == source['id']]
            fresh = {}
            page_metrics = Counter()
            stamp = None
            if live:
                cursor = None
                while True:
                    page = adapter.discover_processing(source['kind'], {'mode': 'history'}, cursor, 100, {}, force=True, baseline_index=True)
                    fresh.update({i['event_key']: i for i in page['items']})
                    page_metrics.update(page['metrics'])
                    cursor = page['cursor']
                    if page['exhausted']:
                        stamp = page.get('change_stamp')
                        adapter.release_snapshot(page['snapshot_id'])
                        break
            prepared = []
            for old in selected:
                incoming = fresh.pop(old['event_key'], old)
                decision = decisions[old['id']]
                # Reuse reviewed saved-image evidence only for the same visible
                # content/media identity; new native revisions get a fresh decision.
                media = lambda item: [(str(a.get('native_id')), a.get('media_index'), a.get('type')) for a in item.get('attachments', [])]
                same = old.get('text') == incoming.get('text') and media(old) == media(incoming)
                if old.get('source_revision') and incoming.get('source_revision'):
                    same = same and old['source_revision'] == incoming['source_revision']
                value = pipeline.prepare(source, incoming, decision=decision if same else None, retrieve=live)
                prepared.append(value)
            # Any genuine arrival during the maintenance window follows the gate.
            prepared.extend(pipeline.prepare_page(source, list(fresh.values())))
            prepared.sort(key=lambda pair: bool(pair[1].get('context_event_key')))
            job = store.put('background_jobs', {'source_id': source['id'], 'account_id': source['account_id'],
                'source_kind': source['kind'], 'mode': 'history', 'state': 'PAUSED', 'initial_history': True,
                'requested_range': {'start': None, 'end': None}, 'activation_baseline': utcnow(), 'cursor': None,
                'counts': {}, 'interval_seconds': 300, 'batch_size': 100, 'cycles': 0, 'migration': True},
                'relevance-migration-' + source['kind'])
            page = {'cursor': None, 'exhausted': True, 'parse_issues': [], 'change_stamp': stamp, 'metrics': dict(page_metrics)}
            result = pipeline.commit(source, prepared, page, job, protected=protected)
            current = store.get('background_jobs', job['id'])
            store.put('background_jobs', {**current, 'state': 'COMPLETED_LOCAL', 'next_run_at': None,
                'last_success_at': utcnow(), 'stop_reason': '相关性迁移完成；已有处理回执保留。'})
            results.append({'source_id': source['id'], 'counts': pipeline.processing(source['id'])['counts'], 'work': result,
                'additional_native_events': len(fresh)})
        # Preserve earlier completed historical jobs and original checkpoints.
        for job in store.all('background_jobs'):
            if job['source_id'] in {s['id'] for s in sources} and not job.get('migration'):
                if job['mode'] == 'history' and job.get('local_exhausted'):
                    store.put('background_jobs', {**job, 'state': 'COMPLETED_LOCAL', 'next_run_at': None})
                elif job['mode'] == 'continuous':
                    store.put('background_jobs', {**job, 'interval_seconds': 300, 'cursor': None,
                        'state': 'PAUSED', 'next_run_at': None})
        # All candidates are exact old automatic assets. No filesystem-wide deletion.
        old_assets = [a for m in before.values() if m['id'] in decisions for a in m.get('attachments', [])]
        gc = gc_unreferenced_blobs(store, old_assets, dry_run=False)
        # Retire old worker temporary duplicates after exact hash/reference checks.
        old_hashes = {a.get('sha256') for a in old_assets if a.get('sha256')}
        staged_removed = 0
        with store.connect() as db:
            referenced_json = '\n'.join(r[0] for r in db.execute('SELECT data FROM records UNION ALL SELECT data FROM revisions UNION ALL SELECT data FROM pending_candidates'))
        old_staging = (store.root / 'background-staging').resolve()
        if old_staging.is_dir():
            for path in old_staging.iterdir():
                if not path.is_file() or not path.resolve().is_relative_to(old_staging) or path.stat().st_size > 64 * 1024 * 1024:
                    continue
                if path.name in referenced_json or str(path.relative_to(store.root)).replace('\\', '/') in referenced_json:
                    continue
                if hashlib.sha256(path.read_bytes()).hexdigest() in old_hashes:
                    path.unlink()
                    staged_removed += 1
        current_records = {}
        with store.connect() as db:
            current_records = {k + '/' + ident: hashlib.sha256(raw.encode()).hexdigest() for k, ident, raw in db.execute('SELECT kind,id,data FROM records')}
            integrity = db.execute('PRAGMA integrity_check').fetchone()[0]
        protected_kinds = {'products', 'cases', 'recommendations', 'exports', 'weekly', 'live_evidence', 'native_sessions', 'page_observations', 'settings'}
        keys = [key for key in baseline['record_hashes'] if key.split('/')[0] in protected_kinds
            or key.startswith('materials/') and key.split('/', 1)[1] in protected
            or key.startswith('attachments/') and any(a.get('id') == key.split('/', 1)[1] for m in before.values() if m['id'] in protected for a in m.get('attachments', []))]
        automatic_attachment_ids = {a['id'] for m in before.values() if m['id'] in decisions for a in m.get('attachments', [])}
        keys += [key for key in baseline['record_hashes'] if key.startswith('attachments/') and key.split('/', 1)[1] not in automatic_attachment_ids]
        keys += [key for key in baseline['record_hashes'] if key.split('/')[0] in {'accounts', 'sources'} and not key.split('/', 1)[1].startswith('background-')]
        keys = sorted(set(keys))
        differences = [key for key in keys if baseline['record_hashes'][key] != current_records.get(key)]
        skipped = {r['event_key'] for s in sources for r in pipeline.receipts(s['id']) if r['outcome'] == 'SKIP_IRRELEVANT' and not r.get('protected_exception')}
        assert not differences, 'PROTECTED_RECORD_CHANGED'
        assert not any(m.get('event_key') in skipped for m in store.all('materials')), 'SKIPPED_MATERIAL_STILL_ACTIVE'
        store.validate_references()
        with store.connect() as db:
            db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            db.execute('VACUUM')
            db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        report = {'finished_at': utcnow(), 'live': live, 'sources': results, 'integrity': integrity,
            'protected_records_checked': len(keys), 'protected_record_differences': differences,
            'protected_automatic_exceptions': {k: v for k, v in protected.items() if k in decisions},
            'materials_before': len(before), 'materials_after': len(store.all('materials')),
            'pending_candidates': len(pipeline.candidates()), 'blob_gc': gc,
            'worker_staging_duplicates_removed': staged_removed,
            'unreferenced_blob_files_removed': len(before_blobs - {p.relative_to(store.root).as_posix() for p in (store.root / 'blobs').rglob('*') if p.is_file()}),
            'skipped_absent_from_active_materials': True, 'backup_path': plan['backup_path']}
        write_new(evidence / ('migration-live.json' if live else 'migration-rehearsal.json'), report)
        print(json.dumps({k: v for k, v in report.items() if k not in {'blob_gc', 'sources', 'protected_automatic_exceptions'}}, ensure_ascii=True))
    finally:
        if adapter:
            adapter.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--restore-rehearsal', action='store_true')
    args = parser.parse_args()
    if args.restore_rehearsal:
        if args.live or args.data.exists():
            raise ValueError('REHEARSAL_MUST_USE_NEW_ISOLATED_DIRECTORY')
        baseline = json.loads((args.evidence / 'baseline.json').read_text(encoding='utf-8'))
        args.data.mkdir(parents=True)
        with zipfile.ZipFile(baseline['backup_path']) as archive:
            for name, info in baseline['file_manifest'].items():
                path = (args.data / name).resolve()
                if not path.is_relative_to(args.data.resolve()):
                    raise ValueError('BACKUP_PATH_INVALID')
                content = archive.read(name)
                if hashlib.sha256(content).hexdigest() != info['sha256']:
                    raise ValueError('BACKUP_HASH_INVALID')
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
    migrate(args.evidence, args.data, live=args.live)
