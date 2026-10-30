"""Exact-source index reconciliation over already-owned immutable snapshots.

The index hashes source payloads inside SQLite callbacks without decoding chat
compression, parsing media, staging raw bodies, or classifying unchanged rows.
Moments requires only its bounded XML envelope ID/time to preserve native IDs.
Fingerprint scans are a separate cost from full content parsing and inspection.
"""
from contextlib import closing
import hashlib
import json
import sqlite3
import struct
import xml.etree.ElementTree as ET

from . import chat, moments


def _raw(value):
    if value is None:
        return b"n", b""
    if isinstance(value, bytes):
        return b"b", value
    return b"s", str(value).encode("utf-8")


def fingerprint(*values):
    digest = hashlib.sha256(b"selected-source-index-v1\x00")
    size = 0
    for value in values:
        kind, data = _raw(value)
        digest.update(kind + struct.pack(">Q", len(data)) + data)
        size += len(data)
    return digest.hexdigest(), size


def moments_envelope(raw, tid):
    """Read only direct TimelineObject/id and createTime, up to 64 KiB.

    Full author/container/media checks still run for every changed event before
    returning a record. Unsupported envelope shapes stay explicit parse gaps.
    """
    data = raw if isinstance(raw, bytes) else str(raw).encode("utf-8")
    if b"<!DOCTYPE" in data[:65536].upper() or b"<!ENTITY" in data[:65536].upper():
        return str(tid), None
    end = data.find(b"</createTime>", 0, 65536)
    if end < 0:
        return str(tid), None
    data = data[:end + len(b"</createTime>")]
    # Do not feed historical body/media nodes to the envelope parser. The
    # observed native schema puts ID/time before these payload fields.
    if b"<contentDesc" in data or b"<ContentObject" in data:
        return str(tid), None
    parser = ET.XMLPullParser(events=("start", "end"))
    stack, ident, stamp = [], None, None
    try:
        for offset in range(0, min(len(data), 65536), 1024):
            parser.feed(data[offset:offset + 1024])
            for event, node in parser.read_events():
                if event == "start":
                    stack.append(node.tag)
                    continue
                direct = stack in (["TimelineObject", "id"], ["SnsDataItem", "TimelineObject", "id"])
                time_direct = stack in (["TimelineObject", "createTime"], ["SnsDataItem", "TimelineObject", "createTime"])
                if direct:
                    ident = (node.text or "").strip()
                elif time_direct:
                    value = (node.text or "").strip()
                    if value.isdecimal():
                        stamp = int(value)
                stack.pop()
                if ident is not None and stamp is not None:
                    return ident or str(tid), stamp
    except (ET.ParseError, UnicodeError, ValueError):
        pass
    return ident or str(tid), stamp


