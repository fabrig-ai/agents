"""Test helpers: a fake runner, a temporary home and a git fixture (docs/design/fab.md, 8)."""

from __future__ import annotations

import atexit
import os
import shutil
import subprocess
import tempfile
import unittest
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from fab import acceptance
from fab.plan import Part, Plan, Slice, Task
from fab.sh import Failed, Result

PENDING = "FAB_PENDING"  # comma-separated subjects whose pending tests run (docs/design/fab.md, 13.1)
START = "2026-10-31T00:00:00.000Z"  # the ts of a History's first record

GIT_ENV = {
    "GIT_AUTHOR_NAME": "fab", "GIT_AUTHOR_EMAIL": "fab@example.invalid",
    "GIT_COMMITTER_NAME": "fab", "GIT_COMMITTER_EMAIL": "fab@example.invalid",
    "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
}


@dataclass
class Call:
    argv: list[str]
    cwd: str | None = None
    input: str | None = None


@dataclass
class FakeRunner:
    """Records each argv and answers from rules: the first rule whose prefix matches wins.

    A rule's answer is a Result, or a function of the Call returning one.
    Unmatched commands succeed with no output.
    """

    rules: list[tuple[list[str], Result | Callable[[Call], Result]]] = field(default_factory=list)
    calls: list[Call] = field(default_factory=list)

    def on(self, prefix: Sequence[str], answer: Result | Callable[[Call], Result]) -> FakeRunner:
        self.rules.append((list(prefix), answer))
        return self

    def __call__(self, argv: Sequence[str], *, cwd: str | None = None, input: str | None = None,
                 env: Mapping[str, str] | None = None, timeout: float | None = None,
                 check: bool = False) -> Result:
        call = Call(list(argv), None if cwd is None else str(cwd), input)
        self.calls.append(call)
        result = Result(0)
        for prefix, answer in self.rules:
            if call.argv[:len(prefix)] == prefix:
                result = answer(call) if callable(answer) else answer
                break
        if check and not result.ok:
            raise Failed(call.argv, result)
        return result

    def argvs(self) -> list[list[str]]:
        return [call.argv for call in self.calls]


@contextmanager
def tmp_home() -> Iterator[Path]:
    """A temporary directory as HOME, with FAB_HOME inside it; both restored after."""
    saved = {key: os.environ.get(key) for key in ("HOME", "FAB_HOME")}
    with tempfile.TemporaryDirectory(prefix="fab-test-") as directory:
        home = Path(directory)
        os.environ["HOME"] = str(home)
        os.environ["FAB_HOME"] = str(home / "fab")
        try:
            yield home
        finally:
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


def git(cwd: Path | str, *args: str) -> str:
    """Real git with a fixed identity and no user configuration; returns stdout."""
    done = subprocess.run(["git", *args], cwd=cwd, env={**os.environ, **GIT_ENV},
                          capture_output=True, text=True)
    if done.returncode:
        raise RuntimeError(f"git {' '.join(args)}: {done.stderr.strip()}")
    return done.stdout.strip()


_TEMPLATE: Path | None = None


def _template() -> Path:
    """An origin (bare) and a clone with one commit on main, built once per process."""
    global _TEMPLATE
    if _TEMPLATE is None:
        root = Path(tempfile.mkdtemp(prefix="fab-git-template-"))
        atexit.register(shutil.rmtree, root, True)
        git(root, "init", "-q", "--bare", "-b", "main", "origin.git")
        git(root, "clone", "-q", "origin.git", "clone")
        clone = root / "clone"
        (clone / "README.md").write_text("fixture\n")
        git(clone, "add", "README.md")
        git(clone, "commit", "-q", "-m", "Start")
        git(clone, "push", "-q", "origin", "HEAD:main")
        _TEMPLATE = root
    return _TEMPLATE


def git_pair(directory: Path) -> tuple[Path, Path]:
    """Copy the template into directory: (origin.git, clone), the clone's origin pointing at the copy."""
    template = _template()
    origin, clone = directory / "origin.git", directory / "clone"
    shutil.copytree(template / "origin.git", origin, symlinks=True)
    shutil.copytree(template / "clone", clone, symlinks=True)
    git(clone, "remote", "set-url", "origin", str(origin))
    return origin, clone


