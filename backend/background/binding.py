"""Explicit-PID handle metadata probe. NOT a key reader or account verifier.

No ReadProcessMemory, database/content reads, debugger, privilege adjustment,
client input, filesystem search, or client termination. Only allowlisted database
handle paths and the loaded Weixin.dll path/version are reported. The native
class-51 handle snapshot is an internal ABI and fails closed if unsupported.

References:
https://learn.microsoft.com/en-us/windows/win32/api/winternl/nf-winternl-ntqueryinformationprocess
https://learn.microsoft.com/en-us/windows/win32/api/winternl/nf-winternl-ntqueryobject
https://learn.microsoft.com/en-us/windows/win32/api/handleapi/nf-handleapi-duplicatehandle
https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getfinalpathnamebyhandlew
https://learn.microsoft.com/en-us/windows/win32/api/tlhelp32/nf-tlhelp32-createtoolhelp32snapshot
https://github.com/winsiderss/systeminformer/blob/master/phnt/include/ntpsapi.h
"""
from __future__ import annotations

import argparse
import ctypes as C
from ctypes import wintypes as W
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys


DB_PATH = re.compile(
    r"^(?P<root>[A-Za-z]:\\(?:[^\\]+\\)*wxid_[^\\]+)\\db_storage\\"
    r"(?P<bucket>contact|message|sns|hardlink)\\(?P<name>[^\\]+)$", re.I)
DB_NAMES = {"contact": re.compile(r"contact\.db(?:-wal|-shm)?$", re.I),
            "hardlink": re.compile(r"hardlink\.db(?:-wal|-shm)?$", re.I),
            "message": re.compile(r"message_(?:\d+|resource)\.db(?:-wal|-shm)?$", re.I),
            "sns": re.compile(r"sns\.db(?:-wal|-shm)?$", re.I)}


def discover_pid():
    """Enumerate process metadata; select exactly one non-child client instance."""
    if os.name != "nt":
        raise RuntimeError("WINDOWS_REQUIRED")
    class ProcessEntry(C.Structure):
        _fields_ = [("size", W.DWORD), ("usage", W.DWORD), ("pid", W.DWORD),
                    ("heap", C.c_size_t), ("module", W.DWORD), ("threads", W.DWORD),
                    ("parent", W.DWORD), ("priority", W.LONG), ("flags", W.DWORD),
                    ("name", W.WCHAR * 260)]
    k = C.WinDLL("kernel32", use_last_error=True)
    snap = api(k, "CreateToolhelp32Snapshot", W.HANDLE, [W.DWORD, W.DWORD])(2, 0)
    if snap == C.c_void_p(-1).value:
        raise RuntimeError("PROCESS_ENUMERATION_FAILED")
    first = api(k, "Process32FirstW", W.BOOL, [W.HANDLE, C.POINTER(ProcessEntry)])
    nxt = api(k, "Process32NextW", W.BOOL, [W.HANDLE, C.POINTER(ProcessEntry)])
    close = api(k, "CloseHandle", W.BOOL, [W.HANDLE])
    found = {}
    try:
        entry = ProcessEntry(); entry.size = C.sizeof(entry)
        ok = first(snap, C.byref(entry))
        while ok:
            if entry.name.casefold() in {"weixin.exe", "wechat.exe"}:
                found[int(entry.pid)] = int(entry.parent)
            ok = nxt(snap, C.byref(entry))
    finally:
        close(snap)
    roots = [pid for pid, parent in found.items() if parent not in found]
    if not roots:
        raise RuntimeError("CLIENT_NOT_RUNNING")
    if len(roots) != 1:
        raise RuntimeError("MULTIPLE_CLIENT_INSTANCES")
    return roots[0]


