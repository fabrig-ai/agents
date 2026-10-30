"""heavy: every build through admission (docs/design/fab.md, 7).

`heavy [--gate] [--] COMMAND...` waits for its lane and for disk, then runs COMMAND in a
systemd scope with its lane's CPU weight, passing its output and exit code through.
"""

from __future__ import annotations

import fcntl
import os
import shutil
import subprocess
import sys
import time
import tomllib
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from fab import log, slots

EX_TEMPFAIL = 75  # disk did not come free within the cap; the run reports `Infra: disk`
WEIGHTS = {"build": 1000, "gate": 10000}
GB = 1_000_000_000


@dataclass(frozen=True)
class Settings:
    builds: int = 3  # builds the build lane admits at once
    headroom: int = 10 * GB  # bytes that stay free for everything else
    allowance: int = 10 * GB  # bytes one build may still need
    cap: float = 1200.0  # seconds a build waits for disk before giving up
    poll: float = 30.0  # seconds between disk checks while waiting


def settings(host: str | None = None, *, path: Path | None = None) -> Settings:
    """This machine's settings: host (default the FAB_HOST environment variable) names its
    fab/hosts.toml entry, whose builds and headroom_gb override the defaults; an unknown or
    missing host keeps the defaults."""
    host = os.environ.get("FAB_HOST") if host is None else host
    if not host:
        return Settings()
    with (path or Path(__file__).with_name("hosts.toml")).open("rb") as source:
        entry = tomllib.load(source).get(host, {})
    defaults = Settings()
    return Settings(builds=entry.get("builds", defaults.builds),
                    headroom=entry.get("headroom_gb", defaults.headroom // GB) * GB)


def admit_disk(need: int, *, free: Callable[[], int], reclaim: Callable[[int], int],
               clock: Callable[[], float], sleep: Callable[[float], None],
               cap: float, poll: float, say: Callable[[str], None]) -> bool:
    """Wait until free() >= need: reclaim(need) whenever short, then sleep poll seconds; give up
    (False) once cap seconds have passed since the start while still short. say() is told once
    when waiting starts and once when it ends or gives up, with the bytes short."""
    started = clock()
    available = free()
    if available >= need:
        return True
    say(f"heavy: disk: waiting: {need - available} bytes short")
    while available < need:
        if clock() - started >= cap:
            say(f"heavy: disk: gave up: {need - available} bytes short")
            return False
        reclaim(need)
        available = free()
        if available >= need:
            break
        remaining = cap - (clock() - started)
        if remaining > 0:
            sleep(min(poll, remaining))
        available = free()
    say("heavy: disk: ready: 0 bytes short")
    return True


@contextmanager
def lane(name: str, builds: int, home: Path) -> Iterator[None]:
    """Hold a place in a lane until the block ends. build: one of `home/heavy/build-<k>.lock`
    (k < builds) taken with a non-blocking flock, polling every second until one is free.
    gate: `home/heavy/gate.lock`, blocking. A holder that dies releases its place (flock)."""
    if name not in WEIGHTS:
        raise ValueError(f"unknown lane {name!r}")
    if name == "build" and builds < 1:
        raise ValueError("build lane needs at least one place")
    directory = home / "heavy"
    directory.mkdir(parents=True, exist_ok=True)
    if name == "gate":
        with (directory / "gate.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)
        return
    while True:
        for k in range(builds):
            lock = (directory / f"build-{k}.lock").open("a")
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                lock.close()
                continue
            except BaseException:
                lock.close()
                raise
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)
                lock.close()
            return
        time.sleep(1)


def wrap(argv: Sequence[str], lane_name: str, *, systemd: bool) -> list[str]:
    """argv in a user scope with the lane's CPU weight when systemd is available:
    `systemd-run --user --scope --quiet -p CPUWeight=<w> -- argv`; argv unchanged otherwise."""
    if not systemd:
        return list(argv)
    return ["systemd-run", "--user", "--scope", "--quiet", "-p",
            f"CPUWeight={WEIGHTS[lane_name]}", "--", *argv]


def main(argv: list[str]) -> int:
    """Parse `[--gate] [--] COMMAND...` (no command: usage, exit 2). `cargo fmt ...` runs directly,
    with no lane or disk wait. Otherwise: take the lane, then admit_disk(headroom + allowance) with
    fab.slots.reclaim and fab.slots.free_bytes; past the cap print `heavy: Infra: disk: ...` to
    stderr and exit EX_TEMPFAIL. Run the wrapped command with inherited stdio and return its exit
    code. Append one record per command to FAB_HOME/heavy.jsonl (fab.log.append with path):
    ev "heavy", lane, argv0, lane_wait, disk_wait, seconds, code."""
    lane_name = "build"
    if argv[:1] == ["--gate"]:
        lane_name, argv = "gate", argv[1:]
    if argv[:1] == ["--"]:
        argv = argv[1:]
    if not argv:
        print("usage: heavy [--gate] [--] COMMAND...", file=sys.stderr)
        return 2

    home = log.home()
    started = time.monotonic()
    lane_wait = disk_wait = 0.0
    if argv[:2] == ["cargo", "fmt"]:
        code = subprocess.run(argv).returncode
    else:
        config = settings()
        lane_started = time.monotonic()
        with lane(lane_name, config.builds, home):
            admitted = time.monotonic()
            lane_wait = admitted - lane_started
            need = config.headroom + config.allowance
            ready = admit_disk(need, free=slots.free_bytes, reclaim=slots.reclaim,
                               clock=time.monotonic, sleep=time.sleep,
                               cap=config.cap, poll=config.poll,
                               say=lambda message: print(message, file=sys.stderr))
            disk_wait = time.monotonic() - admitted
            if not ready:
                print(f"heavy: Infra: disk: admission timed out after {disk_wait:.1f} s; "
                      f"need {need} bytes free", file=sys.stderr)
                code = EX_TEMPFAIL
            else:
                systemd = bool(os.environ.get("XDG_RUNTIME_DIR") and shutil.which("systemd-run"))
                code = subprocess.run(wrap(argv, lane_name, systemd=systemd)).returncode
    log.append("heavy", path=home / "heavy.jsonl", lane=lane_name, argv0=argv[0],
               lane_wait=lane_wait, disk_wait=disk_wait,
               seconds=time.monotonic() - started, code=code)
    return code
