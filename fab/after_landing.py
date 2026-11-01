"""After landing: fabrig's slow tiers on each new main, reds confirmed and recorded
(docs/design/fab.md, 11).

Runs on a builder in one slot claimed for it. Each cycle fetches main; a new tip gets one run
of the tier set, each failed test is run again alone, and every test that is not plainly
passing is classified against its own history. Verdicts are records in
FAB_HOME/after-landing.jsonl, which the dispatcher and the reports read over ssh; the cursor
and the history are FAB_HOME/after-landing/state.json.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from fab import atomic, hosts, log, logins, nextest, slots, tiers, units
from fab.sh import Runner, run, ssh

# The pairs every tip gets, in order. A profile is enrolled only by adding it here: not the
# live pairs (real providers, the user's sign-ins) nor process-temper (its owner's).
TIER_SET = ("exhaustive-skein", "qa-skein", "qa-smith", "qa-jig", "process-jig",
            "browser-skein", "browser-jig", "browser-temper", "qa-temper")
# The live pairs `--live` adds: each variable its tests read, and the kind of login fab lends
# for it, borrowed from the shelf on the dispatcher for the pair and returned after it
# (docs/design/fab.md, 13.13). live-skein joins once its tests read a login's file.
LIVE = {
    "live-temper": (("TEMPER_LIVE_ACCOUNT", "chatgpt"), ("TEMPER_LIVE_CLAUDE", "claude-box")),
    "live-smith": (("SMITH_LIVE_CLAUDE", "claude-box"),),
}
RUN = "after-landing"  # the claim's run and task: `fab slot claim N after-landing after-landing`
RECORD = "after-landing.jsonl"  # under FAB_HOME
STATE = "after-landing"  # FAB_HOME/after-landing/: state.json and one directory per run
# A queue merge on main's first parent: fab's queue writes `Merge <draft>/<task>`, the old
# queue `Merge ready/<draft>/<task>`.
MERGE = re.compile(r"Merge (?:ready/)?([^/\s]+/[^/\s]+)")
UNIT = "fab-after-landing.service"  # the runner's user unit on the machine with the role
ROLE = "after-landing"  # the fab/hosts.toml role of that machine, which names its slot
DRAIN = "2h"  # a stop waits for the run in progress: a deploy never cuts a run short
CONFIRMED = ("new", "standing", "unattributed")  # the states of a red confirmed by its rerun


@dataclass(frozen=True)
class Suspect:
    commit: str
    subject: str
    branch: str | None  # "<draft>/<task>" when the commit is a queue merge; None otherwise


def suspects(repo: Path, previous: str | None, tip: str, *, sh: Runner = run) -> list[Suspect]:
    """The commits that landed between previous and tip: `git rev-list --first-parent
    --reverse <previous>..<tip>` in repo (oldest first), each with its parents and subject from
    `git show -s --format=%P%n%s`. A commit with two parents whose subject fully matches MERGE
    names that branch; any other commit has branch None. previous None: no suspects."""
    if previous is None:
        return []
    commits = sh(["git", "rev-list", "--first-parent", "--reverse", f"{previous}..{tip}"],
                 cwd=str(repo), check=True).out.splitlines()
    result = []
    for commit in commits:
        parents, subject = sh(["git", "show", "-s", "--format=%P%n%s", commit],
                              cwd=str(repo), check=True).out.rstrip("\n").split("\n", 1)
        match = MERGE.fullmatch(subject) if len(parents.split()) == 2 else None
        result.append(Suspect(commit, subject, match.group(1) if match else None))
    return result


def state(first: str, rerun: str | None, last: dict | None) -> str:
    """A test's state at a tip, from its first result there ("pass", "fail" or "skipped"), its
    rerun alone ("pass" or "fail"; None when it was not rerun) and its history entry (last:
    {"result": "pass" or "red", "commit": ...}, None when it never executed).
    skipped: "unobserved". pass: "recovered" when last was red, else "passing".
    fail then pass: "flake". fail then fail: "unattributed" with no history, "standing" when
    last was red, "new" when it was pass. ValueError for a fail without a rerun or a rerun
    after a pass or a skip."""
    if first == "fail":
        if rerun is None:
            raise ValueError("a failed test needs a rerun")
        if rerun == "pass":
            return "flake"
        if last is None:
            return "unattributed"
        return "standing" if last["result"] == "red" else "new"
    if rerun is not None:
        raise ValueError("a passing or skipped test cannot have a rerun")
    if first == "skipped":
        return "unobserved"
    return "recovered" if last is not None and last["result"] == "red" else "passing"


def verdict(states: Iterable[str], faulted: bool) -> str:
    """A run's verdict: "red" when any state is CONFIRMED (whatever faulted), else "partial"
    when a pair faulted, else "green"."""
    if any(value in CONFIRMED for value in states):
        return "red"
    return "partial" if faulted else "green"


class AfterLanding:
    def __init__(self, slot: int, *, home: Path | None = None, sh: Runner = run,
                 tier_set: tuple[str, ...] = TIER_SET, live: bool = False,
                 known: dict[str, hosts.Host] | None = None):
        """slot: the number of a fab slot (fab.slots.slots_dir() / str(slot)); home: FAB_HOME
        (default fab.log.home()). Load state.json when it exists: {"cursor": the last tip run
        without a faulted pair, or null; "last": {"tip", "verdict"} of the last run, or null;
        "tests": {Case.key: {"result": "pass" or "red", "commit": tip}}}; otherwise start
        from all three empty. live adds LIVE's pairs to tier_set; known (default
        fab.hosts.load()) names this machine and the dispatcher they borrow logins from.
        ValueError when the slot does not exist or its claim
        (fab.slots.read_claim) is missing or not RUN's: the runner touches only its own slot."""
        self.repo = slots.slots_dir() / str(slot)
        if self.repo.is_symlink() or not self.repo.is_dir():
            raise ValueError(f"slot {slot} does not exist")
        held = slots.read_claim(slot)
        if held is None or held.run != RUN or held.task != RUN:
            raise ValueError(f"slot {slot} is not claimed for {RUN}")
        self.home = log.home() if home is None else home
        self.sh = sh
        self.tier_set = tier_set + tuple(profile for profile in LIVE if live and profile not in tier_set)
        self.known = known
        self.log_path = self.home / RECORD
        self.state_path = self.home / STATE / "state.json"
        self.state = (json.loads(self.state_path.read_text(encoding="utf-8"))
                      if self.state_path.exists() else {"cursor": None, "last": None, "tests": {}})

    def pair(self, profile: str, tip: str, directory: Path) -> dict:
        """Run one pair at tip (already checked out) and classify its tests.

        The first invocation: write fab.nextest.overlay(<the slot's fab.tiers.NEXTEST_CONFIG
        text>, profile, directory/<profile>.xml) to directory/<profile>.toml, then
        fab.tiers.run_pair (the pair from fab.tiers.load of the slot) with extra
        `--config-file <that file>` and log directory/<profile>.log. Its code must be 0 with no
        failed case or fab.tiers.TEST_FAILED with at least one, and the JUnit must hold at
        least one case. Then each failed case, in order, alone: the same with a fresh overlay
        and log named <profile>-<n> (n from 1) and extra `-E <fab.nextest.exact_filter>`; its
        code must be 0 or TEST_FAILED and its JUnit exactly one case, the same identity, not
        skipped. Each case's state comes from `state` with the history entry for its key.

        Return {"profile", "status": "ran" or "faulted", "reason" (why it faulted, else ""),
        "selected" (cases), "failed" (failed first results), "seconds" (wall time of its
        invocations), "log" (the first log), "cases": [(Case, state, rerun log or "")]}.
        Any of the conditions above failing, a ValueError from fab.nextest or fab.tiers, or an
        OSError faults the pair with the reason (`exit <code>`, `junit: ...`, `rerun: ...`) and
        no cases: a faulted pair says nothing about its tests."""
        first_log = directory / f"{profile}.log"
        result = {"profile": profile, "status": "faulted", "reason": "", "selected": 0,
                  "failed": 0, "seconds": 0.0, "log": str(first_log), "cases": []}
        stage = "junit"

        def invoke(name, extra):
            report = directory / f"{name}.xml"
            config = directory / f"{name}.toml"
            # A replay in the same second must not accept a report from the interrupted run.
            report.unlink(missing_ok=True)
            atomic.write(config, nextest.overlay(config_text, profile, report))
            started = time.monotonic()
            try:
                code = tiers.run_pair(self.repo, target, ["--config-file", str(config), *extra],
                                      directory / f"{name}.log", sh=self.sh, env=env)
            finally:
                result["seconds"] += time.monotonic() - started
            return code, report

        borrowed: list[str] = []
        env: dict[str, str] = {}
        try:
            if profile in LIVE:
                stage = "logins"
                env = self.borrow(profile, tip, directory, borrowed)
                stage = "junit"
            config_text = (self.repo / tiers.NEXTEST_CONFIG).read_text(encoding="utf-8")
            configured = tiers.load(self.repo)
            if profile not in configured:
                raise ValueError(f"unknown tier profile: {profile}")
            target = configured[profile]
            code, report = invoke(profile, [])
            if code not in (0, tiers.TEST_FAILED):
                result["reason"] = f"exit {code}"
                return result
            cases = nextest.junit(report, profile)
            result["selected"] = len(cases)
            result["failed"] = sum(case.result == "fail" for case in cases)
            if not cases or (code == tiers.TEST_FAILED) != bool(result["failed"]):
                raise ValueError(f"exit {code} inconsistent with JUnit results")
            classified = []
            number = 0
            for case in cases:
                rerun = None
                rerun_log = ""
                if case.result == "fail":
                    stage = "rerun"
                    number += 1
                    name = f"{profile}-{number}"
                    expression = nextest.exact_filter(case.binary, case.test)
                    code, report = invoke(name, ["-E", expression])
                    if code not in (0, tiers.TEST_FAILED):
                        raise ValueError(f"exit {code}")
                    selected = nextest.junit(report, profile)
                    if (len(selected) != 1 or selected[0].key != case.key
                            or selected[0].result == "skipped"):
                        raise ValueError("JUnit must select exactly the failed test, not skipped")
                    rerun = selected[0].result
                    if (code == tiers.TEST_FAILED) != (rerun == "fail"):
                        raise ValueError(f"exit {code} inconsistent with JUnit results")
                    rerun_log = str(directory / f"{name}.log")
                classified.append((case, state(case.result, rerun,
                                               self.state["tests"].get(case.key)), rerun_log))
        except (ValueError, OSError, logins.Refused) as error:
            result["reason"] = f"{stage}: {error}"
            return result
        finally:
            self.give_back(borrowed)
        result.update(status="ran", cases=classified)
        return result

    def _shelf(self, argv: list[str]) -> str:
        """Run `fab logins ARGV...` on the dispatcher, where the shelf is (here, when this
        machine is it); its stdout, or Refused with its last error line."""
        machines = hosts.load() if self.known is None else self.known
        dispatcher = next((host for host in machines.values() if "dispatcher" in host.roles), None)
        if dispatcher is None:
            raise logins.Refused("hosts.toml names no dispatcher")
        command = ["fab", "logins", *argv]
        here = hosts.this(machines)
        done = self.sh(command if here is dispatcher else ssh(dispatcher.ssh, command), timeout=600)
        if not done.ok:
            raise logins.Refused((done.err.strip().splitlines() or [f"exit {done.code}"])[-1])
        return done.out.strip()

    def borrow(self, profile: str, tip: str, directory: Path, borrowed: list[str]) -> dict[str, str]:
        """Borrow a login for each of LIVE[profile]'s variables, lent to this machine at
        directory/logins/<variable> (a directory login there, a file login inside it under its
        kind's name) for holder after-landing/<tip[:12]>/<profile>; append each id to borrowed
        as it is lent; return the variables. Refused when one cannot be borrowed."""
        machines = hosts.load() if self.known is None else self.known
        here = hosts.this(machines)
        if here is None:
            raise logins.Refused("this machine is not in hosts.toml")
        env = {}
        for variable, kind in LIVE[profile]:
            place = directory / "logins" / variable
            path = place if logins.KINDS[kind].directory else place / logins.KINDS[kind].item
            borrowed.append(self._shelf(["borrow", kind, here.name, "--path", str(path),
                                         "--holder", f"{RUN}/{tip[:12]}/{profile}"]))
            env[variable] = str(path)
        return env

    def give_back(self, borrowed: list[str]) -> None:
        """Return each borrowed login; one that cannot be returned stays lent to its run (custody
        says where it is) and is recorded as an `error` record for a person."""
        for name in borrowed:
            try:
                self._shelf(["return", name])
            except logins.Refused as error:
                log.append("error", path=self.log_path, error=f"login {name} not returned: {error}")

    def check(self, tip: str) -> dict:
        """One run of the tier set at tip, recorded, the state saved; return the run record.

        Steps: the run directory FAB_HOME/after-landing/<tip[:12]>-<YYYYMMDDTHHMMSSZ>/; in the
        slot `git switch --detach --force <tip>` and `git clean -fd` (target/ is ignored, so it
        stays warm); `pair` for each profile of tier_set; then append to FAB_HOME/RECORD
        (fab.log.append with path), first one `test` record per case whose state is neither
        passing nor unobserved: tip, profile, binary, test, state, error, log (the pair's first
        log), rerun (its rerun log, or ""), good (the history entry's commit when its result is
        pass, else ""), and for a new red branches (the branch names of suspects(good, tip), in
        order) and commits (their count); then one `run` record: tip, previous (the cursor, or
        ""), branches (the branch names of suspects(cursor, tip)), commits (their count),
        verdict, the counts new, standing, unattributed, flake and recovered, pairs (one
        "<profile>:<status>:<selected>:<failed>:<seconds, 1 decimal>" per pair), faults (one
        "<profile>: <reason>" per faulted pair), log (the run directory), freed. freed: the bytes
        of fab.slots.remove(fab.slots.sweep_plan(<slot>/target, <the run's start in ns>)), as
        the queue bounds its target.

        Then update the state and save it (fab.atomic.write, sibling and rename): every case of
        a ran pair that executed sets its key's history to "pass" (passing, recovered, flake)
        or "red" (confirmed) with the tip; unobserved ones keep theirs. "last" becomes this
        tip and verdict; the cursor becomes tip only when no pair faulted. A crash before the
        save redoes the run whole at the next cycle."""
        started_ns = time.time_ns()
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        directory = self.home / STATE / f"{tip[:12]}-{stamp}"
        directory.mkdir(parents=True, exist_ok=True)
        self.sh(["git", "switch", "--detach", "--force", tip], cwd=str(self.repo), check=True)
        self.sh(["git", "clean", "-fd"], cwd=str(self.repo), check=True)
        pairs = [self.pair(profile, tip, directory) for profile in self.tier_set]
        previous = self.state["cursor"]
        landed = suspects(self.repo, previous, tip, sh=self.sh)
        counts = dict.fromkeys((*CONFIRMED, "flake", "recovered"), 0)
        tests = dict(self.state["tests"])
        states = []
        for pair in pairs:
            for case, current, rerun_log in pair["cases"]:
                states.append(current)
                if current not in ("passing", "unobserved"):
                    counts[current] += 1
                    last = self.state["tests"].get(case.key)
                    good = last["commit"] if last and last["result"] == "pass" else ""
                    attribution = {}
                    if current == "new":
                        changed = suspects(self.repo, good, tip, sh=self.sh)
                        attribution = {"branches": [item.branch for item in changed if item.branch],
                                       "commits": len(changed)}
                    log.append("test", path=self.log_path, tip=tip, profile=case.profile,
                               binary=case.binary, test=case.test, state=current, error=case.error,
                               log=pair["log"], rerun=rerun_log, good=good, **attribution)
                if current != "unobserved":
                    tests[case.key] = {"result": "red" if current in CONFIRMED else "pass",
                                       "commit": tip}
        faulted = any(pair["status"] == "faulted" for pair in pairs)
        outcome = verdict(states, faulted)
        freed = slots.remove(slots.sweep_plan(self.repo / "target", started_ns))
        record = log.append(
            "run", path=self.log_path, tip=tip, previous=previous or "",
            branches=[item.branch for item in landed if item.branch], commits=len(landed),
            verdict=outcome, **counts,
            pairs=[f'{pair["profile"]}:{pair["status"]}:{pair["selected"]}:{pair["failed"]}:'
                   f'{pair["seconds"]:.1f}' for pair in pairs],
            faults=[f'{pair["profile"]}: {pair["reason"]}' for pair in pairs
                    if pair["status"] == "faulted"], log=str(directory), freed=freed)
        saved = {"cursor": previous if faulted else tip,
                 "last": {"tip": tip, "verdict": outcome}, "tests": tests}
        atomic.write(self.state_path, json.dumps(saved, sort_keys=True) + "\n")
        self.state = saved
        return record

    def cycle(self) -> bool:
        """In the slot: `git fetch -q origin main`, the tip `git rev-parse origin/main`. Nothing
        to do (False) when the tip is the cursor, or is the last run's tip and that run was
        partial (its suspects stay with the cursor, so the next tip's run covers them).
        Otherwise check(tip) and True."""
        self.sh(["git", "fetch", "-q", "origin", "main"], cwd=str(self.repo), check=True)
        tip = self.sh(["git", "rev-parse", "origin/main"], cwd=str(self.repo), check=True).out.strip()
        last = self.state["last"]
        if tip == self.state["cursor"] or (last and last["tip"] == tip and last["verdict"] == "partial"):
            return False
        self.check(tip)
        return True

    def run(self, *, stop: Path, idle: float = 60.0, sleep: Callable[[float], None] | None = None) -> None:
        """Cycle until the file stop exists, sleeping idle seconds after a cycle with nothing to
        do. An exception in a cycle appends an `error` record (error: its text) to
        FAB_HOME/RECORD, and the loop sleeps and goes on."""
        sleep = time.sleep if sleep is None else sleep
        while not stop.exists():
            try:
                worked = self.cycle()
            except Exception as error:
                log.append("error", path=self.log_path, error=str(error))
                sleep(idle)
            else:
                if not worked:
                    sleep(idle)


