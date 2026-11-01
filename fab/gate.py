"""fabrig's checks: which packages a change selects, and the steps that check them (docs/design/landing.md, 2).

Shared by the queue (the gate lane, on the merge candidate) and precheck (the build lane, in an
implementer's slot). Ported from fabrig's tools/queue/mq, whose selection rules it keeps.
"""

from __future__ import annotations

import fnmatch
import json
import shlex
import time
import tomllib
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from fab import atomic
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
    return any(path == "Cargo.toml" or
               PurePosixPath(path).name in ("rustfmt.toml", "clippy.toml") or
               PurePosixPath(path).name.startswith("rust-toolchain") or
               ".config" in PurePosixPath(path).parts for path in paths)


def package_owners(metadata: dict) -> list[tuple[str, str]]:
    """(directory relative to the workspace root, package id) for each workspace member, deepest first."""
    root = Path(metadata["workspace_root"])
    members = set(metadata["workspace_members"])
    owners = [(Path(package["manifest_path"]).parent.relative_to(root).as_posix(), package["id"])
              for package in metadata["packages"] if package["id"] in members]
    return sorted(owners, key=lambda owner: len(PurePosixPath(owner[0]).parts), reverse=True)


def lock_changes(base_lock: str, head_lock: str, metadata: dict) -> set[str]:
    """Package ids (from metadata's packages) whose Cargo.lock entry (name, version, source,
    dependencies) differs between the two lock files' texts."""
    def entries(document):
        return {(package["name"], package["version"], package.get("source")):
                tuple(sorted(package.get("dependencies", [])))
                for package in tomllib.loads(document).get("package", [])}

    before, after = entries(base_lock), entries(head_lock)
    changed = {key for key in before.keys() | after.keys() if before.get(key) != after.get(key)}
    return {package["id"] for package in metadata["packages"]
            if (package["name"], package["version"], package.get("source")) in changed}


def selection(paths: Sequence[str], metadata: dict, *, always: Sequence[str], read_by_tests: Sequence[str],
              locked: set[str] | None = None) -> str | set[str]:
    """"full", "docs", or the package names to check, exactly as fabrig's tools/queue/mq `selection`:
    full_inputs or a read_by_tests glob match is full; tools/ paths are ignored; Cargo.lock selects
    `locked` (required then, else ValueError); a path in a package's Cargo.toml, build.rs, src/,
    tests/, benches/ or examples/ selects it; any other non-Markdown path is full; nothing selected
    and no lock change is docs; otherwise the selected packages, their reverse dependencies through
    metadata's resolve graph (all edge kinds), and `always` (a name missing from the workspace is a
    ValueError)."""
    if full_inputs(paths) or any(fnmatch.fnmatchcase(path, pattern)
                                for path in paths for pattern in read_by_tests):
        return "full"
    members = set(metadata.get("workspace_members", []))
    packages = {p["id"]: p for p in metadata.get("packages", []) if p["id"] in members}
    owners = package_owners(metadata) if metadata else []
    selected = set()
    for path in paths:
        if path.startswith("tools/"):
            continue
        if path == "Cargo.lock":
            if locked is None:
                raise ValueError("lockfile selection requires base and HEAD lock entries")
            selected.update(locked)
            continue
        for directory, package_id in owners:
            try:
                local = PurePosixPath(path).relative_to(directory)
            except ValueError:
                continue
            if local.as_posix() in ("Cargo.toml", "build.rs") or (len(local.parts) > 1 and
                    local.parts[0] in ("src", "tests", "benches", "examples")):
                selected.add(package_id)
                break
            if not path.endswith(".md"):
                return "full"
            break
        else:
            if not path.endswith(".md"):
                return "full"
    if not selected and "Cargo.lock" not in paths:
        return "docs"
    resolve = metadata.get("resolve")
    if resolve is None:
        raise ValueError("package selection requires cargo metadata's resolve graph")
    reverse = {node["id"]: set() for node in resolve["nodes"]}
    for node in resolve["nodes"]:
        for dependency in node["dependencies"]:
            reverse[dependency].add(node["id"])
    pending = list(selected)
    while pending:
        for dependent in reverse[pending.pop()] - selected:
            selected.add(dependent)
            pending.append(dependent)
    names = {packages[package_id]["name"] for package_id in selected if package_id in packages}
    available = {package["name"] for package in packages.values()}
    missing = set(always) - available
    if missing:
        raise ValueError(f"always.txt names missing workspace packages: {', '.join(sorted(missing))}")
    return names | set(always)


