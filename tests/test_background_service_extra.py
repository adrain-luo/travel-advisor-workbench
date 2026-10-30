"""Deterministic isolated regression checks for background mutation boundaries.

No application singleton, native adapter, WeChat process or business Store is used.
"""
import hashlib
import io
import threading

from PIL import Image
import pytest

from backend.background.service import BackgroundService, EXPECTED_ACCOUNT, EXPECTED_FRIEND
from backend.store import Store
from test_background_service import PRODUCT, complete_initial_history


class OfflineNative:
    def __init__(self):
        self.rows = []
        self.on_retrieve = None
        self.retrieval_error = None
        self.discovery_error = None
        self.discovery_calls = 0

    def bind(self):
        return {"account_native_id": EXPECTED_ACCOUNT, "friend_native_id": EXPECTED_FRIEND}

    def discover(self, kind, scope, cursor, limit):
        self.discovery_calls += 1
        if self.discovery_error:
            raise ValueError(self.discovery_error)
        return {"items": self.rows, "cursor": None, "snapshot_id": "offline-only",
                "exhausted": True, "observed_range": {}, "coverage": "UNKNOWN"}

    def retrieve(self, attachment, staging):
        if self.on_retrieve:
            self.on_retrieve(attachment)
        if self.retrieval_error:
            raise ValueError(self.retrieval_error)
        encoded = io.BytesIO()
        Image.new("RGB", (3, 4), "blue").save(encoded, format="PNG")
        path = staging / "isolated-fixture.png"
        path.write_bytes(encoded.getvalue())
        return {"state": "SAVED", "path": str(path), "mime": "image/png",
                "sha256": hashlib.sha256(encoded.getvalue()).hexdigest(), "quality": "fixture"}


def record(text="revision A", media=False):
    return {"event_key": "offline-event", "native_id": "offline-event",
            "native_revision": hashlib.sha256(text.encode()).hexdigest(),
            "author_id": EXPECTED_FRIEND, "identity_verified": True, "source_kind": "moments",
            "publication_time": "2025-06-01T12:00:00+08:00", "text": PRODUCT + text,
            "attachments": [{"native_id": "offline-media", "media_index": 0,
                "type": "image", "mime": "image/png", "name": "fixture.png",
                "private_ref": "offline-only"}] if media else []}


@pytest.fixture
def isolated(tmp_path):
    store = Store(tmp_path / "background-extra-isolated")
    adapter = OfflineNative()
    service = BackgroundService(store, adapter)
    service.bind()
    source = next(s for s in service.summary()["sources"] if s["kind"] == "moments")
    return store, adapter, service, source


@pytest.mark.parametrize("transition", ["RUNNING", "WAITING", "RETRY"])
def test_pause_between_worker_read_and_write_is_not_overwritten(isolated, monkeypatch, transition):
    store, adapter, service, source = isolated
    complete_initial_history(service, source)
    job = service.create_job({"source_id": source["id"], "mode": "continuous"})
    if transition == "RETRY":
        adapter.discovery_error = "OFFLINE_TEMPORARY_FAILURE"
    original_put = store.put
    reached = threading.Event()
    release = threading.Event()
    pause_finished = threading.Event()

    def pause_at_transition(kind, data, ident=None, **kwargs):
        if (not reached.is_set() and kind == "background_jobs" and data.get("id") == job["id"]
                and data.get("state") == transition):
            reached.set()
            assert release.wait(5), "Isolated worker barrier timed out"
        return original_put(kind, data, ident, **kwargs)

    monkeypatch.setattr(store, "put", pause_at_transition)
    worker = threading.Thread(target=service.run_once, args=(job["id"],))
    def pause():
        service.action(job["id"], "pause")
        pause_finished.set()
    requester = threading.Thread(target=pause)
    try:
        worker.start()
        assert reached.wait(5)
        requester.start()
        # With a correct transition lock, pause waits until the write commits.
        pause_finished.wait(0.2)
    finally:
        release.set()
        worker.join(5)
        if requester.ident is not None:
            requester.join(5)
    assert not worker.is_alive() and not requester.is_alive()
    assert pause_finished.is_set()
    assert store.get("background_jobs", job["id"])["state"] == "PAUSED"


def test_attachment_manual_correction_survives_inflight_download(isolated):
    store, adapter, service, source = isolated
    adapter.rows = [record(media=True)]
    history = service.create_job({"source_id": source["id"], "mode": "history"})
    service.run_once(history["id"])
    attachment = store.all("attachments")[0]
    adapter.on_retrieve = lambda asset: service.classify("attachments", asset["id"], {
        "label": "scenic_personal", "evidence": "Manual correction during offline download."})
    media = next(job for job in store.all("background_jobs") if job["mode"] == "media")
    service.run_once(media["id"])
    current = store.get("attachments", attachment["id"])
    assert current["media_state"] == "VALIDATED"
    assert current["classification"]["origin"] == "manual"
    assert current["classification"]["label"] == "scenic_personal"
    assert store.all("materials")[0]["attachments"][0]["classification"] == current["classification"]


def test_return_to_previously_seen_revision_updates_current_material(isolated):
    store, adapter, service, source = isolated
    complete_initial_history(service, source)
    job = service.create_job({"source_id": source["id"], "mode": "continuous"})
    for text in ("revision A", "revision B", "revision A"):
        adapter.rows = [record(text)]
        service.run_once(job["id"])
    assert len(store.all("materials")) == 1
    assert store.all("materials")[0]["text"] == record("revision A")["text"]


