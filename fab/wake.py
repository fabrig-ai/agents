"""Events start the tick; the timer is only the backstop (docs/design/tick.md, 6).

Whatever ends work the dispatcher waits for wakes the tick: it appends a reason to the want
file beside the log on the dispatcher's machine (hel8), over ssh from any other machine
(`fab wake REASON...`). A systemd path unit starts the event tick while the file exists, so
a burst of wakes makes one tick after the running one. The tick takes the file under its
lock before it reads anything; at its end it wants another when its own records call for
one. A backstop round, on a 10-minute timer, that finds what only an event explains logs a
note: a lost event.
"""

from __future__ import annotations

import argparse
import os
import re
import shlex
import sys
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

from fab import atomic, hosts as machines, log
from fab.hosts import Host
from fab.sh import Failed, Runner, run, ssh

WANT = "tick.want"  # beside the log: one reason per line; its existence is the wake
TAKEN = ".tick.want.taken"  # the want a tick has taken, beside it, until read
TRIGGERS = ("hand", "event", "backstop")  # what started a tick round
AGAIN = ("run.ended", "branch.landed", "branch.rejected", "question.asked", "question.answered",
         "refusal.settled", "call.finished", "call.parked", "call.answered", "red.settled",
         "finding.settled", "red.closed")  # a round's records that want another
AGAIN_LIMIT = 5  # rounds in a row that may want another with no outside wake between them
EVENT_PATH = "fab-events.path"  # starts EVENT_SERVICE while the want exists
EVENT_SERVICE = "fab-events.service"  # `fab tick --trigger event`
BACKSTOP_TIMER = "fab-backstop.timer"  # starts BACKSTOP_SERVICE every 10 minutes
BACKSTOP_SERVICE = "fab-backstop.service"  # `fab tick --trigger backstop`
BACKSTOP = "*:0/10"  # the backstop's OnCalendar (the user, 10-30)
TIMEOUT = "10min"  # each tick service's TimeoutStartSec, as the transient tick had
OLD_TIMER = "fab-tick.timer"  # the transient 2-minute tick the units replace


def want_path(log_path: Path | None = None) -> Path:
    """The want file: WANT beside the log, log_path (default fab.log.default_path()). Pure."""
    return (log_path if log_path is not None else log.default_path()).with_name(WANT)


def want(reason: str, *, path: Path | None = None) -> Path:
    """Wake the tick on this machine: append reason as one line to path (default
    want_path()), creating it and its parents; return path.

    reason's line breaks become spaces and it is stripped; a blank reason is `-`. The line
    goes in one os.write on a descriptor opened O_WRONLY | O_APPEND | O_CREAT (mode 0o600), so
    concurrent wakers never lose each other's lines and never replace the file: this is the
    one file fab appends to without a sibling and a rename, as the log is. The caller is on
    the dispatcher's machine (calls, fab land, fab page answer, the tick); any other machine
    calls wake."""
    path = path if path is not None else want_path()
    line = " ".join(reason.splitlines()).strip() or "-"
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(descriptor, (line + "\n").encode("utf-8"))
    finally:
        os.close(descriptor)
    return path


def take(path: Path | None = None) -> list[str] | None:
    """Take the want at path (default want_path()): None when there is none; else rename it
    to TAKEN beside it (replacing a TAKEN a crashed tick left), read that, remove it, and
    return its stripped non-blank lines in order ([] for an empty want).

    The rename comes first, so a wake that arrives while the taken file is read makes a new
    want, and the path unit starts another round for it. The tick calls this first under
    its lock, before it reads the log or any machine."""
    path = path if path is not None else want_path()
    taken = path.with_name(TAKEN)
    try:
        path.replace(taken)
    except FileNotFoundError:
        return None
    try:
        return [line.strip() for line in taken.read_text(encoding="utf-8").splitlines()
                if line.strip()]
    finally:
        taken.unlink()