def config(repo: Path) -> tuple[list[str], list[str]]:
    """(always, read_by_tests) from always.txt and read-by-tests.txt in the first CONFIG_DIRS
    directory that exists in repo; blank lines and # comments dropped."""
    for directory in CONFIG_DIRS:
        root = repo / directory
        if root.is_dir():
            lists = []
            for name in ("always.txt", "read-by-tests.txt"):
                path = root / name
                lines = path.read_text().splitlines() if path.exists() else []
                lists.append([value for line in lines if (value := line.split("#", 1)[0].strip())])
            return lists[0], lists[1]
    return [], []


def changed_paths(repo: Path, candidate: str = "HEAD", base: str = "origin/main", *, sh: Runner = run) -> list[str]:
    """Paths differing between base and candidate, renames as both sides (`--no-renames`)."""
    output = sh(["git", "diff", "--name-only", "--no-renames", "-z", base, candidate, "--"],
                cwd=str(repo), check=True).out
    return output.split("\0")[:-1] if output else []


def metadata(repo: Path, *, sh: Runner = run) -> dict:
    """cargo metadata --no-deps (workspace_root, workspace_members) with the full run's packages
    and resolve graph merged in, both --locked."""
    workspace = json.loads(sh(["cargo", "metadata", "--no-deps", "--format-version", "1", "--locked"],
                              cwd=str(repo), check=True).out)
    resolved = json.loads(sh(["cargo", "metadata", "--format-version", "1", "--locked"],
                             cwd=str(repo), check=True).out)
    workspace["packages"] = resolved["packages"]
    workspace["resolve"] = resolved["resolve"]
    return workspace


def loader(load: Callable[[Path], dict] | None = None, *, sh: Runner = run) -> Callable[[Path], dict]:
    """Load metadata for one candidate on the first call, passing its repo to load (default
    metadata with sh); return the same dict on every later call."""
    cached = None

    def once(repo: Path) -> dict:
        nonlocal cached
        if cached is None:
            cached = metadata(repo, sh=sh) if load is None else load(repo)
        return cached

    return once


def shown(selected: str | set[str]) -> str | list[str]:
    """The selection for a record: full or docs unchanged, package names sorted."""
    return sorted(selected) if isinstance(selected, set) else selected


def step_texts(results: Sequence[StepResult]) -> list[str]:
    """The results for a record as name:code:seconds strings, seconds to three decimals."""
    return [f"{step.name}:{step.code}:{step.seconds:.3f}" for step in results]


def select(repo: Path, paths: Sequence[str], *, base: str = "origin/main", candidate: str = "HEAD",
           sh: Runner = run, load: Callable[[Path], dict] | None = None) -> str | set[str]:
    """The selection for a checked-out candidate: full_inputs is full without loading metadata;
    only Markdown outside src/tests/benches/examples and tools/ paths need no metadata; otherwise
    metadata (load, default `metadata`), lock_changes from the base's and candidate's Cargo.lock when
    it changed, and `selection` with this repo's config."""
    if full_inputs(paths):
        return "full"
    always, read_by_tests = config(repo)
    if all(path.startswith("tools/") or (path.endswith(".md") and not
           set(PurePosixPath(path).parts[:-1]) & {"src", "tests", "benches", "examples"})
           for path in paths):
        return selection(paths, {}, always=always, read_by_tests=read_by_tests)
    head, expected = sh(["git", "rev-parse", "HEAD", f"{candidate}^{{commit}}"],
                        cwd=str(repo), check=True).out.splitlines()
    if head != expected:
        raise ValueError("checked selection requires the candidate checkout")
    data = metadata(repo, sh=sh) if load is None else load(repo)
    locked = None
    if "Cargo.lock" in paths:
        before = sh(["git", "show", f"{base}:Cargo.lock"], cwd=str(repo), check=True).out
        after = sh(["git", "show", f"{candidate}:Cargo.lock"], cwd=str(repo), check=True).out
        locked = lock_changes(before, after, data)
    return selection(paths, data, always=always, read_by_tests=read_by_tests, locked=locked)


