"""Crash/restart fixture using real BackgroundService and Store, never WeChat.

Creates a fresh isolated recovery-test directory, terminates only its own hidden
Popen worker after a committed page, then verifies recovery in another process.
Existing evidence is never reused or removed. No process enumeration is used.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid

REPO = Path(__file__).resolve().parents[1]
ROOT = REPO / ".local" / "integration-20261028" / "recovery-test"


def write_json(path, value):
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".part")
    with temporary.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixture_item(number, friend, *, media=False):
    return {"event_key": "recovery-fixture-" + str(number), "native_id": str(number),
            "native_post_id": str(number), "author_id": friend, "identity_verified": True,
            "text": "Offline recovery fixture " + str(number),
            "publication_time": "2025-06-01T12:00:00+08:00", "source_time_raw": "1748750400",
            "attachments": [{"native_id": "fixture-image-1", "media_index": 0,
                "type": "image", "mime": "image/png", "name": "recovery-fixture.png",
                "private_ref": "offline-fixture-reference"}] if media else []}


def setup_imports(site_packages):
    # Explicit existing dependency paths; no installation or production config.
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    if site_packages:
        site = Path(site_packages).resolve(strict=True)
        if site != (REPO / ".venv" / "Lib" / "site-packages").resolve(strict=True):
            raise RuntimeError("FIXTURE_DEPENDENCY_PATH_INVALID")
        sys.path.insert(1, str(site))


def worker(phase, root, nonce, site_packages):
    setup_imports(site_packages)
    from PIL import Image
    from backend.background.service import BackgroundService, EXPECTED_ACCOUNT, EXPECTED_FRIEND
    from backend.store import Store
    if root.resolve().parent != ROOT.parent.resolve():
        raise RuntimeError("FIXTURE_ROOT_INVALID")
    config = read_json(root / "run-config.json")
    if config["nonce"] != nonce or config["script_sha256"] != sha(Path(__file__)) or config["parent_pid"] != os.getppid():
        raise RuntimeError("FIXTURE_WORKER_OWNERSHIP_INVALID")
    store = Store(root / "fixture-store")
    png = io.BytesIO()
    Image.new("RGB", (7, 9), (17, 83, 151)).save(png, "PNG")
    image_bytes = png.getvalue()
    rows = [fixture_item(1, EXPECTED_FRIEND, media=True), fixture_item(2, EXPECTED_FRIEND)]

    class FixtureAdapter:
        def __init__(self):
            self.bind_count = 0
            self.discovery_calls = 0
            self.retrieval_calls = 0
            self.fail_first_media = True
            self.history_id = None
            self.closed = False

        def bind(self):
            self.bind_count += 1
            return {"account_native_id": EXPECTED_ACCOUNT, "friend_native_id": EXPECTED_FRIEND,
                    "client_version": "offline-fixture"}

        def discover(self, kind, scope, cursor, limit):
            if not self.bind_count or kind != "moments":
                raise RuntimeError("FIXTURE_BINDING_REQUIRED")
            self.discovery_calls += 1
            offset = 0 if cursor is None else cursor["offset"]
            if cursor is not None and cursor.get("snapshot_id") != "offline-immutable-fixture":
                raise ValueError("CURSOR_SNAPSHOT_UNAVAILABLE")
            if phase == "interrupt" and offset == 1:
                job = store.get("background_jobs", self.history_id)
                attachments = store.all("attachments")
                if job["state"] != "RUNNING" or len(store.all("materials")) != 1 or len(attachments) != 1 or attachments[0]["state"] != "PENDING":
                    raise RuntimeError("FIXTURE_FIRST_PAGE_NOT_COMMITTED")
                write_json(root / "blocked-worker.json", {
                    "pid": os.getpid(), "parent_pid": os.getppid(), "nonce": nonce,
                    "script_sha256": sha(Path(__file__)), "phase": "blocked-next-discovery",
                    "history_id": self.history_id, "cursor": job["cursor"],
                    "job_state": job["state"], "materials": 1, "pending_attachments": 1,
                    "binding_revalidated": self.bind_count >= 3})
                # This worker owns no other worker. Parent terminates its Popen
                # handle while this simulated discovery call has not returned.
                while True:
                    threading.Event().wait(1)
            selected = rows[offset:offset + limit]
            exhausted = offset + len(selected) >= len(rows)
            return {"items": selected, "cursor": None if exhausted else {
                        "snapshot_id": "offline-immutable-fixture", "offset": offset + len(selected)},
                    "snapshot_id": "offline-immutable-fixture", "exhausted": exhausted,
                    "observed_range": {"min_epoch": 1748750400, "max_epoch": 1748750400},
                    "coverage": "UNKNOWN"}

        def retrieve(self, attachment, staging):
            self.retrieval_calls += 1
            if self.fail_first_media:
                self.fail_first_media = False
                return {"state": "RETRY", "reason": "FIXTURE_TEMPORARY_MEDIA_UNAVAILABLE"}
            destination = staging / "recovery-fixture.png"
            destination.write_bytes(image_bytes)
            return {"state": "SAVED", "path": str(destination), "mime": "image/png",
                    "sha256": hashlib.sha256(image_bytes).hexdigest(), "quality": "offline_fixture"}

        def release_snapshot(self, snapshot_id):
            if snapshot_id != "offline-immutable-fixture":
                raise RuntimeError("FIXTURE_SNAPSHOT_SCOPE_INVALID")

        def close(self):
            self.closed = True

    adapter = FixtureAdapter()
    service = BackgroundService(store, adapter)
    if phase == "interrupt":
        service.bind()
        source = next(s for s in store.all("sources") if s["kind"] == "moments")
        history = service.create_job({"source_id": source["id"], "mode": "history", "batch_size": 1})
        media = next(j for j in store.all("background_jobs") if j["mode"] == "media")
        service.action(media["id"], "pause")
        adapter.history_id = history["id"]
        service.run_once(history["id"])
        service.run_once(history["id"])
        raise RuntimeError("FIXTURE_BLOCKING_DISCOVERY_UNEXPECTEDLY_RETURNED")

    before = next(j for j in store.all("background_jobs") if j["mode"] == "history")
    if before["state"] != "RUNNING" or before["cursor"] != {"snapshot_id": "offline-immutable-fixture", "offset": 1}:
        raise RuntimeError("FIXTURE_INTERRUPTED_CHECKPOINT_MISSING")
    adapter.history_id = before["id"]
    service.start()  # Actual startup recovery converts persisted RUNNING to QUEUED.
    deadline = time.monotonic() + 25
    try:
        while time.monotonic() < deadline:
            recovered = store.get("background_jobs", before["id"])
            if recovered["state"] == "COMPLETED_LOCAL":
                break
            time.sleep(0.1)
        else:
            raise RuntimeError("FIXTURE_RECOVERY_DEADLINE")
    finally:
        service.stop()
    if service.thread and service.thread.is_alive():
        raise RuntimeError("FIXTURE_SERVICE_THREAD_STILL_RUNNING")
    if not adapter.bind_count or adapter.discovery_calls != 1:
        raise RuntimeError("FIXTURE_RECOVERY_DID_NOT_REVALIDATE_AND_RESUME")
    recovered_job = store.get("background_jobs", before["id"])
    recovered_material_ids = {m["event_key"]: m["id"] for m in store.all("materials")}
    if len(recovered_material_ids) != 2 or len(store.all("attachments")) != 1:
        raise RuntimeError("FIXTURE_RECOVERY_RECORD_COUNTS_WRONG")

    # Use a new service instance after the scheduler has stopped. Only public
    # job actions/run_once are used; no background service implementation edits.
    media_service = BackgroundService(store, adapter)
    media = next(j for j in store.all("background_jobs") if j["mode"] == "media")
    media_service.action(media["id"], "retry")
    media_service.run_once(media["id"])
    retried = store.all("attachments")[0]
    if retried["state"] != "RETRY" or retried["last_error"] != "FIXTURE_TEMPORARY_MEDIA_UNAVAILABLE":
        raise RuntimeError("FIXTURE_MEDIA_RETRY_NOT_PERSISTED")
    media_service.action(media["id"], "retry")
    media_service.run_once(media["id"])
    saved = store.all("attachments")[0]
    if saved["state"] != "SAVED" or saved["media_state"] != "VALIDATED":
        raise RuntimeError("FIXTURE_MEDIA_RETRY_NOT_COMPLETED")
    stored_bytes = (store.root / saved["path"]).read_bytes()
    if stored_bytes != image_bytes or hashlib.sha256(stored_bytes).hexdigest() != saved["sha256"]:
        raise RuntimeError("FIXTURE_SAVED_IMAGE_HASH_MISMATCH")
    with Image.open(io.BytesIO(stored_bytes)) as image:
        image.load()
        if image.size != (7, 9) or image.format != "PNG":
            raise RuntimeError("FIXTURE_IMAGE_REOPEN_FAILED")
    source = next(s for s in store.all("sources") if s["kind"] == "moments")
    replay = media_service.create_job({"source_id": source["id"], "mode": "continuous", "batch_size": 2})
    media_service.run_once(replay["id"])
    after_ids = {m["event_key"]: m["id"] for m in store.all("materials")}
    with store.connect() as database:
        events = database.execute("SELECT count(*) FROM source_events").fetchone()[0]
        blobs = database.execute("SELECT count(*) FROM blobs").fetchone()[0]
        integrity = database.execute("PRAGMA integrity_check").fetchone()[0]
    if after_ids != recovered_material_ids or events != 2 or blobs != 1 or integrity != "ok":
        raise RuntimeError("FIXTURE_REPLAY_DUPLICATION_OR_INTEGRITY_FAILURE")
    if store.get("background_jobs", before["id"])["state"] != "COMPLETED_LOCAL":
        raise RuntimeError("FIXTURE_MEDIA_CHANGED_COMPLETED_HISTORY")
    media_service.stop()
    write_json(root / "resumed-worker.json", {
        "pid": os.getpid(), "parent_pid": os.getppid(), "nonce": nonce,
        "script_sha256": sha(Path(__file__)), "phase": "recovery-completed",
        "interrupted_state": before["state"], "interrupted_cursor": before["cursor"],
        "binding_revalidated": adapter.bind_count > 0, "binding_calls": adapter.bind_count,
        "resumed_history_state": recovered_job["state"], "history_cursor": recovered_job["cursor"],
        "materials": len(after_ids), "source_events": events, "attachments": 1, "blobs": blobs,
        "saved_attachments": 1, "attachment_retrieval_calls": adapter.retrieval_calls,
        "retry_observed": True, "attachment_sha256": saved["sha256"],
        "image_dimensions": [7, 9], "image_reopened": True,
        "repeat_reconciliation_no_duplicates": True, "sqlite_integrity": integrity,
        "scheduler_thread_stopped": not service.thread.is_alive(), "coverage": "UNKNOWN",
        "live_wechat_access": False, "business_data_access": False})


def wait_marker(path, child, *, seconds):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if path.is_file():
            return read_json(path)
        if child.poll() is not None:
            raise RuntimeError("OWNED_WORKER_EXITED_BEFORE_MARKER")
        time.sleep(0.1)
    raise RuntimeError("OWNED_WORKER_MARKER_TIMEOUT")


def parent(output_root=None):
    root = Path(output_root or ROOT).resolve()
    if root.parent != (REPO / ".local" / "integration-20261028").resolve():
        raise RuntimeError("RECOVERY_ROOT_OUTSIDE_WORKSPACE")
    root.mkdir(parents=True, exist_ok=False)
    base_python = Path(sys.base_prefix) / "python.exe"
    site_packages = REPO / ".venv" / "Lib" / "site-packages"
    if not base_python.is_file() or not site_packages.is_dir():
        raise RuntimeError("EXISTING_FIXTURE_RUNTIME_MISSING")
    nonce = uuid.uuid4().hex
    script = Path(__file__).resolve()
    config = {"nonce": nonce, "parent_pid": os.getpid(), "script_sha256": sha(script),
              "python": str(base_python), "site_packages": str(site_packages)}
    write_json(root / "run-config.json", config)
    workers, logs, termination = [], [], []
    result = {"status": "FAILED", "started_at": datetime.now(timezone.utc).isoformat(),
              "isolated_root": str(root), "live_wechat_access": False, "business_data_access": False,
              "mechanism": "actual owned hidden worker termination and new-process recovery",
              "source_hashes": {str(p.relative_to(REPO)): sha(p) for p in
                  (REPO / "backend/background/service.py", REPO / "backend/store.py", script)}}
    def launch(phase):
        output = (root / (phase + "-worker.log")).open("xb"); logs.append(output)
        environment = dict(os.environ)
        environment["PYTHONPATH"] = os.pathsep.join([str(REPO), str(site_packages)])
        environment["PYTHONIOENCODING"] = "utf-8"
        child = subprocess.Popen([str(base_python), str(script), "--worker", phase,
                                  "--root", str(root), "--nonce", nonce,
                                  "--site-packages", str(site_packages)], cwd=str(REPO), env=environment,
                                 stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        workers.append(child)
        return child
    def validate(marker, child, phase):
        if (marker.get("pid") != child.pid or marker.get("parent_pid") != os.getpid()
                or marker.get("nonce") != nonce or marker.get("script_sha256") != config["script_sha256"]
                or marker.get("phase") != phase):
            raise RuntimeError("OWNED_WORKER_MARKER_IDENTITY_MISMATCH")
    try:
        first = launch("interrupt")
        blocked = wait_marker(root / "blocked-worker.json", first, seconds=30)
        validate(blocked, first, "blocked-next-discovery")
        if first.poll() is not None:
            raise RuntimeError("OWNED_WORKER_NOT_RUNNING_AT_INTERRUPTION")
        first.terminate()  # Uses only this Popen object's owned process handle.
        first.wait(timeout=5)
        termination.append({"pid": first.pid, "marker_verified": True,
                            "mechanism": "owned_Popen_terminate", "exit_code": first.returncode})
        second = launch("resume")
        resumed = wait_marker(root / "resumed-worker.json", second, seconds=45)
        validate(resumed, second, "recovery-completed")
        second.wait(timeout=5)
        if second.returncode or first.pid == second.pid:
            raise RuntimeError("RESTARTED_WORKER_INVALID_EXIT_OR_PID")
        result.update(status="PASS", interrupted_pid=first.pid, restarted_pid=second.pid,
                      interrupted=blocked, resumed=resumed,
                      original_native_record_count=1, final_native_record_count=resumed["materials"])
    except Exception as error:
        result["error"] = str(error)
    finally:
        for child in workers:
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=5)
                termination.append({"pid": child.pid, "mechanism": "owned_Popen_cleanup",
                                    "exit_code": child.returncode})
        for output in logs:
            output.close()
        result.update(owned_worker_pids=[c.pid for c in workers], stopped_workers=termination,
                      owned_worker_exit_codes={str(c.pid): c.returncode for c in workers},
                      no_owned_workers_left=all(c.poll() is not None for c in workers),
                      completed_at=datetime.now(timezone.utc).isoformat())
        write_json(root / "recovery-result.json", result)
    print(json.dumps({"status": result["status"], "result": str(root / "recovery-result.json"),
                      "no_owned_workers_left": result["no_owned_workers_left"], "error": result.get("error")}))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", choices=("interrupt", "resume"))
    parser.add_argument("--root", type=Path)
    parser.add_argument("--nonce")
    parser.add_argument("--site-packages")
    parser.add_argument("--output-root", type=Path, help="Fresh direct child of .local/integration-20261028; never overwrites evidence")
    arguments = parser.parse_args()
    if arguments.worker:
        worker(arguments.worker, arguments.root, arguments.nonce, arguments.site_packages)
    else:
        raise SystemExit(parent(arguments.output_root))
