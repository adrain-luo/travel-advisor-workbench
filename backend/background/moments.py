"""Isolated copy-only SQLCipher/SNS reader; no process access or network.

Format reference: fanyuantaier/wechatauto-replica at
6e603974bbac3bda93d88bbd6995510ae2547f5c, db.py and moment.py.
No candidate module is imported. Keys are supplied as in-memory bytes only.
Record results (including original XML/media URLs) are PRIVATE source data;
callers must not print them into logs or upload them as general reports.
"""
from __future__ import annotations

from contextlib import closing
from datetime import datetime
import hashlib
import hmac
from pathlib import Path
import re
import sqlite3
import struct
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

SOURCE_REVISION = "6e603974bbac3bda93d88bbd6995510ae2547f5c"
PAGE_SIZE = 4096
RESERVED = 80
TARGET = "罗18955311550"


class ReaderError(RuntimeError):
    """Only fixed safe diagnostic codes; no keys, XML, or contact rows."""


def _owned_file(path, owned_root, *, must_exist=True):
    path, owned_root = Path(path).resolve(), Path(owned_root).resolve()
    if not path.is_relative_to(owned_root) or path == owned_root:
        raise ReaderError("PATH_OUTSIDE_OWNED_SNAPSHOT")
    if must_exist and not path.is_file():
        raise ReaderError("SNAPSHOT_FILE_MISSING")
    return path


def _checksum(data, order, initial=(0, 0)):
    if len(data) % 8:
        raise ReaderError("WAL_CHECKSUM_INPUT_ALIGNMENT")
    a, b = initial
    for x, y in struct.iter_unpack(order + "II", data):
        a = (a + x + b) & 0xFFFFFFFF
        b = (b + y + a) & 0xFFFFFFFF
    return a, b


def committed_wal_frames(data):
    """Validate standard SQLite WAL and retain only its last committed prefix.

    A generation-mismatched tail is old WAL capacity, never overlaid. A bad
    checksum in the current generation fails closed. Uncommitted valid trailing
    frames are ignored and explicitly counted. This does not create a snapshot
    of a changing source: the caller must first obtain a stable DB/WAL copy set.
    """
    result = {"present": bool(data), "valid_frames": 0, "committed_frames": 0,
              "uncommitted_frames_ignored": 0, "stale_generation_tail": False,
              "commit_database_pages": None}
    if not data:
        return [], result
    if len(data) < 32:
        raise ReaderError("WAL_HEADER_TRUNCATED")
    magic, version, page_size = struct.unpack(">III", data[:12])
    if magic not in (0x377F0682, 0x377F0683) or version != 3007000 or page_size != PAGE_SIZE:
        raise ReaderError("WAL_FORMAT_UNSUPPORTED")
    order = "<" if magic == 0x377F0682 else ">"
    state = _checksum(data[:24], order)
    if state != struct.unpack(">II", data[24:32]):
        raise ReaderError("WAL_HEADER_CHECKSUM_MISMATCH")
    salt = data[16:24]
    frames, last_commit, commit_pages = [], 0, None
    offset = 32
    while offset < len(data):
        if len(data) - offset < 24 + PAGE_SIZE:
            raise ReaderError("WAL_TRAILING_FRAME_TRUNCATED")
        header, page = data[offset:offset + 24], data[offset + 24:offset + 24 + PAGE_SIZE]
        if header[8:16] != salt:
            result["stale_generation_tail"] = True
            break
        page_number, database_pages = struct.unpack(">II", header[:8])
        if page_number == 0 or page_number > 1_000_000 or database_pages > 1_000_000:
            raise ReaderError("WAL_PAGE_NUMBER_INVALID")
        state = _checksum(header[:8] + page, order, state)
        if state != struct.unpack(">II", header[16:24]):
            raise ReaderError("WAL_FRAME_CHECKSUM_MISMATCH")
        frames.append((page_number, page))
        if database_pages:
            last_commit, commit_pages = len(frames), database_pages
        offset += 24 + PAGE_SIZE
    result.update(valid_frames=len(frames), committed_frames=last_commit,
                  uncommitted_frames_ignored=len(frames) - last_commit,
                  commit_database_pages=commit_pages)
    return frames[:last_commit], result


def _decrypt_page(page, number, key, mac_key):
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    if len(page) != PAGE_SIZE:
        raise ReaderError("ENCRYPTED_PAGE_TRUNCATED")
    offset = 16 if number == 1 else 0
    authenticated = page[offset:PAGE_SIZE - RESERVED + 16] + struct.pack("<I", number)
    expected = hmac.new(mac_key, authenticated, hashlib.sha512).digest()
    if not hmac.compare_digest(expected, page[-64:]):
        raise ReaderError("PAGE_HMAC_MISMATCH")
    iv = page[PAGE_SIZE - RESERVED:PAGE_SIZE - RESERVED + 16]
    dec = Cipher(algorithms.AES(key[:32]), modes.CBC(iv)).decryptor()
    body = dec.update(page[offset:PAGE_SIZE - RESERVED]) + dec.finalize()
    return (b"SQLite format 3\x00" if number == 1 else b"") + body + bytes(RESERVED)


