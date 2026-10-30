"""fabrig's merge queue (docs/design/fab.md, 6). Runs on the gate machine.

Ready refs `ready/<draft>/<task>` are taken oldest first, merged on main as one batch, checked
in the gate lane, and pushed to main; a red batch is bisected. State is re-derived from git
on every cycle, except the tips already tried, kept in FAB_HOME/queue-state.json. Every
outcome is recorded in FAB_HOME/queue.jsonl, which the dispatcher reads.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from fab import atomic, gate, log, slots
from fab.sh import Runner, run


@dataclass(frozen=True)
class Branch:
    name: str  # "<draft>/<task>": the ready ref without its "ready/" prefix
    tip: str
    timestamp: int  # committer time of the tip


def candidates(repo: Path, tried: dict[str, str], *, sh: Runner = run) -> list[Branch]:
    """refs/remotes/origin/ready/<draft>/<task> after a fetch, oldest committer time first (then
    name); a branch whose tip equals tried[name] is left out."""
    output = sh(["git", "for-each-ref",
                 "--format=%(refname) %(objectname) %(committerdate:unix)",
                 "refs/remotes/origin/ready/"], cwd=str(repo), check=True).out
    branches = []
    prefix = "refs/remotes/origin/ready/"
    for line in output.splitlines():
        ref, tip, timestamp = line.split()
        if not ref.startswith(prefix):
            continue
        name = ref.removeprefix(prefix)
        if len(name.split("/")) == 2 and tried.get(name) != tip:
            branches.append(Branch(name, tip, int(timestamp)))
    return sorted(branches, key=lambda branch: (branch.timestamp, branch.name))


def build_batch(repo: Path, branches: Sequence[Branch], base: str = "origin/main", *,
                sh: Runner = run) -> tuple[list[Branch], list[tuple[Branch, str]]]:
    """Detach at base and merge each tip (--no-ff, message `Merge <name>`); return (merged,
    conflicts with their output). A conflict confined to `<tree>/scripts/old-forms.txt` files is
    resolved as fabrig's mq merge_ratchets does (keep ours, recount with old_forms.py --write; a
    raised count is a conflict). A tip already contained in the batch is neither."""
    def git(*args, check=True):
        return sh(["git", *args], cwd=str(repo), check=check)

    if git("status", "--porcelain").out:
        raise RuntimeError("queue checkout has uncommitted or untracked files")
    git("switch", "--detach", base)
    merged, conflicts = [], []
    ratchets = {f"{tree}/scripts/old-forms.txt" for tree in gate.TREES}
    before = git("rev-parse", "HEAD").out.strip()
    for branch in branches:
        result = git("merge", "--no-ff", "-m", f"Merge {branch.name}", branch.tip, check=False)
        if not result.ok:
            paths = git("diff", "--name-only", "--diff-filter=U", "-z").out.split("\0")[:-1]
            if paths and set(paths) <= ratchets:
                git("checkout", "--ours", "--", *paths)
                git("add", "--", *paths)
                git("commit", "--no-edit")
                failure = None
                try:
                    for tree in sorted({path.split("/", 1)[0] for path in paths}):
                        counted = sh(["python3", "-I", "-B",
                                      str(repo / tree / "scripts/old_forms.py"), "--write"],
                                     cwd=str(repo / tree))
                        if counted.code == 1:
                            failure = counted.out + counted.err
                            break
                        if not counted.ok:
                            raise RuntimeError(f"ratchet:{tree} exited {counted.code}: "
                                               f"{counted.out}{counted.err}")
                    if failure is None:
                        git("add", "--", *paths)
                        git("commit", "--amend", "--no-edit")
                except Exception:
                    git("reset", "--hard", before)
                    raise
                if failure is not None:
                    git("reset", "--hard", before)
                    conflicts.append((branch, failure))
                    continue
            else:
                if git("rev-parse", "--verify", "--quiet", "MERGE_HEAD", check=False).ok:
                    git("merge", "--abort")
                if not paths:
                    raise RuntimeError(f"merge of {branch.name} failed: {result.out}{result.err}")
                conflicts.append((branch, result.out + result.err))
                continue
        after = git("rev-parse", "HEAD").out.strip()
        if after != before:
            merged.append(branch)
        before = after
    return merged, conflicts


def bisect(branches: Sequence[Branch], check: Callable[[list[Branch]], bool]) -> tuple[list[Branch], list[Branch]]:
    """(green, red): check the whole; if red and more than one, each half in order, recursively.
    check lands what it passes, so later halves are checked on top of earlier green ones."""
    group = list(branches)
    if not group:
        return [], []
    if check(group):
        return group, []
    if len(group) == 1:
        return [], group
    middle = len(group) // 2
    left_green, left_red = bisect(group[:middle], check)
    right_green, right_red = bisect(group[middle:], check)
    return left_green + right_green, left_red + right_red


class Queue:
    def __init__(self, repo: Path, *, batch: int = 8, full_every: int = 5, home: Path | None = None,
                 sh: Runner = run, load: Callable[[Path], dict] | None = None):
        """repo: the queue's own clone; home: FAB_HOME; load: the metadata loader (fab.gate.metadata)."""
        if batch < 1 or full_every < 1:
            raise ValueError("batch and full_every must be positive")
        self.repo = Path(repo).resolve()
        self.home = Path(home) if home is not None else log.home()
        self.batch, self.full_every = batch, full_every
        self.sh, self.load = sh, load
        self.state_path = self.home / "queue-state.json"
        self.log_path = self.home / "queue.jsonl"
        self.state = json.loads(self.state_path.read_text()) if self.state_path.exists() else {}
        self.state.setdefault("tried", {})
        self.state.setdefault("batches_since_full", 0)
        self.last_merged = []
        self._force_full = False
        self._error_recorded = False

    def _git(self, *args, check=True):
        return self.sh(["git", *args], cwd=str(self.repo), check=check)

    def _save(self) -> None:
        atomic.write(self.state_path, json.dumps(self.state) + "\n")

    def _reject(self, branch: Branch, step: str, detail: Path) -> None:
        self.state["tried"][branch.name] = branch.tip
        log.append("rejected", path=self.log_path, branch=branch.name, tip=branch.tip,
                   step=step, log=str(detail))

    def _retire(self, branches: Sequence[Branch], main: str) -> str | None:
        if not branches:
            return
        # Without --atomic, an updated head does not prevent retiring the other pinned refs.
        refs = [("refs/heads/" + prefix + branch.name, branch.tip)
                for branch in branches for prefix in ("ready/", "")]
        result = self._git("push", *(f"--force-with-lease={ref}:{tip}" for ref, tip in refs),
                           "origin", *(":" + ref for ref, _ in refs), check=False)
        for branch in branches:
            if result.ok:
                self.state["tried"][branch.name] = branch.tip
            log.append("landed", path=self.log_path, branch=branch.name, tip=branch.tip, main=main)
        return None if result.ok else f"cleanup: {result.out}{result.err}"

    def attempt(self, branches: Sequence[Branch]) -> bool:
        """Check branches as one batch on origin/main and land it when green; return green.

        Conflicts are rejected (step "merge"). If nothing merged, the branches are marked tried
        and the attempt is green. Otherwise: selection (full on every full_every-th batch), the
        ratchet steps with --write and a commit of lowered baselines, the gate-lane checks, the
        detail log FAB_HOME/queue/<batch>.log. Green: push the candidate to main with
        --force-with-lease=refs/heads/main:<parent> (refused: an error, nothing marked), delete
        each branch's ready/<name> and <name> refs with leases on their tips, record `landed` per
        branch. Red: a single branch is rejected with its failing step and marked tried.
        Records: `batch` (branches, parent, selection, steps as "name:code:seconds", outcome
        green, red, conflict or error, log), `landed` (branch, tip, main), `rejected` (branch,
        tip, step, log). The checkout is left clean and detached.

        Whatever the outcome, the attempt ends by bounding the gate's target as a slot's is
        (docs/design/fab.md, 7): fab.slots.remove(fab.slots.sweep_plan(repo / "target",
        <the attempt's start in ns>)), the bytes freed going into the batch record as freed."""
        started_ns = time.time_ns()
        started = log.now()
        batch_id = datetime.strptime(started, "%Y-%m-%dT%H:%M:%S.%fZ").strftime("%Y%m%dT%H%M%SZ")
        detail = self.home / "queue" / (batch_id + ".log")
        # Bisection can start several attempts in one second; retain all their output.
        if not detail.exists():
            atomic.write(detail, "")
        record = {"branches": [branch.name for branch in branches], "parent": "",
                  "selection": None, "steps": [], "outcome": "error", "log": str(detail)}
        tried_before = dict(self.state["tried"])
        prepared = False
        clean = False
        self.last_merged = []
        try:
            if self._git("status", "--porcelain").out:
                raise RuntimeError("queue checkout has uncommitted or untracked files")
            prepared = True
            green = self._merge_and_record(branches, detail, record)
            clean = green
            return green
        except Exception as error:
            self.state["tried"] = tried_before
            record.update(outcome="error", error=str(error))
            atomic.extend(detail, f"\n{error}\n")
            self._error_recorded = True
            raise
        finally:
            try:
                if prepared and not clean:
                    self._git("reset", "--hard", "origin/main")
                    self._git("clean", "-fd")
            finally:
                try:
                    record["freed"] = slots.remove(slots.sweep_plan(self.repo / "target", started_ns))
                except Exception as error:
                    record["sweep_error"] = str(error)
                log.append("batch", path=self.log_path, ts=started, **record)

    def _merge_and_record(self, branches, detail, record):
        parent = self._git("rev-parse", "origin/main").out.strip()
        record["parent"] = parent
        merged, conflicts = build_batch(self.repo, branches, parent, sh=self.sh)
        self.last_merged = merged
        if conflicts:
            atomic.extend(detail, "\n".join(output for _, output in conflicts) + "\n")
        conflicted = {branch for branch, _ in conflicts}
        reachable = [branch for branch in branches if branch not in conflicted and branch not in merged]
        green = True
        outcomes = []
        if merged:
            green, outcomes = self._check_batch(parent, detail, record)
        cleanup_error = None
        if green:
            main = self._git("rev-parse", "origin/main").out.strip()
            cleanup_error = self._retire([*merged, *reachable], main)
        elif len(merged) == 1:
            failed = next(step.name for step in outcomes if not step.green)
            self._reject(merged[0], failed, detail)
        for branch, _ in conflicts:
            self._reject(branch, "merge", detail)
        record["outcome"] = ("conflict" if conflicts else "green") if green else "red"
        if cleanup_error:
            record.update(outcome="error", error=cleanup_error)
            atomic.extend(detail, f"\n{cleanup_error}\n")
        self._save()
        return green

    def _check_batch(self, parent, detail, record):
        paths = gate.changed_paths(self.repo, base=parent, sh=self.sh)
        meta = None

        def load(repo):
            nonlocal meta
            if meta is None:
                meta = gate.metadata(repo, sh=self.sh) if self.load is None else self.load(repo)
            return meta

        selected = "full" if self._force_full or self.state["batches_since_full"] + 1 >= self.full_every else \
            gate.select(self.repo, paths, base=parent, sh=self.sh, load=load)
        record["selection"] = sorted(selected) if isinstance(selected, set) else selected
        outcomes = gate.run_steps(gate.ratchet_steps(self.repo, paths, write=True), detail, sh=self.sh)
        green = all(step.green for step in outcomes)
        if green:
            baselines = [f"{tree}/scripts/old-forms.txt" for tree in gate.TREES]
            changed = self._git("diff", "--name-only", "-z", "--", *baselines).out.split("\0")[:-1]
            if changed:
                self._git("add", "--", *changed)
                self._git("commit", "-m", "Lower old-form baselines")
            if self._git("status", "--porcelain").out:
                raise RuntimeError("ratchet left changes outside its baselines")
            if isinstance(selected, set) and any(path.endswith(".rs") for path in paths):
                load(self.repo)
            outcomes += gate.run_steps(gate.check_steps(self.repo, selected, paths, meta, lane="gate"),
                                       detail, sh=self.sh)
            green = all(step.green for step in outcomes)
        record["steps"] = [f"{step.name}:{step.code}:{step.seconds:.3f}" for step in outcomes]
        self.state["batches_since_full"] = 0 if selected == "full" else self.state["batches_since_full"] + 1
        if not green and selected == "full":
            self._force_full = True
        if green:
            if self._git("status", "--porcelain").out:
                raise RuntimeError("checks left uncommitted or untracked files")
            candidate = self._git("rev-parse", "HEAD").out.strip()
            self._git("push", f"--force-with-lease=refs/heads/main:{parent}",
                      "origin", f"{candidate}:refs/heads/main")
            # Advance the local base before checking the next bisection half.
            self._git("update-ref", "refs/remotes/origin/main", candidate)
        return green, outcomes

    def cycle(self) -> bool:
        """Consume queue-untry requests (forget, save, remove, record), then fetch --prune.
        Take up to `batch` candidates and attempt them, bisecting when red;
        return whether there was anything to do."""
        self._error_recorded = False
        self._force_full = False
        requests = self.home / "queue-untry"
        for request in sorted(requests.iterdir()) if requests.exists() else ():
            if request.name.startswith(".") or not request.is_file():
                continue
            branch = request.name.replace("%2F", "/")
            tip = self.state["tried"].pop(branch, None)
            self._save()
            request.unlink()
            log.append("untried", path=self.log_path, branch=branch, tip=tip)
        self._git("fetch", "--prune", "origin")
        branches = candidates(self.repo, self.state["tried"], sh=self.sh)[:self.batch]
        if not branches:
            return False
        initial_green = self.attempt(branches)
        merged = self.last_merged
        first = True

        def check(group):
            nonlocal first
            if first:
                first = False
                return initial_green
            return self.attempt(group)

        bisect(merged, check)
        return True

    def run(self, *, stop: Path, idle: float = 30.0, sleep: Callable[[float], None] | None = None) -> None:
        """Cycle until the file `stop` exists, sleeping `idle` seconds after a cycle with nothing to do.
        An error in a cycle is recorded (`batch` with outcome error) and the loop sleeps and goes on."""
        sleep = time.sleep if sleep is None else sleep
        while not stop.exists():
            self._error_recorded = False
            try:
                worked = self.cycle()
            except Exception as error:
                if not self._error_recorded:
                    log.append("batch", path=self.log_path, branches=[], outcome="error", error=str(error))
                sleep(idle)
            else:
                if not worked:
                    sleep(idle)


