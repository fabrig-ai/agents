"""Codex runs as user units on a builder (docs/design/fab.md, 5). Replaces fabrig's codex-run.

`fab codex start BRIEF DIR REPORT [--effort E] [--read-only] [--model M]` starts the unit and
prints `<id> <state>`, as codex-run did, so `fab.run` reads it the same way. The unit runs
`fab codex _exec ID`, which feeds the brief to `codex exec`, keeps its events, and touches
`<state>/ended` when everything is written.
"""

from __future__ import annotations

import argparse
import json
import secrets
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path

from fab import log
from fab.sh import Failed, Runner, run

CAPACITY = "Selected model is at capacity. Please try a different model."
DELAYS = (120, 300, 900)  # seconds before each retry of a turn the model refused for capacity
EFFORTS = ("medium", "high", "xhigh")


def state_root() -> Path:
    """FAB_HOME/codex: one directory per run, named by its id."""
    return log.home() / "codex"


def new_id(now: Callable[[], str] | None = None) -> str:
    """`YYYYMMDDTHHMMSSZ-xxxx`: UTC seconds and four random hex digits."""
    stamp = datetime.fromisoformat((now or log.now)()).astimezone(timezone.utc)
    return stamp.strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(2)


def command(*, effort: str, read_only: bool, model: str | None, last: Path, thread: str | None) -> list[str]:
    """The codex argv: `codex exec`, then `resume` when a thread continues; `-m model` when given;
    `-c model_reasoning_effort=<effort>`; `--sandbox read-only` when read_only, else
    `--dangerously-bypass-approvals-and-sandbox`; `--skip-git-repo-check --json -o <last>`;
    the thread id when resuming; `-` (the prompt on stdin). --sandbox only without resume."""
    argv = ["codex", "exec"]
    if thread:
        argv.append("resume")
    if model is not None:
        argv.extend(["-m", model])
    argv.extend(["-c", f"model_reasoning_effort={effort}"])
    if read_only:
        if not thread:
            argv.extend(["--sandbox", "read-only"])
    else:
        argv.append("--dangerously-bypass-approvals-and-sandbox")
    argv.extend(["--skip-git-repo-check", "--json", "-o", str(last)])
    if thread:
        argv.append(thread)
    return [*argv, "-"]


def start(brief: Path, workdir: Path, report: Path, *, effort: str = "high", read_only: bool = False,
          model: str | None = None, sh: Runner = run) -> tuple[str, Path]:
    """Refuse (ValueError) a relative path, a missing brief or workdir, an existing report or an
    unknown effort. Create the state directory with meta.json (brief, dir, report, effort,
    read_only, model, started), then `systemd-run --user --collect --quiet --unit fab-codex-<id>
    --property=UMask=0077 -- <python3> -I -B <this repo's bin/fab> codex _exec <id>`. Returns
    (id, state directory)."""
    for name, path in (("brief", brief), ("workdir", workdir), ("report", report)):
        if not path.is_absolute():
            raise ValueError(f"{name} must be absolute")
    if not brief.is_file():
        raise ValueError(f"brief is not a file: {brief}")
    if not workdir.is_dir():
        raise ValueError(f"workdir is not a directory: {workdir}")
    if report.exists() or report.is_symlink():
        raise ValueError(f"report already exists: {report}")
    if effort not in EFFORTS:
        raise ValueError(f"effort must be one of {', '.join(EFFORTS)}")
    while True:
        run_id = new_id()
        state = state_root() / run_id
        try:
            state.mkdir(parents=True, mode=0o700)
            break
        except FileExistsError:
            continue
    meta = {"brief": str(brief), "dir": str(workdir), "report": str(report),
            "effort": effort, "read_only": read_only, "model": model, "started": log.now()}
    sibling = state / "meta.json.tmp"
    sibling.write_text(json.dumps(meta) + "\n", encoding="utf-8")
    sibling.replace(state / "meta.json")
    launcher = Path(__file__).resolve().parent.parent / "bin/fab"
    sh(["systemd-run", "--user", "--collect", "--quiet", "--unit", f"fab-codex-{run_id}",
        "--property=UMask=0077", "--", sys.executable, "-I", "-B", str(launcher),
        "codex", "_exec", run_id], check=True)
    return run_id, state


def tokens(events: Sequence[dict]) -> dict[str, int]:
    """Sums of input_tokens, cached_input_tokens and output_tokens over turn.completed usages."""
    totals = dict.fromkeys(("input_tokens", "cached_input_tokens", "output_tokens"), 0)
    for event in events:
        usage = event.get("usage")
        if event.get("type") != "turn.completed" or not isinstance(usage, dict):
            continue
        for key in totals:
            value = usage.get(key, 0)
            if isinstance(value, int):
                totals[key] += value
    return totals


