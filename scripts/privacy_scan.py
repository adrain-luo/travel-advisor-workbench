"""Local release scanner. Known identities remain in a separate private input file.

This supplements selected-field export and documented visual review; it does not
claim that a regex can identify every credential or identity in image pixels.
Reports contain categories and artifact locations, never matching secret values.
"""
from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
import re
import subprocess
import urllib.parse
import zipfile

PATTERNS = {
    'private-key': rb'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----',
    'github-token': rb'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b',
    'aws-access-key': rb'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b',
    'provider-secret': rb'\bsk-(?:proj-)?[A-Za-z0-9_-]{32,}\b',
    'signed-media-url': rb'https?[^\s"<>]{0,300}[?&](?:token|access_token|signature|sig|authkey|key|x-amz-signature)=[^\s"<>]{8,}',
}
FORBIDDEN_NAMES = {'credential.dpapi', 'live-binding.json', '.env', 'identity-map.json',
                   'consistent-backup.zip', 'instance.lock', 'server.json'}


def variants(value):
    strings = {value, json.dumps(value, ensure_ascii=True)[1:-1], urllib.parse.quote(value),
               value.replace('\\', '\\\\')}
    return {s.encode(encoding) for s in strings for encoding in ('utf-8', 'utf-16-le', 'utf-16-be') if s}


def scan(root, identities, *, git=False):
    needles = {b for raw in identities for b in variants(raw)}
    findings = []
    counters = {'files': 0, 'archive_members': 0, 'git_objects': 0, 'image_metadata': 0}
    def safe_label(label):
        for raw in sorted(identities, key=len, reverse=True):
            label = label.replace(raw, '[excluded-identity]')
            label = label.replace(urllib.parse.quote(raw), '[excluded-identity]')
        for pattern in PATTERNS.values():
            label = re.sub(pattern, b'[excluded-secret]', label.encode('utf-8')).decode('utf-8', errors='replace')
        return label

    def inspect_name(label, name):
        location = safe_label(label)
        payload = name.encode('utf-8')
        if any(value in payload for value in needles):
            findings.append({'category': 'excluded-owner-in-path', 'location': location})
        for category, pattern in PATTERNS.items():
            if re.search(pattern, payload):
                findings.append({'category': category + '-in-path', 'location': location})
        parts = name.replace('\\', '/').split('/')
        if any(part in FORBIDDEN_NAMES or part in {'.venv', 'node_modules', 'background-private'} for part in parts):
            findings.append({'category': 'forbidden-artifact', 'location': location})

    def inspect(label, data, depth=0):
        label = safe_label(label)
        for name, pattern in PATTERNS.items():
            if re.search(pattern, data):
                findings.append({'category': name, 'location': label})
        if any(value in data for value in needles):
            findings.append({'category': 'excluded-owner-identity', 'location': label})
        if depth < 5 and zipfile.is_zipfile(io.BytesIO(data)):
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                for item in archive.infolist():
                    inspect_name(label + '!' + item.filename, item.filename)
                    if not item.is_dir():
                        counters['archive_members'] += 1
                        if item.file_size > 512 * 1024 * 1024:
                            findings.append({'category': 'uninspected-oversize-member', 'location': label + '!' + item.filename})
                        else:
                            inspect(label + '!' + item.filename, archive.read(item), depth + 1)
        if data.startswith((b'\xff\xd8\xff', b'\x89PNG\r\n', b'GIF8', b'RIFF')):
            try:
                from PIL import Image
                with Image.open(io.BytesIO(data)) as picture:
                    metadata = repr(picture.info) + repr(dict(picture.getexif()))
                    counters['image_metadata'] += 1
                    if any(v in metadata.encode('utf-8') for v in needles):
                        findings.append({'category': 'owner-in-image-metadata', 'location': label})
            except (ImportError, OSError, ValueError):
                findings.append({'category': 'image-metadata-not-inspected', 'location': label})
    for path in sorted(root.rglob('*')):
        if not path.is_file() or any(part in {'.git', '.venv', 'node_modules', '__pycache__', '.pytest_cache', '.local'} for part in path.relative_to(root).parts):
            continue
        label = path.relative_to(root).as_posix()
        counters['files'] += 1
        inspect_name(label, label)
        inspect(label, path.read_bytes())
    if git:
        result = subprocess.run(['git', 'cat-file', '--batch-all-objects', '--batch-check=%(objectname) %(objecttype)'],
                                cwd=root, capture_output=True, text=True, check=True)
        for line in result.stdout.splitlines():
            oid, kind = line.split()
            payload = subprocess.run(['git', 'cat-file', kind, oid], cwd=root, capture_output=True, check=True).stdout
            counters['git_objects'] += 1
            inspect('git-object:' + oid, payload)
        staged = subprocess.run(['git', 'diff', '--cached', '--name-only', '-z'], cwd=root, capture_output=True, check=True).stdout
        inspect('git-index-paths', staged)
    return {'status': 'PASS' if not findings else 'FAIL', 'checks': counters, 'findings': findings,
            'scope': 'Known-value, credential-format, container, image-metadata and optional Git object scan; visual-media decisions are recorded separately.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('--identity-map', type=Path, required=True)
    parser.add_argument('--git', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    mapping = json.loads(args.identity_map.read_text(encoding='utf-8'))
    result = scan(args.root, mapping.get('replacements', mapping), git=args.git)
    text = json.dumps(result, indent=2)
    if args.output:
        args.output.write_text(text + '\n', encoding='utf-8')
    print(text)
    raise SystemExit(0 if result['status'] == 'PASS' else 1)


if __name__ == '__main__':
    main()
