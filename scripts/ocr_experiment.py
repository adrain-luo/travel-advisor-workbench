"""Evaluate one local Chinese OCR engine on labeled, previously saved pixels.

No live desktop access and no application data changes. Run using
.local/ocr-env/Scripts/python.exe; --prepare-only needs Pillow only.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from backend.collectors.rapid_ocr import LocalRapidOCR, prepare_image


SAMPLES = [
    {"id": "group_header", "file": "group-history-timestamps.png", "crop": [0, 0, 563, 44], "role": "source_identity", "expected": ["芜湖联众芜湖同业群", "聊天记录", "497"]},
    {"id": "group_time", "file": "group-history-timestamps.png", "crop": [395, 150, 160, 45], "role": "publication_time", "expected": ["2026年10月25日21:55"]},
    {"id": "moments_author", "file": "moments-post-detail.png", "crop": [880, 140, 430, 45], "role": "source_identity", "expected": ["完美新疆西北赵照18552600189"]},
    {"id": "moments_time", "file": "moments-post-detail.png", "crop": [930, 550, 200, 45], "role": "publication_time", "expected": ["昨天09:07"]},
    {"id": "group_boundary", "file": "group-history-timestamps.png", "crop": [20, 145, 530, 370], "role": "message_boundaries", "expected": ["联众吕若兰", "2026年10月25日21:55"], "visual_annotation": {"visible_occurrences": 2, "second_occurrence_partial": True, "media_rectangle_image_pixels": [71, 183, 112, 244]}},
    {"id": "moments_boundaries", "file": "moments-album-page1.png", "crop": [875, 195, 560, 480], "role": "post_boundaries", "expected": ["昨天", "纯净双湖", "伊段时光", "双湖之恋"], "visual_annotation": {"visible_cards": 3, "thumbnail_rectangles_image_pixels": [[955, 216, 144, 142], [955, 367, 144, 143], [955, 519, 144, 143]], "media_set_completeness": "unknown"}},
    {"id": "group_thumbnail", "file": "group-history-timestamps.png", "crop": [71, 183, 112, 244], "role": "thumbnail_not_viewer", "expected": ["庐江温泉", "128"]},
    {"id": "moments_thumbnail", "file": "moments-post-detail.png", "crop": [938, 303, 145, 248], "role": "thumbnail_not_viewer", "expected": ["7980"], "visual_annotation": {"display_is_cropped_poster": True, "complete_media_count": "unknown"}},
    {"id": "wrong_state_document_filter", "file": "group-documents-empty.png", "crop": [235, 400, 100, 55], "role": "wrong_state", "expected": ["无内容"], "visual_annotation": {"expected_state": "empty_document_filter", "must_not_treat_as_history_endpoint": True}},
    {"id": "ambiguous_truncated_contact_header", "file": "moments-album-page1.png", "crop": [1035, 82, 250, 43], "role": "ambiguous_identity", "expected": [], "forbidden_full_identity": "完美新疆西北赵照18552600189", "visual_annotation": {"header_truncated": True, "sufficient_for_identity_alone": False}},
    {"id": "wrong_source_group_header_for_moments", "file": "group-selected-page1.png", "crop": [305, 32, 250, 44], "role": "wrong_source", "expected": ["芜湖联众芜湖同业群"], "forbidden_full_identity": "完美新疆西北赵照18552600189"},
]


def normalized(text):
    return re.sub(r"\s+", "", text).replace("：", ":")


def run(source_dir, output_dir, prepare_only=False):
    output_dir.mkdir(parents=True, exist_ok=True)
    report = {"schema_version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
              "mode": "saved_image_only", "desktop_capture": False, "desktop_input": False,
              "online_product_ai": False, "engine": "RapidOCR 3.9.2 / ONNXRuntime CPU",
              "primary_docs": ["https://rapidai.github.io/RapidOCRDocs/v3.9.2/install_usage/rapidocr/install/", "https://rapidai.github.io/RapidOCRDocs/v3.9.2/install_usage/rapidocr/usage/"],
              "preprocessing": "RGB, 2x LANCZOS, 16px white border; no threshold or grayscale; exactly one pipeline",
              "scoring": "Exact expected substring after whitespace/colon normalization; no fuzzy identity acceptance. Model confidence is not correctness.",
              "sample_annotations": "Human inspection of saved pixels; annotations are evaluation labels, not algorithm outputs.",
              "screen_mapping": "Only OCR-input to source-image mapping established; live screen/client/DPI mapping is outside this experiment.",
              "unavailable_samples": [{"role": "actual_media_viewer_or_save_dialog", "status": "NOT_TESTED", "reason": "No saved screenshot of an open media viewer or Save As dialog in the supplied evidence."}],
              "observations": []}
    engine = None if prepare_only else LocalRapidOCR()
    for sample in SAMPLES:
        input_path = output_dir / (sample["id"] + "-input.png")
        path = source_dir / sample["file"]
        if prepare_only:
            prepared, result = prepare_image(path, sample["crop"])
            prepared.save(input_path)
        else:
            result = engine.recognize(path, crop=sample["crop"], input_path=input_path)
        result["input_sha256"] = hashlib.sha256(input_path.read_bytes()).hexdigest()
        result["input_file"] = input_path.name
        text = normalized(result.get("text", ""))
        checks = [{"expected": expected, "recognized_exactly": normalized(expected) in text} for expected in sample["expected"]]
        observation = {**sample, "ocr": result, "checks": checks,
                       "all_expected_text_present": all(check["recognized_exactly"] for check in checks) if checks and not prepare_only else None,
                       "segmentation_status": "NOT_ESTABLISHED_BY_OCR", "source_verification_status": "NOT_ESTABLISHED_BY_OCR"}
        if sample.get("forbidden_full_identity"):
            observation["false_full_identity_detected"] = normalized(sample["forbidden_full_identity"]) in text
        report["observations"].append(observation)
        (output_dir / "results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"id": sample["id"], "text": result.get("text"), "all_expected_text_present": observation["all_expected_text_present"]}, ensure_ascii=False), flush=True)
    if not prepare_only:
        report["packages"] = {name: importlib.metadata.version(name) for name in ("rapidocr", "onnxruntime", "numpy", "opencv-python", "Pillow")}
        report["text_checks_passed"] = sum(check["recognized_exactly"] for observation in report["observations"] for check in observation["checks"])
        report["text_checks_total"] = sum(len(observation["checks"]) for observation in report["observations"])
        report["conclusion"] = "Recognition scores apply only to these saved crops. Source/session verification, segmentation, media association, viewer navigation and live collection require independent evidence."
        (output_dir / "results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def precise_line_probe(source_dir, output_dir):
    """Test one specific hypothesis: remove neighboring graphics and rotation.

    These are manually labeled text-line crops, not an automatic line selector.
    A successful result cannot establish general page segmentation.
    """
    engine = LocalRapidOCR()
    samples = [("author", "moments-post-detail.png", (935, 149, 230, 26), "完美新疆西北赵照18552600189"),
               ("time", "moments-post-detail.png", (935, 561, 85, 26), "昨天09:07"),
               ("empty", "group-documents-empty.png", (250, 413, 65, 31), "无内容")]
    results = []
    for name, filename, crop, expected in samples:
        result = engine.recognize(source_dir / filename, crop=crop, single_line=True,
                                  input_path=output_dir / (name + "-precise-input.png"))
        results.append({"target": name, "expected": expected, "recognized_exactly": normalized(result["text"]) == normalized(expected), "result": result})
    (output_dir / "precise-upright-line-probe.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    return results


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=ROOT / ".local/live-evidence")
    parser.add_argument("--output-dir", type=Path, default=ROOT / ".local/ocr-experiment-2026-10-28")
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--precise-line-probe", action="store_true")
    args = parser.parse_args()
    if args.precise_line_probe:
        precise_line_probe(args.source_dir, args.output_dir)
    else:
        run(args.source_dir, args.output_dir, args.prepare_only)
