"""heavy: every build through admission (docs/design/fab.md, 7).

`heavy [--gate] [--] COMMAND...` waits for its lane and for disk, then runs COMMAND in a
systemd scope with its lane's CPU weight, passing its output and exit code through.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

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


def settings(host: str | None = None) -> Settings:
    """This machine's settings: host (default the FAB_HOST environment variable) names its
    fab/hosts.toml entry, whose builds and headroom_gb override the defaults; an unknown or
    missing host keeps the defaults."""
    raise NotImplementedError


def admit_disk(need: int, *, free: Callable[[], int], reclaim: Callable[[int], int],
               clock: Callable[[], float], sleep: Callable[[float], None],
               cap: float, poll: float, say: Callable[[str], None]) -> bool:
    """Wait until free() >= need: reclaim(need) whenever short, then sleep poll seconds; give up
    (False) once cap seconds have passed since the start while still short. say() is told once
    when waiting starts and once when it ends or gives up, with the bytes short."""
    raise NotImplementedError


@contextmanager
def lane(name: str, builds: int, home: Path) -> Iterator[None]:
    """Hold a place in a lane until the block ends. build: one of `home/heavy/build-<k>.lock`
    (k < builds) taken with a non-blocking flock, polling every second until one is free.
    gate: `home/heavy/gate.lock`, blocking. A holder that dies releases its place (flock)."""
    raise NotImplementedError


def wrap(argv: Sequence[str], lane_name: str, *, systemd: bool) -> list[str]:
    """argv in a user scope with the lane's CPU weight when systemd is available:
    `systemd-run --user --scope --quiet -p CPUWeight=<w> -- argv`; argv unchanged otherwise."""
    raise NotImplementedError


def main(argv: list[str]) -> int:
    """Parse `[--gate] [--] COMMAND...` (no command: usage, exit 2). `cargo fmt ...` runs directly,
    with no lane or disk wait. Otherwise: take the lane, then admit_disk(headroom + allowance) with
    fab.slots.reclaim and fab.slots.free_bytes; past the cap print `heavy: Infra: disk: ...` to
    stderr and exit EX_TEMPFAIL. Run the wrapped command with inherited stdio and return its exit
    code. Append one record per command to FAB_HOME/heavy.jsonl (fab.log.append with path):
    ev "heavy", lane, argv0, lane_wait, disk_wait, seconds, code."""
    raise NotImplementedError
