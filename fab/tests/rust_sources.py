"""The vocabulary of the Rust gates' tests (docs/design/fab.md, 12): small Rust sources, crates
as trees on disk and in git, and assertions over what fab.rust and fab.rust_digest read.

test_rust.py and test_rust_digest.py speak in these; add a builder here rather than beside a
test.
"""

from __future__ import annotations

import textwrap
import unittest
from collections.abc import Mapping, Sequence
from pathlib import Path

from fab import atomic, gates, rust
from fab.calls import Signature
from fab.digest import Digest, Function
from fab.gates import Finding
from fab.plan import Task
from fab.tests.support import git, git_pair

CRATE = "skein/crates/wire"  # the crate most tests write
LIB = f"{CRATE}/src/lib.rs"
TASK = Task("draft/task", "part", "feature", "fabrig", (), (f"{CRATE}/**",), "high", 30,
            "Fill the wire crate.\n", "docs/plan/draft/tasks/task.md")
WORKSPACE = '[workspace]\nmembers = ["skein/crates/*"]\n'  # the root's Cargo.toml


def rs(text: str) -> str:
    """A Rust file's text from an indented triple-quoted string: dedented, the first newline
    dropped, ending with a newline."""
    return textwrap.dedent(text).lstrip("\n")


def long_fn(name: str, lines: int, *, doc: str = "Do the work.", indent: str = "") -> str:
    """`pub fn <name>() {` ... `}` of exactly lines lines (lines >= 2), each body line a
    distinct `let <name>_<i> = <i>;`, under a one-line `///` doc that is not counted."""
    body = "".join(f"{indent}    let {name}_{index} = {index};\n" for index in range(lines - 2))
    return f"{indent}/// {doc}\n{indent}pub fn {name}() {{\n{body}{indent}}}\n"


def block(tag: str, lines: int = 8, *, indent: str = "    ") -> str:
    """lines distinct statements `let <tag>_<i> = <i> * 2;` that fab.rust.masked keeps: the
    same tag written in two files is a clone of lines lines."""
    return "".join(f"{indent}let {tag}_{index} = {index} * 2;\n" for index in range(lines))


def line_of(text: str, needle: str) -> int:
    """The 1-based number of text's first line holding needle; ValueError when none does."""
    for number, line in enumerate(text.splitlines(), 1):
        if needle in line:
            return number
    raise ValueError(f"{needle!r} not in text")


def manifest(crate: str) -> str:
    """A crate's minimal Cargo.toml, named by its directory's last component."""
    return f'[package]\nname = "{crate.rsplit("/", 1)[-1]}"\nversion = "0.1.0"\nedition = "2021"\n'


def tree(root: Path, files: Mapping[str, str], crates: Sequence[str] = (CRATE,)) -> Path:
    """root holding files (repository-relative path to text) and each crate's Cargo.toml
    (manifest), written with fab.atomic.write; return root. No git."""
    for crate in crates:
        atomic.write(root / crate / "Cargo.toml", manifest(crate))
    for path, text in files.items():
        atomic.write(root / path, text)
    return root


def fabrig_repo(directory: Path, files: Mapping[str, str],
                crates: Sequence[str] = (CRATE,)) -> tuple[Path, Path, str]:
    """A fabrig-shaped repository from support.git_pair: the root's Cargo.toml (WORKSPACE), each
    crate's manifest and files, committed and pushed to main. Returns (origin, clone, main's
    sha)."""
    origin, clone = git_pair(directory)
    tree(clone, {"Cargo.toml": WORKSPACE, **files}, crates)
    git(clone, "add", "-A")
    git(clone, "commit", "-q", "-m", "Add crates")
    git(clone, "push", "-q", "origin", "HEAD:main")
    return origin, clone, git(clone, "rev-parse", "HEAD")


def commit_branch(clone: Path, branch: str, files: Mapping[str, str | None]) -> str:
    """Commit files on a new branch from the clone's HEAD (text written; None deleted) and push
    it to origin; return its tip's sha."""
    git(clone, "checkout", "-qb", branch)
    for path, text in files.items():
        if text is None:
            (clone / path).unlink()
        else:
            atomic.write(clone / path, text)
    git(clone, "add", "-A")
    git(clone, "commit", "-q", "-m", f"Change {branch}")
    git(clone, "push", "-q", "origin", "HEAD")
    return git(clone, "rev-parse", "HEAD")


def item(name: str, text: str, doc: str = "", module: str = LIB) -> Signature:
    """A public item as fab.rust.scan gives it."""
    return Signature(module, name, text, doc)


def function(name: str, start: int, lines: int, module: str = LIB) -> Function:
    """A function as fab.rust.scan gives it."""
    return Function(module, name, start, lines)


class RustTestCase(unittest.TestCase):
    """Assertions over fab.rust's scan of one file, at LIB unless named."""

    def assertItems(self, text: str, expected: Sequence[tuple[str, str, str]],
                    module: str = LIB) -> None:
        """scan's items as (name, text, doc), in order."""
        self.assertEqual([(entry.name, entry.text, entry.doc)
                          for entry in rust.scan(module, text).items], list(expected))

    def assertFunctions(self, text: str, expected: Sequence[tuple[str, int, int]],
                        module: str = LIB) -> None:
        """scan's functions as (name, start, lines), in order."""
        self.assertEqual([(entry.name, entry.start, entry.lines)
                          for entry in rust.scan(module, text).functions], list(expected))

    def assertTests(self, text: str, spans: Sequence[tuple[int, int]], module: str = LIB) -> None:
        """scan's test-only spans, in order."""
        self.assertEqual(list(rust.scan(module, text).tests), list(spans))

    def assertUnreadable(self, text: str, line: int, module: str = LIB) -> None:
        """scan raises the SyntaxError fab.gates.screen turns into a gate:parse finding."""
        with self.assertRaises(SyntaxError) as caught:
            rust.scan(module, text)
        self.assertEqual((caught.exception.filename, caught.exception.lineno), (module, line))

    def assertFindings(self, digest: Digest, expected: Sequence[tuple[str, str]],
                       banned: Sequence[str] = ()) -> None:
        """fab.gates.check's findings over digest as (gate, text), in order; banned defaults
        to none, so pass gates.banned_names(...) to check names."""
        self.assertEqual(gates.check(digest, banned),
                         [Finding(gate, text) for gate, text in expected])
