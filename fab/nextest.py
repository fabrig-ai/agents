"""What fab reads and writes of nextest: its JUnit, exact filters, a config overlay
(docs/design/after-landing.md, 2).

Pure functions over text and files; nothing here runs nextest.
"""

from __future__ import annotations

import json
import math
import re
import tomllib
import xml.etree.ElementTree as ET
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
    result: str  # "pass", "fail", "starved" or "skipped"
    error: str  # the failure's first non-blank line, at most ERROR_LINE characters; "" otherwise

    @property
    def key(self) -> str:
        """The identity as one string, for the history's keys:
        `json.dumps([profile, binary, test], separators=(",", ":"))`."""
        return json.dumps([self.profile, self.binary, self.test], separators=(",", ":"))


def junit(path: Path, profile: str) -> list[Case]:
    """The cases of a nextest JUnit report, in file order. The root must be `testsuites`; each
    `testsuite`'s name is the binary id and each `testcase`'s name the test. A case with a
    `failure` or `error` child failed (error: the first non-blank line of that child's text,
    else its `message` attribute), except a timeout type is starved; with a `skipped`
    child it was skipped; otherwise it passed.
    ValueError when the file is missing or does not parse, the root is wrong, a name is
    missing, an identity repeats, or the root's `tests` attribute (when present) differs from
    the cases counted."""
    try:
        root = ET.parse(path).getroot()
        if root.tag != "testsuites":
            raise ValueError("expected nextest testsuites")
        cases = []
        identities = set()
        for suite in root.findall("testsuite"):
            binary = suite.attrib["name"]
            for element in suite.findall("testcase"):
                name = element.attrib["name"]
                failure = element.find("failure")
                if failure is None:
                    failure = element.find("error")
                error = ""
                if failure is not None:
                    first = failure.text or failure.get("message", "")
                    error = next((line[:ERROR_LINE] for line in first.splitlines()
                                  if line.strip()), "")
                    result = "starved" if "timeout" in failure.get("type", "").lower() else "fail"
                elif element.find("skipped") is not None:
                    result = "skipped"
                else:
                    result = "pass"
                case = Case(profile, binary, name, result, error)
                if case.key in identities:
                    raise ValueError("duplicate test identity")
                identities.add(case.key)
                cases.append(case)
        declared = root.get("tests")
        if declared is not None and int(declared) != len(cases):
            raise ValueError("incomplete JUnit counts")
        return cases
    except (OSError, ET.ParseError, KeyError, ValueError) as error:
        raise ValueError(f"invalid/missing nextest JUnit: {error}") from error


def exact_filter(binary: str, test: str) -> str:
    """`binary_id(=<binary>) & test(=<test>)`; ValueError when either does not fully match SAFE."""
    if any(SAFE.fullmatch(identity) is None for identity in (binary, test)):
        raise ValueError("identity not expressible as an exact filter")
    return f"binary_id(={binary}) & test(={test})"


def union(filters: list[str]) -> str:
    """Filters joined as one expression: each in parentheses, joined by ` | `; one filter
    alone is returned as it is. ValueError for none."""
    if not filters:
        raise ValueError("no filters")
    if len(filters) == 1:
        return filters[0]
    return " | ".join(f"({expression})" for expression in filters)


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
    data = tomllib.loads(config)
    profiles = data.get("profile", {})
    if profile not in profiles:
        raise ValueError(f"unknown nextest profile: {profile}")
    profiles[profile]["junit"] = {
        "path": str(junit_path),
        "store-success-output": False,
        "store-failure-output": True,
    }

    def value(item):
        if isinstance(item, dict):
            return "{" + ", ".join(json.dumps(key, ensure_ascii=False) + " = " + value(child)
                                   for key, child in item.items()) + "}"
        if isinstance(item, list):
            return "[" + ", ".join(value(child) for child in item) + "]"
        if isinstance(item, (str, bool, int)):
            return json.dumps(item, ensure_ascii=False)
        if isinstance(item, float) and math.isfinite(item):
            return repr(item)
        raise ValueError("unsupported nextest configuration value")

    return "".join(json.dumps(key, ensure_ascii=False) + " = " + value(item) + "\n"
                   for key, item in data.items())
