"""Offline boundaries for maintained native background access; no client access."""
from contextlib import closing
import hashlib
import hmac
import json
from pathlib import Path
import sqlite3
import struct
import sys

import pytest

from backend.background import binding, moments, snapshot
from backend.background.native import BackgroundNative, NativeError


def xml(tid, stamp, author="friend", text="ordinary retained text"):
    return f'<TimelineObject><id>{tid}</id><username>{author}</username><createTime>{stamp}</createTime><contentDesc>{text}</contentDesc><ContentObject><mediaList><media><id>one</id><type>2</type><url key="private-fixture-key">https://example.invalid/private-fixture-url</url></media><media><id>two</id><type>2</type><url>https://example.invalid/two</url></media></mediaList></ContentObject></TimelineObject>'


@pytest.fixture
def adapter(tmp_path, monkeypatch):
    native = BackgroundNative(tmp_path, {"expected_account_id": "account", "expected_friend_id": "friend"})
    native._friend = "friend"
    native._identity = (1, 2, "fixture", "fixture.exe")
    native._binding = {"account_directory": str(tmp_path / "source")}
    monkeypatch.setattr(native, "bind", lambda: {"identity_verified": True})
    path = native.private / "fixture.db"
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("CREATE TABLE SnsTimeLine(tid INTEGER PRIMARY KEY,user_name TEXT,content TEXT)")
        rows = [(1, "friend", xml(1, 1483228800)), (2, "friend", xml(2, 1735689600)),
                (3, "friend", xml(3, 1735689600)), (4, "friend", xml(4, 1767225600)),
                (99, "unrelated", xml(99, 1735689600, "unrelated"))]
        db.executemany("INSERT INTO SnsTimeLine VALUES(?,?,?)", rows)
    sid = "a" * 32
    snap = {"snapshot_id": sid, "kind": "sns", "identity": list(native._identity),
            "files": [{"path": str(path), "sha256": snapshot.digest(path), "relative_path": "sns/sns.db"}]}
    native._snapshots[sid] = snap
    monkeypatch.setattr(native, "_snapshot", lambda kind: snap)
    return native, path


def test_all_dates_retained_and_stable_ties(adapter):
    native, _ = adapter
    first = native.discover("moments", {}, limit=2)
    second = native.discover("moments", {}, cursor=first["cursor"], limit=2)
    assert [i["native_id"] for i in first["items"] + second["items"]] == ["4", "3", "2", "1"]
    assert second["exhausted"] and second["coverage"] == "UNKNOWN"
    assert all(i["identity_verified"] and i["text"] == "ordinary retained text" for i in first["items"])


def test_date_bounds_are_half_open_and_do_not_skip_same_second(adapter):
    native, _ = adapter
    page = native.discover("moments", {"start_epoch": 1735689600, "end_epoch": 1767225600})
    assert [i["native_id"] for i in page["items"]] == ["3", "2"]


def test_public_items_contain_no_raw_xml_url_or_record_key(adapter):
    native, _ = adapter
    page = native.discover("moments", {}, limit=1)
    encoded = json.dumps(page)
    assert "private-fixture" not in encoded and "TimelineObject" not in encoded
    assert [a["index"] for a in page["items"][0]["attachments"]] == [0, 1]
    assert all(a["type"] == "image" and a["private_ref"] for a in page["items"][0]["attachments"])
    assert any("private-fixture-key" in p.read_text(encoding="utf-8") for p in (native.private / "references").glob("*.json"))


def test_cursor_rejects_changed_snapshot_and_scope(adapter):
    native, path = adapter
    cursor = native.discover("moments", {}, limit=1)["cursor"]
    with pytest.raises(NativeError, match="CURSOR_SCOPE_MISMATCH"):
        native.discover("moments", {"start_epoch": 1}, cursor=cursor)
    with path.open("ab") as stream:
        stream.write(b"changed")
    with pytest.raises(NativeError, match="IMMUTABLE_SNAPSHOT_CHANGED"):
        native.discover("moments", {}, cursor=cursor)


def test_timeline_wrapper_media_scope_and_ambiguity():
    timeline = xml(1, 1735689600)
    raw = "<SnsDataItem>" + timeline + "<LocalExtraInfo><mediaList><media/></mediaList></LocalExtraInfo></SnsDataItem>"
    parsed = moments.parse_selected_post(1, "friend", raw, author_id="friend")
    assert len(parsed["media"]) == 2 and "LocalExtraInfo" not in parsed["raw_xml"]
    with pytest.raises(moments.ReaderError, match="AMBIGUOUS"):
        moments.parse_selected_post(1, "friend", "<SnsDataItem>" + timeline * 2 + "</SnsDataItem>", author_id="friend")
    with pytest.raises(moments.ReaderError, match="AUTHOR_FILTER"):
        moments.parse_selected_post(1, "friend", raw, author_id="")