def main(argv: list[str]) -> int:
    """`fab queue run|once [--repo PATH] [--batch N]` (repo default FAB_HOME/repos/fabrig; run stops
    at FAB_HOME/queue.stop), `fab queue plan` (the next batch's names, no checks),
    `fab queue log [--since TS]` (queue.jsonl records at or after TS, one per line),
    `fab queue untry BRANCH` (ask the running queue to forget its tried tip next cycle)."""
    parser = argparse.ArgumentParser(prog="fab queue")
    parser.add_argument("command", choices=("run", "once", "plan", "log", "untry"))
    parser.add_argument("branch", nargs="?")
    parser.add_argument("--repo", type=Path, default=log.home() / "repos/fabrig")
    parser.add_argument("--batch", type=int, default=8)
    parser.add_argument("--since")
    args = parser.parse_args(argv)
    if (args.command == "untry") != (args.branch is not None):
        parser.error("untry requires BRANCH; other commands take no branch")
    if args.command == "untry" and (not args.branch or args.branch.startswith(".")):
        parser.error("untry requires a branch name")
    if args.batch < 1:
        parser.error("--batch must be positive")
    if args.command == "log":
        for entry in log.iterate(log.home() / "queue.jsonl"):
            if args.since is None or entry["ts"] >= args.since:
                print(json.dumps(entry, ensure_ascii=False))
        return 0
    try:
        if args.command == "untry":
            path = log.home() / "queue-untry" / args.branch.replace("/", "%2F")
            atomic.write(path, "")
            return 0
        queue = Queue(args.repo, batch=args.batch)
        if args.command == "plan":
            queue._git("fetch", "--prune", "origin")
            for branch in candidates(queue.repo, queue.state["tried"], sh=queue.sh)[:queue.batch]:
                print(branch.name)
        elif args.command == "once":
            queue.cycle()
        else:
            queue.run(stop=queue.home / "queue.stop")
    except (OSError, RuntimeError, ValueError) as error:
        print(f"fab queue: {error}", file=sys.stderr)
        return 1
    return 0