def wake(reason: str, *, sh: Runner = run, hosts: Mapping[str, Host] | None = None,
         here: str | None = None) -> bool:
    """Wake the tick from wherever this runs; return whether the wake was delivered.

    hosts defaults to fab.hosts.load(); this machine is fab.hosts.this(hosts, here). When it
    has the role dispatcher: want(reason), True. Otherwise the dispatcher is the first host
    by name with that role (none: False, nothing run), and the wake is one
    sh(ssh(<its ssh>, ["fab", "wake", reason])), True when it exits 0. Never raises for a
    failed ssh: a lost wake waits for the backstop. A machine not in hosts counts as not the
    dispatcher."""
    hosts = machines.load() if hosts is None else hosts
    local = machines.this(hosts, here)
    if local is not None and "dispatcher" in local.roles:
        want(reason)
        return True
    dispatcher = next((hosts[name] for name in sorted(hosts)
                       if "dispatcher" in hosts[name].roles), None)
    if dispatcher is None:
        return False
    try:
        return sh(ssh(dispatcher.ssh, ["fab", "wake", reason])).ok
    except (OSError, Failed):
        return False


def wanted(records: Iterable[dict]) -> list[str]:
    """The AGAIN types among records' ev, each once, in the order they first appear. Pure.

    records are those the log gained during a round: one of these means the round ended
    work the next decision depends on (a run ended, a branch landed or was refused, a
    question asked or answered, a call's chain finished or parked)."""
    return list(dict.fromkeys(record.get("ev") for record in records if record.get("ev") in AGAIN))


def again(kinds: Sequence[str], taken: Sequence[str]) -> str | None:
    """The reason a round whose records hold kinds (wanted's, not empty) wants another under,
    or None when AGAIN_LIMIT rounds in a row already have. Pure.

    The reason is `tick <n>: <kinds joined by ", ">`. n is 1 + the largest n of the taken
    reasons when taken is not empty and every one of them is a tick's own (`tick <n>: ...`,
    n a positive integer); otherwise 1 (an outside wake, a hand round, a backstop round).
    None when n would exceed AGAIN_LIMIT: a chain that long is a fault, not work."""
    matches = [re.fullmatch(r"tick ([1-9][0-9]*): .*", reason) for reason in taken]
    number = 1 + max(int(match[1]) for match in matches) if matches and all(matches) else 1
    return f"tick {number}: {', '.join(kinds)}" if number <= AGAIN_LIMIT else None


def lost(taken: Sequence[str] | None, records: Iterable[dict]) -> list[str]:
    """What a backstop round found that only an event explains, in this order: `wake
    <reason>` per taken reason (a want no event round started for); then, in records' order,
    `run.ended <run>` per run.ended record (a builder's wake did not arrive) and `<ev> <task>`
    per record carrying queue_ts, falling back to branch when task is absent (a record
    imported from the queue, whose wake did not arrive). Imported tiers.red and
    tiers.recovered records (carrying al_ts) follow as one `after-landing: <n> records`
    count, regardless of the import cursor, so the first import does not list its history.
    records are those the log gained during the round.
    A run that ends just as the backstop collects it reads the same;
    that race is rare. Pure."""
    found = [f"wake {reason}" for reason in taken or ()]
    after_records = 0
    for record in records:
        if record.get("ev") == "run.ended":
            found.append(f"run.ended {record['run']}")
        if record.get("ev") in ("tiers.red", "tiers.recovered") and "al_ts" in record:
            after_records += 1
        if "queue_ts" in record:
            found.append(f"{record['ev']} {record.get('task', record.get('branch'))}")
    if after_records:
        found.append(f"after-landing: {after_records} records")
    return found


