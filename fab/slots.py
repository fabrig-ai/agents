"""Slots on a builder: claims, the sweep that bounds a slot, reclaim (docs/design/fab-machines.md, 2).

Runs on the builder itself; the dispatcher calls it over ssh (`bin/fab slot ...`).
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import stat
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from fab import log

# A test executable is a regular, user-executable file in a profile's deps/ without these suffixes.
NOT_EXECUTABLES = (".so", ".rlib", ".rmeta", ".d")


def slots_dir() -> Path:
    """FAB_SLOTS, or ~/src/fabrig/slots: slot n is the checkout `<dir>/<n>`, its claim `<dir>/<n>.claim`,
    its last release time the mtime of `<dir>/<n>.released`."""
    return Path(os.environ.get("FAB_SLOTS") or Path.home() / "src/fabrig/slots")


@dataclass(frozen=True)
class Claim:
    slot: int
    run: str
    task: str
    since: str  # fab.log.now() when claimed


def slots() -> list[int]:
    """The numbered slot checkouts that exist, ascending."""
    try:
        entries = slots_dir().iterdir()
        return sorted(int(p.name) for p in entries
                      if p.name.isdecimal() and p.name == str(int(p.name))
                      and not p.is_symlink() and p.is_dir())
    except FileNotFoundError:
        return []


def claim(slot: int, run: str, task: str) -> Claim | None:
    """Claim a slot for a run: create its claim file exclusively (O_EXCL) and return the Claim;
    None when it is already claimed. A slot that does not exist is a ValueError."""
    directory = slots_dir()
    checkout = directory / str(slot)
    if checkout.is_symlink() or not checkout.is_dir():
        raise ValueError(f"slot {slot} does not exist")
    held = Claim(slot, run, task, log.now())
    path = directory / f"{slot}.claim"
    # Prepare the complete record before reserving its name exclusively.
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory,
                                     prefix=f".{slot}.claim.", delete=False) as stream:
        temporary = Path(stream.name)
        try:
            json.dump(asdict(held), stream, sort_keys=True)
            stream.write("\n")
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            return None
        os.close(fd)
        try:
            temporary.replace(path)
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        return held
    finally:
        temporary.unlink(missing_ok=True)


def read_claim(slot: int) -> Claim | None:
    try:
        data = json.loads((slots_dir() / f"{slot}.claim").read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    return Claim(**data)


def release(slot: int, run: str) -> int:
    """End a run's hold on its slot: sweep what the run did not write (sweep_plan with since = the
    claim's time), remove the claim, touch the release marker; return the bytes freed.
    A claim held by another run is left alone and is a ValueError; no claim releases nothing (0)."""
    held = read_claim(slot)
    if held is None:
        return 0
    if held.run != run:
        raise ValueError(f"slot {slot} is held by {held.run!r}")
    stamp = datetime.fromisoformat(held.since)
    since_ns = int(stamp.timestamp()) * 1_000_000_000 + stamp.microsecond * 1000
    freed = remove(sweep_plan(slots_dir() / str(slot) / "target", since_ns))
    # Keep the claim until all release work is complete.
    (slots_dir() / f"{slot}.released").touch()
    (slots_dir() / f"{slot}.claim").unlink()
    return freed


def idle() -> list[int]:
    """Unclaimed slots, least recently released first (a slot never released counts as oldest)."""
    def released(slot):
        try:
            return (1, (slots_dir() / f"{slot}.released").stat().st_mtime_ns, slot)
        except FileNotFoundError:
            return (0, 0, slot)

    return sorted((slot for slot in slots()
                   if not (slots_dir() / f"{slot}.claim").exists()), key=released)


def sweep_plan(target: Path, since_ns: int | None) -> list[Path]:
    """What to delete from a cargo target directory to bound it, sorted: every `incremental*`
    directory directly under a profile directory (`<target>/<profile>/incremental*`), and every
    test executable in `<target>/<profile>/deps` whose mtime is older than since_ns (every one
    when since_ns is None). Symlinks are never followed or listed."""
    if target.is_symlink() or not target.is_dir():
        return []
    plan = []
    for profile in target.iterdir():
        if profile.is_symlink() or not profile.is_dir():
            continue
        for entry in profile.iterdir():
            if entry.is_symlink():
                continue
            if entry.name.startswith("incremental") and entry.is_dir():
                plan.append(entry)
            elif entry.name == "deps" and entry.is_dir():
                for candidate in entry.iterdir():
                    try:
                        info = candidate.lstat()
                    except FileNotFoundError:
                        continue
                    if (stat.S_ISREG(info.st_mode) and info.st_mode & stat.S_IXUSR
                            and not candidate.name.endswith(NOT_EXECUTABLES)
                            and (since_ns is None or info.st_mtime_ns < since_ns)):
                        plan.append(candidate)
    return sorted(plan)


def remove(paths: list[Path]) -> int:
    """Delete files and directory trees; return the bytes they occupied (st_blocks * 512).
    A path that vanished meanwhile is skipped."""
    seen = set()

    def size(path):
        try:
            info = path.lstat()
        except FileNotFoundError:
            return 0
        inode = (info.st_dev, info.st_ino)
        if inode in seen:
            return 0
        seen.add(inode)
        total = info.st_blocks * 512
        if stat.S_ISDIR(info.st_mode):
            try:
                total += sum(size(child) for child in path.iterdir())
            except FileNotFoundError:
                pass
        return total

    freed = 0
    for path in paths:
        occupied = size(path)
        try:
            if stat.S_ISDIR(path.lstat().st_mode):
                shutil.rmtree(path)
            else:
                path.unlink()
        except FileNotFoundError:
            continue
        freed += occupied
    return freed


def free_bytes(path: Path | None = None) -> int:
    """Bytes available to this user on the filesystem holding path (slots_dir() by default)."""
    info = os.statvfs(slots_dir() if path is None else path)
    return info.f_bavail * info.f_frsize


def reclaim(need: int, *, free=free_bytes) -> int:
    """Free disk until free() >= need, taking from idle slots only; return the bytes freed.

    First pass, least recently released first: each idle slot's sweep_plan(target, None).
    Second pass, same order: each idle slot's whole target directory. Stop as soon as
    free() >= need. Each slot is claimed (run "reclaim") while it is worked on and its claim
    removed after, without touching its release marker; a slot that cannot be claimed is skipped.
    """
    freed = 0
    if free() >= need:
        return freed
    candidates = idle()
    for whole_target in (False, True):
        for slot in candidates:
            if free() >= need:
                return freed
            if claim(slot, "reclaim", "reclaim") is None:
                continue
            try:
                target = slots_dir() / str(slot) / "target"
                paths = [target] if whole_target else sweep_plan(target, None)
                freed += remove(paths)
            finally:
                (slots_dir() / f"{slot}.claim").unlink()
    return freed


def main(argv: list[str]) -> int:
    """`fab slot list` (one JSON line per slot: slot, claim fields or null, idle rank),
    `fab slot claim N RUN TASK` (exit 1 if held), `fab slot release N RUN` (prints bytes freed),
    `fab slot reclaim --need-gb G` (prints bytes freed and free bytes; exit 1 if still short)."""
    parser = argparse.ArgumentParser(prog="fab slot", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list")
    claiming = commands.add_parser("claim")
    claiming.add_argument("slot", type=int)
    claiming.add_argument("run")
    claiming.add_argument("task")
    releasing = commands.add_parser("release")
    releasing.add_argument("slot", type=int)
    releasing.add_argument("run")
    reclaiming = commands.add_parser("reclaim")
    reclaiming.add_argument("--need-gb", type=float, required=True)
    args = parser.parse_args(argv)
    if args.command == "list":
        ranks = {slot: rank for rank, slot in enumerate(idle())}
        for slot in slots():
            held = read_claim(slot)
            print(json.dumps({"slot": slot, "claim": asdict(held) if held else None,
                              "idle": ranks.get(slot)}, sort_keys=True))
        return 0
    try:
        if args.command == "claim":
            return 0 if claim(args.slot, args.run, args.task) is not None else 1
        if args.command == "release":
            print(release(args.slot, args.run))
            return 0
        if not math.isfinite(args.need_gb) or args.need_gb < 0:
            parser.error("--need-gb must be finite and nonnegative")
        need = int(args.need_gb * 1_000_000_000)
        freed = reclaim(need)
        available = free_bytes()
        print(json.dumps({"freed": freed, "free": available}, sort_keys=True))
        return 0 if available >= need else 1
    except ValueError as error:
        parser.error(str(error))
