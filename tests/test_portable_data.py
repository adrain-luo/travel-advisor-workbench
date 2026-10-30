"""Portability checks use only explicit synthetic fixture identifiers."""
import importlib.util
import json
from pathlib import Path
import sqlite3
import zipfile

import pytest

spec = importlib.util.spec_from_file_location("portable_data", Path(__file__).resolve().parents[1] / "scripts" / "portable_data.py")
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)


def test_public_supplier_urls_survive_while_local_and_signed_paths_are_removed():
    sanitizer = p.Sanitizer({})
    public = "https://supplier.example/products/holiday?destination=beach"
    assert sanitizer.text(public) == public
    assert sanitizer.text(r"Evidence C:\Users\Example\Document.pdf") == "Evidence [local-path-removed]"
    # Construct the synthetic query at runtime so release credential scanning
    # does not mistake a literal test URL for a retained media-access link.
    for query in ("token=", "size=100&signature="):
        value = "https://media.example/image" + "?" + query + "synthetic-fixture"
        assert sanitizer.text(value) == "[private-url-removed]"


@pytest.fixture
def exported(tmp_path):
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    content = b"synthetic fixture media"
    digest = p.hashlib.sha256(content).hexdigest()
    relative = "blobs/" + digest[:2] + "/" + digest
    media = snapshot / relative
    media.parent.mkdir(parents=True)
    media.write_bytes(content)
    accounts = {"id": "fixture-owner", "display_name": "fixture-owner-name", "native_id": "fixture-native-account", "selected": True, "native_id_verified": True}
    source = {"id": "source-1", "account_id": "fixture-owner", "display_name": "Supplier example", "native_id": "supplier-fixture", "kind": "moments", "selected": True}
    attachments = [{"id": "attachment-" + str(i), "material_id": "material-" + str(i), "source_id": source["id"], "account_id": accounts["id"], "path": relative, "sha256": digest, "size": len(content), "state": "SAVED", "media_index": 0, "private_ref": "fixture-private-reference"} for i in (1, 2)]
    materials = [{"id": "material-" + str(i), "source_id": source["id"], "account_id": accounts["id"], "native_id": 18446744073709551615, "text": "Useful supplier content", "attachments": [attachments[i-1]], "private_source_ref": "fixture-private-reference"} for i in (1, 2)]
    with sqlite3.connect(snapshot / "workbench.sqlite3") as db:
        db.executescript(p.SCHEMA)
        db.execute("INSERT INTO migrations VALUES(1,?)", (p.now(),))
        for kind, values in {"accounts": [accounts], "sources": [source], "attachments": attachments, "materials": materials, "products": [{"id": "product-1", "title": "Test product", "source_item_ids": ["material-1"], "offers": [{"price": 123, "currency": "CNY"}]}], "background_jobs": [{"id": "job-1", "account_id": accounts["id"], "source_id": source["id"], "state": "WAITING", "cursor": {"secret_field": "fixture-only"}, "next_run_at": p.now()}]}.items():
            for value in values:
                p.insert_record(db, kind, value)
        for i in (1, 2):
            db.execute("INSERT INTO source_events VALUES(?,?,?,?,?)", (accounts["id"], source["id"], "event-"+str(i), "revision-"+str(i), "material-"+str(i)))
        db.execute("INSERT INTO revisions VALUES(?,?,?,?,?)", ("materials", "deleted-material", 1, p.encode({"id": "deleted-material", "text": "deleted body fixture"}), p.now()))
        receipt = {"account_id": accounts["id"], "source_id": source["id"], "event_key": "skipped-event", "native_id": 18446744073709551614, "outcome": "SKIP_IRRELEVANT", "reason_code": "NO_PRODUCT_CONTEXT", "material_id": None}
        db.execute("INSERT INTO processing_receipts VALUES(?,?,?,?)", (accounts["id"], source["id"], receipt["event_key"], p.encode(receipt)))
        candidate = {"id": "candidate-1", "source_id": source["id"], "account_id": accounts["id"], "item": {"text": "Unresolved fixture", "attachments": []}, "outcome": "PENDING_RELEVANCE", "reason_code": "MEDIA_RELEVANCE_UNRESOLVED", "expires_at": p.now(), "next_retry_at": p.now()}
        db.execute("INSERT INTO pending_candidates VALUES(?,?,?)", (candidate["id"], source["id"], p.encode(candidate)))
    identity = tmp_path / "identity.json"
    p.write_json(identity, {"replacements": {"fixture-owner": "collector-account-001", "fixture-owner-name": "self", "fixture-native-account": "self"}})
    policy = tmp_path / "policy.json"
    p.write_json(policy, {"files": {relative: {"action": "include", "reason": "Synthetic fixture"}}})
    output = tmp_path / "dataset"
    p.export_dataset(snapshot, identity, policy, output, "v-test")
    return output


