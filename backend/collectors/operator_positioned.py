"""Bounded acquisition from an operator-established native source session.

The worker preserves unparsed page observations and independently retrievable
media. It does not equate OCR lines, screenshots, or thumbnails with messages.
Session identity is a short-lived operator assertion plus observable anchors;
it is never a permanent native account/source identifier.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageChops, ImageStat

from .base import CollectorBlocked
from .native_windows import NativeWindows, fail


ROOT = Path(__file__).resolve().parents[2]


def now():
    return datetime.now(timezone.utc).isoformat()


def pixel_hash(image):
    return hashlib.sha256(str(image.size).encode() + image.convert("RGB").tobytes()).hexdigest()


def normalized_name(value):
    return re.sub(r"[\s\W_]", "", value or "")


def source_name(source):
    return re.sub(r"[（(]\d+[）)]$", "", source["display_name"]).strip()


def valid_box(box, size):
    if not isinstance(box, (list, tuple)) or len(box) != 4 or any(type(v) is not int for v in box):
        fail("采集区域需要四个整数坐标。", "INVALID_CALIBRATION")
    left, top, right, bottom = box
    if not (0 <= left < right <= size[0] and 0 <= top < bottom <= size[1]):
        fail("采集区域超出当前窗口。", "INVALID_CALIBRATION")
    return list(box)


def recognize(path, crop=None):
    python = Path(os.environ.get("TRAVEL_OCR_PYTHON", ROOT / ".local/ocr-env/Scripts/python.exe"))
    if not python.is_file():
        return {"text": "", "lines": [], "status": "UNAVAILABLE", "reason": "本地识字组件未安装，已保留原始截图。"}
    args = [str(python), "-m", "backend.collectors.rapid_ocr", str(path), "--scale", "2"]
    if crop:
        left, top, right, bottom = crop
        args += ["--crop", f"{left},{top},{right-left},{bottom-top}"]
    try:
        process = subprocess.run(args, cwd=ROOT, capture_output=True, encoding="utf-8-sig", timeout=35,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=False)
        if process.returncode:
            raise ValueError("Local OCR failed")
        result = json.loads(process.stdout)
        return {**result, "status": "UNVERIFIED_TRANSCRIPTION"}
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {"text": "", "lines": [], "status": "FAILED", "reason": "本地识字未成功；不影响保存原始页面，也不会补填发布时间。"}


def similar_anchor(image, saved_path):
    with Image.open(saved_path) as saved:
        if saved.size != image.size:
            return False
        difference = ImageChops.difference(image.convert("RGB"), saved.convert("RGB"))
        # Tolerance is only for tiny rasterization noise in an established image
        # anchor. OCR spelling corrections/fuzzy name matching are never used.
        mean = sum(ImageStat.Stat(difference).mean) / 3
        changed = difference.convert("L").point(lambda value: 255 if value > 15 else 0)
        fraction = changed.histogram()[255] / (image.width * image.height)
        return mean < 1.2 and fraction < .006


def _document_region(window):
    from pywinauto import Desktop
    try:
        wrapper = Desktop(backend="uia").window(handle=window["hwnd"])
        docs = wrapper.descendants(control_type="Document")
        rect = window["window_rect"]
        regions = []
        for item in docs:
            bounds = item.rectangle()
            candidate = [bounds.left - rect[0], bounds.top - rect[1], bounds.right - rect[0], bounds.bottom - rect[1]]
            if candidate[2] - candidate[0] > 250 and candidate[3] - candidate[1] > 250:
                regions.append(candidate)
        return regions[0] if len(regions) == 1 else None
    except Exception:
        return None


def establish_session(source, account, options, staging_dir):
    if not options.get("operator_acknowledged"):
        fail("请确认本次账号与当前打开的来源页面。", "OPERATOR_ACK_REQUIRED")
    if source.get("account_id") != account.get("id") or source.get("kind") not in {"group", "moments"}:
        fail("账号或来源绑定不一致。", "SOURCE_MISMATCH")
    native = NativeWindows()
    native.desktop_ready()
    windows = native.windows()
    main = [w for w in windows if w["title"] in {"微信", "Weixin", "WeChat"} and w["class_name"] != "#32770"]
    if len(main) != 1:
        fail("请显示一个已登录的微信主窗口，以建立本次账号核对依据。", "ACCOUNT_WINDOW_REQUIRED")
    account_window = main[0]
    name = normalized_name(source_name(source))
    if source["kind"] == "group":
        candidates = [w for w in windows if name in normalized_name(w["title"]) and "聊天记录" in w["title"]]
        if len(candidates) != 1:
            fail("请打开所选群的独立聊天记录窗口；当前无法唯一核对群名与历史页面。", "SOURCE_WINDOW_REQUIRED")
        selected = candidates[0]
        surface = "group_history"
    else:
        selected = account_window
        surface = "contact_album"
    if selected["pid"] != account_window["pid"]:
        fail("所选来源窗口与已确认账号不属于同一微信进程。", "SOURCE_MISMATCH")
    native.activate(selected)
    capture, geometry = native.capture(selected)
    staging_dir = Path(staging_dir).resolve()
    staging_dir.mkdir(parents=True, exist_ok=True)
    scale = selected["dpi"] / 96
    calibration = options.get("calibration") or {}
    if source["kind"] == "group":
        # Observed standalone history layout: title, search, then filter toolbar.
        # Every point is proportional to this window's current physical DPI.
        identity = [int(10*scale), int(4*scale), capture.width-int(90*scale), int(36*scale)]
        pane = [int(3*scale), int(138*scale), capture.width-int(14*scale), capture.height-int(7*scale)]
        older_direction = "up"
    else:
        pane = calibration.get("pane") or _document_region(geometry)
        if not pane:
            fail("联系人相册未暴露可校验的页面区域，请打开该联系人的独立相册页面后重新建立会话。", "ALBUM_LAYOUT_UNSUPPORTED")
        pane = valid_box(pane, capture.size)
        identity = calibration.get("identity") or [pane[0], pane[1], pane[2], min(pane[1]+int(95*scale), pane[3])]
        older_direction = "down"
    pane = valid_box(calibration.get("pane", pane), capture.size)
    identity = valid_box(calibration.get("identity", identity), capture.size)
    original = staging_dir / "source-establishment.png"
    capture.save(original, format="PNG")
    identity_ocr = recognize(original, identity)
    if source["kind"] == "moments":
        # An exact visible prefix can be evidence only alongside the operator's
        # full source assertion and frozen visual anchor; never expand it to a
        # permanent ID. A generic feed header alone cannot establish this mode.
        observed = normalized_name(identity_ocr.get("text"))
        explicit_album = calibration.get("surface") == "contact_album"
        if not explicit_album and name not in observed:
            fail("当前页面不能核对为所选联系人的个人相册；请显示完整联系人身份，不能使用朋友圈总动态。", "ALBUM_IDENTITY_UNRESOLVED")
    header_path = staging_dir / "source-anchor.png"
    capture.crop(identity).save(header_path, format="PNG")
    account_capture, account_geometry = native.capture(account_window, require_foreground=selected["hwnd"] == account_window["hwnd"])
    account_rect = valid_box([int(8*scale), int(37*scale), int(50*scale), int(83*scale)], account_capture.size)
    account_anchor = staging_dir / "account-anchor.png"
    account_capture.crop(account_rect).save(account_anchor, format="PNG")
    preview_path = staging_dir / "selected-source-preview.png"
    capture.crop([pane[0], identity[1], pane[2], pane[3]]).save(preview_path, format="PNG")
    binding = {"schema_version": 1, "acquisition_mode": "operator_positioned", "source_id": source["id"],
               "account_id": account["id"], "source_kind": source["kind"], "surface": surface,
               "source_window": geometry, "account_window": account_geometry, "pane": pane, "identity": identity,
               "account_anchor_rect": account_rect, "identity_anchor_path": str(header_path),
               "account_anchor_path": str(account_anchor), "source_title": selected["title"],
               "initial_page_hash": pixel_hash(capture.crop(pane)), "older_direction": older_direction,
               "operator_established_at": now(), "identity_scope": "current_process_window_session",
               "identity_ocr": identity_ocr, "running_client_version": "unconfirmed",
               "permanent_identity_verified": False, "calibration": calibration}
    return {"binding": binding, "evidence": {"preview_path": str(preview_path), "geometry": geometry,
            "source_name": source["display_name"], "account_name": account.get("display_name"),
            "identity_method": "人工确认本次账号及来源，持续核对窗口、标题和图像锚点", "source_time": None},
            "capabilities": {"positioning": "operator_assisted", "parsed_records": "NOT_VERIFIED",
                             "coverage": "BOUNDED_UNPROVEN", "automatic_reopening": False}}


class PositionedAdapter:
    def __init__(self, session, staging_dir):
        self.session = session
        self.binding = session["binding"]
        self.staging = Path(staging_dir).resolve()
        self.staging.mkdir(parents=True, exist_ok=True)
        self.native = NativeWindows()
        self.source = None
        self.account = None
        self.trace = []

    def _record(self, action, **details):
        event = {"at": now(), "action": action, **details}
        self.trace.append(event)
        with (self.staging / "native-actions.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False) + "\n")

    def resolve_source(self, source, account):
        if (source["id"], account["id"], source.get("kind")) != (self.binding["source_id"], self.binding["account_id"], self.binding["source_kind"]):
            fail("会话与所选账号或来源不一致。", "SOURCE_MISMATCH")
        expiry = self.session.get("expires_at")
        if expiry and datetime.now(timezone.utc) >= datetime.fromisoformat(expiry):
            fail("本次来源确认已经到期，请重新核对。", "SESSION_EXPIRED")
        self.source, self.account = source, account
        self.native.activate(self.binding["source_window"])
        self.verify()
        return {"surface": self.binding["surface"], "identity_scope": "operator_positioned_session"}

    def verify(self):
        current = self.native.validate(self.binding["source_window"])
        if current["title"] != self.binding["source_title"]:
            fail("当前来源标题已变化，已停止采集。", "SOURCE_MISMATCH")
        image, geometry = self.native.capture(self.binding["source_window"])
        if not similar_anchor(image.crop(self.binding["identity"]), self.binding["identity_anchor_path"]):
            fail("当前来源的身份区域发生变化，需重新核对。", "SOURCE_MISMATCH")
        account_image, _ = self.native.capture(self.binding["account_window"], require_foreground=False)
        if not similar_anchor(account_image.crop(self.binding["account_anchor_rect"]), self.binding["account_anchor_path"]):
            fail("微信账号的可见依据发生变化，需重新确认账号。", "SOURCE_MISMATCH")
        return image, geometry

    def _scroll(self, direction):
        self.verify()
        left, top, right, bottom = self.binding["pane"]
        self.native.scroll(self.binding["source_window"], ((left+right)//2, (top+bottom)//2), direction, notches=3)
        self.verify()
        self._record("scroll", direction=direction, notches=3)

    def _align(self, wanted, budget=5):
        image, _ = self.verify()
        if pixel_hash(image.crop(self.binding["pane"])) == wanted:
            return True
        newer = "down" if self.binding["older_direction"] == "up" else "up"
        seen = set()
        for _ in range(budget):
            self._scroll(newer)
            image, _ = self.verify()
            digest = pixel_hash(image.crop(self.binding["pane"]))
            if digest == wanted:
                return True
            if digest in seen:
                return False
            seen.add(digest)
        return False

    def iterate_items(self, source, scope, checkpoint=None):
        from .visual_regions import detect_thumbnail_candidates
        checkpoint = checkpoint or {}
        if checkpoint.get("source_id") not in (None, source["id"]) or checkpoint.get("account_id") not in (None, self.account["id"]):
            fail("恢复锚点不属于本次账号与来源。", "SOURCE_MISMATCH")
        wanted = checkpoint.get("page_hash") or self.binding["initial_page_hash"]
        if not self._align(wanted):
            yield {"items": [], "observations": [], "attachments": [], "checkpoint": checkpoint,
                   "terminal": True, "coverage": "PARTIAL_WITH_GAPS", "resume_anchor_missing": True,
                   "stop_reason": "有限回找中未找到原页面锚点，已保留原进度；请重新定位到开始页或保存的检查点。"}
            return
        if checkpoint.get("page_hash"):
            self._record("resume_anchor_matched", page_hash=wanted)
            self._scroll(self.binding["older_direction"])
        budget = min(max(int(scope.get("page_budget", 3)), 1), 5)
        previous = checkpoint.get("page_hash")
        seen = set()
        cursor = checkpoint
        for index in range(budget):
            image, geometry = self.verify()
            pane = self.binding["pane"]
            page = image.crop(pane)
            digest = pixel_hash(page)
            if digest in seen or digest == previous:
                yield {"items": [], "observations": [], "attachments": [], "checkpoint": cursor,
                       "terminal": True, "coverage": "STALLED_UNPROVEN_END", "stop_reason": "页面没有可验证的变化；不能据此认定已到历史终点。"}
                return
            seen.add(digest)
            capture_path = self.staging / f"page-{uuid.uuid4().hex}.png"
            page.save(capture_path, format="PNG")
            ocr = recognize(capture_path)
            self.verify()
            candidates = detect_thumbnail_candidates(page, min_side=max(45, int(40*geometry["dpi"]/96)))
            attachments = []
            for media_index, candidate in enumerate(candidates):
                box = candidate["box"]
                full_box = [box[0]+pane[0], box[1]+pane[1], box[2]+pane[0], box[3]+pane[1]]
                reference = {"source_id": source["id"], "account_id": self.account["id"], "session_id": self.session["id"],
                             "source_view_hash": digest, "thumbnail_box": full_box,
                             "thumbnail_hash": pixel_hash(image.crop(full_box)), "media_index": media_index,
                             "candidate_only": True, "association_state": "UNRESOLVED", "page_index": index}
                attachments.append({"name": f"待核对图片-{media_index+1}.jpg", "type": "image", "mime": "image/jpeg",
                                    "state": "PENDING", "quality": "unknown", "observation_index": 0,
                                    "record_index": None, "media_index": media_index, "association_state": "UNRESOLVED",
                                    "retrieval_reference": reference})
            cursor = {"source_id": source["id"], "account_id": self.account["id"], "page_hash": digest,
                      "previous_page_hash": previous, "pages_observed": int(checkpoint.get("pages_observed", 0))+index+1,
                      "run_cutoff": scope.get("upper"), "strategy": "exact_visual_page_anchor",
                      "source_time_unknown": True, "identity_scope": "operator_positioned_session"}
            self._record("capture_page", capture_path=str(capture_path), page_hash=digest, candidate_media=len(candidates))
            yield {"items": [], "observations": [{"capture_path": str(capture_path), "observed_at": now(),
                    "page_hash": digest, "previous_page_hash": previous, "ocr": ocr,
                    "parse_state": "UNPARSED", "source_time_raw": None, "source_time": None,
                    "geometry": geometry, "captured_region": pane, "source_kind": source["kind"],
                    "acquisition_method": "operator_positioned_automatic", "candidate_media_count": len(candidates),
                    "issues": ["页面观察尚未解析成独立消息或帖子；文字与图片的归属关系未确认。", "发布时间未知；不得据此判定达到日期边界。"]}],
                    "attachments": attachments, "checkpoint": cursor, "coverage": "UNKNOWN", "terminal": False,
                    "unresolved_associations": len(candidates)}
            # Caller commits observations, pending media and cursor, then retrieves
            # media, before allowing this generator to advance the source page.
            previous = digest
            if index + 1 < budget:
                self._scroll(self.binding["older_direction"])
        yield {"items": [], "observations": [], "attachments": [], "checkpoint": cursor,
               "coverage": "PARTIAL_WITH_GAPS", "terminal": True,
               "stop_reason": "本轮已达到所选页面预算；已保存页面与可获取图片，历史覆盖范围仍未证实。"}

    def fetch_attachment(self, reference, destination):
        if reference.get("source_id") != self.source["id"] or reference.get("account_id") != self.account["id"]:
            fail("附件来源与当前会话不一致。", "SOURCE_MISMATCH")
        if not self._align(reference["source_view_hash"]):
            return {"state": "RETRY", "reason": "无法回到该图片的原页面，已保留附件定位与重试记录。", "quality": "unknown"}
        image, _ = self.verify()
        box = valid_box(reference["thumbnail_box"], image.size)
        if pixel_hash(image.crop(box)) != reference["thumbnail_hash"]:
            return {"state": "RETRY", "reason": "图片候选区域已改变，不能使用旧位置点击。", "quality": "unknown"}
        before = {w["hwnd"] for w in self.native.windows()}
        self._record("open_media_candidate", box=box, source_view_hash=reference["source_view_hash"])
        self.native.click(self.binding["source_window"], ((box[0]+box[2])//2, (box[1]+box[3])//2), double=self.source["kind"] == "group")
        viewer = None
        try:
            viewer = self.native.wait_new_window(before, self.binding["source_window"])
            # Only an observed native image-viewer class may receive save keys.
            approved = self.binding.get("calibration", {}).get("viewer_classes", [])
            if viewer["class_name"] not in approved:
                fail("已打开新窗口，但图片查看器类型尚未验证；需要适配，未发送保存按键。", "VIEWER_UNSUPPORTED")
            self.native.activate(viewer)
            viewer_image, viewer_geometry = self.native.capture(viewer)
            viewer_image.save(self.staging / f"viewer-{uuid.uuid4().hex}.png", format="PNG")
            self._record("verified_viewer", window=viewer_geometry)
            destination = Path(destination).resolve()
            if not destination.is_relative_to(self.staging):
                fail("附件保存位置不在本次应用暂存目录内。", "INVALID_STAGING_PATH")
            destination.parent.mkdir(parents=True, exist_ok=True)
            self.native.key(viewer, "^s")
            self.native.save_dialog(viewer, destination)
            deadline = time.monotonic() + 10
            previous_size = None
            while time.monotonic() < deadline:
                if destination.is_file() and destination.stat().st_size > 0:
                    size = destination.stat().st_size
                    if size == previous_size:
                        break
                    previous_size = size
                time.sleep(.25)
            if not destination.is_file() or destination.stat().st_size > 64*1024*1024:
                fail("图片没有完整写入暂存目录，稍后可重试。", "MEDIA_SAVE_INCOMPLETE")
            with Image.open(destination) as saved:
                saved.verify()
            digest = hashlib.sha256(destination.read_bytes()).hexdigest()
            self._record("saved_client_media", path=str(destination), sha256=digest, quality="client_saved")
            result = {"state": "SAVED", "path": str(destination), "sha256": digest, "quality": "client_saved", "association_state": "UNRESOLVED"}
        finally:
            if viewer and viewer["class_name"] in self.binding.get("calibration", {}).get("viewer_classes", []):
                # Close only the observed viewer created by this worker.
                foreground = self.native.gui.GetForegroundWindow()
                if foreground == viewer["hwnd"] and self.native.gui.IsWindow(viewer["hwnd"]):
                    self.native.key(viewer, "{ESC}")
            if self.native.gui.GetForegroundWindow() == self.binding["source_window"]["hwnd"]:
                self.verify()
                self._record("returned_to_source")
        return result


def make_adapter(session, staging_dir):
    return PositionedAdapter(session, staging_dir)
