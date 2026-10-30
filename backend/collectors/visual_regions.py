"""Conservative photo-region candidates from explicitly supplied source pixels.

This local Pillow-only helper does not capture the desktop, identify a source,
segment posts, associate media, or authorize clicks. The caller supplies the
already verified source pane and its content-only body bounds.
"""
from __future__ import annotations

import argparse
from collections import deque
import hashlib
import io
import json
from pathlib import Path
import sys

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps, ImageStat


def _region(value, size, name):
    if len(value) != 4 or any(type(v) is not int for v in value):
        raise ValueError(f"{name} requires integer left, top, width, height")
    left, top, width, height = value
    if min(left, top) < 0 or min(width, height) <= 0 or left + width > size[0] or top + height > size[1]:
        raise ValueError(f"{name} must stay inside its parent region")
    return left, top, width, height


def _components(mask):
    width, height = mask.size
    values = bytearray(mask.tobytes())
    for start, active in enumerate(values):
        if not active:
            continue
        values[start] = 0
        queue = deque([start])
        x0 = x1 = start % width
        y0 = y1 = start // width
        count = 0
        while queue:
            item = queue.popleft()
            x, y = item % width, item // width
            x0, x1, y0, y1 = min(x0, x), max(x1, x), min(y0, y), max(y1, y)
            count += 1
            for yy in range(max(0, y - 1), min(height, y + 2)):
                for xx in range(max(0, x - 1), min(width, x + 2)):
                    index = yy * width + xx
                    if values[index]:
                        values[index] = 0
                        queue.append(index)
        yield (x0, y0, x1 + 1, y1 + 1), count


def _runs(values, threshold):
    active = [value >= threshold for value in values]
    # Fill isolated two-pixel holes, but retain the larger gaps between cards.
    for index in range(1, len(active) - 1):
        if active[index - 1] and active[index + 1]:
            active[index] = True
    start = None
    for index, value in enumerate([*active, False]):
        if value and start is None:
            start = index
        elif not value and start is not None:
            yield start, index
            start = None


def _dense_rectangles(mask, bounds, minimum):
    """Break sparse emoji bridges using row/column color occupancy."""
    x0, y0, x1, y1 = bounds
    width, height = x1 - x0, y1 - y0
    pixels = mask.crop(bounds).tobytes()
    rows = [sum(bool(value) for value in pixels[y * width:(y + 1) * width]) for y in range(height)]
    for top, bottom in _runs(rows, max(minimum * .4, width * .35)):
        if bottom - top < minimum:
            continue
        columns = [sum(bool(pixels[y * width + x]) for y in range(top, bottom)) for x in range(width)]
        for left, right in _runs(columns, (bottom - top) * .35):
            if right - left < minimum:
                continue
            count = sum(bool(pixels[y * width + x]) for y in range(top, bottom) for x in range(left, right))
            yield (x0 + left, y0 + top, x0 + right, y0 + bottom), count


