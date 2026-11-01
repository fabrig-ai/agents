"""Reds classed before anyone hears them (docs/design/fab-landing.md, 3).

The queue's test steps write nextest's JUnit (`with_junit`). When one is red, each failed test
that passed in the precheck of every branch of the batch runs once more alone, in the gate lane,
before any bisection (`classify`). All passing, the red is collateral: nobody is rejected and the
batch goes again. One failing again, or anything that cannot be classed, and the red stands as
the batch's, as before.
"""

from __future__ import annotations

import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from fab import atomic, gate, nextest, receipts as prechecks, tiers
from fab.gate import Step, StepResult
from fab.nextest import Case
from fab.sh import Runner, run

STEPS = ("default", "fuzzy")  # the gate's test steps; each step's name is its nextest profile
RETRIES = 5  # the most failed tests one red retries; with more, the red stands
LIMIT = 2  # the collateral reds one tip may have; its next red stands


@dataclass(frozen=True)
class Verdict:
    collateral: bool
    tests: tuple[str, ...]  # the step's failed tests, "<binary> <test>" in JUnit order; () unread
    reason: str  # why the red stands; "" when collateral
    retries: tuple[StepResult, ...]  # the retries run, in order


def overlay_text(repo: Path, profile: str, report: Path) -> str:
    """The `--config-file` text that has nextest profile write its JUnit to report: the text of
    repo / fab.tiers.NEXTEST_CONFIG ("" when the file is missing), with a line `[profile.default]`
    appended after a newline when profile is "default" and tomllib finds no profile.default in
    it (nextest's default profile need not be written), then fab.nextest.overlay(that text,
    profile, report). ValueError from tomllib or overlay propagates."""
    config = repo / tiers.NEXTEST_CONFIG
    text = config.read_text() if config.exists() else ""
    profiles = tomllib.loads(text).get("profile", {})
    if profile == "default" and "default" not in profiles:
        text += "\n[profile.default]\n"
    return nextest.overlay(text, profile, report)


def with_junit(steps: Sequence[Step], repo: Path, directory: Path,
               name: str) -> tuple[list[Step], dict[str, Path]]:
    """steps, in order, with each one named in STEPS made to write its JUnit, and those reports:
    ({step name: directory/<name>-<step>.xml}).

    Per such step: remove a stale report at that path (missing_ok), write overlay_text(repo,
    step, report) to directory/<name>-<step>.toml with fab.atomic.write, and extend the step's
    argv with `--config-file <that toml>`. A step whose overlay_text raises ValueError (a
    nextest config that does not parse) is left as it was and has no report, so its red stands.
    Other steps are unchanged."""
    result, reports = [], {}
    for step in steps:
        if step.name not in STEPS:
            result.append(step)
            continue
        report = directory / f"{name}-{step.name}.xml"
        report.unlink(missing_ok=True)
        try:
            text = overlay_text(repo, step.name, report)
        except ValueError:
            result.append(step)
            continue
        config = directory / f"{name}-{step.name}.toml"
        atomic.write(config, text)
        result.append(Step(step.name, (*step.argv, "--config-file", str(config)), step.cwd))
        reports[step.name] = report
    return result, reports


def failed_tests(report: Path, step: str) -> list[str]:
    """The first 20 failed tests in JUnit order, as "<binary> <test>". An unreadable report
    or a step outside STEPS gives []; starved, skipped and passing cases are excluded."""
    if step not in STEPS:
        return []
    try:
        return [f"{case.binary} {case.test}" for case in nextest.junit(report, step)
                if case.result == "fail"][:20]
    except (OSError, ValueError):
        return []


def suspect(case: Case, step: str, receipts: Sequence[dict | None]) -> bool:
    """Whether a test that failed at step may have failed for the batch's load rather than its
    code: receipts, one per branch of the batch, is not empty and fab.receipts.covers(receipt,
    step, case.binary) holds for each."""
    return bool(receipts) and all(prechecks.covers(receipt, step, case.binary)
                                  for receipt in receipts)


def retry_step(repo: Path, failed: StepResult, case: Case, config: Path) -> Step:
    """The step that runs case alone, as failed ran it: Step(f"retry:{failed.name}", argv,
    str(repo)), argv being failed.argv without its last two items when they are `--config-file`
    and a path, then `--config-file <config>` and `-E <fab.nextest.exact_filter(case.binary,
    case.test)>`. Same lane, scope and profile, so nothing is built again. ValueError from
    exact_filter propagates."""
    argv = failed.argv[:-2] if failed.argv[-2:-1] == ("--config-file",) else failed.argv
    return Step(f"retry:{failed.name}", (*argv, "--config-file", str(config), "-E",
                                        nextest.exact_filter(case.binary, case.test)), str(repo))