def settle(trigger: str, taken: Sequence[str] | None, records: Sequence[dict], *,
           path: Path | None = None, log_path: Path | None = None) -> list[str]:
    """Close a tick round and return the lines the tick prints for it, in order.

    trigger is one of TRIGGERS (ValueError otherwise); taken what take gave at the round's
    start; records what the log gained since (other writers' records included).
    1. trigger backstop: when lost(taken, records) is not empty, log a note (log_path) with
       text `lost event: <its items joined by "; ">`; the line is `lost - <that text>`.
    2. kinds = wanted(records). When not empty: reason = again(kinds, taken or []); a reason
       is want(reason, path=path) with the line `again - <reason>`; None logs a note with
       text `tick: <AGAIN_LIMIT> rounds in a row wanted another; the next waits for an event
       or the backstop` and the line `again - stopped`.
    The note of step 1 is not in records and wants nothing."""
    if trigger not in TRIGGERS:
        raise ValueError(f"unknown tick trigger {trigger!r}")
    lines = []
    if trigger == "backstop":
        missing = lost(taken, records)
        if missing:
            text = "lost event: " + "; ".join(missing)
            log.append("note", path=log_path, text=text)
            lines.append("lost - " + text)
    kinds = wanted(records)
    if kinds:
        reason = again(kinds, taken or [])
        if reason is not None:
            want(reason, path=path)
            lines.append("again - " + reason)
        else:
            text = (f"tick: {AGAIN_LIMIT} rounds in a row wanted another; "
                    "the next waits for an event or the backstop")
            log.append("note", path=log_path, text=text)
            lines.append("again - stopped")
    return lines


def units(plan_dirs: Sequence[Path], *, checkout: Path | None = None,
          home: Path | None = None) -> dict[str, str]:
    """The four unit files of the tick on hel8, keyed by name in this order: EVENT_PATH,
    EVENT_SERVICE, BACKSTOP_TIMER, BACKSTOP_SERVICE. Pure.

    checkout is fab's install (default home / "install"); home is FAB_HOME (default
    fab.log.home()). Both and every plan dir are made absolute (Path.absolute, not
    resolved); a path holding a newline, `%`, `$`, `"` or a backslash is a ValueError.
    - EVENT_PATH: `[Unit]` Description `fab: start the tick while an event wants one`;
      `[Path]` PathExists=<home>/WANT and Unit=EVENT_SERVICE; `[Install]`
      WantedBy=default.target.
    - EVENT_SERVICE and BACKSTOP_SERVICE: `[Unit]` Description `fab: the tick, started by an
      event` or `fab: the tick's backstop`; `[Service]` Type=oneshot, TimeoutStartSec=TIMEOUT
      and ExecStart=/usr/bin/bash -lc "<script>", script being, with q = shlex.quote:
      `{ git -C <q checkout> fetch -q origin && git -C <q checkout> checkout -q --detach
      origin/main; } || true; exec <q checkout/bin/fab> tick --trigger <event|backstop>`
      then ` <q plan dir>` per plan dir. A failed fetch still ticks on the code it has, so
      the path unit never retries a want into the start limit for a network fault.
    - BACKSTOP_TIMER: `[Unit]` Description `fab: the tick's backstop, every 10 minutes`;
      `[Timer]` OnCalendar=BACKSTOP and Unit=BACKSTOP_SERVICE; `[Install]`
      WantedBy=timers.target.
    Each file is its sections in that order, one blank line between them, ending with a
    newline."""
    home = (home if home is not None else log.home()).absolute()
    checkout = (checkout if checkout is not None else home / "install").absolute()
    directories = [directory.absolute() for directory in plan_dirs]
    for path in (home, checkout, *directories):
        if any(character in str(path) for character in '\n\r%$"\\'):
            raise ValueError(f"invalid unit path {str(path)!r}")
    q = shlex.quote
    prefix = (f"{{ git -C {q(str(checkout))} fetch -q origin && "
              f"git -C {q(str(checkout))} checkout -q --detach origin/main; }} || true; "
              f"exec {q(str(checkout / 'bin/fab'))} tick --trigger ")
    plans = "".join(" " + q(str(directory)) for directory in directories)
    files = {EVENT_PATH: ("[Unit]\nDescription=fab: start the tick while an event wants one\n\n"
                          f"[Path]\nPathExists={home / WANT}\nUnit={EVENT_SERVICE}\n\n"
                          "[Install]\nWantedBy=default.target\n")}
    for name, description, trigger in (
            (EVENT_SERVICE, "fab: the tick, started by an event", "event"),
            (BACKSTOP_SERVICE, "fab: the tick's backstop", "backstop")):
        script = (prefix + trigger + plans).replace('"', '\\"')
        files[name] = (f"[Unit]\nDescription={description}\n\n"
                       f"[Service]\nType=oneshot\nTimeoutStartSec={TIMEOUT}\n"
                       f'ExecStart=/usr/bin/bash -lc "{script}"\n')
    files[BACKSTOP_TIMER] = ("[Unit]\nDescription=fab: the tick's backstop, every 10 minutes\n\n"
                             f"[Timer]\nOnCalendar={BACKSTOP}\nUnit={BACKSTOP_SERVICE}\n\n"
                             "[Install]\nWantedBy=timers.target\n")
    return {name: files[name] for name in
            (EVENT_PATH, EVENT_SERVICE, BACKSTOP_TIMER, BACKSTOP_SERVICE)}


