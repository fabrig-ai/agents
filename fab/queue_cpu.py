"""Queue CPU reports, without CPU verdicts (docs/design/landing.md, 2; after-landing.md, 2).

The queue owns selection and heavy's lane. The shared collector owns measurement
and timeout reconciliation; this adapter groups its verified tests by package.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import re
import shlex
import time
import tomllib
import xml.etree.ElementTree as ET
from collections.abc import Sequence

from fab import atomic, cpu, gate
from fab.sh import Runner, run

# Mirror the package clauses of the checkout's root default/fuzzy filters, not
# today's workspace membership. In particular binary ids need not name a package.
TREE_PATTERNS = {
    "skein": r"^(skein-.*|forgejo-conformance|github-conformance)$",
    "smith": r"^smith(-.*|$)",
    "jig": r"^jig(-.*|$)",
    "temper": r"^(temper(-.*|$)|git-transcripts)$",
    "fabrig": r"^fabrig-boundary$",
}
PROFILES = ("default", "fuzzy")
KEYS = {"cpu_suite_s", "cpu_test_s"}


def tree(package: str) -> str:
    for name, pattern in TREE_PATTERNS.items():
        if re.fullmatch(pattern, package):
            return name
    raise ValueError(f"no gate tree for package: {package}")


def budgets(repo: Path) -> dict:
    path = repo / cpu.BUDGETS
    data = tomllib.loads(path.read_text()).get("gate", {}) if path.exists() else {}
    if not isinstance(data, dict) or data.keys() - TREE_PATTERNS.keys():
        raise ValueError("invalid gate budget trees")
    for name, profiles in data.items():
        if not isinstance(profiles, dict) or profiles.keys() - set(PROFILES):
            raise ValueError(f"invalid gate.{name} budget profiles")
        for profile, limits in profiles.items():
            if not isinstance(limits, dict) or limits.keys() - KEYS:
                raise ValueError(f"invalid gate.{name}.{profile} budget keys")
            for key, value in limits.items():
                if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                    raise ValueError(f"gate.{name}.{profile}.{key} must be finite positive seconds")
    return data


def summarize(directory: Path, profile: str, measured: dict, full: bool, limits: dict) -> list[dict]:
    inventory = json.loads((directory / "inventory.json").read_text())
    owners = {(binary, test): tree(package) for package, binary, test in inventory}
    cases = cpu.cases(directory, profile, measured)
    trees = {name: dict(profile=profile, tree=name, full=full, cpu_s=0.0,
                        test_wall_s=0.0, tests=0, passed=0, failed=0, starved=0,
                        unobserved=0, incomplete=0, top_cpu=[], budget=limits.get(name, {}).get(profile, {}),
                        over=[]) for name in TREE_PATTERNS}
    for case in cases:
        group = trees[owners[case.binary, case.test]]
        if case.result == "skipped":
            group["unobserved"] += 1
        else:
            group["tests"] += 1
            group[{"pass": "passed", "fail": "failed", "starved": "starved"}[case.result]] += 1
    for test in measured["tests"]:
        group = trees[owners[test["binary_id"], test["test_name"]]]
        group["cpu_s"] += test["cpu_s"]
        group["test_wall_s"] += test["wall_s"]
        group["incomplete"] += test["incomplete"]
        group["top_cpu"].append(test)
        budget = group["budget"]
        if "cpu_test_s" in budget and test["cpu_s"] > budget["cpu_test_s"]:
            group["over"].append(f"test {test['binary_id']} {test['test_name']}: "
                                 f"{test['cpu_s']:.6f}s > {budget['cpu_test_s']}s")
    for group in trees.values():
        budget = group["budget"]
        if full and "cpu_suite_s" in budget and group["cpu_s"] > budget["cpu_suite_s"]:
            group["over"].append(f"suite: {group['cpu_s']:.6f}s > {budget['cpu_suite_s']}s")
        group["top_cpu"] = sorted(group["top_cpu"], key=lambda test: (
            -test["cpu_s"], test["binary_id"], test["test_name"]))[:10]
        # Unset CPU budgets have no verdict. Partial suite totals have none either.
        group["verdict"] = ("over" if group["over"] else "within" if "cpu_test_s" in budget or
                            full and "cpu_suite_s" in budget else None)
    return list(trees.values())


def gate_report(directory: Path, profile: str, measured: dict) -> Path:
    """Give red classification the reconciled cases, preserving the collector's raw JUnit.

    A global-timeout abort looks like a failure in raw JUnit; the collector's
    signal/pending evidence can establish that it was starved instead.
    """
    cases = cpu.cases(directory, profile, measured)
    root = ET.Element("testsuites", tests=str(len(cases)))
    suites = {}
    for case in cases:
        suite = suites.setdefault(case.binary, ET.Element("testsuite", name=case.binary))
        element = ET.SubElement(suite, "testcase", name=case.test)
        if case.result in ("fail", "starved"):
            ET.SubElement(element, "failure", type="test timeout" if case.result == "starved"
                          else "test failure").text = case.error
        elif case.result == "skipped":
            ET.SubElement(element, "skipped")
    root.extend(suites.values())
    report = directory / "gate-junit.xml"
    atomic.write(report, ET.tostring(root, encoding="unicode"))
    return report


def run_steps(steps: Sequence[gate.Step], log: Path, record: dict, *,
              lane: str = "gate", sh: Runner = run) -> tuple[list[gate.StepResult], dict[str, Path]]:
    """Run queue checks; build the wrapper lazily once, retaining each profile's records.

    cpu_trees holds JSON strings because fab's event log permits only scalar fields
    and lists of scalars. Each string has named totals, counts, optional budgets and
    at most ten tests. Raw collector records live under the unique batch directory.
    The wrapper uses lane ("gate" by default); other steps keep gate.run_steps'
    exit checks and timeout.
    """
    outcomes, reports = [], {}
    directory = log.with_suffix("")
    wrapper = None
    for step in steps:
        if step.name not in PROFILES:
            outcomes += gate.run_steps([step], log, sh=sh)
        else:
            repo = Path(step.cwd)
            if wrapper is None:
                directory.mkdir(parents=True, exist_ok=False)
                wrapper = cpu.build_wrapper(repo, directory, lane=lane, sh=sh)
            target = directory / step.name
            atomic.extend(log, f"\n[{step.name}] {shlex.join(step.argv)} (cwd {step.cwd})\n")
            started = time.monotonic()
            code, measured = cpu.collect(repo, step.name, list(step.argv), target, wrapper, sh=sh)
            atomic.extend(log, target.with_suffix(".log").read_text())
            groups = summarize(target, step.name, measured, record["selection"] == "full", budgets(repo))
            reports[step.name] = gate_report(target, step.name, measured)
            record.setdefault("cpu_trees", []).extend(json.dumps(group, separators=(",", ":")) for group in groups)
            for group in groups:
                atomic.extend(log, f"{step.name}/{group['tree']}: CPU {group['cpu_s']:.6f}s, "
                              f"test wall {group['test_wall_s']:.6f}s, {group['tests']} tests, "
                              f"passed {group['passed']}, failed {group['failed']}, starved {group['starved']}, "
                              f"unobserved {group['unobserved']}, "
                              f"{'full' if group['full'] else 'partial'}; "
                              f"{group['verdict'] or 'no CPU verdict'}\n")
                for over in group["over"]:
                    atomic.extend(log, f"{step.name}/{group['tree']}: over {over} (report only)\n")
            # CPU never adds a red. Starvation may clear only nextest's test-failed
            # exit, and only when no independently observed failure remains.
            failed = measured["failures"] or any(group["failed"] for group in groups)
            starved = measured["suite"]["starved_run"] or any(group["starved"] for group in groups)
            green = not failed and (code in (0, gate.NO_TESTS) or code == 100 and starved)
            outcomes.append(gate.StepResult(step.name, step.argv, code, green, time.monotonic() - started))
        if not outcomes[-1].green:
            break
    return outcomes, reports
