"""Reuse the checkout's CPU collector (docs/design/after-landing.md, 2).

collect accepts any nextest command/profile/package selection, including the queue
command. The worker isolates collector cwd and stdout and stays behind fab's runner seam.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
import runpy
import signal
import subprocess
import sys
import tomllib
from dataclasses import replace

# Also executable as an isolated worker by absolute path.
if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fab import atomic, nextest, tiers
from fab.sh import Runner, run
from fab.gate import run_steps

BUDGETS = "tools/tiers/budgets.toml"
TOTAL_KEYS = {"cpu_total_s", "cpu_test_s", "wall_hard_s"}
GLOBAL_TIMEOUT = re.compile(r"^\s*(?:Cancelling|Killing) due to global timeout(?:[:\s]|$)", re.M)


def budgets(repo: Path, path: Path | None = None) -> tuple[dict, dict]:
    """Optional after-landing limits and the unchanged per-pair diagnostic tables.

    No defaults. Retired tables remain diagnostic, so config retirement need not remove
    its historical budget in the same commit. The collector's old schema cannot parse
    after-landing; fab validates this new namespace itself.
    """
    path = path or repo / BUDGETS
    data = tomllib.loads(path.read_text()) if path.exists() else {}
    total = data.pop("after-landing", {})
    if not isinstance(total, dict) or total.keys() - TOTAL_KEYS:
        raise ValueError("invalid after-landing budget keys")
    for name, value in total.items():
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"after-landing.{name} must be finite positive seconds")
    return total, data


def build_wrapper(repo: Path, directory: Path, *, lane: str = "build", sh: Runner = run) -> Path:
    """Build once per tip in its run directory, through heavy; never replace a live wrapper."""
    wrapper = directory / "cpu-wrapper"
    heavy = ["heavy", "--gate"] if lane == "gate" else ["heavy"]
    done = sh([*heavy, "cc", "-std=c11", "-O2", "-static", "-Wall", "-Wextra", "-Werror",
               "tools/tiers/cpu-wrapper.c", "-o", str(wrapper)], cwd=str(repo))
    atomic.write(directory / "cpu-wrapper.log", done.out + done.err)
    if not done.ok:
        raise ValueError(f"CPU wrapper: exit {done.code}")
    return wrapper


def seconds(value: str) -> float:
    """nextest's duration units, including compound durations, for a private wall cap."""
    units = {"ns": 1e-9, "us": 1e-6, "ms": .001, "s": 1, "m": 60, "h": 3600, "d": 86400}
    parts = re.findall(r"([0-9]+(?:\.[0-9]+)?)\s*(ns|us|ms|s|m|h|d)", value)
    if not parts or re.sub(r"[0-9]+(?:\.[0-9]+)?\s*(ns|us|ms|s|m|h|d)\s*", "", value).strip():
        raise ValueError(f"unsupported nextest duration: {value}")
    return sum(float(number) * units[unit] for number, unit in parts)


def cap_wall(path: Path, profile: str, remaining: float | None, collector: dict) -> None:
    if remaining is None:
        return
    data = tomllib.loads(path.read_text())
    selected = data["profile"][profile]
    old = selected.get("global-timeout", data["profile"].get("default", {}).get("global-timeout"))
    limit = min(remaining, seconds(old)) if old is not None else remaining
    selected["global-timeout"] = f"{limit:.9f}s"
    atomic.write(path, collector["toml_config"](data))


def read(directory: Path, profile: str, collector: dict) -> dict:
    """Verified CPU summary, reconciling global-timeout cancellation with observed exits.

    nextest reports global cancellation as an abort, rather than a test timeout. Its
    own cancellation line plus terminated/pending attempts supplies starvation evidence.
    Assertions and other bad exits remain failures, including earlier retry attempts.
    """
    output = (directory / "heavy-output.txt").read_text()
    output = re.sub(r"\x1b\[[0-9;]*m", "", output)
    cancellation = GLOBAL_TIMEOUT.search(output)
    global_timeout = cancellation is not None
    # Nextest reports each completed test before announcing cancellation. Preserve
    # signal failures already reported; only the tests stopped by cancellation starve.
    before = output[:cancellation.start()] if cancellation else ""
    prior_signals = set(re.findall(
        r"(?m)^\s*SIG(?:TERM|KILL)\s+\[[^\]]+\]\s+\([^)]*\)\s+(\S+) (.+)$", before))
    metadata = json.loads((directory / "run.json").read_text())
    if global_timeout:
        metadata["starved"] = True
        atomic.write(directory / "run.json", json.dumps(metadata) + "\n")
    summarize = collector["summary"].__globals__["summarize_records"]

    def reconcile(items, pair, limits, run_info, timeouts, failures):
        if global_timeout or run_info["starved"]:
            cancelled = {(r["profile"], r["binary_id"], r["test_name"], r["attempt"])
                         for r in items if (r["binary_id"], r["test_name"]) not in prior_signals
                         and (r["pending"] or r["signal"] in (signal.SIGTERM, signal.SIGKILL))}
            timeouts = timeouts | cancelled
            # Preserve any independently observed bad exit for this identity.
            bad = {f"{r['binary_id']} {r['test_name']}" for r in items
                   if not r["pending"] and r["exit_code"] != 0
                   and (r["profile"], r["binary_id"], r["test_name"], r["attempt"]) not in timeouts}
            cancelled_names = {f"{key[1]} {key[2]}" for key in cancelled}
            failures = [name for name in failures if name not in cancelled_names or name in bad]
        return summarize(items, pair, limits, run_info, timeouts, failures)

    namespace = collector["summary"].__globals__
    namespace["summarize_records"] = reconcile
    try:
        result = collector["summary"](directory, {}, profile)
    finally:
        namespace["summarize_records"] = summarize
    result["global_timeout"] = global_timeout
    return result


