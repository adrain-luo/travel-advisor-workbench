"""Migration/GC tests use isolated application data only."""
import hashlib
import json
from pathlib import Path

from backend.store import Store
from backend.background.migration import (EXPECTED_ACCOUNT, EXPECTED_FRIEND,
    protected_materials, gc_unreferenced_blobs, evaluate_backup)


def source(store):
    return store.put("sources", {"kind": "moments", "acquisition_mode": "background", "native_id": EXPECTED_FRIEND,
        "account_id": "account", "account_native_id": EXPECTED_ACCOUNT}, "source")


def material(store, ident, **extra):
    return store.put("materials", {"source_kind": "moments", "source_id": "source", "account_id": "account",
        "author_id": EXPECTED_FRIEND, "event_key": "moments:" + ident, "source_revision_hash": "revision-" + ident,
        "identity_verified": True, "acquisition_mode": "background", "text": "你好", "attachments": [], **extra}, ident)


def test_protection_preserves_manual_uploads_edits_and_business_references(tmp_path):
    store = Store(tmp_path); source(store)
    material(store, "safe-skip", classification={"origin": "inspection", "label": "other"})
    material(store, "manual", classification={"origin": "manual", "label": "travel_promotion"})
    material(store, "edited")
    edited = store.get("materials", "edited"); store.put("materials", {**edited, "text": "User supplied revision"})
    material(store, "ambiguous", identity_verified=False)
    material(store, "linked")
    material(store, "linked-attachment")
    store.put("attachments", {"id": "asset", "material_id": "linked-attachment"})
    store.put("products", {"source_item_ids": ["linked"]})
    store.put("weekly", {"snapshot": {"images": [{"attachment_id": "asset"}]}})
    store.put("materials", {"text": "manual upload", "acquisition_mode": "upload"}, "upload")
    protected = protected_materials(store)
    assert "safe-skip" not in protected
    assert set(protected) == {"manual", "edited", "ambiguous", "linked", "linked-attachment", "upload"}
    assert "CONTENT_EDIT_WITHOUT_NATIVE_REVISION_CHANGE" in protected["edited"]
    assert "RETAINED_BUSINESS_REFERENCE" in protected["linked"]


def test_native_revision_changes_are_not_misreported_as_manual_edits(tmp_path):
    store = Store(tmp_path); source(store)
    value = material(store, "native")
    store.put("materials", {**value, "text": "changed native source", "source_revision_hash": "new-native-revision"})
    assert not protected_materials(store)


def test_pending_explicit_material_reference_is_protected(tmp_path):
    store = Store(tmp_path); source(store)
    material(store, "parent")
    with store.connect() as db:
        db.execute("CREATE TABLE IF NOT EXISTS pending_candidates(id TEXT PRIMARY KEY,source_id TEXT NOT NULL,data TEXT NOT NULL)")
        db.execute("INSERT INTO pending_candidates VALUES(?,?,?)", ("pending", "source", json.dumps({"context_material_id": "parent"})))
    assert "RETAINED_BUSINESS_REFERENCE" in protected_materials(store)["parent"]


def test_gc_retains_shared_bytes_current_revisions_pending_and_protected_business(tmp_path):
    store = Store(tmp_path)
    blobs = [store.save_blob(value) for value in (b"shared", b"revision", b"pending", b"export", b"orphan")]
    store.put("materials", {"attachments": [blobs[0]]}, "shared")
    old = store.put("materials", {"attachments": [blobs[1]]}, "revision")
    store.put("materials", {**old, "attachments": []})
    with store.connect() as db:
        db.execute("CREATE TABLE IF NOT EXISTS pending_candidates(id TEXT PRIMARY KEY,source_id TEXT NOT NULL,data TEXT NOT NULL)")
        db.execute("INSERT INTO pending_candidates VALUES(?,?,?)", ("pending", "source", json.dumps({"record": {"attachments": [blobs[2]]}})))
    store.put("exports", {"snapshot": {"media": blobs[3]}})
    first = gc_unreferenced_blobs(store, blobs)
    assert first["eligible"] == [blobs[4]["sha256"]] and not first["removed"]
    second = gc_unreferenced_blobs(store, blobs, dry_run=False)
    assert second["removed"] == [blobs[4]["sha256"]]
    assert all((tmp_path / item["path"]).exists() for item in blobs[:4])
    assert not (tmp_path / blobs[4]["path"]).exists()


def test_gc_rejects_nonblob_paths_and_mismatching_bytes(tmp_path):
    store = Store(tmp_path)
    value = store.save_blob(b"fixture")
    (tmp_path / value["path"]).write_bytes(b"changed")
    outside = tmp_path / "exports" / "keep"; outside.write_bytes(b"fixture")
    result = gc_unreferenced_blobs(store, [value, {**value, "path": "exports/keep"}, {**value, "path": "../escape"}], dry_run=False)
    assert not result["removed"] and len(result["rejected"]) == 3
    assert outside.exists()


def test_backup_evaluation_is_minimal_reversible_and_removes_temporary_copies(tmp_path):
    store = Store(tmp_path / "business"); source(store)
    material(store, "greeting")
    material(store, "tour", text="云南六日游 1999元，含早餐和酒店")
    material(store, "protected", classification={"origin": "manual", "label": "travel_promotion"})
    store.put("background_jobs", {"state": "WAITING", "mode": "continuous", "source_id": "source"}, "job")
    archive = store.backup()
    before = hashlib.sha256(archive.read_bytes()).hexdigest()
    evidence = tmp_path / "evidence"; evidence.mkdir()
    report = evaluate_backup(archive, evidence, ocr=lambda *a, **kw: (_ for _ in ()).throw(AssertionError("text-only records reached OCR")))
    assert report["authorized_evaluated"] == 3 and report["outcome_counts"] == {"SKIP_IRRELEVANT": 1, "KEEP_PRODUCT_RELEVANT": 2}
    assert report["business_writes"] == 0 and report["metrics"]["ocr_operations"] == 0
    baseline = json.loads((evidence / "baseline.json").read_text())
    assert "materials/tour" in baseline["record_hashes"] and baseline["jobs_before_pause"][0]["state"] == "WAITING"
    decision_text = (evidence / "decision-manifest.json").read_text(encoding="utf-8")
    assert "1999" not in decision_text and "你好" not in decision_text and '"text"' not in decision_text
    assert not list(evidence.glob("migration-inspection-*"))
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == before and len(store.all("materials")) == 3