def test_parse_gaps_not_unqualified_history_endpoint(adapter):
    native, path = adapter
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("UPDATE SnsTimeLine SET content='invalid' WHERE tid=4")
    native._snapshots["a" * 32]["files"][0]["sha256"] = snapshot.digest(path)
    page = native.discover("moments", {})
    assert page["stop_reason"] == "LOCAL_ROWS_EXHAUSTED_WITH_PARSE_GAPS"
    assert page["parse_issues"] == [{"native_tid": "4", "code": "SNS_XML_PARSE_FAILED"}]


def test_failed_initial_discovery_releases_only_new_owned_snapshot(adapter):
    native, old_path = adapter
    sid = "a" * 32
    folder = native.private / "snapshots" / sid
    folder.mkdir(parents=True)
    path = folder / "sns.db"
    old_path.rename(path)
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("DROP TABLE SnsTimeLine")
    snap = native._snapshots[sid]
    snap["files"][0].update(path=str(path), sha256=snapshot.digest(path))
    (folder / "manifest.json").write_text(json.dumps(snap), encoding="utf-8")
    with pytest.raises(sqlite3.OperationalError):
        native.discover("moments", {})
    assert not folder.exists() and sid not in native._snapshots
    audit = json.loads((native.private / "audit" / (sid + ".json")).read_text(encoding="utf-8"))
    assert audit["disposition"] == "failed_initial_discovery"
    assert audit["reason"] == "SNAPSHOT_DISCOVERY_QUERY_FAILED"
    assert audit["coverage"] == "UNKNOWN"


def test_parse_gap_page_preserves_its_snapshot(adapter, monkeypatch):
    native, path = adapter
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("UPDATE SnsTimeLine SET content='malformed' WHERE tid=4")
    native._snapshots["a" * 32]["files"][0]["sha256"] = snapshot.digest(path)
    released = []
    monkeypatch.setattr(native, "release_snapshot", lambda *args, **kwargs: released.append(args))
    page = native.discover("moments", {})
    assert page["parse_issues"] and page["coverage"] == "UNKNOWN"
    assert not released and path.exists()


def test_changed_process_invalidates_key_cache_before_read(tmp_path, monkeypatch):
    account = tmp_path / "wxid_account_suffix"; account.mkdir()
    native = BackgroundNative(tmp_path / "out", {"expected_account_id": "wxid_account"})
    report = {"pid": 1, "creation_filetime": 2, "executable_path": "fixture.exe", "account_directory": str(account), "process_to_database_binding_complete": True}
    monkeypatch.setattr(binding, "discover_pid", lambda: 1)
    monkeypatch.setattr(binding, "probe_bounded", lambda pid: dict(report))
    native._observe(); native._keys["sns"] = b"fixture"
    native._image_candidate = {"aes_key": b"fixture"}
    native._image_candidate_identity = native._identity
    report["creation_filetime"] = 3
    with pytest.raises(NativeError, match="ACCOUNT_OR_PROCESS_CHANGED"):
        native._observe()
    assert native._keys == {} and native._binding is None
    assert native._image_candidate is None and native._image_candidate_identity is None


def test_exact_contact_mapping_rejects_ambiguity(tmp_path):
    path = tmp_path / "contact.db"
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("CREATE TABLE contact(username,nick_name,remark)")
        db.executemany("INSERT INTO contact VALUES(?,?,?)", [("a", "friend", ""), ("b", "", "friend")])
    assert moments.resolve_contact(path, owned_root=tmp_path, exact_name="friend")["status"] == "AMBIGUOUS"


def test_copy_cannot_leave_bound_account(tmp_path):
    account = tmp_path / "account"; account.mkdir()
    other = tmp_path / "other.db"; other.write_bytes(b"fixture")
    with pytest.raises((snapshot.SnapshotError, FileNotFoundError)):
        snapshot.capture({"contact": str(other)}, account, tmp_path / "copies")


def test_repeated_discovery_reuses_private_references(adapter):
    native, _ = adapter
    first = native.discover("moments", {})
    count = len(list((native.private / "references").glob("*.json")))
    second = native.discover("moments", {})
    assert first["items"] == second["items"]
    assert len(list((native.private / "references").glob("*.json"))) == count


def test_release_removes_only_completed_owned_snapshot_and_close_keeps_active(tmp_path):
    native = BackgroundNative(tmp_path, {})
    sid = "b" * 32; folder = native.private / "snapshots" / sid; folder.mkdir(parents=True)
    (folder / "manifest.json").write_text(json.dumps({"snapshot_id": sid, "kind": "sns", "stable": True, "validation": {"sns": {"page_hmac_validation": "PASS"}}}), encoding="utf-8")
    (folder / "private.db").write_bytes(b"fixture")
    native._keys["sns"] = b"fixture"
    native._image_candidate = {"aes_key": b"fixture"}
    native.close()
    assert folder.exists() and not native._keys
    assert native._image_candidate is None
    native.release_snapshot(sid)
    assert not folder.exists() and (native.private / "audit" / (sid + ".json")).exists()
    with pytest.raises(NativeError, match="SNAPSHOT_ID_INVALID"):
        native.release_snapshot("../escape")


