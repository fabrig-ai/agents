"""The vocabulary of the events tests (docs/design/fab-tick.md, 6): machines with a dispatcher,
the records a round gains, and assertions on the want file and the log's notes.

test_wake.py, the wakers' tests (codex, calls, land, channel, queue) and the tick's event
tests speak in these; add a builder here rather than beside a test.
"""

from __future__ import annotations

import os
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import patch

from fab import hosts as machines, log, wake
from fab.tests.support import tmp_home

HOSTS = machines.parse("""
[hub]
ssh = "fab@hub.invalid"
hostname = "hub-machine"
roles = ["dispatcher"]

[box]
ssh = "fab@box.invalid"
hostname = "box-machine"
roles = ["builder"]
places = 2

[gate]
ssh = "fab@gate.invalid"
hostname = "gate-machine"
roles = ["gate"]
""")
DISPATCHER, BUILDER, GATE = "hub", "box", "gate"


def ended(run: str, *, outcome: str = "done") -> dict:
    """A run.ended record of run (`<draft>/<task>-<n>`), as a collect logs it."""
    return log.record("run.ended", run=run, task=run.rsplit("-", 1)[0], outcome=outcome,
                      report=f"runs/{run}/report.md", minutes=1.0)


def imported(ev: str, task: str, *, tip: str = "tip") -> dict:
    """A branch.landed or branch.rejected record the tick imported from the queue's record:
    it carries queue_ts."""
    return log.record(ev, task=task, branch=task, tip=tip, queue_ts="2026-10-31T00:00:00.000Z")


def landed(task: str) -> dict:
    """A branch.landed record fab land wrote: no queue_ts."""
    return log.record("branch.landed", task=task, branch=task, tip="tip", main="main")


def started(run: str, *, host: str = BUILDER) -> dict:
    """A run.started record of run: wants nothing and is no lost event."""
    return log.record("run.started", run=run, task=run.rsplit("-", 1)[0], kind="implement",
                      host=host, dir="/slots/1", branch=run.rsplit("-", 1)[0], base="base")


@contextmanager
def here(name: str | None) -> Iterator[None]:
    """FAB_HOST set to name, or removed when None, for the block."""
    with patch.dict(os.environ):
        if name is None:
            os.environ.pop("FAB_HOST", None)
        else:
            os.environ["FAB_HOST"] = name
        yield


class WakeTestCase(unittest.TestCase):
    """A temporary HOME and FAB_HOME: self.log_path is the log there and self.want the want
    file beside it, where a wake on the dispatcher writes."""

    def setUp(self) -> None:
        self.home = self.enterContext(tmp_home())
        self.log_path = log.default_path()
        self.want = wake.want_path(self.log_path)

    def wants(self) -> list[str] | None:
        """The want file's lines, without taking it; None when there is none."""
        if not self.want.exists():
            return None
        return self.want.read_text(encoding="utf-8").splitlines()

    def assertWanted(self, *reasons: str) -> None:
        """The want file exists and holds exactly reasons, one per line, in order."""
        self.assertEqual(self.wants(), list(reasons))

    def assertNoWant(self) -> None:
        """No want file: nothing woke the tick, or a tick took it."""
        self.assertIsNone(self.wants())

    def notes(self) -> list[str]:
        """The text of every note in the log, in order."""
        return [record["text"] for record in log.read(self.log_path) if record["ev"] == "note"]

    def unit(self, files: dict[str, str], name: str) -> dict[str, dict[str, str]]:
        """One unit file of wake.units parsed as {section: {key: value}}; a key given twice
        keeps the last value. Fails the test when the text does not end with a newline."""
        text = files[name]
        self.assertTrue(text.endswith("\n"), name)
        sections: dict[str, dict[str, str]] = {}
        current = None
        for line in text.splitlines():
            if line.startswith("[") and line.endswith("]"):
                current = sections.setdefault(line[1:-1], {})
            elif line.strip():
                key, _, value = line.partition("=")
                self.assertIsNotNone(current, line)
                current[key] = value
        return sections