def probe_bounded(pid, *, timeout=20):
    """Run metadata-only handle enumeration in an owned, time-bounded worker.

    The worker never acquires VM_READ permission or receives keys. A timeout
    terminates only this newly created worker; the client is never terminated.
    """
    if not isinstance(pid, int) or pid <= 0:
        raise RuntimeError("PROCESS_ID_INVALID")
    try:
        result = subprocess.run([sys.executable, "-m", "backend.background.binding", str(pid)],
            cwd=str(Path(__file__).resolve().parents[2]), stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        raise RuntimeError("PROCESS_BINDING_METADATA_TIMEOUT") from None
    if result.returncode or len(result.stdout) > 1024 * 1024:
        raise RuntimeError("PROCESS_BINDING_METADATA_FAILED")
    try:
        value = json.loads(result.stdout.decode("utf-8"))
        if value.get("pid") != pid:
            raise ValueError()
        return value
    except (ValueError, UnicodeError, AttributeError):
        raise RuntimeError("PROCESS_BINDING_METADATA_INVALID") from None


class HandleEntry(C.Structure):
    _fields_ = [("value", W.HANDLE), ("handle_count", C.c_size_t),
                ("pointer_count", C.c_size_t), ("access", W.DWORD),
                ("type_index", W.DWORD), ("attributes", W.DWORD), ("reserved", W.DWORD)]


class HandleHeader(C.Structure):
    _fields_ = [("count", C.c_size_t), ("reserved", C.c_size_t)]


class UnicodeString(C.Structure):
    _fields_ = [("length", W.USHORT), ("maximum_length", W.USHORT), ("buffer", C.c_void_p)]


class ModuleEntry(C.Structure):
    _fields_ = [("dwSize", W.DWORD), ("th32ModuleID", W.DWORD), ("th32ProcessID", W.DWORD),
                ("GlblcntUsage", W.DWORD), ("ProccntUsage", W.DWORD), ("modBaseAddr", C.c_void_p),
                ("modBaseSize", W.DWORD), ("hModule", W.HMODULE),
                ("szModule", W.WCHAR * 256), ("szExePath", W.WCHAR * 260)]


class FixedInfo(C.Structure):
    _fields_ = [(name, W.DWORD) for name in ("signature", "struct_version", "file_ms", "file_ls",
                "product_ms", "product_ls", "flags_mask", "flags", "os", "type", "subtype", "date_ms", "date_ls")]


def api(dll, name, result, arguments):
    function = getattr(dll, name)
    function.restype, function.argtypes = result, arguments
    return function


def object_type_name(query, handle):
    """Read only the public type name for an already-owned duplicate handle."""
    buffer, returned = C.create_string_buffer(4096), W.ULONG()
    status = query(handle, 2, buffer, len(buffer), C.byref(returned)) & 0xFFFFFFFF
    if status:
        return {"status": f"0x{status:08x}", "name": None}
    text = UnicodeString.from_buffer_copy(buffer)
    lower, upper = C.addressof(buffer), C.addressof(buffer) + len(buffer)
    if not text.buffer or text.length % 2 or not lower <= text.buffer <= text.buffer + text.length <= upper:
        return {"status": "INVALID_TYPE_NAME_BUFFER", "name": None}
    name = C.wstring_at(text.buffer, text.length // 2)
    return {"status": "OK", "name": "File" if name == "File" else "UNEXPECTED_NON_FILE_TYPE"}


def version(path):
    v = C.WinDLL("version", use_last_error=True)
    size_of = api(v, "GetFileVersionInfoSizeW", W.DWORD, [W.LPCWSTR, C.POINTER(W.DWORD)])
    get = api(v, "GetFileVersionInfoW", W.BOOL, [W.LPCWSTR, W.DWORD, W.DWORD, C.c_void_p])
    query = api(v, "VerQueryValueW", W.BOOL, [C.c_void_p, W.LPCWSTR, C.POINTER(C.c_void_p), C.POINTER(W.UINT)])
    size = size_of(path, None)
    if not size or size > 8 * 1024 * 1024:
        return {"status": "UNAVAILABLE", "winerror": C.get_last_error()}
    buffer = C.create_string_buffer(size)
    pointer, length = C.c_void_p(), W.UINT()
    if not get(path, 0, size, buffer) or not query(buffer, "\\", C.byref(pointer), C.byref(length)):
        return {"status": "UNAVAILABLE", "winerror": C.get_last_error()}
    if length.value < C.sizeof(FixedInfo):
        return {"status": "UNAVAILABLE", "reason": "short version resource"}
    fixed = C.cast(pointer, C.POINTER(FixedInfo)).contents
    if fixed.signature != 0xFEEF04BD:
        return {"status": "UNAVAILABLE", "reason": "invalid version resource"}
    fmt = lambda high, low: ".".join(map(str, (high >> 16, high & 65535, low >> 16, low & 65535)))
    return {"file_version": fmt(fixed.file_ms, fixed.file_ls),
            "product_version": fmt(fixed.product_ms, fixed.product_ls),
            "evidence": "public on-disk version resource of path from module snapshot"}


def probe(pid):
    if os.name != "nt" or C.sizeof(C.c_void_p) != 8:
        raise RuntimeError("Requires 64-bit Windows interpreter")
    k = C.WinDLL("kernel32", use_last_error=True)
    n = C.WinDLL("ntdll", use_last_error=True)
    open_process = api(k, "OpenProcess", W.HANDLE, [W.DWORD, W.BOOL, W.DWORD])
    close = api(k, "CloseHandle", W.BOOL, [W.HANDLE])
    current = api(k, "GetCurrentProcess", W.HANDLE, [])
    image_name = api(k, "QueryFullProcessImageNameW", W.BOOL, [W.HANDLE, W.DWORD, W.LPWSTR, C.POINTER(W.DWORD)])
    process_id = api(k, "GetProcessId", W.DWORD, [W.HANDLE])
    exit_code = api(k, "GetExitCodeProcess", W.BOOL, [W.HANDLE, C.POINTER(W.DWORD)])
    process_times = api(k, "GetProcessTimes", W.BOOL, [W.HANDLE] + [C.POINTER(W.FILETIME)] * 4)
    duplicate = api(k, "DuplicateHandle", W.BOOL,
                    [W.HANDLE, W.HANDLE, W.HANDLE, C.POINTER(W.HANDLE), W.DWORD, W.BOOL, W.DWORD])
    file_type = api(k, "GetFileType", W.DWORD, [W.HANDLE])
    path_name = api(k, "GetFinalPathNameByHandleW", W.DWORD, [W.HANDLE, W.LPWSTR, W.DWORD, W.DWORD])
    query_handles = api(n, "NtQueryInformationProcess", C.c_long,
                        [W.HANDLE, W.ULONG, C.c_void_p, W.ULONG, C.POINTER(W.ULONG)])
    query_object = api(n, "NtQueryObject", C.c_long,
                       [W.HANDLE, W.ULONG, C.c_void_p, W.ULONG, C.POINTER(W.ULONG)])
    snapshot = api(k, "CreateToolhelp32Snapshot", W.HANDLE, [W.DWORD, W.DWORD])
    module_first = api(k, "Module32FirstW", W.BOOL, [W.HANDLE, C.POINTER(ModuleEntry)])
    module_next = api(k, "Module32NextW", W.BOOL, [W.HANDLE, C.POINTER(ModuleEntry)])
    # Query metadata and duplicate existing handles only; no VM_READ/WRITE or TERMINATE.
    process = open_process(0x0400 | 0x0040, False, pid)
    if not process:
        raise RuntimeError(f"OpenProcess metadata access failed: {C.get_last_error()}")
    report = {"pid": pid, "worker_pid": os.getpid(), "observed_at": datetime.now(timezone.utc).isoformat(),
              "mode": "explicit_process_handle_metadata_only", "process_access_mask": "0x0440",
              "ReadProcessMemory_calls": 0, "database_content_bytes_read": 0, "filesystem_searches": 0,
              "foreground_actions": 0, "account_identity_verified": False,
              "source_identity_verified": False, "keys_read": False,
              "limitations": ["An open database directory is process association, not authenticated account identity",
                              "Handle snapshot is transient and may miss unopened databases",
                              "No automatic child-process or account-directory fallback",
                              "Class 51 is an internal OS ABI; failure does not establish absence"]}
    try:
        length, image_buffer = W.DWORD(32768), C.create_unicode_buffer(32768)
        if not image_name(process, 0, image_buffer, C.byref(length)):
            raise RuntimeError(f"Process executable query failed: {C.get_last_error()}")
        # Do not publish an unrelated process path if PID was stale/reused.
        if Path(image_buffer.value).name.casefold() not in {"weixin.exe", "wechat.exe"}:
            raise RuntimeError("Explicit PID is not Weixin.exe or WeChat.exe")
        if process_id(process) != pid:
            raise RuntimeError("Process handle PID mismatch")
        report["executable_path"] = image_buffer.value
        report["process_executable"] = image_buffer.value
        times = [W.FILETIME() for _ in range(4)]
        if process_times(process, *(C.byref(t) for t in times)):
            report["creation_filetime"] = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
            report["process_creation_filetime"] = report["creation_filetime"]
        # Version evidence uses module enumeration, never a remote-memory read.
        modules = []
        snap = snapshot(0x00000008 | 0x00000010, pid)
        if snap == C.c_void_p(-1).value:
            report["module_snapshot_error"] = C.get_last_error()
        else:
            try:
                module = ModuleEntry()
                module.dwSize = C.sizeof(module)
                ok = module_first(snap, C.byref(module))
                for _ in range(2048):
                    if not ok:
                        break
                    if module.szModule.casefold() == "weixin.dll":
                        modules.append({"path": module.szExePath, "base_address": int(module.modBaseAddr or 0),
                                        "module_size": int(module.modBaseSize), **version(module.szExePath)})
                    ok = module_next(snap, C.byref(module))
                else:
                    report["module_snapshot_capped"] = True
            finally:
                close(snap)
        report["loaded_weixin_dll"] = modules
        if len(modules) == 1:
            report["loaded_weixin_dll_base"] = modules[0]["base_address"]
            report["loaded_weixin_dll_size"] = modules[0]["module_size"]
        size, returned = 65536, W.ULONG()
        for _ in range(8):
            if size > 16 * 1024 * 1024:
                raise RuntimeError("Handle snapshot exceeds 16 MiB bound")
            buffer = C.create_string_buffer(size)
            status = query_handles(process, 51, buffer, size, C.byref(returned)) & 0xFFFFFFFF
            if status == 0:
                break
            if status not in {0xC0000004, 0xC0000023}:
                raise RuntimeError(f"Class-51 snapshot unsupported/denied: 0x{status:08x}")
            size = max(size * 2, returned.value)
        else:
            raise RuntimeError("Handle snapshot did not stabilize within eight attempts")
        header = HandleHeader.from_buffer_copy(buffer)
        count = int(header.count)
        required = C.sizeof(HandleHeader) + count * C.sizeof(HandleEntry)
        if count > 100000 or required > size or (returned.value and required > returned.value):
            raise RuntimeError("Handle snapshot layout/count validation failed")
        failures = {"duplicate": 0, "disk_path": 0}
        duplicate_failures_by_type, successful_types, disk_types = {}, set(), set()
        disk_object_type_names = {}
        allowed = {}
        disk_handles = 0
        for index in range(count):
            entry = HandleEntry.from_buffer_copy(buffer, C.sizeof(HandleHeader) + index * C.sizeof(HandleEntry))
            own = W.HANDLE()
            # Zero requested access: metadata only. NEVER DUPLICATE_CLOSE_SOURCE.
            if not duplicate(process, entry.value, current(), C.byref(own), 0, False, 0):
                failures["duplicate"] += 1
                type_key = str(entry.type_index)
                duplicate_failures_by_type[type_key] = duplicate_failures_by_type.get(type_key, 0) + 1
                continue
            try:
                successful_types.add(int(entry.type_index))
                if file_type(own) != 1:
                    continue
                disk_types.add(int(entry.type_index))
                if str(entry.type_index) not in disk_object_type_names:
                    disk_object_type_names[str(entry.type_index)] = object_type_name(query_object, own)
                disk_handles += 1
                text_buffer = C.create_unicode_buffer(32768)
                # FILE_NAME_OPENED avoids normalized-path component traversal.
                got = path_name(own, text_buffer, len(text_buffer), 0x8)
                if not got or got >= len(text_buffer):
                    failures["disk_path"] += 1
                    continue
                path = text_buffer.value
                if path.startswith("\\\\?\\"):
                    path = path[4:]
                match = DB_PATH.fullmatch(path)
                if not match or not DB_NAMES[match["bucket"].lower()].fullmatch(match["name"]):
                    continue
                allowed[path.casefold()] = {"path": path, "account_directory": match["root"],
                                           "bucket": match["bucket"].lower()}
                if len(allowed) > 512:
                    raise RuntimeError("ALLOWLISTED_HANDLE_PATH_LIMIT")
            finally:
                close(own)
        report.update(handle_count=count, disk_handle_count=disk_handles, query_failures=failures)
        # ObjectTypeIndex identifies a kernel object type in this snapshot.
        # Verify the observed disk type's public name is File. A distinct type
        # index cannot conceal File handles even if that other type cannot be
        # duplicated. Its failure remains reported, but does not reduce the
        # coverage of file-handle path queries. No fixed type number is assumed.
        failed_disk = sum(value for key, value in duplicate_failures_by_type.items() if int(key) in disk_types)
        unknown_failed_types = sorted(int(key) for key in duplicate_failures_by_type if int(key) not in successful_types)
        verified_file_types = {int(key) for key, value in disk_object_type_names.items() if value["name"] == "File"}
        report.update(duplicate_failures_by_type_index=duplicate_failures_by_type,
                      successful_duplicate_type_indices=sorted(successful_types),
                      successful_disk_type_indices=sorted(disk_types),
                      disk_object_type_names=disk_object_type_names,
                      verified_file_type_indices=sorted(verified_file_types),
                      failed_duplicates_for_observed_disk_types=failed_disk,
                      unknown_failed_type_indices=unknown_failed_types,
                      duplicate_failure_scope="Other object-type indices are excluded from File-handle coverage only when observed disk types are directly verified as File")
        roots = {value["account_directory"].casefold() for value in allowed.values()}
        report["observed_account_root_count"] = len(roots)
        if len(roots) > 1:
            report.update(status="BLOCKED", reason="Multiple account roots observed; no binding selected",
                          database_handles=[], account_directory=None)
        elif len(roots) == 1:
            report.update(status="PARTIAL", reason="One open database root observed; authenticated identity still required",
                          database_handles=sorted(allowed.values(), key=lambda row: row["path"].casefold()),
                          account_directory=next(iter(allowed.values()))["account_directory"])
        else:
            report.update(status="BLOCKED", reason="No allowlisted database handles observed; no directory inferred",
                          database_handles=[], account_directory=None)
        required_paths = {}
        if len(roots) == 1:
            for value in allowed.values():
                bucket = value["bucket"]
                if bucket in {"contact", "sns"} and Path(value["path"]).name.casefold() == bucket + ".db":
                    required_paths[bucket] = value["path"]
        report["required_database_paths"] = required_paths
        report["contact_and_sns_base_handles_present"] = set(required_paths) == {"contact", "sns"}
        code = W.DWORD()
        if not exit_code(process, C.byref(code)) or code.value != 259:
            report.update(status="BLOCKED", reason="Target process exited during observation", account_directory=None)
        report["target_running_at_end"] = code.value == 259
        report["process_to_database_binding_complete"] = (
            len(roots) == 1 and report["contact_and_sns_base_handles_present"] and
            bool(disk_types) and disk_types == verified_file_types and failed_disk == 0 and
            failures["disk_path"] == 0 and report["target_running_at_end"] and
            "creation_filetime" in report)
        return report
    finally:
        close(process)


if __name__ == "__main__":
    try:
        if len(sys.argv) != 2 or not sys.argv[1].isdigit():
            raise ValueError()
        print(json.dumps(probe(int(sys.argv[1])), ensure_ascii=True))
    except Exception:
        sys.exit(1)

