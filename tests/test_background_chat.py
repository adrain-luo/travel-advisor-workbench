"""Isolated native-schema fixtures; these do not establish live chat compatibility."""
import hashlib
import io
import sqlite3
import struct
from pathlib import Path

import pytest
from PIL import Image

from backend.background.chat import (
    AUTHORIZED_ACCOUNT as ACCOUNT, AUTHORIZED_FRIEND as FRIEND,
    ChatReadError, V2_MAGIC, decode_cached_image, missing_history_capability,
    read_chat_page, retrieve_chat,
)

TABLE = "Msg_" + hashlib.md5(FRIEND.encode()).hexdigest()
OTHER_TABLE = "Msg_" + hashlib.md5(b"unselected_friend").hexdigest()


@pytest.fixture
def scope(tmp_path):
    account = tmp_path / (ACCOUNT + "_fixture")
    account.mkdir()
    staging = tmp_path / "staging"
    staging.mkdir()
    return {"account_dir": account, "account_id": ACCOUNT, "friend_id": FRIEND}, staging


def shard(tmp_path, number, rows, sender_map=((1, ACCOUNT), (2, FRIEND))):
    path = tmp_path / f"copy-{number}.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE Name2Id(user_name TEXT)")
    con.executemany("INSERT INTO Name2Id(rowid,user_name) VALUES (?,?)", sender_map)
    columns = "(local_id INTEGER PRIMARY KEY,server_id TEXT,local_type INTEGER,real_sender_id INTEGER,create_time INTEGER,sort_seq INTEGER,message_content BLOB,packed_info_data BLOB,compress_content BLOB,source BLOB)"
    con.execute(f"CREATE TABLE {TABLE}" + columns)
    con.execute(f"CREATE TABLE {OTHER_TABLE}" + columns)
    con.execute(f"INSERT INTO {OTHER_TABLE} VALUES (1,'99',1,2,50,1,'must not leak',NULL,NULL,NULL)")
    con.executemany(f"INSERT INTO {TABLE} VALUES (?,?,?,?,?,?,?,NULL,NULL,NULL)", rows)
    con.commit(); con.close()
    return {"relative_path": f"message/message_{number}.db", "path": path}


def page(entries, scope, **kwargs):
    return read_chat_page(entries, **scope, **kwargs)


def test_same_second_shard_ids_sender_maps_and_large_ids(tmp_path, scope):
    args, _ = scope
    first = shard(tmp_path, 0, [(1, "18446744073709551615", 1, 1, 100, 900, "sent exactly\n"),
                                 (2, "9007199254740993", 1, 2, 100, 900, "received")])
    second = shard(tmp_path, 1, [(1, "9007199254740994", 1, 1, 100, 900, "received other shard"),
                                  (2, "9007199254740995", 1, 2, 100, 900, "sent other shard")],
                   sender_map=((1, FRIEND), (2, ACCOUNT)))
    results, cursor = [], None
    while True:
        result = page([second, first], args, limit=1, cursor=cursor)
        results += result["records"]
        cursor = result["next_cursor"]
        if result["exhausted"]:
            break
    assert len(results) == len({r["native_id"] for r in results}) == 4
    assert [r["direction"] for r in results] == ["sent", "received", "received", "sent"]
    assert results[0]["server_id"] == "18446744073709551615"
    assert results[0]["text"] == "sent exactly\n"
    assert results[0]["local_id"] == results[2]["local_id"] == "1"
    assert all("must not leak" not in r["text"] for r in results)
    assert all(r["source_revision"] for r in results)


def test_date_range_and_repeated_records_are_not_content_deduplicated(tmp_path, scope):
    args, _ = scope
    entry = shard(tmp_path, 0, [(i, str(i), 1, 2, t, i, "same content")
                                for i, t in enumerate((99, 100, 100, 200), 1)])
    result = page([entry], args, start_epoch=100, end_epoch=200)
    assert len(result["records"]) == 2
    assert len({r["event_key"] for r in result["records"]}) == 2
    assert result["coverage"] == "UNKNOWN"
    assert result["local_snapshot_exhausted"]
    assert result["observed_range"] == {"start_epoch": 100, "end_epoch": 100}
    assert [r["event_key"] for r in page([entry], args, start_epoch=100, end_epoch=200)["records"]] == [r["event_key"] for r in result["records"]]


