"""Service onboarding/index/receipt integration, using synthetic adapters only."""
import copy
from datetime import datetime, timezone
import hashlib
import json

import pytest

from backend.background.service import BackgroundService, EXPECTED_ACCOUNT, EXPECTED_FRIEND
from backend.background.relevance import KEEP_PRODUCT_RELEVANT as KEEP, SKIP_IRRELEVANT as SKIP
from backend.store import Store


PRODUCT = "旅游线路报价499元，含酒店住宿，11月8日出团。"


def event(ident, text=PRODUCT, *, when="2025-06-01T12:00:00+08:00", media=False):
    value = {"event_key": str(ident), "native_id": str(ident), "native_post_id": str(ident),
        "server_id": str(ident), "account_id": EXPECTED_ACCOUNT,
        "conversation_id": EXPECTED_FRIEND, "author_id": EXPECTED_FRIEND,
        "identity_verified": True, "publication_time": when, "text": text,
        "source_kind": "moments", "private_source_ref": "private-" + str(ident),
        "attachments": [{"native_id": "media-" + str(ident), "media_index": 0, "type": "image",
            "name": "fixture.png", "mime": "image/png", "private_ref": "media-private-" + str(ident)}] if media else []}
    value["native_revision"] = hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
    return value


class IncrementalFixture:
    def __init__(self, rows=(), snapshots=None):
        self.rows = list(rows)
        self.snapshots = {} if snapshots is None else snapshots
        self.discovery_calls = self.snapshot_calls = self.content_reads = self.retrieval_calls = 0
        self.forces, self.discarded = [], []

    def bind(self):
        return {"account_native_id": EXPECTED_ACCOUNT, "friend_native_id": EXPECTED_FRIEND}

    def source_change_stamp(self, kind):
        return hashlib.sha256(json.dumps(self.rows, sort_keys=True).encode()).hexdigest()

    def discover_processing(self, kind, scope, cursor, limit, known_revisions,
                            *, force=False, previous_change_stamp=None, baseline_index=False):
        self.discovery_calls += 1; self.forces.append(force)
        stamp = self.source_change_stamp(kind)
        metric = dict.fromkeys(("native_rows_inspected", "index_entries_inspected", "index_payload_bytes_hashed",
                               "content_reads", "snapshot_copies", "new_or_changed"), 0)
        if cursor is None and not force and not baseline_index and stamp == previous_change_stamp:
            return {"items": [], "cursor": None, "exhausted": True, "snapshot_id": None,
                    "change_stamp": stamp, "source_unchanged": True, "metrics": metric, "baseline_entries": []}
        if cursor is None:
            self.snapshot_calls += 1
            sid = str(len(self.snapshots)); offset = 0
            self.snapshots[sid] = {"rows": copy.deepcopy(self.rows), "stamp": stamp}
        else:
            sid, offset = cursor["sid"], cursor["offset"]
            if sid not in self.snapshots:
                raise ValueError("CURSOR_SNAPSHOT_UNAVAILABLE")
        snapshot = self.snapshots[sid]
        selected = snapshot["rows"][offset:offset + limit]
        start = datetime.fromisoformat(scope["start"]).timestamp() if scope.get("start") else None
        end = datetime.fromisoformat(scope["end"]).timestamp() if scope.get("end") else None
        items, baseline = [], []
        for incoming in selected:
            epoch = datetime.fromisoformat(incoming["publication_time"]).timestamp()
            if baseline_index:
                baseline.append({"event_key": incoming["event_key"], "native_revision": incoming["native_revision"], "publication_epoch": epoch})
            if (start is None or epoch >= start) and (end is None or epoch < end):
                if known_revisions.get(incoming["event_key"]) != incoming["native_revision"]:
                    items.append(copy.deepcopy(incoming))
        self.content_reads += len(items)
        exhausted = offset + len(selected) >= len(snapshot["rows"])
        metric.update(native_rows_inspected=len(selected), index_entries_inspected=len(selected),
                      content_reads=len(items), snapshot_copies=int(cursor is None), new_or_changed=len(items))
        return {"items": items, "cursor": None if exhausted else {"sid": sid, "offset": offset + len(selected)},
                "exhausted": exhausted, "snapshot_id": sid, "change_stamp": snapshot["stamp"],
                "metrics": metric, "baseline_entries": baseline, "coverage": "UNKNOWN"}

    def retrieve(self, attachment, staging):
        self.retrieval_calls += 1
        return {"state": "RETRY", "reason": "FIXTURE_BYTES_MISSING"}

    def discard_private(self, values, *, protected_refs=()):
        self.discarded.extend(values)

    def release_snapshot(self, snapshot_id, **kwargs):
        pass  # Persisted fake snapshots intentionally support restart assertions.


