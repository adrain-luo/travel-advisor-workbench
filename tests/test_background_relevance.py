"""Deterministic relevance fixtures; no business data or live client access."""
import json

import pytest

from backend.background.relevance import decide, RULE_VERSION


@pytest.mark.parametrize("text", [
    "云南双飞六日游，纯玩团，含酒店和接送，欢迎报名",
    "团期 11月8日，成人价格: 2580，儿童价: 1800",
    "行程安排\nD1 昆明接机\nD2 石林游览\nD3 大理游览",
    "该旅游套餐费用包含住宿和早餐，不含单房差",
    "7月8日出团取消，调整到7月10日，已订客人可退定金",
    "东北旅游线路报价更正为每人3800元，单房差另计",
    "10月12日旅行团仅剩3位",
    "精品六日游，纯玩小团，含酒店、餐饮和交通",
    "西安五日游 1999元",
    "7-day tour includes hotel and breakfast. Price: $899",
])
def test_product_information_kept_without_requiring_price(text):
    value = decide({"text": text, "publication_time": "2020-01-01T00:00:00+08:00"})
    assert value["outcome"] == "KEEP_PRODUCT_RELEVANT"
    assert value["rule_version"] == RULE_VERSION and not value["needs_inspection"]
    assert "bookable" not in json.dumps(value) and "2020" not in json.dumps(value)


@pytest.mark.parametrize("text", ["你好", "好的", "谢谢", "👍😊", "云南", "18955311550", "杭州今天下雨", "今天去公园，太美了", "照片拍得不错", "800元", "还剩3位", "晚饭一起吃吗"])
def test_ordinary_chat_destination_phone_or_unlinked_price_not_material(text):
    value = decide({"text": text, "friend_name": "云南旅游18955311550", "type": "text"})
    assert value["outcome"] == "SKIP_IRRELEVANT"
    assert value["context_event_key"] is None and not value["needs_inspection"]


def test_only_explicit_same_source_product_reply_has_context():
    record = {"event_key": "child", "account_id": "a", "source_id": "s", "conversation_id": "c",
              "text": "800元", "reply_to_event_key": "parent"}
    context = {"relationship_verified": True, "relationship": "explicit_reply", "parent_event_key": "parent",
               "parent_outcome": "KEEP_PRODUCT_RELEVANT", "account_id": "a", "source_id": "s", "conversation_id": "c"}
    assert decide(record, reply_context=context)["context_event_key"] == "parent"
    assert decide(record, reply_context=context)["outcome"] == "KEEP_PRODUCT_RELEVANT"
    for altered in ({"relationship": "temporal_proximity"}, {"relationship_verified": False},
                    {"account_id": "other"}, {"parent_outcome": "PENDING_RELEVANCE"}, {"parent_event_key": "elsewhere"}):
        assert decide(record, reply_context={**context, **altered})["outcome"] == "SKIP_IRRELEVANT"
    assert decide({**record, "text": "谢谢"}, reply_context=context)["outcome"] == "SKIP_IRRELEVANT"


def test_known_inspection_reference_and_manual_decisions_preserved():
    labels = ["travel_promotion"] * 2 + ["travel_sharing"] * 2 + ["other"] * 3 + ["uncertain"]
    results = [decide({"text": "", "classification": {"origin": "inspection", "label": label},
        "attachments": [{"classification": {"origin": "inspection", "label": "scenic_personal"}}]})["outcome"] for label in labels]
    assert results.count("KEEP_PRODUCT_RELEVANT") == 2
    assert results.count("SKIP_IRRELEVANT") == 5
    assert results.count("PENDING_RELEVANCE") == 1
    assert decide({"text": "旅游团仅剩3位", "classification": {"origin": "manual", "label": "other"}})["outcome"] == "SKIP_IRRELEVANT"
    assert decide({"text": "你好", "classification": {"origin": "rule", "label": "travel_promotion"}})["outcome"] == "SKIP_IRRELEVANT"


def test_image_only_inspection_is_hash_and_revision_bound():
    record = {"event_key": "one", "source_revision_hash": "rev", "text": "", "attachments": [{"sha256": "a" * 64}]}
    assert decide(record)["needs_inspection"]
    evidence = {"event_key": "one", "source_revision_hash": "rev", "status": "COMPLETED",
        "images": [{"sha256": "a" * 64, "state": "RECOGNIZED", "trusted_for_rules": True,
                    "text": "云南双飞六日游，含酒店早餐，团期11月8日"}], "metrics": {"ocr_operations": 1, "media_inspected": 1}}
    result = decide(record, inspection=evidence)
    assert result["outcome"] == "KEEP_PRODUCT_RELEVANT" and result["reason_code"] == "OCR_PRODUCT_EVIDENCE"
    assert result["metrics"]["ocr_operations"] == 1 and "云南" not in json.dumps(result, ensure_ascii=False)
    for changed in ({"event_key": "other"}, {"source_revision_hash": "old"}):
        assert decide(record, inspection={**evidence, **changed})["outcome"] == "PENDING_RELEVANCE"
    evidence["images"][0]["sha256"] = "b" * 64
    assert decide(record, inspection=evidence)["outcome"] == "PENDING_RELEVANCE"


def test_image_failure_not_irrelevance_and_no_text_not_scenic_proof():
    record = {"event_key": "one", "text": "谢谢", "attachments": [{"sha256": "a" * 64}]}
    for state, expected in (("ACQUISITION_FAILED", "RETRY_ACQUISITION"), ("UNRESOLVED", "PENDING_RELEVANCE"), ("RECOGNIZED", "PENDING_RELEVANCE")):
        evidence = {"event_key": "one", "images": [{"sha256": "a" * 64, "state": state, "text": "", "trusted_for_rules": False}]}
        assert decide(record, inspection=evidence)["outcome"] == expected


def test_positive_text_can_decide_before_optional_attachment_download():
    result = decide({"text": "旅游团10月8日出发，余位3人", "attachments": [{"state": "UNAVAILABLE"}]})
    assert result["outcome"] == "KEEP_PRODUCT_RELEVANT" and not result["needs_inspection"]


def test_native_reply_server_id_resolves_only_with_bound_native_account():
    record = {"event_key": "child", "account_id": "business-account", "source_id": "s", "conversation_id": "friend", "text": "还剩3位",
              "reply": {"relationship": "explicit_reply", "relationship_verified": True, "native_server_id": "123456789012345678",
                        "account_id": "native-account", "conversation_id": "friend"}}
    context = {"relationship_verified": True, "relationship": "explicit_reply", "parent_event_key": "parent",
               "parent_outcome": "KEEP_PRODUCT_RELEVANT", "account_id": "business-account", "source_id": "s", "conversation_id": "friend",
               "account_native_id": "native-account", "parent_native_id": "123456789012345678"}
    assert decide(record, reply_context=context)["context_event_key"] == "parent"
    assert decide(record, reply_context={**context, "account_native_id": "elsewhere"})["outcome"] == "SKIP_IRRELEVANT"