def moments_page(path, *, owned_root, author_id, known_revisions, limit=100, cursor=None,
                 start_epoch=None, end_epoch=None, baseline_index=False):
    if not author_id or author_id.endswith("@chatroom"):
        raise moments.ReaderError("AUTHOR_FILTER_REQUIRED")
    offset = 0 if cursor is None else cursor.get("offset")
    if not isinstance(offset, int) or offset < 0:
        raise moments.ReaderError("CURSOR_INDEX_OFFSET_INVALID")
    metrics = {"native_rows_inspected": 0, "index_entries_inspected": 0,
               "index_payload_bytes_hashed": 0, "new_or_changed": 0, "content_reads": 0}
    def index_value(tid, author, raw):
        revision, size = fingerprint("moments", str(tid), author, raw)
        ident, epoch = moments_envelope(raw, tid)
        metrics["index_payload_bytes_hashed"] += size
        metrics["native_rows_inspected"] += 1
        return json.dumps([revision, ident, epoch], ensure_ascii=False)
    records, issues, epochs, baseline_entries = [], [], [], []
    with closing(moments._connect(path, owned_root)) as connection:
        count, unique = connection.execute("SELECT COUNT(*),COUNT(DISTINCT tid) FROM SnsTimeLine WHERE user_name=?", (author_id,)).fetchone()
        if count != unique:
            raise moments.ReaderError("SNS_DUPLICATE_NATIVE_TID")
        connection.create_function("processing_index", 3, index_value)
        rows = connection.execute("SELECT tid,processing_index(tid,user_name,CAST(content AS BLOB)) AS idx FROM SnsTimeLine WHERE user_name=? ORDER BY tid DESC LIMIT ? OFFSET ?",
                                  (author_id, limit + 1, offset)).fetchall()
        exhausted = len(rows) <= limit
        for row in rows[:limit]:
            revision, ident, epoch = json.loads(row["idx"])
            metrics["index_entries_inspected"] += 1
            event_key = "moments:" + author_id + ":" + ident
            if baseline_index and epoch is not None:
                baseline_entries.append({"event_key": event_key, "native_revision": revision,
                                         "publication_epoch": epoch})
            if epoch is not None:
                epochs.append(epoch)
                if (start_epoch is not None and epoch < start_epoch) or (end_epoch is not None and epoch >= end_epoch):
                    continue
            if known_revisions.get(event_key) == revision:
                continue
            metrics["new_or_changed"] += 1
            full = connection.execute("SELECT tid,user_name,content FROM SnsTimeLine WHERE user_name=? AND tid=?", (author_id, row["tid"])).fetchone()
            metrics["content_reads"] += 1
            try:
                record = moments.parse_selected_post(full["tid"], full["user_name"], full["content"], author_id=author_id)
                actual_id = record["native_post_id"] or record["native_tid"]
                if actual_id != ident:
                    raise moments.ReaderError("SNS_INDEX_ENVELOPE_UNSUPPORTED")
                if (start_epoch is not None and record["publication_epoch"] < start_epoch) or (end_epoch is not None and record["publication_epoch"] >= end_epoch):
                    continue
                record["native_revision"] = revision
                records.append(record)
            except moments.ReaderError as error:
                issues.append({"event_key": event_key, "native_tid": str(row["tid"]),
                               "native_revision": revision, "code": str(error)})
    return {"records": records, "parse_issues": issues, "metrics": metrics,
            "baseline_entries": baseline_entries,
            "cursor": None if exhausted else {"offset": offset + len(rows[:limit])},
            "exhausted": exhausted, "observed_range": {"min_epoch": min(epochs), "max_epoch": max(epochs)} if epochs else None}


def _chat_revision(row, sender):
    keys = ("local_id", "server_id", "local_type", "real_sender_id", "create_time", "sort_seq",
            "message_content", "compress_content", "packed_info_data", "source")
    values = [row[key] if key not in keys[6:] or row[key] is None or isinstance(row[key], bytes)
              else str(row[key]).encode("utf-8") for key in keys]
    return fingerprint("chat", *values, sender)


