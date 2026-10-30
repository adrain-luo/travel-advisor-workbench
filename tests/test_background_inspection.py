"""Supplied-image inspection fixtures; no WeChat or external OCR execution."""
import hashlib

from PIL import Image
import pytest

from backend.background.inspection import inspect_record, InspectionError
from backend.background.relevance import decide


def image_record(tmp_path, count=1):
    assets = []
    for index in range(count):
        path = tmp_path / (str(index) + ".png")
        Image.new("RGB", (32, 32), "white").save(path)
        assets.append({"path": path.name, "type": "image", "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "index": index})
    return {"event_key": "fixture", "text": "", "attachments": assets}


def text_ocr(path, *, timeout):
    assert 0 < timeout <= 20
    return {"source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "lines": [{"text": "品质六日游，含酒店早餐，10月8日出团", "confidence": .98}]}


def test_image_only_flyer_reaches_local_recognition(tmp_path):
    record = image_record(tmp_path)
    assert decide(record)["needs_inspection"]
    evidence = inspect_record(record, allowed_root=tmp_path, ocr=text_ocr)
    assert evidence["metrics"]["ocr_operations"] == 1
    assert evidence["metrics"]["media_inspected"] == 1
    assert decide(record, inspection=evidence)["outcome"] == "KEEP_PRODUCT_RELEVANT"
    assert not evidence["captures_desktop"] and not evidence["network_access"]


@pytest.mark.parametrize("kind", ["missing", "hash", "outside", "unreadable"])
def test_bytes_failure_is_acquisition_not_relevance(tmp_path, kind):
    allowed = tmp_path / "inspection"; allowed.mkdir()
    record = image_record(allowed)
    asset = record["attachments"][0]
    if kind == "missing":
        (allowed / asset["path"]).unlink()
    elif kind == "hash":
        asset["sha256"] = "f" * 64
    elif kind == "outside":
        path = tmp_path / "outside.png"
        Image.new("RGB", (32, 32)).save(path)
        asset["path"] = str(path)
    else:
        path = allowed / asset["path"]; path.write_bytes(b"not an image")
        asset["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    evidence = inspect_record(record, allowed_root=allowed, ocr=lambda *a, **kw: pytest.fail("invalid bytes reached OCR"))
    assert evidence["metrics"]["ocr_operations"] == 0
    assert decide(record, inspection=evidence)["outcome"] == "RETRY_ACQUISITION"


@pytest.mark.parametrize("kind", ["unavailable", "unscored", "low", "empty"])
def test_unavailable_or_unreliable_recognition_stays_pending(tmp_path, kind):
    record = image_record(tmp_path)
    def ocr(path, **kw):
        if kind == "unavailable":
            raise InspectionError("LOCAL_RECOGNITION_UNAVAILABLE")
        result = text_ocr(path, **kw)
        if kind == "unscored":
            result["lines"][0].pop("confidence")
        elif kind == "low":
            result["lines"][0]["confidence"] = .4
        else:
            result["lines"] = []
        return result
    evidence = inspect_record(record, allowed_root=tmp_path, ocr=ocr)
    assert decide(record, inspection=evidence)["outcome"] == "PENDING_RELEVANCE"


def test_count_bound_and_confirmed_nonproduct_dont_repeat_ocr(tmp_path):
    record = image_record(tmp_path, 4)
    first = record["attachments"][0]
    first["classification"] = {"origin": "inspection", "label": "scenic_personal"}
    evidence = inspect_record(record, allowed_root=tmp_path, ocr=text_ocr, max_images=2)
    assert evidence["metrics"]["ocr_operations"] == 2
    assert evidence["images"][0]["state"] == "CONFIRMED_NONPRODUCT"
    assert evidence["images"][-1]["reason_code"] == "INSPECTION_LIMIT_REACHED"


def test_document_bytes_without_recognizer_not_discarded(tmp_path):
    path = tmp_path / "scan.pdf"; path.write_bytes(b"%PDF-fixture")
    record = {"event_key": "document", "attachments": [{"path": path.name, "type": "file", "mime": "application/pdf",
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}]}
    evidence = inspect_record(record, allowed_root=tmp_path, ocr=text_ocr)
    assert evidence["images"][0]["reason_code"] == "DOCUMENT_RECOGNITION_UNAVAILABLE"
    assert decide(record, inspection=evidence)["outcome"] == "PENDING_RELEVANCE"
