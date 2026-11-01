"""Commit a cut's inputs without committing in its checkout (docs/design/integration.md, 3)."""

from __future__ import annotations

import argparse
import fcntl
import shutil
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from fab import channel, designer, land, log
from fab.sh import Failed, Runner, run


def _checkout(plan_dir: Path, sh: Runner) -> tuple[Path, str, str, bool]:
    ancestor = plan_dir
    while not ancestor.exists():
        ancestor = ancestor.parent
    if not ancestor.is_dir():
        raise ValueError(f"not a plan directory: {plan_dir}")
    checkout = Path(sh(["git", "rev-parse", "--show-toplevel"],
                       cwd=str(ancestor), check=True).out.strip()).resolve()
    plan_dir.relative_to(checkout)
    repo = designer.repository(checkout, sh=sh)
    detached = not sh(["git", "symbolic-ref", "-q", "HEAD"], cwd=str(checkout)).ok
    upstream = ""
    if not detached:
        upstream = sh(["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"],
                      cwd=str(checkout)).out.strip()
    trunk = f"{plan_dir.name}/integration"
    allowed = repo == "agents" and upstream == "origin/main"
    allowed |= repo == "fabrig" and (detached or upstream in ("origin/main", f"origin/{trunk}"))
    if not allowed:
        raise ValueError(f"{repo} checkout must track origin/main" +
                         (f" or origin/{trunk}, or be detached" if repo == "fabrig" else ""))
    return checkout, repo, trunk if upstream == f"origin/{trunk}" else "main", detached


def _sources(plan_dir: Path, files: Sequence[Path | str]) -> list[Path]:
    if plan_dir.name == "inputs":
        raise ValueError("draft must not be named inputs")
    if (plan_dir / "plan.toml").exists():
        raise ValueError(f"plan.toml already exists in {plan_dir}")
    if plan_dir in channel.plan_dirs():
        raise ValueError(f"plan directory is already listed: {plan_dir}")
    sources = [Path(file).absolute() for file in files]
    if not sources:
        raise ValueError("at least one input is required")
    names = set()
    for source in sources:
        if not source.is_file() and not source.is_dir():
            raise ValueError(f"input does not exist or is not a file or directory: {source}")
        if source.name in names:
            raise ValueError(f"inputs share a name: {source.name}")
        names.add(source.name)
    return sources


def _check_paths(checkout: Path, paths: list[str], trunk: str, replace: bool, sh: Runner) -> None:
    for path in paths:
        if not replace and sh(["git", "cat-file", "-e", f"origin/{trunk}:{path}"],
                              cwd=str(checkout)).ok:
            raise ValueError(f"input already exists at origin/{trunk}: {path}; use --replace")
        status = sh(["git", "status", "--porcelain", "--", path], cwd=str(checkout), check=True)
        if status.out.strip():
            raise ValueError(f"input is untracked or changed in checkout: {path}")


def _check_branch(checkout: Path, branch: str, replace: bool, sh: Runner) -> None:
    if not sh(["git", "check-ref-format", f"refs/heads/{branch}"], cwd=str(checkout)).ok:
        raise ValueError(f"invalid inputs branch: {branch}")
    found = sh(["git", "ls-remote", "--exit-code", "origin", f"refs/heads/{branch}"],
               cwd=str(checkout))
    if found.ok and not (replace and branch.startswith("ready/inputs/")):
        raise ValueError(f"branch already exists on origin: {branch}")
    if found.code not in (0, 2):
        raise Failed(["git", "ls-remote", "--exit-code", "origin", f"refs/heads/{branch}"], found)


def _copy(source: Path, destination: Path, replace: bool) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if replace and (destination.exists() or destination.is_symlink()):
        if destination.is_dir() and not destination.is_symlink():
            shutil.rmtree(destination)
        else:
            destination.unlink()
    if source.is_dir():
        shutil.copytree(source, destination)
        return
    with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=f".{destination.name}.",
                                     delete=False) as sibling:
        copied = Path(sibling.name)
    try:
        shutil.copy2(source, copied)
        copied.replace(destination)
    finally:
        copied.unlink(missing_ok=True)