def test_metadata_timeout_is_bounded_and_does_not_return_partial_binding(monkeypatch):
    import subprocess
    def timeout(*args, **kwargs):
        assert kwargs["timeout"] == 20 and kwargs["stdin"] == subprocess.DEVNULL
        raise subprocess.TimeoutExpired("owned worker", 20)
    monkeypatch.setattr(binding.subprocess, "run", timeout)
    with pytest.raises(RuntimeError, match="PROCESS_BINDING_METADATA_TIMEOUT"):
        binding.probe_bounded(123)


def test_chat_source_private_and_unknown_sender_retained(adapter):
    native, _ = adapter
    record = {"native_id_verified": True, "conversation_id": "friend", "event_key": "fixture",
              "author_id": None, "private_source": {"xml": "fixture-private-token"}, "attachments": []}
    result = native._sanitize(record, "chat")
    assert result["identity_verified"] and not result["sender_identity_verified"]
    assert "fixture-private-token" not in json.dumps(result)
    assert "private_source" not in result and result["private_source_ref"]


@pytest.mark.parametrize("valid", [False, True])
def test_image_candidate_cached_only_after_exact_media_validation(adapter, monkeypatch, valid):
    import types
    from backend.background import chat
    native, _ = adapter
    native._binding["pid"] = 1
    monkeypatch.setattr(native, "_observe", lambda: native._binding)
    candidate = {"aes_key": b"fixture-key-12345", "xor_key": 7}
    seen = []
    def retrieve(reference, output, **kw):
        seen.append(kw.get("image_keys"))
        if kw.get("image_keys") is None:
            return {"state": "RETRY_PENDING", "reason": "CHAT_IMAGE_KEY_REQUIRED"}
        return {"state": "VALIDATED" if valid else "UNAVAILABLE", "reason": None if valid else "CHAT_IMAGE_DECRYPTION_FAILED"}
    monkeypatch.setattr(chat, "retrieve_chat", retrieve)
    probe = types.SimpleNamespace(probe_image_key=lambda report, **kw: (candidate, {"reason": "CANDIDATE_REQUIRES_VALIDATION"}))
    monkeypatch.setitem(sys.modules, "backend.background.image_access", probe)
    ref = native._private_record({"source_kind": "chat", "account_id": "account", "friend_id": "friend", "reference": {"fixture": True}})
    result = native.retrieve({"private_ref": ref}, native.root / "stage")
    assert result["state"] == ("SAVED" if valid else "UNAVAILABLE")
    assert native._image_keys == (candidate if valid else None)
    assert native._image_candidate is None
    assert len(seen) == 2


def test_unsupported_first_image_does_not_starve_later_requested_wxgf(adapter, monkeypatch):
    import types
    from backend.background import chat
    native, _ = adapter
    monkeypatch.setattr(native, "_observe", lambda: native._binding)
    candidate = {"aes_key": b"fixture-key-12345", "xor_key": 7}
    probes, reads = [], []
    def probe(report, **kw):
        probes.append(report)
        return candidate, {"reason": "CANDIDATE_REQUIRES_VALIDATION", "media_validated": False}
    def retrieve(reference, output, **kw):
        reads.append((reference["occurrence"], kw.get("image_keys")))
        if kw.get("image_keys") is None:
            return {"state": "RETRY_PENDING", "reason": "CHAT_IMAGE_KEY_REQUIRED"}
        if reference["occurrence"] == "unsupported":
            return {"state": "UNAVAILABLE", "reason": "CHAT_IMAGE_FORMAT_UNSUPPORTED"}
        return {"state": "VALIDATED", "quality": "unknown_cached_transcoded", "native_source_format": "wxgf"}
    monkeypatch.setattr(chat, "retrieve_chat", retrieve)
    monkeypatch.setitem(sys.modules, "backend.background.image_access", types.SimpleNamespace(probe_image_key=probe))
    def attachment(occurrence):
        return {"private_ref": native._private_record({"source_kind": "chat", "account_id": "account",
            "friend_id": "friend", "reference": {"occurrence": occurrence}})}
    first = native.retrieve(attachment("unsupported"), native.root / "stage")
    assert first["state"] == "UNAVAILABLE" and first["reason"] == "CHAT_IMAGE_FORMAT_UNSUPPORTED"
    assert native._image_keys is None and native._image_candidate is candidate
    second = native.retrieve(attachment("wxgf"), native.root / "stage")
    assert second["state"] == "SAVED" and second["quality"] == "unknown_cached_transcoded"
    assert native._image_keys is candidate and native._image_candidate is None
    assert len(probes) == 1 and [r[0] for r in reads] == ["unsupported", "unsupported", "wxgf", "wxgf"]
    audits = [json.loads(p.read_text()) for p in (native.private / "audit").glob("image-key-*.json")]
    failed = next(a for a in audits if not a["media_validated"])
    assert failed["validation_reason"] == "CHAT_IMAGE_FORMAT_UNSUPPORTED"
    assert failed["candidate_retained_for_requested_occurrence"] is True
    assert any(a["media_validated"] and a["validation_state"] == "VALIDATED" for a in audits)
    encoded = json.dumps(audits)
    assert "fixture-key" not in encoded and "aes_key" not in encoded and "xor_key" not in encoded