def service(slot: int) -> units.Service:
    """UNIT, which runs `fab after-landing run --slot <slot>` and drains for up to DRAIN."""
    return units.Service(UNIT, "fabrig's slow tiers on each new main", ROLE,
                         (RUN, "run", "--slot", str(slot)), "after-landing.stop", DRAIN)


def install(*, sh: Runner = run, directory: Path | None = None, checkout: Path | None = None,
            known: dict[str, hosts.Host] | None = None) -> str:
    """Install or refresh UNIT on this machine at a deploy; return what was done, one line.

    known is the machines (default fab.hosts.load()). On the machine with ROLE, its
    after_landing_slot is claimed for RUN first (fab.slots.claim, or the claim RUN already
    holds); a slot that is missing or held by another run is a ValueError and nothing is
    installed. Then fab.units.install of service(slot), which on a machine without ROLE
    disables a unit it finds; the slot is the user's to release there."""
    known = known if known is not None else hosts.load()
    host = hosts.this(known)
    slot = host.after_landing_slot if host is not None else 0
    if host is not None and ROLE in host.roles:
        if slot < 1:
            raise ValueError(f"{host.name}: the {ROLE} role needs after_landing_slot")
        held = slots.claim(slot, RUN, RUN) or slots.read_claim(slot)
        if held is None or held.run != RUN:
            raise ValueError(f"slot {slot} is held by {held.run if held else 'nobody'}, not {RUN}")
    return units.install(service(slot), sh=sh, directory=directory, checkout=checkout, known=known)


