"""Explicit offline fixtures: these tests are NOT live WeChat compatibility proof."""
import hashlib
from pathlib import Path

import pytest

from backend.collectors import CollectorBlocked, UploadAdapter, WeChatGroupAdapter, WeChatMomentsAdapter
from backend.collectors.base import normalize_item
from backend.collectors.native_uia import NativeUIADriver
from backend.time_semantics import classify_time, make_scope, parse_source_time


NOW = "2026-10-25T12:00:00+08:00"
ACCOUNT = {"id": "fixture-account", "identity_evidence": "fixture only"}
SOURCE = {"id": "fixture-group", "account_id": ACCOUNT["id"], "kind": "group", "display_name": "测试夹具群"}


class FixtureDriver:
    """A normalized driver fixture, deliberately not a WeChat mock interface."""
    def __init__(self, pages, surface="group_history"):
        self.pages, self.index, self.surface = pages, 0, surface
        self.mismatch = False

    def probe(self, kind):
        return {"kind": kind, "available": True, "status": "NOT_TESTED", "reason": "离线测试夹具"}

    def resolve(self, source, account):
        self.index = 0
        return {"surface": self.surface}

    def verify(self, source, account):
        if self.mismatch:
            raise CollectorBlocked("测试身份不匹配", "IDENTITY_MISMATCH")

    def read_page(self, source):
        return self.pages[min(self.index, len(self.pages) - 1)]

    def previous_page(self, source):
        self.index += 1

    def fetch(self, reference, destination):
        return {"state": "RETRY", "quality": "unknown", "reason": "离线夹具缺失附件"}


def page(*texts, endpoint=False, runtime=None):
    data = {"items": [{"text": text, "type": "text", "source_time_raw": "2026-10-24 10:00:00",
                       "ui_runtime_id": [runtime[i]] if runtime else None}
                      for i, text in enumerate(texts)], "observed_at": NOW}
    if endpoint:
        data["endpoint_evidence"] = {"verified": True, "text": "测试夹具终点"}
    return data


def ready(pages):
    driver = FixtureDriver(pages)
    adapter = WeChatGroupAdapter(driver)
    adapter.resolve_source(SOURCE, ACCOUNT)
    return adapter, driver


def test_date_only_start_is_local_inclusive_and_cutoff_is_frozen():
    scope = make_scope("SINCE", "2026-10-25", now=NOW)
    assert scope["start"] == "2026-10-25T00:00:00+08:00"
    assert scope["date_only_start"] and scope["upper"] == NOW
    assert classify_time(parse_source_time("2026-10-25 00:00:00", NOW), scope) == "IN_RANGE"
    assert classify_time(parse_source_time("2026-10-25 12:00:00", NOW), scope) == "IN_RANGE"
    assert classify_time(parse_source_time("2026-10-25 12:00:01", NOW), scope) == "AFTER"


def test_unknown_year_is_not_invented_and_coarse_separator_stays_uncertain():
    scope = make_scope("SINCE", "2026-10-25", now=NOW)
    ambiguous = parse_source_time("10月25日 09:00", NOW)
    assert ambiguous["start"] is None and ambiguous["status"] == "ambiguous"
    separator = parse_source_time("昨天 23:00", NOW, inherited_separator=True)
    assert separator["source_time"] is None
    assert classify_time(separator, scope) == "UNCERTAIN"


def test_relative_dates_cross_year_using_observation_clock():
    value = parse_source_time("昨天 09:00", "2026-01-01T12:00:00+08:00")
    assert value["start"] == "2025-12-31T09:00:00+08:00"
    assert value["precision"] == "minute"
    assert parse_source_time("2026年2月30日", NOW)["status"] == "invalid"
    assert parse_source_time("2025年12月31日", NOW)["precision"] == "day"


def test_compact_observed_relative_timestamp_keeps_raw_evidence_and_precision():
    value = parse_source_time("昨天09:07", NOW)
    assert value["source_time_raw"] == "昨天09:07"
    assert value["status"] == "parsed" and value["precision"] == "minute"
    assert value["start"] == "2026-10-24T09:07:00+08:00"
    assert value["end"] == "2026-10-24T09:08:00+08:00"
    assert value["source_time"] is None