def chat_page(snapshots, *, account_dir, account_id, friend_id, known_revisions,
              limit=100, cursor=None, start_epoch=None, end_epoch=None, baseline_index=False):
    account = chat._scope(account_dir, account_id, friend_id)
    entries = chat._snapshot_entries(snapshots, account)
    table = "Msg_" + hashlib.md5(friend_id.encode()).hexdigest()
    scope = [account_id, friend_id, start_epoch, end_epoch]
    last = None
    if cursor:
        if cursor.get("scope") != scope or cursor.get("version") != 1:
            raise chat.ChatReadError("CHAT_INDEX_CURSOR_SCOPE_MISMATCH")
        values = cursor.get("last")
        if not isinstance(values, list) or len(values) != 4:
            raise chat.ChatReadError("CHAT_INDEX_CURSOR_INVALID")
        last = (chat._integer(values[0]), chat._integer(values[1]), str(values[2]), chat._integer(values[3]))
    metrics = {"native_rows_inspected": 0, "index_entries_inspected": 0,
               "index_payload_bytes_hashed": 0, "new_or_changed": 0, "content_reads": 0}
    connections, indexes, selected, epochs = [], {}, [], []
    records, issues, baseline_entries = [], [], []
    try:
        for entry in entries:
            connection = chat._connect(entry["path"]); connections.append(connection)
            rel = entry["relative_path"]
            if rel in {"hardlink/hardlink.db", "message/message_resource.db"}:
                indexes[rel] = connection
                continue
            if not connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
                continue
            columns = chat._columns(connection, table)
            required = {"local_id", "server_id", "local_type", "real_sender_id", "create_time", "sort_seq", "message_content"}
            if not required <= columns or "user_name" not in chat._columns(connection, "Name2Id"):
                raise chat.ChatReadError("CHAT_MESSAGE_SCHEMA_UNSUPPORTED")
            senders = {int(row[0]): row[1] for row in connection.execute("SELECT rowid,user_name FROM Name2Id WHERE user_name IN (?,?)", (account_id, friend_id))}
            keys = ("local_id", "server_id", "local_type", "real_sender_id", "create_time", "sort_seq", "message_content", "compress_content", "packed_info_data", "source")
            expressions = ["\"" + key + "\"" if key in columns else "NULL" for key in keys]
            expressions[6:] = ["CAST(" + value + " AS BLOB)" for value in expressions[6:]]
            def index_value(*values, _senders=senders):
                sender = _senders.get(chat._integer(values[3] or 0))
                revision, size = fingerprint("chat", *values, sender)
                metrics["index_payload_bytes_hashed"] += size
                metrics["native_rows_inspected"] += 1
                return revision
            connection.create_function("processing_index", len(keys), index_value)
            where, args = [], []
            if start_epoch is not None and not baseline_index:
                where.append("create_time>=?"); args.append(start_epoch)
            if end_epoch is not None and not baseline_index:
                where.append("create_time<?"); args.append(end_epoch)
            if last:
                where.append("(create_time,sort_seq,?,local_id)>(?,?,?,?)"); args += [rel, *last]
            query = 'SELECT local_id,create_time,sort_seq,processing_index(' + ",".join(expressions) + ') AS revision FROM "' + table + '"'
            if where:
                query += " WHERE " + " AND ".join(where)
            query += " ORDER BY create_time,sort_seq,local_id LIMIT ?"
            for row in connection.execute(query, [*args, limit + 1]):
                key = (chat._integer(row["create_time"]), chat._integer(row["sort_seq"]), rel, chat._integer(row["local_id"]))
                selected.append((key, row["revision"], entry, connection, senders, columns))
        selected.sort(key=lambda value: value[0])
        exhausted = len(selected) <= limit
        for key, revision, entry, connection, senders, columns in selected[:limit]:
            metrics["index_entries_inspected"] += 1
            epochs.append(key[0])
            native_id = entry["relative_path"] + "/" + table + "/" + str(key[3])
            event_key = chat._hash_json([account_id, friend_id, native_id])
            if baseline_index:
                baseline_entries.append({"event_key": event_key, "native_revision": revision,
                                         "publication_epoch": key[0]})
            if (start_epoch is not None and key[0] < start_epoch) or (end_epoch is not None and key[0] >= end_epoch):
                continue
            if known_revisions.get(event_key) == revision:
                continue
            metrics["new_or_changed"] += 1
            optional = ",".join('"' + field + '"' if field in columns else 'NULL AS "' + field + '"' for field in ("packed_info_data", "compress_content", "source"))
            row = connection.execute('SELECT local_id,server_id,local_type,real_sender_id,create_time,sort_seq,message_content,' + optional + ' FROM "' + table + '" WHERE local_id=?', (key[3],)).fetchone()
            metrics["content_reads"] += 1
            if _chat_revision(row, senders.get(chat._integer(row["real_sender_id"] or 0)))[0] != revision:
                raise chat.ChatReadError("CHAT_INDEX_SNAPSHOT_CHANGED")
            try:
                record = chat._record(row, entry, table, senders, account_id, friend_id,
                                      indexes.get("hardlink/hardlink.db"), indexes.get("message/message_resource.db"))
                record["native_revision"] = revision
                records.append(record)
            except chat.ChatReadError as error:
                issues.append({"event_key": event_key, "native_id": native_id, "native_revision": revision, "code": error.code})
        next_cursor = None
        if selected and not exhausted:
            key = selected[min(limit, len(selected)) - 1][0]
            next_cursor = {"version": 1, "scope": scope, "last": [str(key[0]), str(key[1]), key[2], str(key[3])]}
        return {"records": records, "parse_issues": issues, "metrics": metrics,
                "baseline_entries": baseline_entries,
                "cursor": next_cursor, "exhausted": exhausted,
                "observed_range": {"min_epoch": min(epochs), "max_epoch": max(epochs)} if epochs else None}
    except sqlite3.Error:
        raise chat.ChatReadError("CHAT_INDEX_SCHEMA_OR_QUERY_UNSUPPORTED") from None
    finally:
        for connection in connections:
            connection.close()
