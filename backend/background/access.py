"""Bounded passive key probe; never imports or initializes wechatauto.

Source reference: fanyuantaier/wechatauto-replica at
6e603974bbac3bda93d88bbd6995510ae2547f5c, wechatauto/db.py
lines 43-123, 147-186, 1090-1208. This is an independently bounded adaptation.
Only the owning root may execute it against the explicitly bound account/PID.
Keys remain in memory in the return value of probe(); CLI prints booleans only.
"""

from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import struct
import sys
import time

DEADLINE_SECONDS = 30.0
MAX_READ_BYTES = 256 * 1024 * 1024
CHUNK_BYTES = 1024 * 1024
PAGE_BYTES = 4096
NAME = b"com.Tencent.WCDB.Config.Cipher"
MASK = bytes.fromhex("d2c7442458020000004889442450488b450048844c2448488944254048584c24")
HEX_LITERAL = re.compile(rb"[xX]'([0-9a-fA-F]{64,192})'")


class ProbeStop(Exception):
    """Fixed non-secret reason code; never includes candidate values."""


class Budget:
    def __init__(self):
        self.started = time.monotonic()
        self.read_bytes = 0

    def check(self):
        if time.monotonic() - self.started >= DEADLINE_SECONDS:
            raise ProbeStop("deadline_exceeded")

    def reserve(self, count):
        self.check()
        if count <= 0 or self.read_bytes + count > MAX_READ_BYTES:
            raise ProbeStop("read_budget_exceeded")
        # Count requested bytes conservatively, including failed/partial reads.
        self.read_bytes += count


def _norm(value):
    return os.path.normcase(os.path.abspath(os.fspath(value)))


def _under(path, root):
    try:
        return os.path.commonpath([_norm(path), _norm(root)]) == _norm(root)
    except ValueError:
        return False


def _verified_binding(binding_path, pid, creation_filetime, executable_path, budget):
    path = Path(binding_path).resolve(strict=True)
    if path.stat().st_size > 65536:
        raise ProbeStop("binding_too_large")
    obj = json.loads(path.read_text(encoding="utf-8-sig"))
    if obj.get("schema_version") != 1:
        raise ProbeStop("binding_schema_invalid")
    auth = obj.get("authorization", {})
    if not (auth.get("current_authenticated_account_selected") is True
            and auth.get("passive_key_read_approved") is True
            and auth.get("confirmed_by") == "user"
            and isinstance(auth.get("confirmation_reference"), str)
            and auth["confirmation_reference"].strip()):
        raise ProbeStop("account_authorization_missing")
    proc = obj.get("process", {})
    if (proc.get("pid") != pid or proc.get("creation_filetime") != creation_filetime
            or not isinstance(proc.get("executable_path"), str)
            or _norm(proc["executable_path"]) != _norm(executable_path)):
        raise ProbeStop("process_binding_mismatch")
    acct = obj.get("account", {})
    if acct.get("handle_binding_verified") is not True:
        raise ProbeStop("account_handle_binding_missing")
    account_dir = Path(acct["directory"]).resolve(strict=True)
    storage = Path(obj["storage_root"]).resolve(strict=True)
    evidence = Path(acct["handle_evidence"]).resolve(strict=True)
    if not evidence.is_file() or not account_dir.is_dir() or not storage.is_dir():
        raise ProbeStop("binding_evidence_missing")
    if _under(storage, account_dir) or not _under(path, storage):
        raise ProbeStop("storage_not_isolated")
    items = obj.get("database_copies", [])
    if not isinstance(items, list) or not 1 <= len(items) <= 128:
        raise ProbeStop("copy_allowlist_invalid")
    pages = {}
    for item in items:
        budget.check()
        kind = item.get("kind")
        if not isinstance(kind, str) or not re.fullmatch(r"contact|sns|message_\d+|message_resource|hardlink", kind) or kind in pages:
            raise ProbeStop("database_kind_not_allowed")
        if item.get("active_handle_verified") is not True:
            raise ProbeStop("database_handle_binding_missing")
        source = Path(item["source_path"]).resolve(strict=True)
        copy = Path(item["copy_path"]).resolve(strict=True)
        if source.name.lower() != kind + ".db" or not source.is_file():
            raise ProbeStop("source_not_allowed")
        bucket = "message" if kind.startswith("message_") else kind
        if source != (account_dir / "db_storage" / bucket / (kind + ".db")).resolve(strict=True):
            raise ProbeStop("source_outside_bound_account")
        if not copy.is_file() or not _under(copy, storage) or _under(copy, account_dir):
            raise ProbeStop("copy_not_isolated")
        expected_hash = item.get("sha256", "")
        if not re.fullmatch(r"[0-9a-fA-F]{64}", expected_hash):
            raise ProbeStop("copy_hash_missing")
        before = copy.stat()
        digest = hashlib.sha256()
        first = b""
        with copy.open("rb") as handle:
            while True:
                budget.check()
                chunk = handle.read(CHUNK_BYTES)
                if not chunk:
                    break
                if not first:
                    first = chunk[:PAGE_BYTES]
                digest.update(chunk)
        after = copy.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ProbeStop("copy_changed")
        if not hmac.compare_digest(digest.hexdigest(), expected_hash.lower()):
            raise ProbeStop("copy_hash_mismatch")
        if len(first) != PAGE_BYTES:
            raise ProbeStop("copy_first_page_short")
        pages[kind] = first
    return pages