def test_relative_minutes_remain_an_interval():
    value = parse_source_time("5分钟前", NOW)
    assert value["start"] == "2026-10-25T11:54:00+08:00"
    assert value["end"] == "2026-10-25T11:55:00+08:00"
    assert value["source_time"] is None


def test_incremental_overlap_does_not_claim_old_edit_coverage():
    scope = make_scope("INCREMENTAL", now=NOW, last_checkpoint={"last_cutoff": "2026-10-24T12:00:00+08:00"})
    assert scope["start"] == "2026-10-22T12:00:00+08:00"
    assert not scope["reconcile_old_edits"]


def test_invalid_ranges_and_ambiguous_dst_are_rejected():
    with pytest.raises(ValueError):
        make_scope("SINCE", "2027-01-01", now=NOW)
    with pytest.raises(ValueError):
        make_scope("SINCE", "2026-11-01T01:30:00", timezone="America/New_York", now="2026-11-02T12:00:00-05:00")


def test_no_selected_source_or_changed_account_cannot_start():
    adapter = WeChatGroupAdapter(FixtureDriver([page("a")]))
    with pytest.raises(CollectorBlocked, match="具体微信来源"):
        adapter.resolve_source({}, ACCOUNT)
    with pytest.raises(CollectorBlocked, match="其他账号"):
        adapter.resolve_source(SOURCE, {"id": "other"})


def test_general_feed_is_never_selected_contact_history():
    adapter = WeChatMomentsAdapter(FixtureDriver([page("a")], "general_feed"))
    with pytest.raises(CollectorBlocked, match="综合动态流"):
        adapter.resolve_source({**SOURCE, "kind": "moments"}, ACCOUNT)


def test_repeated_viewport_is_partial_and_does_not_repeat_items():
    adapter, _ = ready([page("a", "b")])
    pages = list(adapter.iterate_items(SOURCE, make_scope("ALL_ACCESSIBLE", now=NOW)))
    assert len(pages) == 2
    assert pages[-1]["coverage"] == "STALLED_UNPROVEN_END"
    assert pages[-1]["items"] == []
    assert "last_cutoff" not in pages[-1]["checkpoint"]


def test_page_budget_does_not_become_complete():
    adapter, _ = ready([page("a"), page("b")])
    scope = {**make_scope("ALL_ACCESSIBLE", now=NOW), "page_budget": 1}
    pages = list(adapter.iterate_items(SOURCE, scope))
    assert pages[-1]["coverage"] == "PARTIAL_WITH_GAPS" and pages[-1]["resource_cap"]


def test_supported_endpoint_has_evidence_and_completion_watermark():
    adapter, _ = ready([page("a"), page("b", endpoint=True)])
    pages = list(adapter.iterate_items(SOURCE, make_scope("ALL_ACCESSIBLE", now=NOW)))
    assert pages[-1]["coverage"] == "ACCESSIBLE_END_REACHED"
    assert pages[-1]["endpoint_evidence"]["text"]
    assert pages[-1]["checkpoint"]["last_cutoff"] == NOW


def test_overlap_reconciles_unique_context_but_keeps_legitimate_repeat():
    adapter, _ = ready([page("a", "b", "c"), page("b", "c", "d", endpoint=True)])
    pages = list(adapter.iterate_items(SOURCE, make_scope("ALL_ACCESSIBLE", now=NOW)))
    assert [i["text"] for i in pages[-1]["items"]] == ["d"]
    adapter, _ = ready([page("repeat", "repeat"), page("repeat", "repeat", "repeat", endpoint=True)])
    pages = list(adapter.iterate_items(SOURCE, make_scope("ALL_ACCESSIBLE", now=NOW)))
    assert len(pages[-1]["items"]) == 3


def test_runtime_ids_reconcile_overlap_only_inside_one_traversal():
    adapter, _ = ready([page("same", "same", runtime=[1, 2]), page("same", "same", runtime=[2, 3], endpoint=True)])
    pages = list(adapter.iterate_items(SOURCE, make_scope("ALL_ACCESSIBLE", now=NOW)))
    assert len(pages[-1]["items"]) == 1
    assert pages[-1]["items"][0]["event_key"] is None
    assert pages[-1]["items"][0]["target_identity_verified"] is True
    assert pages[-1]["items"][0]["identity_verified"] is False