def pending(subject: str):
    """Mark an acceptance test class, or one test, pending on subject (fab.acceptance's
    `<draft>/<part>` or `<draft>/slice-<n>`): skipped with the reason `pending: <subject>`
    unless FAB_PENDING, read when the decorator runs, lists subject. The accept run deletes
    the decorator's line; until then main stays green."""
    listed = os.environ.get(PENDING, "").split(",")
    return unittest.skipUnless(subject in listed, f"pending: {subject}")


def build_part(identifier: str, *, needs: Sequence[str] = (), mode: str = "feature",
               done: bool = False) -> Part:
    """A part titled `Part <id>` whose design cites `docs/design/fab.md, 13.1`."""
    return Part(identifier, f"Part {identifier}", mode, tuple(needs), "docs/design/fab.md, 13.1",
                done)


def build_plan(*parts: Part, slices: Sequence[tuple[int, Sequence[str]]] = (),
               draft: str = "draft", repo: str = "agents") -> Plan:
    """A plan of parts in order; each slice given as (number, its parts), story `Story <n>`,
    not walked."""
    return Plan(draft, repo, (), 1.0, 2.0, {part.id: part for part in parts},
                tuple(Slice(number, f"Story {number}", tuple(names), False)
                      for number, names in slices))


def build_task(name: str, *, part: str, draft: str = "draft", needs: Sequence[str] = (),
               files: Sequence[str] = (), kind: str = "feature", repo: str = "agents") -> Task:
    """A spec task `<draft>/<name>` at `docs/plan/<draft>/tasks/<name>.md`; needs are short
    names of the same draft."""
    return Task(f"{draft}/{name}", part, kind, repo, tuple(f"{draft}/{need}" for need in needs),
                tuple(files), "high", 25, f"# {name}\n", f"docs/plan/{draft}/tasks/{name}.md")


@dataclass
class History:
    """A log written by a test, in order: each record's ts one second after the last, from START."""

    events: list[dict] = field(default_factory=list)
    reports: dict[str, str] = field(default_factory=dict)  # run id -> its report's text

    def add(self, ev: str, **fields) -> dict:
        """Append and return the record `{"ts", "ev", **fields}`."""
        moment = datetime.fromisoformat(START) + timedelta(seconds=len(self.events))
        record = {"ts": moment.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z", "ev": ev, **fields}
        self.events.append(record)
        return record

    def run(self, task: str, *, kind: str = "implement", outcome: str | None = None,
            branch: str | None = None, report: str | None = None) -> str:
        """A run of task: run.started (run `<task>-<n>`, n counting this history's starts of
        task; host "builder"; branch, default the run id for fab.acceptance's kinds and the
        task otherwise) and, given an outcome, its run.ended; report, when given, is kept as
        the run's report text. Return the run id."""
        count = sum(event["ev"] == "run.started" and event.get("task") == task
                    for event in self.events)
        run_id = f"{task}-{count + 1}"
        if branch is None:
            branch = run_id if kind in acceptance.KINDS else task
        self.add("run.started", run=run_id, task=task, kind=kind, host="builder",
                 branch=branch, base="origin/main")
        if report is not None:
            self.reports[run_id] = report
        if outcome is not None:
            self.end(run_id, outcome)
        return run_id

    def report(self, run_id: str) -> str:
        """A run's report text as given to run, "" for none: fab.acceptance's report reader."""
        return self.reports.get(run_id, "")

    def end(self, run_id: str, outcome: str = "done") -> dict:
        """run.ended of a run this history started, report `runs/<run>/report.md`."""
        started = next(event for event in reversed(self.events)
                       if event["ev"] == "run.started" and event["run"] == run_id)
        return self.add("run.ended", run=run_id, task=started["task"], outcome=outcome,
                        report=f"runs/{run_id}/report.md", minutes=1.0)

    def landed(self, task: str) -> dict:
        """branch.landed of task, its branch that of its last run.started (else the task)."""
        started = next((event for event in reversed(self.events)
                        if event["ev"] == "run.started" and event.get("task") == task), {})
        return self.add("branch.landed", task=task, branch=started.get("branch", task),
                        tip="tip", main="main")

    def landed_all(self, *tasks: str) -> None:
        """Each task run to done and landed, in order."""
        for task in tasks:
            self.run(task, outcome="done")
            self.landed(task)
