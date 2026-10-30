"""The event log: one JSON object per line, appended, never changed (docs/design/fab.md, 3)."""

from __future__ import annotations

import fcntl
import json
import os
import re
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

EVENT = re.compile(r"^[a-z]+(\.[a-z]+)*$")
SCALARS = (str, int, float, bool, type(None))


def home() -> Path:
    """FAB_HOME: fab's runtime data on this machine."""
    return Path(os.environ.get("FAB_HOME") or Path.home() / "src/fabrig/fab")


def default_path() -> Path:
    return home() / "log.jsonl"


def now() -> str:
    """UTC to the millisecond, as every record's ts."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def record(ev: str, *, ts: str | None = None, **fields) -> dict:
    """A validated record: a known-shape type and flat fields."""
    if not EVENT.match(ev):
        raise ValueError(f"event type {ev!r} is not dotted lowercase words")
    for key, value in fields.items():
        flat = all(isinstance(item, SCALARS) for item in value) if isinstance(value, list | tuple) else \
            isinstance(value, SCALARS)
        if not flat:
            raise ValueError(f"field {key!r} is not a scalar or a list of scalars")
    return {"ts": ts or now(), "ev": ev, **{k: list(v) if isinstance(v, tuple) else v for k, v in fields.items()}}


def append(ev: str, *, path: Path | None = None, ts: str | None = None, **fields) -> dict:
    """Append one record under the log's lock and make it durable; return it."""
    entry = record(ev, ts=ts, **fields)
    line = json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n"
    path = path or default_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path.with_name(path.name + ".lock"), "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        with open(path, "a+b") as log:
            # A torn last line (a crash mid-write) is closed off, so it stays one bad line.
            if log.tell() and (log.seek(-1, os.SEEK_END), log.read(1))[1] != b"\n":
                log.write(b"\n")
            log.write(line.encode())
            log.flush()
            os.fsync(log.fileno())
    return entry


def read(path: Path | None = None) -> list[dict]:
    """Every record, oldest first; lines that do not parse (a torn write) are skipped."""
    return list(iterate(path))


def iterate(path: Path | None = None) -> Iterator[dict]:
    path = path or default_path()
    try:
        log = open(path, encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return
    with log:
        for line in log:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(entry, dict) and isinstance(entry.get("ev"), str):
                yield entry
