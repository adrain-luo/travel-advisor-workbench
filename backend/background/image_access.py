"""Scoped passive image-key candidate from the already-bound client's module.

Reviewed source: fanyuantaier/wechatauto-replica 6e603974bbac3bda93d88bbd6995510ae2547f5c,
wechatauto/db.py:299-349 and media.py:107-116. This adaptation stops before the
upstream master-cipher branch. It never reads cfg+0x2B8, disk authentication
stores, key caches, other processes, or an original database. No import has I/O.
The returned candidate is NOT verified until exact-source DAT decoding succeeds.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import hashlib
from pathlib import Path
import re
import struct
import time

from . import access

LANDMARK = b"global_config"
MAX_STRING = 128


def _pointer(value):
    return 0x10000 <= value < 0x800000000000


def _derive_candidate(read, landmark_address, expected_account_id):
    """Pure bounded pointer-chain primitive; read callback enforces budgets."""
    marker = read(landmark_address, 32)
    if marker is None or len(marker) != 32 or marker[:13] != LANDMARK:
        return None
    size, capacity = struct.unpack_from("<QQ", marker, 16)
    if size != 13 or capacity != 15:
        return None
    pointer_data = read(landmark_address + 16 - 0x138, 8)
    if pointer_data is None or len(pointer_data) != 8:
        return None
    v18 = struct.unpack("<Q", pointer_data)[0]
    if not _pointer(v18):
        return None
    pointer_data = read(v18 + 0x68, 8)
    if pointer_data is None or len(pointer_data) != 8:
        return None
    cfg = struct.unpack("<Q", pointer_data)[0]
    if not _pointer(cfg):
        return None
    account_string = read(cfg + 0x48, 32)
    if account_string is None or len(account_string) != 32:
        return None
    length, capacity = struct.unpack_from("<QQ", account_string, 16)
    if not 1 <= length <= MAX_STRING or capacity < length or capacity > 4096:
        return None
    if length <= 15:
        if capacity != 15:
            return None
        raw_account = account_string[:length]
    else:
        string_pointer = struct.unpack_from("<Q", account_string)[0]
        if not _pointer(string_pointer):
            return None
        raw_account = read(string_pointer, length)
    if raw_account != expected_account_id.encode("ascii"):
        return None
    number = read(cfg + 0x40, 4)
    if number is None or len(number) != 4:
        return None
    dword = struct.unpack("<I", number)[0]
    aes = hashlib.md5((str(dword) + expected_account_id).encode("ascii")).hexdigest()[:16].encode("ascii")
    return {"aes_key": aes, "xor_key": dword & 255}


def _module_matches(api, pid, expected_path, expected_base, expected_size):
    from .binding import ModuleEntry
    api.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    api.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    api.Module32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ModuleEntry)]
    api.Module32FirstW.restype = wintypes.BOOL
    api.Module32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ModuleEntry)]
    api.Module32NextW.restype = wintypes.BOOL
    snapshot = api.CreateToolhelp32Snapshot(0x08 | 0x10, pid)
    if not snapshot or snapshot == ctypes.c_void_p(-1).value:
        raise access.ProbeStop("image_module_metadata_unavailable")
    matches = []
    try:
        entry = ModuleEntry()
        entry.dwSize = ctypes.sizeof(entry)
        ok = api.Module32FirstW(snapshot, ctypes.byref(entry))
        for _ in range(2048):
            if not ok:
                break
            if entry.szModule.casefold() == "weixin.dll":
                matches.append((access._norm(entry.szExePath), int(entry.modBaseAddr or 0), int(entry.modBaseSize)))
            ok = api.Module32NextW(snapshot, ctypes.byref(entry))
        else:
            raise access.ProbeStop("image_module_metadata_limit")
    finally:
        api.CloseHandle(snapshot)
    if matches != [(access._norm(expected_path), expected_base, expected_size)]:
        raise access.ProbeStop("image_loaded_module_changed")


def _module_regions(api, handle, base, size, budget):
    """Only committed readable mappings of this exact loaded module."""
    regions, address = [], base
    while address < base + size:
        budget.check()
        info = access.MBI()
        if not api.VirtualQueryEx(handle, ctypes.c_void_p(address), ctypes.byref(info), ctypes.sizeof(info)):
            raise access.ProbeStop("image_module_regions_unavailable")
        region_base, region_size = int(info.BaseAddress or 0), int(info.RegionSize)
        end = min(region_base + region_size, base + size)
        if region_size <= 0 or end <= address:
            raise access.ProbeStop("image_module_region_invalid")
        protection = int(info.Protect) & 0xFF
        if (info.State == 0x1000 and info.Type == 0x1000000 and info.AllocationBase == base
                and not info.Protect & 0x100 and protection in {2, 4, 8, 0x20, 0x40, 0x80}):
            start = max(region_base, base)
            # Static global objects normally reside in writable image sections.
            # Prioritize them without scanning other process heaps for names.
            priority = 0 if protection in {4, 8, 0x40, 0x80} else 1
            regions.append((priority, start, end))
        address = end
        if len(regions) > 4096:
            raise access.ProbeStop("image_module_region_limit")
    return sorted(regions)


def probe_image_key(binding_report, *, expected_account_id):
    """Return (in-memory candidate or None, safe report). Never log/persist keys.

    Caller must first validate authenticated self/contact identity and only call
    for an exactly indexed selected-chat DAT. Reuse only after full decoding.
    """
    budget = access.Budget()
    candidate, api, handle = None, None, None
    reason = "image_cfg_landmark_not_found"
    stats = {"landmark_hits": 0, "regions_scanned": 0, "phase": "binding_validation"}
    try:
        report = binding_report
        if (report.get("process_to_database_binding_complete") is not True
                or report.get("target_running_at_end") is not True
                or report.get("authenticated_account_id") != expected_account_id
                or not re.fullmatch(r"wxid_[A-Za-z0-9]+", expected_account_id)):
            raise access.ProbeStop("image_account_binding_unverified")
        account_name = Path(report["account_directory"]).name
        if not (account_name == expected_account_id or re.fullmatch(re.escape(expected_account_id) + r"_[A-Za-z0-9]+", account_name)):
            raise access.ProbeStop("image_account_directory_mismatch")
        modules = report.get("loaded_weixin_dll") or []
        if len(modules) != 1:
            raise access.ProbeStop("image_loaded_module_ambiguous")
        base = int(report["loaded_weixin_dll_base"])
        size = int(report["loaded_weixin_dll_size"])
        module_path = modules[0]["path"]
        if not _pointer(base) or not 4096 <= size < 1024 * 1024 * 1024 or not _pointer(base + size):
            raise access.ProbeStop("image_module_range_invalid")
        if Path(module_path).name.casefold() != "weixin.dll":
            raise access.ProbeStop("image_module_path_invalid")
        pid, creation, executable = int(report["pid"]), int(report["creation_filetime"]), report["executable_path"]
        api = access._windows_api()
        metadata = api.OpenProcess(0x1000, False, pid)
        if not metadata:
            raise access.ProbeStop("image_process_metadata_denied")
        try:
            access._check_process(api, metadata, creation, executable)
            _module_matches(api, pid, module_path, base, size)
        finally:
            api.CloseHandle(metadata)
        handle = api.OpenProcess(0x0010 | 0x0400, False, pid)
        if not handle:
            raise access.ProbeStop("image_process_read_denied")
        access._check_process(api, handle, creation, executable)

        def read(address, count):
            if not _pointer(address) or count <= 0 or not _pointer(address + count):
                return None
            budget.reserve(count)
            buffer = ctypes.create_string_buffer(count)
            actual = ctypes.c_size_t()
            ok = api.ReadProcessMemory(handle, ctypes.c_void_p(address), buffer, count, ctypes.byref(actual))
            return buffer.raw[:count] if ok and actual.value == count else None

        stats["phase"] = "loaded_module_landmark"
        seen = set()
        for _, begin, end in _module_regions(api, handle, base, size, budget):
            tail, offset = b"", begin
            stats["regions_scanned"] += 1
            while offset < end:
                length = min(access.CHUNK_BYTES, end - offset)
                data = read(offset, length)
                if data:
                    joined = tail + data
                    at = joined.find(LANDMARK)
                    while at >= 0:
                        absolute = offset - len(tail) + at
                        if absolute not in seen and (absolute + 16) % 8 == 0 and absolute >= base + 0x138:
                            seen.add(absolute)
                            stats["landmark_hits"] += 1
                            if len(seen) > 128:
                                raise access.ProbeStop("image_landmark_candidate_limit")
                            possible = _derive_candidate(read, absolute, expected_account_id)
                            if possible:
                                access._check_process(api, handle, creation, executable)
                                _module_matches(api, pid, module_path, base, size)
                                candidate = possible
                                stats["phase"] = "candidate_requires_media_validation"
                                raise access.ProbeStop("image_candidate_derived_account_matched")
                        at = joined.find(LANDMARK, at + 1)
                    tail = joined[-31:]
                else:
                    tail = b""
                offset += length
    except access.ProbeStop as error:
        reason = str(error)
        if reason != "image_candidate_derived_account_matched":
            candidate = None
    except Exception:
        reason, candidate = "image_probe_validation_error", None
    finally:
        if api and handle:
            api.CloseHandle(handle)
    return candidate, {"reason": reason.upper(), "stop_reason": reason.upper(), "candidate_available": candidate is not None,
                       "media_validated": False, "keys_persisted": False,
                       "process_read_bytes": budget.read_bytes,
                       "elapsed_seconds": round(time.monotonic() - budget.started, 3),
                       "deadline_seconds": access.DEADLINE_SECONDS,
                       "read_budget_bytes": access.MAX_READ_BYTES, "progress": stats}
