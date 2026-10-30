"""Verify an isolated imported workbench and optionally exercise business workflows."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import sqlite3
import urllib.error
import urllib.parse
import urllib.request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--exercise', action='store_true', help='Create verification business records in this isolated imported dataset')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    parsed = urllib.parse.urlparse(args.url)
    if parsed.scheme != 'http' or parsed.hostname != '127.0.0.1':
        raise ValueError('Use a loopback verification instance')
    base = args.url.rstrip('/')

    def call(path, data=None, method=None, binary=False):
        request = urllib.request.Request(base + path, data=None if data is None else json.dumps(data).encode('utf-8'),
                                         method=method, headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(request, timeout=60) as response:
            content = response.read()
            return content if binary else json.loads(content)

    health = call('/api/health')
    assert health['status'] == 'ok'
    assert Path(health['data_dir']).resolve() == args.data_dir.resolve(), 'Wrong data directory'
    assert health.get('live_collection_enabled') is False, 'Live collection must be disabled'
    state = call('/api/state')
    assert not state['settings']['has_api_key']
    assert not state['settings']['provider']['base_url']
    assert not state['settings']['foreground_collection_enabled']
    assert all(not account.get('selected') for account in state['accounts'])
    assert all(not source.get('selected') for source in state['sources'])
    html = call('/', binary=True).decode('utf-8')
    assert '选团助手' in html
    bundles = re.findall(r'(?:src|href)="(/assets/[^\"]+)"', html)
    assert bundles
    for asset in bundles:
        assert len(call(asset, binary=True)) > 100
    sources = {source['id']: source for source in state['sources']}
    materials = {material['id']: material for material in state['materials']}
    opened_images = 0
    opened_documents = 0
    links = []
    from PIL import Image
    for material in materials.values():
        detail = call('/api/materials/' + material['id'])
        assert detail['source_id'] in sources
        assert sources[detail['source_id']]['display_name']
        assert detail.get('observed_at') or detail.get('first_discovered_at') or detail.get('created_at')
        attachments = detail.get('attachments', [])
        assert [a['id'] for a in attachments] == [a['id'] for a in material.get('attachments', [])]
        for attachment in attachments:
            if attachment.get('state') != 'SAVED':
                continue
            content = call('/api/attachments/' + attachment['id'], binary=True)
            assert hashlib.sha256(content).hexdigest() == attachment['sha256']
            assert len(content) == attachment['size']
            if attachment['mime'].startswith('image/'):
                with Image.open(io.BytesIO(content)) as picture:
                    picture.load()
                    assert picture.width and picture.height
                opened_images += 1
            else:
                opened_documents += 1
        links.append({'material_id': material['id'], 'source_id': material['source_id'],
                      'attachment_ids': [a['id'] for a in attachments], 'publication_time': material.get('publication_time') or material.get('source_time_raw')})
    for product in state['products']:
        assert product['source_item_ids'] and all(x in materials for x in product['source_item_ids'])
    pending_images = 0
    with sqlite3.connect((args.data_dir / 'workbench.sqlite3').resolve().as_uri() + '?mode=ro', uri=True) as db:
        candidates = [json.loads(row[0]) for row in db.execute('SELECT data FROM pending_candidates')]
        for candidate in candidates:
            assert candidate.get('imported') and candidate.get('executable') is False
            for index, attachment in enumerate(candidate.get('item', {}).get('attachments', [])):
                if attachment.get('state') not in {'SAVED', 'STAGED'}:
                    continue
                content = call('/api/background/candidates/' + candidate['id'] + '/attachments/' + str(index), binary=True)
                assert hashlib.sha256(content).hexdigest() == attachment['sha256']
                assert len(content) == attachment['size']
                if attachment.get('mime', '').startswith('image/'):
                    with Image.open(io.BytesIO(content)) as picture:
                        picture.load()
                    pending_images += 1
        assert db.execute("SELECT COUNT(*) FROM records WHERE kind IN ('jobs','background_jobs','checkpoints','native_sessions','background_status')").fetchone()[0] == 0
        assert db.execute('SELECT COUNT(*) FROM source_index').fetchone()[0] == 0
    assert len(materials) > 0 and len(state['products']) > 0
    operations = []
    if args.exercise:
        assert health.get('imported_dataset'), 'Business exercise requires an imported dataset marker'
        product = state['products'][0]
        note = str(product.get('notes') or '')
        edited = call('/api/products/' + product['id'], {'notes': note + '\n部署验证：本地编辑。'}, method='PUT')
        assert edited['notes'].endswith('部署验证：本地编辑。')
        restored = call('/api/products/' + product['id'], {'notes': product.get('notes')}, method='PUT')
        assert restored['notes'] == product.get('notes')
        versions = call('/api/products/' + product['id'] + '/versions')
        assert len(versions) >= 3
        operations.append('product edit, version history, original note restored')
        matching = call('/api/match', {'requirements': {}})
        assert matching['matched'] or matching['needs_verification']
        operations.append('structured matching')
        rec = call('/api/recommendations', {'product_ids': [p['id'] for p in state['products']], 'requirements': {}})
        exported = call('/api/recommendations/' + rec['id'] + '/export', {})
        text_bytes = call(exported['text_url'], binary=True)
        assert '来源' in text_bytes.decode('utf-8')
        image_bytes = call(exported['image_url'], binary=True)
        with Image.open(io.BytesIO(image_bytes)) as picture:
            picture.load()
            assert picture.width > 100 and picture.height > 100
        operations.append('comparison and Chinese text/PNG export')
        weekly = call('/api/weekly', {'title': '部署验证周汇总', 'product_ids': [product['id']], 'recommendation_ids': [rec['id']]})
        weekly_export = call('/api/weekly/' + weekly['id'] + '/export', {})
        assert '资料整理时间' in call(weekly_export['text_url'], binary=True).decode('utf-8')
        operations.append('weekly collection and Chinese text export')
    after = call('/api/health')
    assert after.get('live_collection_enabled') is False
    result = {'status': 'PASS', 'schema_version': health['schema_version'], 'imported_dataset': health.get('imported_dataset'),
              'counts': {kind: len(state[kind]) for kind in ['materials', 'products', 'sources', 'accounts', 'cases', 'recommendations', 'weekly']},
              'images_opened_from_materials': opened_images, 'documents_opened_from_materials': opened_documents,
              'pending_candidate_images_opened': pending_images,
              'source_links': links, 'business_operations': operations, 'chinese_ui_assets_loaded': len(bundles),
              'live_collection_enabled': False, 'ai_provider_configured': False}
    serialized = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(serialized + '\n', encoding='utf-8')
    print(serialized)


if __name__ == '__main__':
    main()