def test_changed_snapshot_requires_reconciliation_and_finds_late_old_row(tmp_path, scope):
    args, _ = scope
    entry = shard(tmp_path, 0, [(1, "1", 1, 2, 200, 2, "first"), (2, "2", 1, 2, 300, 3, "second")])
    first = page([entry], args, limit=1)
    with sqlite3.connect(entry["path"]) as con:
        con.execute(f"INSERT INTO {TABLE} VALUES (3,'3',1,2,100,1,'late old record',NULL,NULL,NULL)")
    with pytest.raises(ChatReadError, match="CHAT_CURSOR_SNAPSHOT_MISMATCH"):
        page([entry], args, limit=1, cursor=first["next_cursor"])
    assert page([entry], args)["records"][0]["text"] == "late old record"


def test_scope_originals_and_wal_fail_closed(tmp_path, scope):
    args, _ = scope
    entry = shard(tmp_path, 0, [(1, "1", 1, 2, 100, 1, "data")])
    with pytest.raises(ChatReadError, match="CHAT_SCOPE_NOT_AUTHORIZED"):
        page([entry], {**args, "friend_id": "other"})
    original = args["account_dir"] / "message_0.db"
    original.write_bytes(entry["path"].read_bytes())
    with pytest.raises(ChatReadError, match="CHAT_ORIGINAL_DATABASE_FORBIDDEN"):
        page([{**entry, "path": original}], args)
    Path(str(entry["path"]) + "-wal").write_bytes(b"unmerged")
    with pytest.raises(ChatReadError, match="CHAT_SNAPSHOT_NOT_SEALED"):
        page([entry], args)


def test_query_error_does_not_become_empty_history(tmp_path, scope):
    args, _ = scope
    entry = shard(tmp_path, 0, [])
    entry["path"].write_bytes(b"not a database")
    with pytest.raises(ChatReadError, match="CHAT_SNAPSHOT_QUERY_FAILED"):
        page([entry], args)


def test_compressed_text_is_retained_with_explicit_issue_not_end_of_history(tmp_path, scope, monkeypatch):
    import sys
    args, _ = scope
    monkeypatch.setitem(sys.modules, "zstandard", None)
    entry = shard(tmp_path, 0, [(1, "1", 1, 2, 100, 1, b"\x28\xb5\x2f\xfdunsupported")])
    # Native WeChat sometimes stores binary data in a column with TEXT affinity.
    with sqlite3.connect(entry["path"]) as con:
        con.execute(f"UPDATE {TABLE} SET message_content=CAST(message_content AS TEXT)")
    record = page([entry], args)["records"][0]
    assert record["content_encoding_issue"] == "ZSTD_DEPENDENCY_UNAVAILABLE"
    assert record["issues"] == ["ZSTD_DEPENDENCY_UNAVAILABLE"]
    assert record["native_id"] and record["source_revision"]


def test_revision_excludes_snapshot_changes_and_cursor_rejects_range_change(tmp_path, scope):
    args, _ = scope
    entry = shard(tmp_path, 0, [(1, "1", 1, 2, 100, 1, "same"), (2, "2", 1, 2, 101, 2, "second")])
    first = page([entry], args, limit=1)
    with pytest.raises(ChatReadError, match="CHAT_CURSOR_SNAPSHOT_MISMATCH"):
        page([entry], args, limit=1, cursor=first["next_cursor"], start_epoch=100)
    with sqlite3.connect(entry["path"]) as con:
        con.execute(f"UPDATE {OTHER_TABLE} SET message_content='unrelated update'")
    again = page([entry], args, limit=1)
    assert first["snapshot_id"] != again["snapshot_id"]
    assert first["records"][0]["source_revision"] == again["records"][0]["source_revision"]


def test_native_media_xml_is_preserved_only_in_private_source(tmp_path, scope):
    args, _ = scope
    content = '<msg><videomsg aeskey="fixture-private-value"/></msg>'
    entry = shard(tmp_path, 0, [(1, "1", 43, 2, 100, 1, content)])
    record = page([entry], args)["records"][0]
    assert record["text"] == ""
    assert record["private_source"]["message_content"] == {"encoding": "native", "value": content}
    del record["private_source"]
    assert "fixture-private-value" not in str(record)


def test_real_zstd_frames_restore_text_and_exact_image_xml(tmp_path, scope):
    zstandard = pytest.importorskip("zstandard")
    args, _ = scope
    digest = "b" * 32
    original = "  exact long text\nwith preserved whitespace\n"
    image_xml = f'<msg><img md5="{digest}" aeskey="private-fixture"/></msg>'
    compressor = zstandard.ZstdCompressor()
    entry = shard(tmp_path, 0, [(1, "1", 1, 2, 100, 1, compressor.compress(original.encode())),
                                 (2, "2", 3, 2, 101, 2, compressor.compress(image_xml.encode()))])
    index = image_index(tmp_path, digest, png_bytes())
    records = page([entry, index], args)["records"]
    assert records[0]["text"] == original
    assert records[0]["content_encoding_issue"] is None
    assert records[1]["attachments"][0]["reason"] is None
    assert records[1]["attachments"][0]["private_reference"]["message_md5"] == digest
    assert records[1]["text"] == ""


