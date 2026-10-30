"""Bounded, read-only WeChat storage feasibility probe; never a scan/import.

Reads database headers/schema only and samples media format signatures. It does
not read message rows, login stores, process memory, keys, or network endpoints.
Exact-byte matches to previously authorized saved media can optionally be copied
to an evidence directory. Such matches do not establish record/history coverage.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3


DATABASES = ("contact/contact.db", "session/session.db", "message/message_0.db",
             "message/message_resource.db", "sns/sns.db")
MEDIA_BUCKETS = ("msg/attach", "msg/file", "business/sns")


def file_hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def signature(header):
    if header.startswith(b"SQLite format 3\x00"):
        return "sqlite"
    if header.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if header.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if header.startswith(b"RIFF") and header[8:12] == b"WEBP":
        return "webp"
    if header.startswith(b"%PDF-"):
        return "pdf"
    if header.startswith(b"PK\x03\x04"):
        return "zip_container"
    if header.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        return "compound_document"
    if header.startswith(b"\x07\x08V2"):
        return "wechat_v2_container_candidate"
    if header.startswith(b"\x07\x08V1"):
        return "wechat_v1_container_candidate"
    if header[4:8] == b"ftyp":
        return "iso_media_container"
    return "opaque_or_other"


def bounded_files(root, limit):
    count = 0
    if not root.exists():
        return
    for current, directories, files in os.walk(root, followlinks=False):
        directories[:] = sorted(d for d in directories if not (Path(current) / d).is_symlink()
                                and not (Path(current) / d).is_junction())
        for name in sorted(files):
            path = Path(current) / name
            if path.is_symlink() or not path.is_file():
                continue
            yield path
            count += 1
            if count >= limit:
                return


def probe_database(path):
    result = {"exists": path.is_file(), "rows_read": 0}
    if not result["exists"]:
        return result
    stat = path.stat()
    with path.open("rb") as stream:
        header = stream.read(32)
    result.update(size=stat.st_size, signature=signature(header),
                  header_sha256=hashlib.sha256(header).hexdigest(),
                  wal_present=Path(str(path) + "-wal").exists())
    # immutable prevents SQLite from creating or updating any sidecar files.
    # This is a format test, not a coherent live snapshot or content query.
    try:
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)) as db:
            result["schema_object_count"] = db.execute("SELECT count(*) FROM sqlite_master").fetchone()[0]
        result["ordinary_sqlite_readable"] = True
    except sqlite3.DatabaseError as exc:
        result.update(ordinary_sqlite_readable=False, sqlite_error=str(exc))
    result["unchanged_metadata"] = (stat.st_size, stat.st_mtime_ns) == (path.stat().st_size, path.stat().st_mtime_ns)
    return result


def probe(root, references, output, limit=10000, sample_limit=8):
    root, output = root.resolve(), output.resolve()
    if not root.is_dir():
        raise ValueError("WeChat data directory does not exist")
    if output.is_relative_to(root):
        raise ValueError("Evidence output must be outside the WeChat data directory")
    refs = []
    for reference in references:
        refs.append({"path": str(reference.resolve()), "size": reference.stat().st_size,
                     "sha256": file_hash(reference)})
    report = {"observed_at": datetime.now(timezone.utc).isoformat(), "data_root": str(root),
              "mode": "read_only_metadata_and_signatures", "collection_run": False,
              "source_identity_verified": False, "account_identity_verified": False,
              "historical_coverage": "UNKNOWN", "source_records_saved": 0,
              "media_associations_verified": 0, "reference_media": refs, "accounts": [],
              "skipped": ["login_and_key_stores", "message_rows", "process_memory", "decryption",
                          "network_backfill", "foreground_input", "online_documents"]}
    for account in sorted(root.glob("wxid_*")):
        if not account.is_dir() or account.is_symlink() or account.is_junction():
            continue
        row = {"directory": account.name, "directory_name_is_not_verified_account_binding": True,
               "databases": {}, "media": {}}
        for relative in DATABASES:
            row["databases"][relative] = probe_database(account / "db_storage" / relative)
        for bucket in MEDIA_BUCKETS:
            location = account / bucket
            counts, samples, matches = Counter(), [], []
            total_bytes, visited, failures = 0, 0, 0
            for path in bounded_files(location, limit):
                visited += 1
                try:
                    stat = path.stat()
                    total_bytes += stat.st_size
                    counts[path.suffix.lower() or "[none]"] += 1
                    if len(samples) < sample_limit:
                        with path.open("rb") as stream:
                            header = stream.read(32)
                        # Avoid exposing unrelated document names/content in reports.
                        samples.append({"relative_path_sha256": hashlib.sha256(str(path.relative_to(account)).encode()).hexdigest(),
                                        "size": stat.st_size, "extension": path.suffix.lower(),
                                        "signature": signature(header)})
                    candidates = [ref for ref in refs if ref["size"] == stat.st_size]
                    if candidates:
                        digest = file_hash(path)
                        for ref in candidates:
                            if digest != ref["sha256"]:
                                continue
                            destination = output.parent / "matched-media" / digest
                            destination.parent.mkdir(parents=True, exist_ok=True)
                            if not destination.exists():
                                shutil.copyfile(path, destination)
                            if file_hash(destination) != digest:
                                raise ValueError("Copied reference media hash mismatch")
                            matches.append({"relative_path": str(path.relative_to(root)), "sha256": digest,
                                            "saved_path": str(destination), "reference_path": ref["path"],
                                            "method": "exact_bytes_match_to_prior_manual_evidence",
                                            "record_association_verified": False})
                except OSError:
                    failures += 1
            row["media"][bucket] = {"exists": location.exists(), "files_observed": visited,
                                     "enumeration_complete": visited < limit, "limit": limit,
                                     "bytes_observed": total_bytes, "extensions": dict(counts),
                                     "signature_samples": samples, "exact_reference_matches": matches,
                                     "read_failures": failures}
        report["accounts"].append(row)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reference", action="append", type=Path, default=[])
    parser.add_argument("--limit", type=int, default=10000)
    args = parser.parse_args()
    if not 1 <= args.limit <= 10000:
        parser.error("limit must be between 1 and 10000")
    data = probe(args.root, args.reference, args.output, args.limit)
    print(json.dumps({"output": str(args.output), "accounts": len(data["accounts"]),
                      "source_records_saved": 0, "source_identity_verified": False,
                      "matched_media": sum(len(bucket["exact_reference_matches"])
                                           for account in data["accounts"] for bucket in account["media"].values())}))