def cases(directory: Path, profile: str, measured: dict) -> list[nextest.Case]:
    """JUnit plus started attempts absent from an interrupted JUnit; never invent passes."""
    report = directory / "junit.xml"
    parsed = nextest.junit(report, profile) if report.exists() else []
    known = {(case.binary, case.test): case for case in parsed}
    failures = set(measured["failures"])
    for item in measured["tests"]:
        key = item["binary_id"], item["test_name"]
        case = known.get(key, nextest.Case(profile, *key, "starved", "run stopped"))
        if f"{key[0]} {key[1]}" in failures:
            case = replace(case, result="fail")
        elif item["starved"]:
            case = replace(case, result="starved")
        known[key] = case
    inventory = directory / "inventory.json"
    if inventory.exists():
        for _, binary, test in json.loads(inventory.read_text()):
            known.setdefault((binary, test), nextest.Case(profile, binary, test, "skipped", "run stopped"))
    return list(known.values())


def collect(repo: Path, profile: str, command: list[str], directory: Path, wrapper: Path,
            *, wall_hard_s: float | None = None, sh: Runner = run) -> tuple[int, dict]:
    """Run a selected nextest command with the checkout's collector; no implicit wall timeout.

    command already contains heavy and any env/package selection. This function is shared
    with queue CPU integration; it neither chooses packages nor applies budgets.
    """
    request = dict(profile=profile, command=command, directory=str(directory),
                   wrapper=str(wrapper), wall_hard_s=wall_hard_s)
    if directory.exists() and any(directory.iterdir()):
        raise ValueError(f"CPU directory must be empty: {directory}")
    done = sh([sys.executable, "-I", "-B", str(Path(__file__).resolve())],
              cwd=str(repo), input=json.dumps(request))
    atomic.write(directory.with_suffix(".log"), done.out + done.err)
    summary = directory / "summary.json"
    if not summary.exists():
        raise ValueError(f"CPU collector exit {done.code}: {(done.err or done.out)[-500:]}")
    return done.code, json.loads(summary.read_text())


def run_pair(repo: Path, target: tiers.Pair, extra: list[str], log: Path, *,
             directory: Path, wrapper: Path, wall_hard_s: float | None,
             sh: Runner = run, env: dict | None = None) -> tuple[int, dict]:
    """Keep fab's prerequisites, replacing only its nextest step with collection."""
    output = tiers.target_directory(repo, sh=sh) if tiers.bundle(target) is not None or any(
        binary.env for binary in target.binaries) else None
    commands = tiers.steps(repo, target, extra, output, env)
    prerequisites = run_steps(commands[:-1], log, sh=sh)
    if prerequisites and not prerequisites[-1].green:
        return tiers.REFUSED, {}
    code, measured = collect(repo, target.profile, list(commands[-1].argv), directory,
                             wrapper, wall_hard_s=wall_hard_s, sh=sh)
    atomic.extend(log, directory.with_suffix(".log").read_text())
    return code, measured


def worker(request: dict) -> int:
    profile = request["profile"]
    directory = Path(request["directory"])
    collector = runpy.run_path("tools/tiers/cpu.py")
    command = list(request["command"])
    config = Path(".config/nextest.toml")
    if "--config-file" in command:
        index = command.index("--config-file")
        config = Path(command[index + 1])
        del command[index:index + 2]
    overlay = collector["prepare"](directory, profile, Path(request["wrapper"]), config)
    cap_wall(directory / "repository.toml", profile, request["wall_hard_s"], collector)
    # An independent inventory distinguishes tests never started after cancellation.
    index = command.index("nextest") + 1
    listing_command = [*command[:index], "list", *command[index + 1:], *overlay,
                       "--message-format", "json", "--color", "never"]
    listing_command = [arg for arg in listing_command if arg != "--no-fail-fast"]
    listing = subprocess.run(listing_command, stdin=subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if listing.returncode:
        raise ValueError(f"nextest inventory exit {listing.returncode}: {listing.stderr}")
    inventory = tiers.listed(listing.stdout)
    atomic.write(directory / "inventory.json", json.dumps(sorted(inventory)) + "\n")
    command = [*command, *overlay, "--retries", "0", "--color", "never",
               "--status-level", "all", "--final-status-level", "fail"]
    # execute calls summary before returning. The adapter also recognizes global-timeout
    # and preserves collector validation; no per-pair limits affect this execution.
    original = collector["execute"].__globals__["summary"]
    def summary(*args, **kwargs):
        return read(directory, profile, {**collector, "summary": original})
    collector["execute"].__globals__["summary"] = summary
    try:
        code = collector["execute"](command, dict(os.environ), directory, profile, {})
        measured = summary()
        atomic.write(directory / "summary.json", json.dumps(measured) + "\n")
        # Preserve infrastructure/setup/bad-command exits even alongside starvation.
        raw = json.loads((directory / "run.json").read_text()).get("returncode", code)
        if raw not in (0, 4, 100):
            return raw
        return 100 if measured["failures"] else 0 if (
            measured["suite"]["starved_run"] or measured["suite"]["starved"]) else code
    finally:
        collector["execute"].__globals__["summary"] = original


if __name__ == "__main__":
    try:
        sys.exit(worker(json.load(sys.stdin)))
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"CPU collector: {error}", file=sys.stderr)
        sys.exit(2)