def decrypt_snapshot(database_copy, wal_copy, key, output, *, owned_root,
                     expected_database_sha256, expected_wal_sha256=None,
                     byte_budget=128 * 1024 * 1024):
    """Decrypt explicit immutable copies into a fresh owned file, key in memory.

    Validates every base/committed-WAL page HMAC, WAL checksums/generation/commit
    boundary, then SQLite quick_check. No source files or external paths touched.
    """
    db = _owned_file(database_copy, owned_root)
    out = _owned_file(output, owned_root, must_exist=False)
    if out.exists() or out == db:
        raise ReaderError("OUTPUT_ALREADY_EXISTS")
    if len(key) not in (32, 48):
        raise ReaderError("KEY_LENGTH_UNSUPPORTED")
    wal = _owned_file(wal_copy, owned_root) if wal_copy is not None else None
    if db.stat().st_size + (wal.stat().st_size if wal else 0) > byte_budget:
        raise ReaderError("SNAPSHOT_BYTE_BUDGET_EXCEEDED")
    encrypted = db.read_bytes()
    wal_bytes = wal.read_bytes() if wal else b""
    if hashlib.sha256(encrypted).hexdigest() != expected_database_sha256:
        raise ReaderError("DATABASE_COPY_HASH_CHANGED")
    if wal and (not expected_wal_sha256 or hashlib.sha256(wal_bytes).hexdigest() != expected_wal_sha256):
        raise ReaderError("WAL_COPY_HASH_CHANGED")
    if not encrypted or len(encrypted) % PAGE_SIZE:
        raise ReaderError("DATABASE_PAGE_ALIGNMENT_UNSUPPORTED")
    salt = key[32:] if len(key) == 48 else encrypted[:16]
    mac_key = hashlib.pbkdf2_hmac("sha512", key[:32], bytes(x ^ 0x3A for x in salt), 2, dklen=32)
    frames, wal_report = committed_wal_frames(wal_bytes)
    base_pages = len(encrypted) // PAGE_SIZE
    final_pages = wal_report["commit_database_pages"] or base_pages
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        with out.open("xb") as dest:
            for number in range(1, base_pages + 1):
                page = encrypted[(number - 1) * PAGE_SIZE:number * PAGE_SIZE]
                dest.write(_decrypt_page(page, number, key, mac_key))
            for number, page in frames:
                plain = _decrypt_page(page, number, key, mac_key)
                if number <= final_pages:
                    dest.seek((number - 1) * PAGE_SIZE)
                    dest.write(plain)
            dest.truncate(final_pages * PAGE_SIZE)
        with out.open("r+b") as dest:
            header = bytearray(dest.read(100))
            if header[:16] != b"SQLite format 3\x00" or header[16:18] != b"\x10\x00" or header[20] != RESERVED:
                raise ReaderError("DECRYPTED_SQLITE_HEADER_UNSUPPORTED")
            # The owned output is a flattened snapshot, with no output WAL.
            header[18:20] = b"\x01\x01"
            header[28:32] = struct.pack(">I", final_pages)
            header[92:96] = header[24:28]
            dest.seek(0)
            dest.write(header)
        with closing(sqlite3.connect(out.as_uri() + "?mode=ro&immutable=1", uri=True)) as conn:
            conn.execute("PRAGMA query_only=ON")
            if conn.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                raise ReaderError("DECRYPTED_QUICK_CHECK_FAILED")
    except Exception:
        # Preserve the rejected copy for diagnosis, without claiming it readable.
        raise
    return {"status": "PASS", "input_database_sha256": expected_database_sha256,
            "input_wal_sha256": expected_wal_sha256, "decrypted_sha256": hashlib.sha256(out.read_bytes()).hexdigest(),
            "base_pages": base_pages, "snapshot_pages": final_pages, "wal": wal_report,
            "page_hmac_validation": "PASS", "sqlite_quick_check": "PASS",
            "key_persisted": False, "source_revision": SOURCE_REVISION}


def _connect(path, owned_root):
    path = _owned_file(path, owned_root)
    connection = sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)
    connection.execute("PRAGMA query_only=ON")
    connection.row_factory = sqlite3.Row
    return connection