def _publish(checkout: Path, sources: list[Path], paths: list[str], trunk: str,
             draft: str, branch: str, replace: bool, sh: Runner) -> None:
    with tempfile.TemporaryDirectory(prefix="fab-inputs-") as directory:
        worktree = Path(directory) / "tree"
        sh(["git", "worktree", "add", "--detach", str(worktree), f"origin/{trunk}"],
           cwd=str(checkout), check=True)
        try:
            for source, path in zip(sources, paths):
                _copy(source, worktree / path, replace)
            sh(["git", "add", "--", *paths], cwd=str(worktree), check=True)
            sh(["git", "-c", "user.name=fab", "-c", "user.email=fab@localhost",
                "commit", "-m", f"{draft}: inputs"], cwd=str(worktree), check=True)
            force = ["--force"] if replace and branch.startswith("ready/inputs/") else []
            sh(["git", "push", *force, "origin", f"HEAD:refs/heads/{branch}"],
               cwd=str(worktree), check=True)
        finally:
            sh(["git", "worktree", "remove", "--force", str(worktree)],
               cwd=str(checkout), check=True)


def _land(checkout: Path, branch: str, sh: Runner, log_path: Path | None) -> None:
    if land.main([branch]) == 0:
        return
    sh(["git", "push", "origin", "--delete", branch], cwd=str(checkout), check=True)
    rejected = next((event for event in reversed(log.read(log_path))
                     if event.get("ev") == "branch.rejected" and event.get("branch") == branch), {})
    raise ValueError(f"fab land {branch} refused at {rejected.get('step', 'unknown')}")


def _follow(checkout: Path, sh: Runner) -> None:
    home = log.home()
    home.mkdir(parents=True, exist_ok=True)
    with open(home / "tick.lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        sh(["git", "fetch", "origin"], cwd=str(checkout), check=True)
        sh(["git", "merge", "--ff-only", "@{upstream}"], cwd=str(checkout), check=True)


def add(plan_dir: Path, files: Sequence[Path | str], *, replace: bool = False,
        sh: Runner = run, log_path: Path | None = None) -> list[str]:
    """Validate and commit files or whole directories to PLAN_DIR/inputs in a detached worktree.

    Return repository paths for cut --source. Push an integration trunk, land an agents
    inputs branch, or publish a fabrig ready ref and print its waiting conditions. Follow
    a pushed trunk or landed main under the tick lock. Refusals raise ValueError before
    committing; a landing refusal deletes its inputs branch and names the logged step.
    The caller's checkout receives no local commit and the temporary worktree is removed.
    """
    plan_dir = Path(plan_dir).resolve()
    sources = _sources(plan_dir, files)
    checkout, repo, trunk, detached = _checkout(plan_dir, sh)
    paths = [(plan_dir.relative_to(checkout) / "inputs" / source.name).as_posix() for source in sources]
    branch = trunk if trunk != "main" else f"inputs/{plan_dir.name}"
    if repo == "fabrig" and trunk == "main":
        branch = f"ready/{branch}"
    if trunk == "main":
        _check_branch(checkout, branch, replace, sh)
    sh(["git", "fetch", "origin"], cwd=str(checkout), check=True)
    _check_paths(checkout, paths, trunk, replace, sh)
    _publish(checkout, sources, paths, trunk, plan_dir.name, branch, replace, sh)
    if repo == "agents":
        _land(checkout, branch, sh, log_path)
    if trunk != "main" or repo == "agents":
        _follow(checkout, sh)
    else:
        print(f"cut waits for {branch}'s queue.landed and for the checkout to hold the files")
        if detached:
            print("checkout is detached; the operator must move it to the landed files")
    return paths


def main(argv: list[str]) -> int:
    """Run fab plan inputs PLAN_DIR FILE... [--replace]; print paths, or a refusal and exit 1."""
    parser = argparse.ArgumentParser(prog="fab plan", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    inputs = commands.add_parser("inputs")
    inputs.add_argument("plan_dir", type=Path)
    inputs.add_argument("files", nargs="+", type=Path)
    inputs.add_argument("--replace", action="store_true")
    args = parser.parse_args(argv)
    try:
        paths = add(args.plan_dir, args.files, replace=args.replace, sh=run)
    except (ValueError, OSError, Failed) as error:
        print(f"fab plan: {error}", file=sys.stderr)
        return 1
    print("\n".join(paths))
    return 0