@pytest.fixture
def setup(tmp_path):
    store = Store(tmp_path / "incremental-isolated")
    adapter = IncrementalFixture()
    service = BackgroundService(store, adapter)
    service.bind()
    source = next(value for value in store.all("sources") if value["kind"] == "moments")
    return store, adapter, service, source


def finish_history(setup, *, date_range=None, batch_size=100):
    store, adapter, service, source = setup
    history = service.create_job({"source_id": source["id"], "mode": "history", "range": date_range or {}, "batch_size": batch_size})
    for _ in range(20):
        service.run_once(history["id"])
        if store.get("background_jobs", history["id"])["state"] == "COMPLETED_LOCAL":
            return store.get("background_jobs", history["id"])
    raise AssertionError(store.get("background_jobs", history["id"]))


def test_unchanged_cycles_do_no_classification_download_or_history_replay(setup):
    store, adapter, service, source = setup
    adapter.rows = [event("product"), event("casual", "你好")]
    history = finish_history(setup)
    continuous = service.create_job({"source_id": source["id"], "mode": "continuous"})
    assert continuous["interval_seconds"] == 300
    first_index = store.get("source_processing", source["id"])["last_index_reconciliation_at"]
    reads, snapshots = adapter.content_reads, adapter.snapshot_calls
    for _ in range(2):
        service.run_once(continuous["id"])
        cycle = store.get("background_jobs", continuous["id"])["last_cycle"]
        assert cycle["classification_operations"] == cycle["ocr_operations"] == cycle["media_retrieval_operations"] == 0
        assert cycle["content_reads"] == cycle["snapshot_copies"] == 0
    assert adapter.content_reads == reads and adapter.snapshot_calls == snapshots
    assert len(store.all("materials")) == 1 and len(service.pipeline.receipts(source["id"])) == 2
    assert store.get("source_processing", source["id"])["last_index_reconciliation_at"] == first_index
    service.action(history["id"], "resume"); service.run_once(history["id"])
    assert adapter.content_reads == reads


def test_new_skip_advances_receipt_new_keep_promotes_and_changed_event_preserves_manual(setup):
    store, adapter, service, source = setup
    adapter.rows = [event("old", "你好")]
    finish_history(setup)
    continuous = service.create_job({"source_id": source["id"], "mode": "continuous"})
    adapter.rows += [event("new-skip", "收到，谢谢"), event("new-keep")]
    service.run_once(continuous["id"])
    receipts = {r["event_key"]: r for r in service.pipeline.receipts(source["id"])}
    assert receipts["new-skip"]["outcome"] == SKIP and receipts["new-keep"]["outcome"] == KEEP
    assert [m["event_key"] for m in store.all("materials")] == ["new-keep"]
    material = store.all("materials")[0]
    service.classify("materials", material["id"], {"label": "travel_promotion", "evidence": "manual fixture decision"})
    adapter.rows[-1] = event("new-keep", "普通聊天修订")
    service.run_once(continuous["id"])
    material = store.all("materials")[0]
    assert material["text"] == "普通聊天修订" and material["classification"]["origin"] == "manual"
    adapter.rows[0] = event("old", PRODUCT + "更正团费399元")
    service.run_once(continuous["id"])
    assert {m["event_key"] for m in store.all("materials")} == {"old", "new-keep"}