def test_out_of_order_old_item_does_not_stop_and_outside_scope_not_ingested():
    old = page("old")
    old["items"][0]["source_time_raw"] = "2026-10-20 10:00:00"
    current = page("current", endpoint=True)
    current["items"][0]["source_time_raw"] = "2026-10-25 10:00:00"
    adapter, _ = ready([old, current])
    pages = list(adapter.iterate_items(SOURCE, make_scope("SINCE", "2026-10-25", now=NOW)))
    assert pages[0]["items"] == []
    assert pages[-1]["items"][0]["text"] == "current"


def test_target_interference_stops_on_next_boundary():
    adapter, driver = ready([page("a"), page("b")])
    iterator = adapter.iterate_items(SOURCE, make_scope("ALL_ACCESSIBLE", now=NOW))
    next(iterator)
    driver.mismatch = True
    with pytest.raises(CollectorBlocked):
        next(iterator)


def test_foreign_checkpoint_rejected_before_read():
    adapter, _ = ready([page("a")])
    with pytest.raises(CollectorBlocked):
        list(adapter.iterate_items(SOURCE, make_scope("ALL_ACCESSIBLE", now=NOW), {"account_id": "other"}))
    with pytest.raises(CollectorBlocked):
        list(adapter.iterate_items(SOURCE, make_scope("ALL_ACCESSIBLE", now=NOW), {"source_id": "other"}))


def test_interrupted_traversal_resumes_by_reopening_with_original_cutoff():
    adapter, driver = ready([page("a"), page("b", endpoint=True)])
    scope = make_scope("ALL_ACCESSIBLE", now=NOW)
    iterator = adapter.iterate_items(SOURCE, scope)
    committed_page = next(iterator)
    iterator.close()
    assert "last_cutoff" not in committed_page["checkpoint"]
    restarted = WeChatGroupAdapter(driver)
    restarted.resolve_source(SOURCE, ACCOUNT)
    pages = list(restarted.iterate_items(SOURCE, scope, committed_page["checkpoint"]))
    assert pages[0]["items"][0]["text"] == "a"
    assert pages[-1]["checkpoint"]["last_cutoff"] == NOW
    # Replaying is explicit; uncertain event IDs are not silently deduplicated.
    assert pages[0]["items"][0]["event_key"] is None


def test_resume_page_budget_counts_new_pages_after_saved_overlap():
    fixture_pages = [page(f"{i}-a", f"{i}-b", endpoint=i == 5) for i in range(1, 6)]
    scope = {**make_scope("ALL_ACCESSIBLE", now=NOW), "page_budget": 2}
    first, _ = ready(fixture_pages)
    first_pages = list(first.iterate_items(SOURCE, scope))
    checkpoint = first_pages[-1]["checkpoint"]
    assert checkpoint["pages_observed"] == 2
    second, _ = ready(fixture_pages)
    second_pages = list(second.iterate_items(SOURCE, scope, checkpoint))
    checkpoint = second_pages[-1]["checkpoint"]
    assert checkpoint["pages_observed"] == 4
    assert checkpoint["new_pages_observed"] == 2
    assert checkpoint["replay_pages_observed"] == 2
    assert checkpoint["resume_anchor_status"] == "MATCHED_CONTEXT"
    assert [p["replayed"] for p in second_pages if not p["terminal"]] == [True, True, False, False]
    # A partial replay retains the original frontier rather than regressing it.
    assert second_pages[0]["checkpoint"]["overlap_context"] == first_pages[-1]["checkpoint"]["overlap_context"]
    third, _ = ready(fixture_pages)
    final = list(third.iterate_items(SOURCE, scope, checkpoint))[-1]
    assert final["coverage"] == "ACCESSIBLE_END_REACHED"
    assert final["checkpoint"]["pages_observed"] == 5
    assert final["checkpoint"]["new_pages_observed"] == 1


def test_ambiguous_replay_anchor_does_not_invent_cursor_confidence():
    fixture_pages = [page("start-a", "start-b"), page("repeat", "repeat"), page("later-a", "later-b")]
    scope = {**make_scope("ALL_ACCESSIBLE", now=NOW), "page_budget": 2}
    first, _ = ready(fixture_pages)
    checkpoint = list(first.iterate_items(SOURCE, scope))[-1]["checkpoint"]
    resumed, _ = ready(fixture_pages)
    result = list(resumed.iterate_items(SOURCE, {**scope, "replay_budget": 2}, checkpoint))[-1]
    assert result["resume_anchor_missing"] is True
    assert result["coverage"] == "PARTIAL_WITH_GAPS"
    assert result["checkpoint"]["overlap_context"] == checkpoint["overlap_context"]
    assert result["checkpoint"]["resume_anchor_status"] == "SEARCHING"
    assert "last_cutoff" not in result["checkpoint"]