def png_bytes():
    stream = io.BytesIO()
    Image.new("RGB", (5, 7), (4, 20, 230)).save(stream, format="PNG")
    return stream.getvalue()


def image_index(tmp_path, digest, data, directory=None):
    path = tmp_path / "hardlink-copy.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE dir2id(username TEXT)")
    con.executemany("INSERT INTO dir2id(rowid,username) VALUES (?,?)",
                    [(1, directory or hashlib.md5(FRIEND.encode()).hexdigest()), (2, "2025-01")])
    con.execute("CREATE TABLE image_hardlink_info_v4(md5 TEXT,type INTEGER,file_name TEXT,file_size INTEGER,modify_time INTEGER,dir1 INTEGER,dir2 INTEGER)")
    con.execute("INSERT INTO image_hardlink_info_v4 VALUES (?,2,'indexed-name.dat',?,100,1,2)", (digest, len(data)))
    con.commit(); con.close()
    return {"relative_path": "hardlink/hardlink.db", "path": path}


def test_image_exact_index_path_real_bytes_and_independent_reopen(tmp_path, scope):
    args, staging = scope
    data = png_bytes()
    digest = "e" * 32  # Message md5 identifies the indexed rendition; not guessed from its filename.
    entry = shard(tmp_path, 0, [(1, "9007199254740993", 3, 2, 1735689600, 1, f'<msg><img md5="{digest}"/></msg>')])
    index = image_index(tmp_path, digest, data)
    attachment = page([entry, index], args)["records"][0]["attachments"][0]
    reference = attachment["private_reference"]
    target = args["account_dir"] / reference["candidates"][0]["relative_path"]
    target.parent.mkdir(parents=True); target.write_bytes(data)
    result = retrieve_chat(reference, staging, **args)
    assert result["state"] == "VALIDATED"
    assert result["quality"] == "unknown_cached_rendition"
    assert result["sha256"] == hashlib.sha256(data).hexdigest()
    with Image.open(result["path"]) as image:
        image.load(); assert image.size == (5, 7)
    assert Path(result["path"]).read_bytes() == data


def test_image_same_md5_other_conversation_and_binary_guess_rejected(tmp_path, scope):
    args, staging = scope
    digest = "c" * 32
    entry = shard(tmp_path, 0, [(1, "1", 3, 2, 100, 1, f'<msg><img md5="{digest}"/></msg>'),
                                 (2, "2", 3, 2, 101, 2, ("binary" + digest).encode())])
    index = image_index(tmp_path, digest, png_bytes(), directory=hashlib.md5(b"unselected").hexdigest())
    records = page([entry, index], args)["records"]
    assert records[0]["attachments"][0]["reason"] == "IMAGE_EXACT_INDEX_LINK_MISSING"
    assert records[1]["attachments"][0]["reason"] == "IMAGE_MESSAGE_MD5_UNAVAILABLE"
    assert retrieve_chat(records[0]["attachments"][0]["private_reference"], staging, **args)["state"] == "UNAVAILABLE"


@pytest.mark.parametrize("payload,reason", [
    (b"unknown-format" + b"\0" * 64, "CHAT_IMAGE_FORMAT_UNSUPPORTED"),
    (b"\x89PNG\r\n\x1a\n" + b"\0" * 64, "CHAT_IMAGE_DECODE_FAILED"),
])
def test_unsupported_or_corrupt_image_is_not_transient_file_read_failure(tmp_path, scope, payload, reason):
    args, staging = scope
    digest = "d" * 32
    entry = shard(tmp_path, 0, [(1, "1", 3, 2, 100, 1, f'<msg><img md5="{digest}"/></msg>')])
    index = image_index(tmp_path, digest, payload)
    ref = page([entry, index], args)["records"][0]["attachments"][0]["private_reference"]
    target = args["account_dir"] / ref["candidates"][0]["relative_path"]
    target.parent.mkdir(parents=True); target.write_bytes(payload)
    result = retrieve_chat(ref, staging, **args)
    assert result["state"] == "UNAVAILABLE"
    assert result["reason"] == reason
    assert result["reason"] != "CHAT_ATTACHMENT_READ_FAILED"