def at_capacity(events: Sequence[dict], stderr: str) -> bool:
    """Whether a turn failed because the model was at capacity (an error or turn.failed event
    whose message is CAPACITY, or CAPACITY in stderr)."""
    if CAPACITY in stderr:
        return True
    for event in events:
        if event.get("type") == "error" and event.get("message") == CAPACITY:
            return True
        error = event.get("error")
        if event.get("type") == "turn.failed" and isinstance(error, dict) and error.get("message") == CAPACITY:
            return True
    return False


def execute(run_id: str, *, sh: Runner = run, sleep: Callable[[float], None] | None = None) -> int:
    """The unit's body. Run the command in the workdir with the brief on stdin, appending stdout
    to events.jsonl and stderr to stderr.log; keep the thread id from the first thread.started
    event in `thread`. On failure at capacity, sleep the next DELAYS entry and resume the thread
    with `Go on with the task: the model was at capacity.`, at most len(DELAYS) times. Then: if
    the report is missing, write it as `Failed: the run wrote no report.` followed by last.md
    (when any); write result.json (exit, tries, tokens, ended); touch `ended` last. Returns the
    codex exit code."""
    state = state_root() / run_id
    meta = json.loads((state / "meta.json").read_text(encoding="utf-8"))
    prompt = Path(meta["brief"]).read_text(encoding="utf-8")
    report = Path(meta["report"])
    last = state / "last.md"
    thread_path = state / "thread"
    thread = thread_path.read_text(encoding="utf-8").strip() if thread_path.exists() else None
    all_events = []
    tries = 0

    def write(path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        sibling = path.with_name(path.name + ".tmp")
        sibling.write_text(text, encoding="utf-8")
        sibling.replace(path)

    with (state / "events.jsonl").open("a+b") as stdout, (state / "stderr.log").open("a+b") as stderr:
        while True:
            tries += 1
            stdout.seek(0, 2)
            stderr.seek(0, 2)
            event_offset, error_offset = stdout.tell(), stderr.tell()
            argv = command(effort=meta["effort"], read_only=meta["read_only"], model=meta["model"],
                           last=last, thread=thread)
            try:
                code = subprocess.run(argv, cwd=meta["dir"], input=prompt.encode("utf-8"),
                                      stdout=stdout, stderr=stderr).returncode
            except OSError as error:
                code = 127 if isinstance(error, FileNotFoundError) else 126
                stderr.write((str(error) + "\n").encode("utf-8"))
            stdout.flush()
            stderr.flush()
            stdout.seek(event_offset)
            events = []
            for line in stdout.read().splitlines():
                try:
                    event = json.loads(line)
                except (ValueError, UnicodeDecodeError):
                    continue
                if isinstance(event, dict):
                    events.append(event)
            all_events.extend(events)
            stderr.seek(error_offset)
            errors = stderr.read().decode("utf-8", errors="replace")
            if not thread:
                thread = next((event["thread_id"] for event in events
                               if event.get("type") == "thread.started"
                               and isinstance(event.get("thread_id"), str) and event["thread_id"]), None)
                if thread:
                    write(thread_path, thread + "\n")
            if code == 0 or tries > len(DELAYS) or not thread or not at_capacity(events, errors):
                break
            (sleep or time.sleep)(DELAYS[tries - 1])
            prompt = "Go on with the task: the model was at capacity."
    if not report.exists():
        message = "Failed: the run wrote no report.\n"
        if last.exists():
            message += last.read_text(encoding="utf-8", errors="replace")
        write(report, message)
    result = {"exit": code, "tries": tries, "tokens": tokens(all_events), "ended": log.now()}
    write(state / "result.json", json.dumps(result) + "\n")
    write(state / "ended", "")
    return code


def main(argv: list[str]) -> int:
    """`fab codex start ...` (prints `<id> <state>`; exit 2 on a refusal with its reason) and
    `fab codex _exec ID` (the unit's entry; exits with execute's code)."""
    class Parser(argparse.ArgumentParser):
        def error(self, message):
            raise ValueError(message)

    parser = Parser(prog="fab codex", description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    launch = actions.add_parser("start")
    launch.add_argument("brief", type=Path)
    launch.add_argument("workdir", type=Path)
    launch.add_argument("report", type=Path)
    launch.add_argument("--effort", choices=EFFORTS, default="high")
    launch.add_argument("--read-only", action="store_true")
    launch.add_argument("--model")
    actions.add_parser("_exec").add_argument("run_id")
    try:
        args = parser.parse_args(argv)
        if args.action == "_exec":
            return execute(args.run_id)
        run_id, state = start(args.brief, args.workdir, args.report, effort=args.effort,
                              read_only=args.read_only, model=args.model, sh=run)
        print(f"{run_id} {state}")
        return 0
    except SystemExit as error:
        return error.code
    except (OSError, ValueError, Failed) as error:
        print("fab codex: " + " ".join(str(error).splitlines()), file=sys.stderr)
        return 2
