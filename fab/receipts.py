"""Precheck receipts at the queue (docs/design/fab-landing.md, 3).

Precheck writes a receipt on the builder (fab.precheck). The dispatcher carries it to the gate
when it readies the tip (`deliver`, received by `fab queue receipt`), and the queue reads it
there (`load`): a batch of one lands on a receipt that names its tip and main (`reusable`), and
a failing test its precheck ran green is retried before the red counts (`covers`, fab.reds).
A receipt that is missing or does not parse is no receipt: the queue checks the tip in full.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from pathlib import Path

from fab import atomic, landing_report, log
from fab.hosts import Host
from fab.run import remote_home
from fab.sh import Runner, run, ssh

DIRECTORY = "receipts"  # FAB_HOME/receipts/<tip>.json on the gate
SHA = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?")  # a full commit id, SHA-1 or SHA-256
OUTCOMES = ("green", "red", "conflict")  # a receipt's outcomes, as fab.precheck writes them
RUN_KINDS = ("implement", "repair", "rebase")  # the runs whose slot prechecks the branch


def path(home: Path, tip: str) -> Path:
    """home/DIRECTORY/<tip>.json, home being FAB_HOME; ValueError when tip does not fully match
    SHA, so no tip names a path outside DIRECTORY."""
    if not isinstance(tip, str) or SHA.fullmatch(tip) is None:
        raise ValueError("tip must be a full lowercase SHA")
    return home / DIRECTORY / f"{tip}.json"


def parse(text: str, tip: str) -> dict:
    """The receipt in text, checked, as fab.precheck writes it: a JSON object whose `tip` equals
    tip; `tip` and `main` strings fully matching SHA; `outcome` one of OUTCOMES; `selection`
    "full", "docs" or a list of strings; `steps` a list of strings. Return the object as it is,
    its other keys (log, at) kept. ValueError naming the first field that fails, or the JSON
    error."""
    receipt = json.loads(text)
    if not isinstance(receipt, dict):
        raise ValueError("receipt must be a JSON object")
    for field in ("tip", "main"):
        value = receipt.get(field)
        if not isinstance(value, str) or SHA.fullmatch(value) is None:
            raise ValueError(f"{field} must be a full lowercase SHA")
        if field == "tip" and value != tip:
            raise ValueError("tip does not match the requested tip")
    if receipt.get("outcome") not in OUTCOMES:
        raise ValueError("outcome must be green, red or conflict")
    selection = receipt.get("selection")
    if selection not in ("full", "docs") and not (
            isinstance(selection, list) and all(isinstance(name, str) for name in selection)):
        raise ValueError("selection must be full, docs or a list of strings")
    steps = receipt.get("steps")
    if not isinstance(steps, list) or not all(isinstance(step, str) for step in steps):
        raise ValueError("steps must be a list of strings")
    return receipt


def store(home: Path, tip: str, text: str) -> Path:
    """Keep text, a receipt for tip, at path(home, tip) and return that path: parse(text, tip)
    first (its ValueError propagates and nothing is written), then fab.atomic.write the text as
    given."""
    parse(text, tip)
    destination = path(home, tip)
    atomic.write(destination, text)
    return destination


def load(home: Path, tip: str) -> dict | None:
    """The receipt kept for tip: parse of path(home, tip)'s text. None, never an exception, when
    tip is not a SHA, the file is missing or unreadable (OSError, UnicodeDecodeError) or parse
    refuses it."""
    try:
        return parse(path(home, tip).read_text(encoding="utf-8"), tip)
    except (OSError, UnicodeDecodeError, ValueError):
        return None


def reusable(receipt: dict | None, tip: str, main: str) -> bool:
    """Whether a batch of tip alone, merged on main, may land on receipt's checks: receipt is not
    None, its outcome is green, its tip is tip and its main is main."""
    return receipt is not None and receipt.get("outcome") == "green" and \
        receipt.get("tip") == tip and receipt.get("main") == main


def covers(receipt: dict | None, step: str, binary: str) -> bool:
    """Whether receipt shows the tests of nextest binary id binary passing at step: receipt is not
    None and green; a step named step is among its steps (each `name:code:seconds`, split as
    fab.landing_report.steps splits a batch's; a green receipt's steps all passed); and its
    selection is "full" or lists the binary's package, the binary id up to its first "::"
    (`skein-core::wire` and `skein-core` are skein-core's)."""
    if receipt is None or receipt.get("outcome") != "green":
        return False
    if not any(ran.name == step for ran in landing_report.steps(receipt)):
        return False
    selection = receipt.get("selection")
    return selection == "full" or (isinstance(selection, list) and binary.split("::", 1)[0] in selection)


def builder(task_id: str, events: Iterable[dict], hosts: Mapping[str, Host]) -> Host | None:
    """The builder that holds the task's receipts: the host of the task's latest run.started
    whose task is task_id and kind one of RUN_KINDS, when hosts has it with role builder; None
    when there is no such run or host."""
    latest = None
    for event in events:
        if event.get("ev") == "run.started" and event.get("task") == task_id and \
                event.get("kind") in RUN_KINDS:
            latest = event
    host = hosts.get(latest.get("host")) if latest is not None else None
    return host if host is not None and "builder" in host.roles else None


def deliver(task_id: str, tip: str, events: Iterable[dict], hosts: Mapping[str, Host], *,
            sh: Runner = run, log_path: Path | None = None) -> bool:
    """Carry tip's precheck receipt from its builder to the gate, before the tip is readied;
    return whether the gate now holds it. Never raises for a command that fails.

    1. host = builder(task_id, events, hosts); None: False, nothing run.
    2. One ssh to host (fab.sh.ssh): `cat <fab.run.remote_home(host)>/precheck/<tip>.json`. Not
       ok: False and no note (the run did not precheck that tip).
    3. parse(its output, tip); a ValueError: a note `receipt <task_id>: <error>`, False. An
       outcome other than green: False, no note (it is neither reusable nor covers a test).
    4. The gate: the first host by name with role gate; none: a note `receipt <task_id>: no
       gate host`, False. One ssh to it, `fab queue receipt <tip>`, the receipt's text as
       input. Not ok: a note `receipt <task_id>: gate: <the last line of its err, else out>`,
       False. Ok: True.
    Notes are fab.log.append("note", path=log_path, text=...)."""
    host = builder(task_id, events, hosts)
    if host is None:
        return False
    copied = sh(ssh(host.ssh, ["cat", f"{remote_home(host)}/precheck/{tip}.json"]))
    if not copied.ok:
        return False
    try:
        receipt = parse(copied.out, tip)
    except ValueError as error:
        log.append("note", path=log_path, text=f"receipt {task_id}: {error}")
        return False
    if receipt["outcome"] != "green":
        return False
    gate = next((host for host in sorted(hosts.values(), key=lambda host: host.name)
                 if "gate" in host.roles), None)
    if gate is None:
        log.append("note", path=log_path, text=f"receipt {task_id}: no gate host")
        return False
    accepted = sh(ssh(gate.ssh, ["fab", "queue", "receipt", tip]), input=copied.out)
    if not accepted.ok:
        reason = ((accepted.err or accepted.out).strip().splitlines() or [""])[-1]
        log.append("note", path=log_path, text=f"receipt {task_id}: gate: {reason}")
    return accepted.ok
