"""`fab land`: land a branch of this repository on main (docs/design/fab.md, 6)."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from fab.sh import Runner, run

# What fab land may land; anything else still goes through tools/land.
ALLOWED = ("fab/", "bin/fab", "docs/design/fab.md", "docs/design/fab.status.md", "docs/plan/")
REMOTE = "git@github.com:fabrig-ai/agents.git"
TEST = ("bin/fab", "test")


@dataclass(frozen=True)
class Outcome:
    landed: bool
    step: str  # "landed", or the step that refused: fetch, rebase, paths, test, push
    detail: str
    tip: str | None = None
    main: str | None = None


def outside(paths: Iterable[str]) -> list[str]:
    """The paths fab land may not land, sorted: an ALLOWED entry ending in / covers a directory, others match exactly."""
    raise NotImplementedError


def task_of(branch: str) -> str | None:
    """The task a branch serves: `<draft>/<task>` from `<draft>/<task>` or `<draft>/<task>-r<n>`; None otherwise."""
    raise NotImplementedError


def land(checkout: Path, branch: str, *, test: Sequence[str] = TEST, sh: Runner = run, tries: int = 3) -> Outcome:
    """Land origin/<branch> from checkout, a clone of the repository, and return what happened.

    fetch origin --prune; detach at origin/<branch>; rebase onto origin/main (a conflict
    aborts the rebase: step "rebase"); the changed paths against origin/main must all be
    allowed (step "paths", detail naming them); run `test` in checkout with a 120 s timeout
    (step "test", detail the output's last 20 lines); push HEAD to refs/heads/main, which
    origin accepts only as a fast-forward. A push refused because main moved starts again
    from the fetch, at most `tries` times in all (step "push"). Then delete the remote branch;
    a failed delete is noted in detail, not a refusal. The checkout is left detached and
    clean in every outcome. A landed Outcome carries the landed tip and main (the same sha).
    """
    raise NotImplementedError


def main(argv: list[str]) -> int:
    """`fab land BRANCH [--task ID] [--checkout PATH]`: one landing at a time, logged.

    The checkout defaults to FAB_HOME/repos/agents, cloned from REMOTE when missing. A flock
    on FAB_HOME/land-agents.lock serializes landings. The task defaults to task_of(BRANCH).
    Logs branch.landed (task, branch, tip, main) or branch.rejected (task, branch, tip, step,
    log: the detail); prints the outcome; exits 0 when landed, 1 when refused.
    """
    raise NotImplementedError
