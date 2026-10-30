"""Offline index/diff tests: fixture files only, no native client or business DB."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import uuid

import pytest

from backend.background import chat, moments, processing_index
from backend.background.native import BackgroundNative, NativeError

ACCOUNT, FRIEND = chat.AUTHORIZED_ACCOUNT, chat.AUTHORIZED_FRIEND
TABLE = "Msg_" + hashlib.md5(FRIEND.encode()).hexdigest()


def sns(tid, epoch, text="fixture"):
    return f'<SnsDataItem><TimelineObject><id>{tid}</id><username>{FRIEND}</username><createTime>{epoch}</createTime><contentDesc>{text}</contentDesc><ContentObject><mediaList><media><id>image</id><type>2</type><url key="private-key-fixture">https://fixture.invalid/image</url></media></mediaList></ContentObject></TimelineObject></SnsDataItem>'


def adapter(tmp_path, monkeypatch, kind):
    account = tmp_path / (ACCOUNT + "_fixture"); account.mkdir()
    native = BackgroundNative(tmp_path / "owned", {"expected_account_id": ACCOUNT, "expected_friend_id": FRIEND})
    native._identity = (1, 2, str(account).casefold(), "fixture.exe")
    native._friend = FRIEND
    native._binding = {"account_directory": str(account)}
    monkeypatch.setattr(native, "bind", lambda: {"account_native_id": ACCOUNT, "friend_native_id": FRIEND})
    source = tmp_path / "fixture-source.db"
    with closing(sqlite3.connect(source)) as db, db:
        if kind == "moments":
            db.execute("CREATE TABLE SnsTimeLine(tid INTEGER PRIMARY KEY,user_name,content)")
            db.executemany("INSERT INTO SnsTimeLine VALUES(?,?,?)", [
                (1, FRIEND, sns(1, 100)), (2, FRIEND, sns(2, 200)), (3, FRIEND, sns(3, 200)),
                (99, "outside-selected-source", "not inspected")])
        else:
            db.execute("CREATE TABLE Name2Id(user_name)")
            db.executemany("INSERT INTO Name2Id(rowid,user_name) VALUES(?,?)", [(1, ACCOUNT), (2, FRIEND)])
            db.execute(f"CREATE TABLE {TABLE}(local_id INTEGER PRIMARY KEY,server_id TEXT,local_type INTEGER,real_sender_id INTEGER,create_time INTEGER,sort_seq INTEGER,message_content BLOB,packed_info_data BLOB,compress_content BLOB,source BLOB)")
            db.executemany(f"INSERT INTO {TABLE} VALUES(?,?,?,?,?,?,?,NULL,NULL,NULL)", [
                (1, "18446744073709551615", 1, 2, 100, 1, "first fixture"),
                (2, "9007199254740993", 1, 1, 200, 2, "second fixture")])
    calls = {"snapshots": 0}
    def stamp(source_kind):
        return hashlib.sha256(source.read_bytes()).hexdigest()
    def snapshot(kind):
        calls["snapshots"] += 1
        sid = uuid.uuid4().hex
        folder = native.private / "snapshots" / sid; folder.mkdir(parents=True)
        path = folder / "sealed.db"; shutil.copyfile(source, path)
        result = {"snapshot_id": sid, "identity": list(native._identity), "stable": True,
                  "kind": kind, "files": [{"path": str(path), "sha256": stamp(kind),
                    "relative_path": "sns/sns.db" if kind == "sns" else "message/message_0.db"}]}
        (folder / "manifest.json").write_text(json.dumps(result), encoding="utf-8")
        native._snapshots[sid] = result
        return result
    monkeypatch.setattr(native, "source_change_stamp", stamp)
    monkeypatch.setattr(native, "_snapshot", snapshot)
    return native, source, calls


@pytest.mark.parametrize("kind", ["moments", "chat"])
def test_quiet_checks_and_forced_index_do_not_reread_unchanged_content(tmp_path, monkeypatch, kind):
    native, source, calls = adapter(tmp_path, monkeypatch, kind)
    first = native.discover_processing(kind, {}, known_revisions={})
    known = {item["event_key"]: item["native_revision"] for item in first["items"]}
    assert len(known) == (3 if kind == "moments" else 2)
    assert first["metrics"]["content_reads"] == len(known)
    native.release_snapshot(first["snapshot_id"])
    references = set((native.private / "references").glob("*.json"))
    for _ in range(2):
        quiet = native.discover_processing(kind, {}, known_revisions=known, previous_change_stamp=first["change_stamp"])
        assert quiet["source_unchanged"] and quiet["snapshot_id"] is None
        assert quiet["metrics"]["index_entries_inspected"] == quiet["metrics"]["content_reads"] == 0
    assert calls["snapshots"] == 1
    def no_full_parse(*args, **kwargs):
        raise AssertionError("Unchanged source body was parsed again")
    monkeypatch.setattr(moments, "parse_selected_post", no_full_parse)
    monkeypatch.setattr(chat, "_record", no_full_parse)
    reconciled = native.discover_processing(kind, {}, known_revisions=known,
                                           previous_change_stamp=first["change_stamp"], force=True)
    assert not reconciled["items"] and reconciled["metrics"]["content_reads"] == 0
    assert reconciled["metrics"]["index_entries_inspected"] == len(known)
    assert reconciled["metrics"]["index_payload_bytes_hashed"] > 0
    assert set((native.private / "references").glob("*.json")) == references


@pytest.mark.parametrize("kind", ["moments", "chat"])
def test_late_old_arrival_and_revision_load_only_two_changed_bodies(tmp_path, monkeypatch, kind):
    native, source, _ = adapter(tmp_path, monkeypatch, kind)
    before = native.discover_processing(kind, {}, known_revisions={})
    known = {item["event_key"]: item["native_revision"] for item in before["items"]}
    with closing(sqlite3.connect(source)) as db, db:
        if kind == "moments":
            db.execute("INSERT INTO SnsTimeLine VALUES(?,?,?)", (4, FRIEND, sns(4, 50, "late historical")))
            db.execute("UPDATE SnsTimeLine SET content=? WHERE tid=2", (sns(2, 200, "changed revision"),))
        else:
            db.execute(f"INSERT INTO {TABLE} VALUES(3,'3',1,2,50,0,'late historical',NULL,NULL,NULL)")
            db.execute(f"UPDATE {TABLE} SET message_content='changed revision' WHERE local_id=2")
    page = native.discover_processing(kind, {}, known_revisions=known, previous_change_stamp=before["change_stamp"])
    assert page["metrics"]["new_or_changed"] == page["metrics"]["content_reads"] == 2
    assert sorted(item["text"] for item in page["items"]) == ["changed revision", "late historical"]
    assert all(item["native_revision"] != known.get(item["event_key"]) for item in page["items"])


@pytest.mark.parametrize("kind", ["moments", "chat"])
def test_restart_resumes_immutable_index_cursor_without_skipping_ties(tmp_path, monkeypatch, kind):
    native, _, calls = adapter(tmp_path, monkeypatch, kind)
    first = native.discover_processing(kind, {}, limit=1, known_revisions={})
    cursor = first["cursor"]
    native._snapshots.clear()  # Simulated adapter restart: manifest persists.
    known = {item["event_key"]: item["native_revision"] for item in first["items"]}
    items = list(first["items"])
    while cursor:
        page = native.discover_processing(kind, {}, cursor=cursor, limit=1, known_revisions=known)
        items.extend(page["items"])
        known.update({item["event_key"]: item["native_revision"] for item in page["items"]})
        cursor = page["cursor"]
    assert len(items) == len({item["event_key"] for item in items}) == (3 if kind == "moments" else 2)
    assert calls["snapshots"] == 1


def test_skip_cleanup_keeps_receipt_and_protected_reference_without_raw_archive(tmp_path, monkeypatch):
    native, _, _ = adapter(tmp_path, monkeypatch, "moments")
    page = native.discover_processing("moments", {}, known_revisions={})
    item = page["items"][0]
    receipt = {"event_key": item["event_key"], "native_revision": item["native_revision"], "disposition": "SKIP_IRRELEVANT"}
    protected = item["attachments"][0]["private_ref"]
    result = native.discard_private([item], protected_refs={protected})
    assert result["removed_references"] == 1
    assert not (native.private / "references" / (item["private_source_ref"] + ".json")).exists()
    assert (native.private / "references" / (protected + ".json")).exists()
    native.discard_private([protected])
    assert receipt["disposition"] == "SKIP_IRRELEVANT"  # Cleanup is not a receipt mutation.
    again = native.discover_processing("moments", {}, known_revisions={receipt["event_key"]: receipt["native_revision"]})
    assert receipt["event_key"] not in {value["event_key"] for value in again["items"]}


def test_explicit_reply_preserves_large_server_id_and_rejects_foreign_scope(tmp_path, monkeypatch):
    native, source, _ = adapter(tmp_path, monkeypatch, "chat")
    reply = f'<msg><appmsg><title>还有3个位置</title><type>57</type><refermsg><svrid>18446744073709551615</svrid><fromusr>{FRIEND}</fromusr><chatusr>{FRIEND}</chatusr><content>private quoted body</content></refermsg></appmsg></msg>'
    with closing(sqlite3.connect(source)) as db, db:
        db.execute(f"UPDATE {TABLE} SET local_type=49,message_content=? WHERE local_id=2", (reply,))
    page = native.discover_processing("chat", {}, known_revisions={})
    item = next(value for value in page["items"] if value["local_id"] == "2")
    assert item["text"] == "还有3个位置"
    assert item["reply"]["native_server_id"] == "18446744073709551615"
    assert item["reply"]["relationship_verified"]
    assert "private quoted body" not in json.dumps(item)
    with closing(sqlite3.connect(source)) as db, db:
        db.execute(f"UPDATE {TABLE} SET message_content=? WHERE local_id=2", (reply.replace(f"<fromusr>{FRIEND}</fromusr>", "<fromusr>other-account</fromusr>"),))
    page = native.discover_processing("chat", {}, known_revisions={})
    item = next(value for value in page["items"] if value["local_id"] == "2")
    assert "reply" not in item and "EXPLICIT_REPLY_SCOPE_UNVERIFIED" in item["issues"]


def test_chat_index_handles_binary_payload_declared_as_text_without_decoding(tmp_path, monkeypatch):
    native, source, _ = adapter(tmp_path, monkeypatch, "chat")
    with closing(sqlite3.connect(source)) as db, db:
        db.execute(f"UPDATE {TABLE} SET message_content=CAST(x'fffe00' AS TEXT) WHERE local_id=2")
    first = native.discover_processing("chat", {}, known_revisions={})
    known = {item["event_key"]: item["native_revision"] for item in first["items"]}
    again = native.discover_processing("chat", {}, known_revisions=known)
    assert not again["items"] and again["metrics"]["content_reads"] == 0


def test_real_change_stamp_is_bounded_and_detects_wal_creation(tmp_path, monkeypatch):
    account = tmp_path / (ACCOUNT + "_fixture")
    source = account / "db_storage" / "sns" / "sns.db"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"fixture" * 10000)
    native = BackgroundNative(tmp_path / "owned", {"expected_account_id": ACCOUNT, "expected_friend_id": FRIEND})
    native._friend = FRIEND; native._identity = (1, 2, str(account), "fixture.exe")
    native._binding = {"account_directory": str(account)}
    monkeypatch.setattr(native, "bind", lambda: {})
    monkeypatch.setattr(native, "_paths", lambda kind: {"sns": str(source)})
    first = native.source_change_stamp("moments")
    assert native._stamp_bytes["moments"] == 8192
    assert native.source_change_stamp("moments") == first
    Path(str(source) + "-wal").write_bytes(b"fixture-wal")
    assert native.source_change_stamp("moments") != first
    assert not (native.private / "snapshots").exists()


def test_processing_date_range_and_parse_failure_remain_separate(tmp_path, monkeypatch):
    native, source, _ = adapter(tmp_path, monkeypatch, "moments")
    bounded = native.discover_processing("moments", {"start_epoch": 100, "end_epoch": 200}, known_revisions={})
    assert [item["native_post_id"] for item in bounded["items"]] == ["1"]
    with closing(sqlite3.connect(source)) as db, db:
        db.execute("UPDATE SnsTimeLine SET content='malformed' WHERE tid=2")
    result = native.discover_processing("moments", {}, known_revisions={})
    assert result["parse_issues"][0]["native_revision"]
    assert result["coverage"] == "UNKNOWN"
    assert (native.private / "snapshots" / result["snapshot_id"]).is_dir()
    assert len(result["items"]) == 2


def test_private_cleanup_advances_past_protected_prefix(tmp_path):
    native = BackgroundNative(tmp_path, {})
    directory = native.private / "references"; directory.mkdir()
    tokens = [str(number).zfill(32) for number in (1, 2, 3)]
    for token in tokens:
        path = directory / (token + '.json')
        path.write_text('{}')
        # Test cursor progress independently of Windows timestamp granularity.
        import os
        os.utime(path, (1_600_000_000, 1_600_000_000))
    first = native.gc_private_references(tokens[:2], older_than_seconds=0, max_files=2)
    assert first["removed_references"] == 0 and first["scanned_references"] == 2
    second = native.gc_private_references(tokens[:2], older_than_seconds=0, max_files=2)
    assert second["removed_references"] == 1
    assert not (directory / (tokens[2] + ".json")).exists()


@pytest.mark.parametrize("kind", ["moments", "chat"])
def test_bounded_initial_history_baselines_old_outside_range_but_finds_future_arrival(tmp_path, monkeypatch, kind):
    native, source, calls = adapter(tmp_path, monkeypatch, kind)
    known, processed, baseline, cursor = {}, [], [], None
    while True:
        page = native.discover_processing(kind, {"start_epoch": 100, "end_epoch": 200},
            cursor=cursor, limit=1, known_revisions=known, baseline_index=True)
        processed.extend(page["items"])
        baseline.extend(page["baseline_entries"])
        known.update({row["event_key"]: row["native_revision"] for row in page["baseline_entries"]})
        cursor = page["cursor"]
        if page["exhausted"]:
            break
    assert len(processed) == 1
    assert len(baseline) == (3 if kind == "moments" else 2)
    assert all(set(row) == {"event_key", "native_revision", "publication_epoch"} for row in baseline)
    assert calls["snapshots"] == 1
    old_keys = set(known)
    with closing(sqlite3.connect(source)) as db, db:
        if kind == "moments":
            db.execute("INSERT INTO SnsTimeLine VALUES(?,?,?)", (4, FRIEND, sns(4, 300, "future newly available")))
        else:
            db.execute(f"INSERT INTO {TABLE} VALUES(3,'3',1,2,300,3,'future newly available',NULL,NULL,NULL)")
    incremental = native.discover_processing(kind, {}, known_revisions=known)
    assert len(incremental["items"]) == 1
    assert incremental["items"][0]["text"] == "future newly available"
    assert incremental["items"][0]["event_key"] not in old_keys
    assert incremental["metrics"]["content_reads"] == 1
