"""After landing: fabrig's slow tiers on each new main, reds confirmed and recorded
(docs/design/fab.md, 11).

Runs on a builder in one slot claimed for it. Each cycle fetches main; a new tip gets one run
of the tier set, each failed test is run again alone, and every test that is not plainly
passing is classified against its own history. Verdicts are records in
FAB_HOME/after-landing.jsonl, which the dispatcher and the reports read over ssh; the cursor
and the history are FAB_HOME/after-landing/state.json.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from fab.sh import Runner, run

# The pairs every tip gets, in order. A profile is enrolled only by adding it here: not the
# live pairs (real providers, the user's sign-ins) nor process-temper (its owner's).
TIER_SET = ("exhaustive-skein", "qa-skein", "qa-smith", "qa-jig", "process-jig",
            "browser-skein", "browser-jig", "browser-temper", "qa-temper")
RUN = "after-landing"  # the claim's run and task: `fab slot claim N after-landing after-landing`
RECORD = "after-landing.jsonl"  # under FAB_HOME
STATE = "after-landing"  # FAB_HOME/after-landing/: state.json and one directory per run
# A queue merge on main's first parent: fab's queue writes `Merge <draft>/<task>`, the old
# queue `Merge ready/<draft>/<task>`.
MERGE = re.compile(r"Merge (?:ready/)?([^/\s]+/[^/\s]+)")
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
    raise NotImplementedError


def state(first: str, rerun: str | None, last: dict | None) -> str:
    """A test's state at a tip, from its first result there ("pass", "fail" or "skipped"), its
    rerun alone ("pass" or "fail"; None when it was not rerun) and its history entry (last:
    {"result": "pass" or "red", "commit": ...}, None when it never executed).
    skipped: "unobserved". pass: "recovered" when last was red, else "passing".
    fail then pass: "flake". fail then fail: "unattributed" with no history, "standing" when
    last was red, "new" when it was pass. ValueError for a fail without a rerun or a rerun
    after a pass or a skip."""
    raise NotImplementedError


def verdict(states: Iterable[str], faulted: bool) -> str:
    """A run's verdict: "red" when any state is CONFIRMED (whatever faulted), else "partial"
    when a pair faulted, else "green"."""
    raise NotImplementedError


class AfterLanding:
    def __init__(self, slot: int, *, home: Path | None = None, sh: Runner = run,
                 tier_set: tuple[str, ...] = TIER_SET):
        """slot: the number of a fab slot (fab.slots.slots_dir() / str(slot)); home: FAB_HOME
        (default fab.log.home()). Load state.json when it exists: {"cursor": the last tip run
        without a faulted pair, or null; "last": {"tip", "verdict"} of the last run, or null;
        "tests": {Case.key: {"result": "pass" or "red", "commit": tip}}}; otherwise start
        from all three empty. ValueError when the slot does not exist or its claim
        (fab.slots.read_claim) is missing or not RUN's: the runner touches only its own slot."""
        raise NotImplementedError

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
        raise NotImplementedError

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

        Then update the state and save it (fab.run._write, sibling and rename): every case of
        a ran pair that executed sets its key's history to "pass" (passing, recovered, flake)
        or "red" (confirmed) with the tip; unobserved ones keep theirs. "last" becomes this
        tip and verdict; the cursor becomes tip only when no pair faulted. A crash before the
        save redoes the run whole at the next cycle."""
        raise NotImplementedError

    def cycle(self) -> bool:
        """In the slot: `git fetch -q origin main`, the tip `git rev-parse origin/main`. Nothing
        to do (False) when the tip is the cursor, or is the last run's tip and that run was
        partial (its suspects stay with the cursor, so the next tip's run covers them).
        Otherwise check(tip) and True."""
        raise NotImplementedError

    def run(self, *, stop: Path, idle: float = 60.0, sleep: Callable[[float], None] | None = None) -> None:
        """Cycle until the file stop exists, sleeping idle seconds after a cycle with nothing to
        do. An exception in a cycle appends an `error` record (error: its text) to
        FAB_HOME/RECORD, and the loop sleeps and goes on."""
        raise NotImplementedError


def main(argv: list[str]) -> int:
    """`fab after-landing run|once --slot N` (run stops at FAB_HOME/after-landing.stop) and
    `fab after-landing log [--since TS]` (RECORD's records at or after TS, one JSON object per
    line, as `fab queue log` prints). Exit 0; 1 with `fab after-landing: <error>` on stderr
    for an OSError, RuntimeError or ValueError (a slot not claimed for RUN); 2 on bad
    arguments."""
    raise NotImplementedError
