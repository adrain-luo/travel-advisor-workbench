"""Relevance promotion/receipt transactions with isolated Store and fake media."""
import hashlib
import json

import pytest

from backend.background.pipeline import RelevancePipeline
from backend.background.relevance import KEEP_PRODUCT_RELEVANT as KEEP, SKIP_IRRELEVANT as SKIP, PENDING_RELEVANCE as PENDING, RETRY_ACQUISITION as RETRY
from backend.background.service import EXPECTED_ACCOUNT, EXPECTED_FRIEND
from backend.store import Store


PRODUCT = "旅游线路报价499元，含酒店住宿，11月8日出团。"


class MediaFixture:
    def __init__(self):
        self.retrieved = 0
        self.discarded = []

    def retrieve(self, attachment, staging):
        self.retrieved += 1
        return {"state": "RETRY", "reason": "FIXTURE_BYTES_MISSING"}

    def discard_private(self, values, *, protected_refs=()):
        self.discarded.extend(values)


def row(event, text=PRODUCT, *, revision=None, media=False):
    return {"event_key": str(event), "native_id": str(event), "server_id": str(event),
        "native_revision": revision or hashlib.sha256((str(event) + text).encode()).hexdigest(),
        "account_id": EXPECTED_ACCOUNT, "conversation_id": EXPECTED_FRIEND,
        "author_id": EXPECTED_FRIEND, "identity_verified": True, "source_kind": "chat",
        "publication_time": "2025-06-01T12:00:00+08:00", "source_time_raw": "1748750400",
        "text": text, "private_source_ref": "fixture-private-source",
        "attachments": [{"native_id": "image-" + str(event), "media_index": 0, "type": "image",
            "name": "fixture.png", "mime": "image/png", "private_ref": "fixture-private-media"}] if media else []}


@pytest.fixture
def pipeline(tmp_path):
    store = Store(tmp_path / "pipeline-isolated")
    source = store.put("sources", {"kind": "chat", "native_id": EXPECTED_FRIEND,
        "account_id": "business-account-fixture", "account_native_id": EXPECTED_ACCOUNT,
        "acquisition_mode": "background"}, "source-fixture")
    job = store.put("background_jobs", {"source_id": source["id"], "account_id": source["account_id"],
        "mode": "history", "initial_history": True, "state": "RUNNING", "requested_range": {},
        "activation_baseline": "2026-01-01T00:00:00+00:00", "counts": {}, "cursor": None})
    adapter = MediaFixture()
    return store, RelevancePipeline(store, adapter), source, job, adapter


def page(cursor=None, exhausted=True, **extra):
    return {"cursor": cursor, "exhausted": exhausted, "snapshot_id": "fixture-snapshot",
            "coverage": "UNKNOWN", "metrics": {"index_entries_inspected": 1}, **extra}


def commit_rows(pipeline, rows, **extra):
    store, engine, source, job, adapter = pipeline
    prepared = [engine.prepare(source, value) for value in rows]
    engine.commit(source, prepared, page(**extra), store.get("background_jobs", job["id"]))
    return prepared


def test_skip_receipt_and_cursor_commit_without_business_body(pipeline):
    store, engine, source, job, adapter = pipeline
    incoming = row("irrelevant", "普通问候，晚上吃饭了吗")
    commit_rows(pipeline, [incoming], cursor={"offset": 1}, exhausted=False)
    receipts = engine.receipts(source["id"])
    assert receipts[0]["outcome"] == SKIP
    assert incoming["text"] not in json.dumps(receipts, ensure_ascii=False)
    assert not store.all("materials") and not store.all("attachments")
    assert not engine.candidates()
    assert store.get("background_jobs", job["id"])["cursor"] == {"offset": 1}
    assert engine.known(source["id"])[incoming["event_key"]] == incoming["native_revision"]
    assert adapter.discarded and adapter.retrieved == 0


def test_receipts_and_materials_roll_back_when_progress_commit_fails(pipeline, monkeypatch):
    store, engine, source, job, adapter = pipeline
    prepared = [engine.prepare(source, row("keep")), engine.prepare(source, row("skip", "你好"))]
    def failed_commit(*args, **kwargs):
        raise RuntimeError("FIXTURE_CURSOR_COMMIT_FAILURE")
    monkeypatch.setattr(store, "ingest_background_page", failed_commit)
    with pytest.raises(RuntimeError, match="FIXTURE_CURSOR_COMMIT_FAILURE"):
        engine.commit(source, prepared, page(cursor={"offset": 2}), job)
    assert not engine.receipts(source["id"])
    assert not store.all("materials") and not store.all("checkpoints")
    assert not adapter.discarded


