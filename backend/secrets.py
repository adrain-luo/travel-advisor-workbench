"""Store credentials separately from portable business data using Windows DPAPI."""
import base64
import ctypes
import os
from pathlib import Path
from ctypes import wintypes


class DataBlob(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_byte))]


def _crypt(content: bytes, decrypt=False):
    buffer = ctypes.create_string_buffer(content)
    source = DataBlob(len(content), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    output = DataBlob()
    if decrypt:
        ok = ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output))
    else:
        ok = ctypes.windll.crypt32.CryptProtectData(ctypes.byref(source), "Travel Workbench", None, None, None, 1, ctypes.byref(output))
    if not ok:
        raise ValueError("无法读取或保存本机 AI 密钥，请重新配置")
    try:
        return ctypes.string_at(output.data, output.size)
    finally:
        ctypes.windll.kernel32.LocalFree(output.data)


def set_key(root: Path, value: str):
    path = root / "credential.dpapi"
    if not value:
        path.unlink(missing_ok=True)
    elif os.name == "nt":
        path.write_bytes(base64.b64encode(_crypt(value.encode())))
    else:
        raise ValueError("此平台请通过 TRAVEL_AI_KEY 环境变量配置密钥")


def get_key(root: Path):
    if os.environ.get("TRAVEL_AI_KEY"):
        return os.environ["TRAVEL_AI_KEY"]
    path = root / "credential.dpapi"
    if path.exists() and os.name == "nt":
        return _crypt(base64.b64decode(path.read_bytes()), decrypt=True).decode()
    return None
