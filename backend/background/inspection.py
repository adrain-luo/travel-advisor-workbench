"""Bounded OCR of explicit saved attachments, with no client or network access.

Text in the returned evidence is transient: callers may use it to decide a
record, but must not log or permanently archive excluded OCR/body content.
This module neither promotes nor deletes business data. The caller owns bounded
staging, receipts, retry policy and cleanup. OCR does not identify sources.
"""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import threading
import time

from PIL import Image, UnidentifiedImageError


MAX_BYTES = 32 * 1024 * 1024
MAX_PIXELS = 20_000_000
MAX_OCR_OUTPUT = 2 * 1024 * 1024
MIN_LINE_CONFIDENCE = 0.90
ROOT = Path(__file__).resolve().parents[2]


class InspectionError(RuntimeError):
    """Fixed safe reason code only."""


def _rapid_ocr(path, *, timeout):
    """Reuse the installed saved-image bridge, with no downloads or UI imports.

    Windows.Media.Ocr supplied no confidence and failed the earlier saved-image
    feasibility reference. It is deliberately not an acceptance fallback.
    The existing RapidOCR bridge requires all three local model files before
    engine construction and does not operate the desktop.
    """
    executable = Path(sys.executable)
    if not executable.is_file():
        raise InspectionError("LOCAL_RECOGNITION_UNAVAILABLE")
    arguments = [str(executable), "-m", "backend.collectors.rapid_ocr", str(path), "--scale", "1"]
    try:
        process = subprocess.Popen(arguments, cwd=str(ROOT), stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, shell=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except OSError:
        raise InspectionError("LOCAL_RECOGNITION_UNAVAILABLE") from None
    chunks, size, overflow = [], [0], threading.Event()
    def read():
        try:
            while True:
                chunk = process.stdout.read(65536)
                if not chunk:
                    break
                size[0] += len(chunk)
                if size[0] > MAX_OCR_OUTPUT:
                    overflow.set()
                    process.kill()
                    break
                chunks.append(chunk)
        except OSError:
            overflow.set()
    reader = threading.Thread(target=read, daemon=True, name="bounded-saved-image-ocr")
    reader.start()
    try:
        process.wait(timeout=max(0.05, timeout))
        reader.join(timeout=1)
        if overflow.is_set() or reader.is_alive():
            raise InspectionError("LOCAL_RECOGNITION_OUTPUT_LIMIT")
        if process.returncode:
            raise InspectionError("LOCAL_RECOGNITION_FAILED")
        try:
            value = json.loads(b"".join(chunks).decode("utf-8-sig"))
        except (UnicodeError, ValueError):
            raise InspectionError("LOCAL_RECOGNITION_INVALID_RESULT") from None
        if not isinstance(value, dict):
            raise InspectionError("LOCAL_RECOGNITION_INVALID_RESULT")
        return value
    except subprocess.TimeoutExpired:
        raise InspectionError("LOCAL_RECOGNITION_TIMEOUT") from None
    finally:
        if process.poll() is None:
            process.kill()
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass
        reader.join(timeout=1)
        if process.stdout:
            process.stdout.close()


def _saved_file(asset, root):
    locator = next((asset.get(k) for k in ("inspection_path", "path", "blob_path", "storage_path", "file_path") if asset.get(k)), None)
    if not isinstance(locator, (str, Path)):
        raise InspectionError("INSPECTION_BYTES_MISSING")
    candidate = Path(locator)
    candidate = candidate if candidate.is_absolute() else root / candidate
    try:
        candidate = candidate.resolve(strict=True)
        if not candidate.is_relative_to(root) or not candidate.is_file():
            raise InspectionError("INSPECTION_PATH_OUTSIDE_ALLOWED_ROOT")
        before = candidate.stat()
        if not 0 < before.st_size <= MAX_BYTES:
            raise InspectionError("INSPECTION_BYTE_LIMIT")
        with candidate.open("rb") as stream:
            content = stream.read(MAX_BYTES + 1)
        after = candidate.stat()
    except InspectionError:
        raise
    except OSError:
        raise InspectionError("INSPECTION_BYTES_UNREADABLE") from None
    if len(content) != before.st_size or (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise InspectionError("INSPECTION_BYTES_CHANGED")
    digest = hashlib.sha256(content).hexdigest()
    if not isinstance(asset.get("sha256"), str) or digest != asset["sha256"].lower():
        raise InspectionError("INSPECTION_BYTE_HASH_MISMATCH")
    return candidate, content, digest


def _reliable_text(value, digest):
    if value.get("source_sha256") != digest:
        raise InspectionError("INSPECTION_OCR_SOURCE_MISMATCH")
    selected = []
    for line in value.get("lines", [])[:5000]:
        confidence = line.get("confidence")
        if (isinstance(confidence, (int, float)) and not isinstance(confidence, bool)
                and MIN_LINE_CONFIDENCE <= confidence <= 1
                and line.get("inside_selected_region") is not False
                and isinstance(line.get("text"), str)):
            selected.append(line["text"][:2000])
    return "\n".join(selected)[:100_000]


def inspect_record(record, *, allowed_root, ocr=None, max_images=3, timeout_seconds=20):
    """Inspect at most max_images explicitly associated, already saved files.

    ocr is an optional saved-image recognizer(path, timeout=float) callback. It
    must return source_sha256 and lines with text/confidence; unscored OCR cannot
    establish a product. Default is the existing isolated local RapidOCR engine.
    No source text, contact name, filename or directory is used as visual proof.
    The total deadline includes all OCR calls. A caller-supplied callback must
    honor its timeout; the default subprocess enforces it.
    """
    if not isinstance(record, dict) or type(max_images) is not int or not 1 <= max_images <= 10:
        raise ValueError("INSPECTION_REQUEST_INVALID")
    if not isinstance(timeout_seconds, (int, float)) or not 0 < timeout_seconds <= 30:
        raise ValueError("INSPECTION_DEADLINE_INVALID")
    root = Path(allowed_root).resolve(strict=True)
    started = time.monotonic()
    deadline = started + timeout_seconds
    assets = [a for a in record.get("attachments", []) if isinstance(a, dict) and not a.get("retired")]
    images = []
    metrics = {"ocr_operations": 0, "media_inspected": 0, "bytes_inspected": 0}
    recognizer = ocr or _rapid_ocr
    for index, asset in enumerate(assets):
        item = {"index": asset.get("media_index", asset.get("index", index)),
                "sha256": asset.get("sha256"), "state": "UNRESOLVED", "text": "",
                "trusted_for_rules": False, "reason_code": "INSPECTION_LIMIT_REACHED"}
        images.append(item)
        classification = asset.get("classification") or {}
        if (classification.get("origin") in {"manual", "inspection"}
                and classification.get("label") in {"scenic_personal", "travel_sharing", "other", "irrelevant"}):
            item.update(state="CONFIRMED_NONPRODUCT", reason_code="TRUSTED_NONPRODUCT_CLASSIFICATION")
            continue
        if metrics["media_inspected"] >= max_images or time.monotonic() >= deadline:
            continue
        try:
            path, content, digest = _saved_file(asset, root)
            metrics["media_inspected"] += 1
            metrics["bytes_inspected"] += len(content)
            item["sha256"] = digest
            try:
                with Image.open(io.BytesIO(content)) as image:
                    if image.width * image.height > MAX_PIXELS or min(image.size) < 1:
                        raise InspectionError("INSPECTION_PIXEL_LIMIT")
                    image.verify()
                with Image.open(io.BytesIO(content)) as image:
                    image.load()
            except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning):
                if asset.get("type") in {"document", "file"} and not str(asset.get("mime", "")).startswith("image/"):
                    item.update(state="UNRESOLVED", reason_code="DOCUMENT_RECOGNITION_UNAVAILABLE")
                    continue
                raise InspectionError("INSPECTION_IMAGE_UNREADABLE") from None
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                continue
            metrics["ocr_operations"] += 1
            value = recognizer(path, timeout=remaining)
            text = _reliable_text(value, digest)
            # The bridge hashes source bytes. Recheck after its call as well to
            # reject an altered supplied file, without accepting stale OCR.
            if path.stat().st_size != len(content) or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise InspectionError("INSPECTION_BYTES_CHANGED")
            item.update(state="RECOGNIZED", text=text, trusted_for_rules=bool(text),
                        reason_code="HIGH_CONFIDENCE_LOCAL_TEXT" if text else "NO_RELIABLE_LOCAL_TEXT")
        except InspectionError as error:
            code = str(error)
            acquisition = code.startswith("INSPECTION_") and code != "INSPECTION_OCR_SOURCE_MISMATCH"
            item.update(state="ACQUISITION_FAILED" if acquisition else "UNRESOLVED", reason_code=code)
        except (OSError, ValueError, TypeError, KeyError):
            item.update(state="UNRESOLVED", reason_code="LOCAL_RECOGNITION_FAILED")
    states = {i["state"] for i in images}
    status = "ACQUISITION_FAILED" if "ACQUISITION_FAILED" in states else (
        "COMPLETED" if states <= {"RECOGNIZED", "CONFIRMED_NONPRODUCT"} else "PARTIAL")
    return {"event_key": record.get("event_key"),
            "source_revision_hash": record.get("source_revision_hash") or record.get("source_revision"),
            "status": status, "images": images, "metrics": metrics,
            "elapsed_seconds": round(time.monotonic() - started, 3), "deadline_seconds": timeout_seconds,
            "captures_desktop": False, "network_access": False, "temporary_evidence": True}