def main(argv: list[str]) -> int:
    """`fab after-landing run|once --slot N [--live]` (run stops at FAB_HOME/after-landing.stop),
    `fab after-landing log [--since TS]` (RECORD's records at or after TS, one JSON object per
    line, as `fab queue log` prints) and `fab after-landing install` (install() at a deploy,
    printing its line). Exit 0; 1 with `fab after-landing: <error>` on stderr for an OSError,
    RuntimeError or ValueError (a slot not claimed for RUN); 2 on bad arguments."""
    parser = argparse.ArgumentParser(prog="fab after-landing")
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("run", "once"):
        running = commands.add_parser(command)
        running.add_argument("--slot", type=int, required=True)
        running.add_argument("--live", action="store_true", help="also LIVE's pairs, on logins from the shelf")
    commands.add_parser("log").add_argument("--since")
    commands.add_parser("install")
    try:
        args = parser.parse_args(argv)
    except SystemExit as error:
        return int(error.code)
    try:
        if args.command == "install":
            print(install())
        elif args.command == "log":
            for entry in log.iterate(log.home() / RECORD):
                if args.since is None or entry["ts"] >= args.since:
                    print(json.dumps(entry, ensure_ascii=False))
        else:
            runner = AfterLanding(args.slot, live=args.live)
            if args.command == "once":
                runner.cycle()
            else:
                runner.run(stop=runner.home / "after-landing.stop")
    except (OSError, RuntimeError, ValueError) as error:
        print(f"fab after-landing: {error}", file=sys.stderr)
        return 1
    return 0