def test_document_requires_server_link_and_content_hash(tmp_path, scope):
    args, staging = scope
    data = b"%PDF-1.4\nfixture document bytes\n%%EOF\n"
    digest = hashlib.md5(data).hexdigest()
    content = f"<msg><appmsg><title>travel.pdf</title><type>6</type><appattach><md5>{digest}</md5><totallen>{len(data)}</totallen></appattach></appmsg></msg>"
    entry = shard(tmp_path, 0, [(1, "9007199254740993", 49, 2, 1735689600, 1, content)])
    resource = tmp_path / "resource-copy.db"
    with sqlite3.connect(resource) as con:
        con.execute("CREATE TABLE ChatName2Id(user_name TEXT)")
        con.execute("INSERT INTO ChatName2Id(rowid,user_name) VALUES (1,?)", (FRIEND,))
        con.execute("CREATE TABLE MessageResourceInfo(message_id INTEGER,message_svr_id TEXT,chat_id INTEGER,message_local_id INTEGER,message_create_time INTEGER,message_local_type INTEGER)")
        con.execute("CREATE TABLE MessageResourceDetail(message_id INTEGER,packed_info BLOB)")
        con.execute("INSERT INTO MessageResourceInfo VALUES (9,'9007199254740993',1,1,1735689600,49)")
        con.execute("INSERT INTO MessageResourceDetail VALUES (9,'travel.pdf')")
    ref = page([entry, {"relative_path": "message/message_resource.db", "path": resource}], args)["records"][0]["attachments"][0]["private_reference"]
    target = args["account_dir"] / ref["candidates"][0]["relative_path"]
    target.parent.mkdir(parents=True); target.write_bytes(b"unrelated same-name file")
    assert retrieve_chat(ref, staging, **args)["reason"] == "CHAT_FILE_CONTENT_HASH_MISMATCH"
    target.write_bytes(data)
    result = retrieve_chat(ref, staging, **args)
    assert result["state"] == "VALIDATED"
    assert Path(result["path"]).read_bytes() == data
    assert result["quality"] == "hash_verified_file"
    ref["friend_id"] = "other"
    assert retrieve_chat(ref, staging, **args)["reason"] == "CHAT_ATTACHMENT_SCOPE_MISMATCH"


def test_v2_image_explicit_keys_only_and_wrong_key_fails():
    crypto = pytest.importorskip("cryptography.hazmat.primitives.ciphers")
    plain = png_bytes()
    prefix_len, xor_len = 32, 12
    aes_key, xor_key = b"0123456789abcdef", 0x5D
    prefix = plain[:prefix_len] + bytes([16]) * 16
    encryptor = crypto.Cipher(crypto.algorithms.AES(aes_key), crypto.modes.ECB()).encryptor()
    container = V2_MAGIC + struct.pack("<II", prefix_len, xor_len) + b"\0" + encryptor.update(prefix) + encryptor.finalize() + plain[prefix_len:-xor_len] + bytes(v ^ xor_key for v in plain[-xor_len:])
    with pytest.raises(ChatReadError, match="CHAT_IMAGE_KEY_REQUIRED"):
        decode_cached_image(container)
    assert decode_cached_image(container, {"aes_key": aes_key, "xor_key": xor_key}) == plain
    with pytest.raises(ChatReadError, match="CHAT_IMAGE_DECRYPTION_FAILED"):
        decode_cached_image(container, {"aes_key": b"badbadbadbadbadb", "xor_key": xor_key})


def test_v2_index_plaintext_size_allows_exact_header_padding_only(tmp_path, scope):
    crypto = pytest.importorskip("cryptography.hazmat.primitives.ciphers")
    args, staging = scope
    plain = png_bytes()
    digest, aes_key, xor_key = "a" * 32, b"0123456789abcdef", 0x5D
    prefix_len, xor_len = 32, 12
    encryptor = crypto.Cipher(crypto.algorithms.AES(aes_key), crypto.modes.ECB()).encryptor()
    prefix = encryptor.update(plain[:prefix_len] + bytes([16]) * 16) + encryptor.finalize()
    container = V2_MAGIC + struct.pack("<II", prefix_len, xor_len) + b"\0" + prefix + plain[prefix_len:-xor_len] + bytes(v ^ xor_key for v in plain[-xor_len:])
    assert len(container) == len(plain) + 31
    entry = shard(tmp_path, 0, [(1, "1", 3, 2, 1735689600, 1, f'<msg><img md5="{digest}"/></msg>')])
    index = image_index(tmp_path, digest, plain)
    ref = page([entry, index], args)["records"][0]["attachments"][0]["private_reference"]
    path = args["account_dir"] / ref["candidates"][0]["relative_path"]
    path.parent.mkdir(parents=True); path.write_bytes(container)
    assert retrieve_chat(ref, staging, **args)["reason"] == "CHAT_IMAGE_KEY_REQUIRED"
    result = retrieve_chat(ref, staging, **args, image_keys={"aes_key": aes_key, "xor_key": xor_key})
    assert result["state"] == "VALIDATED" and result["bytes"] == len(plain)
    assert Path(result["path"]).read_bytes() == plain
    ref["candidates"][0]["indexed_size"] += 1
    assert retrieve_chat(ref, staging, **args, image_keys={"aes_key": aes_key, "xor_key": xor_key})["reason"] == "CHAT_INDEXED_SIZE_MISMATCH"


