"""Offline feasibility-probe boundaries; never evidence of WeChat support."""
import json
import sqlite3

import pytest

from scripts.probe_background_access import probe


def test_probe_preserves_sources_and_does_not_promote_cache_to_records(tmp_path):
    root = tmp_path / "wechat"
    account = root / "wxid_fixture"
    database = account / "db_storage" / "contact" / "contact.db"
    database.parent.mkdir(parents=True)
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE contact(secret TEXT)")
        connection.execute("INSERT INTO contact VALUES('must not appear in report')")
    opaque = account / "db_storage" / "sns" / "sns.db"
    opaque.parent.mkdir(parents=True)
    opaque.write_bytes(b"opaque database fixture" * 200)
    media = account / "business" / "sns" / "fixture"
    media.parent.mkdir(parents=True)
    media.write_bytes(b"\xff\xd8\xfffixture bytes, not real image")
    reference = tmp_path / "known-manual.jpg"
    reference.write_bytes(media.read_bytes())
    before = {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()}
    report = probe(root, [reference], tmp_path / "evidence" / "probe.json")
    row = report["accounts"][0]
    assert row["databases"]["contact/contact.db"]["ordinary_sqlite_readable"] is True
    assert row["databases"]["sns/sns.db"]["ordinary_sqlite_readable"] is False
    assert all(value["rows_read"] == 0 for value in row["databases"].values())
    assert "must not appear" not in json.dumps(report)
    assert report["source_records_saved"] == report["media_associations_verified"] == 0
    assert report["historical_coverage"] == "UNKNOWN"
    match = row["media"]["business/sns"]["exact_reference_matches"][0]
    assert match["record_association_verified"] is False
    assert before == {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()}
    with pytest.raises(ValueError, match="outside"):
        probe(root, [], root / "forbidden.json")
