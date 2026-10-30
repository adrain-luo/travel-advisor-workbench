import importlib.util
import io
from pathlib import Path
import zipfile


def scanner():
    path = Path(__file__).resolve().parents[1] / 'scripts' / 'privacy_scan.py'
    spec = importlib.util.spec_from_file_location('release_scanner', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_archive_path_identity_is_detected_without_reporting_value(tmp_path):
    with zipfile.ZipFile(tmp_path / 'bundle.zip', 'w') as archive:
        archive.writestr('images/synthetic-owner-name.png', b'innocuous')
    result = scanner().scan(tmp_path, {'synthetic-owner-name': 'self'})
    assert result['status'] == 'FAIL'
    assert any(f['category'] == 'excluded-owner-in-path' for f in result['findings'])
    assert 'synthetic-owner-name' not in str(result)


def test_nested_archive_credential_filename_is_detected(tmp_path):
    nested = io.BytesIO()
    with zipfile.ZipFile(nested, 'w') as archive:
        archive.writestr('data/credential.dpapi', b'encrypted-synthetic-fixture')
    with zipfile.ZipFile(tmp_path / 'handoff.zip', 'w') as archive:
        archive.writestr('data.zip', nested.getvalue())
    result = scanner().scan(tmp_path, {})
    assert result['status'] == 'FAIL'
    assert any(f['category'] == 'forbidden-artifact' for f in result['findings'])


def test_safe_nested_archive_passes(tmp_path):
    with zipfile.ZipFile(tmp_path / 'data.zip', 'w') as archive:
        archive.writestr('data/readme.txt', 'sanitized dataset')
    result = scanner().scan(tmp_path, {'synthetic-owner-name': 'self'})
    assert result['status'] == 'PASS'
