"""fabrig's merge queue (docs/design/fab.md, 6). Runs on the gate machine.

Ready refs `ready/<draft>/<task>` are taken oldest first, merged on main as one batch, checked
in the gate lane, and pushed to main; a red batch is bisected. State is re-derived from git
on every cycle, except the tips already tried and the collateral reds each tip has had, kept in
FAB_HOME/queue-state.json. Every outcome is recorded in FAB_HOME/queue.jsonl, which the
dispatcher reads. A batch of one may land on its precheck receipt (fab.receipts), and a red is
classed before anyone hears it (fab.reds; docs/design/fab.md, 13.8).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from fab import atomic, gate, heavy, hosts as machines, log, queue_cpu, receipts, reds, slots, units, wake as events
from fab.sh import Runner, run

UNIT = "fab-queue.service"  # the queue's user unit on the gate machine
DRAIN = "1h"  # how long a stop waits for the cycle in progress before interrupting it


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
                 sh: Runner = run, load: Callable[[Path], dict] | None = None,
                 wake: Callable[[str], object] | None = None):
        """repo: the queue's own clone; home: FAB_HOME; load: the metadata loader (fab.gate.metadata).
        wake: when set, cycle wakes the tick once for its landed and rejected records."""
        if batch < 1 or full_every < 1:
            raise ValueError("batch and full_every must be positive")
        self.repo = Path(repo).resolve()
        self.home = Path(home) if home is not None else log.home()
        self.batch, self.full_every = batch, full_every
        self.sh, self.load = sh, load
        self.wake = wake
        self._wake_notes: list[str] = []
        self.state_path = self.home / "queue-state.json"
        self.log_path = self.home / "queue.jsonl"
        self.state = json.loads(self.state_path.read_text()) if self.state_path.exists() else {}
        self.state.setdefault("tried", {})
        self.state.setdefault("collateral", {})
        self.state.setdefault("batches_since_full", 0)
        self.last_merged = []
        self.last_outcome = None
        self._force_full = False
        self._error_recorded = False

    def _git(self, *args, check=True):
        return self.sh(["git", *args], cwd=str(self.repo), check=check)

    def _save(self) -> None:
        atomic.write(self.state_path, json.dumps(self.state) + "\n")

    def _reject(self, branch: Branch, step: str, detail: Path) -> None:
        """Record a rejection with up to 20 failures from the test step's derived JUnit,
        or [] when unreadable or not a test step; note it for the cycle's wake."""
        tests = reds.failed_tests(detail.with_suffix("") / step / "gate-junit.xml", step)
        self.state["tried"][branch.name] = branch.tip
        self.state["collateral"].pop(branch.name, None)
        log.append("rejected", path=self.log_path, branch=branch.name, tip=branch.tip,
                   step=step, tests=tests, log=str(detail))
        self._wake_notes.append(f"rejected {branch.name}")

    def _retire(self, branches: Sequence[Branch], main: str, detail: Path) -> str | None:
        """Retire pinned refs, recording each landing and noting it for the cycle's wake.

        Each ready/<name> is deleted with a lease on its tip, and <name> too when the fetched
        refs/remotes/origin/<name> is that tip: a branch readied by hand may have no <name>,
        or one that has moved on, and either is left alone. A refused source delete is logged
        in detail and left alone. Refused or unreported ready deletes are read back; only a
        ready ref still at the landed tip is a cleanup error and leaves that tip untried."""
        if not branches:
            return
        refs = []
        for branch in branches:
            refs.append(("refs/heads/ready/" + branch.name, branch.tip))
            source = self._git("rev-parse", "--verify", "--quiet",
                               f"refs/remotes/origin/{branch.name}^{{commit}}", check=False)
            if source.ok and source.out.strip() == branch.tip:
                refs.append(("refs/heads/" + branch.name, branch.tip))
        # Without --atomic, an updated head does not prevent retiring the other pinned refs.
        result = self._git("push", "--porcelain",
                           *(f"--force-with-lease={ref}:{tip}" for ref, tip in refs),
                           "origin", *(":" + ref for ref, _ in refs), check=False)
        statuses = {}
        for line in result.out.splitlines():
            fields = line.split("\t", 2)
            if len(fields) == 3 and fields[0] in ("-", "!"):
                ref = fields[1].partition(":")[2]
                statuses[ref] = (fields[0], fields[2].strip())
        errors = []
        for branch in branches:
            source_ref = "refs/heads/" + branch.name
            if source_ref in statuses and statuses[source_ref][0] == "!":
                atomic.extend(detail, f"left {branch.name}: {statuses[source_ref][1]}\n")
            ready_ref = "refs/heads/ready/" + branch.name
            status, reason = statuses.get(ready_ref, ("", result.err.strip() or "delete not reported"))
            remaining = False
            if status != "-":
                remote = self._git("ls-remote", "origin", ready_ref)
                remaining = any(line.split() == [branch.tip, ready_ref]
                                for line in remote.out.splitlines())
            self.state["collateral"].pop(branch.name, None)
            if remaining:
                errors.append(f"cleanup: ready/{branch.name} {reason}")
            else:
                self.state["tried"][branch.name] = branch.tip
            log.append("landed", path=self.log_path, branch=branch.name, tip=branch.tip, main=main)
            self._wake_notes.append(f"landed {branch.name}")
        return "; ".join(errors) or None

    def attempt(self, branches: Sequence[Branch]) -> bool:
        """Check branches as one batch on origin/main and land it when green; return green.

        Conflicts are rejected (step "merge"). If nothing merged, the branches are marked tried
        and the attempt is green. Otherwise: selection (full on every full_every-th batch), the
        ratchet steps with --write and a commit of lowered baselines, the gate-lane checks, the
        detail log FAB_HOME/queue/<batch>.log. Green: push the candidate to main with
        --force-with-lease=refs/heads/main:<parent> (refused: an error, nothing marked), delete
        each branch's ready/<name>, and its <name> when that is still the tip, with leases on
        their tips, record `landed` per branch. Red: a single branch is rejected with its failing
        step and marked tried. A check step that exits heavy.EX_TEMPFAIL (short of disk) is an
        error, not a red: nothing is rejected or marked tried, and the batch goes again.
        Records: `batch` (branches, parent, selection, steps as "name:code:seconds", outcome
        green, red, conflict or error, log), `landed` (branch, tip, main), `rejected` (branch,
        tip, step, tests, log). The checkout is left clean and detached.

        A receipt (docs/design/fab.md, 13.8): when exactly one branch merged, the batch is not a
        full one (not forced, and batches_since_full + 1 < full_every) and
        fab.receipts.reusable(fab.receipts.load(home, tip), tip, parent) holds, the checks are the
        ratchet steps with --write and their baseline commit as always, then only the `fmt` steps
        of fab.gate.check_steps for the queue's own selection. The batch record gains receipt (the
        receipt's path) and the batch counts toward the next full one (batches_since_full + 1,
        whatever the selection).

        Otherwise default/fuzzy use fab.queue_cpu and fab.cpu, with a wrapper built once
        in FAB_HOME/queue/<batch>/ and collector records/JUnit under each profile there.
        cpu_trees in the batch is a list of JSON strings with per-tree CPU, test wall,
        counts, selection completeness, optional budgets and top ten tests by CPU.
        Budget excesses are report only; starvation alone is green. A red is classed
        (fab.reds.classify on the red result and its report,
        with fab.receipts.load of each merged tip in merge order) unless a merged branch already
        has fab.reds.LIMIT collateral reds at its tip in state["collateral"] ({name: {"tip",
        "count"}}); the retries' results join the record's steps. Collateral: the outcome is
        collateral and the record gains retried (the verdict's tests); per merged branch a
        `collateral` record (branch, tip, step, tests, log) and its count raised (from 1 at a new
        tip); nothing is rejected or marked tried, no full check is forced, and the attempt
        returns False. A red that stands, classed or not, goes on as red, the record gaining
        stands (the verdict's reason) when it was classed. Conflicts are rejected either way. A
        branch landed or rejected loses its state["collateral"] entry.

        Whatever the outcome, the attempt ends by bounding the gate's target as a slot's is
        (docs/design/fab.md, 7): fab.slots.remove(fab.slots.sweep_plan(repo / "target",
        <the attempt's start in ns>)), the bytes freed going into the batch record as freed.
        last_outcome is then the batch record's outcome."""
        return self._attempt(branches)

    def _attempt(self, branches: Sequence[Branch]) -> bool:
        """Keep an attempt's state, cleanup and outcome together, including errors."""
        started_ns = time.time_ns()
        started = log.now()
        stamp = datetime.fromtimestamp(started_ns // 1_000_000_000, timezone.utc).strftime("%Y%m%dT%H%M%S")
        batch_id = f"{stamp}{started_ns % 1_000_000_000:09d}Z"
        detail = self.home / "queue" / (batch_id + ".log")
        # Each bisection attempt needs fresh collector directories, even in the same second.
        atomic.write(detail, "")
        record = {"branches": [branch.name for branch in branches], "parent": "",
                  "selection": None, "steps": [], "outcome": "error", "log": str(detail)}
        tried_before = dict(self.state["tried"])
        collateral_before = dict(self.state["collateral"])
        prepared = False
        clean = False
        self.last_merged = []
        try:
            if self._git("status", "--porcelain").out:
                raise RuntimeError("queue checkout has uncommitted or untracked files")
            prepared = True
            green = self._batch(branches, detail, record)
            self._save()
            clean = green
            return green
        except Exception as error:
            self.state["tried"] = tried_before
            self.state["collateral"] = collateral_before
            record.update(outcome="error", error=str(error))
            atomic.extend(detail, f"\n{error}\n")
            self._error_recorded = True
            raise
        finally:
            try:
                self._finish(started_ns, started, record, prepared, clean)
            finally:
                self.last_outcome = record["outcome"]

    def _batch(self, branches: Sequence[Branch], detail: Path, record: dict) -> bool:
        """Merge, check and publish one batch, recording rejections and retirement errors."""
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
            paths = gate.changed_paths(self.repo, base=parent, sh=self.sh)
            green, outcomes, _ = self._checks(parent, paths, detail, record, merged)
            if green:
                self._publish(parent)
        cleanup_error = None
        if green:
            main = self._git("rev-parse", "origin/main").out.strip()
            cleanup_error = self._retire([*merged, *reachable], main, detail)
        elif len(merged) == 1 and record["outcome"] != "collateral":
            failed = next(step.name for step in outcomes if not step.green)
            self._reject(merged[0], failed, detail)
        for branch, _ in conflicts:
            self._reject(branch, "merge", detail)
        if record["outcome"] != "collateral":
            record["outcome"] = ("conflict" if conflicts else "green") if green else "red"
        if cleanup_error:
            record.update(outcome="error", error=cleanup_error)
            atomic.extend(detail, f"\n{cleanup_error}\n")
        return green

    def _checks(self, parent: str, paths: Sequence[str], detail: Path,
                record: dict, merged: Sequence[Branch]) -> tuple[bool, list[gate.StepResult], str | set[str]]:
        """Select and check the candidate, committing lowered baselines and counting full checks."""
        load = gate.loader(self.load, sh=self.sh)
        full = self._force_full or self.state["batches_since_full"] + 1 >= self.full_every
        reuse = not full and len(merged) == 1 and receipts.reusable(
            receipts.load(self.home, merged[0].tip), merged[0].tip, parent)
        if reuse:
            record["receipt"] = str(receipts.path(self.home, merged[0].tip))
        selected = "full" if full else gate.select(self.repo, paths, base=parent, sh=self.sh, load=load)
        record["selection"] = gate.shown(selected)
        outcomes = gate.run_steps(gate.ratchet_steps(self.repo, paths, write=True), detail, sh=self.sh)
        green = all(step.green for step in outcomes)
        reports = {}
        if green:
            baselines = [f"{tree}/scripts/old-forms.txt" for tree in gate.TREES]
            changed = self._git("diff", "--name-only", "-z", "--", *baselines).out.split("\0")[:-1]
            if changed:
                self._git("add", "--", *changed)
                self._git("commit", "-m", "Lower old-form baselines")
            if self._git("status", "--porcelain").out:
                raise RuntimeError("ratchet left changes outside its baselines")
            meta = load(self.repo) if isinstance(selected, set) else None
            checks = gate.check_steps(self.repo, selected, paths, meta, lane="gate")
            if reuse:
                checks = [step for step in checks if step.name == "fmt"]
            checked, reports = queue_cpu.run_steps(checks, detail, record, sh=self.sh)
            outcomes += checked
            green = all(step.green for step in outcomes)
            if not green and outcomes[-1].code == heavy.EX_TEMPFAIL:
                # Short of disk is the gate's fault, not the batch's: an error, tried again.
                raise RuntimeError(f"Infra: disk at {outcomes[-1].name}")
        if not green:
            self._red(outcomes, reports, detail, record, merged)
        record["steps"] = gate.step_texts(outcomes)
        self.state["batches_since_full"] = (
            0 if selected == "full" and not reuse else self.state["batches_since_full"] + 1)
        if not green and selected == "full" and not reuse and record.get("outcome") != "collateral":
            self._force_full = True
        return green, outcomes, selected

    def _red(self, outcomes: list[gate.StepResult], reports: dict[str, Path], detail: Path,
             record: dict, merged: Sequence[Branch]) -> None:
        """Class a red within the tips' collateral limit and record its retries and counts."""
        counts = self.state["collateral"]
        if any(counts.get(branch.name, {}).get("tip") == branch.tip and
               counts[branch.name]["count"] >= reds.LIMIT for branch in merged):
            return
        failed = outcomes[-1]
        verdict = reds.classify(self.repo, failed, reports.get(failed.name),
                                [receipts.load(self.home, branch.tip) for branch in merged],
                                detail, name=detail.stem, sh=self.sh)
        outcomes.extend(verdict.retries)
        if not verdict.collateral:
            record["stands"] = verdict.reason
            return
        record.update(outcome="collateral", retried=list(verdict.tests))
        for branch in merged:
            prior = counts.get(branch.name, {})
            count = prior["count"] if prior.get("tip") == branch.tip else 0
            counts[branch.name] = {"tip": branch.tip, "count": count + 1}
            log.append("collateral", path=self.log_path, branch=branch.name, tip=branch.tip,
                       step=failed.name, tests=list(verdict.tests), log=str(detail))

    def _publish(self, parent: str) -> None:
        """Push a clean candidate with a lease on main's parent and advance the local base."""
        if self._git("status", "--porcelain").out:
            raise RuntimeError("checks left uncommitted or untracked files")
        candidate = self._git("rev-parse", "HEAD").out.strip()
        self._git("push", f"--force-with-lease=refs/heads/main:{parent}",
                  "origin", f"{candidate}:refs/heads/main")
        # Advance the local base before checking the next bisection half.
        self._git("update-ref", "refs/remotes/origin/main", candidate)

    def _finish(self, started_ns: int, started: str, record: dict, prepared: bool, clean: bool) -> None:
        """Reset unsuccessful attempts, sweep old build output and always record the batch."""
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

    def cycle(self) -> bool:
        """Consume queue-untry requests (forget, save, remove, record), then fetch --prune.
        Take up to `batch` candidates and attempt them, bisecting when red;
        return whether there was anything to do. A collateral attempt (last_outcome
        "collateral") is not bisected: its branches go again next cycle. Within a bisection, a
        collateral attempt counts as passed, so its group is not split further. Finally, wake
        once with `queue <landed/rejected notes joined by comma>` when records were written
        and wake is set; clear the notes even on error. A failed wake is printed to stderr
        and never fails the cycle."""
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
        try:
            initial_green = self.attempt(branches)
            merged = self.last_merged
            first = True

            def check(group):
                nonlocal first
                if first:
                    first = False
                    return initial_green or self.last_outcome == "collateral"
                return self.attempt(group) or self.last_outcome == "collateral"

            bisect(merged, check)
            return True
        finally:
            try:
                if self._wake_notes and self.wake is not None:
                    self.wake("queue " + ", ".join(self._wake_notes))
            except Exception as error:
                print(f"fab queue: wake: {error}", file=sys.stderr)
            finally:
                self._wake_notes.clear()

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


def service(repo: Path | None = None) -> units.Service:
    """UNIT, which runs `fab queue run --repo <repo>` on the gate (repo default
    ~/src/fabrig/queue, made absolute) and drains for up to DRAIN on a stop."""
    repo = (repo if repo is not None else Path.home() / "src/fabrig/queue").absolute()
    return units.Service(UNIT, "fabrig's merge queue", "gate",
                         ("queue", "run", "--repo", str(repo)), "queue.stop", DRAIN)


def unit(*, checkout: Path | None = None, repo: Path | None = None, home: Path | None = None) -> str:
    """The text of UNIT (fab.units.text of service(repo)). Pure."""
    return units.text(service(repo), checkout=checkout, home=home)


def install(*, sh: Runner = run, directory: Path | None = None, checkout: Path | None = None,
            repo: Path | None = None, known: dict[str, machines.Host] | None = None) -> str:
    """Install or refresh UNIT on this machine at a deploy (fab.units.install of service(repo)
    for the machines with the role gate); return what was done, one line."""
    return units.install(service(repo), sh=sh, directory=directory, checkout=checkout, known=known)


def main(argv: list[str]) -> int:
    """`fab queue run|once [--repo PATH] [--batch N]` (repo default FAB_HOME/repos/fabrig; run stops
    at FAB_HOME/queue.stop), `fab queue plan` (the next batch's names, no checks),
    `fab queue log [--since TS]` (queue.jsonl records at or after TS, one per line),
    `fab queue untry BRANCH` (ask the running queue to forget its tried tip next cycle),
    `fab queue receipt TIP` (keep the precheck receipt on stdin for TIP, fab.receipts.store
    with FAB_HOME; a refusal prints `fab queue: <error>` and exits 1),
    `fab queue install [--repo PATH]` (install(repo=) at a deploy, printing its line; repo
    default ~/src/fabrig/queue).
    Running cycles wake the tick through fab.wake.wake."""
    parser = argparse.ArgumentParser(prog="fab queue")
    parser.add_argument("command", choices=("run", "once", "plan", "log", "untry", "receipt", "install"))
    parser.add_argument("branch", nargs="?")
    parser.add_argument("--repo", type=Path)
    parser.add_argument("--batch", type=int, default=8)
    parser.add_argument("--since")
    args = parser.parse_args(argv)
    if (args.command in ("untry", "receipt")) != (args.branch is not None):
        parser.error("untry requires BRANCH; receipt requires TIP; other commands take no branch")
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
        if args.command == "install":
            print(install(repo=args.repo))
            return 0
        if args.repo is None:
            args.repo = log.home() / "repos/fabrig"
        if args.command == "receipt":
            receipts.store(log.home(), args.branch, sys.stdin.read())
            return 0
        if args.command == "untry":
            path = log.home() / "queue-untry" / args.branch.replace("/", "%2F")
            atomic.write(path, "")
            return 0
        queue = Queue(args.repo, batch=args.batch, wake=events.wake)
        if args.command == "plan":
            queue._git("fetch", "--prune", "origin")
            for branch in candidates(queue.repo, queue.state["tried"], sh=queue.sh)[:queue.batch]:
                print(branch.name)
        elif args.command == "once":
            queue.cycle()
        else:
            queue.run(stop=queue.home / "queue.stop")
    except (OSError, RuntimeError, ValueError) as error:  # Failed is a RuntimeError
        print(f"fab queue: {error}", file=sys.stderr)
        return 1
    return 0
