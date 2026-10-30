"""Optional local RapidOCR engine for supplied pixels, with explicit transforms.

Run with the isolated OCR environment. This module performs no desktop capture,
UI input, source verification, message segmentation, or product interpretation.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import sys
import time

from PIL import Image, ImageOps


def prepare_image(path, crop=None, *, scale=2, padding=16):
    path = Path(path).resolve(strict=True)
    with Image.open(path) as source:
        size = source.size
        region = tuple(crop or (0, 0, *size))
        if len(region) != 4 or any(type(v) is not int for v in region):
            raise ValueError("Crop requires four integer coordinates")
        left, top, width, height = region
        if min(left, top) < 0 or min(width, height) <= 0 or left + width > size[0] or top + height > size[1]:
            raise ValueError("Crop lies outside the source pixels")
        if scale not in (1, 2, 3) or padding < 0 or padding > 64:
            raise ValueError("Unsupported preprocessing transform")
        if width * height * scale * scale > 20_000_000:
            raise ValueError("OCR input exceeds the pixel budget")
        selected = source.crop((left, top, left + width, top + height)).convert("RGB")
        if scale != 1:
            selected = selected.resize((width * scale, height * scale), Image.Resampling.LANCZOS)
        prepared = ImageOps.expand(selected, padding, "white")
        metadata = {"source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "source_dimensions": list(size), "source_format": source.format,
                    "crop": list(region), "scale": scale, "padding": padding,
                    "input_dimensions": list(prepared.size), "input_color_mode": "RGB",
                    "source_coordinate_formula": "source = crop_origin + (ocr_input - padding) / scale",
                    "screen_coordinate_mapping": "Not established from saved screenshots; requires current client capture geometry."}
        return prepared, metadata


class LocalRapidOCR:
    def __init__(self):
        import rapidocr
        from rapidocr import RapidOCR
        models = Path(rapidocr.__file__).parent / "models"
        paths = {"Det.model_path": models / "PP-OCRv6_det_small.onnx",
                 "Cls.model_path": models / "ch_ppocr_mobile_v2.0_cls_mobile.onnx",
                 "Rec.model_path": models / "PP-OCRv6_rec_small.onnx"}
        if not all(path.is_file() for path in paths.values()):
            raise RuntimeError("Bundled local OCR models are missing; runtime downloads are disabled")
        self.model_files = [{"name": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for path in paths.values()]
        self.engine = RapidOCR(params={**{key: str(path) for key, path in paths.items()},
                                      "Global.log_level": "warning", "EngineConfig.onnxruntime.intra_op_num_threads": 2,
                                      "EngineConfig.onnxruntime.inter_op_num_threads": 1})

    def recognize(self, path, *, crop=None, scale=2, padding=16, input_path=None, single_line=False):
        import numpy as np

        prepared, metadata = prepare_image(path, crop, scale=scale, padding=padding)
        if input_path:
            prepared.save(input_path, format="PNG")
        # RapidOCR accepts numpy arrays in OpenCV BGR convention.
        pixels = np.asarray(prepared)[:, :, ::-1].copy()
        started = time.perf_counter()
        result = self.engine(pixels, use_det=not single_line, use_cls=not single_line)
        elapsed = time.perf_counter() - started
        texts = result.txts or ()
        scores = result.scores or ()
        boxes = getattr(result, "boxes", None)
        boxes = boxes if boxes is not None else [None] * len(texts)
        left, top, width, height = metadata["crop"]
        lines = []
        for text, confidence, box in zip(texts, scores, boxes):
            if box is None:
                lines.append({"text": text, "confidence": float(confidence), "input_polygon": None,
                              "image_polygon": None, "inside_selected_region": None})
                continue
            polygon = [[float(x), float(y)] for x, y in box]
            image_polygon = [[left + (x - padding) / scale, top + (y - padding) / scale] for x, y in polygon]
            lines.append({"text": text, "confidence": float(confidence), "input_polygon": polygon,
                          "image_polygon": image_polygon,
                          "inside_selected_region": all(left <= x <= left + width and top <= y <= top + height for x, y in image_polygon)})
        return {**metadata, "engine": "RapidOCR/ONNXRuntime CPU", "version": importlib.metadata.version("rapidocr"),
                "text": "\n".join(texts), "lines": lines, "elapsed_seconds": elapsed,
                "model_files": self.model_files, "single_upright_line": single_line,
                "identity_verified": False, "record_segmentation_verified": False,
                "issues": ["本地文字识别仅提供文字与位置证据；来源身份、消息边界及媒体归属需另行验证。"]}


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument("--crop")
    parser.add_argument("--scale", type=int, default=2)
    parser.add_argument("--single-line", action="store_true", help="Recognize an already isolated upright text line; no detected boxes are reported")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    crop = tuple(map(int, args.crop.split(","))) if args.crop else None
    result = LocalRapidOCR().recognize(args.image, crop=crop, scale=args.scale, single_line=args.single_line)
    serialized = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(serialized, encoding="utf-8")
    else:
        print(serialized)


if __name__ == "__main__":
    main()
