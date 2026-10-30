"""Window-scoped Windows I/O for the application-owned acquisition worker.

This module is called by the serialized native worker, not by the browser.
Coordinates are physical screenshot pixels mapped through current window bounds.
It neither injects into WeChat nor reads process memory or encrypted databases.
"""
from __future__ import annotations

import ctypes
import os
import time
from pathlib import Path

from PIL import ImageGrab, ImageStat

from .base import CollectorBlocked


def fail(message, code):
    raise CollectorBlocked(message, code)


class NativeWindows:
    def __init__(self):
        if os.name != "nt":
            fail("此采集模式需要在微信所在的 Windows 桌面运行。", "WINDOWS_DESKTOP_REQUIRED")
        import win32api
        import win32con
        import win32gui
        import win32process
        self.api, self.con, self.gui, self.process = win32api, win32con, win32gui, win32process
        self.user = ctypes.windll.user32
        self.user.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        self.user.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
        self.user.GetDpiForWindow.argtypes = [ctypes.c_void_p]

    def desktop_ready(self):
        self.user.OpenInputDesktop.restype = ctypes.c_void_p
        desktop = self.user.OpenInputDesktop(0, False, 0x0100)
        if not desktop:
            fail("桌面不可访问，请解锁后重新建立本次采集会话。", "DESKTOP_UNAVAILABLE")
        self.user.CloseDesktop.argtypes = [ctypes.c_void_p]
        self.user.CloseDesktop(desktop)

    def process_info(self, pid):
        handle = self.api.OpenProcess(0x1000, False, pid)
        try:
            size = ctypes.c_ulong(32768)
            buffer = ctypes.create_unicode_buffer(size.value)
            kernel = ctypes.windll.kernel32
            kernel.QueryFullProcessImageNameW.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_ulong)]
            if not kernel.QueryFullProcessImageNameW(int(handle), 0, buffer, ctypes.byref(size)):
                raise OSError("Cannot identify window executable")
            times = self.process.GetProcessTimes(handle)
            session_id = ctypes.c_ulong()
            kernel.ProcessIdToSessionId(pid, ctypes.byref(session_id))
            return {"pid": pid, "executable": buffer.value, "process_started_at": times["CreationTime"].isoformat(), "session_id": session_id.value}
        finally:
            handle.Close()

    def describe(self, hwnd):
        if not self.gui.IsWindow(hwnd):
            fail("微信窗口已替换，请重新定位并建立会话。", "WINDOW_REPLACED")
        _, pid = self.process.GetWindowThreadProcessId(hwnd)
        info = self.process_info(pid)
        rect = list(self.gui.GetWindowRect(hwnd))
        client = self.gui.GetClientRect(hwnd)
        origin = self.gui.ClientToScreen(hwnd, (0, 0))
        return {**info, "hwnd": hwnd, "title": self.gui.GetWindowText(hwnd), "class_name": self.gui.GetClassName(hwnd),
                "owner": self.gui.GetWindow(hwnd, self.con.GW_OWNER), "visible": bool(self.gui.IsWindowVisible(hwnd)),
                "minimized": bool(self.gui.IsIconic(hwnd)), "window_rect": rect,
                "client_rect_screen": [origin[0], origin[1], origin[0] + client[2], origin[1] + client[3]],
                "dpi": self.user.GetDpiForWindow(hwnd), "coordinate_units": "physical_pixels"}

    def windows(self):
        output = []
        def inspect(hwnd, unused):
            if not self.gui.IsWindowVisible(hwnd) or self.gui.IsIconic(hwnd):
                return
            try:
                info = self.describe(hwnd)
                if Path(info["executable"]).name.lower() in {"weixin.exe", "wechat.exe"}:
                    output.append(info)
            except (OSError, self.api.error):
                pass
        self.gui.EnumWindows(inspect, None)
        return output

    def validate(self, expected):
        self.desktop_ready()
        now = self.describe(expected["hwnd"])
        for key in ("pid", "executable", "process_started_at", "class_name", "session_id"):
            if now[key] != expected[key]:
                fail("微信进程或窗口已变化，请重新确认账号与来源。", "WINDOW_REPLACED")
        if not now["visible"] or now["minimized"]:
            fail("已绑定窗口不可见，请打开所选来源后重新确认。", "WINDOW_UNAVAILABLE")
        old_rect, new_rect = expected["window_rect"], now["window_rect"]
        if [old_rect[2] - old_rect[0], old_rect[3] - old_rect[1], expected["dpi"]] != [new_rect[2] - new_rect[0], new_rect[3] - new_rect[1], now["dpi"]]:
            fail("窗口尺寸或缩放已改变，旧的图像定位已失效，请重新建立会话。", "GEOMETRY_CHANGED")
        return now

    def activate(self, expected):
        now = self.validate(expected)
        from pywinauto.controls.hwndwrapper import HwndWrapper
        HwndWrapper(now["hwnd"]).set_focus()
        time.sleep(.2)
        if self.gui.GetForegroundWindow() != now["hwnd"]:
            fail("无法切换到已绑定的微信窗口，请手动显示该窗口。", "FOREGROUND_UNAVAILABLE")
        return now

    def capture(self, expected, *, require_foreground=True):
        now = self.validate(expected)
        if require_foreground and self.gui.GetForegroundWindow() != now["hwnd"]:
            fail("微信当前窗口已切换，采集暂停以避免混采。", "SOURCE_MISMATCH")
        image = ImageGrab.grab(window=now["hwnd"])
        rect = now["window_rect"]
        if image.size != (rect[2] - rect[0], rect[3] - rect[1]):
            fail("截图像素与窗口坐标不一致，暂不支持此显示布局。", "CAPTURE_MAPPING_UNSUPPORTED")
        if max(ImageStat.Stat(image).stddev) < 2:
            fail("微信窗口未返回可读图像，当前捕获路径需要适配。", "CAPTURE_UNSUPPORTED")
        now["screenshot_dimensions"] = list(image.size)
        now["screenshot_to_screen"] = {"x_offset": rect[0], "y_offset": rect[1], "scale_x": 1, "scale_y": 1}
        client = now["client_rect_screen"]
        now["client_in_screenshot"] = [client[0] - rect[0], client[1] - rect[1], client[2] - rect[0], client[3] - rect[1]]
        return image, now

    def _point(self, expected, point):
        now = self.validate(expected)
        if self.gui.GetForegroundWindow() != now["hwnd"]:
            fail("目标窗口不在前台，已停止输入。", "SOURCE_MISMATCH")
        x, y = map(int, point)
        rect = now["window_rect"]
        if not (0 <= x < rect[2] - rect[0] and 0 <= y < rect[3] - rect[1]):
            fail("目标位置超出已验证窗口。", "INVALID_TARGET")
        absolute = (rect[0] + x, rect[1] + y)
        hit = self.gui.WindowFromPoint(absolute)
        if self.gui.GetAncestor(hit, 2) != now["hwnd"]:
            fail("目标位置被其他窗口遮挡，已停止输入。", "SOURCE_MISMATCH")
        return absolute

    def click(self, expected, point, *, double=False):
        from pywinauto import mouse
        absolute = self._point(expected, point)
        if double:
            mouse.double_click(coords=absolute)
        else:
            mouse.click(coords=absolute)
        time.sleep(.35)

    def scroll(self, expected, point, direction, notches=3):
        from pywinauto import mouse
        absolute = self._point(expected, point)
        mouse.scroll(coords=absolute, wheel_dist=notches if direction == "up" else -notches)
        time.sleep(.55)

    def key(self, expected, keys):
        # Only navigation/save shortcuts; never type into a chat composer.
        if keys not in {"^s", "{ESC}", "{RIGHT}", "{LEFT}"}:
            fail("此采集器不支持该键盘操作。", "INVALID_ACTION")
        self.validate(expected)
        if self.gui.GetForegroundWindow() != expected["hwnd"]:
            fail("键盘目标已变化，已停止输入。", "SOURCE_MISMATCH")
        from pywinauto.keyboard import send_keys
        send_keys(keys, pause=.05)
        time.sleep(.25)

    def wait_new_window(self, before, parent, timeout=4):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            new = [w for w in self.windows() if w["hwnd"] not in before and w["pid"] == parent["pid"]]
            if len(new) == 1:
                return new[0]
            if len(new) > 1:
                foreground = self.gui.GetForegroundWindow()
                chosen = [w for w in new if w["hwnd"] == foreground]
                if len(chosen) == 1:
                    return chosen[0]
            time.sleep(.1)
        fail("没有找到可验证的微信图片查看器，已保留待重试附件。", "VIEWER_UNSUPPORTED")

    def save_dialog(self, viewer, destination, timeout=5):
        from pywinauto import Desktop
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            dialogs = [w for w in self.windows() if w["pid"] == viewer["pid"] and w["class_name"] == "#32770" and ("保存" in w["title"] or "Save" in w["title"])]
            if len(dialogs) == 1:
                dialog = dialogs[0]
                self.activate(dialog)
                wrapper = Desktop(backend="uia").window(handle=dialog["hwnd"])
                edits = [c for c in wrapper.descendants(control_type="Edit") if c.element_info.automation_id == "1001"]
                saves = [c for c in wrapper.descendants(control_type="Button") if c.element_info.automation_id == "1" and ("保存" in c.window_text() or "Save" in c.window_text())]
                if len(edits) != 1 or len(saves) != 1:
                    fail("另存为对话框的文件名或保存按钮无法唯一定位。", "SAVE_DIALOG_UNSUPPORTED")
                destination = Path(destination).resolve()
                if destination.exists():
                    fail("暂存文件已经存在，请使用新的采集路径。", "STAGING_CONFLICT")
                edits[0].set_edit_text(str(destination))
                if edits[0].get_value() != str(destination):
                    fail("另存为文件路径未正确填写，已停止保存。", "SAVE_DIALOG_UNSUPPORTED")
                saves[0].invoke()
                return dialog
            time.sleep(.15)
        fail("图片查看器没有打开可用的保存对话框。", "SAVE_DIALOG_UNSUPPORTED")