def test_clear_product_text_promotes_and_casual_reply_does_not(pipeline):
    store, engine, source, job, adapter = pipeline
    commit_rows(pipeline, [row("keep"), row("skip", "收到，谢谢")])
    assert [material["event_key"] for material in store.all("materials")] == ["keep"]
    assert {r["event_key"]: r["outcome"] for r in engine.receipts(source["id"])} == {"keep": KEEP, "skip": SKIP}
    assert store.get("background_jobs", job["id"])["last_cycle"]["inspected"] == 2
    assert adapter.retrieved == 0


def test_image_only_acquisition_failure_is_not_irrelevance(pipeline):
    store, engine, source, job, adapter = pipeline
    commit_rows(pipeline, [row("image", "", media=True)])
    receipt = engine.receipts(source["id"])[0]
    assert receipt["outcome"] == RETRY
    assert not store.all("materials")
    assert engine.candidates()[0]["outcome"] == RETRY
    assert adapter.retrieved == 1


def test_manual_negative_receipt_survives_removal_and_new_revision(pipeline):
    store, engine, source, job, adapter = pipeline
    commit_rows(pipeline, [row("corrected")])
    material = store.all("materials")[0]
    store.put("materials", {**material, "classification": {"label": "other", "origin": "manual"}})
    commit_rows(pipeline, [row("corrected", "你好", revision="revision-two")])
    assert not store.all("materials")
    assert engine.receipts(source["id"])[0]["classification"]["origin"] == "manual"
    commit_rows(pipeline, [row("corrected", PRODUCT + "更正价格399元", revision="revision-three")])
    assert not store.all("materials")
    assert engine.receipts(source["id"])[0]["outcome"] == SKIP
    assert engine.known(source["id"])["corrected"] == "revision-three"


def test_explicit_native_reply_augments_accepted_parent_without_new_card(pipeline):
    store, engine, source, job, adapter = pipeline
    parent = row("18446744073709551615")
    commit_rows(pipeline, [parent])
    reply = row("9007199254740993", "499元")
    reply["reply"] = {"relationship": "explicit_reply", "relationship_verified": True,
        "native_server_id": parent["server_id"], "account_id": EXPECTED_ACCOUNT,
        "conversation_id": EXPECTED_FRIEND, "source_message_server_id": reply["server_id"]}
    prepared = commit_rows(pipeline, [reply])
    assert prepared[0][1]["outcome"] == KEEP
    materials = store.all("materials")
    assert len(materials) == 1
    assert materials[0]["product_context"][0]["event_key"] == reply["event_key"]
    receipts = {value["event_key"]: value for value in engine.receipts(source["id"])}
    assert receipts[reply["event_key"]]["material_id"] == receipts[parent["event_key"]]["material_id"]


def test_expired_uncertain_candidate_keeps_pending_receipt_not_skip(pipeline):
    store, engine, source, job, adapter = pipeline
    commit_rows(pipeline, [row("uncertain", "旅游线路")])
    candidate = engine.candidates()[0]
    candidate["expires_at"] = "2000-01-01T00:00:00+00:00"
    with store.connect() as db:
        db.execute("UPDATE pending_candidates SET data=? WHERE id=?", (json.dumps(candidate), candidate["id"]))
    engine.expire()
    assert not engine.candidates()
    receipt = engine.receipts(source["id"])[0]
    assert receipt["outcome"] == PENDING and receipt["reason_code"] == "PENDING_EXPIRED"
    assert receipt["event_key"] in engine.known(source["id"])


def test_outside_range_baseline_is_separate_from_relevance_receipts(pipeline):
    store, engine, source, job, adapter = pipeline
    entry = {"event_key": "old-outside-range", "native_revision": "outside-revision", "publication_epoch": 1}
    engine.commit(source, [], page(baseline_entries=[entry]), job)
    assert engine.known(source["id"])[entry["event_key"]] == "outside-revision"
    assert entry["event_key"] not in engine.known(source["id"], include_baseline=False)
    assert not engine.receipts(source["id"])
    assert not store.all("materials")
