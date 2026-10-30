"""Transactional records, immutable assets, and portable verified backups."""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import threading
import uuid
import zipfile
from contextlib import nullcontext
from datetime import datetime, timezone


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def uid():
    return uuid.uuid4().hex


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


class Store:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        for directory in ("blobs", "exports", "backups", "restores"):
            (self.root / directory).mkdir(exist_ok=True)
        self.lock = threading.RLock()
        self.db_path = self.root / "workbench.sqlite3"
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS records(
                    kind TEXT NOT NULL,id TEXT NOT NULL,data TEXT NOT NULL,
                    created_at TEXT NOT NULL,updated_at TEXT NOT NULL,
                    PRIMARY KEY(kind,id));
                CREATE TABLE IF NOT EXISTS revisions(
                    kind TEXT NOT NULL,id TEXT NOT NULL,version INTEGER NOT NULL,
                    data TEXT NOT NULL,created_at TEXT NOT NULL,
                    PRIMARY KEY(kind,id,version));
                CREATE TABLE IF NOT EXISTS source_events(
                    account_id TEXT NOT NULL,source_id TEXT NOT NULL,event_key TEXT NOT NULL,
                    revision_hash TEXT NOT NULL,item_id TEXT NOT NULL,
                    PRIMARY KEY(account_id,source_id,event_key,revision_hash));
                CREATE TABLE IF NOT EXISTS blobs(
                    hash TEXT PRIMARY KEY,size INTEGER NOT NULL,path TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS processing_receipts(
                    account_id TEXT NOT NULL,source_id TEXT NOT NULL,event_key TEXT NOT NULL,
                    data TEXT NOT NULL,PRIMARY KEY(account_id,source_id,event_key));
                CREATE TABLE IF NOT EXISTS pending_candidates(
                    id TEXT PRIMARY KEY,source_id TEXT NOT NULL,data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS source_index(
                    source_id TEXT NOT NULL,event_key TEXT NOT NULL,revision TEXT NOT NULL,
                    PRIMARY KEY(source_id,event_key));
                CREATE INDEX IF NOT EXISTS records_by_kind ON records(kind,updated_at);
            """)
            db.execute("INSERT OR IGNORE INTO migrations VALUES(1,?)", (utcnow(),))

    def connect(self):
        db = sqlite3.connect(self.db_path, timeout=20, factory=ClosingConnection)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA secure_delete=ON")
        return db

    def all(self, kind):
        with self.connect() as db:
            return [json.loads(r[0]) for r in db.execute(
                "SELECT data FROM records WHERE kind=? ORDER BY updated_at DESC", (kind,))]

    def get(self, kind, ident):
        with self.connect() as db:
            row = db.execute("SELECT data FROM records WHERE kind=? AND id=?", (kind, ident)).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, kind, data, ident=None, *, db=None):
        with self.lock:
            own = db is None
            db = db or self.connect()
            try:
                ident = ident or data.get("id") or uid()
                old = db.execute("SELECT data FROM records WHERE kind=? AND id=?", (kind, ident)).fetchone()
                old = json.loads(old[0]) if old else {}
                result = {**data, "id": ident, "created_at": old.get("created_at", utcnow()), "updated_at": utcnow(), "version": old.get("version", 0) + 1}
                db.execute("INSERT INTO records VALUES(?,?,?,?,?) ON CONFLICT(kind,id) DO UPDATE SET data=excluded.data,updated_at=excluded.updated_at",
                           (kind, ident, encode(result), result["created_at"], result["updated_at"]))
                db.execute("INSERT INTO revisions VALUES(?,?,?,?,?)", (kind, ident, result["version"], encode(result), utcnow()))
                if own:
                    db.commit()
                return result
            finally:
                if own:
                    db.close()

    def versions(self, kind, ident):
        with self.connect() as db:
            return [json.loads(r[0]) for r in db.execute("SELECT data FROM revisions WHERE kind=? AND id=? ORDER BY version DESC", (kind, ident))]

    def save_blob(self, content: bytes):
        digest = hashlib.sha256(content).hexdigest()
        relative = f"blobs/{digest[:2]}/{digest}"
        path = self.root / relative
        with self.lock:
            path.parent.mkdir(exist_ok=True)
            if not path.exists():
                temporary = path.with_suffix(f".{uid()}.partial")
                with temporary.open("xb") as handle:
                    handle.write(content)
                    handle.flush()
                    os.fsync(handle.fileno())
                if hashlib.sha256(temporary.read_bytes()).hexdigest() != digest:
                    raise ValueError("文件校验失败，请重新导入")
                os.replace(temporary, path)
            elif hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise ValueError("原始文件校验失败，请从备份恢复")
            with self.connect() as db:
                db.execute("INSERT OR IGNORE INTO blobs VALUES(?,?,?)", (digest, len(content), relative))
        return {"sha256": digest, "size": len(content), "path": relative}

    def ingest_page(self, source, items, checkpoint, job):
        """Persist occurrences and cursor together; uncertain identities are retained."""
        saved = []
        with self.lock, self.connect() as db:
            for item in items:
                # Only driver-proven stable identities may suppress occurrences.
                identity_verified = item.get("identity_verified") or item.get("identity_confidence") == "verified_native"
                event_key = item.get("event_key") if identity_verified else None
                event_key = event_key or uid()
                stable_content = {k: item.get(k) for k in ("text", "author", "type", "source_time_raw", "nested_content", "quoted")}
                stable_content["attachments"] = [{k: a.get(k) for k in ("name", "type", "media_index", "source_url", "native_id")} for a in item.get("attachments", [])]
                revision_hash = hashlib.sha256(encode(stable_content).encode()).hexdigest()
                existing = db.execute("SELECT item_id FROM source_events WHERE account_id=? AND source_id=? AND event_key=? AND revision_hash=?",
                                      (source["account_id"], source["id"], event_key, revision_hash)).fetchone()
                if existing:
                    continue
                record = {**item, "source_id": source["id"], "account_id": source["account_id"], "observed_at": item.get("observed_at", utcnow()),
                          "event_key": event_key, "identity_uncertain": not bool(identity_verified), "state": "PENDING_EXTRACTION"}
                record["attachments"] = [{**a, "id": uid(), "state": "PENDING", "attempts": 0} for a in record.get("attachments", [])]
                record = self.put("materials", record, db=db)
                for attachment in record["attachments"]:
                    self.put("attachments", {**attachment, "material_id": record["id"], "source_id": source["id"], "account_id": source["account_id"], "retrieval_reference": attachment.copy()}, db=db)
                db.execute("INSERT INTO source_events VALUES(?,?,?,?,?)", (source["account_id"], source["id"], event_key, revision_hash, record["id"]))
                saved.append(record)
            previous = self.get("checkpoints", source["id"]) or {}
            self.put("checkpoints", {"account_id": source["account_id"], "source_id": source["id"], "cursor": checkpoint, "job_id": job["id"], "last_cutoff": previous.get("last_cutoff")}, source["id"], db=db)
            job["checkpoint"] = checkpoint
            job["counts"]["discovered"] += len(saved)
            current = db.execute("SELECT data FROM records WHERE kind='jobs' AND id=?", (job["id"],)).fetchone()
            if current and json.loads(current[0])["state"] in {"PAUSING", "PAUSED", "CANCELED"}:
                job["state"] = json.loads(current[0])["state"]
            self.put("jobs", job, db=db)
        return saved

    def staged_asset(self, path, staging_dir, *, name=None, mime=None, image_required=False):
        """Validate bytes from this worker's staging directory before linking them."""
        staging_dir = Path(staging_dir).resolve()
        incoming = Path(path).resolve()
        if not incoming.is_relative_to(staging_dir) or not incoming.is_file():
            raise ValueError("采集文件不在本任务暂存目录内")
        expected_size = incoming.stat().st_size
        if not 0 < expected_size <= 64 * 1024 * 1024:
            raise ValueError("采集文件为空或超过保存上限")
        with incoming.open("rb") as handle:
            content = handle.read(64 * 1024 * 1024 + 1)
        if len(content) != expected_size or incoming.stat().st_size != expected_size:
            raise ValueError("采集文件仍在变化，请等待保存完成后重试")
        actual_mime = mime or "application/octet-stream"
        if image_required or actual_mime.startswith("image/"):
            from PIL import Image
            with Image.open(io.BytesIO(content)) as image:
                actual_mime = Image.MIME.get(image.format, "application/octet-stream")
                image.verify()
            if not actual_mime.startswith("image/"):
                raise ValueError("采集图片格式校验失败")
        return {**self.save_blob(content), "name": name or incoming.name, "mime": actual_mime}

    def ingest_background_page(self, source, items, page, job, *, db=None):
        """Commit stable occurrences, source revisions, media work and one job cursor.

        History and incremental jobs have distinct IDs/cursors. Source revisions
        update the same material while the revisions table retains prior values.
        Classification corrections and already verified bytes survive rescans.
        """
        added = changed = 0
        new_evidence = []
        with self.lock, (self.connect() if db is None else nullcontext(db)) as db:
            for item in items:
                event = str(item.get("event_key") or "")
                if not event or not item.get("identity_verified"):
                    raise ValueError("后台记录缺少已验证的原生标识")
                allowed_authors = {source["native_id"]} if source['kind'] == 'moments' else {source["native_id"], source.get("account_native_id")}
                unknown_chat_sender = source['kind'] == 'chat' and item.get('author_id') is None and item.get('conversation_id') == source['native_id']
                if item.get("author_id") not in allowed_authors and not unknown_chat_sender:
                    raise ValueError("后台记录来源不符")
                canonical = {k: v for k, v in item.items() if k not in
                             {"attachments", "classification", "relevance", "observed_at", "first_discovered_at", "private_ref", "private_source_ref", "native_revision"}}
                canonical["attachments"] = [{k: a.get(k) for k in ("native_id", "media_index", "type")}
                                             for a in item.get("attachments", [])]
                if isinstance(canonical.get('provenance'), dict):
                    canonical['provenance'] = {k: v for k, v in canonical['provenance'].items() if k != 'snapshot_sha256'}
                revision = hashlib.sha256(encode(canonical).encode()).hexdigest()
                known = db.execute("SELECT item_id FROM source_events WHERE account_id=? AND source_id=? AND event_key=? ORDER BY rowid DESC LIMIT 1",
                                   (source["account_id"], source["id"], event)).fetchone()
                prior = None
                if known:
                    row = db.execute("SELECT data FROM records WHERE kind='materials' AND id=?", (known[0],)).fetchone()
                    prior = json.loads(row[0]) if row else None
                seen = db.execute("SELECT 1 FROM source_events WHERE account_id=? AND source_id=? AND event_key=? AND revision_hash=?",
                                  (source["account_id"], source["id"], event, revision)).fetchone()
                ident = prior["id"] if prior else uid()
                attachments = []
                context_assets = [a for a in (prior or {}).get('attachments', []) if a.get('context_event_key')]
                old_media = {(str(a.get("native_id")), a.get("media_index")): a for a in (prior or {}).get("attachments", []) if not a.get('context_event_key')}
                for incoming in item.get("attachments", []):
                    key = (str(incoming.get("native_id")), incoming.get("media_index"))
                    old = old_media.get(key, {})
                    validated = incoming.get('state') == 'SAVED' and incoming.get('sha256') and incoming.get('path')
                    merged = {**old, **incoming} if validated else {**incoming, **old}
                    attachment = {**merged, "id": old.get("id") or uid(),
                        "private_ref": incoming.get("private_ref", old.get("private_ref")),
                        "material_id": ident, "source_id": source["id"], "account_id": source["account_id"],
                        "native_post_id": str(item.get("native_post_id") or event),
                        "author_id": item["author_id"], "acquisition_mode": "background",
                        "state": 'SAVED' if validated else old.get("state", incoming.get("state", "PENDING")), "media_state": 'VALIDATED' if validated else old.get("media_state", incoming.get("media_state", "REFERENCE_DISCOVERED")),
                        "attempts": old.get("attempts", 0), "retired": False,
                        "classification": old.get("classification", incoming.get("classification", {}))}
                    attachments.append(old if old and attachment == old else self.put("attachments", attachment, db=db))
                attachments.extend(context_assets)
                active = {a["id"] for a in attachments}
                for old in old_media.values():
                    if old["id"] not in active:
                        self.put("attachments", {**old, "retired": True}, db=db)
                material = {**(prior or {}), **item,
                    "id": ident, "account_id": source["account_id"], "source_id": source["id"],
                    "acquisition_mode": "background", "event_key": event,
                    "first_discovered_at": (prior or {}).get("first_discovered_at", utcnow()),
                    "observed_at": (prior or {}).get("observed_at", utcnow()),
                    "attachments": attachments, "state": (prior or {}).get("state", "PENDING_EXTRACTION"),
                    "classification": (prior or {}).get("classification") if (prior or {}).get('classification', {}).get('origin') in {'manual', 'inspection'} else item.get("classification", {}),
                    "analysis_deferred": True, "identity_uncertain": False, "source_revision_hash": revision}
                if prior and prior.get('source_revision_hash') == revision:
                    material = {**prior, 'attachments': attachments}
                if material != prior:
                    self.put("materials", material, ident, db=db)
                if not seen:
                    db.execute("INSERT INTO source_events VALUES(?,?,?,?,?)",
                               (source["account_id"], source["id"], event, revision, ident))
                if not prior or prior.get('source_revision_hash') != revision:
                    added += int(prior is None)
                    changed += int(prior is not None)
                # Another background job may save a newly published event before
                # this continuous job reaches it. Reconciliation still observes
                # that event, while records already stored before activation do
                # not become new evidence merely because their timestamp is ahead.
                native_time = item.get('publication_time') or item.get('source_time')
                if job['mode'] == 'continuous' and native_time:
                    try:
                        baseline = datetime.fromisoformat(job['activation_baseline'])
                        if (datetime.fromisoformat(native_time) > baseline
                                and datetime.fromisoformat(material['first_discovered_at']) >= baseline):
                            new_evidence.append({'event_key': event, 'source_time': native_time,
                                'first_discovered_at': material['first_discovered_at'],
                                'observation': 'reconciled_by_continuous'})
                    except (ValueError, TypeError):
                        pass
            current = db.execute("SELECT data FROM records WHERE kind='background_jobs' AND id=?", (job["id"],)).fetchone()
            current = json.loads(current[0]) if current else job
            counts = {**current.get("counts", {})}
            counts["discovered"] = counts.get("discovered", 0) + added
            counts["revisions"] = counts.get("revisions", 0) + changed
            observed_ranges = [value for value in (current.get('observed_range'), page.get('observed_range')) if value]
            lower = [value.get('min_epoch', value.get('start_epoch')) for value in observed_ranges]
            upper = [value.get('max_epoch', value.get('end_epoch')) for value in observed_ranges]
            lower = [value for value in lower if isinstance(value, (int, float))]
            upper = [value for value in upper if isinstance(value, (int, float))]
            observed_range = ({'min_epoch': min(lower), 'max_epoch': max(upper)} if lower and upper else None)
            updated = {**current, "cursor": page.get("cursor"), "counts": counts,
                       "observed_range": observed_range, "coverage": "UNKNOWN",
                       "local_exhausted": bool(page.get("exhausted")), "snapshot_id": page.get("snapshot_id"),
                       "last_page_at": utcnow()}
            evidence = {value['event_key']: value for value in current.get('new_event_evidence', [])}
            for value in new_evidence:
                evidence.setdefault(value['event_key'], value)
            updated['new_event_evidence'] = sorted(evidence.values(),
                key=lambda value: (value['first_discovered_at'], value['event_key']))[-100:]
            gaps = {encode(g): g for g in current.get('parse_gaps', []) + page.get('parse_issues', [])}
            updated['parse_gaps'] = list(gaps.values())
            self.put("background_jobs", updated, db=db)
            self.put("checkpoints", {"source_id": source["id"], "account_id": source["account_id"],
                "job_id": job["id"], "mode": job["mode"], "cursor": page.get("cursor"),
                "requested_range": job.get("requested_range"), "coverage": "UNKNOWN", "last_cutoff": None},
                "background:" + job["id"], db=db)
        return {"added": added, "revised": changed}

    def update_background_attachment(self, attachment, changes):
        """Update independent media work and its material projection atomically."""
        with self.lock, self.connect() as db:
            row = db.execute("SELECT data FROM records WHERE kind='attachments' AND id=?", (attachment['id'],)).fetchone()
            current = json.loads(row[0])
            updated = self.put("attachments", {**current, **changes}, db=db)
            row = db.execute("SELECT data FROM records WHERE kind='materials' AND id=?", (updated['material_id'],)).fetchone()
            material = json.loads(row[0])
            self.put("materials", {**material, "attachments": [updated if a['id'] == updated['id'] else a
                                                              for a in material.get('attachments', [])]}, db=db)
        return updated

    def save_session_evidence(self, session, result, staging_dir):
        """Persist a session preview without creating a parsed source record."""
        evidence = dict(result.get("evidence") or {})
        preview_path = evidence.pop("preview_path", None)
        if not preview_path or not result.get("binding"):
            raise ValueError("当前页面缺少可复核的绑定证据")
        with self.lock:
            asset = self.staged_asset(preview_path, staging_dir, name="微信来源会话.png", image_required=True)
            with self.connect() as db:
                aid = uid()
                attachment = self.put("attachments", {**asset, "id": aid, "source_id": session["source_id"],
                    "account_id": session["account_id"], "session_id": session["id"], "role": "session_evidence",
                    "acquisition_mode": "operator_positioned", "state": "SAVED", "quality": "screenshot",
                    "url": f"/api/attachments/{aid}", "retrieved_at": utcnow()}, db=db)
                return self.put("native_sessions", {**session, "state": "READY", "binding": result["binding"],
                    "evidence": {**evidence, "attachment_id": attachment["id"]},
                    "capabilities": result.get("capabilities", {}), "preview_url": f"/api/attachments/{aid}?preview=true",
                    "identity_scope": "session", "established_at": utcnow(), "stop_code": None,
                    "reason": "已建立本次人工定位会话；采集时仍会核对来源与窗口。"}, db=db)

    def ingest_native_page(self, source, page, job, session, staging_dir):
        """Commit unparsed page evidence, real media and a bounded cursor together.

        Page captures are separate records, never manufactured messages. Each
        captured occurrence is retained; equal image bytes only deduplicate blobs.
        """
        observations = page.get("observations") or []
        items = page.get("items") or []
        media = page.get("attachments") or []
        prepared_observations, prepared_media = [], []
        with self.lock:
            # Prepare immutable assets before opening the business transaction.
            for observation in observations:
                capture = self.staged_asset(observation["capture_path"], staging_dir,
                                            name="微信页面观察.png", image_required=True)
                prepared_observations.append((observation, capture))
            for attachment in media:
                attachment = dict(attachment)
                if attachment.get("staging_path"):
                    asset = self.staged_asset(attachment["staging_path"], staging_dir,
                        name=attachment.get("name"), mime=attachment.get("mime"),
                        image_required=attachment.get("type") == "image")
                    attachment = {**attachment, **asset, "state": "SAVED", "retrieved_at": utcnow()}
                elif attachment.get("state") == "SAVED":
                    raise ValueError("附件未提供已保存的暂存文件")
                else:
                    attachment["state"] = attachment.get("state", "PENDING")
                prepared_media.append(attachment)
            with self.connect() as db:
                common = {"source_id": source["id"], "source_name": source["display_name"],
                          "account_id": source["account_id"], "session_id": session["id"], "job_id": job["id"],
                          "acquisition_mode": "operator_positioned", "acquisition_method": "operator_positioned_native",
                          "source_positioning": "operator_assisted", "identity_scope": "session"}
                saved_items, saved_observations = [], []
                for item in items:
                    if item.get("type") == "page_observation" or item.get("parse_state") == "UNPARSED":
                        raise ValueError("未解析页面不能计为来源记录")
                    saved_items.append(self.put("materials", {**item, **common, "attachments": [],
                        "observed_at": item.get("observed_at", utcnow()), "state": "PENDING_EXTRACTION",
                        "analysis_deferred": True, "identity_uncertain": not bool(item.get("identity_verified"))}, db=db))
                for observation, asset in prepared_observations:
                    oid, aid = uid(), uid()
                    capture = self.put("attachments", {**asset, **common, "id": aid, "observation_id": oid,
                        "role": "page_capture", "quality": "screenshot", "state": "SAVED", "attempts": 0,
                        "association_state": "PAGE_OBSERVATION", "url": f"/api/attachments/{aid}"}, db=db)
                    data = {key: value for key, value in observation.items() if key not in {"capture_path", "attachments", "id"}}
                    record = self.put("page_observations", {**data, **common, "id": oid,
                        "type": "page_observation", "parse_state": observation.get("parse_state", "UNPARSED"),
                        "observed_at": observation.get("observed_at", utcnow()), "attachments": [capture],
                        "unresolved_associations": max(0, int(observation.get("unresolved_associations", 0)))}, db=db)
                    saved_observations.append(record)
                saved_media = []
                for attachment in prepared_media:
                    observation_index, record_index = attachment.get("observation_index"), attachment.get("record_index")
                    if observation_index is not None and (type(observation_index) is not int or not 0 <= observation_index < len(saved_observations)):
                        raise ValueError("附件页面关联无效")
                    if record_index is not None and (type(record_index) is not int or not 0 <= record_index < len(saved_items)):
                        raise ValueError("附件来源记录关联无效")
                    if record_index is not None and attachment.get("association_state", "VERIFIED") != "VERIFIED":
                        raise ValueError("未确认的附件关联不能写入已解析来源记录")
                    aid = uid()
                    data = {key: value for key, value in attachment.items() if key not in {"staging_path", "observation_index", "record_index", "id"}}
                    record = self.put("attachments", {**data, **common, "id": aid, "role": "supplier_media",
                        "quality": attachment.get("quality", "unknown"), "attempts": attachment.get("attempts", 0),
                        "material_id": saved_items[record_index]["id"] if record_index is not None else None,
                        "observation_id": saved_observations[observation_index]["id"] if observation_index is not None else None,
                        "association_state": attachment.get("association_state", "VERIFIED" if record_index is not None else "UNRESOLVED"),
                        "url": f"/api/attachments/{aid}" if attachment["state"] == "SAVED" else None}, db=db)
                    if record_index is not None:
                        saved_items[record_index]["attachments"].append(record)
                    if observation_index is not None:
                        saved_observations[observation_index]["attachments"].append(record)
                    saved_media.append(record)
                for record in saved_items:
                    self.put("materials", record, db=db)
                for observation in saved_observations:
                    unresolved = sum(a.get("role") == "supplier_media" and a.get("association_state") != "VERIFIED" for a in observation["attachments"])
                    observation["unresolved_associations"] = max(observation["unresolved_associations"], unresolved)
                    self.put("page_observations", observation, db=db)
                current = db.execute("SELECT data FROM records WHERE kind='jobs' AND id=?", (job["id"],)).fetchone()
                current = json.loads(current[0]) if current else job
                counts = dict(current.get("counts", {}))
                counts["page_observations"] = counts.get("page_observations", 0) + len(saved_observations)
                counts["parsed_records"] = counts.get("parsed_records", 0) + len(saved_items)
                counts["discovered"] = counts["parsed_records"]
                counts["acquired_attachments"] = counts.get("acquired_attachments", 0) + sum(a["state"] == "SAVED" for a in saved_media)
                counts["unresolved_associations"] = counts.get("unresolved_associations", 0) + sum(o["unresolved_associations"] for o in saved_observations) + sum(
                    not a.get("observation_id") and a.get("association_state") != "VERIFIED" for a in saved_media)
                checkpoint = page.get("checkpoint", current.get("checkpoint"))
                checkpoint_id = f"operator_positioned:{session['id']}"
                self.put("checkpoints", {"account_id": source["account_id"], "source_id": source["id"],
                    "session_id": session["id"], "acquisition_mode": "operator_positioned", "cursor": checkpoint,
                    "job_id": job["id"], "last_cutoff": None, "coverage": page.get("coverage", "UNKNOWN")}, checkpoint_id, db=db)
                self.put("jobs", {**current, "checkpoint": checkpoint, "checkpoint_id": checkpoint_id,
                                  "counts": counts, "counts_scope": "this_job"}, db=db)
        return {"materials": saved_items, "observations": saved_observations, "attachments": saved_media}

    def update_native_attachment(self, attachment, result, staging_dir):
        """Commit late bytes independently from page discovery/checkpoints."""
        with self.lock:
            if result.get("state") == "SAVED":
                asset = self.staged_asset(result["path"], staging_dir, name=attachment.get("name"),
                    mime=result.get("mime", attachment.get("mime")), image_required=attachment.get("type") == "image")
                if result.get("sha256") and result["sha256"] != asset["sha256"]:
                    raise ValueError("采集附件哈希校验失败")
                updated = {**attachment, **asset, "state": "SAVED", "quality": result.get("quality", attachment.get("quality", "unknown")),
                           "retrieved_at": utcnow(), "url": f"/api/attachments/{attachment['id']}", "last_error": None}
            else:
                updated = {**attachment, "state": "UNAVAILABLE" if result.get("state") == "UNAVAILABLE" else "RETRY",
                           "last_error": result.get("reason") or "附件暂未取得，已保留独立重试记录。"}
            updated["attempts"] = attachment.get("attempts", 0) + 1
            with self.connect() as db:
                updated = self.put("attachments", updated, db=db)
                for kind, key in (("materials", "material_id"), ("page_observations", "observation_id")):
                    if not updated.get(key):
                        continue
                    row = db.execute("SELECT data FROM records WHERE kind=? AND id=?", (kind, updated[key])).fetchone()
                    if not row:
                        raise ValueError("附件来源关联缺失")
                    parent = json.loads(row[0])
                    self.put(kind, {**parent, "attachments": [updated if item["id"] == updated["id"] else item for item in parent.get("attachments", [])]}, db=db)
            return updated

    def recover(self):
        # A prior process's native binding is evidence, not a reusable UI lease.
        for session in self.all("native_sessions"):
            if session.get("state") in {"READY", "QUEUED", "ESTABLISHING", "STAGED"}:
                self.put("native_sessions", {**session, "state": "EXPIRED", "stop_code": "SESSION_PROCESS_RESTART",
                                             "reason": "应用已重新启动，请重新确认当前打开的微信来源；原采集记录和检查点仍保留。"})
        for job in self.all("jobs"):
            if job["state"] in {"RUNNING", "QUEUED", "PAUSING"}:
                self.put("jobs", {**job, "state": "PAUSED", "stop_reason": "上次采集中断，已保留素材与检查点；可继续采集。"})
        for material in self.all("materials"):
            if material.get("state") == "ANALYZING":
                self.put("materials", {**material, "state": "PENDING_EXTRACTION", "issues": ["上次分析中断，可重新分析；原始素材已保存。"]})

    def backup(self):
        """Freeze writes, use SQLite backup, and hash every required immutable asset."""
        name = f"backup-{datetime.now(timezone.utc):%Y%m%dT%H%M%S}-{uid()[:6]}"
        folder = self.root / "backups"
        snapshot = folder / f"{name}.sqlite3"
        archive = folder / f"{name}.zip"
        with self.lock:
            self.validate_references()
            with self.connect() as source, sqlite3.connect(snapshot, factory=ClosingConnection) as target:
                source.backup(target)
            files = [("workbench.sqlite3", snapshot)]
            files.extend((p.relative_to(self.root).as_posix(), p) for p in (self.root / "blobs").rglob("*") if p.is_file() and ".partial" not in p.name)
            # Expiring candidates are separate from business search, but a backup
            # must carry the still-retained bytes needed to resume their inspection.
            with self.connect() as db:
                candidates = [json.loads(r[0]) for r in db.execute('SELECT data FROM pending_candidates')]
            candidate_paths = {a.get('path') for c in candidates for a in c.get('item', {}).get('attachments', []) if a.get('path')}
            for relative in sorted(candidate_paths):
                path = (self.root / relative).resolve()
                if path.is_relative_to(self.root / 'relevance-staging') and path.is_file():
                    files.append((path.relative_to(self.root).as_posix(), path))
            # Export rendering may be concurrent; only committed assets belong to a snapshot.
            for record in self.all("exports"):
                files.extend((record[key], self.root / record[key]) for key in ("image_path", "text_path") if record.get(key))
            # Several export occurrences may share one immutable content-addressed file.
            # Preserve every database record, but write each relative archive path once.
            files = sorted(dict(files).items())
            manifest = {"schema_version": 1, "created_at": utcnow(), "secrets_included": False,
                        "files": {n: {"sha256": hashlib.sha256(p.read_bytes()).hexdigest(), "size": p.stat().st_size} for n, p in files}}
            with zipfile.ZipFile(archive, "x", zipfile.ZIP_DEFLATED) as output:
                for name, path in files:
                    output.write(path, name)
                output.writestr("manifest.json", encode(manifest))
            snapshot.unlink()
        return archive

    def validate_references(self):
        """Check application links as well as database/ZIP structural integrity."""
        attachments = {a["id"]: a for a in self.all("attachments")}
        exports = {e["id"]: e for e in self.all("exports")}
        for material in self.all("materials"):
            for reference in material.get("attachments", []):
                if reference["id"] not in attachments:
                    raise ValueError("素材附件关联缺失，备份校验未通过")
        for observation in self.all("page_observations"):
            if any(a["id"] not in attachments for a in observation.get("attachments", [])):
                raise ValueError("页面观察附件关联缺失，备份校验未通过")
        for session in self.all("native_sessions"):
            evidence_id = session.get("evidence", {}).get("attachment_id")
            if evidence_id and evidence_id not in attachments:
                raise ValueError("采集会话证据附件缺失，备份校验未通过")
        for attachment in attachments.values():
            if attachment.get("state") != "SAVED":
                continue
            path = (self.root / attachment["path"]).resolve()
            if not path.is_relative_to(self.root / "blobs") or not path.is_file():
                raise ValueError("已保存附件的原始文件缺失，备份校验未通过")
            if hashlib.sha256(path.read_bytes()).hexdigest() != attachment["sha256"]:
                raise ValueError("已保存附件校验失败")
        for record in exports.values():
            for key in ("image", "text"):
                if not record.get(f"{key}_path"):
                    continue
                path = (self.root / record[f"{key}_path"]).resolve()
                if not path.is_relative_to(self.root / "exports") or not path.is_file():
                    raise ValueError("导出文件缺失，备份校验未通过")
                expected = record.get(f"{key}_sha256")
                if expected and hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                    raise ValueError("导出文件校验失败")
        for recommendation in self.all("recommendations"):
            if any(ident not in exports for ident in recommendation.get("exports", [])):
                raise ValueError("推荐版本的导出关联缺失")
        return True

    def restore_test(self, archive: Path):
        """Restore to a fresh sibling directory, never overwrite the live dataset."""
        archive = archive.resolve()
        if archive.parent != (self.root / "backups").resolve() or archive.suffix != ".zip":
            raise ValueError("请选择本应用备份目录中的 ZIP 备份")
        destination = self.root / "restores" / uid()
        with zipfile.ZipFile(archive) as incoming:
            manifest = json.loads(incoming.read("manifest.json"))
            if manifest.get("schema_version") != 1 or "workbench.sqlite3" not in manifest.get("files", {}):
                raise ValueError("备份版本或清单无效")
            if len(manifest["files"]) > 100000:
                raise ValueError("备份文件数量超过校验上限")
            validated = []
            for name, meta in manifest["files"].items():
                target = (destination / name).resolve()
                if not target.is_relative_to(destination.resolve()) or "\\" in name or ":" in name:
                    raise ValueError("备份包含无效路径")
                if name != "workbench.sqlite3" and not name.startswith(("blobs/", "exports/")):
                    raise ValueError("备份包含未支持的文件")
                info = incoming.getinfo(name)
                if info.file_size != meta["size"] or info.file_size > 512 * 1024 * 1024:
                    raise ValueError("备份文件大小校验失败")
                content = incoming.read(name)
                if hashlib.sha256(content).hexdigest() != meta["sha256"]:
                    raise ValueError("备份文件哈希校验失败")
                validated.append((target, content))
            for target, content in validated:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
        restored = Store(destination)
        with restored.connect() as db:
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("数据库完整性校验失败")
        restored.validate_references()
        return {"path": str(destination), "files": len(validated), "counts": {k: len(restored.all(k)) for k in ("materials", "products", "sources", "jobs", "cases", "recommendations", "weekly")}, "message": "已恢复到独立校验目录，当前数据未替换。"}
