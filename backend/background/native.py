"""Maintained background-only adapter with explicit account and source binding.

No import performs process, source database, network or UI access. Database keys
exist only in this object's memory. Source XML, access URLs and local locators
are isolated under background-private; public results contain opaque references.
"""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import hashlib
import heapq
import importlib
import json
from pathlib import Path
import re
import shutil
import sqlite3
import sys
import threading
import time
import uuid

from . import access, binding, moments, snapshot as copies


class NativeError(RuntimeError):
    """Fixed safe code, never raw OS/SQLite/network exception strings."""


def _json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False)


def _scope(scope):
    scope = scope or {}
    def epoch(value):
        if value is None or value == "":
            return None
        if isinstance(value, (int, float)):
            return int(value)
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError()
            return int(parsed.timestamp())
        except ValueError:
            raise NativeError("DATE_RANGE_REQUIRES_TIMEZONE") from None
    start = epoch(scope.get("start_epoch", scope.get("start")))
    end = epoch(scope.get("end_epoch", scope.get("end")))
    if start is not None and end is not None and start >= end:
        raise NativeError("DATE_RANGE_INVALID")
    return {"start_epoch": start, "end_epoch": end}


class BackgroundNative:
    def __init__(self, root: Path, config: dict):
        self.root = Path(root).resolve()
        self.config = dict(config or {})
        self.private = self.root / "background-private"
        self.private.mkdir(parents=True, exist_ok=True)
        self.expected_account = self.config.get("expected_account_id", self.config.get("account_native_id", ""))
        self.expected_friend = self.config.get("expected_friend_id", "")
        self.friend_name = self.config.get("friend_name", "")
        self._identity = None
        self._binding = None
        self._friend = None
        self._keys = {}
        self._image_keys = None
        self._image_probe_at = 0.0
        self._image_candidate = None
        self._image_candidate_identity = None
        self._image_candidate_at = 0.0
        self._image_candidate_attempts = 0
        self._snapshots = {}
        self._change_stamp_cache = {}
        self._stamp_bytes = {}
        self._private_gc_cursor = ""
        self._lock = threading.RLock()

    @staticmethod
    def capabilities():
        return {"database_read": "IMPLEMENTED_BOUND_LOCAL_SNAPSHOTS",
                "database_key_access": "PASSIVE_READ_ONLY_SESSION_CACHE",
                "moments_media": "KNOWN_RECORD_URL_ONLY",
                "chat_media": "EXACT_INDEX_ASSOCIATION_REQUIRED",
                "image_key_access": "PASSIVE_BOUND_ACCOUNT_CANDIDATE_REQUIRES_MEDIA_VALIDATION",
                "uncached_history": "BLOCKED_NO_AUTHORIZED_REMOTE_PATH",
                "missing_media_remote": "BLOCKED_NO_AUTHORIZED_REMOTE_PATH",
                "live_new_content": "NOT_TESTED"}

    def _invalidate(self):
        self._keys.clear()
        self._image_keys = None
        self._image_probe_at = 0.0
        self._clear_image_candidate()
        self._snapshots.clear()
        self._change_stamp_cache.clear()
        self._stamp_bytes.clear()
        self._friend = None
        self._binding = None
        self._identity = None

    def _clear_image_candidate(self):
        self._image_candidate = None
        self._image_candidate_identity = None
        self._image_candidate_at = 0.0
        self._image_candidate_attempts = 0

    def _observe(self):
        try:
            pid = binding.discover_pid()
            report = binding.probe_bounded(pid)
            account = Path(report["account_directory"]).resolve(strict=True)
            expected = self.expected_account
            if not (account.name == expected or account.name.startswith(expected + "_")):
                raise NativeError("AUTHENTICATED_ACCOUNT_CHANGED")
            if not report.get("process_to_database_binding_complete"):
                raise NativeError("ACCOUNT_PROCESS_BINDING_INCOMPLETE")
            identity = (report["pid"], report["creation_filetime"], str(account).casefold(), report["executable_path"].casefold())
            if self._identity is not None and identity != self._identity:
                self._invalidate()
                raise NativeError("ACCOUNT_OR_PROCESS_CHANGED")
            self._identity, self._binding = identity, report
            return report
        except NativeError:
            self._invalidate()
            raise
        except Exception as error:
            self._invalidate()
            code = str(error)
            if not re.fullmatch(r"[A-Z][A-Z_]{3,80}", code):
                code = "ACCOUNT_PROCESS_BINDING_UNAVAILABLE"
            raise NativeError(code) from None

    def _safe_binding(self):
        b = self._binding
        return {"status": "BOUND", "identity_verified": self._friend is not None,
                "account_native_id": self.expected_account, "friend_native_id": self._friend,
                "account_display_name": self.config.get("account_display_name", "采集账号"),
                "friend_name": self.friend_name, "pid": b["pid"],
                "creation_filetime": b["creation_filetime"],
                "client_version": next((r.get("file_version") for r in b.get("loaded_weixin_dll", []) if r.get("file_version")), None),
                "account_directory": b["account_directory"],
                "observed_database_paths": [r["path"] for r in b["database_handles"] if r["path"].lower().endswith(".db")],
                "capabilities": self.capabilities()}

    def bind(self):
        if not all((self.expected_account, self.expected_friend, self.friend_name, self.config.get("account_display_name"))):
            raise NativeError("FRESH_LOCAL_BINDING_REQUIRED")
        with self._lock:
            self._observe()
            if self._friend is None:
                contact = self._snapshot("contact")
                with closing(moments._connect(contact["files"][0]["path"], self.private)) as conn:
                    self_rows = conn.execute("SELECT username,nick_name FROM contact WHERE username=? LIMIT 2", (self.expected_account,)).fetchall()
                expected_display = self.config["account_display_name"]
                if len(self_rows) != 1 or self_rows[0]["nick_name"] != expected_display:
                    self._invalidate()
                    raise NativeError("AUTHENTICATED_ACCOUNT_CONTACT_UNVERIFIED")
                found = moments.resolve_contact(contact["files"][0]["path"], owned_root=self.private, exact_name=self.friend_name)
                if found["status"] != "VERIFIED_EXACT_MAPPING" or found["author_id"] != self.expected_friend:
                    self._invalidate()
                    raise NativeError("FRIEND_IDENTITY_UNVERIFIED")
                self._friend = found["author_id"]
                self.release_snapshot(contact["snapshot_id"])
            return self._safe_binding()

    def _paths(self, kind):
        valid = {}
        for row in self._binding["database_handles"]:
            path = Path(row["path"])
            name = path.name.casefold()
            if not name.endswith(".db"):
                continue
            stem = name[:-3]
            if not re.fullmatch(r"contact|sns|message_\d+|message_resource|hardlink", stem):
                continue
            if kind == stem or (kind in {"chat", "message"} and (stem.startswith("message_") or stem == "hardlink")):
                valid[stem] = str(path)
        if not valid or (kind in {"chat", "message"} and not any(re.fullmatch(r"message_\d+", k) for k in valid)):
            raise NativeError("REQUIRED_DATABASE_HANDLE_NOT_OBSERVED")
        return valid

    def snapshot(self, kind):
        with self._lock:
            self.bind()
            return self._snapshot("sns" if kind == "moments" else kind)

    def _snapshot(self, kind):
        self._pending_snapshot = None
        try:
            return self._snapshot_work(kind)
        except Exception as error:
            pending = self._pending_snapshot
            if pending is not None:
                base = (self.private / "snapshots").resolve()
                pending = pending.resolve()
                if pending.is_relative_to(base) and pending != base and re.fullmatch(r"[0-9a-f]{32}", pending.name):
                    code = str(error)
                    if not re.fullmatch(r"[A-Z][A-Z_]{3,80}", code):
                        code = "SNAPSHOT_ATTEMPT_FAILED"
                    audit = {"snapshot_id": pending.name, "kind": kind, "status": "FAILED",
                             "reason": code, "source_coverage": "UNKNOWN",
                             "released_at": datetime.now(timezone.utc).isoformat()}
                    key_report = pending / "key-result-safe.json"
                    if key_report.is_file():
                        audit["key_access"] = json.loads(key_report.read_text(encoding="utf-8"))
                    _json(self.private / "audit" / (pending.name + ".json"), audit)
                    shutil.rmtree(pending)
            raise
        finally:
            self._pending_snapshot = None

    def _snapshot_work(self, kind):
        try:
            importlib.import_module("cryptography.hazmat.primitives.ciphers")
        except ImportError:
            raise NativeError("CRYPTOGRAPHY_DEPENDENCY_UNAVAILABLE") from None
        paths = self._paths(kind)
        identifier = uuid.uuid4().hex
        folder = self.private / "snapshots" / identifier
        folder.mkdir(parents=True, exist_ok=False)
        self._pending_snapshot = folder
        captured = copies.capture(paths, self._binding["account_directory"], folder / "encrypted")
        # Reject logout/account or PID reuse during the full snapshot window.
        self._observe()
        b = self._binding
        evidence = folder / "binding.json"; _json(evidence, b)
        base_rows = [r for r in captured["files"] if not r["suffix"]]
        missing = []
        for row in base_rows:
            with Path(row["copy_path"]).open("rb") as stream:
                page = stream.read(4096)
            key = self._keys.get(row["kind"])
            if key is None or not access._verify(key[:32], page, key[32:] if len(key) == 48 else None):
                self._keys.pop(row["kind"], None)
                # The same session key may cover another explicitly bound DB.
                for candidate in list(self._keys.values()):
                    if access._verify(candidate[:32], page, candidate[32:] if len(candidate) == 48 else None):
                        self._keys[row["kind"]] = candidate
                        break
                else:
                    missing.append(row)
        if missing:
            if self.config.get("passive_key_read_approved", True) is not True:
                raise NativeError("PASSIVE_KEY_ACCESS_NOT_APPROVED")
            access_binding = {"schema_version": 1,
                "authorization": {"current_authenticated_account_selected": True,
                    "passive_key_read_approved": True, "confirmed_by": "user",
                    "confirmation_reference": "Approved continuous current-account Moments and one-to-one friend chat background read"},
                "process": {k: b[k] for k in ("pid", "creation_filetime", "executable_path")},
                "account": {"directory": b["account_directory"], "handle_binding_verified": True,
                            "handle_evidence": str(evidence)}, "storage_root": str(self.private),
                "database_copies": [{**r, "active_handle_verified": True} for r in missing]}
            access_path = folder / "access.json"; _json(access_path, access_binding)
            keys, report = access.probe(access_path, **access_binding["process"])
            _json(folder / "key-result-safe.json", report)
            self._observe()
            self._keys.update(keys)
            if any(row["kind"] not in self._keys for row in missing):
                raise NativeError("DATABASE_KEY_UNAVAILABLE")
        files, validation = [], {}
        for row in base_rows:
            wal = next((r for r in captured["files"] if r["kind"] == row["kind"] and r["suffix"] == "-wal"), None)
            output = folder / "decrypted" / (row["kind"] + ".db")
            result = moments.decrypt_snapshot(row["copy_path"], wal["copy_path"] if wal else None,
                self._keys[row["kind"]], output, owned_root=self.private,
                expected_database_sha256=row["sha256"], expected_wal_sha256=wal["sha256"] if wal else None,
                byte_budget=int(self.config.get("snapshot_byte_budget", 512 * 1024 * 1024)))
            bucket = "message" if row["kind"].startswith("message_") else row["kind"]
            files.append({"path": str(output), "relative_path": bucket + "/" + row["kind"] + ".db",
                          "sha256": result["decrypted_sha256"], "kind": row["kind"]})
            validation[row["kind"]] = result
        self._observe()
        result = {"snapshot_id": identifier, "kind": kind, "files": files,
                  "stable": True, "coverage": "UNKNOWN", "identity": list(self._identity),
                  "validation": validation}
        _json(folder / "manifest.json", result)
        self._snapshots[identifier] = result
        return result

    def release_snapshot(self, snapshot_id, *, disposition="completed", reason=None):
        """Drop an owned completed snapshot or an uncommitted failed discovery.

        Active cursor snapshots remain on disk across close/restart. The caller
        must only release completed pages after their cursor commit succeeds.
        Failed initial discovery has no committed cursor and keeps a safe audit.
        """
        with self._lock:
            if not isinstance(snapshot_id, str) or not re.fullmatch(r"[0-9a-f]{32}", snapshot_id):
                raise NativeError("SNAPSHOT_ID_INVALID")
            base = (self.private / "snapshots").resolve()
            folder = (base / snapshot_id).resolve()
            if not folder.is_relative_to(base) or folder == base:
                raise NativeError("SNAPSHOT_RELEASE_OUTSIDE_PRIVATE_ROOT")
            if not folder.is_dir():
                self._snapshots.pop(snapshot_id, None)
                return
            manifest = folder / "manifest.json"
            if not manifest.is_file():
                raise NativeError("SNAPSHOT_RELEASE_MANIFEST_REQUIRED")
            value = json.loads(manifest.read_text(encoding="utf-8"))
            if value.get("snapshot_id") != snapshot_id:
                raise NativeError("SNAPSHOT_RELEASE_ID_MISMATCH")
            audit = {"snapshot_id": snapshot_id, "kind": value.get("kind"),
                     "stable": value.get("stable"), "coverage": "UNKNOWN",
                     "validation": value.get("validation", {}),
                     "disposition": disposition, "reason": reason,
                     "released_at": datetime.now(timezone.utc).isoformat()}
            destination = self.private / "audit" / (snapshot_id + ".json")
            if not destination.exists():
                _json(destination, audit)
            shutil.rmtree(folder)
            self._snapshots.pop(snapshot_id, None)

    def close(self):
        with self._lock:
            self._invalidate()

    def _private_record(self, value):
        # Stable private IDs avoid duplicate URL/XML files on every full poll.
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
        reference = hashlib.sha256(encoded).hexdigest()[:32]
        path = self.private / "references" / (reference + ".json")
        if not path.exists():
            _json(path, value)
        return reference

    def _sanitize(self, record, source_kind):
        if source_kind == "moments":
            event = "moments:" + record["author_id"] + ":" + (record["native_post_id"] or record["native_tid"])
            result = {"event_key": event, "native_id": record["native_post_id"] or record["native_tid"],
                      "native_post_id": record["native_post_id"], "type": "post",
                      "native_tid": record["native_tid"], "author_id": record["author_id"],
                      "publication_time": record["publication_time"], "source_time_raw": record["publication_time_raw"],
                      "publication_epoch": record["publication_epoch"], "source_sha256": record["source_fullxml_sha256"],
                      "text": record["text"], "source_kind": "moments", "identity_verified": True,
                      "attachments": []}
            for media in record["media"]:
                private = {"source_kind": "moments", "account_id": self.expected_account,
                           "friend_id": self._friend, "post_id": record["native_post_id"], "media": media}
                result["attachments"].append({"native_id": str(media["native_media_id"]),
                    "media_index": media["media_index"], "index": media["media_index"],
                    "kind": "image" if media["type_raw"] in {"2", ""} else "unsupported",
                    "type": "image" if media["type_raw"] in {"2", ""} else "file",
                    "name": str(record["native_post_id"] or record["native_tid"]) + "-" + str(media["media_index"]) + ".jpg",
                    "mime": "image/jpeg" if media["type_raw"] in {"2", ""} else "application/octet-stream",
                    "type_raw": media["type_raw"], "state": "PENDING", "quality": "unknown_CDN_rendition",
                    "private_ref": self._private_record(private)})
            result["private_source_ref"] = self._private_record({"source_kind": "moments_record", "event_key": event, "record": record})
            if record.get("native_revision"):
                result["native_revision"] = record["native_revision"]
            return result
        result = dict(record)
        private_source = result.pop("private_source", None)
        if private_source is not None:
            result["private_source_ref"] = self._private_record({"source_kind": "chat_record", "event_key": result["event_key"],
                                  "account_id": self.expected_account, "friend_id": self._friend,
                                  "source": private_source})
        result["source_kind"] = "chat"
        result["identity_verified"] = record.get("native_id_verified") is True and record.get("conversation_id") == self._friend
        result["sender_identity_verified"] = record.get("author_id") in {self.expected_account, self._friend}
        result["attachments"] = []
        for attachment in record.get("attachments", []):
            safe = dict(attachment)
            private = safe.pop("private_reference", None)
            if private is not None:
                safe["private_ref"] = self._private_record({"source_kind": "chat", "account_id": self.expected_account,
                    "friend_id": self._friend, "reference": private})
            result["attachments"].append(safe)
        return result

    def discard_private(self, values, *, protected_refs=()):
        """Remove explicitly discarded processing payloads after ledger commit.

        The caller protects opaque IDs referenced by retained materials/pending
        candidates. No client/cache paths or historical engineering evidence are
        eligible. A skipped receipt does not need any of these private bodies.
        """
        references = set()
        for value in values:
            if isinstance(value, str):
                references.add(value)
            elif isinstance(value, dict):
                if value.get("private_source_ref"):
                    references.add(value["private_source_ref"])
                if value.get("private_ref"):
                    references.add(value["private_ref"])
                references.update(a["private_ref"] for a in value.get("attachments", []) if a.get("private_ref"))
        protected = set(protected_refs)
        removed = 0
        with self._lock:
            folder = (self.private / "references").resolve()
            for reference in references - protected:
                if not isinstance(reference, str) or not re.fullmatch(r"[0-9a-f]{32}", reference):
                    raise NativeError("PRIVATE_REFERENCE_INVALID")
                path = folder / (reference + ".json")
                if path.exists():
                    if path.resolve().parent != folder:
                        raise NativeError("PRIVATE_REFERENCE_OUTSIDE_ROOT")
                    path.unlink(); removed += 1
        return {"removed_references": removed}

    def gc_private_references(self, retained_refs, *, older_than_seconds=3600, max_files=1000):
        """Bounded cleanup of orphaned private references; never infer relevance."""
        if older_than_seconds < 0 or not 1 <= max_files <= 10000:
            raise NativeError("PRIVATE_CLEANUP_BOUND_INVALID")
        retained = set(retained_refs)
        root = self.private / "references"
        cutoff, candidates, scanned = time.time() - older_than_seconds, [], 0
        # Advance across protected files too, so a large retained prefix cannot
        # permanently starve orphan cleanup. Only this bounded page is stat/read.
        names = heapq.nsmallest(max_files, (path.name for path in root.glob("*.json")
                                         if path.name > self._private_gc_cursor))
        for name in names:
            path = root / name
            scanned += 1
            if path.stem not in retained and path.stat().st_mtime <= cutoff:
                candidates.append(path.stem)
        self._private_gc_cursor = names[-1] if len(names) == max_files else ""
        return {**self.discard_private(candidates, protected_refs=retained), "scanned_references": scanned,
                "cleanup_cursor": self._private_gc_cursor or None}

    def source_change_stamp(self, source_kind):
        """Cheap change hint over bound file metadata and DB/WAL edge samples.

        This is not a proof of unchanged source content. The scheduler must use
        a separately bounded periodic forced index reconciliation. No snapshot,
        decryption, text parsing, OCR or media retrieval occurs on a warm bind.
        """
        with self._lock:
            if source_kind not in {"moments", "chat"}:
                raise NativeError("DISCOVERY_SCOPE_INVALID")
            self.bind()
            paths = self._paths("sns" if source_kind == "moments" else "chat")
            account = Path(self._binding["account_directory"]).resolve(strict=True)
            values, sampled = [], 0
            for kind, value in sorted(paths.items()):
                base = Path(value).resolve(strict=True)
                bucket = "message" if kind.startswith("message_") else kind
                if base != (account / "db_storage" / bucket / (kind + ".db")).resolve(strict=True):
                    raise NativeError("CHANGE_STAMP_SOURCE_NOT_BOUND")
                for suffix in ("", "-wal"):
                    path = Path(str(base) + suffix)
                    try:
                        before = path.stat()
                    except FileNotFoundError:
                        if not suffix:
                            raise NativeError("CHANGE_STAMP_DATABASE_MISSING") from None
                        values.append([kind, suffix, None]); continue
                    if path.resolve().parent != base.parent:
                        raise NativeError("CHANGE_STAMP_SOURCE_NOT_BOUND")
                    with path.open("rb") as stream:
                        head = stream.read(4096)
                        tail = b""
                        if before.st_size > 4096:
                            stream.seek(max(4096, before.st_size - 4096)); tail = stream.read(4096)
                    after = path.stat()
                    left = (before.st_size, before.st_mtime_ns, before.st_ctime_ns, before.st_ino)
                    right = (after.st_size, after.st_mtime_ns, after.st_ctime_ns, after.st_ino)
                    if left != right:
                        raise NativeError("CHANGE_STAMP_SOURCE_UNSTABLE")
                    sampled += len(head) + len(tail)
                    values.append([kind, suffix, list(left), hashlib.sha256(head + tail).hexdigest()])
            stamp = hashlib.sha256(json.dumps([list(self._identity), self._friend, source_kind, values], sort_keys=True).encode()).hexdigest()
            self._change_stamp_cache[source_kind] = stamp
            self._stamp_bytes[source_kind] = sampled
            return stamp

    def discover_processing(self, source_kind, scope, cursor=None, limit=100,
                            known_revisions=None, *, force=False, previous_change_stamp=None,
                            baseline_index=False):
        """Compare a lightweight native index; parse/stage only undecided revisions.

        known_revisions maps exact event_key to native_revision from the durable
        processing ledger, including SKIP receipts. force bypasses only the cheap
        stamp shortcut; explicit reprocessing passes an empty/subset receipt map.
        """
        from . import processing_index
        with self._lock:
            if source_kind not in {"moments", "chat"} or not 1 <= limit <= 1000:
                raise NativeError("DISCOVERY_SCOPE_INVALID")
            known = known_revisions or {}
            if not isinstance(known, dict):
                raise NativeError("PROCESSING_RECEIPTS_INVALID")
            self.bind()
            bounds = _scope(scope)
            pending_snapshot = None
            copies_count, sampled, stamp = 0, 0, None
            try:
                if cursor is None:
                    stamp = self.source_change_stamp(source_kind)
                    sampled = self._stamp_bytes.get(source_kind, 0)
                    if not force and not baseline_index and previous_change_stamp is not None and stamp == previous_change_stamp:
                        return {"items": [], "parse_issues": [], "cursor": None, "exhausted": True,
                            "baseline_entries": [],
                            "snapshot_id": None, "change_stamp": stamp, "source_unchanged": True,
                            "coverage": "UNKNOWN", "observed_range": None,
                            "metrics": {"native_rows_inspected": 0, "index_entries_inspected": 0,
                                "index_payload_bytes_hashed": 0, "new_or_changed": 0,
                                "content_reads": 0, "snapshot_copies": 0, "change_stamp_sampled_bytes": sampled}}
                    snap = self._snapshot("sns" if source_kind == "moments" else "chat")
                    pending_snapshot = snap["snapshot_id"]
                    copies_count = 1
                    after = self.source_change_stamp(source_kind)
                    sampled += self._stamp_bytes.get(source_kind, 0)
                    if after != stamp:
                        stamp = None
                    inner = None
                else:
                    if (not isinstance(cursor, dict) or cursor.get("version") != 2
                            or cursor.get("source_kind") != source_kind or cursor.get("scope") != bounds
                            or bool(cursor.get("baseline_index")) != bool(baseline_index)):
                        raise NativeError("CURSOR_PROCESSING_SCOPE_MISMATCH")
                    sid = cursor.get("snapshot_id")
                    if not isinstance(sid, str) or not re.fullmatch(r"[0-9a-f]{32}", sid):
                        raise NativeError("CURSOR_SNAPSHOT_INVALID")
                    snap = self._snapshots.get(sid)
                    if snap is None:
                        path = self.private / "snapshots" / sid / "manifest.json"
                        if not path.is_file():
                            raise NativeError("CURSOR_SNAPSHOT_UNAVAILABLE")
                        snap = json.loads(path.read_text(encoding="utf-8"))
                    if snap.get("identity") != list(self._identity):
                        raise NativeError("CURSOR_ACCOUNT_OR_PROCESS_CHANGED")
                    inner, stamp = cursor.get("inner"), cursor.get("change_stamp")
                for file in snap["files"]:
                    if copies.digest(moments._owned_file(file["path"], self.private)) != file["sha256"]:
                        raise NativeError("IMMUTABLE_SNAPSHOT_CHANGED")
                if source_kind == "moments":
                    page = processing_index.moments_page(snap["files"][0]["path"], owned_root=self.private,
                        author_id=self._friend, known_revisions=known, limit=limit, cursor=inner,
                        baseline_index=baseline_index, **bounds)
                else:
                    page = processing_index.chat_page(snap["files"], account_dir=self._binding["account_directory"],
                        account_id=self.expected_account, friend_id=self._friend,
                        known_revisions=known, limit=limit, cursor=inner, baseline_index=baseline_index, **bounds)
                items = [self._sanitize(record, source_kind) for record in page["records"]]
                next_cursor = None if page["exhausted"] else {"version": 2, "source_kind": source_kind,
                    "scope": bounds, "snapshot_id": snap["snapshot_id"], "inner": page["cursor"],
                    "change_stamp": stamp, "baseline_index": bool(baseline_index)}
                metrics = {**page["metrics"], "snapshot_copies": copies_count,
                           "change_stamp_sampled_bytes": sampled}
                return {"items": items, "parse_issues": page["parse_issues"], "cursor": next_cursor,
                        "baseline_entries": page["baseline_entries"],
                        "exhausted": page["exhausted"], "snapshot_id": snap["snapshot_id"],
                        "change_stamp": stamp, "source_unchanged": False,
                        "observed_range": page["observed_range"], "coverage": "UNKNOWN", "metrics": metrics}
            except Exception as error:
                if pending_snapshot is not None:
                    code = str(error)
                    if not re.fullmatch(r"[A-Z][A-Z_]{3,80}", code):
                        code = "SNAPSHOT_INDEX_QUERY_FAILED"
                    self.release_snapshot(pending_snapshot, disposition="failed_initial_discovery", reason=code)
                raise

    def discover(self, source_kind, scope, cursor=None, limit=100):
        """Keep returned pages resumable; discard only uncommitted query failures."""
        with self._lock:
            self._pending_discovery_snapshot = None
            try:
                return self._discover_page(source_kind, scope, cursor, limit)
            except Exception as error:
                snapshot_id = self._pending_discovery_snapshot
                if snapshot_id is not None:
                    code = str(error)
                    if not re.fullmatch(r"[A-Z][A-Z_]{3,80}", code):
                        code = "SNAPSHOT_DISCOVERY_QUERY_FAILED"
                    self.release_snapshot(snapshot_id, disposition="failed_initial_discovery", reason=code)
                raise
            finally:
                self._pending_discovery_snapshot = None

    def _discover_page(self, source_kind, scope, cursor=None, limit=100):
        with self._lock:
            if source_kind not in {"moments", "chat"} or not 1 <= limit <= 1000:
                raise NativeError("DISCOVERY_SCOPE_INVALID")
            self.bind()
            bounds = _scope(scope)
            if cursor is None:
                snap = self._snapshot("sns" if source_kind == "moments" else "chat")
                # No caller has committed a cursor to this fresh snapshot yet.
                # Existing cursor snapshots are preserved on an interrupted read.
                self._pending_discovery_snapshot = snap["snapshot_id"]
                offset, inner = 0, None
            else:
                if not isinstance(cursor, dict) or cursor.get("source_kind") != source_kind or cursor.get("scope") != bounds:
                    raise NativeError("CURSOR_SCOPE_MISMATCH")
                sid = cursor.get("snapshot_id")
                if not isinstance(sid, str) or not re.fullmatch(r"[0-9a-f]{32}", sid):
                    raise NativeError("CURSOR_SNAPSHOT_INVALID")
                snap = self._snapshots.get(sid)
                if snap is None:
                    path = self.private / "snapshots" / sid / "manifest.json"
                    if not path.is_file():
                        raise NativeError("CURSOR_SNAPSHOT_UNAVAILABLE")
                    snap = json.loads(path.read_text(encoding="utf-8"))
                if snap.get("identity") != list(self._identity):
                    raise NativeError("CURSOR_ACCOUNT_OR_PROCESS_CHANGED")
                offset, inner = int(cursor.get("offset", 0)), cursor.get("inner")
            for file in snap["files"]:
                path = moments._owned_file(file["path"], self.private)
                if copies.digest(path) != file["sha256"]:
                    raise NativeError("IMMUTABLE_SNAPSHOT_CHANGED")
            if source_kind == "chat":
                from .chat import read_chat_page
                page = read_chat_page(snap["files"], account_dir=self._binding["account_directory"],
                    account_id=self.expected_account, friend_id=self._friend, limit=limit,
                    cursor=inner, **bounds)
                items = [self._sanitize(record, "chat") for record in page["records"]]
                exhausted = page["exhausted"]
                next_cursor = {"snapshot_id": snap["snapshot_id"], "source_kind": source_kind,
                    "scope": bounds, "inner": page["next_cursor"]} if not exhausted else None
                return {"items": items, "cursor": next_cursor, "exhausted": exhausted,
                        "observed_range": page.get("observed_range"), "coverage": "UNKNOWN",
                        "snapshot_id": snap["snapshot_id"]}
            path = snap["files"][0]["path"]
            with closing(moments._connect(path, self.private)) as conn:
                count, distinct = conn.execute("SELECT COUNT(*),COUNT(DISTINCT tid) FROM SnsTimeLine WHERE user_name=?", (self._friend,)).fetchone()
                if count != distinct:
                    raise NativeError("SNS_DUPLICATE_NATIVE_TID")
                rows = conn.execute("SELECT tid,user_name,content FROM SnsTimeLine WHERE user_name=? ORDER BY tid DESC LIMIT ? OFFSET ?",
                                    (self._friend, limit + 1, offset)).fetchall()
            exhausted = len(rows) <= limit
            records, issues, epochs = [], [], []
            for row in rows[:limit]:
                try:
                    record = moments.parse_selected_post(row["tid"], row["user_name"], row["content"], author_id=self._friend)
                    epoch = record["publication_epoch"]
                    epochs.append(epoch)
                    if ((bounds["start_epoch"] is None or epoch >= bounds["start_epoch"])
                            and (bounds["end_epoch"] is None or epoch < bounds["end_epoch"])):
                        records.append(self._sanitize(record, "moments"))
                except moments.ReaderError as error:
                    issues.append({"native_tid": str(row["tid"]), "code": str(error)})
            next_cursor = {"snapshot_id": snap["snapshot_id"], "source_kind": source_kind,
                "scope": bounds, "offset": offset + min(len(rows), limit)} if not exhausted else None
            return {"items": records, "cursor": next_cursor, "exhausted": exhausted,
                    "observed_range": {"min_epoch": min(epochs), "max_epoch": max(epochs)} if epochs else None,
                    "coverage": "UNKNOWN", "snapshot_id": snap["snapshot_id"], "parse_issues": issues,
                    "stop_reason": "LOCAL_ROWS_EXHAUSTED_WITH_PARSE_GAPS" if exhausted and issues else ("LOCAL_ROWS_EXHAUSTED" if exhausted else "PAGE_LIMIT")}

    def retrieve(self, attachment, staging_dir):
        with self._lock:
            self.bind()
            reference = attachment.get("private_ref", "")
            if not isinstance(reference, str) or not re.fullmatch(r"[0-9a-f]{32}", reference):
                return {"state": "UNAVAILABLE", "reason": "ATTACHMENT_PRIVATE_REFERENCE_MISSING"}
            path = self.private / "references" / (reference + ".json")
            if not path.is_file():
                return {"state": "UNAVAILABLE", "reason": "ATTACHMENT_PRIVATE_REFERENCE_MISSING"}
            private = json.loads(path.read_text(encoding="utf-8"))
            if private.get("account_id") != self.expected_account or private.get("friend_id") != self._friend:
                raise NativeError("ATTACHMENT_IDENTITY_MISMATCH")
            output = Path(staging_dir).resolve()
            if not output.is_relative_to(self.root) or output.is_relative_to(Path(self._binding["account_directory"]).resolve()):
                raise NativeError("ATTACHMENT_STAGING_NOT_ISOLATED")
            output.mkdir(parents=True, exist_ok=True)
            if private["source_kind"] == "chat":
                from .chat import retrieve_chat
                result = retrieve_chat(private["reference"], output, account_dir=self._binding["account_directory"],
                                       account_id=self.expected_account, friend_id=self._friend, image_keys=self._image_keys)
                needs_key = result.get("reason") == "CHAT_IMAGE_KEY_REQUIRED"
                if self._image_keys is not None and result.get("reason") in {"CHAT_IMAGE_DECRYPTION_FAILED", "CHAT_ATTACHMENT_VALIDATION_FAILED"}:
                    self._image_keys = None
                    needs_key = True
                retry_after = max(60, int(self.config.get("image_key_probe_retry_seconds", 300)))
                if needs_key and self.config.get("passive_key_read_approved", True) is not True:
                    self._clear_image_candidate()
                    return {"state": "UNAVAILABLE", "reason": "PASSIVE_KEY_ACCESS_NOT_APPROVED"}
                if needs_key:
                    now = time.monotonic()
                    if (self._image_candidate_identity != self._identity
                            or now - self._image_candidate_at >= 300
                            or self._image_candidate_attempts >= 64):
                        self._clear_image_candidate()
                    candidate = self._image_candidate
                    safe = {"reason": "CANDIDATE_REUSED_FOR_REQUESTED_OCCURRENCE"}
                    if candidate is None and (not self._image_probe_at or now - self._image_probe_at >= retry_after):
                        from .image_access import probe_image_key
                        self._image_probe_at = now
                        report = {**self._binding, "authenticated_account_id": self.expected_account}
                        candidate, safe = probe_image_key(report, expected_account_id=self.expected_account)
                        self._observe()
                        if candidate is not None:
                            # This remains explicitly unverified. An unsupported
                            # first format must not prevent validation on the next
                            # separately requested exact indexed occurrence. No
                            # additional source files or conversations are searched.
                            self._image_candidate = candidate
                            self._image_candidate_identity = self._identity
                            self._image_candidate_at = time.monotonic()
                            self._image_candidate_attempts = 0
                        else:
                            result = {"state": "RETRY_PENDING", "reason": safe.get("reason", "CHAT_IMAGE_KEY_UNAVAILABLE"), "quality": "unknown"}
                            _json(self.private / "audit" / ("image-key-" + uuid.uuid4().hex + ".json"), safe)
                    if candidate is not None:
                        self._image_candidate_attempts += 1
                        result = retrieve_chat(private["reference"], output, account_dir=self._binding["account_directory"],
                            account_id=self.expected_account, friend_id=self._friend, image_keys=candidate)
                        self._observe()
                        if result.get("state") == "VALIDATED":
                            # A candidate becomes a session cache entry only after
                            # exact indexed bytes pass full decryption and decode.
                            self._image_keys = candidate
                            self._clear_image_candidate()
                        elif result.get("reason") in {"CHAT_IMAGE_DECRYPTION_FAILED", "CHAT_ATTACHMENT_VALIDATION_FAILED", "CHAT_IMAGE_KEY_REQUIRED"}:
                            self._clear_image_candidate()
                        validation_reason = result.get("reason")
                        if validation_reason is not None and (not isinstance(validation_reason, str)
                                or not re.fullmatch(r"[A-Z][A-Z_]{3,80}", validation_reason)):
                            validation_reason = "IMAGE_CANDIDATE_VALIDATION_FAILED"
                        validation_state = result.get("state")
                        if validation_state not in {"VALIDATED", "UNAVAILABLE", "RETRY_PENDING"}:
                            validation_state = "UNAVAILABLE"
                        _json(self.private / "audit" / ("image-key-" + uuid.uuid4().hex + ".json"), {
                            **safe, "validation_state": validation_state,
                            "validation_reason": validation_reason,
                            "media_validated": result.get("state") == "VALIDATED",
                            "candidate_retained_for_requested_occurrence": self._image_candidate is not None,
                            "keys_persisted": False})
                state = result.get("state")
                result["state"] = "SAVED" if state in {"SAVED", "STORED_VERIFIED", "VALIDATED"} else ("RETRY" if state == "RETRY_PENDING" else "UNAVAILABLE")
                return result
            from .media import retrieve_image
            media = private["media"]
            if attachment.get("media_index", attachment.get("index")) != media["media_index"] or str(attachment.get("native_id", "")) != str(media["native_media_id"]):
                raise NativeError("ATTACHMENT_OCCURRENCE_MISMATCH")
            if media["type_raw"] not in {"2", ""}:
                return {"state": "UNAVAILABLE", "reason": "MOMENTS_MEDIA_TYPE_UNSUPPORTED"}
            result = retrieve_image(media, post_id=private["post_id"], author_id=self._friend,
                                    expected_media_index=media["media_index"], output_dir=output)
            if result["status"] != "STORED_VERIFIED":
                return {"state": "RETRY", "reason": result.get("failure_code", "MEDIA_RETRIEVAL_FAILED").upper()}
            fmt = result["format"].lower()
            return {"state": "SAVED", "path": result["blob_path"], "sha256": result["sha256"],
                    "mime": "image/" + ("jpeg" if fmt == "jpg" else fmt), "bytes": result["bytes"],
                    "quality": result["quality"], "width": result["width"], "height": result["height"],
                    "decode_method": result["decode_method"]}
