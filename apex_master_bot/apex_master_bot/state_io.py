"""Atomic single-file writes and advisory serialization for a shared local ledger."""
import csv
import fcntl
import io
import os
import subprocess
import tempfile
from functools import wraps
from inspect import signature
from pathlib import Path


def atomic_text(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="", dir=path.parent,
                                     prefix=f".{path.name}.", delete=False) as tmp:
        try:
            tmp.write(content)
            tmp.flush()
            os.fsync(tmp.fileno())
            tmp.close()
            os.replace(tmp.name, path)
        finally:
            Path(tmp.name).unlink(missing_ok=True)


def append_unique(path, fields, rows, key):
    path = Path(path)
    existing = []
    if path.exists():
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames != fields:
                raise ValueError(f"unexpected ledger schema in {path.name}")
            existing = list(reader)
            if any(None in row or any(v is None for v in row.values()) for row in existing):
                raise ValueError(f"incomplete row in {path.name}")
    keys = {tuple(row[k] for k in key) for row in existing}
    added = []
    for row in rows:
        values = tuple(str(row[k]) for k in key)
        if values not in keys:
            added.append({k: row.get(k, "") for k in fields})
            keys.add(values)
    if added:
        out = io.StringIO(newline="")
        writer = csv.DictWriter(out, fieldnames=fields)
        writer.writeheader()
        writer.writerows(existing)
        writer.writerows(added)
        atomic_text(path, out.getvalue())
    return len(added)


def ledger_lock(func):
    sig = signature(func)

    @wraps(func)
    def locked(*args, **kwargs):
        root = Path(sig.bind(*args, **kwargs).arguments["ledger_dir"])
        root.mkdir(parents=True, exist_ok=True)
        # The inode must survive each lock release so waiting processes share the same lock.
        with (root / ".v2.lock").open("a") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            return func(*args, **kwargs)

    return locked


def git_revision():
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=Path(__file__).parent,
            stderr=subprocess.DEVNULL, text=True, timeout=5,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return None
