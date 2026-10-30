"""Selected-field portable exports, verified imports, and isolated backup tools.

Only run export against a consistent application backup extracted into a private
directory. The identity map and media review policy are local inputs, never
deliverables. Unknown fields and unreviewed file bytes fail closed or are omitted.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import sys
import tempfile
from urllib.parse import urlparse
from urllib.request import Request, urlopen
import zipfile

SCHEMA_VERSION = 1
PACKAGE_FORMAT = "travel-advisor-logical-v1"
MANIFEST = "dataset-manifest.json"
MARKER = "imported-installation.json"
BASE = set("id created_at updated_at version".split())


def fields(text):
    return BASE | set(text.split())


FIELDS = {
    "accounts": fields("display_name acquisition_method acquisition_mode"),
    "sources": fields("account_id kind display_name native_id acquisition_method acquisition_mode"),
    "attachments": fields("account_id acquisition_method acquisition_mode author_id bytes_saved_at classification decode_method evidence_only file_type height index kind material_id media_index media_state mime name native_id native_post_id origin original_verified path quality reason retrieved_at saved_at sha256 size source_id state type type_raw url validated_at width context_event_key association_state observation_id"),
    "materials": fields("account_id acquisition_method acquisition_mode analysis_deferred attachments author author_id classification content_encoding_issue conversation_id coverage direction event_key evidence_references extractions extracted_text segments first_discovered_at identity_confidence identity_uncertain imported_at issues local_id media_count_observed media_set_complete_verified message_epoch message_type message_type_raw native_id native_post_id native_revision native_tid observation_time_precision observed_at provenance publication_epoch publication_time relevance review_state sender_native_id server_id sort_seq source_id source_kind source_note source_revision source_revision_hash source_sha256 source_time source_time_raw state supplier text text_origin time_evidence type product_context reply_to_event_key"),
    "products": fields("acquisition_method advisor_judgment correction_at departure_city destination duration_days evidence hotels issues itinerary notes offers origin review_state shopping source_item_ids supplier title transcription_method transport verifications source_snapshots"),
    "cases": fields("name notes outcome request_text requirements"),
    "recommendations": fields("candidate_snapshots case_id exports image_url product_ids product_snapshots requirements_snapshot stale status text text_url"),
    "weekly": fields("information_date product_ids product_snapshots recommendation_snapshots reviewed_at text_url timezone title"),
    "exports": fields("image_path image_sha256 recommendation_id recommendation_version snapshot text_path text_sha256 weekly_id"),
    "extractions": fields("material_id result segments issues origin"),
    "verifications": fields("product_id field value scope evidence confirmed_by confirmed_at origin"),
    "live_evidence": fields("acquisition_method imported_at material_ids note product_ids"),
}
HISTORY_FIELDS = fields("account_id source_id source_kind mode state counts coverage initial_history interval_seconds last_cycle last_media_cycle last_page_at last_success_at local_exhausted observed_range requested_range stop_reason failures cycles onboarding_state initial_range last_checked_at last_pending_cycle last_pending_checked_at last_index_reconciliation_at" )
RECEIPT_FIELDS = set("account_id source_id event_key native_id native_server_id revision_hash outcome rule_version reason_code processed_at material_id first_discovered_at publication_time attempts protected_exception reply_target classification context_parent_revision".split())
CANDIDATE_FIELDS = set("id source_id account_id item outcome reason_code created_at attempts".split())
NESTED_FIELDS = set("""
label origin evidence updated_at prior_label correction_reason corrected_at
outcome reason_code rule_version score reasons confidence
anchor_basis end inherited_separator observation_time_precision observed_at precision source_time source_time_raw start status timezone
local_id server_id shard table snapshot_sha256
field source_item_id location quote
price price_max price_kind currency unit traveler occupancy departure_date valid_from valid_to extras transport_included inclusions exclusions availability confirmed_at conditions amount name required
destination departure_city date_start date_end duration_days budget budget_unit adults children shopping hotels pace hard_constraints preferences questions information_date
product applicable_offer failed unknown reasons score warnings selected explanation constraints
material_id material_version source_id source_kind source_name author source_time time_evidence
attachment_id text parser_version products visual_transcripts
inspected new kept updated skipped pending acquisition_failed media_inspected classification_operations ocr_operations media_retrieval_operations native_rows_inspected content_reads index_entries_inspected index_payload_bytes_hashed snapshot_copies new_or_changed change_stamp_sampled_bytes discovered failed revisions saved checked_at candidate_retries min_epoch max_epoch
relationship relationship_verified parent_event_key parent_outcome parent_native_id native_server_id
""".split()) | BASE
NESTED_FIELDS |= set().union(*FIELDS.values())
NATIVE_STRING_FIELDS = {"native_id", "native_post_id", "native_tid", "native_server_id", "server_id", "local_id", "sort_seq", "reply_target", "parent_native_id"}
SCHEMA = """
CREATE TABLE migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
CREATE TABLE records(kind TEXT NOT NULL,id TEXT NOT NULL,data TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,PRIMARY KEY(kind,id));
CREATE TABLE revisions(kind TEXT NOT NULL,id TEXT NOT NULL,version INTEGER NOT NULL,data TEXT NOT NULL,created_at TEXT NOT NULL,PRIMARY KEY(kind,id,version));
CREATE TABLE source_events(account_id TEXT NOT NULL,source_id TEXT NOT NULL,event_key TEXT NOT NULL,revision_hash TEXT NOT NULL,item_id TEXT NOT NULL,PRIMARY KEY(account_id,source_id,event_key,revision_hash));
CREATE TABLE blobs(hash TEXT PRIMARY KEY,size INTEGER NOT NULL,path TEXT NOT NULL);
CREATE TABLE processing_receipts(account_id TEXT NOT NULL,source_id TEXT NOT NULL,event_key TEXT NOT NULL,data TEXT NOT NULL,PRIMARY KEY(account_id,source_id,event_key));
CREATE TABLE pending_candidates(id TEXT PRIMARY KEY,source_id TEXT NOT NULL,data TEXT NOT NULL);
CREATE TABLE source_index(source_id TEXT NOT NULL,event_key TEXT NOT NULL,revision TEXT NOT NULL,PRIMARY KEY(source_id,event_key));
CREATE INDEX records_by_kind ON records(kind,updated_at);
"""


def now():
    return datetime.now(timezone.utc).isoformat()


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def sha(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def checked_path(root, relative):
    if not isinstance(relative, str) or not relative or "\\" in relative or ":" in relative:
        raise ValueError("Unsafe relative file reference")
    part = PurePosixPath(relative)
    if part.is_absolute() or any(p in {"", ".", ".."} for p in relative.split("/")):
        raise ValueError("Unsafe relative file reference")
    target = Path(root).joinpath(*part.parts)
    if not target.resolve().is_relative_to(Path(root).resolve()) or target.is_symlink():
        raise ValueError("File reference leaves package root")
    return target


def connect_read(path):
    return sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)


class Sanitizer:
    def __init__(self, replacements):
        self.replacements = sorted(((str(k), str(v)) for k, v in replacements.items() if k), key=lambda kv: -len(kv[0]))
        self.removed = Counter()

    def text(self, value):
        for original, alias in self.replacements:
            value = value.replace(original, alias)
        # Essential managed paths are rewritten separately; local evidence paths
        # are descriptive only and must not bind the receiving machine.
        value = re.sub(r"(?<![A-Za-z0-9_])[A-Za-z]:[\\/][^\s\"<>|]+", "[local-path-removed]", value)
        value = re.sub(r"https?://[^\s<>\"]*[?&](?:token|key|auth|sign|signature|expires|access_token)=[^\s<>\"]*", "[private-url-removed]", value, flags=re.I)
        return value

    def value(self, value, allowed=None, key=""):
        if isinstance(value, dict):
            result = {}
            for child_key, child in value.items():
                if child_key not in (NESTED_FIELDS if allowed is None else allowed):
                    self.removed[child_key] += 1
                    continue
                result[child_key] = self.value(child, key=child_key)
            return result
        if isinstance(value, list):
            return [self.value(x, key=key) for x in value]
        if key in NATIVE_STRING_FIELDS and value is not None:
            return self.text(str(value))
        if isinstance(value, str):
            return self.text(value)
        return value


def insert_record(db, kind, value, revision=True):
    created = value.get("created_at") or now()
    updated = value.get("updated_at") or created
    value = {**value, "created_at": created, "updated_at": updated, "version": value.get("version", 1)}
    db.execute("INSERT INTO records VALUES(?,?,?,?,?)", (kind, value["id"], encode(value), created, updated))
    if revision:
        db.execute("INSERT OR REPLACE INTO revisions VALUES(?,?,?,?,?)", (kind, value["id"], value["version"], encode(value), created))


def export_dataset(snapshot, identity_map, media_policy, output, version):
    snapshot, output = Path(snapshot).resolve(), Path(output).resolve()
    if output.exists():
        raise ValueError("Export destination must not exist")
    identity = read_json(identity_map)
    sanitizer = Sanitizer(identity.get("replacements", identity))
    review_policy = read_json(media_policy)
    if review_policy.get("review_complete") is False:
        raise ValueError("Media privacy review is incomplete")
    policy = {str(k).replace("\\", "/"): v for k, v in review_policy.get("files", {}).items()}
    candidate_policy = review_policy.get("candidates", {})
    output.mkdir(parents=True)
    transformations, exclusions, file_map = [], [], {}
    input_manifest = read_json(snapshot / "manifest.json") if (snapshot / "manifest.json").exists() else {}
    with closing(connect_read(snapshot / "workbench.sqlite3")) as source:
        if source.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("Snapshot database integrity failure")
        records = defaultdict(dict)
        for kind, ident, data in source.execute("SELECT kind,id,data FROM records"):
            records[kind][ident] = json.loads(data)
        candidates = [json.loads(r[0]) for r in source.execute("SELECT data FROM pending_candidates")]
        receipts = [json.loads(r[0]) for r in source.execute("SELECT data FROM processing_receipts")]
        # Media references are selected from current retained objects, not from
        # the native cache or the historical blob catalog.
        references = set()
        for value in records["attachments"].values():
            if value.get("path"):
                references.add(value["path"].replace("\\", "/"))
        for candidate in candidates:
            for value in candidate.get("item", {}).get("attachments", []):
                if value.get("path"):
                    references.add(value["path"].replace("\\", "/"))
        for value in records["exports"].values():
            for field in ("image_path", "text_path"):
                if value.get(field):
                    references.add(value[field].replace("\\", "/"))
        for relative in sorted(references):
            original = checked_path(snapshot, relative)
            review = policy.get(relative)
            if not review:
                raise ValueError("Referenced file lacks explicit privacy review: " + relative)
            action = review.get("action")
            reason = sanitizer.text(str(review.get("reason") or "Reviewed retained application asset"))
            public_ref = sanitizer.text(relative)
            if action == "exclude" or not original.is_file():
                reason = reason if action == "exclude" else "Referenced original file is missing"
                file_map[relative] = {"excluded": True, "reason": reason}
                exclusions.append({"reference": public_ref, "reason": reason, "category": "privacy" if action == "exclude" else "missing"})
                continue
            if action not in {"include", "replace"}:
                raise ValueError("Unknown media review action")
            content_path = Path(review["replacement_path"]).resolve() if action == "replace" else original
            if not content_path.is_file():
                raise ValueError("Reviewed derivative is missing")
            content = content_path.read_bytes()
            if relative.endswith(".txt"):
                content = sanitizer.text(content.decode("utf-8-sig")).encode("utf-8")
            digest = hashlib.sha256(content).hexdigest()
            target_relative = ("exports/" + digest + Path(relative).suffix.lower()) if relative.startswith("exports/") else ("blobs/" + digest[:2] + "/" + digest)
            target = checked_path(output, target_relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            file_map[relative] = {"path": target_relative, "sha256": digest, "size": len(content), "transformed": action == "replace" or content != original.read_bytes()}
            if content.startswith((b"\x89PNG\r\n", b"\xff\xd8\xff", b"GIF87a", b"GIF89a")):
                from PIL import Image
                with Image.open(io.BytesIO(content)) as image:
                    file_map[relative].update(width=image.width, height=image.height, mime=Image.MIME.get(image.format, "application/octet-stream"))
                    image.verify()
            if file_map[relative]["transformed"]:
                transformations.append({"reference": public_ref, "exported_path": target_relative, "sha256": digest, "reason": reason if action == "replace" else "Text identity aliasing"})

        def attachment(value):
            clean = sanitizer.value(value, FIELDS["attachments"])
            info = file_map.get(str(value.get("path", "")).replace("\\", "/"))
            if info and not info.get("excluded"):
                clean.update({k: info[k] for k in ("path", "sha256", "size")})
                clean.update({k: info[k] for k in ("width", "height", "mime") if k in info})
                clean["url"] = "/api/attachments/" + clean["id"] if clean.get("id") in {sanitizer.text(i) for i in records["attachments"]} else None
                if info["transformed"]:
                    clean["export_transformation"] = "privacy-sanitized derivative"
                    clean["original_verified"] = False
                    if info.get("mime") and info["mime"] != value.get("mime"):
                        suffix = {"image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif"}.get(info["mime"])
                        if suffix:
                            clean["original_name"] = clean.get("name")
                            clean["name"] = Path(clean.get("name") or clean.get("id") or "image").stem + ".sanitized" + suffix
                            clean["file_type"] = suffix[1:]
            elif info and info.get("excluded"):
                for key in ("path", "sha256", "size", "url"):
                    clean.pop(key, None)
                clean.update(state="UNAVAILABLE", media_state="UNAVAILABLE", export_exclusion_reason=info["reason"])
            elif value.get("state") in {"SAVED", "STAGED"}:
                for key in ("path", "sha256", "size", "url"):
                    clean.pop(key, None)
                clean.update(state="UNAVAILABLE", export_exclusion_reason="Historical or missing file was not part of the retained snapshot")
            clean["imported"] = True
            return clean

        def material(value):
            clean = sanitizer.value(value, FIELDS["materials"])
            clean["attachments"] = [attachment(a) for a in value.get("attachments", [])]
            clean["imported"] = True
            historical_identity = {key: value[key] for key in ("native_id_verified", "identity_verified", "sender_identity_verified") if isinstance(value.get(key), bool)}
            if historical_identity:
                clean["historical_identity_evidence"] = {"scope": "original snapshot observation; not receiving-account verification", **historical_identity}
            if clean.get("direction") in {"outgoing", "sent", "self"}:
                clean["author"] = "self"
                clean["author_id"] = "self"
                clean["sender_native_id"] = "self"
            return clean

        def clean_record(kind, value):
            if kind == "attachments":
                return attachment(value)
            if kind == "materials":
                return material(value)
            clean = sanitizer.value(value, FIELDS[kind])
            if kind == "accounts":
                clean.update(native_id=None, native_id_verified=False, selected=False, verification_status="IMPORTED", imported=True)
                clean["display_name"] = clean["id"]
            if kind == "sources":
                clean.update(native_id_verified=False, selected=False, verification_status="IMPORTED", imported=True)
                if isinstance(value.get("native_id_verified"), bool):
                    clean["historical_identity_evidence"] = {"native_id_verified": value["native_id_verified"], "scope": "original snapshot observation; not receiving-account verification"}
                clean["capabilities"] = {"available": False, "status": "IMPORTED", "reason": "导入的历史来源；未绑定本机账号，实时采集已停用。"}
            if kind == "exports":
                for prefix in ("image", "text"):
                    original_path = value.get(prefix + "_path")
                    if original_path:
                        info = file_map[original_path.replace("\\", "/")]
                        if info.get("excluded"):
                            clean.pop(prefix + "_path", None)
                            clean.pop(prefix + "_sha256", None)
                            clean[prefix + "_exclusion_reason"] = info["reason"]
                        else:
                            clean[prefix + "_path"] = info["path"]
                            clean[prefix + "_sha256"] = info["sha256"]
            return clean

        with sqlite3.connect(output / "workbench.sqlite3") as dest:
            dest.executescript(SCHEMA)
            dest.execute("INSERT INTO migrations VALUES(?,?)", (SCHEMA_VERSION, now()))
            for kind in FIELDS:
                for value in records[kind].values():
                    insert_record(dest, kind, clean_record(kind, value))
            # Only business versions of objects that still exist are retained.
            # Old accounts, native leases, removed materials and job churn never
            # enter this new database or its free pages.
            revision_kinds = {"materials", "products", "cases", "recommendations", "weekly", "extractions", "verifications"}
            for kind, ident, ver, data, created in source.execute("SELECT kind,id,version,data,created_at FROM revisions ORDER BY kind,id,version"):
                if kind not in revision_kinds or ident not in records[kind]:
                    continue
                clean = clean_record(kind, json.loads(data))
                dest.execute("INSERT OR REPLACE INTO revisions VALUES(?,?,?,?,?)", (kind, clean["id"], ver, encode(clean), created))
            for old_kind in ("jobs", "background_jobs", "source_processing", "checkpoints"):
                for value in records[old_kind].values():
                    clean = sanitizer.value(value, HISTORY_FIELDS)
                    clean.update(id=old_kind + ":" + clean["id"], original_kind=old_kind, historical_state=clean.pop("state", None), state="IMPORTED_DETACHED", executable=False)
                    insert_record(dest, "import_history", clean)
            for row in source.execute("SELECT account_id,source_id,event_key,revision_hash,item_id FROM source_events"):
                if row[4] in records["materials"]:
                    dest.execute("INSERT INTO source_events VALUES(?,?,?,?,?)", tuple(sanitizer.text(str(x)) for x in row))
            for value in receipts:
                clean = sanitizer.value(value, RECEIPT_FIELDS)
                clean.update(imported=True, synchronization_eligible=False)
                dest.execute("INSERT INTO processing_receipts VALUES(?,?,?,?)", (clean["account_id"], clean["source_id"], clean["event_key"], encode(clean)))
            for value in candidates:
                clean = sanitizer.value(value, CANDIDATE_FIELDS)
                clean["item"] = material(value.get("item", {}))
                privacy = candidate_policy.get(value["id"], {})
                if privacy.get("exclude_text"):
                    clean["item"]["text"] = ""
                    for field in ("extracted_text", "segments", "extractions", "product_context"):
                        clean["item"].pop(field, None)
                    reason = sanitizer.text(str(privacy.get("reason") or "Excluded private or unrelated candidate body"))
                    clean["item"]["export_exclusion_reason"] = reason
                    exclusions.append({"reference": "candidate:" + clean["id"], "reason": reason, "category": "candidate_body"})
                clean.update(imported=True, executable=False, expires_at=None, next_retry_at=None)
                dest.execute("INSERT INTO pending_candidates VALUES(?,?,?)", (clean["id"], clean["source_id"], encode(clean)))
            for info in file_map.values():
                if not info.get("excluded") and info["path"].startswith("blobs/"):
                    dest.execute("INSERT OR IGNORE INTO blobs VALUES(?,?,?)", (info["sha256"], info["size"], info["path"]))
            insert_record(dest, "settings", {"id": "main", "timezone": "Asia/Shanghai", "provider": {"protocol": "openai_compatible", "base_url": "", "model": "", "vision_model": "", "timeout": 30, "timeout_seconds": 30, "max_concurrency": 2}, "imported": True, "live_collection_enabled": False})
            dest.commit()
        report = validate_database(output)
        file_manifest = {p.relative_to(output).as_posix(): {"size": p.stat().st_size, "sha256": sha(p)} for p in sorted(output.rglob("*")) if p.is_file()}
        manifest = {"format": PACKAGE_FORMAT, "schema_version": SCHEMA_VERSION, "dataset_version": version, "snapshot_timestamp": input_manifest.get("created_at"), "exported_at": now(), "files": file_manifest, "counts": report, "transformations": transformations, "exclusions": exclusions, "removed_field_names": sorted(sanitizer.removed), "removed_field_counts": dict(sorted(sanitizer.removed.items())), "removed_categories": ["owner identity replaced by stable aliases", "native transport and media access fields", "account verification and selected state", "live jobs, leases, cursors, and source indexes", "unreferenced blobs and removed-content history", "native databases, private snapshots, credentials, and caches"], "source_record_counts": {k: len(v) for k, v in sorted(records.items())}, "source_revision_rows": source.execute("SELECT COUNT(*) FROM revisions").fetchone()[0], "pending_candidates_detached": True, "live_collection_enabled": False}
        manifest["dataset_id"] = hashlib.sha256(encode(manifest).encode()).hexdigest()
        write_json(output / MANIFEST, manifest)
        verify_dataset(output)
        return {"dataset_id": manifest["dataset_id"], "dataset_version": version, "counts": report, "files": len(file_manifest), "bytes": sum(x["size"] for x in file_manifest.values()), "transformations": len(transformations), "exclusions": len(exclusions)}


def validate_database(root):
    root = Path(root)
    with closing(connect_read(root / "workbench.sqlite3")) as db:
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("Database integrity failure")
        if [r[0] for r in db.execute("SELECT version FROM migrations")] != [SCHEMA_VERSION]:
            raise ValueError("Unsupported database schema")
        objects = defaultdict(dict)
        for kind, ident, data in db.execute("SELECT kind,id,data FROM records"):
            value = json.loads(data)
            if value["id"] != ident:
                raise ValueError("Record identifier mismatch")
            objects[kind][ident] = value
        candidates = [json.loads(r[0]) for r in db.execute("SELECT data FROM pending_candidates")]
        receipts = [json.loads(r[0]) for r in db.execute("SELECT data FROM processing_receipts")]

        def require(kind, ident):
            if ident and ident not in objects[kind]:
                raise ValueError("Broken " + kind + " relationship")

        def validate_attachment(value):
            require("sources", value.get("source_id"))
            require("accounts", value.get("account_id"))
            if value.get("state") in {"SAVED", "STAGED"}:
                path = checked_path(root, value["path"])
                if not path.is_file() or path.stat().st_size != value["size"] or sha(path) != value["sha256"]:
                    raise ValueError("Attachment byte integrity failure")

        def validate_business_snapshot(value):
            if isinstance(value, list):
                for item in value:
                    validate_business_snapshot(item)
            elif isinstance(value, dict):
                for key, kind in (("account_id", "accounts"), ("source_id", "sources"), ("material_id", "materials"), ("source_item_id", "materials"), ("product_id", "products"), ("case_id", "cases"), ("recommendation_id", "recommendations"), ("weekly_id", "weekly")):
                    require(kind, value.get(key))
                for key, kind in (("source_item_ids", "materials"), ("product_ids", "products"), ("exports", "exports")):
                    if isinstance(value.get(key), list):
                        for ident in value[key]:
                            if isinstance(ident, str):
                                require(kind, ident)
                if value.get("path") and value.get("state") in {"SAVED", "STAGED"}:
                    validate_attachment(value)
                for child in value.values():
                    if isinstance(child, (dict, list)):
                        validate_business_snapshot(child)

        for value in objects["sources"].values():
            require("accounts", value.get("account_id"))
        for value in objects["materials"].values():
            require("sources", value.get("source_id"))
            require("accounts", value.get("account_id"))
            for item in value.get("attachments", []):
                require("attachments", item["id"])
                validate_attachment(item)
                canonical = objects["attachments"][item["id"]]
                for key in ("path", "sha256", "state", "media_index"):
                    if item.get(key) != canonical.get(key):
                        raise ValueError("Embedded attachment does not match occurrence")
        for value in objects["attachments"].values():
            require("materials", value.get("material_id"))
            validate_attachment(value)
        for value in candidates:
            require("sources", value.get("source_id"))
            require("accounts", value.get("account_id"))
            for item in value.get("item", {}).get("attachments", []):
                validate_attachment(item)
        for value in objects["products"].values():
            for ident in value.get("source_item_ids", []):
                require("materials", ident)
        for value in objects["recommendations"].values():
            require("cases", value.get("case_id"))
            for ident in value.get("product_ids", []):
                require("products", ident)
            for ident in value.get("exports", []):
                require("exports", ident)
        for value in objects["weekly"].values():
            for ident in value.get("product_ids", []):
                require("products", ident)
        for value in objects["exports"].values():
            require("recommendations", value.get("recommendation_id"))
            require("weekly", value.get("weekly_id"))
            for prefix in ("image", "text"):
                if value.get(prefix + "_path"):
                    path = checked_path(root, value[prefix + "_path"])
                    if not path.is_file() or (value.get(prefix + "_sha256") and sha(path) != value[prefix + "_sha256"]):
                        raise ValueError("Export byte integrity failure")
        for kind in ("materials", "products", "cases", "recommendations", "weekly", "exports", "extractions", "verifications"):
            for value in objects[kind].values():
                validate_business_snapshot(value)
        for kind, data in db.execute("SELECT kind,data FROM revisions"):
            if kind in {"materials", "products", "cases", "recommendations", "weekly", "extractions", "verifications"}:
                validate_business_snapshot(json.loads(data))
        for account, source, event, revision, material in db.execute("SELECT * FROM source_events"):
            require("accounts", account); require("sources", source); require("materials", material)
        for value in receipts:
            require("accounts", value.get("account_id")); require("sources", value.get("source_id")); require("materials", value.get("material_id"))
        for digest, size, relative in db.execute("SELECT hash,size,path FROM blobs"):
            path = checked_path(root, relative)
            if not path.is_file() or path.stat().st_size != size or sha(path) != digest:
                raise ValueError("Blob integrity failure")
        return {"records": {kind: len(values) for kind, values in sorted(objects.items()) if values}, "revisions": db.execute("SELECT COUNT(*) FROM revisions").fetchone()[0], "source_events": db.execute("SELECT COUNT(*) FROM source_events").fetchone()[0], "processing_receipts": len(receipts), "processing_outcomes": dict(sorted(Counter(v.get("outcome") for v in receipts).items())), "pending_candidates": len(candidates), "pending_outcomes": dict(sorted(Counter(v.get("outcome") for v in candidates).items())), "saved_attachment_occurrences": sum(v.get("state") == "SAVED" for v in objects["attachments"].values()), "unavailable_attachment_occurrences": sum(v.get("state") == "UNAVAILABLE" for v in objects["attachments"].values()), "pending_attachment_slots": sum(len(v.get("item", {}).get("attachments", [])) for v in candidates), "pending_saved_files": sum(a.get("state") in {"SAVED", "STAGED"} for v in candidates for a in v.get("item", {}).get("attachments", [])), "unique_blobs": db.execute("SELECT COUNT(*) FROM blobs").fetchone()[0], "relationship_checks": "PASS"}


def verify_dataset(folder):
    folder = Path(folder).resolve()
    if folder.is_file():
        with tempfile.TemporaryDirectory(prefix="travel-verify-") as scratch:
            unpack_archive(folder, scratch)
            return verify_dataset(scratch)
    manifest = read_json(folder / MANIFEST)
    if manifest.get("format") != PACKAGE_FORMAT or manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Unsupported package or schema version")
    core = {k: v for k, v in manifest.items() if k != "dataset_id"}
    if hashlib.sha256(encode(core).encode()).hexdigest() != manifest.get("dataset_id"):
        raise ValueError("Manifest identity mismatch")
    allowed = set(manifest["files"]) | {MANIFEST}
    actual = {p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()}
    if actual != allowed:
        raise ValueError("Unlisted or missing package files")
    for name, info in manifest["files"].items():
        path = checked_path(folder, name)
        if not path.is_file() or path.stat().st_size != info["size"] or sha(path) != info["sha256"]:
            raise ValueError("Package file integrity failure: " + name)
    counts = validate_database(folder)
    if counts != manifest["counts"]:
        raise ValueError("Manifest record counts mismatch")
    return {"status": "verified", "dataset_id": manifest["dataset_id"], "dataset_version": manifest["dataset_version"], "counts": counts, "files": len(manifest["files"])}


def import_dataset(package, destination):
    package, destination = Path(package).resolve(), Path(destination).resolve()
    if package.is_file():
        with tempfile.TemporaryDirectory(prefix="travel-import-package-") as scratch:
            unpack_archive(package, scratch)
            return import_dataset(scratch, destination)
    checked = verify_dataset(package)
    if destination.exists() and any(destination.iterdir()):
        marker = destination / MARKER
        if marker.is_file() and read_json(marker).get("dataset_id") == checked["dataset_id"]:
            return {"status": "already_imported", "dataset_id": checked["dataset_id"], "preserved_existing_changes": True}
        raise ValueError("Destination contains data; choose a new empty data directory")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".travel-import-", dir=destination.parent))
    try:
        manifest = read_json(package / MANIFEST)
        for name in [*manifest["files"], MANIFEST]:
            target = checked_path(temporary, name)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(checked_path(package, name), target)
        validate_database(temporary)
        write_json(temporary / MARKER, {"dataset_id": checked["dataset_id"], "dataset_version": checked["dataset_version"], "schema_version": SCHEMA_VERSION, "imported_at": now(), "live_collection_enabled": False})
        if destination.exists():
            destination.rmdir()
        temporary.rename(destination)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return {"status": "imported", "dataset_id": checked["dataset_id"], "destination": str(destination), "counts": checked["counts"]}


def pack_dataset(folder, archive):
    verify_dataset(folder)
    archive = Path(archive)
    if archive.exists():
        raise ValueError("Archive destination already exists")
    manifest = read_json(Path(folder) / MANIFEST)
    with zipfile.ZipFile(archive, "x", zipfile.ZIP_DEFLATED) as output:
        for name in sorted([*manifest["files"], MANIFEST]):
            output.write(checked_path(folder, name), name)
    return {"archive": str(archive), "size": archive.stat().st_size, "sha256": sha(archive)}


def unpack_archive(archive, destination):
    destination = Path(destination).resolve()
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("Unpack destination must be empty")
    with zipfile.ZipFile(archive) as incoming:
        infos = incoming.infolist()
        names = [i.filename for i in infos]
        if len(names) != len(set(names)) or sum(i.file_size for i in infos) > 2 * 1024**3:
            raise ValueError("Duplicate archive paths or excessive expanded size")
        for info in infos:
            checked_path(destination, info.filename.rstrip("/"))
            if (info.external_attr >> 16) & 0o170000 == 0o120000 or info.file_size > 512 * 1024**2:
                raise ValueError("Unsupported archive member")
        for info in infos:
            target = checked_path(destination, info.filename.rstrip("/"))
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with incoming.open(info) as source, target.open("xb") as sink:
                    shutil.copyfileobj(source, sink)
    return {"status": "unpacked", "destination": str(destination), "files": len(infos)}


def backup_instance(url, output):
    parsed = urlparse(url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"} or parsed.username or parsed.password:
        raise ValueError("Backup requires a loopback application URL")
    output = Path(output).resolve()
    if output.exists():
        raise ValueError("Backup output already exists")
    with urlopen(url.rstrip("/") + "/api/health", timeout=15) as response:
        health = json.load(response)
    data_root = Path(health["data_dir"])
    if not (data_root / MARKER).is_file():
        raise ValueError("This command backs up imported installations only")
    with urlopen(Request(url.rstrip("/") + "/api/backup", data=b"{}", headers={"Content-Type": "application/json"}, method="POST"), timeout=120) as response:
        result = json.load(response)
    source = Path(result["path"]).resolve()
    if source.parent != (data_root / "backups").resolve():
        raise ValueError("Application returned an unexpected backup path")
    shutil.copyfile(source, output)
    with zipfile.ZipFile(output, "a", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(MARKER, (data_root / MARKER).read_bytes())
    return {"archive": str(output), "size": output.stat().st_size, "sha256": sha(output)}


def restore_backup(archive, destination):
    destination = Path(destination).resolve()
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("Restore never overwrites an existing installation")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".travel-restore-", dir=destination.parent))
    try:
        unpack_archive(archive, temporary)
        if not (temporary / MARKER).is_file():
            raise ValueError("Backup does not identify an imported installation")
        manifest = read_json(temporary / "manifest.json")
        if manifest.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("Unsupported backup schema")
        actual = {p.relative_to(temporary).as_posix() for p in temporary.rglob("*") if p.is_file()}
        if actual != set(manifest["files"]) | {"manifest.json", MARKER}:
            raise ValueError("Unlisted or missing backup files")
        for name, info in manifest["files"].items():
            path = checked_path(temporary, name)
            if path.stat().st_size != info["size"] or sha(path) != info["sha256"]:
                raise ValueError("Backup hash failure")
        counts = validate_database(temporary)
        if destination.exists():
            destination.rmdir()
        temporary.rename(destination)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return {"status": "restored", "destination": str(destination), "counts": counts}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export")
    for name in ("snapshot", "identity-map", "media-policy", "output", "version"):
        export.add_argument("--" + name, required=True)
    verify = commands.add_parser("verify"); verify.add_argument("--package", required=True)
    imp = commands.add_parser("import"); imp.add_argument("--package", required=True); imp.add_argument("--data-dir", required=True)
    pack = commands.add_parser("pack"); pack.add_argument("--dataset", "--package", dest="package", required=True); pack.add_argument("--output", required=True)
    unpack = commands.add_parser("unpack"); unpack.add_argument("--archive", required=True); unpack.add_argument("--output", required=True)
    backup = commands.add_parser("backup"); backup.add_argument("--url", required=True); backup.add_argument("--output", required=True)
    restore = commands.add_parser("restore"); restore.add_argument("--archive", required=True); restore.add_argument("--data-dir", required=True)
    args = parser.parse_args()
    if args.command == "export":
        result = export_dataset(args.snapshot, args.identity_map, args.media_policy, args.output, args.version)
    elif args.command == "verify":
        result = verify_dataset(args.package)
    elif args.command == "import":
        result = import_dataset(args.package, args.data_dir)
    elif args.command == "pack":
        result = pack_dataset(args.package, args.output)
    elif args.command == "unpack":
        result = unpack_archive(args.archive, args.output)
    elif args.command == "backup":
        result = backup_instance(args.url, args.output)
    else:
        result = restore_backup(args.archive, args.data_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