def _windows_api():
    if os.name != "nt" or ctypes.sizeof(ctypes.c_void_p) != 8:
        raise ProbeStop("windows_x64_required")
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    api.OpenProcess.restype = wintypes.HANDLE
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    api.CloseHandle.restype = wintypes.BOOL
    api.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                             wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    api.QueryFullProcessImageNameW.restype = wintypes.BOOL
    api.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    api.GetProcessTimes.restype = wintypes.BOOL
    api.ReadProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                     ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
    api.ReadProcessMemory.restype = wintypes.BOOL
    api.VirtualQueryEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t]
    api.VirtualQueryEx.restype = ctypes.c_size_t
    return api


def _check_process(api, handle, expected_creation, expected_image):
    name = ctypes.create_unicode_buffer(32768)
    size = wintypes.DWORD(len(name))
    if not api.QueryFullProcessImageNameW(handle, 0, name, ctypes.byref(size)):
        raise ProbeStop("process_image_unavailable")
    times = [wintypes.FILETIME() for _ in range(4)]
    if not api.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
        raise ProbeStop("process_time_unavailable")
    created = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
    exited = (times[1].dwHighDateTime << 32) | times[1].dwLowDateTime
    if exited or created != expected_creation or _norm(name.value) != _norm(expected_image):
        raise ProbeStop("live_process_identity_mismatch")


class MBI(ctypes.Structure):
    _fields_ = [("BaseAddress", ctypes.c_void_p), ("AllocationBase", ctypes.c_void_p),
                ("AllocationProtect", wintypes.DWORD), ("alignment1", wintypes.DWORD),
                ("RegionSize", ctypes.c_size_t), ("State", wintypes.DWORD),
                ("Protect", wintypes.DWORD), ("Type", wintypes.DWORD),
                ("alignment2", wintypes.DWORD)]


def _verify(candidate, page, salt=None):
    if salt is None:
        salt = page[:16]
    mac_key = hashlib.pbkdf2_hmac("sha512", candidate,
                                bytes(value ^ 0x3A for value in salt), 2, dklen=32)
    calculated = hmac.new(mac_key, page[16:4032] + struct.pack("<I", 1), hashlib.sha512).digest()
    return hmac.compare_digest(calculated, page[4032:4096])


def _walk_reference_candidates(api, handle, read, budget, stats, visit):
    """One pass: locate the existing node length field, verify its name pointer.

    The upstream node contains <name pointer, exact name length>. Reversing the
    discovery order avoids reading every region once for names and again for
    references. visit() verifies the exact name bytes and full node before keys.
    """
    needle = struct.pack("<Q", len(NAME))
    overlap = len(needle) - 1
    seen = set()
    address = 0
    while address < 0x800000000000:
        budget.check()
        mbi = MBI()
        if not api.VirtualQueryEx(handle, ctypes.c_void_p(address), ctypes.byref(mbi), ctypes.sizeof(mbi)):
            break
        base = mbi.BaseAddress or 0
        size = mbi.RegionSize
        next_address = base + size
        if not size or next_address <= address:
            raise ProbeStop("invalid_memory_region")
        if (mbi.State == 0x1000 and (mbi.Protect & 0xFF) & 0xE6
                and not mbi.Protect & 0x100 and size < 0x10000000):
            cursor = base
            tail = b""
            while cursor < next_address:
                data = read(cursor, min(CHUNK_BYTES, next_address - cursor))
                if data:
                    joined = tail + data
                    origin = cursor - len(tail)
                    at = joined.find(needle)
                    while at >= 0:
                        # The pair begins one pointer-width before its length.
                        found = origin + at - 8
                        if found not in seen:
                            seen.add(found)
                            stats["length_field_candidates"] += 1
                            if len(seen) > 32768:
                                raise ProbeStop("candidate_address_limit")
                            visit(found)
                        at = joined.find(needle, at + 1)
                    tail = joined[-overlap:] if overlap else b""
                else:
                    tail = b""
                cursor += min(CHUNK_BYTES, next_address - cursor)
        address = next_address