def test_restart_continues_initial_cursor_and_keeps_skipped_receipts(setup):
    store, adapter, service, source = setup
    adapter.rows = [event("skip", "你好"), event("keep")]
    history = service.create_job({"source_id": source["id"], "mode": "history", "batch_size": 1})
    service.run_once(history["id"])
    checkpoint = store.get("background_jobs", history["id"])["cursor"]
    assert checkpoint and service.pipeline.receipts(source["id"])[0]["outcome"] == SKIP
    assert not store.all("materials")
    restarted_adapter = IncrementalFixture(adapter.rows, adapter.snapshots)
    resumed = BackgroundService(Store(store.root), restarted_adapter)
    resumed.run_once(history["id"])
    assert restarted_adapter.snapshot_calls == 0 and restarted_adapter.content_reads == 1
    assert store.get("background_jobs", history["id"])["state"] == "COMPLETED_LOCAL"
    assert len(resumed.pipeline.receipts(source["id"])) == 2
    assert resumed.pipeline.processing(source["id"])["onboarding_state"] == "INITIAL_LOCAL_HISTORY_PROCESSED"


def test_initial_parse_gap_on_earlier_page_blocks_incremental_handoff(setup):
    store, adapter, service, source = setup
    adapter.rows = [event("one"), event("two")]
    discover = adapter.discover_processing

    def with_gap(kind, scope, cursor, limit, known_revisions, **options):
        page = discover(kind, scope, cursor, limit, known_revisions, **options)
        page["parse_issues"] = [{"native_id": "malformed", "code": "MALFORMED_RECORD"}] if cursor is None else []
        return page

    adapter.discover_processing = with_gap
    history = service.create_job({"source_id": source["id"], "mode": "history", "batch_size": 1})
    service.run_once(history["id"])
    service.run_once(history["id"])
    assert store.get("background_jobs", history["id"])["state"] == "BLOCKED"
    assert service.pipeline.processing(source["id"])["onboarding_state"] == "INITIAL_HISTORY_RUNNING"
    calls = adapter.discovery_calls
    continuous = service.create_job({"source_id": source["id"], "mode": "continuous"})
    service.run_once(continuous["id"])
    assert adapter.discovery_calls == calls


def test_initial_bounded_range_baselines_old_outside_rows_and_later_new_event(setup):
    store, adapter, service, source = setup
    adapter.rows = [event("old2024", when="2024-05-01T00:00:00+08:00"), event("initial2025"),
                    event("old2026", when="2026-02-01T00:00:00+08:00")]
    finish_history(setup, date_range={"start": "2025-01-01", "end": "2026-01-01"}, batch_size=1)
    assert [m["event_key"] for m in store.all("materials")] == ["initial2025"]
    assert len(service.pipeline.receipts(source["id"])) == 1
    assert len(service.pipeline.known(source["id"])) == 3
    adapter.rows.append(event("new2026", when="2026-10-28T17:00:00+08:00"))
    continuous = service.create_job({"source_id": source["id"], "mode": "continuous"})
    service.run_once(continuous["id"])
    assert {m["event_key"] for m in store.all("materials")} == {"initial2025", "new2026"}
    assert store.get("background_jobs", continuous["id"])["last_cycle"]["content_reads"] == 1
    finish_history(setup, date_range={"start": "2024-01-01", "end": "2025-01-01"})
    assert {m["event_key"] for m in store.all("materials")} == {"old2024", "initial2025", "new2026"}


def test_parent_and_explicit_reply_in_same_page_make_one_product_card(setup):
    store, adapter, service, moments_source = setup
    source = next(s for s in store.all("sources") if s["kind"] == "chat")
    parent = event("18446744073709551615")
    reply = event("9007199254740993", "499元")
    for value in (parent, reply): value["source_kind"] = "chat"
    reply["reply"] = {"relationship": "explicit_reply", "relationship_verified": True,
        "native_server_id": parent["server_id"], "account_id": EXPECTED_ACCOUNT,
        "conversation_id": EXPECTED_FRIEND, "source_message_server_id": reply["server_id"]}
    adapter.rows = [parent, reply]
    finish_history((store, adapter, service, source))
    materials = store.all("materials")
    assert len(materials) == 1
    assert materials[0].get("product_context", [])[0]["event_key"] == reply["event_key"]
    assert all(r["outcome"] == KEEP for r in service.pipeline.receipts(source["id"]))
