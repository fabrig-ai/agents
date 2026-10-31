"""A task spec changed on a branch of the plan's repository, for the tick to land (13.1).

The foreman's answers (fab.foreman) and its repair and rebase sections (fab.repairs) are
written into task specs the same way: a worktree of the plan's checkout at origin/main, the
spec edited there, one commit pushed to a branch that the tick lands with `fab land`.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from fab.plan import Task
from fab.sh import Runner, run


def commit(task: Task, checkout: Path, edit: Callable[[str], str], *, branch: str,
           message: str, worktree: Path, sh: Runner = run) -> str | None:
    """Commit edit(<the task's spec on origin/main>) on branch and push it; return branch,
    or None when edit leaves the spec unchanged (origin/main records the change already).

    checkout is the plan's repository on this machine (a clone with origin; the tick's plan
    checkout); worktree a path under FAB_HOME that does not exist yet. The spec's path is
    Path(task.path).resolve() relative to checkout.resolve(); a spec outside the checkout is
    a ValueError before any command. Each git command with check=True:
    1. `git fetch origin` in checkout;
    2. `git worktree add -B <branch> <worktree> origin/main` in checkout (-B: an earlier
       attempt's branch is reset);
    3. the spec at that path, read in the worktree; new = edit(spec); equal to the spec
       means None, with nothing committed or pushed;
    4. otherwise new written there through fab.atomic.write, then in the worktree
       `git -c user.name=fab -c user.email=fab@localhost commit -q -m <message> -- <spec
       path>` and `git push -q --force origin HEAD:refs/heads/<branch>`.
    In every outcome, last: `git worktree remove --force <worktree>` and `git branch -D
    <branch>` in checkout, errors ignored. The pushed branch stays for fab.land.main.

    fab.foreman.commit is this with with_answer as edit; its steps and argvs are unchanged."""
    raise NotImplementedError