@pytest.mark.parametrize("expired", ["age", "attempts", "identity", "approval"])
def test_unverified_image_candidate_cannot_outlive_scope_or_bounds(adapter, monkeypatch, expired):
    from backend.background import chat, native as native_module
    native, _ = adapter
    monkeypatch.setattr(native_module.time, "monotonic", lambda: 1000.0)
    native._image_candidate = {"aes_key": b"fixture-key-12345", "xor_key": 7}
    native._image_candidate_identity = native._identity
    native._image_candidate_at = 999.0
    native._image_probe_at = 999.0
    if expired == "age":
        native._image_candidate_at = 699.0
    elif expired == "attempts":
        native._image_candidate_attempts = 64
    elif expired == "identity":
        native._image_candidate_identity = (9, 9, "other", "other.exe")
    else:
        native.config["passive_key_read_approved"] = False
    seen = []
    def retrieve(reference, output, **kw):
        seen.append(kw.get("image_keys"))
        return {"state": "RETRY_PENDING", "reason": "CHAT_IMAGE_KEY_REQUIRED"}
    monkeypatch.setattr(chat, "retrieve_chat", retrieve)
    ref = native._private_record({"source_kind": "chat", "account_id": "account", "friend_id": "friend", "reference": {"fixture": True}})
    result = native.retrieve({"private_ref": ref}, native.root / "stage")
    assert result["state"] == ("UNAVAILABLE" if expired == "approval" else "RETRY")
    assert seen == [None] and native._image_candidate is None


def test_authenticated_wal_uses_only_committed_prefix(tmp_path):
    dependency = Path(sys.base_prefix) / "Lib" / "site-packages"
    if dependency.is_dir():
        sys.path.append(str(dependency))
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    source = tmp_path / "plain.db"
    with closing(sqlite3.connect(source)) as db, db:
        db.execute("PRAGMA page_size=4096"); db.execute("PRAGMA user_version=1")
    plain = bytearray(source.read_bytes()); plain[20] = 80; plain[105:107] = struct.pack(">H", 4016)
    key, salt, iv = bytes(range(32)), bytes(range(16)), bytes(range(16, 32))
    mac = hashlib.pbkdf2_hmac("sha512", key, bytes(x ^ 0x3A for x in salt), 2, dklen=32)
    def encrypt(page):
        enc = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
        body = enc.update(bytes(page[16:4016])) + enc.finalize()
        return salt + body + iv + hmac.new(mac, body + iv + struct.pack("<I", 1), hashlib.sha512).digest()
    encrypted = encrypt(plain); (tmp_path / "encrypted.db").write_bytes(encrypted)
    header = struct.pack(">6I", 0x377F0682, 3007000, 4096, 0, 42, 43)
    checksum = moments._checksum(header, "<"); wal = header + struct.pack(">II", *checksum)
    for version, commit in [(2, 1), (3, 0)]:
        page = bytearray(plain); page[60:64] = struct.pack(">I", version); page = encrypt(page)
        first = struct.pack(">II", 1, commit); checksum = moments._checksum(first + page, "<", checksum)
        wal += first + header[16:24] + struct.pack(">II", *checksum) + page
    (tmp_path / "encrypted.db-wal").write_bytes(wal)
    result = moments.decrypt_snapshot(tmp_path / "encrypted.db", tmp_path / "encrypted.db-wal", key, tmp_path / "out.db", owned_root=tmp_path,
                                      expected_database_sha256=hashlib.sha256(encrypted).hexdigest(), expected_wal_sha256=hashlib.sha256(wal).hexdigest())
    assert result["wal"]["uncommitted_frames_ignored"] == 1
    with closing(sqlite3.connect(tmp_path / "out.db")) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 2
    broken = bytearray(wal); broken[60] ^= 1
    with pytest.raises(moments.ReaderError, match="CHECKSUM_MISMATCH"):
        moments.committed_wal_frames(bytes(broken))