def ratchet_steps(repo: Path, paths: Sequence[str], *, write: bool) -> list[Step]:
    """One `ratchet:<tree>` step per tree the paths touch: `python3 -I -B <tree>/scripts/old_forms.py`,
    with --write when write, run in the tree's directory."""
    trees = {path.split("/", 1)[0] for path in paths} & set(TREES)
    return [Step(f"ratchet:{tree}", ("python3", "-I", "-B", str(repo / tree / "scripts/old_forms.py"),
                                   *(("--write",) if write else ())), str(repo / tree))
            for tree in sorted(trees)]


def check_steps(repo: Path, selected: str | set[str], paths: Sequence[str], meta: dict | None,
                *, lane: str) -> list[Step]:
    """The checks for a selection, as fabrig's mq check_commands: fmt (--all --check when full;
    otherwise --check scoped to the packages owning changed .rs files, when any), then, unless docs,
    clippy (--all-targets -- -D warnings), build (nextest run --no-run), default (nextest run
    --no-fail-fast) and fuzzy (the same with --profile fuzzy), each through heavy (`heavy --gate`
    when lane is "gate", plain `heavy` when "build"), scoped by --workspace or -p per package."""
    steps = []
    if selected == "full":
        steps.append(Step("fmt", ("cargo", "fmt", "--all", "--check"), str(repo)))
    elif selected != "docs":
        rust_paths = [PurePosixPath(path) for path in paths if path.endswith(".rs")]
        if rust_paths:
            if meta is None:
                raise ValueError("formatting changed Rust files requires package ownership metadata")
            owners = package_owners(meta)
            ids = set()
            for path in rust_paths:
                for directory, package_id in owners:
                    if path.is_relative_to(directory):
                        ids.add(package_id)
                        break
            names = sorted(package["name"] for package in meta["packages"] if package["id"] in ids)
            if names:
                scope = tuple(arg for name in names for arg in ("-p", name))
                steps.append(Step("fmt", ("cargo", "fmt", "--check", *scope), str(repo)))
    if selected and selected != "docs":
        scope = ("--workspace",) if selected == "full" else tuple(
            arg for name in sorted(selected) for arg in ("-p", name))
        heavy = ("heavy", "--gate") if lane == "gate" else ("heavy",)
        steps.extend([
            Step("clippy", (*heavy, "cargo", "clippy", *scope, "--all-targets", "--", "-D", "warnings"), str(repo)),
            Step("build", (*heavy, "cargo", "nextest", "run", *scope, "--no-run"), str(repo)),
            Step("default", (*heavy, "cargo", "nextest", "run", *scope, "--no-fail-fast"), str(repo)),
            Step("fuzzy", (*heavy, "cargo", "nextest", "run", *scope, "--no-fail-fast", "--profile", "fuzzy"), str(repo)),
        ])
    return steps


def run_steps(steps: Sequence[Step], log: Path, *, sh: Runner = run, timeout: float = STEP_TIMEOUT,
              clock: Callable[[], float] | None = None) -> list[StepResult]:
    """Run steps in order, appending each one's command line and output to log; stop after the first
    red. Green is exit 0, or NO_TESTS for build, default and fuzzy. clock defaults to time.monotonic."""
    clock = time.monotonic if clock is None else clock
    outcomes = []
    content = log.read_text() if log.exists() else ""
    for step in steps:
        content += f"\n[{step.name}] {shlex.join(step.argv)} (cwd {step.cwd})\n"
        started = clock()
        try:
            result = sh(step.argv, cwd=step.cwd, timeout=timeout)
        except OSError as error:
            code, output = 127, f"{error}\n"
        else:
            code, output = result.code, result.out + result.err
        seconds = clock() - started
        content += output
        atomic.write(log, content)
        green = code == 0 or (step.name in ("build", "default", "fuzzy") and code == NO_TESTS)
        outcomes.append(StepResult(step.name, step.argv, code, green, seconds))
        if not green:
            break
    return outcomes
