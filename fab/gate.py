"""fabrig's checks: which packages a change selects, and the steps that check them (docs/design/fab.md, 6).

Shared by the queue (the gate lane, on the merge candidate) and precheck (the build lane, in an
implementer's slot). Ported from fabrig's tools/queue/mq, whose selection rules it keeps.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from fab.sh import Runner, run

TREES = ("skein", "smith", "jig", "temper")
# Gate configuration in the checked checkout; the first existing directory wins.
CONFIG_DIRS = (".config/gate", "tools/queue")
STEP_TIMEOUT = 3 * 3600
NO_TESTS = 4  # nextest's exit when a selection holds no tests: green for build, default and fuzzy


@dataclass(frozen=True)
class Step:
    name: str
    argv: tuple[str, ...]
    cwd: str


@dataclass(frozen=True)
class StepResult:
    name: str
    argv: tuple[str, ...]
    code: int
    green: bool
    seconds: float


def full_inputs(paths: Iterable[str]) -> bool:
    """A change to the root Cargo.toml, any rustfmt.toml, clippy.toml, rust-toolchain* or anything
    under a .config directory checks the whole workspace."""
    raise NotImplementedError


def package_owners(metadata: dict) -> list[tuple[str, str]]:
    """(directory relative to the workspace root, package id) for each workspace member, deepest first."""
    raise NotImplementedError


def lock_changes(base_lock: str, head_lock: str, metadata: dict) -> set[str]:
    """Package ids (from metadata's packages) whose Cargo.lock entry (name, version, source,
    dependencies) differs between the two lock files' texts."""
    raise NotImplementedError


def selection(paths: Sequence[str], metadata: dict, *, always: Sequence[str], read_by_tests: Sequence[str],
              locked: set[str] | None = None) -> str | set[str]:
    """"full", "docs", or the package names to check, exactly as fabrig's tools/queue/mq `selection`:
    full_inputs or a read_by_tests glob match is full; tools/ paths are ignored; Cargo.lock selects
    `locked` (required then, else ValueError); a path in a package's Cargo.toml, build.rs, src/,
    tests/, benches/ or examples/ selects it; any other non-Markdown path is full; nothing selected
    and no lock change is docs; otherwise the selected packages, their reverse dependencies through
    metadata's resolve graph (all edge kinds), and `always` (a name missing from the workspace is a
    ValueError)."""
    raise NotImplementedError


def config(repo: Path) -> tuple[list[str], list[str]]:
    """(always, read_by_tests) from always.txt and read-by-tests.txt in the first CONFIG_DIRS
    directory that exists in repo; blank lines and # comments dropped."""
    raise NotImplementedError


def changed_paths(repo: Path, candidate: str = "HEAD", base: str = "origin/main", *, sh: Runner = run) -> list[str]:
    """Paths differing between base and candidate, renames as both sides (`--no-renames`)."""
    raise NotImplementedError


def metadata(repo: Path, *, sh: Runner = run) -> dict:
    """cargo metadata --no-deps (workspace_root, workspace_members) with the full run's packages
    and resolve graph merged in, both --locked."""
    raise NotImplementedError


def select(repo: Path, paths: Sequence[str], *, base: str = "origin/main", candidate: str = "HEAD",
           sh: Runner = run, load: Callable[[Path], dict] | None = None) -> str | set[str]:
    """The selection for a checked-out candidate: full_inputs is full without loading metadata;
    only Markdown outside src/tests/benches/examples and tools/ paths need no metadata; otherwise
    metadata (load, default `metadata`), lock_changes from the base's and candidate's Cargo.lock when
    it changed, and `selection` with this repo's config."""
    raise NotImplementedError


def ratchet_steps(repo: Path, paths: Sequence[str], *, write: bool) -> list[Step]:
    """One `ratchet:<tree>` step per tree the paths touch: `python3 -I -B <tree>/scripts/old_forms.py`,
    with --write when write, run in the tree's directory."""
    raise NotImplementedError


def check_steps(repo: Path, selected: str | set[str], paths: Sequence[str], meta: dict | None,
                *, lane: str) -> list[Step]:
    """The checks for a selection, as fabrig's mq check_commands: fmt (--all --check when full;
    otherwise --check scoped to the packages owning changed .rs files, when any), then, unless docs,
    clippy (--all-targets -- -D warnings), build (nextest run --no-run), default (nextest run
    --no-fail-fast) and fuzzy (the same with --profile fuzzy), each through heavy (`heavy --gate`
    when lane is "gate", plain `heavy` when "build"), scoped by --workspace or -p per package."""
    raise NotImplementedError


def run_steps(steps: Sequence[Step], log: Path, *, sh: Runner = run, timeout: float = STEP_TIMEOUT,
              clock: Callable[[], float] | None = None) -> list[StepResult]:
    """Run steps in order, appending each one's command line and output to log; stop after the first
    red. Green is exit 0, or NO_TESTS for build, default and fuzzy. clock defaults to time.monotonic."""
    raise NotImplementedError
