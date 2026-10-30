"""Read one explicitly authorized conversation from immutable decrypted copies.

No client imports, process access, UI, account discovery or original-DB writes.
Schema references are pinned in .local/integration-20261028/chat-and-backfill-research.md.
The caller validates the live binding and atomically persists events and cursors.
"""
from __future__ import annotations

import hashlib
import base64
import io
import json
import mimetypes
import os
from pathlib import Path, PurePosixPath
import re
import sqlite3
import struct
import uuid
import warnings
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

AUTHORIZED_ACCOUNT = "wxid_fixture_account"
AUTHORIZED_FRIEND = "wxid_fixture_friend"
MAX_BYTES = 64 * 1024 * 1024
V2_MAGIC = b"\x07\x08\x56\x32\x08\x07"
V1_MAGIC = b"\x07\x08\x05\x56\x02\x05"
_MD5 = re.compile(r"[0-9a-fA-F]{32}\Z")


class ChatReadError(RuntimeError):
    """Fixed safe error code; never include message contents or secrets."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


def _hash_json(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode()).hexdigest()


def _scope(account_dir, account_id, friend_id):
    # The native adapter verifies these exact IDs against the fresh local binding.
    # Constants above are synthetic fixture identities, never production defaults.
    if (not isinstance(account_id, str) or not isinstance(friend_id, str)
            or not re.fullmatch(r"wxid_[A-Za-z0-9_]+", account_id)
            or not re.fullmatch(r"wxid_[A-Za-z0-9_]+", friend_id) or account_id == friend_id):
        raise ChatReadError("CHAT_SCOPE_NOT_AUTHORIZED")
    root = Path(account_dir).resolve()
    if root.name != account_id and not re.fullmatch(re.escape(account_id) + r"_[a-zA-Z0-9]+", root.name):
        raise ChatReadError("CHAT_ACCOUNT_DIRECTORY_MISMATCH")
    return root


def _sha_file(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _snapshot_entries(snapshots, account_root):
    if isinstance(snapshots, dict):
        values = [{"relative_path": k, **v} if isinstance(v, dict)
                  else {"relative_path": k, "path": v} for k, v in snapshots.items()]
    else:
        values = list(snapshots)
    entries, roles = [], set()
    for value in values:
        rel = str(value.get("relative_path") or value.get("kind") or "").replace("\\", "/")
        rel = str(PurePosixPath(rel))
        if not (re.fullmatch(r"message/message_[0-9]+\.db", rel)
                or rel in {"message/message_resource.db", "hardlink/hardlink.db"}):
            continue
        if rel in roles:
            raise ChatReadError("CHAT_DUPLICATE_SHARD")
        path = Path(value["path"]).resolve(strict=True)
        if path.is_relative_to(account_root):
            raise ChatReadError("CHAT_ORIGINAL_DATABASE_FORBIDDEN")
        if not path.is_file() or Path(str(path) + "-wal").exists():
            raise ChatReadError("CHAT_SNAPSHOT_NOT_SEALED")
        stat = path.stat()
        digest = _sha_file(path)
        if value.get("sha256") and digest != value["sha256"]:
            raise ChatReadError("CHAT_SNAPSHOT_HASH_MISMATCH")
        entries.append({"relative_path": rel, "path": path, "sha256": digest,
                        "stat": (stat.st_size, stat.st_mtime_ns)})
        roles.add(rel)
    entries.sort(key=lambda entry: entry["relative_path"])
    if not any(re.fullmatch(r"message/message_[0-9]+\.db", e["relative_path"]) for e in entries):
        raise ChatReadError("CHAT_MESSAGE_SNAPSHOT_REQUIRED")
    return entries


def _connect(path):
    connection = sqlite3.connect(Path(path).as_uri() + "?mode=ro&immutable=1", uri=True)
    connection.row_factory = sqlite3.Row
    # Native columns declared TEXT can contain compressed/binary payloads.
    def native_text(value):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            return value
    connection.text_factory = native_text
    connection.execute("PRAGMA query_only=ON")
    return connection


def _columns(connection, table):
    return {row[1] for row in connection.execute('PRAGMA table_info("' + table + '")')}


def _integer(value, code="CHAT_NATIVE_INTEGER_INVALID"):
    if isinstance(value, bool) or not re.fullmatch(r"-?[0-9]+", str(value)):
        raise ChatReadError(code)
    return int(value)


def _decode_text(value):
    if value is None:
        return "", None
    if isinstance(value, str):
        return value, None
    if not isinstance(value, bytes):
        raise ChatReadError("CHAT_CONTENT_TYPE_UNSUPPORTED")
    if len(value) > 2 * 1024 * 1024:
        return "", "CONTENT_SIZE_LIMIT"
    if value.startswith(b"\x28\xb5\x2f\xfd"):
        try:
            import zstandard
        except ImportError:
            return "", "ZSTD_DEPENDENCY_UNAVAILABLE"
        try:
            value = zstandard.ZstdDecompressor().decompress(value, max_output_size=2 * 1024 * 1024)
        except Exception:
            return "", "CONTENT_DECOMPRESSION_FAILED"
    try:
        return value.decode("utf-8"), None
    except UnicodeDecodeError:
        return "", "CONTENT_ENCODING_UNSUPPORTED"


def _private_value(value):
    if isinstance(value, bytes):
        return {"encoding": "base64", "value": base64.b64encode(value).decode("ascii")}
    if value is None or isinstance(value, (str, int)):
        return {"encoding": "native", "value": value}
    raise ChatReadError("CHAT_CONTENT_TYPE_UNSUPPORTED")


def _xml(text):
    if not text or len(text) > 2 * 1024 * 1024 or "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
        return None
    try:
        element = ET.fromstring(text)
    except ET.ParseError:
        return None
    return element if element.tag == "msg" else None


def _single(parent, path):
    nodes = parent.findall(path) if parent is not None else []
    return nodes[0] if len(nodes) == 1 else None


def _component(value):
    return isinstance(value, str) and bool(value) and value not in {".", ".."} and not any(c in value for c in '/\\:\x00')


def _image_links(connection, md5, friend_id):
    """Use indexed full components, never filename similarity or directory scans."""
    if connection is None:
        return [], "IMAGE_HARDLINK_SNAPSHOT_REQUIRED"
    required = {"md5", "type", "file_name", "file_size", "modify_time", "dir1", "dir2"}
    if not required <= _columns(connection, "image_hardlink_info_v4") or "username" not in _columns(connection, "dir2id"):
        return [], "IMAGE_HARDLINK_SCHEMA_UNSUPPORTED"
    rows = connection.execute(
        "SELECT h.rowid AS index_rowid,h.md5,h.type,h.file_name,h.file_size,h.modify_time,"
        "a.username AS directory1,b.username AS directory2 FROM image_hardlink_info_v4 h "
        "JOIN dir2id a ON a.rowid=h.dir1 JOIN dir2id b ON b.rowid=h.dir2 "
        "WHERE lower(h.md5)=? AND h.type<>4 ORDER BY h.modify_time DESC,h.rowid", (md5,)).fetchall()
    conversation = hashlib.md5(friend_id.encode()).hexdigest()
    links = []
    for row in rows:
        if row["directory1"] != conversation:
            continue
        if not all(_component(row[key]) for key in ("directory1", "directory2", "file_name")):
            raise ChatReadError("CHAT_INDEX_PATH_INVALID")
        name = row["file_name"]
        # Tier labels are conservative. A cache suffix alone never proves original quality.
        quality = "thumbnail" if name.lower().endswith("_t.dat") else "unknown_cached_rendition"
        links.append({"relative_path": "/".join(("msg", "attach", row["directory1"], row["directory2"], "Img", name)),
                      "index_table": "image_hardlink_info_v4", "index_rowid": str(row["index_rowid"]),
                      "indexed_size": int(row["file_size"] or 0), "quality": quality})
    links.sort(key=lambda link: (link["quality"] == "thumbnail", link["relative_path"]))
    return links, None if links else "IMAGE_EXACT_INDEX_LINK_MISSING"


def _resource_names(connection, record):
    """Return only names attached to the exact server ID; names are not byte proof."""
    server_id = record["server_id"]
    if connection is None or server_id == "0":
        return []
    required = {"message_id", "message_svr_id", "chat_id", "message_local_id", "message_create_time", "message_local_type"}
    if (not required <= _columns(connection, "MessageResourceInfo")
            or not {"message_id", "packed_info"} <= _columns(connection, "MessageResourceDetail")
            or "user_name" not in _columns(connection, "ChatName2Id")):
        return []
    rows = connection.execute(
        "SELECT d.packed_info FROM MessageResourceDetail d JOIN MessageResourceInfo i "
        "ON d.message_id=i.message_id JOIN ChatName2Id c ON c.rowid=i.chat_id "
        "WHERE CAST(i.message_svr_id AS TEXT)=? AND c.user_name=? AND i.message_local_id=? "
        "AND i.message_create_time=? AND (i.message_local_type & 4294967295)=?",
        (server_id, record["conversation_id"], int(record["local_id"]), record["message_epoch"],
         record["message_type"] & 0xFFFFFFFF)).fetchall()
    names = []
    for row in rows:
        value, error = _decode_text(row[0])
        if not error and _component(value) and value not in names:
            names.append(value)
    return names


def _attachments(record, content, hardlink, resource):
    base = record["message_type"] & 0xFFFFFFFF
    root = _xml(content)
    if base not in {3, 49}:
        return []
    img = _single(root, "./img")
    app = _single(root, "./appmsg")
    app_type = app.findtext("type") if app is not None else None
    if base == 49 and app_type != "6" and record["message_type"] >> 32 != 6:
        return []
    kind = "image" if base == 3 else "file"
    reference = {"kind": "chat", "account_id": record["account_id"], "friend_id": record["conversation_id"],
                 "native_id": record["native_id"], "media_index": 0, "attachment_type": kind,
                 "provenance": record["provenance"], "candidates": []}
    reason, name = None, "微信图片" if kind == "image" else "微信文件"
    if kind == "image":
        digest = img.get("md5", "") if img is not None else ""
        if _MD5.fullmatch(digest):
            reference["message_md5"] = digest.lower()
            reference["association"] = "message_xml_md5_to_hardlink_index"
            reference["candidates"], reason = _image_links(hardlink, digest.lower(), record["conversation_id"])
        else:
            reason = "IMAGE_MESSAGE_MD5_UNAVAILABLE"
    else:
        attach = _single(app, "./appattach")
        digest = attach.findtext("md5", "") if attach is not None else ""
        title = app.findtext("title", "") if app is not None else ""
        names = _resource_names(resource, record)
        if _component(title):
            name = title
        reference["expected_size"] = None
        size = attach.findtext("totallen", "") if attach is not None else ""
        if size.isdecimal():
            reference["expected_size"] = int(size)
        if not _MD5.fullmatch(digest):
            reason = "FILE_CONTENT_HASH_UNAVAILABLE"
        elif len(names) != 1:
            reason = "FILE_EXACT_RESOURCE_LINK_UNAVAILABLE"
        elif _component(title) and names[0] != title:
            reason = "FILE_RESOURCE_TITLE_MISMATCH"
        else:
            # The source maps file cache by month/name. Content MD5, not this
            # locator, establishes byte identity; no other months are searched.
            month = datetime.fromtimestamp(record["message_epoch"], timezone.utc).astimezone(
                ZoneInfo("Asia/Shanghai")).strftime("%Y-%m")
            reference.update(expected_md5=digest.lower(), association="server_resource_link_and_message_content_md5")
            reference["candidates"] = [{"relative_path": f"msg/file/{month}/{names[0]}", "quality": "hash_verified_file"}]
            name = names[0]
    reference["unavailable_reason"] = reason
    return [{"native_id": record["native_id"] + "/0", "index": 0, "media_index": 0,
             "name": name, "type": kind, "mime": "image/*" if kind == "image" else mimetypes.guess_type(name)[0] or "application/octet-stream",
             "quality": "unknown_cached_rendition" if kind == "image" else "unknown",
             "state": "REFERENCE_DISCOVERED", "reason": reason, "private_reference": reference}]


def _record(row, entry, table, senders, account_id, friend_id, hardlink, resource):
    local_id = str(_integer(row["local_id"]))
    server_id = str(_integer(row["server_id"] or 0))
    sender_number = _integer(row["real_sender_id"] or 0)
    sender = senders.get(sender_number)
    if sender and sender not in {account_id, friend_id}:
        raise ChatReadError("CHAT_SENDER_SCOPE_MISMATCH")
    epoch, sequence = _integer(row["create_time"]), _integer(row["sort_seq"])
    native_id = entry["relative_path"] + "/" + table + "/" + local_id
    raw = row["message_content"]
    content, issue = _decode_text(raw)
    if (not content or issue) and row["compress_content"]:
        alternate, alt_issue = _decode_text(row["compress_content"])
        if not alt_issue:
            content, issue = alternate, None
    message_type = _integer(row["local_type"])
    base = message_type & 0xFFFFFFFF
    result = {"account_id": account_id, "conversation_id": friend_id, "native_id": native_id,
              "native_id_verified": True, "local_id": local_id, "server_id": server_id,
              "author_id": sender, "author": sender, "sender_native_id": str(sender_number),
              "direction": "sent" if sender == account_id else "received" if sender == friend_id else "unknown",
              "message_type": message_type, "message_type_raw": str(message_type),
              "type": "text" if base == 1 else "image" if base == 3 else "file" if base == 49 else "other",
              "message_epoch": epoch, "sort_seq": str(sequence), "publication_epoch": epoch,
              "publication_time": datetime.fromtimestamp(epoch, timezone.utc).isoformat(),
              "source_time_raw": str(epoch),
              "text": content if base == 1 or (base not in {3, 49} and not content.lstrip().startswith("<")) else "",
              "content_encoding_issue": issue, "issues": [issue] if issue else [],
              "provenance": {"shard": entry["relative_path"], "table": table, "local_id": local_id,
                             "server_id": server_id, "snapshot_sha256": entry["sha256"]}}
    # Media XML can contain access keys. The native adapter persists this only
    # in its private source store, and removes it from ordinary event/UI JSON.
    result["private_source"] = {key: _private_value(row[key]) for key in
                                ("message_content", "compress_content", "packed_info_data", "source")}
    if sender is None:
        result["issues"].append("SENDER_MAPPING_UNAVAILABLE")
    result["event_key"] = _hash_json([account_id, friend_id, native_id])
    result["source_revision"] = _hash_json([result["private_source"], server_id,
        str(message_type), str(epoch), str(sequence), sender])
    result["attachments"] = _attachments(result, content, hardlink, resource)
    if base == 49:
        app = _single(_xml(content), "./appmsg")
        result["text"] = app.findtext("title", "") if app is not None else ""
        # An explicit native quote/reference is distinct from temporal proximity.
        # Parent lookup must still resolve this server ID inside the same bound
        # account/conversation and confirm that parent's product relevance.
        if app is not None and app.findtext("type", "").strip() == "57":
            reference = app.find("refermsg")
            if reference is not None:
                target = reference.findtext("svrid", "").strip()
                source_user = reference.findtext("fromusr", "").strip()
                chat_user = reference.findtext("chatusr", "").strip()
                if (target.isdecimal() and int(target) > 0
                        and source_user in {"", account_id, friend_id}
                        and chat_user in {"", account_id, friend_id}):
                    result["reply"] = {"relationship": "explicit_reply", "relationship_verified": True,
                        "native_server_id": str(int(target)), "account_id": account_id,
                        "conversation_id": friend_id, "source_message_server_id": server_id}
                else:
                    result["issues"].append("EXPLICIT_REPLY_SCOPE_UNVERIFIED")
    return result


def read_chat_page(snapshots, *, account_dir, account_id, friend_id, limit=100, cursor=None,
                   start_epoch=None, end_epoch=None, attachment_index_snapshot=None):
    """Ascending, snapshot-bound keyset page; date range is [start,end).

    snapshots is role->path or [{relative_path,path,sha256?}]. Only message_N,
    message_resource and hardlink roles are read. Different snapshots require a
    fresh reconciliation traversal, so late-arriving old messages are retained.
    """
    account_root = _scope(account_dir, account_id, friend_id)
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 1000:
        raise ChatReadError("CHAT_PAGE_LIMIT_INVALID")
    if start_epoch is not None:
        start_epoch = _integer(start_epoch)
    if end_epoch is not None:
        end_epoch = _integer(end_epoch)
    if start_epoch is not None and end_epoch is not None and start_epoch >= end_epoch:
        raise ChatReadError("CHAT_DATE_RANGE_INVALID")
    entries = _snapshot_entries(snapshots, account_root)
    if attachment_index_snapshot:
        extra = dict(attachment_index_snapshot, relative_path="hardlink/hardlink.db")
        entries = _snapshot_entries(entries + [extra], account_root)
    scope = [account_id, friend_id, start_epoch, end_epoch]
    snapshot_id = _hash_json([(e["relative_path"], e["sha256"]) for e in entries])
    last = None
    if cursor:
        if cursor.get("snapshot_id") != snapshot_id or cursor.get("scope") != scope or cursor.get("version") != 1:
            raise ChatReadError("CHAT_CURSOR_SNAPSHOT_MISMATCH")
        raw_last = cursor.get("last")
        if not isinstance(raw_last, list) or len(raw_last) != 4:
            raise ChatReadError("CHAT_CURSOR_INVALID")
        last = (_integer(raw_last[0]), _integer(raw_last[1]), str(raw_last[2]), _integer(raw_last[3]))
    table = "Msg_" + hashlib.md5(friend_id.encode()).hexdigest()
    connections, rows, matched = [], [], []
    observed_min, observed_max = None, None
    try:
        indexes = {}
        for entry in entries:
            connection = _connect(entry["path"])
            connections.append(connection)
            rel = entry["relative_path"]
            if rel in {"hardlink/hardlink.db", "message/message_resource.db"}:
                indexes[rel] = connection
                continue
            exists = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
            if not exists:
                continue
            matched.append(rel)
            columns = _columns(connection, table)
            required = {"local_id", "server_id", "local_type", "real_sender_id", "create_time", "sort_seq", "message_content"}
            if not required <= columns:
                raise ChatReadError("CHAT_MESSAGE_SCHEMA_UNSUPPORTED")
            if "user_name" not in _columns(connection, "Name2Id"):
                raise ChatReadError("CHAT_SENDER_SCHEMA_UNSUPPORTED")
            senders = {int(r[0]): r[1] for r in connection.execute(
                "SELECT rowid,user_name FROM Name2Id WHERE user_name IN (?,?)", (account_id, friend_id))}
            where, args = [], []
            if start_epoch is not None:
                where.append("create_time>=?"); args.append(start_epoch)
            if end_epoch is not None:
                where.append("create_time<?"); args.append(end_epoch)
            bounds = connection.execute('SELECT min(create_time),max(create_time) FROM "' + table + '"' +
                (" WHERE " + " AND ".join(where) if where else ""), args).fetchone()
            if bounds[0] is not None:
                observed_min = min(observed_min, bounds[0]) if observed_min is not None else bounds[0]
                observed_max = max(observed_max, bounds[1]) if observed_max is not None else bounds[1]
            if last:
                where.append("(create_time,sort_seq,?,local_id)>(?,?,?,?)")
                args += [rel, *last]
            optional = ",".join('"' + col + '"' if col in columns else 'NULL AS "' + col + '"'
                                for col in ("packed_info_data", "compress_content", "source"))
            query = 'SELECT local_id,server_id,local_type,real_sender_id,create_time,sort_seq,message_content,' + optional + ' FROM "' + table + '"'
            if where:
                query += " WHERE " + " AND ".join(where)
            query += " ORDER BY create_time,sort_seq,local_id LIMIT ?"
            for row in connection.execute(query, [*args, limit + 1]):
                key = (_integer(row["create_time"]), _integer(row["sort_seq"]), rel, _integer(row["local_id"]))
                rows.append((key, row, entry, senders))
        rows.sort(key=lambda item: item[0])
        exhausted = len(rows) <= limit
        chosen = rows[:limit]
        records = [_record(row, entry, table, senders, account_id, friend_id,
                           indexes.get("hardlink/hardlink.db"), indexes.get("message/message_resource.db"))
                   for _, row, entry, senders in chosen]
        for entry in entries:
            stat = entry["path"].stat()
            if (stat.st_size, stat.st_mtime_ns) != entry["stat"]:
                raise ChatReadError("CHAT_SNAPSHOT_CHANGED")
        next_cursor = None
        if chosen and not exhausted:
            key = chosen[-1][0]
            next_cursor = {"version": 1, "snapshot_id": snapshot_id, "scope": scope,
                           "last": [str(key[0]), str(key[1]), key[2], str(key[3])]}
        return {"records": records, "next_cursor": next_cursor, "snapshot_id": snapshot_id,
                "exhausted": exhausted, "coverage": "UNKNOWN", "local_snapshot_exhausted": exhausted,
                "observed_range": {"start_epoch": observed_min, "end_epoch": observed_max},
                "matched_shards": matched, "examined_shards": [e["relative_path"] for e in entries if re.fullmatch(r"message/message_[0-9]+\.db", e["relative_path"])],
                "stop_reason": "LOCAL_SNAPSHOT_EXHAUSTED_NATIVE_HISTORY_UNKNOWN" if exhausted else "PAGE_LIMIT"}
    except sqlite3.Error:
        raise ChatReadError("CHAT_SNAPSHOT_QUERY_FAILED") from None
    finally:
        for connection in connections:
            connection.close()


def _image_info(data):
    from PIL import Image, UnidentifiedImageError
    known_signature = (data.startswith((b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n", b"GIF87a", b"GIF89a", b"BM"))
                       or (data[:4] == b"RIFF" and data[8:12] == b"WEBP"))
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                width, height = image.size
                if image.format not in {"JPEG", "PNG", "GIF", "WEBP", "BMP"}:
                    raise ChatReadError("CHAT_IMAGE_FORMAT_UNSUPPORTED")
                if width <= 0 or height <= 0 or width * height > 40_000_000:
                    raise ChatReadError("CHAT_IMAGE_DIMENSIONS_REJECTED")
                result = {"mime": Image.MIME[image.format], "width": width, "height": height}
                image.verify()
            with Image.open(io.BytesIO(data)) as image:
                image.load()
        return result
    except ChatReadError:
        raise
    except UnidentifiedImageError:
        raise ChatReadError("CHAT_IMAGE_DECODE_FAILED" if known_signature else "CHAT_IMAGE_FORMAT_UNSUPPORTED") from None
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ChatReadError("CHAT_IMAGE_DIMENSIONS_REJECTED") from None
    except (OSError, ValueError, SyntaxError, struct.error):
        # These exceptions come from decoding in-memory bytes, not filesystem I/O.
        # Keep permanent format/corruption failures out of the transient read queue.
        raise ChatReadError("CHAT_IMAGE_DECODE_FAILED") from None


def _decrypt_cached_payload(data, image_keys=None):
    """Unwrap encryption before checking native size or converting a format."""
    if data[:6] in {V1_MAGIC, V2_MAGIC}:
        keys = image_keys or {}
        xor_key = keys.get("xor_key")
        if not isinstance(xor_key, int) or not 0 <= xor_key <= 255:
            raise ChatReadError("CHAT_IMAGE_KEY_REQUIRED")
        if data[:6] == V1_MAGIC:
            if len(data) < 22:
                raise ChatReadError("CHAT_IMAGE_CONTAINER_INVALID")
            plain = bytes(value ^ xor_key for value in data[22:])
        else:
            aes_key = keys.get("aes_key")
            if isinstance(aes_key, str):
                aes_key = aes_key.encode("ascii")
            if not isinstance(aes_key, bytes) or len(aes_key) != 16:
                raise ChatReadError("CHAT_IMAGE_KEY_REQUIRED")
            if len(data) < 15:
                raise ChatReadError("CHAT_IMAGE_CONTAINER_INVALID")
            aes_size, xor_size = struct.unpack_from("<II", data, 6)
            block_size = aes_size + 16 - aes_size % 16
            if 15 + block_size + xor_size > len(data):
                raise ChatReadError("CHAT_IMAGE_CONTAINER_INVALID")
            from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
            decryptor = Cipher(algorithms.AES(aes_key), modes.ECB()).decryptor()
            prefix = decryptor.update(data[15:15 + block_size]) + decryptor.finalize()
            padding = prefix[-1]
            if not 1 <= padding <= 16 or prefix[-padding:] != bytes([padding]) * padding or len(prefix) - padding != aes_size:
                raise ChatReadError("CHAT_IMAGE_DECRYPTION_FAILED")
            tail_start = len(data) - xor_size
            plain = prefix[:-padding] + data[15 + block_size:tail_start] + bytes(value ^ xor_key for value in data[tail_start:])
        return plain
    return data


def decode_cached_image(data, image_keys=None):
    """Decode explicit cached still-image bytes/keys, without format conversion."""
    plain = _decrypt_cached_payload(data, image_keys)
    _image_info(plain)
    return plain


def _indexed_image_size_matches(data, indexed_size):
    """Native V2 index sizes describe decoded bytes, excluding header/padding.

    Require the exact overhead computed from this container's declared AES size;
    do not treat arbitrary size differences as a permissible cached rendition.
    """
    if not indexed_size:
        return True
    if data[:6] != V2_MAGIC:
        return len(data) == indexed_size
    if len(data) < 15:
        return False
    aes_size, xor_size = struct.unpack_from("<II", data, 6)
    block_size = aes_size + 16 - aes_size % 16
    if 15 + block_size + xor_size > len(data):
        return False
    return len(data) - 15 - (block_size - aes_size) == indexed_size


def retrieve_chat(private_reference, staging_dir, *, account_dir, account_id, friend_id, image_keys=None,
                  native_source_dir=None):
    """Read exact indexed cached bytes into owned staging; safe statuses only."""
    result = {"state": "UNAVAILABLE", "quality": "unknown", "reason": None}
    try:
        root = _scope(account_dir, account_id, friend_id)
        reference = private_reference
        if reference.get("account_id") != account_id or reference.get("friend_id") != friend_id or reference.get("kind") != "chat":
            raise ChatReadError("CHAT_ATTACHMENT_SCOPE_MISMATCH")
        if reference.get("unavailable_reason"):
            raise ChatReadError(reference["unavailable_reason"])
        kind = reference.get("attachment_type")
        association = reference.get("association")
        if kind == "image" and association != "message_xml_md5_to_hardlink_index":
            raise ChatReadError("CHAT_ATTACHMENT_ASSOCIATION_UNPROVEN")
        if kind == "file" and association != "server_resource_link_and_message_content_md5":
            raise ChatReadError("CHAT_ATTACHMENT_ASSOCIATION_UNPROVEN")
        if kind not in {"image", "file"}:
            raise ChatReadError("CHAT_ATTACHMENT_TYPE_UNSUPPORTED")
        candidates = reference.get("candidates") or []
        if not candidates or len(candidates) > 20:
            raise ChatReadError("CHAT_EXACT_INDEX_LINK_MISSING")
        last_error = "CHAT_LOCAL_FILE_UNAVAILABLE"
        for candidate in candidates:
            rel = PurePosixPath(candidate["relative_path"])
            if rel.is_absolute() or any(not _component(component) for component in rel.parts):
                raise ChatReadError("CHAT_INDEX_PATH_INVALID")
            allowed_prefix = ("msg", "attach", hashlib.md5(friend_id.encode()).hexdigest()) if kind == "image" else ("msg", "file")
            if rel.parts[:len(allowed_prefix)] != allowed_prefix:
                raise ChatReadError("CHAT_INDEX_PATH_OUTSIDE_SOURCE")
            path = root.joinpath(*rel.parts).resolve()
            if not path.is_relative_to(root):
                raise ChatReadError("CHAT_INDEX_PATH_OUTSIDE_ACCOUNT")
            if not path.is_file():
                continue
            before = path.stat()
            if before.st_size > MAX_BYTES or before.st_size <= 0:
                last_error = "CHAT_ATTACHMENT_SIZE_REJECTED"; continue
            with path.open("rb") as stream:
                data = stream.read(MAX_BYTES + 1)
            after = path.stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns) or len(data) != before.st_size:
                last_error = "CHAT_ATTACHMENT_CHANGED"; continue
            if kind == "image" and not _indexed_image_size_matches(data, candidate.get("indexed_size")):
                last_error = "CHAT_INDEXED_SIZE_MISMATCH"; continue
            info = {}
            quality = candidate["quality"]
            if kind == "image":
                try:
                    data = _decrypt_cached_payload(data, image_keys)
                    if candidate.get("indexed_size") and len(data) != candidate["indexed_size"]:
                        last_error = "CHAT_DECODED_INDEXED_SIZE_MISMATCH"; continue
                    if data.startswith(b"wxgf"):
                        from .codec import CodecError, convert_wxgf_to_png
                        native_source = data
                        try:
                            data, info = convert_wxgf_to_png(native_source)
                        except CodecError as error:
                            raise ChatReadError(str(error)) from None
                        quality = info.pop("quality")
                        # Optional isolated private preservation of the exact
                        # decrypted source. Preview/source hashes stay distinct.
                        if native_source_dir is not None:
                            source_root = Path(native_source_dir).resolve(strict=True)
                            if not source_root.is_dir() or source_root.is_relative_to(root):
                                raise ChatReadError("CHAT_NATIVE_SOURCE_DIRECTORY_INVALID")
                            source_path = source_root / (info["native_source_sha256"] + ".wxgf")
                            if not source_path.exists():
                                with source_path.open("xb") as source_file:
                                    source_file.write(native_source)
                                    source_file.flush(); os.fsync(source_file.fileno())
                            if _sha_file(source_path) != info["native_source_sha256"]:
                                raise ChatReadError("CHAT_NATIVE_SOURCE_HASH_MISMATCH")
                            info["private_native_source_path"] = str(source_path)
                    info.update(_image_info(data))
                except ChatReadError as error:
                    last_error = error.code; continue
            else:
                expected = reference.get("expected_md5", "")
                if not _MD5.fullmatch(expected) or hashlib.md5(data).hexdigest() != expected:
                    last_error = "CHAT_FILE_CONTENT_HASH_MISMATCH"; continue
                if reference.get("expected_size") is not None and len(data) != reference["expected_size"]:
                    last_error = "CHAT_FILE_EXPECTED_SIZE_MISMATCH"; continue
                info["mime"] = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            staging = Path(staging_dir).resolve(strict=True)
            if not staging.is_dir() or staging.is_relative_to(root):
                raise ChatReadError("CHAT_STAGING_DIRECTORY_INVALID")
            digest = hashlib.sha256(data).hexdigest()
            destination = staging / digest
            temporary = staging / (digest + "." + uuid.uuid4().hex + ".part")
            try:
                with temporary.open("xb") as output:
                    output.write(data); output.flush(); os.fsync(output.fileno())
                os.replace(temporary, destination)
            finally:
                if temporary.exists():
                    temporary.unlink()
            if _sha_file(destination) != digest:
                raise ChatReadError("CHAT_STORED_HASH_MISMATCH")
            if kind == "image":
                _image_info(destination.read_bytes())
            result.update(state="VALIDATED", path=str(destination), sha256=digest, bytes=len(data),
                          quality=quality, reason=None, **info)
            return result
        raise ChatReadError(last_error)
    except ChatReadError as error:
        result["reason"] = error.code
        if error.code in {"CHAT_ATTACHMENT_CHANGED", "CHAT_LOCAL_FILE_UNAVAILABLE", "CHAT_IMAGE_KEY_REQUIRED"}:
            result["state"] = "RETRY_PENDING"
    except (OSError, ValueError, sqlite3.Error):
        result.update(state="RETRY_PENDING", reason="CHAT_ATTACHMENT_READ_FAILED")
    except Exception:
        result.update(state="UNAVAILABLE", reason="CHAT_ATTACHMENT_VALIDATION_FAILED")
    return result


def missing_history_capability():
    return {"status": "BLOCKED", "code": "REMOTE_NATIVE_HISTORY_MECHANISM_UNVERIFIED",
            "implemented": False, "local_snapshot_backfill": True,
            "reason": "No reviewed allowed route retrieves records absent from the native local snapshot.",
            "next_required_evidence": "A source-bound background history request and an independently known missing native record."}
