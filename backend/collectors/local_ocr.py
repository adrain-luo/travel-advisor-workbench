"""Local OCR for explicitly supplied images; never captures or operates desktop UI.

OCR text and word boxes are evidence for a future calibrated visual driver.
They are not verified source identity, message boundaries, or scan coverage.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import platform
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

from .base import CollectorBlocked


def _invoke(arguments: list[str], timeout: float = 20) -> dict:
    if platform.system() != "Windows":
        raise CollectorBlocked("本地文字识别需要 Windows 桌面系统。", "LOCAL_OCR_WINDOWS_REQUIRED")
    shell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    helper = Path(__file__).with_name("windows_ocr.ps1")
    try:
        result = subprocess.run(
            [str(shell), "-NoLogo", "-NoProfile", "-NonInteractive", "-File", str(helper), *arguments],
            capture_output=True, encoding="utf-8-sig", timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW, check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise CollectorBlocked("本地文字识别超时，请缩小选定区域后重试。", "LOCAL_OCR_TIMEOUT") from exc
    except OSError as exc:
        raise CollectorBlocked("无法启动 Windows 本地文字识别组件。", "LOCAL_OCR_UNAVAILABLE") from exc
    if result.returncode:
        raise CollectorBlocked("Windows 本地文字识别失败，请检查已安装的识别语言及图片大小。", "LOCAL_OCR_FAILED")
    try:
        return json.loads(result.stdout)
    except ValueError as exc:
        raise CollectorBlocked("本地文字识别返回了无法读取的结果。", "LOCAL_OCR_INVALID_RESULT") from exc


def probe_local_ocr() -> dict:
    """Query installed recognition languages without opening the desktop."""
    result = _invoke(["-ListLanguages"])
    return {"engine": "Windows.Media.Ocr", **result, "captures_desktop": False}


def recognize_image(path: str | Path, *, crop: tuple[int, int, int, int] | None = None,
                    scale: int = 2, language: str = "zh-Hans-CN", timeout: float = 20) -> dict:
    """Recognize one selected region; preserve input bytes and actual word bounds.

    `crop` is (left, top, width, height) in source-image pixels. Scaling is an
    explicit local preprocessing step, not a claim of improved factual accuracy.
    Native OCR supplies no word confidence score. Rotated boxes are not mapped
    back to source pixels without a verified inverse transform.
    """
    if scale not in (1, 2, 3):
        raise ValueError("OCR scale must be 1, 2, or 3")
    path = Path(path).resolve(strict=True)
    original = path.read_bytes()
    source_hash = hashlib.sha256(original).hexdigest()
    with Image.open(io.BytesIO(original)) as source:
        width, height = source.size
        region = crop or (0, 0, width, height)
        if len(region) != 4 or any(type(value) is not int for value in region):
            raise ValueError("OCR region requires four integer pixel coordinates")
        left, top, region_width, region_height = region
        if min(left, top) < 0 or min(region_width, region_height) <= 0 or left + region_width > width or top + region_height > height:
            raise ValueError("OCR region must stay inside the supplied image")
        if region_width * region_height * scale * scale > 30_000_000:
            raise ValueError("OCR region exceeds the bounded preprocessing budget")
        selected = source.crop((left, top, left + region_width, top + region_height)).convert("RGB")
        if scale != 1:
            selected = selected.resize((region_width * scale, region_height * scale), Image.Resampling.LANCZOS)
        with tempfile.TemporaryDirectory(prefix="travel-ocr-") as temporary:
            local_image = Path(temporary) / "selected-region.png"
            selected.save(local_image)
            result = _invoke(["-ImagePath", str(local_image), "-Language", language], timeout)
    if (result.get("width"), result.get("height")) != (region_width * scale, region_height * scale):
        raise CollectorBlocked("识别结果与选定区域尺寸不一致，不能用于定位。", "LOCAL_OCR_DIMENSION_MISMATCH")
    angle = result.get("text_angle")
    mapped = angle in (None, 0, 0.0)
    for line in result.get("lines", []):
        for word in line.get("words", []):
            bounds = word["bounds"]
            word["image_bounds"] = ({"x": left + bounds["x"] / scale, "y": top + bounds["y"] / scale,
                                     "width": bounds["width"] / scale, "height": bounds["height"] / scale}
                                    if mapped else None)
    return {**result, "engine": "Windows.Media.Ocr", "source_sha256": source_hash,
            "source_dimensions": {"width": width, "height": height},
            "crop": {"left": left, "top": top, "width": region_width, "height": region_height},
            "scale": scale, "origin": "local_ocr_transcription", "identity_verified": False,
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "issues": ["文字识别结果需核对，不能单独证明微信来源身份、消息边界或历史覆盖。"] +
                      ([] if mapped else ["识别结果存在旋转角度，尚未换算到原图坐标，不能用于自动点击。"])}


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", nargs="?")
    parser.add_argument("--crop", help="left,top,width,height in source-image pixels")
    parser.add_argument("--scale", type=int, default=2)
    parser.add_argument("--probe", action="store_true")
    args = parser.parse_args()
    if args.probe:
        output = probe_local_ocr()
    elif args.image:
        output = recognize_image(args.image, crop=tuple(map(int, args.crop.split(","))) if args.crop else None, scale=args.scale)
    else:
        parser.error("provide an image path or --probe")
    print(json.dumps(output, ensure_ascii=False))
