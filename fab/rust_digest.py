"""The structure digest of a fabrig branch: fab.digest's Digest, read from Rust
(docs/design/fab.md, 12).

The same digest the Python gates check, built from the crates the branch touches: a crate is
a directory holding a Cargo.toml (the repository root's aside), and its production sources are
the `.rs` files under its `src/` that classify calls production. Items come from fab.rust's
scan of both trees and are compared by fab.digest.compare; long functions are
fab.digest.long_functions with fab.rust.functions; clones are fab.digest.clones over the
touched crates' sources at tip, masked by fab.rust.masked. Only touched crates are archived,
so a branch of a large workspace extracts only the crates it changed.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from fab.calls import Signature
from fab.digest import Change, Digest
from fab.plan import Task
from fab.sh import Runner, run

MANIFEST = "Cargo.toml"
SOURCES = "src"  # a crate's production sources sit under <crate>/src/
TEST_DIRS = ("tests", "benches")  # a path with one of these as a directory is tests
TEST_FILES = ("tests.rs",)  # file names that are tests wherever they stand


def classify(path: str) -> str:
    """fab.digest.KINDS for a fabrig path. "tests": a directory component in TEST_DIRS, a file
    name in TEST_FILES, starting `test_`, or ending `_test.rs` or `_tests.rs`. "docs": ending
    `.md`, or a directory component `docs`. "production" otherwise (Cargo.toml, build.rs,
    examples and scripts among them). Tests win over docs. Pure."""
    raise NotImplementedError


def crates(repo: Path, rev: str, *, sh: Runner = run) -> list[str]:
    """The crate roots at rev, sorted: `git ls-tree -r -z --name-only <rev>` in repo
    (check=True), the parent directory of every path whose file name is MANIFEST, the root's
    own Cargo.toml left out. A git failure raises fab.sh.Failed."""
    raise NotImplementedError


def owner(path: str, roots: Sequence[str]) -> str | None:
    """The crate a production source belongs to: the longest root of roots such that path
    starts with `<root>/<SOURCES>/` and ends `.rs`; None when there is none (a test, a
    build.rs, an example, a path outside every crate). Pure."""
    raise NotImplementedError


def sources(root: Path, roots: Sequence[str]) -> list[str]:
    """The production sources of the crates roots under root (an extracted tree): every
    `<crate>/src/**/*.rs` file that exists, classify production and owned by that crate (not a
    nested one), as repository-relative posix paths, sorted. A crate missing from root has
    none."""
    raise NotImplementedError


def inventory(root: Path, roots: Sequence[str]) -> list[Signature]:
    """The public items of the crates roots under root: fab.rust.items(path, its UTF-8 text)
    for each of sources(root, roots), in that order. A SyntaxError propagates."""
    raise NotImplementedError


def build(task: Task, run_id: str, branch: str, base_sha: str, tip_sha: str,
          changes: Sequence[Change], base: Path, tip: Path, roots: Sequence[str]) -> Digest:
    """The digest of a fabrig branch from its changes (kinds from classify), its two trees
    (each holding the touched crates that exist at its side) and roots, the touched crates.

    The sources a branch changed are its production changes that owner places in roots, new
    files and existing ones alike. In order: changes sorted by path;
    fab.digest.outside(their paths, task.files); added, removed and changed from
    fab.digest.compare(inventory(base, roots), inventory(tip, roots)); modules: the changed
    sources with no such file under base, sorted; long: for every changed source that exists
    under tip, new or grown, fab.digest.long_functions(path, its text under base or "" when
    absent, its text under tip, find=fab.rust.functions), so an existing file's function grown
    past the cap is listed; clones: fab.digest.clones over every path of sources(tip, roots),
    each text fab.rust.masked(text, fab.rust.scan(path, text).tests), with the added lines
    (fab.digest.added_lines of its base and tip text) of every changed source that exists
    under tip. Files are read as UTF-8. A SyntaxError propagates. Digest's fields are filled
    as fab.digest.build fills them, kind task.kind; long sorted by module and start."""
    raise NotImplementedError


def gather(repo: Path, task: Task, run_id: str, branch: str, base: str, tip: str,
           directory: Path, *, sh: Runner = run) -> Digest:
    """fabrig's digest of a branch, as fab.gates.GATHER calls it under the gating lock.

    In order: fab.digest.changes(repo, base, tip), each change's kind replaced by
    classify(path); crates(repo, base) and crates(repo, tip); roots, the touched crates:
    owner(path, base crates) and owner(path, tip crates) of every changed path, None left out,
    sorted and unique; directory/"base" by fab.digest.archive(repo, base, ..., paths=the roots
    among the base crates), or created empty when there are none; directory/"tip" the same
    for tip; then build(task, run_id, branch, base, tip, changes, base tree, tip tree, roots).
    A git failure raises fab.sh.Failed; a SyntaxError propagates."""
    raise NotImplementedError