def test_selected_export_keeps_occurrences_and_native_precision(exported):
    report = p.verify_dataset(exported)
    assert report["counts"]["source_events"] == 2
    assert report["counts"]["unique_blobs"] == 1
    assert report["counts"]["saved_attachment_occurrences"] == 2
    with sqlite3.connect(exported / "workbench.sqlite3") as db:
        all_data = "\n".join(r[0] for r in db.execute("SELECT data FROM records UNION ALL SELECT data FROM revisions"))
        assert "fixture-owner" not in all_data
        assert "fixture-private-reference" not in all_data
        assert "deleted body fixture" not in all_data
        assert '"cursor"' not in all_data
        assert db.execute("SELECT COUNT(*) FROM records WHERE kind='background_jobs'").fetchone()[0] == 0
        material = json.loads(db.execute("SELECT data FROM records WHERE kind='materials' LIMIT 1").fetchone()[0])
        assert material["native_id"] == "18446744073709551615"
        candidate = json.loads(db.execute("SELECT data FROM pending_candidates").fetchone()[0])
        assert candidate["expires_at"] is None and candidate["next_retry_at"] is None
        assert candidate["item"]["text"] == "Unresolved fixture"


def test_repeat_import_preserves_user_changes_and_refuses_other_data(exported, tmp_path):
    target = tmp_path / "instance"
    assert p.import_dataset(exported, target)["status"] == "imported"
    user_file = target / "user-note.txt"
    user_file.write_text("Keep this local edit", encoding="utf-8")
    assert p.import_dataset(exported, target)["status"] == "already_imported"
    assert user_file.read_text() == "Keep this local edit"
    other = tmp_path / "other"
    other.mkdir()
    (other / "existing.txt").write_text("preserve")
    with pytest.raises(ValueError, match="contains data"):
        p.import_dataset(exported, other)


def test_tampered_file_and_unlisted_file_rejected(exported):
    extra = exported / "extra.txt"
    extra.write_text("unlisted")
    with pytest.raises(ValueError, match="Unlisted"):
        p.verify_dataset(exported)
    extra.unlink()
    blob = next(p for p in (exported / "blobs").rglob("*") if p.is_file())
    blob.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="integrity"):
        p.verify_dataset(exported)


def test_zip_import_and_archive_path_traversal(exported, tmp_path):
    archive = tmp_path / "dataset.zip"
    p.pack_dataset(exported, archive)
    assert p.verify_dataset(archive)["status"] == "verified"
    assert p.import_dataset(archive, tmp_path / "from-zip")["status"] == "imported"
    malicious = tmp_path / "bad.zip"
    with zipfile.ZipFile(malicious, "w") as output:
        output.writestr("../outside.txt", "do not extract")
    with pytest.raises(ValueError, match="Unsafe"):
        p.unpack_archive(malicious, tmp_path / "bad-output")
    assert not (tmp_path / "outside.txt").exists()


def test_consistent_application_backup_restores_to_fresh_root(exported, tmp_path):
    from backend.store import Store
    instance = tmp_path / "instance"
    p.import_dataset(exported, instance)
    store = Store(instance)
    product = store.get("products", "product-1")
    store.put("products", {**product, "notes": "A receiving user's later edit"})
    archive = store.backup()
    with zipfile.ZipFile(archive, "a", zipfile.ZIP_DEFLATED) as output:
        output.writestr(p.MARKER, (instance / p.MARKER).read_bytes())
    restored = tmp_path / "restored"
    assert p.restore_backup(archive, restored)["status"] == "restored"
    assert Store(restored).get("products", "product-1")["notes"] == "A receiving user's later edit"
    with pytest.raises(ValueError, match="never overwrites"):
        p.restore_backup(archive, instance)


def test_windows_input_paths_and_png_derivative_metadata(exported, tmp_path):
    from PIL import Image
    snapshot = tmp_path / "snapshot"
    with sqlite3.connect(snapshot / "workbench.sqlite3") as db:
        for kind, ident, data in db.execute("SELECT kind,id,data FROM records WHERE kind IN ('attachments','materials')").fetchall():
            value = json.loads(data)
            assets = value.get("attachments", []) if kind == "materials" else [value]
            for asset in assets:
                asset.update(path=asset["path"].replace("/", "\\"), mime="image/jpeg", name="poster.jpg")
            db.execute("UPDATE records SET data=? WHERE kind=? AND id=?", (p.encode(value), kind, ident))
            db.execute("UPDATE revisions SET data=? WHERE kind=? AND id=?", (p.encode(value), kind, ident))
    derivative = tmp_path / "derivative.png"
    Image.new("RGB", (2, 3), "white").save(derivative)
    policy = p.read_json(tmp_path / "policy.json")
    for review in policy["files"].values():
        review.update(action="replace", replacement_path=str(derivative), reason="Synthetic metadata test")
    p.write_json(tmp_path / "policy.json", policy)
    output = tmp_path / "derivative-dataset"
    p.export_dataset(snapshot, tmp_path / "identity.json", tmp_path / "policy.json", output, "v-test-derivative")
    with sqlite3.connect(output / "workbench.sqlite3") as db:
        asset = json.loads(db.execute("SELECT data FROM records WHERE kind='attachments' LIMIT 1").fetchone()[0])
        assert asset["name"] == "poster.sanitized.png"
        assert asset["original_name"] == "poster.jpg"
        assert asset["file_type"] == "png" and asset["mime"] == "image/png"
        assert (asset["width"], asset["height"]) == (2, 3)
        assert asset["original_verified"] is False
        assert "\\" not in asset["path"]
