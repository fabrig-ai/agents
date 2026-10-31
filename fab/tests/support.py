"""Test helpers: a fake runner, a temporary home and a git fixture (docs/design/fab.md, 8)."""

from __future__ import annotations

import atexit
import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from fab import atomic
from fab.sh import Failed, Result

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


# Several plans in one tick (docs/design/fab.md, 13.4): plans on disk and the log's records.

def write_plan(directory: Path, draft: str, parts: Mapping[str, Sequence[str]] | None = None, *,
               contracts: Sequence[str] = (), tasks: Sequence[str] = (), repo: str = "agents") -> Path:
    """A sound queue plan with reviews and non-direct parts at directory: plan.toml
    with parts (id to needs; default one part `core`), each a feature part designed by `design.md`, those in contracts marked
    contract, and one slice holding them all; then one spec `tasks/<name>.md` per name of
    tasks, of the first part, needing nothing. Written through fab.atomic.write; returns
    directory."""
    parts = {"core": ()} if parts is None else parts
    lines = [f'draft = "{draft}"', f'repo = "{repo}"',
             'landing = "queue"', 'reviews = true', 'direct = false']
    for identifier, needs in parts.items():
        lines += ["[[part]]", f'id = "{identifier}"', f'title = "{identifier.title()}"',
                  'mode = "feature"', f"needs = {list(needs)!r}", 'design = "design.md"',
                  f"contract = {str(identifier in contracts).lower()}"]
    lines += ["[[slice]]", "id = 1", 'story = "It runs"', f"parts = {list(parts)!r}", "walk = false"]
    atomic.write(directory / "plan.toml", "\n".join(lines) + "\n")
    first = next(iter(parts))
    for name in tasks:
        atomic.write(directory / "tasks" / f"{name}.md",
                     f'+++\nid = "{name}"\npart = "{first}"\nkind = "feature"\nneeds = []\n+++\n')
    return directory


def run_started(task: str, n: int = 1, *, kind: str = "implement", host: str = "builder",
                **fields) -> dict:
    """A run.started record: task a full task id (`<draft>/<name>`), a foreman's
    `<draft>/<name>/foreman`, or a root call's id for a review run; run `<task>-<n>`."""
    return {"ev": "run.started", "task": task, "run": f"{task}-{n}", "kind": kind,
            "host": host, **fields}


def run_ended(task: str, n: int = 1, outcome: str = "done", **fields) -> dict:
    """The run.ended record of run_started(task, n)."""
    return {"ev": "run.ended", "task": task, "run": f"{task}-{n}", "outcome": outcome,
            "report": "report.md", **fields}


def call_started(call: str, role: str, subject: str, **fields) -> dict:
    """A call.started record of call (its id) on branch `calls/<call>`."""
    return {"ev": "call.started", "call": call, "role": role, "subject": subject,
            "branch": f"calls/{call}", **fields}


def call_ended(call: str, outcome: str = "done", **fields) -> dict:
    """The call.ended record of call."""
    return {"ev": "call.ended", "call": call, "outcome": outcome, **fields}


def units(fake: FakeRunner) -> list[str]:
    """The unit names of the `systemd-run ... --unit NAME ...` commands fake ran, in order."""
    return [call.argv[call.argv.index("--unit") + 1] for call in fake.calls
            if call.argv[:1] == ["systemd-run"] and "--unit" in call.argv]
