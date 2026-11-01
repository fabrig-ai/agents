"""Create a plan's integration trunk (docs/design/integration.md, 3)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from fab import log
from fab.sh import Failed, Runner, run


def make(plan_path: str | Path, *, base: str = "origin/main", sh: Runner = run,
         log_path: Path | None = None) -> Path:
    """Fetch, refuse an occupied plan or trunk, then create and publish its worktree.

    Remove the worktree and local branch on push failure. Log trunk.made only
    after publication and return the plan directory inside the new worktree.
    """
    clone = log.home() / "repos" / "fabrig"
    sh(["git", "fetch", "--prune", "origin"], cwd=str(clone), check=True)
    plan_path = Path(plan_path)
    if (plan_path.is_absolute() or ".." in plan_path.parts or
            len(plan_path.parts) < 3 or plan_path.parts[-3:-1] != ("docs", "plan")):
        raise ValueError(f"PLAN_PATH must be a relative <prefix>docs/plan/<draft>: {plan_path}")
    draft = plan_path.name
    branch = f"{draft}/integration"
    worktree = log.home() / "integration" / draft
    plan_file = f"{base}:{plan_path.as_posix()}/plan.toml"
    if sh(["git", "cat-file", "-e", plan_file], cwd=str(clone)).ok:
        raise ValueError(f"plan.toml already exists at {plan_file}")
    for ref in (f"refs/remotes/origin/{branch}", f"refs/heads/{branch}"):
        if sh(["git", "show-ref", "--verify", "--quiet", ref], cwd=str(clone)).ok:
            raise ValueError(f"branch already exists: {ref}")
    if worktree.exists() or worktree.is_symlink():
        raise ValueError(f"worktree path already exists: {worktree}")
    sh(["git", "worktree", "add", "-b", branch, str(worktree), base], cwd=str(clone), check=True)
    try:
        sh(["git", "push", "-u", f"--force-with-lease=refs/heads/{branch}:", "origin", branch],
           cwd=str(worktree), check=True)
    except (Failed, OSError):
        sh(["git", "worktree", "remove", "--force", str(worktree)], cwd=str(clone), check=True)
        sh(["git", "branch", "-D", branch], cwd=str(clone), check=True)
        raise
    tip = sh(["git", "rev-parse", "HEAD"], cwd=str(worktree), check=True).out.strip()
    log.append("trunk.made", path=log_path, draft=draft, base=base, tip=tip)
    return worktree / plan_path


def main(argv: list[str]) -> int:
    """Parse fab trunk make, print its plan directory, and report refusals as exit 1."""
    parser = argparse.ArgumentParser(prog="fab trunk", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("make")
    command.add_argument("plan_path", metavar="PLAN_PATH", type=Path)
    command.add_argument("--base", default="origin/main", metavar="REV")
    args = parser.parse_args(argv)
    try:
        print(make(args.plan_path, base=args.base))
    except (ValueError, OSError, Failed) as error:
        print(f"fab trunk: {error}", file=sys.stderr)
        return 1
    return 0