def find_thumbnail_candidates(path: str | Path, *, pane: tuple[int, int, int, int],
                              body_bounds: tuple[int, int, int, int],
                              min_size: int = 50, max_candidates: int = 20) -> dict:
    """Return colored rectangular candidates; coordinates are saved-image pixels.

    `pane` is left/top/width/height in the source image. `body_bounds` is relative
    to that pane and must exclude toolbars and unrelated conversations. Small
    avatars and emoji are rejected by size; dull/monochrome images may be missed.
    A candidate does not establish that a media viewer can be opened safely.
    """
    if type(min_size) is not int or min_size < 50 or min_size > 300:
        raise ValueError("Minimum candidate size must be 50 to 300 source pixels")
    if type(max_candidates) is not int or not 1 <= max_candidates <= 50:
        raise ValueError("Candidate limit must be 1 to 50")
    path = Path(path).resolve(strict=True)
    raw = path.read_bytes()
    with Image.open(io.BytesIO(raw)) as opened:
        source_format = opened.format
        image = opened.convert("RGB")
    px, py, pw, ph = _region(pane, image.size, "Pane")
    bx, by, bw, bh = _region(body_bounds, (pw, ph), "Body")
    if bw * bh > 8_000_000:
        raise ValueError("Body exceeds the bounded pixel budget")
    origin_x, origin_y = px + bx, py + by
    body = image.crop((origin_x, origin_y, origin_x + bw, origin_y + bh))
    red, green, blue = body.split()
    maximum = ImageChops.lighter(ImageChops.lighter(red, green), blue)
    minimum = ImageChops.darker(ImageChops.darker(red, green), blue)
    colorful = ImageChops.subtract(maximum, minimum).point(lambda v: 255 if v >= 28 else 0)
    # Two-pixel cells retain small inter-card gaps. Closing repairs tiny holes,
    # but deliberately does not join separate cards across ordinary row gaps.
    stride = 2
    padded = ImageOps.expand(colorful, (0, 0, bw % stride, bh % stride), 0)
    grid = padded.resize((padded.width // stride, padded.height // stride), Image.Resampling.BOX)
    grid = grid.point(lambda v: 255 if v >= 48 else 0)
    grid = grid.filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.MinFilter(3))
    candidates = []
    rectangles = []
    for bounds, count in _components(grid):
        if min(bounds[2] - bounds[0], bounds[3] - bounds[1]) * stride >= min_size:
            rectangles.extend(_dense_rectangles(grid, bounds, min_size / stride))
    for (x0, y0, x1, y1), count in rectangles:
        left, top, right, bottom = x0 * stride, y0 * stride, min(bw, x1 * stride), min(bh, y1 * stride)
        width, height = right - left, bottom - top
        if min(width, height) < min_size or max(width / height, height / width) > 6:
            continue
        component_fill = count / ((x1 - x0) * (y1 - y0))
        patch = body.crop((left, top, right, bottom))
        color_fraction = ImageStat.Stat(colorful.crop((left, top, right, bottom))).mean[0] / 255
        # Ignore the coarse-mask border so a solid colored UI block does not
        # acquire false texture from a two-pixel white perimeter.
        texture_stddev = ImageStat.Stat(patch.crop((3, 3, width - 3, height - 3)).convert("L")).stddev[0]
        if component_fill < .38 or color_fraction < .20 or texture_stddev < 20:
            continue
        image_bounds = [origin_x + left, origin_y + top, width, height]
        encoded = io.BytesIO()
        patch.save(encoded, format="PNG")
        candidates.append({"candidate_only": True, "image_bounds": image_bounds,
                           "extent_kind": "colored_texture_region", "full_thumbnail_bounds_verified": False,
                           "pane_bounds": [bx + left, by + top, width, height],
                           "body_bounds": [left, top, width, height],
                           "crop_sha256": hashlib.sha256(encoded.getvalue()).hexdigest(), "crop_hash_encoding": "PNG RGB",
                           "pixel_sha256": hashlib.sha256(patch.tobytes()).hexdigest(),
                           "component_fill": round(component_fill, 4), "color_fraction": round(color_fraction, 4),
                           "texture_stddev": round(texture_stddev, 3),
                           "touches_body_edge": left <= stride or top <= stride or right >= bw - stride or bottom >= bh - stride,
                           "post_association": None, "click_verified": False})
    candidates.sort(key=lambda c: (c["image_bounds"][1], c["image_bounds"][0]))
    total = len(candidates)
    return {"schema_version": 1, "method": "color-components-pillow-v1", "candidate_only": True,
            "source_sha256": hashlib.sha256(raw).hexdigest(), "source_format": source_format,
            "source_dimensions": list(image.size), "pane": list(pane), "body": list(body_bounds),
            "coordinate_space": "source_image_pixels", "screen_mapping_verified": False,
            "candidates": candidates[:max_candidates], "candidate_count_before_limit": total,
            "limit_reached": total > max_candidates, "source_records_created": 0,
            "issues": ["仅为彩色图片区域候选，不能据此确定帖子边界、媒体归属、完整张数或安全点击位置。", "灰度、低饱和或过小图片可能漏检；候选须由采集器结合当前来源和窗口状态核验。"]}


def annotate_candidates(path: str | Path, result: dict, output: str | Path):
    """Save review annotations without changing the source pixels or image file."""
    with Image.open(path) as source:
        image = source.convert("RGB")
    draw = ImageDraw.Draw(image)
    for index, candidate in enumerate(result["candidates"], 1):
        x, y, width, height = candidate["image_bounds"]
        draw.rectangle((x, y, x + width - 1, y + height - 1), outline="#e60046", width=3)
        draw.text((x + 3, y + 3), f"Candidate {index}", fill="white", stroke_width=2, stroke_fill="black")
    image.save(output, format="PNG")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument("--pane", required=True, help="left,top,width,height in source pixels")
    parser.add_argument("--body", required=True, help="left,top,width,height relative to pane")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--annotate", type=Path)
    args = parser.parse_args()
    result = find_thumbnail_candidates(args.image, pane=tuple(map(int, args.pane.split(","))), body_bounds=tuple(map(int, args.body.split(","))))
    if args.annotate:
        annotate_candidates(args.image, result, args.annotate)
    serialized = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(serialized, encoding="utf-8")
    else:
        print(serialized)
