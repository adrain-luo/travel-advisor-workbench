"""Offline subprocess durability/replay proof; never a live WeChat collector.

Uses historical manually saved JPEG bytes with explicitly synthetic source/event
identities. Refuses to reuse a test database. Terminates only an owned Popen child.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time


def write_json(path, data):
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_image(path, expected):
    from PIL import Image
    assert digest(path) == expected
    with Image.open(path) as image:
        image.load()
        return {"sha256": expected, "size": path.stat().st_size,
                "format": image.format, "dimensions": list(image.size)}


def fixture_items(scope):
    def event(key, sample):
        return {"type": "image", "text": "OFFLINE SYNTHETIC PUBLICATION",
                "author": "fixture-only", "event_key": key,
                "identity_verified": True, "identity_evidence": "synthetic fixture identity only",
                "source_time_raw": scope["upper"], "observed_at": scope["upper"],
                "acquisition_method": "offline_historical_sample_fixture",
                "attachments": [{"name": sample + ".jpg", "type": "image", "mime": "image/jpeg",
                                 "media_index": 0, "quality": "client_saved",
                                 "sample_key": sample, "original_verified": False}]}
    return [event("synthetic-A", "group"), event("synthetic-B", "group"),
            event("synthetic-M", "moments"), event("synthetic-PENDING", "group")]


def child(args):
    sys.path.insert(0, str(args.project))
    from backend.store import Store
    root = args.run / "offline-test-data"
    assert Path(os.environ["TRAVEL_DATA_DIR"]).resolve() == root.resolve()
    assert "backend.app" not in sys.modules
    baseline = json.loads((args.run / "baseline.json").read_text(encoding="utf-8-sig"))
    scope = {"mode": "SINCE", "start": "2026-10-13T00:00:00+08:00",
             "upper": baseline["observed_at"], "timezone": "Asia/Shanghai",
             "start_inclusive": True, "upper_inclusive": True, "fixture_only": True}
    source = {"id": "OFFLINE-SYNTHETIC-SOURCE", "account_id": "OFFLINE-SYNTHETIC-ACCOUNT"}
    items = fixture_items(scope)
    if args.phase == "prepare":
        store = Store(root)
        staging = root / "staging"
        staging.mkdir()
        samples = {}
        for key, name in (("group", "group-selected-poster.jpg"), ("moments", "moments-selected-post.jpg")):
            original = args.project / ".local" / "live-evidence" / name
            destination = staging / (key + ".jpg")
            shutil.copyfile(original, destination)
            asset = store.save_blob(destination.read_bytes())
            samples[key] = {**verify_image(destination, digest(original)), "original_path": str(original),
                            "staged_path": str(destination), "blob_path": asset["path"],
                            "provenance": "historical_manual_wechat_client_save_2026-10-25",
                            "original_quality_verified": False, "live_retrieval": False}
        job = store.put("jobs", {"state": "RUNNING", "counts": {"discovered": 0},
                                 "scope": scope, "fixture_only": True})
        checkpoint = {"fixture_page": 1, "scope": scope, "coverage": "UNKNOWN"}
        saved = store.ingest_page(source, items, checkpoint, job)
        assert len(saved) == 4
        for material in saved:
            if material["event_key"] == "synthetic-PENDING":
                continue
            attachment = store.get("attachments", material["attachments"][0]["id"])
            sample = samples[attachment["sample_key"]]
            store.update_native_attachment(attachment, {"state": "SAVED", "path": sample["staged_path"],
                "sha256": sample["sha256"], "quality": "client_saved"}, staging)
        ready = {"pid": os.getpid(), "job_id": job["id"], "samples": samples,
                 "checkpoint": store.get("checkpoints", source["id"]), "scope": scope,
                 "material_ids": sorted(m["id"] for m in store.all("materials")),
                 "attachment_ids": sorted(a["id"] for a in store.all("attachments")),
                 "pending_ids": sorted(a["id"] for a in store.all("attachments") if a["state"] == "PENDING")}
        assert len(ready["pending_ids"]) == 1
        write_json(args.run / "offline-ready.json", ready)
        # Parent terminates this owned child after observing committed readiness.
        sys.stdin.buffer.read(1)
        raise RuntimeError("Prepare child must be interrupted by its owner")

    ready = json.loads((args.run / "offline-ready.json").read_text(encoding="utf-8"))
    assert os.getpid() != ready["pid"]
    store = Store(root)
    assert store.get("jobs", ready["job_id"])["state"] == "RUNNING"
    reopened = {key: verify_image(root / sample["blob_path"], sample["sha256"])
                for key, sample in ready["samples"].items()}
    store.recover()
    assert store.get("jobs", ready["job_id"])["state"] == "PAUSED"
    assert store.get("checkpoints", source["id"]) == ready["checkpoint"]
    assert sorted(m["id"] for m in store.all("materials")) == ready["material_ids"]
    assert sorted(a["id"] for a in store.all("attachments")) == ready["attachment_ids"]
    assert sorted(a["id"] for a in store.all("attachments") if a["state"] == "PENDING") == ready["pending_ids"]
    job = store.get("jobs", ready["job_id"])
    replayed = store.ingest_page(source, items, ready["checkpoint"]["cursor"], job)
    assert replayed == [] and len(store.all("materials")) == 4
    # Same bytes and content, independently identified synthetic publication.
    another = {**items[0], "event_key": "synthetic-C"}
    added = store.ingest_page(source, [another], ready["checkpoint"]["cursor"], job)
    assert len(added) == 1 and len(store.all("materials")) == 5
    checkpoint_before_retry = store.get("checkpoints", source["id"])
    staging = root / "staging"
    group = ready["samples"]["group"]
    late = store.get("attachments", ready["pending_ids"][0])
    failed = store.update_native_attachment(late, {"state": "RETRY", "reason": "offline synthetic unavailable attempt"}, staging)
    assert failed["state"] == "RETRY" and failed["attempts"] == 1
    result = {"state": "SAVED", "path": group["staged_path"], "sha256": group["sha256"], "quality": "client_saved"}
    retried = store.update_native_attachment(failed, result, staging)
    assert retried["state"] == "SAVED" and retried["attempts"] == 2
    verify_image(root / retried["path"], group["sha256"])
    extra = store.get("attachments", added[0]["attachments"][0]["id"])
    store.update_native_attachment(extra, result, staging)
    assert store.get("checkpoints", source["id"]) == checkpoint_before_retry
    assert len(list((root / "blobs").glob("*/*"))) == 2
    assert len({m["event_key"] for m in store.all("materials")}) == 5
    assert all(a["state"] == "SAVED" for a in store.all("attachments"))
    store.validate_references()
    write_json(args.run / "offline-child-result.json", {
        "restart_pid": os.getpid(), "scope": scope, "reopened_images": reopened,
        "pre_interruption_materials": 4, "records_lost": 0, "duplicate_replay_new_events": 0,
        "new_distinct_identical_content_events": len(added), "final_synthetic_events": 5,
        "final_blobs": 2, "recovered_job_state": store.get("jobs", ready["job_id"])["state"],
        "pending_after_restart": len(ready["pending_ids"]), "pending_after_retry": 0,
        "late_retry_attempts": retried["attempts"], "checkpoint_unchanged_by_retry": True,
        "reference_validation": "PASS", "durability": "PASS", "deduplication": "PASS",
        "interruption_resume": "PASS", "proof_scope": "offline_storage_only"})


def main(args):
    root = args.run / "offline-test-data"
    if root.exists() or (args.run / "offline-replay.json").exists():
        raise ValueError("Refusing to reuse existing offline test data or report")
    assert args.run.is_dir() and (args.run / "baseline.json").is_file()
    env = {**os.environ, "TRAVEL_DATA_DIR": str(root), "TRAVEL_TEST_MODE": "1",
           "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1"}
    env.pop("TRAVEL_ENABLE_FOREGROUND_COLLECTION", None)
    # Windows venv python.exe may be a redirector with a different worker PID.
    # Own the actual interpreter process and use this project's existing packages.
    interpreter = Path(getattr(sys, "_base_executable", sys.executable)).resolve()
    env["PYTHONPATH"] = os.pathsep.join((str(args.project), str(args.project / ".venv" / "Lib" / "site-packages")))
    command = [str(interpreter), str(Path(__file__).resolve()), "--project", str(args.project), "--run", str(args.run)]
    owned = []
    report = {"live_collection": False, "live_source_records": 0,
              "evidence_class": "offline_subprocess_storage_fixture_with_historical_manual_sample_bytes",
              "original_quality_verified": False, "source_identity_verified": False,
              "requested_history_coverage": "UNKNOWN", "new_content_discovery_verified": False,
              "test_data_dir": str(root), "foreground_actions": 0,
              "limitations": ["No live WeChat worker or network access", "Synthetic publication identifiers",
                              "Historical JPEGs are client-saved, not verified originals",
                              "Process interruption after page commit; no mid-transaction crash claim"]}
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        with (args.run / "offline-worker-prepare.log").open("w", encoding="utf-8") as log:
            first = subprocess.Popen(command + ["--phase", "prepare"], cwd=args.project, env=env,
                                     stdin=subprocess.PIPE, stdout=log, stderr=subprocess.STDOUT, creationflags=flags)
            owned.append(first)
            deadline = time.monotonic() + 30
            while not (args.run / "offline-ready.json").is_file():
                if first.poll() is not None:
                    raise RuntimeError("Prepare worker exited before readiness; inspect log")
                if time.monotonic() > deadline:
                    raise TimeoutError("Prepare worker readiness timeout")
                time.sleep(.05)
            ready = json.loads((args.run / "offline-ready.json").read_text(encoding="utf-8"))
            assert first.pid == ready["pid"] and first.poll() is None, "Owned handle must identify actual Python worker"
            first.terminate()
            exit_code = first.wait(timeout=10)
            report["interrupted_owned_process"] = {"pid": first.pid, "command": command + ["--phase", "prepare"],
                                                    "exit_code": exit_code, "method": "Popen.terminate on owned handle"}
            report["samples"] = ready["samples"]
        with (args.run / "offline-worker-restart.log").open("w", encoding="utf-8") as log:
            second = subprocess.Popen(command + ["--phase", "restart"], cwd=args.project, env=env,
                                      stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, creationflags=flags)
            owned.append(second)
            if second.wait(timeout=30) != 0:
                raise RuntimeError("Restart worker failed; inspect log")
        report.update(json.loads((args.run / "offline-child-result.json").read_text(encoding="utf-8")))
        report["status"] = "PASS"
    except Exception as exc:
        report.update(status="FAIL", error=str(exc))
        raise
    finally:
        for process in owned:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            if process.stdin:
                process.stdin.close()
        report["owned_children_remaining"] = sum(process.poll() is None for process in owned)
        write_json(args.run / "offline-replay.json", report)
    print(json.dumps({"status": report["status"], "live_collection": False,
                      "synthetic_events": report["final_synthetic_events"], "blobs": report["final_blobs"],
                      "report": str(args.run / "offline-replay.json")}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--phase", choices=("prepare", "restart"))
    args = parser.parse_args()
    args.project, args.run = args.project.resolve(), args.run.resolve()
    child(args) if args.phase else main(args)
