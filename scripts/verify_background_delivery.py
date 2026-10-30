"""Read-only delivery verification through the loopback app and its backup.

Creates one app backup and isolated evidence files. Never imports a collector,
opens native WeChat files, reads keys, or changes application records.
"""
from pathlib import Path
from datetime import datetime, timezone
import argparse
import collections
import hashlib
import io
import json
import sqlite3
import urllib.request
import zipfile

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / '.local' / 'integration-20261028'


def api(path, body=None):
    request = urllib.request.Request('http://127.0.0.1:8765' + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--name', required=True)
    args = parser.parse_args()
    if not args.name.replace('-', '').isalnum():
        raise ValueError('Invalid evidence name')
    output = RUN / (args.name + '.json')
    if output.exists():
        raise ValueError('Evidence already exists')
    state = api('/api/state')
    report = {'observed_at': datetime.now(timezone.utc).isoformat(),
              'foreground_enabled': state['settings']['foreground_collection_enabled'],
              'background': state['background']}
    backup = api('/api/backup', {})
    report['backup'] = backup['path']
    database = RUN / (args.name + '.sqlite3')
    with zipfile.ZipFile(backup['path']) as archive:
        database.write_bytes(archive.read('workbench.sqlite3'))
        manifest = json.loads(archive.read('manifest.json'))
    db = sqlite3.connect(database.as_uri() + '?mode=ro&immutable=1', uri=True)
    rows = {(kind, ident): data for kind, ident, data in db.execute('SELECT kind,id,data FROM records')}
    before = json.loads((RUN / 'business-before.json').read_text(encoding='utf-8'))
    preserved = []
    for old in before['records']:
        data = rows.get((old['kind'], old['id']))
        preserved.append(bool(data and hashlib.sha256(data.encode()).hexdigest() == old['sha256']))
    report['existing_records_unchanged'] = {'total': len(preserved), 'unchanged': sum(preserved)}
    with zipfile.ZipFile(json.loads((RUN / 'business-backup-before.json').read_text(encoding='utf-8-sig'))['path']) as oldzip:
        oldmanifest = json.loads(oldzip.read('manifest.json'))
        oldassets = {name: meta for name, meta in oldmanifest['files'].items() if name != 'workbench.sqlite3'}
    report['existing_files_unchanged'] = {'total': len(oldassets), 'unchanged': sum(
        manifest['files'].get(name) == meta for name, meta in oldassets.items())}
    records = [(kind, json.loads(data)) for (kind, _), data in rows.items()]
    materials = [data for kind, data in records if kind == 'materials' and data.get('acquisition_mode') == 'background']
    attachments = [data for kind, data in records if kind == 'attachments' and data.get('acquisition_mode') == 'background' and not data.get('retired')]
    data_root = Path(state['settings']['data_dir']).resolve()
    checks = []
    for asset in attachments:
        result = {key: asset.get(key) for key in ('id', 'material_id', 'source_id', 'native_id', 'media_index',
            'state', 'last_error', 'quality', 'sha256', 'size', 'width', 'height', 'classification',
            'native_source_sha256', 'native_source_bytes', 'native_source_format', 'decode_method')}
        if asset['state'] == 'SAVED':
            path = (data_root / asset['path']).resolve()
            assert path.is_relative_to(data_root / 'blobs')
            raw = path.read_bytes()
            result['reopened_hash_size_match'] = hashlib.sha256(raw).hexdigest() == asset['sha256'] and len(raw) == asset['size']
            if asset['mime'].startswith('image/'):
                with Image.open(io.BytesIO(raw)) as image:
                    image.load()
                    result['independently_decoded'] = True
                    result['decoded_dimensions'] = [image.width, image.height]
            assert result['reopened_hash_size_match']
        checks.append(result)
    report['attachments'] = checks
    report['sources'] = {}
    for kind in ('moments', 'chat'):
        posts = [record for record in materials if record['source_kind'] == kind]
        ids = {record['id'] for record in posts}
        files = [asset for asset in attachments if asset['material_id'] in ids]
        source_id = 'background-' + kind + '-wxid_8n1ox3efqcat11'
        events = db.execute('SELECT count(*),count(DISTINCT event_key) FROM source_events WHERE source_id=?', (source_id,)).fetchone()
        report['sources'][kind] = {'records': len(posts), 'event_revisions': events[0], 'unique_native_events': events[1],
            'directions': dict(collections.Counter(record.get('direction', 'not_applicable') for record in posts)),
            'attachment_states': dict(collections.Counter(asset['state'] for asset in files)),
            'attachment_types': dict(collections.Counter(asset.get('type') for asset in files)),
            'failure_reasons': dict(collections.Counter(asset.get('last_error') for asset in files if asset['state'] != 'SAVED')),
            'quality': dict(collections.Counter(asset.get('quality') for asset in files if asset['state'] == 'SAVED')),
            'document_samples': sum(asset.get('type') == 'file' for asset in files) if kind == 'chat' else None,
            'records_manifest': [{key: record.get(key) for key in ('id', 'native_id', 'native_post_id', 'event_key',
                'author_id', 'conversation_id', 'direction', 'publication_time', 'source_time', 'first_discovered_at', 'classification')} for record in posts]}
        assert events[1] == len(posts)
        assert all(isinstance(record['native_id'], str) for record in posts)
    report['new_event_count'] = sum(len(job.get('new_event_evidence', [])) for job in state['background']['jobs'] if job['mode'] == 'continuous')
    assert all(preserved) and report['existing_files_unchanged']['total'] == report['existing_files_unchanged']['unchanged']
    assert report['foreground_enabled'] is False
    report['verification'] = 'PASS'
    db.close()
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'evidence': str(output), 'verification': report['verification'],
        'existing_records_unchanged': report['existing_records_unchanged'],
        'sources': {kind: {key: value for key, value in data.items() if key != 'records_manifest'} for kind, data in report['sources'].items()},
        'new_event_count': report['new_event_count']}, ensure_ascii=True))


if __name__ == '__main__':
    main()
