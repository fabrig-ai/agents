"""A task spec changed on a branch of the plan's repository, for the tick to land (calls.md 2).

The foreman's answers (fab.foreman) and its repair and rebase sections (fab.repairs) are
written into task specs the same way: a worktree of the plan's checkout at origin/<trunk>, the
spec edited there, one commit pushed to a branch that the tick lands with `fab land`.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from fab import atomic
from fab.plan import Task
from fab.sh import Runner, run


def commit(task: Task, checkout: Path, edit: Callable[[str], str], *, branch: str,
           message: str, worktree: Path, sh: Runner = run, trunk: str = "main") -> str | None:
    """Commit edit(<the task's spec on origin/<trunk>>) on branch and push it; return branch,
    or None when edit leaves the spec unchanged (origin/<trunk> records the change already).

    checkout is the plan's repository on this machine (a clone with origin; the tick's plan
    checkout); worktree a path under FAB_HOME that does not exist yet. The spec's path is
    Path(task.path).resolve() relative to checkout.resolve(); a spec outside the checkout is
    a ValueError before any command. Each git command with check=True:
    1. `git fetch origin` in checkout;
    2. `git worktree add -B <branch> <worktree> origin/<trunk>` in checkout (-B: an earlier
       attempt's branch is reset);
    3. the spec at that path, read in the worktree; new = edit(spec); equal to the spec
       means None, with nothing committed or pushed;
    4. otherwise new written there through fab.atomic.write, then in the worktree
       `git -c user.name=fab -c user.email=fab@localhost commit -q -m <message> -- <spec
       path>` and `git push -q --force origin HEAD:refs/heads/<branch>`.
    In every outcome, last: `git worktree remove --force <worktree>` and `git branch -D
    <branch>` in checkout, errors ignored. The pushed branch stays for fab.land.main.

    fab.foreman.commit is this with with_answer as edit; its steps and argvs are unchanged."""
    relative = Path(task.path).resolve().relative_to(checkout.resolve())
    return commit_path(str(relative), checkout, edit, branch=branch, message=message,
                       worktree=worktree, sh=sh, trunk=trunk)


def commit_path(path: str, checkout: Path, edit: Callable[[str], str], *, branch: str,
                message: str, worktree: Path, sh: Runner = run, trunk: str = "main") -> str | None:
    """Commit and push an edited repository path, or return None when unchanged.

    Use commit's worktree, command order and cleanup (docs/design/fab.md, 13.15).
    Read a missing file as empty text and stage it with `git add -- <path>` before
    committing. Refuse absolute paths and paths outside checkout before commands.
    """
    if Path(path).is_absolute():
        raise ValueError("path must be relative to checkout")
    relative = (checkout / path).resolve().relative_to(checkout.resolve())

    def git(*argv, cwd=checkout):
        return sh(["git", *argv], cwd=str(cwd), check=True)

    try:
        git("fetch", "origin")
        git("worktree", "add", "-B", branch, str(worktree), f"origin/{trunk}")
        path = worktree / relative
        try:
            spec = path.read_text()
            missing = False
        except FileNotFoundError:
            spec, missing = "", True
        new = edit(spec)
        if new == spec:
            return None
        atomic.write(path, new)
        if missing:
            git("add", "--", str(relative), cwd=worktree)
        git("-c", "user.name=fab", "-c", "user.email=fab@localhost", "commit", "-q", "-m",
            message, "--", str(relative), cwd=worktree)
        git("push", "-q", "--force", "origin", f"HEAD:refs/heads/{branch}", cwd=worktree)
        return branch
    finally:
        for argv in (("worktree", "remove", "--force", str(worktree)), ("branch", "-D", branch)):
            try:
                git(*argv)
            except Exception:
                pass
