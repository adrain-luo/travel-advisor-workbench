"""Bounded stable copies of explicit, process-bound database paths only."""
from pathlib import Path
import hashlib
import shutil


class SnapshotError(RuntimeError):
    pass


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def metadata(path):
    try:
        s = path.stat()
        return (s.st_size, s.st_mtime_ns, s.st_ino)
    except FileNotFoundError:
        return None


def capture(paths, account_dir, output_dir, *, byte_budget=512 * 1024 * 1024):
    """Copy DB+WAL, require two whole-source hash sweeps to agree with copies.

    This proves stable input bytes for authenticated WAL validation, not atomic
    cross-database transactions. Only named DBs and their WAL siblings are read.
    """
    account, output = Path(account_dir).resolve(strict=True), Path(output_dir).resolve()
    if output.is_relative_to(account) or not paths or len(paths) > 128:
        raise SnapshotError("SNAPSHOT_SCOPE_INVALID")
    candidates = []
    for kind, path in paths.items():
        source = Path(path).resolve(strict=True)
        bucket = "message" if kind.startswith("message_") else kind
        expected = account / "db_storage" / bucket / (kind + ".db")
        if source != expected.resolve(strict=True):
            raise SnapshotError("SNAPSHOT_SOURCE_NOT_BOUND")
        for suffix in ("", "-wal"):
            candidates.append((kind, suffix, Path(str(source) + suffix)))
    output.mkdir(parents=True, exist_ok=False)
    for attempt in range(1, 4):
        folder = output / ("attempt-" + str(attempt)); folder.mkdir()
        before = {str(p): metadata(p) for _, _, p in candidates}
        if any(before[str(p)] is None for _, suffix, p in candidates if not suffix):
            raise SnapshotError("SOURCE_DATABASE_MISSING")
        if sum(meta[0] for meta in before.values() if meta) > byte_budget:
            raise SnapshotError("SNAPSHOT_BYTE_BUDGET_EXCEEDED")
        copied = []
        try:
            for kind, suffix, src in candidates:
                if before[str(src)] is None:
                    continue
                dst = folder / (kind + ".db" + suffix)
                shutil.copyfile(src, dst)
                copied.append({"kind": kind, "suffix": suffix, "source_path": str(src),
                               "copy_path": str(dst), "sha256": digest(dst)})
            first = {r["source_path"]: digest(r["source_path"]) for r in copied}
            second = {r["source_path"]: digest(r["source_path"]) for r in copied}
            after = {str(p): metadata(p) for _, _, p in candidates}
        except FileNotFoundError:
            continue
        if before == after and all(first[r["source_path"]] == second[r["source_path"]] == r["sha256"] for r in copied):
            return {"files": copied, "attempts": attempt, "stable": True,
                    "cross_database_transaction_atomicity_claimed": False}
    raise SnapshotError("SOURCE_SNAPSHOT_UNSTABLE")