def test_account_change_during_media_blocks_job_without_success_cycle(isolated):
    store, adapter, service, source = isolated
    adapter.rows = [record(media=True)]
    history = service.create_job({"source_id": source["id"], "mode": "history"})
    service.run_once(history["id"])
    media = next(job for job in store.all("background_jobs") if job["mode"] == "media")
    adapter.retrieval_error = "ACCOUNT_OR_PROCESS_CHANGED"
    service.run_once(media["id"])
    current = store.get("background_jobs", media["id"])
    assert current["state"] == "BLOCKED"
    assert current["last_success_at"] is None
    assert service.summary()["binding"]["state"] == "BLOCKED"


def test_account_change_after_bind_invalidates_public_binding(isolated):
    store, adapter, service, source = isolated
    complete_initial_history(service, source)
    job = service.create_job({"source_id": source["id"], "mode": "continuous"})
    adapter.discovery_error = "ACCOUNT_OR_PROCESS_CHANGED"
    service.run_once(job["id"])
    assert store.get("background_jobs", job["id"])["state"] == "BLOCKED"
    assert service.summary()["binding"]["state"] == "BLOCKED"


def test_running_transition_storage_failure_does_not_leak_source_lock(isolated, monkeypatch):
    store, adapter, service, source = isolated
    complete_initial_history(service, source)
    adapter.discovery_calls = 0
    job = service.create_job({"source_id": source["id"], "mode": "continuous"})
    original_put = store.put
    failed = False
    def fail_one_transition(kind, data, ident=None, **kwargs):
        nonlocal failed
        if not failed and kind == "background_jobs" and data.get("state") == "RUNNING":
            failed = True
            raise OSError("Isolated write failure")
        return original_put(kind, data, ident, **kwargs)
    monkeypatch.setattr(store, "put", fail_one_transition)
    try:
        service.run_once(job["id"])
    except OSError:
        pass
    assert failed
    service.run_once(job["id"])
    assert adapter.discovery_calls == 1


def test_manual_post_correction_does_not_restore_stale_text(isolated, monkeypatch):
    store, adapter, service, source = isolated
    complete_initial_history(service, source)
    adapter.rows = [record("initial text")]
    job = service.create_job({"source_id": source["id"], "mode": "continuous"})
    service.run_once(job["id"])
    material = store.all("materials")[0]
    original_get = store.get
    reached = threading.Event()
    release = threading.Event()
    revised = threading.Event()

    def revise_after_read(kind, ident):
        value = original_get(kind, ident)
        if not reached.is_set() and kind == "materials" and ident == material["id"]:
            reached.set()
            assert release.wait(5), "Isolated classification barrier timed out"
        return value

    monkeypatch.setattr(store, "get", revise_after_read)
    classifier = threading.Thread(target=service.classify, args=("materials", material["id"],
        {"label": "travel_promotion", "evidence": "Manual fixture."}))
    def revise():
        store.ingest_background_page(source, [record("new source text")], {
            "cursor": None, "exhausted": True, "snapshot_id": "offline-only"},
            original_get("background_jobs", job["id"]))
        revised.set()
    writer = threading.Thread(target=revise)
    try:
        classifier.start()
        assert reached.wait(5)
        writer.start()
        # A correct material mutation lock serializes this update after correction.
        revised.wait(0.2)
    finally:
        release.set()
        classifier.join(5)
        if writer.ident is not None:
            writer.join(5)
    assert not classifier.is_alive() and not writer.is_alive()
    assert revised.is_set()
    current = original_get("materials", material["id"])
    assert current["classification"]["origin"] == "manual"
    assert current["text"] == record("new source text")["text"]
def test_incomplete_binding_retries_without_access_and_revalidates(isolated):
    store, adapter, service, source = isolated
    complete_initial_history(service, source)
    adapter.discovery_calls = 0
    adapter.rows = [record()]
    job = service.create_job({'source_id': source['id'], 'mode': 'continuous'})
    store.put('background_jobs', {**job, 'cursor': {'snapshot_id': 'abandoned-snapshot'}})
    retired = []
    adapter.release_snapshot = lambda ident, **kwargs: retired.append((ident, kwargs))
    verified_bind = adapter.bind
    def incomplete():
        raise ValueError('ACCOUNT_PROCESS_BINDING_INCOMPLETE')
    adapter.bind = incomplete
    service.run_once(job['id'])
    blocked = store.get('background_jobs', job['id'])
    assert blocked['state'] == 'RETRY' and blocked['cursor'] is None
    assert service.summary()['binding']['state'] == 'BLOCKED'
    assert adapter.discovery_calls == 0 and not store.all('materials')
    assert retired[0][0] == 'abandoned-snapshot'
    assert retired[0][1]['reason'] == 'ACCOUNT_PROCESS_BINDING_INCOMPLETE'
    adapter.bind = verified_bind
    service.run_once(job['id'])
    assert store.get('background_jobs', job['id'])['state'] == 'WAITING'
    assert service.summary()['binding']['state'] == 'VERIFIED'
    assert len(store.all('materials')) == 1

