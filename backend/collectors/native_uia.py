"""Declarative, read-oriented UIA traversal for an enrolled client surface.

This is a real pywinauto driver, not a recorder replay or a mock. No selectors are
shipped for the inspected Weixin 4.1.13.65 because its content tree was collapsed.
An enrollment must be produced from observed, uniquely matching accessibility
controls on the selected account/client. It contains no screen coordinates.
"""
from __future__ import annotations

import ctypes
import hashlib
import importlib.metadata
import json
import os
import platform
import time
from datetime import datetime, timezone
from pathlib import Path

from .base import CollectorBlocked


SELECTOR_KEYS = {"title", "title_re", "auto_id", "control_type", "class_name"}
BLOCKED_ACTION_NAMES = ("发送", "Send", "点赞", "Like", "评论", "Comment", "发表", "Publish", "删除", "Delete", "支付", "Pay")


class NativeUIADriver:
    def __init__(self, enrollment_path: str | Path | None = None):
        self.enrollment_path = Path(enrollment_path or os.environ["TRAVEL_WECHAT_ENROLLMENT"]) if enrollment_path or os.environ.get("TRAVEL_WECHAT_ENROLLMENT") else None
        self.enrollment = None
        self.window = None
        self.source = None
        self.account = None
        self.route = None
        self._row_references = {}

    def _load(self):
        if not self.enrollment_path or not self.enrollment_path.is_file():
            raise CollectorBlocked("当前微信版本的自动采集路径尚未完成适配与实机验证。请使用已保存资料；群历史和联系人相册需由技术人员继续适配。", "UIA_NOT_ENROLLED")
        try:
            config = json.loads(self.enrollment_path.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            raise CollectorBlocked("微信采集路径配置无法读取，请重新进行兼容性验证。", "INVALID_ENROLLMENT") from exc
        if config.get("schema_version") != 1 or not config.get("verified_at") or not config.get("evidence_reference"):
            raise CollectorBlocked("采集路径缺少版本或实机验证证据，不能开始采集。", "UNVERIFIED_ENROLLMENT")
        self.enrollment = config
        return config

    def probe(self, kind: str):
        features = {"selected_history": "BLOCKED", "account_identity": "NOT_TESTED",
                    "timestamps": "NOT_TESTED", "original_images": "NOT_TESTED",
                    "documents": "NOT_TESTED", "resume": "NOT_TESTED"}
        info = {"kind": kind, "adapter": "native-uia-enrolled-v1", "status": "BLOCKED", "available": False,
                "features": features, "client_version_observed": "4.1.13.65",
                "observed_ui": "MMUIRenderSubWindowHW without source content controls",
                "requires_unlocked_desktop": True}
        if platform.system() != "Windows":
            return {**info, "code": "WINDOWS_DESKTOP_REQUIRED", "reason": "微信采集器必须在微信所在的 Windows 交互桌面运行。"}
        try:
            config = self._load()
            info["client_version_current"] = self._verify_executable_version(config)
            try:
                info["library_version"] = importlib.metadata.version("pywinauto")
            except importlib.metadata.PackageNotFoundError:
                raise CollectorBlocked("尚未安装 Windows UIA 运行依赖，请运行本地安装脚本。", "UIA_DEPENDENCY_MISSING")
            route = config.get("routes", {}).get(kind)
            if not route:
                raise CollectorBlocked("该来源类型尚无已验证的采集路径；群聊与联系人朋友圈需要分别验证。", "ROUTE_NOT_ENROLLED")
            if kind == "moments" and route.get("surface") != "contact_album":
                raise CollectorBlocked("当前配置仅能读取综合朋友圈，尚不能读取指定联系人的历史。", "CONTACT_ALBUM_REQUIRED")
            return {**info, "available": True, "status": "PARTIAL", "features": route.get("tested_features", features),
                    "reason": "已配置实机路径；每次采集仍需重新验证账号、来源和桌面。", "enrolled_at": config["verified_at"]}
        except CollectorBlocked as exc:
            return {**info, "code": exc.code, "reason": exc.message}

    @staticmethod
    def _selector(selector):
        if not isinstance(selector, dict) or not selector or set(selector) - SELECTOR_KEYS:
            raise CollectorBlocked("采集控件定位配置无效。", "INVALID_SELECTOR")
        return selector

    @staticmethod
    def _matches(wrapper, selector):
        import re
        info = wrapper.element_info
        values = {"title": info.name, "auto_id": info.automation_id,
                  "control_type": info.control_type, "class_name": info.class_name}
        for key, value in selector.items():
            if key == "title_re":
                if not re.fullmatch(value, info.name or ""):
                    return False
            elif values.get(key) != value:
                return False
        return True

    def _find(self, root, selector, optional=False):
        selector = self._selector(selector)
        matches = [item for item in root.descendants() if self._matches(item, selector)]
        if not matches and optional:
            return None
        if len(matches) != 1:
            raise CollectorBlocked("当前界面无法唯一定位采集控件；可能存在同名来源或界面已变化。请返回所选来源后重试。", "TARGET_AMBIGUOUS")
        return matches[0]

    def _text(self, root, selector, optional=False):
        control = self._find(root, selector, optional)
        if control is None:
            return None
        text = control.window_text()
        if not text:
            try:
                text = control.iface_value.CurrentValue
            except Exception:
                pass
        return text

    def _expected(self, spec, source, account):
        if "value" in spec:
            return str(spec["value"])
        path = spec.get("from", "").split(".")
        value = {"source": source, "account": account}
        try:
            for field in path:
                value = value[field]
        except (TypeError, KeyError):
            raise CollectorBlocked("来源或账号缺少可复核的身份信息，请补充绑定信息。", "IDENTITY_EVIDENCE_MISSING")
        if not isinstance(value, (str, int)) or not str(value):
            raise CollectorBlocked("身份信息不能为空，也不能仅使用未经确认的昵称。", "IDENTITY_EVIDENCE_MISSING")
        return str(value)

    def _check_identity(self, rules, source, account, root=None):
        if not rules:
            raise CollectorBlocked("尚未配置账号或来源身份校验。", "IDENTITY_CHECK_MISSING")
        for rule in rules:
            actual = self._text(root or self.window, rule["selector"])
            expected = self._expected(rule["expected"], source, account)
            if actual != expected:
                raise CollectorBlocked("微信账号或当前来源与绑定信息不一致，采集已暂停，请重新确认。", "IDENTITY_MISMATCH")

    def _desktop_ready(self):
        user32 = ctypes.windll.user32
        user32.OpenInputDesktop.restype = ctypes.c_void_p
        handle = user32.OpenInputDesktop(0, False, 0x0100)
        if not handle:
            raise CollectorBlocked("当前桌面不可访问，请解锁并打开微信后继续。", "DESKTOP_UNAVAILABLE")
        user32.CloseDesktop.argtypes = [ctypes.c_void_p]
        user32.CloseDesktop(handle)
        if self.window and user32.GetForegroundWindow() != self.window.handle:
            raise CollectorBlocked("微信已不在前台，采集已暂停。请切回所选微信窗口后继续。", "USER_INTERFERENCE")

    def _attach(self):
        config = self.enrollment or self._load()
        self._verify_executable_version(config)
        from pywinauto import Desktop
        self._desktop_ready()
        selector = self._selector(config["window"])
        windows = [x for x in Desktop(backend="uia").windows() if self._matches(x, selector)]
        if len(windows) != 1:
            raise CollectorBlocked("无法唯一定位微信窗口，请打开已绑定账号的微信窗口。", "WINDOW_NOT_UNIQUE")
        self.window = windows[0]
        # HWND and process IDs are runtime handles, not persistent account IDs.
        from pywinauto.application import process_module
        actual_executable = str(process_module(self.window.process_id()))
        expected_executable = config.get("executable")
        if not expected_executable or os.path.normcase(actual_executable) != os.path.normcase(expected_executable):
            raise CollectorBlocked("微信窗口所属程序与已验证路径不符，已停止采集。", "EXECUTABLE_MISMATCH")
        self._desktop_ready()

    @staticmethod
    def _file_version(executable):
        """Read the executable's public version resource, never process memory."""
        from ctypes import wintypes

        class FixedFileInfo(ctypes.Structure):
            _fields_ = [(name, wintypes.DWORD) for name in (
                "signature", "structure_version", "file_version_ms", "file_version_ls",
                "product_version_ms", "product_version_ls", "file_flags_mask", "file_flags",
                "file_os", "file_type", "file_subtype", "file_date_ms", "file_date_ls")]

        version = ctypes.WinDLL("version", use_last_error=True)
        version.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
        version.GetFileVersionInfoSizeW.restype = wintypes.DWORD
        version.GetFileVersionInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
        version.GetFileVersionInfoW.restype = wintypes.BOOL
        version.VerQueryValueW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.UINT)]
        version.VerQueryValueW.restype = wintypes.BOOL
        unused = wintypes.DWORD()
        size = version.GetFileVersionInfoSizeW(str(executable), ctypes.byref(unused))
        if not size:
            raise OSError("Executable version resource unavailable")
        buffer = ctypes.create_string_buffer(size)
        if not version.GetFileVersionInfoW(str(executable), 0, size, buffer):
            raise OSError("Executable version resource could not be read")
        pointer, length = ctypes.c_void_p(), wintypes.UINT()
        if not version.VerQueryValueW(buffer, "\\", ctypes.byref(pointer), ctypes.byref(length)) or length.value < ctypes.sizeof(FixedFileInfo):
            raise OSError("Executable version resource invalid")
        info = ctypes.cast(pointer, ctypes.POINTER(FixedFileInfo)).contents
        if info.signature != 0xFEEF04BD:
            raise OSError("Executable version signature invalid")
        return ".".join(str(value) for value in (info.product_version_ms >> 16, info.product_version_ms & 0xFFFF,
                                                 info.product_version_ls >> 16, info.product_version_ls & 0xFFFF))

    def _verify_executable_version(self, config):
        expected = config.get("client_version")
        if not isinstance(expected, str) or not expected or not config.get("executable"):
            raise CollectorBlocked("采集路径缺少已验证的微信版本，请重新进行兼容性验证。", "CLIENT_VERSION_NOT_ENROLLED")
        try:
            observed = self._file_version(config["executable"])
        except (OSError, AttributeError) as exc:
            raise CollectorBlocked("无法核对微信程序版本，采集已暂停。", "CLIENT_VERSION_UNAVAILABLE") from exc
        if observed != expected:
            raise CollectorBlocked(f"微信版本已变化（当前 {observed}，已验证 {expected}），请重新验证采集路径。", "CLIENT_VERSION_MISMATCH")
        return observed

    def _action(self, step, source, account):
        self._desktop_ready()
        target = self._find(self.window, step["selector"])
        title = target.window_text() or ""
        if any(word.lower() in title.lower() for word in BLOCKED_ACTION_NAMES):
            raise CollectorBlocked("采集路径包含发送或修改内容的操作，已拒绝执行。", "NON_READ_ACTION")
        action = step.get("action", "invoke")
        try:
            if action == "invoke":
                target.iface_invoke.Invoke()
            elif action == "select":
                target.iface_selection_item.Select()
            elif action == "search":
                if not ("搜索" in title or "search" in (target.element_info.automation_id or "").lower()):
                    raise CollectorBlocked("搜索动作未定位到已验证的搜索框。", "SEARCH_CONTROL_REQUIRED")
                target.iface_value.SetValue(self._expected(step["value"], source, account))
            else:
                raise CollectorBlocked("不支持的采集导航动作。", "INVALID_ACTION")
        except CollectorBlocked:
            raise
        except Exception as exc:
            raise CollectorBlocked("微信控件不支持已配置的无障碍操作，请重新验证采集路径。", "UIA_PATTERN_UNAVAILABLE") from exc
        time.sleep(min(float(step.get("wait_seconds", 0.25)), 2))

    def resolve(self, source, account):
        config = self.enrollment or self._load()
        self.route = config["routes"][source["kind"]]
        if not any(rule.get("discriminator") for rule in self.route.get("source_identity", [])):
            raise CollectorBlocked("来源缺少用于区分同名群或联系人的身份特征，不能仅凭名称开始采集。", "SOURCE_DISCRIMINATOR_MISSING")
        self._attach()
        self._check_identity(config.get("account_identity"), source, account)
        for step in self.route.get("open_source", []):
            self._check_identity(config.get("account_identity"), source, account)
            self._action(step, source, account)
        self.source, self.account = source, account
        self.verify(source, account)
        return {"id": source["id"], "account_id": account["id"], "surface": self.route.get("surface"),
                "verified_at": datetime.now(timezone.utc).isoformat()}

    def verify(self, source, account):
        self._desktop_ready()
        self._check_identity(self.enrollment.get("account_identity"), source, account)
        self._check_identity(self.route.get("source_identity"), source, account)

    def read_page(self, source):
        self.verify(source, self.account)
        route = self.route
        container = self._find(self.window, route["container"])
        row_selector = self._selector(route["item"])
        rows = [x for x in container.children() if self._matches(x, row_selector)]
        output = []
        self._row_references = {}
        for position, row in enumerate(rows):
            text = self._text(row, route["text"], optional=True) if route.get("text") else row.window_text()
            raw_time = self._text(row, route["time"], optional=True) if route.get("time") else None
            author = self._text(row, route["author"], optional=True) if route.get("author") else None
            item = {"text": text or "", "source_time_raw": raw_time, "author": author,
                    "type": "post" if source["kind"] == "moments" else "text", "attachments": [],
                    "native_id_verified": False, "locator": {"surface": route["surface"], "position": position},
                    "issues": []}
            try:
                item["ui_runtime_id"] = list(row.element_info.runtime_id)
            except Exception:
                item["ui_runtime_id"] = None
            for media_type, selector in route.get("media", {}).items():
                media = [x for x in row.descendants() if self._matches(x, self._selector(selector))]
                for index, control in enumerate(media):
                    ref = hashlib.sha256(f"{source['id']}|{text}|{raw_time}|{position}|{media_type}|{index}".encode()).hexdigest()
                    self._row_references[ref] = control
                    item["attachments"].append({"reference": ref, "name": control.window_text() or media_type,
                                                 "type": media_type, "media_index": index, "state": "PENDING",
                                                 "quality": "unknown", "source_id": source["id"]})
            item["observed_media_count"] = len(item["attachments"])
            output.append(item)
        endpoint = None
        if route.get("endpoint"):
            text = self._text(container, route["endpoint"]["selector"], optional=True)
            expected = route["endpoint"].get("text")
            if text and text == expected:
                endpoint = {"verified": True, "text": text, "enrollment_evidence": self.enrollment["evidence_reference"]}
        return {"items": output, "endpoint_evidence": endpoint,
                "ordering_proven": False, "observed_at": datetime.now(timezone.utc).isoformat()}

    def previous_page(self, source):
        self.verify(source, self.account)
        container = self._find(self.window, self.route["container"])
        try:
            # UIA ScrollAmount: 0 large decrement; 2 no amount; 3 large increment.
            amount = 0 if self.route.get("older_direction", "up") == "up" else 3
            container.iface_scroll.Scroll(2, amount)
        except Exception as exc:
            raise CollectorBlocked("该来源未暴露可用的历史翻页控件，已保留当前页。", "PAGINATION_UNAVAILABLE") from exc
        time.sleep(0.5)

    def fetch(self, reference, destination):
        self.verify(self.source, self.account)
        if reference.get("source_id") != self.source["id"]:
            raise CollectorBlocked("附件不属于当前已验证来源。", "ATTACHMENT_SOURCE_MISMATCH")
        # Default UIA trees expose media labels but no byte-download pattern.
        # Never open arbitrary documents or treat a screenshot as an original.
        return {"state": "RETRY", "quality": "unknown", "reason": "当前无障碍路径尚未验证原图或文件保存；请保留待重试记录并完成附件保存适配。"}
