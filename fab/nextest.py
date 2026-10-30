"""What fab reads and writes of nextest: its JUnit, exact filters, a config overlay
(docs/design/fab.md, 11).

Pure functions over text and files; nothing here runs nextest.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# The alphabet an exact filter accepts unquoted; any other identity is refused, never escaped.
SAFE = re.compile(r"[A-Za-z0-9_:.-]+")
ERROR_LINE = 500  # characters kept of a failure's first line


@dataclass(frozen=True)
class Case:
    profile: str
    binary: str  # nextest's binary id: the JUnit testsuite's name
    test: str  # the JUnit testcase's name
    result: str  # "pass", "fail" or "skipped"
    error: str  # the failure's first non-blank line, at most ERROR_LINE characters; "" otherwise

    @property
    def key(self) -> str:
        """The identity as one string, for the history's keys:
        `json.dumps([profile, binary, test], separators=(",", ":"))`."""
        raise NotImplementedError


def junit(path: Path, profile: str) -> list[Case]:
    """The cases of a nextest JUnit report, in file order. The root must be `testsuites`; each
    `testsuite`'s name is the binary id and each `testcase`'s name the test. A case with a
    `failure` or `error` child failed (error: the first non-blank line of that child's text,
    else its `message` attribute); with a `skipped` child it was skipped; otherwise it passed.
    ValueError when the file is missing or does not parse, the root is wrong, a name is
    missing, an identity repeats, or the root's `tests` attribute (when present) differs from
    the cases counted."""
    raise NotImplementedError


def exact_filter(binary: str, test: str) -> str:
    """`binary_id(=<binary>) & test(=<test>)`; ValueError when either does not fully match SAFE."""
    raise NotImplementedError


def union(filters: list[str]) -> str:
    """Filters joined as one expression: each in parentheses, joined by ` | `; one filter
    alone is returned as it is. ValueError for none."""
    raise NotImplementedError


def overlay(config: str, profile: str, junit_path: Path) -> str:
    """The repository's nextest config (the text of `.config/nextest.toml`) with the profile's
    JUnit report written to junit_path, as TOML text to pass with `--config-file`.

    Parse config with tomllib; set `profile.<profile>.junit` to {path: str(junit_path),
    store-success-output: false, store-failure-output: true}, replacing any junit table the
    profile had; write every top-level key as `<json key> = <value>`, one per line, values as
    inline TOML (tables `{k = v, ...}` with JSON-quoted keys, arrays `[a, b]`, strings
    JSON-quoted with ensure_ascii False, booleans, integers and finite floats), so nested
    overrides survive. ValueError for an unknown profile, a value of another type (a datetime)
    or a non-finite float. The result parses back with tomllib to the same data plus the junit
    table."""
    raise NotImplementedError