def test_wxgf_index_size_applies_before_transcoding_and_preserves_source(tmp_path, scope, monkeypatch):
    from backend.background import codec
    args, staging = scope
    native = b"wxgf" + b"source-container" * 12
    png = png_bytes()
    def convert(value):
        assert value == native
        return png, {"quality": "unknown_cached_transcoded", "native_source_sha256": hashlib.sha256(native).hexdigest(),
                     "native_source_bytes": len(native), "native_source_format": "wxgf", "decode_method": "WXGF_HEVC_FFmpeg_to_PNG"}
    monkeypatch.setattr(codec, "convert_wxgf_to_png", convert)
    digest = "9" * 32
    entry = shard(tmp_path, 0, [(1, "1", 3, 2, 100, 1, f'<msg><img md5="{digest}"/></msg>')])
    index = image_index(tmp_path, digest, native)
    ref = page([entry, index], args)["records"][0]["attachments"][0]["private_reference"]
    target = args["account_dir"] / ref["candidates"][0]["relative_path"]
    target.parent.mkdir(parents=True); target.write_bytes(native)
    private_sources = tmp_path / "private-native-sources"
    private_sources.mkdir()
    result = retrieve_chat(ref, staging, **args, native_source_dir=private_sources)
    assert result["state"] == "VALIDATED"
    assert result["quality"] == "unknown_cached_transcoded"
    assert result["bytes"] == len(png) != len(native)
    assert result["native_source_bytes"] == len(native)
    assert result["native_source_sha256"] == hashlib.sha256(native).hexdigest()
    assert Path(result["private_native_source_path"]).read_bytes() == native
    assert Path(result["path"]).read_bytes() == png


def test_missing_native_history_is_not_local_exhaustion():
    capability = missing_history_capability()
    assert capability["status"] == "BLOCKED"
    assert capability["local_snapshot_backfill"] is True
    assert capability["implemented"] is False


def test_passive_image_primitive_matches_exact_account_without_master_key_reads():
    from backend.background.image_access import _derive_candidate
    landmark, v18, cfg, name_pointer = 0x200000, 0x300000, 0x400000, 0x500000
    marker = b"global_config" + b"\0" * 3 + struct.pack("<QQ", 13, 15)
    account_string = struct.pack("<QQQQ", name_pointer, 0, len(ACCOUNT), 31)
    dword = 0x12345678
    memory = {(landmark, 32): marker, (landmark + 16 - 0x138, 8): struct.pack("<Q", v18),
              (v18 + 0x68, 8): struct.pack("<Q", cfg), (cfg + 0x48, 32): account_string,
              (name_pointer, len(ACCOUNT)): ACCOUNT.encode(), (cfg + 0x40, 4): struct.pack("<I", dword)}
    reads = []
    def read(address, length):
        reads.append((address, length))
        return memory.get((address, length))
    result = _derive_candidate(read, landmark, ACCOUNT)
    assert result == {"aes_key": hashlib.md5((str(dword) + ACCOUNT).encode()).hexdigest()[:16].encode(), "xor_key": 0x78}
    assert all(address != cfg + 0x2B8 for address, _ in reads)
    memory[(name_pointer, len(ACCOUNT))] = b"x" * len(ACCOUNT)
    reads.clear()
    assert _derive_candidate(read, landmark, ACCOUNT) is None
    assert (cfg + 0x40, 4) not in reads


def test_image_probe_without_authenticated_binding_never_opens_process(monkeypatch):
    from backend.background import image_access
    def forbidden():
        pytest.fail("process API initialized without authenticated binding")
    monkeypatch.setattr(image_access.access, "_windows_api", forbidden)
    candidate, report = image_access.probe_image_key({}, expected_account_id=ACCOUNT)
    assert candidate is None
    assert report["reason"] == "IMAGE_ACCOUNT_BINDING_UNVERIFIED"
    assert report["process_read_bytes"] == 0
    assert report["keys_persisted"] is False
