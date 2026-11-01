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
import tomllib
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from fab import atomic, cpu, hosts, log, logins, nextest, slots, tiers, units, wake as events
from fab.sh import Runner, run, ssh

# The pairs every tip gets, in order. A profile is enrolled only by adding it here: not the
# live pairs (real providers, the user's sign-ins). The qa, exhaustive and process-jig pairs
# ended on 11-01 (the user: provenance is not a tier); process-temper joined once within its
# 360 CPU-s (decision 0028).
TIER_SET = ("browser-jig", "browser-temper", "browser-skein", "process-temper")
# The live pairs `--live` adds: each variable its tests read, and the kind of login fab lends
# for it, borrowed from the shelf on the dispatcher for the pair and returned after it
# (docs/design/fab.md, 13.13). Not live-smith: its tests need `SMITH_LIVE`, a whole live root
# (smith's configuration, host id, a ChatGPT record of smith's own signed in by `smith login
# chatgpt`, and programs/claude), which no shelf kind holds yet (11-01, red on hetzner8).
# Not live-temper: all its live stories are owner-run and ignored; since fabrig eb6c40aaf
# the live binaries have no harness unit tests, so nextest exits 4 (no tests to run),
# faulting every run and holding the cursor. It returns only once the user decides which
# ignored stories, if any, should run under `--live` with `--run-ignored`.
LIVE = {
    "live-skein": (("SKEIN_TEST_LIVE_OPENAI_AUTH", "codex"), ("SKEIN_TEST_LIVE_ANTHROPIC_CREDENTIALS", "claude")),
}
# The cheapest models, for live pairs whose tests take theirs from the environment (the
# user, 11-01: cheap models such as luna). temper's and smith's live tests pick gpt-6-luna and
# claude-haiku-5-5 themselves.
CHEAP = {
    "live-skein": {"SKEIN_TEST_LIVE_OPENAI_MODEL": "gpt-6-luna", "SKEIN_TEST_LIVE_ANTHROPIC_MODEL": "claude-haiku-5-5"},
}
# Kinds whose tests read the access token and never refresh it: fab refreshes it first.
REFRESHED = ("codex", "claude")
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
    """A test's state from its first result (pass/fail/skipped/starved), its rerun
    alone (pass/fail/starved; None when it was not rerun) and its history entry (last:
    {"result": "pass" or "red", "commit": ...}, None when it never executed).
    Starved preserves history without a rerun; an observed fail stays red if its rerun
    starves. skipped: "unobserved". pass: "recovered" when last was red, else "passing".
    fail then pass: "flake". fail then fail: "unattributed" with no history, "standing" when
    last was red, "new" when it was pass. ValueError for a fail without a rerun or a rerun
    after a pass or a skip."""
    if first == "starved":
        if rerun is not None:
            raise ValueError("a starved test cannot have a rerun")
        return "starved"
    if first == "fail":
        if rerun == "starved":
            rerun = "fail"  # an observed failure cannot be cleared by starvation
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
        self.wrapper = None
        self.limits = {}
        self.diagnostics = {}
        self.wall_s = 0.0
        self.log_path = self.home / RECORD
        self.state_path = self.home / STATE / "state.json"
        self.state = (json.loads(self.state_path.read_text(encoding="utf-8"))
                      if self.state_path.exists() else {"cursor": None, "last": None, "tests": {}})

    def remaining(self) -> float | None:
        """The remaining total test wall allowance; builds and admission are outside it."""
        hard = self.limits.get("wall_hard_s")
        return None if hard is None else hard - self.wall_s

    def pair(self, profile: str, tip: str, directory: Path) -> dict:
        """Run one configured pair with fab's prerequisites and the checkout's collector.

        Absent profiles retire; after total wall expiry they stay unobserved. Every
        invocation has a fresh collector directory. Only actual failures get exact
        reruns; observed failures survive a starved or wall-prevented confirmation.
        Malformed/missing reports or a failed prerequisite fault the pair. CPU and
        test wall include reruns, even when classification later faults.
        """
        first_log = directory / f"{profile}.log"
        result = {"profile": profile, "status": "faulted", "reason": "", "selected": 0,
                  "failed": 0, "seconds": 0.0, "wall_s": 0.0, "cpu_s": 0.0,
                  "starved_run": False, "measurements": {},
                  "budget": self.diagnostics.get(profile, {}), "log": str(first_log), "cases": []}
        stage = "junit"

        def invoke(name, extra):
            report = directory / f"{name}.xml"
            config = directory / f"{name}.toml"
            # A replay in the same second must not accept a report from the interrupted run.
            report.unlink(missing_ok=True)
            atomic.write(config, nextest.overlay(config_text, profile, report))
            started = time.monotonic()
            try:
                remaining = self.remaining()
                if remaining is not None and remaining <= 0:
                    return None, [], {}
                if self.wrapper is None:
                    self.wrapper = cpu.build_wrapper(self.repo, directory, sh=self.sh)
                code, measured = cpu.run_pair(
                    self.repo, target, ["--config-file", str(config), *extra],
                    directory / f"{name}.log", directory=directory / f"{name}-cpu",
                    wrapper=self.wrapper, wall_hard_s=remaining, sh=self.sh, env=env)
                if measured:
                    suite = measured["suite"]
                    self.wall_s += suite["wall_s"]
                    result["wall_s"] += suite["wall_s"]
                    result["cpu_s"] += suite["cpu_s"]
                    result["starved_run"] |= suite["starved_run"]
                    for item in measured["tests"]:
                        identity = (item["binary_id"], item["test_name"])
                        values = result["measurements"].setdefault(identity, dict(cpu_s=0.0, wall_s=0.0, starved=0, incomplete=0))
                        values["cpu_s"] += item["cpu_s"]
                        values["wall_s"] += item["wall_s"]
                        values["starved"] += item["starved"]
                        values["incomplete"] += item["incomplete"]
            finally:
                result["seconds"] += time.monotonic() - started
            return code, cpu.cases(directory / f"{name}-cpu", profile, measured) if measured else [], measured

        borrowed: list[str] = []
        env: dict[str, str] = {}
        try:
            config_text = (self.repo / tiers.NEXTEST_CONFIG).read_text(encoding="utf-8")
            if profile not in tomllib.loads(config_text).get("profile", {}):
                result.update(status="retired", reason="profile removed from checkout")
                return result
            configured = tiers.load(self.repo)
            if profile not in configured:
                result.update(status="retired", reason="profile removed from checkout")
                return result
            target = configured[profile]
            if self.remaining() is not None and self.remaining() <= 0:
                result.update(status="unobserved", reason="total wall hard limit")
                return result
            if profile in LIVE:
                stage = "logins"
                env = self.borrow(profile, tip, directory, borrowed)
                stage = "junit"
            code, cases, measured = invoke(profile, [])
            if code not in (0, tiers.TEST_FAILED):
                result["reason"] = f"exit {code}"
                return result
            result["selected"] = len(cases)
            result["failed"] = sum(case.result == "fail" for case in cases)
            if (not cases and not result["starved_run"]) or (code == tiers.TEST_FAILED) != bool(result["failed"]):
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
                    code, selected, rerun_measured = invoke(name, ["-E", expression])
                    if code is None:
                        # The failure was observed before the budget stopped confirmation.
                        classified.append((case, state("fail", "fail", self.state["tests"].get(case.key)), ""))
                        continue
                    if code not in (0, tiers.TEST_FAILED):
                        raise ValueError(f"exit {code}")
                    if (len(selected) != 1 or selected[0].key != case.key
                            or selected[0].result == "skipped"):
                        raise ValueError("JUnit must select exactly the failed test, not skipped")
                    rerun = selected[0].result
                    if rerun != "starved" and (code == tiers.TEST_FAILED) != (rerun == "fail"):
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
        as it is lent; return the variables. A REFRESHED kind's token is refreshed where it was
        lent first, by `fab logins account KIND --home <its directory> --validate` (skein's
        tests read the access token and never refresh it; Claude's lasts hours). Refused when
        one cannot be borrowed or refreshed."""
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
            if kind in REFRESHED:
                done = self.sh(["fab", "logins", "account", kind, "--home", str(place), "--validate"], timeout=300)
                try:
                    found = json.loads(done.out.strip().splitlines()[-1])
                except (IndexError, json.JSONDecodeError):
                    found = {"error": (done.err.strip().splitlines() or [f"exit {done.code}"])[-1]}
                if "error" in found:
                    raise logins.Refused(f"{borrowed[-1]} did not refresh: {found['error']}")
            env[variable] = str(path)
        return {**env, **CHEAP.get(profile, {})}

    def give_back(self, borrowed: list[str]) -> None:
        """Return each borrowed login; one that cannot be returned stays lent to its run (custody
        says where it is) and is recorded as an `error` record for a person."""
        for name in borrowed:
            try:
                self._shelf(["return", name])
            except logins.Refused as error:
                log.append("error", path=self.log_path, error=f"login {name} not returned: {error}")

    def check(self, tip: str) -> dict:
        """Check out tip, run the set, record CPU/states, save conclusive history.

        Records are scalar/list fields (docs/design/fab.md, 11): pair diagnostics,
        every selected test's result and CPU, then the run's totals, optional budget
        and verdict. Starved and unobserved tests preserve history. A fault keeps
        the cursor; a crash before saving causes a whole new run on the next cycle.
        After saving, wake the tick once for new, unattributed or recovered tests;
        a failed wake is printed and does not fail the run.
        """
        started_ns = time.time_ns()
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        directory = self.home / STATE / f"{tip[:12]}-{stamp}"
        directory.mkdir(parents=True, exist_ok=True)
        self.sh(["git", "switch", "--detach", "--force", tip], cwd=str(self.repo), check=True)
        self.sh(["git", "clean", "-fd"], cwd=str(self.repo), check=True)
        self.limits, self.diagnostics = cpu.budgets(self.repo)
        self.wrapper = None
        self.wall_s = 0.0
        pairs = [self.pair(profile, tip, directory) for profile in self.tier_set]
        previous = self.state["cursor"]
        landed = suspects(self.repo, previous, tip, sh=self.sh)
        counts = dict.fromkeys((*CONFIRMED, "flake", "recovered", "starved", "unobserved", "passing"), 0)
        hangs = []
        over = []
        total_cpu = sum(pair["cpu_s"] for pair in pairs)
        if "cpu_total_s" in self.limits and total_cpu > self.limits["cpu_total_s"]:
            contributors = ", ".join(
                f"{pair['profile']} {binary} {name}={values['cpu_s']:.6f}s"
                for pair in pairs for (binary, name), values in pair["measurements"].items())
            over.append(f"total CPU {total_cpu:.6f}s > {self.limits['cpu_total_s']}s; tests: {contributors}")
        tests = dict(self.state["tests"])
        states = []
        reds = []
        for pair in pairs:
            log.append("pair", path=self.log_path, tip=tip, profile=pair["profile"],
                       status=pair["status"], cpu_s=pair["cpu_s"], wall_s=pair["wall_s"],
                       budget=[f"{key}={json.dumps(value)}" for key, value in pair["budget"].items()],
                       reason=pair["reason"], log=pair["log"])
            for (binary, name), measured in pair["measurements"].items():
                counts["starved"] += bool(measured["starved"])
                if "cpu_test_s" in self.limits and measured["cpu_s"] > self.limits["cpu_test_s"]:
                    over.append(f"{pair['profile']} {binary} {name}: CPU {measured['cpu_s']:.6f}s > {self.limits['cpu_test_s']}s")
            for case, current, rerun_log in pair["cases"]:
                states.append(current)
                if current != "starved":
                    counts[current] += 1
                measured = pair["measurements"].get((case.binary, case.test), {})
                used = measured.get("cpu_s", 0.0)
                wall = measured.get("wall_s", 0.0)
                possible_hang = current == "starved" and wall > 0 and used < wall * 0.1
                if possible_hang:
                    hangs.append(f"{case.profile} {case.binary} {case.test}: CPU {used:.3f}s / wall {wall:.3f}s")
                last = self.state["tests"].get(case.key)
                good = last["commit"] if last and last["result"] == "pass" else ""
                attribution = {}
                if current in CONFIRMED:
                    reds.append(case.key)
                if current == "unattributed":
                    attribution = {"branches": [item.branch for item in landed if item.branch]}
                elif current == "new":
                    changed = suspects(self.repo, good, tip, sh=self.sh)
                    attribution = {"branches": [item.branch for item in changed if item.branch],
                                   "commits": len(changed)}
                log.append("test", path=self.log_path, tip=tip, profile=case.profile,
                           key=case.key, binary=case.binary, test=case.test, state=current, error=case.error,
                           cpu_s=used, wall_s=wall, starved=bool(measured.get("starved")),
                           incomplete=measured.get("incomplete", 0), possible_hang=possible_hang,
                           log=pair["log"], rerun=rerun_log, good=good, **attribution)
                if current not in ("unobserved", "starved"):
                    tests[case.key] = {"result": "red" if current in CONFIRMED else "pass",
                                       "commit": tip}
        faulted = any(pair["status"] == "faulted" for pair in pairs)
        outcome = "red" if over else verdict(states, faulted)
        freed = slots.remove(slots.sweep_plan(self.repo / "target", started_ns))
        record = log.append(
            "run", path=self.log_path, tip=tip, previous=previous or "",
            branches=[item.branch for item in landed if item.branch], commits=len(landed),
            verdict=outcome, reds=reds, **counts, cpu_s=total_cpu, wall_s=self.wall_s,
            wall_starved=((self.remaining() is not None and self.remaining() <= 0)
                          or any(pair["starved_run"] or pair["status"] == "unobserved" for pair in pairs)),
            possible_hangs=hangs, budget=[f"{key}={value}s" for key, value in self.limits.items()],
            over_budget=over,
            cpu_pairs=[f"{pair['profile']}:{pair['cpu_s']:.6f}:{pair['wall_s']:.6f}" for pair in pairs],
            pairs=[f'{pair["profile"]}:{pair["status"]}:{pair["selected"]}:{pair["failed"]}:'
                   f'{pair["seconds"]:.1f}' for pair in pairs],
            faults=[f'{pair["profile"]}: {pair["reason"]}' for pair in pairs
                    if pair["status"] == "faulted"], log=str(directory), freed=freed)
        saved = {"cursor": previous if faulted else tip,
                 "last": {"tip": tip, "verdict": outcome}, "tests": tests}
        atomic.write(self.state_path, json.dumps(saved, sort_keys=True) + "\n")
        self.state = saved
        if any(counts[name] for name in ("new", "unattributed", "recovered")):
            reason = (f"after-landing {tip[:12]} new {counts['new']} "
                      f"unattributed {counts['unattributed']} recovered {counts['recovered']}")
            try:
                if not events.wake(reason, sh=self.sh, hosts=self.known):
                    print(f"fab after-landing: wake: not delivered: {reason}", file=sys.stderr)
            except Exception as error:
                print(f"fab after-landing: wake: {error}", file=sys.stderr)
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


def imported(entry: dict) -> dict | None:
    """The log record the dispatcher keeps for one of RECORD's entries, its ev included, or
    None: a `run` becomes tiers.run (tip, verdict, the counts, branches, reds, faults,
    log), a new or unattributed `test` becomes tiers.red (tip, key, state, profile,
    binary, test, error, branches, log, rerun), a recovered `test` becomes
    tiers.recovered (tip, key, profile, binary, test). Omit absent fields for older
    records; anything else is left on the machine. Pure."""
    if entry.get("ev") == "run":
        fields = ("tip", "verdict", *CONFIRMED, "flake", "recovered", "starved", "unobserved", "cpu_s", "wall_s",
                  "wall_starved", "possible_hangs", "budget", "over_budget", "branches", "reds", "faults", "log")
        return {"ev": "tiers.run", **{key: entry[key] for key in fields if key in entry}}
    if entry.get("ev") == "test":
        if entry.get("state") in ("new", "unattributed"):
            fields = ("tip", "key", "state", "profile", "binary", "test", "error", "branches", "log", "rerun")
            return {"ev": "tiers.red", **{key: entry[key] for key in fields if key in entry}}
        if entry.get("state") == "recovered":
            fields = ("tip", "key", "profile", "binary", "test")
            return {"ev": "tiers.recovered", **{key: entry[key] for key in fields if key in entry}}
    return None


def service(slot: int) -> units.Service:
    """UNIT, which runs `fab after-landing run --slot <slot> --live` (the live pairs too, the
    user 11-01) and drains for up to DRAIN."""
    return units.Service(UNIT, "fabrig's slow tiers on each new main", ROLE,
                         (RUN, "run", "--slot", str(slot), "--live"), "after-landing.stop", DRAIN)


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