def probe(binding_path, *, pid, creation_filetime, executable_path):
    """Return (in-memory key mapping, non-secret report); no persistence or UI."""
    budget = Budget()
    keys = {}
    pages = {}
    stop = "scan_completed"
    handle = None
    api = None
    stats = {"phase": "binding_validation", "length_field_candidates": 0,
             "exact_name_hits": 0, "verified_reference_hits": 0,
             "candidate_hmac_tests": 0}
    try:
        pages = _verified_binding(binding_path, pid, creation_filetime, executable_path, budget)
        api = _windows_api()
        stats["phase"] = "process_identity_validation"
        # Establish identity with metadata-only permissions before any VM read.
        check_handle = api.OpenProcess(0x1000, False, pid)
        if not check_handle:
            raise ProbeStop("process_metadata_access_denied")
        try:
            _check_process(api, check_handle, creation_filetime, executable_path)
        finally:
            api.CloseHandle(check_handle)
        handle = api.OpenProcess(0x0010 | 0x0400, False, pid)
        if not handle:
            raise ProbeStop("process_read_access_denied")
        _check_process(api, handle, creation_filetime, executable_path)

        def read(address, count):
            if not (0x10000 <= address < 0x800000000000) or address + count > 0x800000000000:
                return None
            budget.reserve(count)
            buffer = ctypes.create_string_buffer(count)
            actual = ctypes.c_size_t()
            ok = api.ReadProcessMemory(handle, ctypes.c_void_p(address), buffer, count, ctypes.byref(actual))
            return buffer.raw[:actual.value] if ok and actual.value else None

        stats["phase"] = "scanning_reference_nodes"
        names = {}
        tested = set()

        def visit(address):
            budget.check()
            node = read(address - 0x10, 0x50)
            if not node or len(node) < 0x40:
                return
            if struct.unpack_from("<Q", node, 0x18)[0] != len(NAME):
                return
            name_ptr = struct.unpack_from("<Q", node, 0x10)[0]
            if name_ptr not in names:
                names[name_ptr] = read(name_ptr, len(NAME)) == NAME
                if names[name_ptr]:
                    stats["exact_name_hits"] += 1
            if not names[name_ptr]:
                return
            stats["verified_reference_hits"] += 1
            config_ptr = struct.unpack_from("<Q", node, 0x28)[0]
            obj = read(config_ptr + 0x88, 0x28)
            if not obj or len(obj) < 0x18:
                return
            data_ptr, data_len = struct.unpack_from("<QQ", obj, 0x8)
            if not 0 < data_len <= 1024:
                return
            blob = read(data_ptr, data_len)
            if not blob or len(blob) != data_len:
                return
            decoded = bytes(value ^ MASK[i % len(MASK)] for i, value in enumerate(blob))
            for match in HEX_LITERAL.finditer(decoded):
                literal = match.group(1)
                starts = [0]
                if len(literal) > 96:
                    starts += list(range(0, len(literal) - 63, 32)) + [len(literal) - 64]
                for offset in dict.fromkeys(starts):
                    budget.check()
                    candidate = bytes.fromhex(literal[offset:offset + 64].decode("ascii"))
                    if len(candidate) != 32 or len(set(candidate)) < 15 or candidate in tested:
                        continue
                    tested.add(candidate)
                    salt = (bytes.fromhex(literal[offset + 64:offset + 96].decode("ascii"))
                            if offset + 96 <= len(literal) else None)
                    for kind, page in pages.items():
                        if kind in keys:
                            continue
                        stats["candidate_hmac_tests"] += 1
                        if _verify(candidate, page):
                            keys[kind] = candidate
                        elif salt is not None and _verify(candidate, page, salt):
                            keys[kind] = candidate + salt
                    if len(keys) == len(pages):
                        _check_process(api, handle, creation_filetime, executable_path)
                        stats["phase"] = "validated"
                        raise ProbeStop("all_allowlisted_databases_validated")

        _walk_reference_candidates(api, handle, read, budget, stats, visit)
    except ProbeStop as error:
        stop = str(error)
        if stop == "live_process_identity_mismatch":
            keys.clear()
    except Exception:
        # No traceback, repr, exception-local dump, candidate bytes or key hashes.
        stop = "validation_or_probe_error"
        keys.clear()
    finally:
        if handle and api:
            api.CloseHandle(handle)
    report = {
        "schema_version": 1,
        "stop_reason": stop,
        "hmac_validated": {kind: kind in keys for kind in sorted(pages)},
        "all_allowlisted_validated": bool(pages) and len(keys) == len(pages),
        "process_read_bytes": budget.read_bytes,
        "elapsed_seconds": round(time.monotonic() - budget.started, 3),
        "deadline_seconds": DEADLINE_SECONDS,
        "read_budget_bytes": MAX_READ_BYTES,
        "keys_persisted": False,
        "scan_progress": stats,
    }
    return keys, report

