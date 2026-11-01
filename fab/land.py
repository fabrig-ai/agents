"""`fab land`: land a branch of this repository on main (docs/design/fab-landing.md, 2)."""

from __future__ import annotations

import argparse
import fcntl
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from fab import log, wake
from fab.sh import Runner, run

# What fab land never lands: the legacy kit, kept as reference, and the user's drafts.
FORBIDDEN = ("old/", "docs/design/draft/")
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
    """The paths fab land may not land, sorted: those under a FORBIDDEN directory."""
    return sorted(path for path in paths if path.startswith(FORBIDDEN))


def task_of(branch: str) -> str | None:
    """The task a branch serves: `<draft>/<task>` from `<draft>/<task>` or `<draft>/<task>-r<n>`; None otherwise."""
    match = re.fullmatch(r"([^/\s]+/[^/\s]+?)(?:-r[0-9]+)?", branch)
    return match.group(1) if match else None


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
    def git(*args: str):
        return sh(["git", *args], cwd=str(checkout))

    def detail(result) -> str:
        output = "\n".join(part.rstrip("\n") for part in (result.out, result.err) if part)
        return "\n".join(output.splitlines()[-20:])

    tip, main_tip = None, None
    try:
        if branch == "main" or not git("check-ref-format", "refs/heads/" + branch).ok:
            return Outcome(False, "fetch", f"Invalid landing branch: {branch}")
        for attempt in range(tries):
            fetched = git("fetch", "origin", "--prune")
            if not fetched.ok:
                return Outcome(False, "fetch", detail(fetched), tip, main_tip)
            source = git("rev-parse", "--verify", "refs/remotes/origin/" + branch + "^{commit}")
            target = git("rev-parse", "--verify", "refs/remotes/origin/main^{commit}")
            if not source.ok or not target.ok:
                return Outcome(False, "fetch", detail(source) + "\n" + detail(target), tip, main_tip)
            tip, main_tip = source.out.strip(), target.out.strip()
            detached = git("checkout", "--detach", "--force", tip)
            if not detached.ok:
                return Outcome(False, "rebase", detail(detached), tip, main_tip)
            git("clean", "-fdx")
            rebased = git("-c", "user.name=fab", "-c", "user.email=fab@localhost",
                          "rebase", main_tip)
            if not rebased.ok:
                git("rebase", "--abort")
                return Outcome(False, "rebase", detail(rebased), tip, main_tip)
            tip = git("rev-parse", "HEAD").out.strip()
            changed = git("diff", "--name-only", "--no-renames", "-z", main_tip, tip, "--")
            if not changed.ok:
                return Outcome(False, "paths", detail(changed), tip, main_tip)
            forbidden = outside(path for path in changed.out.split("\0") if path)
            if forbidden:
                return Outcome(False, "paths", "Paths fab land may not land:\n" + "\n".join(forbidden), tip, main_tip)
            try:
                tested = sh(test, cwd=str(checkout), timeout=120)
            except OSError as error:
                return Outcome(False, "test", str(error), tip, main_tip)
            if not tested.ok:
                return Outcome(False, "test", detail(tested), tip, main_tip)
            pushed = git("push", "--porcelain", "origin", "HEAD:refs/heads/main")
            if not pushed.ok:
                current = git("ls-remote", "--refs", "origin", "refs/heads/main")
                moved = current.ok and current.out.split() and current.out.split()[0] != main_tip
                if moved and attempt + 1 < tries:
                    continue
                return Outcome(False, "push", detail(pushed), tip, main_tip)
            deleted = git("push", "origin", "--delete", branch)
            message = "Already contained in main" if tip == main_tip else "Landed"
            message += "; branch deleted" if deleted.ok else "; branch delete failed:\n" + detail(deleted)
            return Outcome(True, "landed", message, tip, tip)
        return Outcome(False, "push", f"No landing attempts (tries={tries})", tip, main_tip)
    finally:
        # This is a dedicated landing clone; discard test output and detach even on refusal.
        git("checkout", "--detach", "--force", "HEAD")
        git("clean", "-fdx")


def main(argv: list[str]) -> int:
    """`fab land BRANCH [--task ID] [--checkout PATH]`: one landing at a time, logged.

    The checkout defaults to FAB_HOME/repos/agents, cloned from REMOTE when missing. A flock
    on FAB_HOME/land-agents.lock serializes landings. The task defaults to task_of(BRANCH).
    Logs branch.landed (task, branch, tip, main) or branch.rejected (task, branch, tip, step,
    log: the detail); wakes the tick with `land <task or -> <step>` after logging;
    prints the outcome; exits 0 when landed, 1 when refused.
    """
    parser = argparse.ArgumentParser(prog="fab land", description=__doc__)
    parser.add_argument("branch")
    parser.add_argument("--task")
    parser.add_argument("--checkout", type=Path)
    args = parser.parse_args(argv)
    home = log.home()
    home.mkdir(parents=True, exist_ok=True)
    checkout = args.checkout or home / "repos" / "agents"
    task = args.task if args.task is not None else task_of(args.branch)
    with open(home / "land-agents.lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not checkout.exists():
            checkout.parent.mkdir(parents=True, exist_ok=True)
            cloned = run(["git", "clone", REMOTE, str(checkout)])
            if cloned.ok:
                outcome = land(checkout, args.branch)
            else:
                outcome = Outcome(False, "fetch", "\n".join((cloned.out + cloned.err).strip().splitlines()[-20:]))
        else:
            outcome = land(checkout, args.branch)
        fields = dict(task=task, branch=args.branch, tip=outcome.tip)
        if outcome.landed:
            log.append("branch.landed", **fields, main=outcome.main)
        else:
            log.append("branch.rejected", **fields, step=outcome.step, log=outcome.detail)
        wake.want(f"land {task if task is not None else '-'} {outcome.step}")
        print(f"{args.branch}: {outcome.step}: {outcome.detail}")
        return 0 if outcome.landed else 1
