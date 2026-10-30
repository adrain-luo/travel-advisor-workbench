"""Isolated fixture tests. These do not prove live WeChat or AI compatibility."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import threading
import time
import zipfile

import pytest
from fastapi.testclient import TestClient

from backend.store import Store


@pytest.fixture
def client(tmp_path, monkeypatch):
    # Retained collector fixtures opt in; production defaults remain disabled.
    monkeypatch.setenv("TRAVEL_ENABLE_FOREGROUND_COLLECTION", "1")
    from backend import app as module
    module.analysis_pool.shutdown(wait=True)
    module.wechat_pool.shutdown(wait=True)
    monkeypatch.setattr(module, "store", Store(tmp_path / "data"))
    monkeypatch.setattr(module, "analysis_pool", ThreadPoolExecutor(max_workers=2))
    monkeypatch.setattr(module, "wechat_pool", ThreadPoolExecutor(max_workers=1))
    with TestClient(module.app) as test_client:
        yield test_client
    module.analysis_pool.shutdown(wait=True)
    module.wechat_pool.shutdown(wait=True)


def product_payload(source_id=None):
    return {"title": "测试夹具·云南五日游", "supplier": "测试供应商", "destination": "云南", "departure_city": "上海", "duration_days": 5,
            "shopping": "none", "source_item_ids": [source_id] if source_id else [],
            "offers": [{"price": 3000, "price_kind": "exact", "currency": "CNY", "unit": "per_person", "traveler": "adult", "occupancy": "双人间",
                        "departure_date": "2026-11-02", "extras": [], "transport_included": True}]}


def wait_analysis(client, material_id):
    for _ in range(60):
        material = client.get(f"/api/materials/{material_id}").json()
        if material["state"] not in {"ANALYZING", "PENDING_EXTRACTION"}:
            return material
        time.sleep(.025)
    pytest.fail("analysis did not settle")


def test_offline_upload_product_case_export_restart_and_restore(client):
    from backend import app as module
    response = client.post("/api/uploads", files=[("files", ("fixture.txt", "测试夹具：云南纯玩五日，成人双人间 3000 元。".encode(), "text/plain"))])
    assert response.status_code == 200, response.text
    material = wait_analysis(client, response.json()["materials"][0]["id"])
    assert material["state"] == "NEEDS_CONFIGURATION"
    assert material["source_time"] is None
    assert "云南" in material["extracted_text"]
    raw = client.get(material["attachments"][0]["url"])
    assert raw.status_code == 200
    product = client.post("/api/products", json=product_payload(material["id"])).json()
    req = {"destination": "云南", "shopping": "none", "budget": 3500, "budget_unit": "per_person", "date_start": "2026-11-01", "date_end": "2026-11-05"}
    candidates = client.post("/api/match", json={"requirements": req}).json()
    assert candidates["matched"][0]["product"]["id"] == product["id"]
    case = client.post("/api/cases", json={"name": "测试接待", "requirements": req}).json()
    rec = client.post("/api/recommendations", json={"case_id": case["id"], "product_ids": [product["id"]]}).json()
    exported_response = client.post(f"/api/recommendations/{rec['id']}/export")
    assert exported_response.status_code == 200, exported_response.text
    exported = exported_response.json()
    assert client.get(exported["image_url"]).content.startswith(b"\x89PNG")
    text = client.get(exported["text_url"]).text
    assert text == rec["text"]
    assert "3000" in text and "2026-11-02" in text
    client.put(f"/api/products/{product['id']}", json={"title": "修改后的夹具产品"})
    state = client.get("/api/state").json()
    assert state["recommendations"][0]["stale"] is True
    assert state["recommendations"][0]["status"] == "PREPARED"
    assert client.get(exported["text_url"]).text == text
    reopened = Store(module.store.root)
    assert reopened.get("products", product["id"])["title"] == "修改后的夹具产品"
    weekly = client.post("/api/weekly", json={"product_ids": [product["id"]], "title": "测试夹具周报"}).json()
    weekly_export = client.post(f"/api/weekly/{weekly['id']}/export").json()
    assert "测试夹具周报" in client.get(weekly_export["text_url"]).text
    backup = client.post("/api/backup").json()
    restored = client.post("/api/restore", json={"path": backup["path"]})
    assert restored.status_code == 200, restored.text
    assert restored.json()["counts"]["products"] == 1
    assert restored.json()["counts"]["materials"] == 1
    with zipfile.ZipFile(backup["path"]) as archive:
        assert "credential.dpapi" not in archive.namelist()


def test_blob_dedup_keeps_occurrences(client):
    payload = b"fixture only"
    for _ in range(2):
        assert client.post("/api/uploads", files={"files": ("fixture.txt", payload, "text/plain")}).status_code == 200
    from backend import app as module
    module.analysis_pool.shutdown(wait=True)
    assert len(module.store.all("materials")) == 2
    assert len(list((module.store.root / "blobs").rglob("*"))) == 2  # one prefix directory and one blob


def test_recommendation_freezes_publication_evidence_not_import_time(client):
    from backend import app as module
    material = module.store.put("materials", {"text": "fixture", "source_id": "fixture-source",
        "source_time_raw": "昨天09:07", "observed_at": "2026-10-25",
        "observation_time_precision": "day", "time_evidence": {"status": "parsed", "precision": "minute",
        "start": "2026-10-24T09:07:00+08:00", "end": "2026-10-24T09:08:00+08:00"}})
    module.store.put("sources", {"display_name": "夹具来源", "kind": "moments"}, "fixture-source")
    product = client.post("/api/products", json=product_payload(material["id"])).json()
    rec = client.post("/api/recommendations", json={"product_ids": [product["id"]]}).json()
    frozen = rec["product_snapshots"][0]["source_snapshots"][0]
    assert frozen["source_time_raw"] == "昨天09:07"
    assert frozen["observed_at"] == "2026-10-25"
    assert frozen["source_name"] == "夹具来源"
    module.store.put("materials", {**material, "source_time_raw": "已更正"})
    assert module.store.get("recommendations", rec["id"])["product_snapshots"][0]["source_snapshots"][0] == frozen
    weekly = client.post("/api/weekly", json={"product_ids": [product["id"]]}).json()
    assert weekly["product_snapshots"][0]["source_snapshots"][0]["source_time_raw"] == "已更正"


def test_weekly_freezes_business_date_and_readable_source_evidence(client, monkeypatch):
    from backend import app as module

    module.store.put("sources", {"display_name": "夹具朋友圈联系人", "kind": "moments"}, "internal-source-identifier")
    material = module.store.put("materials", {"text": "fixture", "source_id": "internal-source-identifier",
        "source_time_raw": "昨天09:07", "observed_at": "2026-10-25", "observation_time_precision": "day",
        "time_evidence": {"status": "parsed", "precision": "minute", "timezone": "Asia/Shanghai",
                          "start": "2026-10-24T09:07:00+08:00"}}, "internal-material-identifier")
    product = client.post("/api/products", json=product_payload(material["id"])).json()
    monkeypatch.setattr(module, "utcnow", lambda: "2026-10-25T16:45:12+00:00")
    weekly = client.post("/api/weekly", json={"product_ids": [product["id"]], "title": "夹具周报"}).json()
    assert weekly["timezone"] == "Asia/Shanghai"
    assert weekly["information_date"] == "2026-10-26 00:45"
    assert weekly["reviewed_at"] == "2026-10-25T16:45:12+00:00"

    # Later edits and timezone changes must not rewrite a reviewed collection.
    module.store.put("materials", {**material, "source_time_raw": "后续更正内容"})
    client.put(f"/api/products/{product['id']}", json={"title": "后续修改标题"})
    client.put("/api/settings", json={"timezone": "UTC"})
    monkeypatch.setattr(module, "utcnow", lambda: "2030-01-01T00:00:00+00:00")
    outputs = []
    for _ in range(2):
        exported = client.post(f"/api/weekly/{weekly['id']}/export")
        assert exported.status_code == 200, exported.text
        outputs.append(client.get(exported.json()["text_url"]).text)
    assert outputs[0] == outputs[1]
    text = outputs[0]
    assert "资料整理时间：2026-10-26 00:45（中国标准时间）" in text
    assert "信息整理时间：2026-10-26 00:45" in text
    assert "夹具朋友圈联系人" in text and "原文“昨天09:07”" in text
    assert "观察日期 2026-10-25" in text and "对应 2026-10-24 09:07" in text
    for forbidden in ("internal-source-identifier", "internal-material-identifier", product["id"], product["updated_at"],
                      "2026-10-24T09:07:00", "来源素材：", "资料更新：", "后续更正内容", "后续修改标题", "2030-01-01"):
        assert forbidden not in text


def test_legacy_weekly_uses_saved_review_instant_and_preserves_recommendation_text(client):
    from backend import app as module

    product = {**product_payload("legacy-internal-material"), "updated_at": "2026-10-25T20:11:59+00:00",
               "source_time": "10月20日（年份未知）"}
    weekly = module.store.put("weekly", {"title": "旧版夹具周报", "product_snapshots": [product],
        "recommendation_snapshots": [{"text": "已保存的人工接待建议；信息整理时间：2026-10-20 08:00"}],
        "reviewed_at": "2026-10-25T16:45:12Z"})
    client.put("/api/settings", json={"timezone": "UTC"})
    exported = client.post(f"/api/weekly/{weekly['id']}/export")
    assert exported.status_code == 200, exported.text
    text = client.get(exported.json()["text_url"]).text
    assert "资料整理时间：2026-10-26 00:45（中国标准时间）" in text
    assert "资料更新时间：10月20日（年份未知）" in text
    assert "已保存的人工接待建议；信息整理时间：2026-10-20 08:00" in text
    assert "legacy-internal-material" not in text and product["updated_at"] not in text
    current = module.store.get("weekly", weekly["id"])
    assert current["information_date"] == "2026-10-26 00:45"
    assert current["timezone"] == "Asia/Shanghai"
    assert current["product_snapshots"] == [product]


def test_legacy_weekly_with_unknown_review_date_does_not_invent_current_date(client):
    from backend import app as module

    weekly = module.store.put("weekly", {"title": "整理时间缺失的夹具周报",
        "product_snapshots": [{"title": "时间待确认产品", "source_item_ids": ["private-source-id"]}]})
    exported = client.post(f"/api/weekly/{weekly['id']}/export")
    assert exported.status_code == 200, exported.text
    text = client.get(exported.json()["text_url"]).text
    assert "资料整理时间：未知（旧记录未保存可确认的整理时间）" in text
    assert "信息整理时间：未知（旧记录未保存可确认的整理时间）" in text
    assert "资料更新时间：来源时间未知" in text
    assert "private-source-id" not in text


def test_scans_block_honestly_and_preserve_scope(client):
    account = client.post("/api/accounts", json={"display_name": "fixture account", "identity_evidence": "fixture only, not live"}).json()
    source = client.post("/api/sources", json={"account_id": account["id"], "kind": "moments", "display_name": "fixture contact", "identity_evidence": "fixture identity"}).json()
    response = client.post("/api/scans", json={"source_ids": [source["id"]], "mode": "SINCE", "start": "2026-01-01"})
    assert response.status_code == 200, response.text
    from backend import app as module
    for _ in range(100):
        job = module.store.all("jobs")[0]
        if job["state"] == "COMPATIBILITY_BLOCKED":
            break
        time.sleep(.02)
    assert job["state"] == "COMPATIBILITY_BLOCKED"
    assert job["coverage"] == "UNKNOWN"
    assert job["counts"]["discovered"] == 0
    assert job["requested_start"].endswith("00:00:00+08:00")
    assert client.get("/api/state").json()["materials"] == []


def test_cross_origin_mutation_rejected(client):
    response = client.post("/api/paste", json={"text": "do not write"}, headers={"Origin": "https://unrelated.example"})
    assert response.status_code == 403


def test_source_event_revision_and_checkpoint_atomicity(tmp_path):
    store = Store(tmp_path)
    source = {"account_id": "a", "id": "s"}
    job = store.put("jobs", {"state": "RUNNING", "counts": {"discovered": 0}})
    item = {"type": "text", "text": "fixture", "event_key": "verified-event", "identity_verified": True, "attachments": [{"name": "late.pdf"}]}
    assert len(store.ingest_page(source, [item], {"cursor": 1}, job)) == 1
    assert len(store.ingest_page(source, [{**item, "observed_at": "later"}], {"cursor": 2}, job)) == 0
    assert len(store.ingest_page(source, [{**item, "text": "corrected"}], {"cursor": 3}, job)) == 1
    assert len(store.all("materials")) == 2
    assert store.get("checkpoints", "s")["last_cutoff"] is None
    assert len(store.all("attachments")) == 2
    assert all(a["state"] == "PENDING" for a in store.all("attachments"))
    # Distinct source identities preserve the same material's provenance.
    store.ingest_page({"account_id": "a", "id": "s2"}, [item], {}, job)
    assert len(store.all("materials")) == 3
    store.recover()
    assert store.get("jobs", job["id"])["state"] == "PAUSED"


def test_restore_rejects_tampering(tmp_path):
    store = Store(tmp_path)
    store.put("products", {"title": "fixture"})
    archive = store.backup()
    with zipfile.ZipFile(archive, "a") as file:
        file.writestr("workbench.sqlite3", b"tampered")
    with pytest.raises(ValueError):
        store.restore_test(archive)


def test_incompatible_product_cannot_be_silently_recommended(client):
    product = client.post("/api/products", json=product_payload()).json()
    response = client.post("/api/recommendations", json={"product_ids": [product["id"]], "requirements": {"destination": "北京"}})
    assert response.status_code == 422


def test_human_product_survives_reanalysis(client):
    material = client.post("/api/paste", json={"text": "Fixture only: original supplier text"}).json()
    wait_analysis(client, material["id"])
    product = client.post("/api/products", json=product_payload(material["id"])).json()
    client.put(f"/api/products/{product['id']}", json={"title": "人工修正保留"})
    client.post(f"/api/materials/{material['id']}/analyze")
    from backend import app as module
    module.analysis_pool.shutdown(wait=True)
    assert module.store.get("products", product["id"])["title"] == "人工修正保留"
    assert len(module.store.versions("products", product["id"])) == 2


def test_late_media_requests_another_analysis_after_running_attempt(client, monkeypatch):
    """A fixture blocks the first analysis while an independent download finishes."""
    from backend import app as module
    from backend import extraction

    first_started = threading.Event()
    allow_first_finish = threading.Event()
    analyzed_texts = []

    def fixture_analysis(material, settings, api_key):
        analyzed_texts.append(material["text"])
        if len(analyzed_texts) == 1:
            first_started.set()
            assert allow_first_finish.wait(3), "fixture analysis release timed out"
        return {"status": "ANALYZED", "products": [], "issues": []}

    monkeypatch.setattr(extraction, "analyze_material", fixture_analysis)
    source = {"id": "fixture-source", "account_id": "fixture-account"}
    job = module.store.put("jobs", {"state": "RUNNING"})
    pending = {"id": "fixture-late-media", "name": "late.txt", "state": "PENDING", "attempts": 0,
               "source_id": source["id"], "retrieval_reference": {"fixture": True}}
    material = module.store.put("materials", {"source_id": source["id"], "text": "Initial fixture text",
                                               "state": "PENDING_EXTRACTION", "attachments": [pending], "extractions": []})
    module.store.put("attachments", {**pending, "material_id": material["id"]})

    class FixtureLateMediaAdapter:
        def fetch_attachment(self, reference, destination):
            destination.write_text("Late fixture document content", encoding="utf-8")
            return {"state": "SAVED", "quality": "original", "path": str(destination)}

    module.queue_analysis(material["id"])
    try:
        assert first_started.wait(3)
        module.retrieve_media(FixtureLateMediaAdapter(), source, job["id"])
        assert module.store.get("attachments", pending["id"])["state"] == "SAVED"
    finally:
        allow_first_finish.set()
    for _ in range(160):
        with module.analysis_lock:
            active = material["id"] in module.analysis_ids
        if not active:
            break
        time.sleep(.025)
    assert not active, "dirty analysis did not finish"
    current = module.store.get("materials", material["id"])
    assert len(analyzed_texts) == 2
    assert "Late fixture document content" not in analyzed_texts[0]
    assert "Late fixture document content" in analyzed_texts[1]
    assert "Late fixture document content" in current["extracted_text"]
    assert current["state"] == "ANALYZED" and len(current["extractions"]) == 2


def test_export_preserves_concurrent_edit_and_stale_flag(client, monkeypatch):
    from backend import app as module
    from backend import exports

    product = client.post("/api/products", json=product_payload()).json()
    recommendation = client.post("/api/recommendations", json={"product_ids": [product["id"]]}).json()
    old_text = recommendation["text"]

    def fixture_render(products, requirements, text, path):
        assert text == old_text
        module.edit_recommendation(recommendation["id"], {"text": "Concurrent operator edit"})
        module.flag_recommendations(product_id=product["id"])
        path.write_bytes(b"fixture image: rendering quality is not under test")

    monkeypatch.setattr(exports, "render_comparison", fixture_render)
    response = client.post(f"/api/recommendations/{recommendation['id']}/export")
    assert response.status_code == 200, response.text
    result = response.json()
    current = module.store.get("recommendations", recommendation["id"])
    stored_export = module.store.get("exports", result["id"])
    assert current["text"] == "Concurrent operator edit"
    assert current["stale"] is True
    assert result["current_version_changed"] is True
    assert result["recommendation_version"] == recommendation["version"]
    assert "image_url" not in current and "text_url" not in current
    assert stored_export["snapshot"]["text"] == old_text
    assert client.get(result["text_url"]).text.replace("\r\n", "\n") == old_text
    assert result["id"] in current["exports"]


def test_backup_waits_for_complete_upload_attachment_linkage(client, monkeypatch):
    """Pause between two writes and verify a concurrent snapshot sees both."""
    from backend import app as module

    material_inserted = threading.Event()
    finish_attachment_write = threading.Event()
    backup_entered = threading.Event()
    original_put = module.store.put

    def held_put(kind, data, ident=None, *, db=None):
        result = original_put(kind, data, ident, db=db)
        if kind == "materials" and data.get("attachments") and not material_inserted.is_set():
            material_inserted.set()
            assert finish_attachment_write.wait(3), "fixture upload release timed out"
        return result

    monkeypatch.setattr(module.store, "put", held_put)

    def concurrent_backup():
        backup_entered.set()
        return module.store.backup()

    with ThreadPoolExecutor(max_workers=2) as pool:
        uploading = pool.submit(client.post, "/api/uploads", files={"files": ("atomic.txt", b"atomic fixture", "text/plain")})
        try:
            assert material_inserted.wait(3)
            backing_up = pool.submit(concurrent_backup)
            assert backup_entered.wait(3)
            assert not backing_up.done(), "backup escaped the unfinished upload transaction"
        finally:
            finish_attachment_write.set()
        response = uploading.result(timeout=5)
        assert response.status_code == 200, response.text
        archive = backing_up.result(timeout=5)
    restored = module.store.restore_test(archive)
    restored_store = Store(Path(restored["path"]))
    assert restored["counts"]["materials"] == 1
    assert len(restored_store.all("attachments")) == 1
    assert restored_store.validate_references() is True
    material = restored_store.all("materials")[0]
    reference = material["attachments"][0]
    assert restored_store.get("attachments", reference["id"])["material_id"] == material["id"]


def test_failed_upload_linkage_rolls_back_material(client, monkeypatch):
    from backend import app as module

    original_put = module.store.put

    def fail_attachment_insert(kind, data, ident=None, *, db=None):
        if kind == "attachments":
            raise RuntimeError("fixture interrupted attachment registration")
        return original_put(kind, data, ident, db=db)

    monkeypatch.setattr(module.store, "put", fail_attachment_insert)
    with pytest.raises(RuntimeError, match="fixture interrupted"):
        client.post("/api/uploads", files={"files": ("interrupted.txt", b"fixture bytes", "text/plain")})
    assert module.store.all("materials") == []
    assert module.store.all("attachments") == []
    assert module.store.validate_references() is True


def saved_attachment_fixture(store):
    blob = store.save_blob(b"fixture original bytes")
    attachment = {**blob, "id": "fixture-attachment", "state": "SAVED", "name": "fixture.txt", "mime": "text/plain"}
    material = store.put("materials", {"text": "", "attachments": [attachment]})
    store.put("attachments", {**attachment, "material_id": material["id"]})
    return blob


def test_backup_rejects_missing_referenced_original(tmp_path):
    store = Store(tmp_path / "fixture-data")
    blob = saved_attachment_fixture(store)
    (store.root / blob["path"]).unlink()
    with pytest.raises(ValueError, match="原始文件缺失"):
        store.backup()


def test_restore_rejects_valid_archive_with_missing_database_reference(tmp_path):
    """ZIP/hash/SQLite integrity can pass while a database asset link is broken."""
    store = Store(tmp_path / "fixture-data")
    blob = saved_attachment_fixture(store)
    original_archive = store.backup()
    incomplete_archive = store.root / "backups" / "fixture-incomplete.zip"
    with zipfile.ZipFile(original_archive) as incoming, zipfile.ZipFile(incomplete_archive, "w") as outgoing:
        manifest = json.loads(incoming.read("manifest.json"))
        manifest["files"].pop(blob["path"])
        for name in manifest["files"]:
            outgoing.writestr(name, incoming.read(name))
        outgoing.writestr("manifest.json", json.dumps(manifest))
    with pytest.raises(ValueError, match="原始文件缺失"):
        store.restore_test(incomplete_archive)


def test_backup_shared_export_paths_preserves_occurrences_without_duplicate_members(tmp_path):
    import hashlib
    from PIL import Image

    store = Store(tmp_path / 'shared-exports')
    text_path = store.root / 'exports' / 'shared.txt'
    image_path = store.root / 'exports' / 'shared.png'
    text_path.write_text('共享的导出内容', encoding='utf-8')
    Image.new('RGB', (2, 2), 'white').save(image_path)
    shared = {'text_path': 'exports/shared.txt', 'image_path': 'exports/shared.png',
              'text_sha256': hashlib.sha256(text_path.read_bytes()).hexdigest(),
              'image_sha256': hashlib.sha256(image_path.read_bytes()).hexdigest()}
    store.put('exports', shared, 'first-occurrence')
    store.put('exports', shared, 'second-occurrence')
    backup = store.backup()
    with zipfile.ZipFile(backup) as archive:
        names = archive.namelist()
        assert len(names) == len(set(names))
        assert names.count('exports/shared.txt') == names.count('exports/shared.png') == 1
        manifest = json.loads(archive.read('manifest.json'))
        assert set(manifest['files']) == set(names) - {'manifest.json'}
    restored = store.restore_test(backup)
    restored_store = Store(Path(restored['path']))
    assert len(restored_store.all('exports')) == 2
    assert {r['text_path'] for r in restored_store.all('exports')} == {'exports/shared.txt'}
    assert restored_store.validate_references() is True