def resolve_contact(contact_snapshot, *, owned_root, exact_name=TARGET):
    if not isinstance(exact_name, str) or not exact_name.strip():
        raise ReaderError("TARGET_NAME_REQUIRED")
    with closing(_connect(contact_snapshot, owned_root)) as conn:
        columns = {r[1] for r in conn.execute('PRAGMA table_info("contact")')}
        if not {"username", "nick_name", "remark"}.issubset(columns):
            raise ReaderError("CONTACT_SCHEMA_UNSUPPORTED")
        rows = conn.execute("SELECT username,nick_name,remark FROM contact WHERE remark=? OR nick_name=? LIMIT 3",
                            (exact_name, exact_name)).fetchall()
    valid = [dict(row) for row in rows if row["username"] and not str(row["username"]).endswith("@chatroom")]
    ids = {row["username"] for row in valid}
    if len(ids) == 0:
        return {"status": "NOT_FOUND", "exact_name": exact_name, "matches": [], "author_id": None}
    if len(ids) != 1 or len(rows) >= 3:
        return {"status": "AMBIGUOUS", "exact_name": exact_name, "matches": valid, "author_id": None}
    return {"status": "VERIFIED_EXACT_MAPPING", "exact_name": exact_name,
            "matches": valid, "author_id": next(iter(ids)), "source": "contact exact remark/nick_name match"}


def parse_selected_post(tid, sql_author, raw_xml, *, author_id):
    if not author_id or sql_author != author_id:
        raise ReaderError("AUTHOR_FILTER_MISMATCH")
    if isinstance(raw_xml, bytes):
        try:
            raw_xml = raw_xml.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ReaderError("SNS_XML_ENCODING_UNSUPPORTED") from exc
    if not isinstance(raw_xml, str) or len(raw_xml.encode("utf-8")) > 2 * 1024 * 1024:
        raise ReaderError("SNS_XML_SIZE_UNSUPPORTED")
    if "<!DOCTYPE" in raw_xml.upper() or "<!ENTITY" in raw_xml.upper():
        raise ReaderError("SNS_XML_ENTITY_DECLARATION_REJECTED")
    source_fullxml_sha256 = hashlib.sha256(raw_xml.encode("utf-8")).hexdigest()
    try:
        source_tree = ET.fromstring(raw_xml)
    except ET.ParseError as exc:
        raise ReaderError("SNS_XML_PARSE_FAILED") from exc
    if source_tree.tag == "TimelineObject":
        tree = source_tree
    elif source_tree.tag == "SnsDataItem":
        timelines = [node for node in source_tree if node.tag == "TimelineObject"]
        if len(timelines) != 1:
            raise ReaderError("SNS_TIMELINE_CONTAINER_AMBIGUOUS")
        tree = timelines[0]
    else:
        raise ReaderError("SNS_TIMELINE_CONTAINER_UNSUPPORTED")
    def direct(tag):
        return tree.findtext(tag, default="").strip()
    xml_author = direct("username")
    if xml_author and xml_author != author_id:
        raise ReaderError("SNS_XML_AUTHOR_MISMATCH")
    raw_time = direct("createTime")
    if not re.fullmatch(r"\d{1,12}", raw_time):
        raise ReaderError("SNS_PUBLICATION_TIME_UNSUPPORTED")
    publication = int(raw_time)
    text = tree.findtext("contentDesc", default="")
    media = []
    for index, node in enumerate(tree.findall("./ContentObject/mediaList/media")):
        url = node.find("url")
        thumbnail = node.find("thumb")
        size = node.find("size")
        media.append({"media_index": index, "native_media_id": node.findtext("id", default=""),
                      "type_raw": node.findtext("type", default=""),
                      "url": (url.text or "").strip() if url is not None else "",
                      "url_attributes": dict(url.attrib) if url is not None else {},
                      "thumbnail_url": (thumbnail.text or "").strip() if thumbnail is not None else "",
                      "thumbnail_attributes": dict(thumbnail.attrib) if thumbnail is not None else {},
                      "size_attributes": dict(size.attrib) if size is not None else {},
                      "raw_media_xml": ET.tostring(node, encoding="unicode"),
                      "retrieval_state": "PENDING", "quality": "unknown"})
    travel_terms = re.findall(r"旅游|旅行|团期|纯玩|行程|双飞|动车|酒店|报价|\d+日游|\d+天\d+晚", text)
    classification = "travel_text_candidate" if travel_terms else ("image_only_candidate" if media and not text.strip() else "unclassified")
    return {"in_scope": True, "native_post_id": direct("id"), "native_tid": str(tid),
            "author_id": author_id, "xml_author_present": bool(xml_author),
            "publication_epoch": publication, "publication_time_raw": raw_time,
            "publication_time": datetime.fromtimestamp(publication, ZoneInfo("Asia/Shanghai")).isoformat(),
            "text": text, "raw_xml": ET.tostring(tree, encoding="unicode"),
            "raw_xml_scope": "TimelineObject serialization; full source remains in copied database",
            "source_fullxml_sha256": source_fullxml_sha256,
            "media": media, "expected_media_count": len(media),
            "classification": classification, "classification_terms": list(dict.fromkeys(travel_terms)),
            "classification_is_supplier_confirmation": False}