def test_new_scan_cutoff_does_not_reuse_old_resume_frontier():
    fixture_pages = [page("one-a", "one-b"), page("two-a", "two-b"), page("three-a", "three-b")]
    scope = {**make_scope("ALL_ACCESSIBLE", now=NOW), "page_budget": 2}
    first, _ = ready(fixture_pages)
    checkpoint = list(first.iterate_items(SOURCE, scope))[-1]["checkpoint"]
    new_scan, _ = ready(fixture_pages)
    new_scope = {**make_scope("INCREMENTAL", now="2026-10-25T13:00:00+08:00"), "page_budget": 1}
    result = list(new_scan.iterate_items(SOURCE, new_scope, checkpoint))[-1]
    assert result["checkpoint"]["pages_observed"] == 1
    assert result["checkpoint"]["replay_pages_observed"] == 0
    assert result["checkpoint"]["resume_anchor_status"] == "NOT_REQUIRED"


def test_media_retry_remains_independent_of_completed_discovery(tmp_path):
    class LateMediaDriver(FixtureDriver):
        def __init__(self):
            super().__init__([page("a", endpoint=True)])
            self.attempts = 0

        def fetch(self, reference, destination):
            self.attempts += 1
            if self.attempts == 1:
                return {"state": "RETRY", "quality": "unknown", "reason": "测试附件暂不可用"}
            destination.write_bytes(b"fixture attachment bytes")
            return {"state": "SAVED", "quality": "original", "path": str(destination),
                    "sha256": hashlib.sha256(destination.read_bytes()).hexdigest()}

    driver = LateMediaDriver()
    adapter = WeChatGroupAdapter(driver)
    adapter.resolve_source(SOURCE, ACCOUNT)
    terminal = list(adapter.iterate_items(SOURCE, make_scope("ALL_ACCESSIBLE", now=NOW)))[-1]
    assert terminal["checkpoint"]["last_cutoff"] == NOW
    first = adapter.fetch_attachment({"source_id": SOURCE["id"]}, tmp_path / "late.bin")
    second = adapter.fetch_attachment({"source_id": SOURCE["id"]}, tmp_path / "late.bin")
    assert first["state"] == "RETRY" and second["state"] == "SAVED"
    assert driver.attempts == 2


def test_native_unenrolled_path_is_honestly_blocked(tmp_path):
    result = NativeUIADriver(tmp_path / "nonexistent.json").probe("moments")
    assert result["available"] is False and result["status"] == "BLOCKED"


def test_native_version_guard_rejects_auto_update_at_same_executable_path(monkeypatch):
    driver = NativeUIADriver()
    config = {"executable": r"C:\fixture\Weixin.exe", "client_version": "4.1.13.65"}
    monkeypatch.setattr(driver, "_file_version", lambda path: "4.1.13.65")
    assert driver._verify_executable_version(config) == "4.1.13.65"
    monkeypatch.setattr(driver, "_file_version", lambda path: "4.1.14.10")
    with pytest.raises(CollectorBlocked) as error:
        driver._verify_executable_version(config)
    assert error.value.code == "CLIENT_VERSION_MISMATCH"


def test_native_version_guard_requires_enrollment_and_readable_version(monkeypatch):
    driver = NativeUIADriver()
    with pytest.raises(CollectorBlocked) as error:
        driver._verify_executable_version({"executable": r"C:\fixture\Weixin.exe"})
    assert error.value.code == "CLIENT_VERSION_NOT_ENROLLED"

    def unavailable(path):
        raise OSError("fixture version read failure")

    monkeypatch.setattr(driver, "_file_version", unavailable)
    with pytest.raises(CollectorBlocked) as error:
        driver._verify_executable_version({"executable": r"C:\fixture\Weixin.exe", "client_version": "4.1.13.65"})
    assert error.value.code == "CLIENT_VERSION_UNAVAILABLE"