def classify(repo: Path, failed: StepResult, report: Path | None, receipts: Sequence[dict | None],
             log: Path, *, name: str, sh: Runner = run) -> Verdict:
    """Class a red of the queue's checks, failed being the red result (the last run_steps gave),
    report its JUnit (with_junit's, or None), receipts the batch's branches' (fab.receipts.load
    of each merged tip, in merge order) and log the batch's detail log.

    The red stands, nothing run, with this reason, at the first that holds:
    - failed.name is not in STEPS: `step <name>`;
    - failed.code is not fab.tiers.TEST_FAILED: `exit <code>`;
    - report is None: `no junit`; fab.nextest.junit(report, failed.name) raises: `junit: <error>`;
    - no case failed: `no failed test`; more than RETRIES did: `<n> tests failed`;
    - a failed case is not suspect(case, failed.name, receipts): `<binary> <test> not
      prechecked`.
    tests holds the failed cases as soon as the JUnit is read.

    Otherwise each failed case, in JUnit order, n counting from 1: config and report are
    <report's directory>/<name>-<step>-<n>.toml and .xml; remove a stale report, write
    overlay_text(repo, failed.name, report) to config, and run retry_step(repo, failed, case,
    config) through fab.gate.run_steps([step], log, sh=sh) (its output joins the detail log).
    Its JUnit holding exactly that case passing, with exit 0, passes. Exactly that case failing,
    with exit TEST_FAILED, stands: `<binary> <test> failed alone`, and no later case runs.
    Anything else stands: `retry: <binary> <test>: <what>` (another exit, another case count or
    identity, a ValueError from fab.nextest). Every case passing: collateral, reason "".
    retries holds the result of every retry run."""
    tests = ()

    def stands(reason):
        return Verdict(False, tests, reason, ())

    if failed.name not in STEPS:
        return stands(f"step {failed.name}")
    if failed.code != tiers.TEST_FAILED:
        return stands(f"exit {failed.code}")
    if report is None:
        return stands("no junit")
    try:
        cases = [case for case in nextest.junit(report, failed.name) if case.result == "fail"]
    except ValueError as error:
        return stands(f"junit: {error}")
    tests = tuple(f"{case.binary} {case.test}" for case in cases)
    if not cases:
        return stands("no failed test")
    if len(cases) > RETRIES:
        return stands(f"{len(cases)} tests failed")
    for case, identity in zip(cases, tests):
        if not suspect(case, failed.name, receipts):
            return stands(f"{identity} not prechecked")
    return _retry(repo, failed, cases, report.parent, log, name=name, sh=sh)


def _retry(repo: Path, failed: StepResult, cases: Sequence[Case], directory: Path,
           log: Path, *, name: str, sh: Runner) -> Verdict:
    """Retry the covered failures in order; stop at the first result that cannot pass alone."""
    tests = tuple(f"{case.binary} {case.test}" for case in cases)
    retries = []

    def stands(reason):
        return Verdict(False, tests, reason, tuple(retries))

    for n, (case, identity) in enumerate(zip(cases, tests), 1):
        retry_report = directory / f"{name}-{failed.name}-{n}.xml"
        config = retry_report.with_suffix(".toml")
        try:
            retry_report.unlink(missing_ok=True)
            atomic.write(config, overlay_text(repo, failed.name, retry_report))
            step = retry_step(repo, failed, case, config)
            retried, = gate.run_steps([step], log, sh=sh)
            retries.append(retried)
            if retried.code not in (0, tiers.TEST_FAILED):
                return stands(f"retry: {identity}: exit {retried.code}")
            ran = nextest.junit(retry_report, failed.name)
            if len(ran) != 1:
                return stands(f"retry: {identity}: {len(ran)} cases")
            if ran[0].key != case.key:
                return stands(f"retry: {identity}: different test")
            if retried.code == tiers.TEST_FAILED and ran[0].result == "fail":
                return stands(f"{identity} failed alone")
            if retried.code != 0 or ran[0].result != "pass":
                return stands(f"retry: {identity}: exit {retried.code}, {ran[0].result}")
        except ValueError as error:
            return stands(f"retry: {identity}: {error}")
    return Verdict(True, tests, "", tuple(retries))
