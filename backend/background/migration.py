"""Read-only migration planning and narrowly scoped, reference-checked blob GC.

Planning reads a verified backup, never the native client. It writes only a
body-free baseline and decision manifest. Temporary extracted copies are removed
on exit. The caller owns atomic application cleanup and pauses its workers.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sqlite3
import tempfile
import threading
import zipfile

from .relevance import decide, KEEP_PRODUCT_RELEVANT, RULE_VERSION
from .inspection import inspect_record, _rapid_ocr


from .service import EXPECTED_ACCOUNT, EXPECTED_FRIEND
_OPERATIONAL = {"accounts", "sources", "jobs", "background_jobs", "background_status", "checkpoints", "settings"}
_EDIT_FIELDS = ("text", "title", "supplier", "source_note", "notes", "user_notes", "tags", "description")


def _objects(value):
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from _objects(item)
    elif isinstance(value, list):
        for item in value:
            yield from _objects(item)


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def _tables(db):
    return {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _rows(store):
    with store.connect() as db:
        records = [(row[0], row[1], json.loads(row[2])) for row in db.execute("SELECT kind,id,data FROM records")]
        revisions = [(row[0], row[1], json.loads(row[2])) for row in db.execute("SELECT kind,id,data FROM revisions")]
        if "pending_candidates" in _tables(db):
            records.extend(("pending_candidates", row[0], json.loads(row[1]))
                           for row in db.execute("SELECT id,data FROM pending_candidates"))
    return records, revisions


def _manual(value):
    return any((isinstance(obj.get("classification"), dict) and obj["classification"].get("origin") == "manual")
               or obj.get("user_edited") is True or obj.get("edited_by") in {"user", "manual"}
               or obj.get("origin") == "manual" for obj in _objects(value))


def _authorized(material, sources, *, expected_account=EXPECTED_ACCOUNT, expected_friend=EXPECTED_FRIEND):
    source = sources.get(material.get("source_id"), {})
    if material.get("acquisition_mode") != "background" or source.get("acquisition_mode") != "background":
        return False
    if (source.get("native_id") != expected_friend or source.get("account_native_id") != expected_account
            or material.get("account_id") != source.get("account_id")):
        return False
    kind = material.get("source_kind")
    if kind not in {"moments", "chat"} or source.get("kind") != kind:
        return False
    if kind == "moments" and material.get("author_id") != expected_friend:
        return False
    if kind == "chat" and material.get("conversation_id") != expected_friend:
        return False
    return bool(material.get("event_key") and material.get("source_revision_hash")
                and material.get("identity_verified") is True)


def protected_materials(store, *, expected_account=EXPECTED_ACCOUNT, expected_friend=EXPECTED_FRIEND):
    """Return {material_id: fixed protection reasons}, without changing the Store.

    Shared files protect bytes rather than forcing an irrelevant material to stay.
    GC checks every retained current record, revision and pending candidate.
    Known inspection labels are classification evidence, not user-edit flags.
    """
    records, revisions = _rows(store)
    materials = {ident: value for kind, ident, value in records if kind == "materials"}
    sources = {ident: value for kind, ident, value in records if kind == "sources"}
    attached = {ident: value.get("material_id") for kind, ident, value in records if kind == "attachments"}
    protected = defaultdict(set)
    for ident, value in materials.items():
        if value.get("acquisition_mode") != "background":
            protected[ident].add("NONBACKGROUND_MATERIAL")
        elif not _authorized(value, sources, expected_account=expected_account, expected_friend=expected_friend):
            protected[ident].add("AMBIGUOUS_OR_OUT_OF_SCOPE_PROVENANCE")
        if _manual(value):
            protected[ident].add("EXPLICIT_USER_DECISION_OR_EDIT")
        if value.get("extractions") or value.get("extracted_text") or value.get("segments"):
            protected[ident].add("EXISTING_ANALYSIS_OR_BUSINESS_DERIVATIVE")
    versions = defaultdict(list)
    for kind, ident, value in records + revisions:
        if kind == "materials" and ident in materials:
            versions[ident].append(value)
            if _manual(value):
                protected[ident].add("EXPLICIT_USER_DECISION_OR_EDIT")
        if kind == "attachments" and _manual(value) and value.get("material_id") in materials:
            protected[value["material_id"]].add("EXPLICIT_ATTACHMENT_USER_DECISION")
        if kind not in _OPERATIONAL | {"materials", "attachments"}:
            for token in _strings(value):
                if token in materials:
                    protected[token].add("RETAINED_BUSINESS_REFERENCE")
                if attached.get(token) in materials:
                    protected[attached[token]].add("RETAINED_BUSINESS_ATTACHMENT_REFERENCE")
    for ident, history in versions.items():
        by_native_revision = defaultdict(set)
        for value in history:
            revision = value.get("source_revision_hash")
            if revision:
                content = {field: value.get(field) for field in _EDIT_FIELDS}
                by_native_revision[revision].add(json.dumps(content, sort_keys=True, ensure_ascii=False))
        if any(len(values) > 1 for values in by_native_revision.values()):
            protected[ident].add("CONTENT_EDIT_WITHOUT_NATIVE_REVISION_CHANGE")
    return {ident: sorted(reasons) for ident, reasons in protected.items()}


class _BackupStore:
    def __init__(self, root):
        self.root = Path(root)
        self.db_path = self.root / "workbench.sqlite3"
        self.lock = threading.RLock()

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.db_path.as_uri() + "?mode=ro&immutable=1", uri=True)
        try:
            yield db
        finally:
            db.close()


def _safe_member(name):
    path = PurePosixPath(name)
    return (not path.is_absolute() and ".." not in path.parts and ":" not in name
            and "\\" not in name and str(path) == name)


def _extract(archive, manifest, name, folder):
    if not _safe_member(name) or name not in manifest.get("files", {}):
        raise ValueError("BACKUP_MEMBER_NOT_VERIFIED")
    expected = manifest["files"][name]
    if not 0 < int(expected.get("size", 0)) <= 256 * 1024 * 1024:
        raise ValueError("BACKUP_MEMBER_SIZE_INVALID")
    info = archive.getinfo(name)
    if info.file_size != expected["size"]:
        raise ValueError("BACKUP_MEMBER_SIZE_MISMATCH")
    content = archive.read(name)
    if hashlib.sha256(content).hexdigest() != expected.get("sha256"):
        raise ValueError("BACKUP_MEMBER_HASH_MISMATCH")
    destination = (folder / name).resolve()
    if not destination.is_relative_to(folder.resolve()):
        raise ValueError("BACKUP_MEMBER_PATH_REJECTED")
    if not destination.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
    return destination


def _write_new(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)


def _baseline(store, archive_path, manifest):
    with store.connect() as db:
        rows = list(db.execute("SELECT kind,id,data FROM records"))
    return {"backup_path": str(archive_path), "record_hashes": {
        kind + "/" + ident: hashlib.sha256(data.encode("utf-8")).hexdigest() for kind, ident, data in rows},
        "file_manifest": manifest["files"], "jobs_before_pause": [json.loads(data) for kind, _, data in rows if kind == "background_jobs"],
        "counts": dict(Counter(kind for kind, _, _ in rows)), "contains_source_bodies": False}


def evaluate_backup(archive_path, evidence_dir, *, ocr=None, progress=None, manifest_name="decision-manifest.json"):
    """Evaluate all authorized imported records; retain only minimal decisions.

    Extracted SQLite and selected saved media are temporary and always removed.
    The original backup is read-only. OCR cache exists only during this call.
    progress receives aggregate counts, never record text or media references.
    """
    archive_path = Path(archive_path).resolve(strict=True)
    evidence_dir = Path(evidence_dir).resolve(strict=True)
    with zipfile.ZipFile(archive_path) as archive, tempfile.TemporaryDirectory(prefix="migration-inspection-", dir=evidence_dir) as temp:
        if len(set(archive.namelist())) != len(archive.namelist()):
            raise ValueError("BACKUP_DUPLICATE_MEMBER")
        if archive.getinfo("manifest.json").file_size > 4 * 1024 * 1024:
            raise ValueError("BACKUP_MANIFEST_TOO_LARGE")
        manifest = json.loads(archive.read("manifest.json"))
        folder = Path(temp)
        _extract(archive, manifest, "workbench.sqlite3", folder)
        store = _BackupStore(folder)
        with store.connect() as db:
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("BACKUP_DATABASE_INTEGRITY_FAILED")
        baseline = _baseline(store, archive_path, manifest)
        baseline_path = evidence_dir / "baseline.json"
        if not baseline_path.exists():
            _write_new(baseline_path, baseline)
        elif json.loads(baseline_path.read_text(encoding="utf-8"))["record_hashes"] != baseline["record_hashes"]:
            raise ValueError("BASELINE_ALREADY_DIFFERS")
        records, _ = _rows(store)
        sources = {ident: value for kind, ident, value in records if kind == "sources"}
        materials = {ident: value for kind, ident, value in records if kind == "materials"}
        protected = protected_materials(store)
        decisions, inspection_cache = {}, {}
        ocr_calls, cache_hits = 0, 0
        def recognize(path, **kwargs):
            nonlocal ocr_calls, cache_hits
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest in inspection_cache:
                cache_hits += 1
                return inspection_cache[digest]
            ocr_calls += 1
            value = (ocr or _rapid_ocr)(path, **kwargs)
            inspection_cache[digest] = value
            return value
        for ident, material in materials.items():
            if not _authorized(material, sources):
                continue
            decision = decide(material)
            if decision["needs_inspection"]:
                before_calls = ocr_calls
                for asset in material.get("attachments", []):
                    name = asset.get("path")
                    if isinstance(name, str) and name in manifest["files"] and name.startswith("blobs/"):
                        _extract(archive, manifest, name, folder)
                inspection = inspect_record(material, allowed_root=folder, ocr=recognize)
                inspection["metrics"]["ocr_operations"] = ocr_calls - before_calls
                decision = decide(material, inspection=inspection)
            decisions[ident] = {"material_id": ident, "account_id": material.get("account_id"),
                "source_id": material.get("source_id"), "event_key": material.get("event_key"),
                "native_id": str(material.get("native_id", "")), "source_revision_hash": material.get("source_revision_hash"),
                **decision, "protection_reasons": protected.get(ident, [])}
            classification = material.get("classification") or {}
            if classification.get("origin") in {"manual", "inspection"}:
                decisions[ident]["explicit_classification"] = {key: classification[key] for key in ("label", "origin", "updated_at") if key in classification}
            if progress and len(decisions) % 10 == 0:
                progress({"evaluated": len(decisions), "ocr_operations": ocr_calls,
                          "outcomes": dict(Counter(d["outcome"] for d in decisions.values()))})
        # A referenced parent may be later in publication/storage order. Only
        # explicit native IDs in the same selected source may trigger this pass.
        server_index = defaultdict(list)
        for ident, material in materials.items():
            if ident in decisions and material.get("server_id") not in (None, "", "0"):
                server_index[(material.get("account_id"), material.get("source_id"), str(material["server_id"]))].append(ident)
        for _ in range(3):
            updated = False
            for ident, entry in decisions.items():
                material = materials[ident]
                reply = material.get("reply") or {}
                if entry["outcome"] == KEEP_PRODUCT_RELEVANT or not reply.get("relationship_verified"):
                    continue
                parents = server_index.get((material.get("account_id"), material.get("source_id"), str(reply.get("native_server_id", ""))), [])
                if len(parents) != 1 or decisions[parents[0]]["outcome"] != KEEP_PRODUCT_RELEVANT:
                    continue
                parent = materials[parents[0]]
                context = {"relationship": "explicit_reply", "relationship_verified": True,
                    "parent_event_key": parent["event_key"], "parent_native_id": str(parent["server_id"]),
                    "parent_outcome": KEEP_PRODUCT_RELEVANT, "account_native_id": EXPECTED_ACCOUNT,
                    **{key: material.get(key) for key in ("account_id", "source_id", "conversation_id")}}
                candidate = decide(material, reply_context=context)
                if candidate["outcome"] == KEEP_PRODUCT_RELEVANT:
                    candidate["metrics"] = entry["metrics"]
                    decisions[ident] = {**entry, **candidate}
                    updated = True
            if not updated:
                break
        report = {"backup_path": str(archive_path), "rule_version": RULE_VERSION,
            "authorized_evaluated": len(decisions), "outcome_counts": dict(Counter(d["outcome"] for d in decisions.values())),
            "protected_materials": protected, "protected_authorized_count": sum(bool(d["protection_reasons"]) for d in decisions.values()),
            "metrics": {"classification_operations": len(decisions), "ocr_operations": ocr_calls,
                        "ocr_cache_hits": cache_hits, "media_inspected": sum(d["metrics"]["media_inspected"] for d in decisions.values())},
            "decisions": list(decisions.values()), "contains_source_bodies": False,
            "business_writes": 0, "native_access": 0}
        _write_new(evidence_dir / manifest_name, report)
        return {key: value for key, value in report.items() if key not in {"decisions", "protected_materials"}}


def gc_unreferenced_blobs(store, candidates, *, dry_run=True):
    """GC only explicit removed-import candidates after atomic cleanup commits.

    candidates is a sequence of {path:'blobs/ab/<sha256>',sha256:<sha256>}.
    All retained current data, revisions and pending payloads are examined under
    the Store lock. Any hash/path reference preserves shared bytes. Exports and
    rollback backups are never candidates. This function does not remove rows.
    """
    root = Path(store.root).resolve(strict=True)
    result = {"removed": [], "eligible": [], "retained": [], "rejected": [], "dry_run": bool(dry_run)}
    with store.lock:
        with store.connect() as db:
            values = [json.loads(row[0]) for row in db.execute("SELECT data FROM records UNION ALL SELECT data FROM revisions")]
            if "pending_candidates" in _tables(db):
                values.extend(json.loads(row[0]) for row in db.execute("SELECT data FROM pending_candidates"))
        tokens = {token.replace("\\", "/") for value in values for token in _strings(value)}
        hashes = {token.lower() for token in tokens if re.fullmatch(r"[0-9A-Fa-f]{64}", token)}
        for candidate in candidates:
            digest = str(candidate.get("sha256", "")).lower()
            relative = candidate.get("path", "")
            expected = "blobs/" + digest[:2] + "/" + digest
            if not re.fullmatch(r"[a-f0-9]{64}", digest) or relative != expected:
                result["rejected"].append({"sha256": digest if re.fullmatch(r"[a-f0-9]{64}", digest) else None, "reason": "NOT_OWNED_CONTENT_ADDRESSED_BLOB"})
                continue
            path = (root / relative).resolve()
            if not path.is_relative_to((root / "blobs").resolve()) or not path.is_relative_to(root):
                result["rejected"].append({"sha256": digest, "reason": "BLOB_PATH_ESCAPE"})
                continue
            if digest in hashes or relative in tokens or path.as_posix() in tokens:
                result["retained"].append({"sha256": digest, "reason": "RETAINED_RECORD_REVISION_OR_PENDING_REFERENCE"})
                continue
            if not path.is_file():
                continue
            if path.stat().st_size > 64 * 1024 * 1024 or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                result["rejected"].append({"sha256": digest, "reason": "BLOB_HASH_OR_SIZE_MISMATCH"})
                continue
            result["eligible"].append(digest)
            if not dry_run:
                path.unlink()
                result["removed"].append(digest)
    return result