def test_upload_original_unknown_publication_date_and_byte_integrity(tmp_path):
    source_file = tmp_path / "uploaded.txt"
    source_file.write_text("测试夹具，不是真实微信采集", encoding="utf-8")
    adapter = UploadAdapter()
    source = {"id": "upload-fixture", "kind": "upload", "items": [{"path": str(source_file)}]}
    result = list(adapter.iterate_items(source, make_scope("ALL_ACCESSIBLE", now=NOW)))[0]
    item = result["items"][0]
    assert item["source_time"] is None and item["time_evidence"]["status"] == "unknown"
    saved = adapter.fetch_attachment(item["attachments"][0], tmp_path / "store" / "original.txt")
    assert saved["state"] == "SAVED"
    assert saved["sha256"] == hashlib.sha256(source_file.read_bytes()).hexdigest()


def test_fingerprint_does_not_promote_ui_id_or_sdk_hash_to_native_identity():
    item = normalize_item({"text": "repeat", "native_id": "unstable-id", "hash": "colliding"}, SOURCE, NOW, 0,
                          make_scope("ALL_ACCESSIBLE", now=NOW))
    assert item["event_key"] is None and item["identity_confidence"] == "overlap_required"


def test_local_ocr_sends_only_selected_pixels_and_preserves_source(tmp_path, monkeypatch):
    from PIL import Image
    from backend.collectors import local_ocr
    image_path = tmp_path / "fixture.png"
    image = Image.new("RGB", (120, 80), "red")
    image.paste("blue", (40, 20, 80, 60))
    image.save(image_path)
    original = image_path.read_bytes()
    temporary_paths = []

    def recognize_fixture(arguments, timeout=20):
        selected = Path(arguments[arguments.index("-ImagePath") + 1])
        temporary_paths.append(selected)
        with Image.open(selected) as crop:
            assert crop.size == (80, 80)
            assert crop.getpixel((40, 40)) == (0, 0, 255)
            assert crop.getpixel((0, 0)) == (0, 0, 255)
        return {"width": 80, "height": 80, "language": "zh-Hans-CN", "text_angle": 0,
                "lines": [{"text": "fixture", "words": [{"text": "fixture", "bounds": {"x": 10, "y": 12, "width": 30, "height": 20}}]}]}

    monkeypatch.setattr(local_ocr, "_invoke", recognize_fixture)
    result = local_ocr.recognize_image(image_path, crop=(40, 20, 40, 40), scale=2)
    assert image_path.read_bytes() == original
    assert result["source_sha256"] == hashlib.sha256(original).hexdigest()
    assert result["identity_verified"] is False
    assert result["lines"][0]["words"][0]["image_bounds"] == {"x": 45, "y": 26, "width": 15, "height": 10}
    assert all(not path.exists() for path in temporary_paths)


def test_local_ocr_rejects_outside_regions_before_recognition(tmp_path, monkeypatch):
    from PIL import Image
    from backend.collectors import local_ocr
    image_path = tmp_path / "fixture.png"
    Image.new("RGB", (100, 100), "white").save(image_path)
    monkeypatch.setattr(local_ocr, "_invoke", lambda *args, **kwargs: pytest.fail("invalid region reached OCR"))
    for crop in ((-1, 0, 40, 40), (70, 0, 40, 40), (0, 0, 0, 40), (0, 0, 40.5, 40)):
        with pytest.raises(ValueError):
            local_ocr.recognize_image(image_path, crop=crop)


def test_local_ocr_rotated_boxes_are_not_silently_used_as_source_coordinates(tmp_path, monkeypatch):
    from PIL import Image
    from backend.collectors import local_ocr
    image_path = tmp_path / "fixture.png"
    Image.new("RGB", (100, 100), "white").save(image_path)
    monkeypatch.setattr(local_ocr, "_invoke", lambda *args: {
        "width": 200, "height": 200, "text_angle": 2.4,
        "lines": [{"text": "fixture", "words": [{"text": "fixture", "bounds": {"x": 10, "y": 12, "width": 30, "height": 20}}]}]})
    result = local_ocr.recognize_image(image_path)
    assert result["lines"][0]["words"][0]["image_bounds"] is None
    assert any("不能用于自动点击" in issue for issue in result["issues"])
