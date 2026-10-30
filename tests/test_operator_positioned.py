"""Isolated native-session integration fixtures, never live WeChat proof."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
import time
from types import SimpleNamespace

from fastapi.testclient import TestClient
from PIL import Image
import pytest

from backend.collectors import CollectorBlocked
from backend.store import Store


def picture(path, color="blue"):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (32, 32), color).save(path)
    return str(path)


def wait_record(module, kind, ident, active):
    for _ in range(150):
        record = module.store.get(kind, ident)
        if record["state"] not in active:
            return record
        time.sleep(.01)
    pytest.fail(f"fixture {kind} did not settle")


@pytest.fixture
def native_client(tmp_path, monkeypatch):
    # Explicitly opt in only for the synthetic retained-pipeline regressions.
    monkeypatch.setenv("TRAVEL_ENABLE_FOREGROUND_COLLECTION", "1")
    from backend import app as module
    module.analysis_pool.shutdown(wait=True)
    module.wechat_pool.shutdown(wait=True)
    monkeypatch.setattr(module, "store", Store(tmp_path / "data"))
    monkeypatch.setattr(module, "analysis_pool", ThreadPoolExecutor(max_workers=1))
    monkeypatch.setattr(module, "wechat_pool", ThreadPoolExecutor(max_workers=1))
    control = {"pages": 2, "fetches": 0, "resumed_checkpoints": []}

    def establish(source, account, options, staging):
        control["establish_calls"] = control.get("establish_calls", 0) + 1
        if control.get("establish_error"):
            raise control["establish_error"]
        assert options["operator_acknowledged"] is True
        return {"binding": {"fixture_only": True, "source_id": source["id"]},
                "evidence": {"preview_path": picture(staging / "session.png"), "geometry": {"width": 32, "height": 32}},
                "capabilities": {"status": "NOT_TESTED", "reason": "离线夹具"}}

    class Adapter:
        def __init__(self, session, staging):
            self.session, self.staging = session, staging

        def resolve_source(self, source, account):
            assert source["id"] == self.session["source_id"]

        def iterate_items(self, source, scope, checkpoint):
            if checkpoint:
                control["resumed_checkpoints"].append(checkpoint)
            start = checkpoint["page_index"] + 1 if checkpoint else 0
            for index in range(start, control["pages"]):
                if control.get("mismatch_after_first") and index == 1:
                    raise CollectorBlocked("所选来源已改变，采集已暂停。", "SOURCE_MISMATCH")
                yield {"observations": [{"capture_path": picture(self.staging / f"page-{index}.png", "green"),
                           "parse_state": "UNPARSED", "raw_text": "离线页面夹具", "source_time_raw": None}],
                       "items": [], "attachments": [{"name": f"fixture-{index}.jpg", "type": "image", "mime": "image/jpeg",
                           "quality": "unknown", "state": "PENDING", "observation_index": 0, "record_index": None,
                           "media_index": 0, "association_state": "UNRESOLVED",
                           "retrieval_reference": {"fixture_only": True, "page_index": index, "source_id": source["id"]}}],
                       "checkpoint": {"page_index": index, "anchor": f"fixture-anchor-{index}"},
                       "coverage": "ACCESSIBLE_END_REACHED" if control.get("false_endpoint") else "PARTIAL_WITH_GAPS",
                       "terminal": index == control["pages"] - 1, "stop_reason": "离线夹具页数已到达，未证明终点。"}

        def fetch_attachment(self, reference, destination):
            control["fetches"] += 1
            # Discovery and its retry record must already be committed.
            job = module.store.all("jobs")[0]
            assert job["checkpoint"]["page_index"] >= reference["page_index"]
            assert module.store.all("page_observations")
            assert any(a.get("state") in {"PENDING", "RETRY"} for a in module.store.all("attachments"))
            if control.get("fail_first_media") and reference["page_index"] == 0:
                return {"state": "RETRY", "reason": "离线夹具：文件暂不可用。"}
            if control.get("pause_on_fetch"):
                module.store.put("jobs", {**job, "state": "PAUSING"})
                control["pause_on_fetch"] = False
            if control.get("disable_on_fetch"):
                monkeypatch.delenv("TRAVEL_ENABLE_FOREGROUND_COLLECTION", raising=False)
            return {"state": "SAVED", "path": picture(destination.with_suffix(".jpg"), "red"), "quality": "client_saved", "mime": "image/jpeg"}

    monkeypatch.setitem(sys.modules, "backend.collectors.operator_positioned", SimpleNamespace(
        establish_session=establish, make_adapter=lambda session, staging: Adapter(session, staging)))
    with TestClient(module.app) as client:
        account = client.post("/api/accounts", json={"display_name": "夹具账号", "identity_evidence": "离线夹具"}).json()
        source = client.post("/api/sources", json={"account_id": account["id"], "kind": "group", "display_name": "夹具群", "identity_evidence": "离线夹具来源"}).json()
        yield client, module, source, control
    module.wechat_pool.shutdown(wait=True)
    module.analysis_pool.shutdown(wait=True)


def establish(client, module, source):
    staged = client.post("/api/native-sessions", json={"source_id": source["id"], "page_budget": 3})
    assert staged.status_code == 200, staged.text
    session = staged.json()
    queued = client.post(f"/api/native-sessions/{session['id']}/establish", json={"operator_acknowledged": True, "start_delay_seconds": 0})
    assert queued.status_code == 200, queued.text
    return wait_record(module, "native_sessions", session["id"], {"QUEUED", "ESTABLISHING"})


def scan(client, module, source, session):
    result = client.post("/api/scans", json={"source_ids": [source["id"]], "mode": "ALL_ACCESSIBLE",
        "acquisition_mode": "operator_positioned", "session_id": session["id"], "page_budget": 3, "start_delay_seconds": 0})
    assert result.status_code == 200, result.text
    return wait_record(module, "jobs", result.json()["jobs"][0]["id"], {"QUEUED", "RUNNING", "PAUSING"})


def test_staging_is_not_acquisition_and_requires_operator_acknowledgement(native_client):
    client, module, source, control = native_client
    session = client.post("/api/native-sessions", json={"source_id": source["id"], "page_budget": 2}).json()
    assert session["state"] == "STAGED"
    assert not module.store.all("attachments") and not module.store.all("page_observations")
    assert client.post(f"/api/native-sessions/{session['id']}/establish", json={}).status_code == 422
    ready = establish(client, module, source)
    assert ready["state"] == "READY" and ready["identity_scope"] == "session"
    assert client.get(ready["preview_url"]).content.startswith(b"\x89PNG")
    assert not module.store.all("materials")
    changed = module.store.get("sources", source["id"])
    module.store.put("sources", {**changed, "identity_evidence": "changed identity"})
    response = client.post("/api/scans", json={"source_ids": [source["id"]], "mode": "ALL_ACCESSIBLE", "acquisition_mode": "operator_positioned", "session_id": ready["id"]})
    assert response.status_code == 409
    assert module.store.get("native_sessions", ready["id"])["state"] == "EXPIRED"


def test_page_observations_media_counts_and_checkpoint_are_separate(native_client):
    client, module, source, control = native_client
    manual = module.store.put("materials", {"source_id": source["id"], "acquisition_method": "assistant_native_ui_manual", "text": "旧人工证据", "attachments": []})
    session = establish(client, module, source)
    job = scan(client, module, source, session)
    assert job["state"] == "PARTIAL"
    assert {key: job["counts"][key] for key in ("page_observations", "parsed_records", "acquired_attachments", "unresolved_associations")} == {
        "page_observations": 2, "parsed_records": 0, "acquired_attachments": 2, "unresolved_associations": 2}
    assert module.store.get("materials", manual["id"]) == manual
    assert not module.store.get("checkpoints", source["id"])
    checkpoint = module.store.get("checkpoints", f"operator_positioned:{session['id']}")
    assert checkpoint["last_cutoff"] is None and checkpoint["cursor"]["page_index"] == 1
    assert control["fetches"] == 2
    observations = module.store.all("page_observations")
    assert all(len(o["attachments"]) == 2 for o in observations)
    for observation in observations:
        assert client.get(f"/api/page-observations/{observation['id']}").status_code == 200
        assert all(client.get(a["url"]).status_code == 200 for a in observation["attachments"])
    restored = module.store.restore_test(module.store.backup())
    restored_store = Store(Path(restored["path"]))
    assert len(restored_store.all("page_observations")) == 2
    assert restored_store.validate_references()


def test_source_mismatch_invalidates_session_and_rebinding_preserves_anchor(native_client):
    client, module, source, control = native_client
    control["mismatch_after_first"] = True
    session = establish(client, module, source)
    job = scan(client, module, source, session)
    assert job["state"] == "NEEDS_USER_ACTION" and job["stop_code"] == "SOURCE_MISMATCH"
    assert job["counts"]["page_observations"] == 1
    assert module.store.get("native_sessions", session["id"])["state"] == "EXPIRED"
    assert client.post(f"/api/jobs/{job['id']}/resume", json={"start_delay_seconds": 0}).status_code == 409
    control["mismatch_after_first"] = False
    replacement = establish(client, module, source)
    response = client.post(f"/api/jobs/{job['id']}/resume", json={"session_id": replacement["id"], "start_delay_seconds": 0})
    assert response.status_code == 200
    resumed = wait_record(module, "jobs", job["id"], {"QUEUED", "RUNNING"})
    assert control["resumed_checkpoints"][-1] == job["checkpoint"]
    assert resumed["counts"]["page_observations"] == 2
    assert resumed["scope"]["upper"] == job["scope"]["upper"]


def test_pause_preserves_media_and_resume_uses_committed_anchor(native_client):
    client, module, source, control = native_client
    control["pause_on_fetch"] = True
    session = establish(client, module, source)
    job = scan(client, module, source, session)
    assert job["state"] == "PAUSED"
    assert job["counts"]["page_observations"] == job["counts"]["acquired_attachments"] == 1
    assert client.post(f"/api/jobs/{job['id']}/resume", json={"start_delay_seconds": 0}).status_code == 200
    resumed = wait_record(module, "jobs", job["id"], {"QUEUED", "RUNNING"})
    assert resumed["counts"]["page_observations"] == 2 and resumed["counts"]["acquired_attachments"] == 2


def test_failed_media_retries_after_discovery_finishes_without_rescanning(native_client):
    client, module, source, control = native_client
    control["fail_first_media"] = True
    session = establish(client, module, source)
    job = scan(client, module, source, session)
    assert job["counts"]["page_observations"] == 2 and job["counts"]["acquired_attachments"] == 1
    assert job["counts"]["media_failures"] == 1
    old_checkpoint = job["checkpoint"]
    control["fail_first_media"] = False
    response = client.post(f"/api/jobs/{job['id']}/retry", json={"start_delay_seconds": 0})
    assert response.status_code == 200
    finished = wait_record(module, "jobs", job["id"], {"QUEUED", "RUNNING"})
    assert finished["counts"]["page_observations"] == 2
    assert finished["counts"]["acquired_attachments"] == 2 and finished["counts"]["media_failures"] == 0
    assert finished["checkpoint"] == old_checkpoint


def test_engineering_gap_and_unsupported_completion_claim_are_truthful(native_client):
    client, module, source, control = native_client
    control["establish_error"] = CollectorBlocked("本地文字识别组件尚未完成适配。", "OCR_UNAVAILABLE")
    session = establish(client, module, source)
    assert session["state"] == "COMPATIBILITY_BLOCKED"
    control.pop("establish_error")
    control["false_endpoint"] = True
    session = establish(client, module, source)
    job = scan(client, module, source, session)
    assert job["state"] == "PARTIAL" and job["coverage"] == "PARTIAL_WITH_GAPS"


def test_native_page_transaction_rejects_unowned_files_and_invalid_links(tmp_path):
    store = Store(tmp_path / "data")
    source = {"id": "source", "account_id": "account", "display_name": "离线夹具"}
    session = {"id": "session"}
    job = store.put("jobs", {"state": "RUNNING", "counts": {}})
    staging = store.root / "staging"
    outside = picture(tmp_path / "outside.png")
    with pytest.raises(ValueError):
        store.ingest_native_page(source, {"observations": [{"capture_path": outside}], "checkpoint": {"bad": True}}, job, session, staging)
    capture = picture(staging / "capture.png")
    with pytest.raises(ValueError):
        store.ingest_native_page(source, {"observations": [{"capture_path": capture}],
            "attachments": [{"state": "PENDING", "observation_index": 9}], "checkpoint": {"bad": True}}, job, session, staging)
    assert not store.all("page_observations") and not store.all("attachments") and not store.all("checkpoints")
    assert store.get("jobs", job["id"])["counts"] == {}


def test_restart_expires_native_binding_without_losing_job_anchor(tmp_path):
    store = Store(tmp_path)
    session = store.put("native_sessions", {"state": "READY", "binding": {"fixture_only": True}})
    job = store.put("jobs", {"state": "RUNNING", "session_id": session["id"], "checkpoint": {"anchor": "fixture"}})
    store.recover()
    assert store.get("native_sessions", session["id"])["state"] == "EXPIRED"
    assert store.get("jobs", job["id"])["state"] == "PAUSED"
    assert store.get("jobs", job["id"])["checkpoint"] == {"anchor": "fixture"}


def test_foreground_gate_blocks_new_and_queued_routes_before_adapter_use(native_client, monkeypatch):
    client, module, source, control = native_client
    monkeypatch.delenv("TRAVEL_ENABLE_FOREGROUND_COLLECTION", raising=False)
    import backend.collectors as collectors
    real_get_adapter = collectors.get_adapter

    def guarded_factory(kind, *args, **kwargs):
        assert kind == "upload", "disabled foreground adapter was constructed"
        return real_get_adapter(kind, *args, **kwargs)

    monkeypatch.setattr(collectors, "get_adapter", guarded_factory)
    monkeypatch.setattr(module.wechat_pool, "submit", lambda *args, **kwargs: pytest.fail("disabled foreground work was queued"))
    session = module.store.put("native_sessions", {"state": "QUEUED", "source_id": source["id"], "binding": {"fixture": True}})
    for endpoint, payload in (("/api/native-sessions", {"source_id": source["id"]}),
                              (f"/api/native-sessions/{session['id']}/establish", {"operator_acknowledged": True}),
                              ("/api/scans", {"source_ids": [source["id"]], "mode": "ALL_ACCESSIBLE"}),
                              ("/api/scans", {"source_ids": [source["id"]], "mode": "ALL_ACCESSIBLE", "acquisition_mode": "operator_positioned"})):
        response = client.post(endpoint, json=payload)
        assert response.status_code == 409
        assert response.json()["stop_code"] == "FOREGROUND_COLLECTION_DISABLED"
        assert "前台微信采集已停用" in response.json()["detail"]
        assert "后台同步" in response.json()["detail"]
    module.establish_native_session(session["id"])
    assert module.store.get("native_sessions", session["id"])["state"] == "COMPATIBILITY_BLOCKED"
    for mode in ("unattended", "operator_positioned"):
        job = module.store.put("jobs", {"state": "QUEUED", "source_id": source["id"], "acquisition_mode": mode,
            "checkpoint": {"anchor": "preserve"}, "counts": {}, "coverage": "UNKNOWN"})
        module.run_scan(job["id"])
        blocked = module.store.get("jobs", job["id"])
        assert blocked["state"] == "COMPATIBILITY_BLOCKED" and blocked["stop_code"] == "FOREGROUND_COLLECTION_DISABLED"
        assert blocked["checkpoint"] == {"anchor": "preserve"}
        for action in ("resume", "retry"):
            assert client.post(f"/api/jobs/{job['id']}/{action}", json={}).status_code == 409
    state = client.get("/api/state").json()
    assert state["settings"]["foreground_collection_enabled"] is False
    assert state["capabilities"]["upload"]["available"] is True
    assert all(state["capabilities"][kind]["code"] == "FOREGROUND_COLLECTION_DISABLED" for kind in ("group", "moments"))
    assert control.get("establish_calls", 0) == control["fetches"] == 0
    assert not module.store.all("materials") and not module.store.all("page_observations")


def test_foreground_gate_stops_next_page_and_preserves_committed_bytes(native_client):
    client, module, source, control = native_client
    session = establish(client, module, source)
    control["disable_on_fetch"] = True
    job = scan(client, module, source, session)
    assert job["state"] == "COMPATIBILITY_BLOCKED"
    assert job["stop_code"] == "FOREGROUND_COLLECTION_DISABLED"
    assert job["counts"]["page_observations"] == job["counts"]["acquired_attachments"] == 1
    assert job["checkpoint"]["page_index"] == 0 and control["fetches"] == 1