def install(plan_dirs: Sequence[Path], *, sh: Runner = run, directory: Path | None = None,
            checkout: Path | None = None) -> list[Path]:
    """Install the tick's units on this machine (hel8) and return the files written.

    directory defaults to $XDG_CONFIG_HOME/systemd/user, or ~/.config/systemd/user without
    it. In this order: units(plan_dirs, checkout=checkout) (its ValueError before anything
    is done); each file through fab.atomic.write into directory; `systemctl --user
    daemon-reload`; `systemctl --user enable --now EVENT_PATH BACKSTOP_TIMER` (both
    check=True); then `systemctl --user stop OLD_TIMER` (check=False: the transient tick may
    be gone; a tick it started finishes on its own and shares the tick's lock)."""
    files = units(plan_dirs, checkout=checkout)
    if directory is None:
        config = os.environ.get("XDG_CONFIG_HOME")
        directory = (Path(config) if config else Path.home() / ".config") / "systemd/user"
    paths = []
    for name, text in files.items():
        path = directory / name
        atomic.write(path, text)
        paths.append(path)
    sh(["systemctl", "--user", "daemon-reload"], check=True)
    sh(["systemctl", "--user", "enable", "--now", EVENT_PATH, BACKSTOP_TIMER], check=True)
    sh(["systemctl", "--user", "stop", OLD_TIMER], check=False)
    return paths


def main(argv: list[str]) -> int:
    """`fab wake REASON...` and `fab wake --install [PLAN_DIR...]`.

    REASON's words joined by single spaces go to wake(reason); exit 0 when delivered, else 1
    with `fab wake: not delivered: <reason>` on stderr. No REASON without --install: usage
    on stderr, exit 2. With --install, the positionals are plan dirs: install(those), print
    each path written, then `enabled <EVENT_PATH> <BACKSTOP_TIMER>`; exit 0. An OSError,
    ValueError or fab.sh.Failed prints `fab wake: <error on one line>` on stderr, exit 1."""
    parser = argparse.ArgumentParser(prog="fab wake", description=__doc__)
    parser.add_argument("--install", action="store_true")
    parser.add_argument("words", nargs="*")
    try:
        args = parser.parse_args(argv)
        if not args.install and not args.words:
            parser.error("a reason is required without --install")
        if args.install:
            for path in install([Path(word) for word in args.words]):
                print(path)
            print(f"enabled {EVENT_PATH} {BACKSTOP_TIMER}")
            return 0
        reason = " ".join(args.words)
        if wake(reason):
            return 0
        print(f"fab wake: not delivered: {reason}", file=sys.stderr)
        return 1
    except SystemExit as error:
        return error.code
    except (OSError, ValueError, Failed) as error:
        print("fab wake: " + " ".join(str(error).splitlines()), file=sys.stderr)
        return 1
