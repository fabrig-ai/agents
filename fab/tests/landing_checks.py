"""The vocabulary of the landing checks' tests (docs/design/fab.md, 13.8): receipts as
fab.precheck writes them, nextest's JUnit, and a fake nextest that writes it.

test_receipts.py, test_reds.py and the queue's receipt and classing tests speak in these; add a
builder here rather than beside a test.
"""

from __future__ import annotations

import json
import tomllib
import unittest
import xml.etree.ElementTree as ET
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from fab import atomic, nextest, tiers
from fab.sh import Result

TIP = "1" * 40
MAIN = "2" * 40
STEPS = ("fmt", "clippy", "build", "default", "fuzzy")  # a full receipt's steps, in order


def receipt(tip: str = TIP, main: str = MAIN, *, outcome: str = "green",
            selection: str | Sequence[str] = ("pkg",), steps: Sequence[str] = STEPS) -> dict:
    """A receipt as fab.precheck writes it: each step `name:0:1.000`, the last `name:101:1.000`
    when outcome is red; a docs selection runs no steps."""
    shown = selection if isinstance(selection, str) else sorted(selection)
    names = () if shown == "docs" else steps
    texts = [f"{name}:0:1.000" for name in names]
    if outcome == "red" and texts:
        texts[-1] = f"{names[-1]}:101:1.000"
    return {"tip": tip, "main": main, "selection": shown, "steps": texts, "outcome": outcome,
            "log": f"/fab/precheck/{tip}.log", "at": "2026-10-31T00:00:00.000Z"}


def receipt_text(value: dict) -> str:
    """The receipt's file text, as fab.precheck writes it."""
    return json.dumps(value, indent=2) + "\n"


def kept(home: Path, value: dict) -> Path:
    """value kept where the queue reads it, home/receipts/<tip>.json; return that path."""
    path = home / "receipts" / f"{value['tip']}.json"
    atomic.write(path, receipt_text(value))
    return path


def junit_xml(cases: Sequence[tuple[str, str, str]]) -> str:
    """nextest JUnit for (binary, test, result) cases, result pass, fail or skipped, one
    testsuite per binary in first-seen order, the root counting the cases."""
    root = ET.Element("testsuites", tests=str(len(cases)))
    suites = {}
    for binary, test, result in cases:
        if binary not in suites:
            suites[binary] = ET.SubElement(root, "testsuite", name=binary)
        case = ET.SubElement(suites[binary], "testcase", name=test)
        if result == "fail":
            ET.SubElement(case, "failure").text = "assertion failed\nleft: 1, right: 2"
        elif result == "skipped":
            ET.SubElement(case, "skipped")
    return ET.tostring(root, encoding="unicode")


def alone(binary: str, test: str) -> str:
    """The -E expression a retry of one test passes."""
    return nextest.exact_filter(binary, test)


@dataclass
class FakeNextest:
    """A runner for argvs holding `nextest run` (behind heavy too): it writes the JUnit its
    --config-file names for its --profile (default without one) from results[<its -E
    expression, None without one>] and exits 0, or fab.tiers.TEST_FAILED when a case failed.
    A key missing from results, or a None entry, writes no JUnit and exits codes.get(key, 0).
    Other argvs go to fallback, else succeed with no output. calls holds each nextest argv."""

    results: Mapping[str | None, Sequence[tuple[str, str, str]] | None]
    codes: Mapping[str | None, int] = field(default_factory=dict)
    fallback: Callable[..., Result] | None = None
    calls: list[list[str]] = field(default_factory=list)

    def __call__(self, argv: Sequence[str], **kwargs) -> Result:
        argv = list(argv)
        if not any(argv[i:i + 2] == ["nextest", "run"] for i in range(len(argv))):
            return self.fallback(argv, **kwargs) if self.fallback else Result(0)
        self.calls.append(argv)

        def option(flag):
            return argv[argv.index(flag) + 1] if flag in argv else None

        key = option("-E")
        cases = self.results.get(key)
        if cases is None:
            return Result(self.codes.get(key, 0))
        config = option("--config-file")
        profile = option("--profile") or "default"
        if config is not None:
            data = tomllib.loads(Path(config).read_text())
            atomic.write(Path(data["profile"][profile]["junit"]["path"]), junit_xml(cases))
        failed = any(result == "fail" for _, _, result in cases)
        return Result(self.codes.get(key, tiers.TEST_FAILED if failed else 0))


class ChecksTestCase(unittest.TestCase):
    def assertCollateral(self, verdict, *tests):
        """verdict classes the red collateral, its failed tests being tests."""
        self.assertEqual((verdict.collateral, verdict.reason, verdict.tests), (True, "", tests))

    def assertStands(self, verdict, reason, *tests):
        """verdict lets the red stand for reason, its failed tests being tests."""
        self.assertEqual((verdict.collateral, verdict.reason, verdict.tests),
                         (False, reason, tests))
