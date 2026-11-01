"""fab's own long-running user units, written at a deploy on the machines whose role in
fab/hosts.toml wants them (docs/design/landing.md, 2; after-landing.md, 2): the queue on the gate, after landing
on its builder.

A deploy runs each unit's install on every machine. A machine with the role gets the unit and
a restart on the new code; one without it has a unit it finds disabled, so moving the role
moves the unit. A unit disabled by hand is a pause, and a deploy leaves it disabled.
"""

from __future__ import annotations

import getpass
import os
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path

from fab import atomic, hosts as machines, log
from fab.sh import Failed, Runner, run


@dataclass(frozen=True)
class Service:
    name: str  # the unit file's name, `fab-<what>.service`
    description: str  # what it runs, after "fab: "
    role: str  # the fab/hosts.toml role of the machines that run it
    command: tuple[str, ...]  # fab's arguments: the unit runs `<checkout>/bin/fab <command>`
    stop: str  # the file under FAB_HOME whose existence ends the command's loop
    drain: str  # TimeoutStopSec: how long a stop waits for the work in progress


def text(service: Service, *, checkout: Path | None = None, home: Path | None = None) -> str:
    """The unit file of service. Pure.

    checkout is fab's install (default home / "install"), home FAB_HOME (default
    fab.log.home()); both are made absolute, and they or a command argument holding a newline,
    `%`, `$`, `"` or a backslash is a ValueError. The service sets FAB_HOME, removes a stale
    stop file before it starts, and runs `/usr/bin/bash -lc "exec <checkout>/bin/fab
    <command>"` (shell-quoted). A stop drains: ExecStop creates the stop file and waits for the
    main process to end its cycle, up to the drain, after which the rest is interrupted with
    SIGINT so the cycle's cleanup still runs. Restart=on-failure after 60 s;
    WantedBy=default.target."""
    home = (home if home is not None else log.home()).absolute()
    checkout = (checkout if checkout is not None else home / "install").absolute()
    for word in (str(home), str(checkout), *service.command):
        if any(character in word for character in '\n\r%$"\\'):
            raise ValueError(f"invalid unit argument {word!r}")
    q = shlex.quote
    stop = home / service.stop
    command = " ".join(q(word) for word in (str(checkout / "bin/fab"), *service.command))
    return (f"[Unit]\nDescription=fab: {service.description}\n\n"
            f"[Service]\nEnvironment=FAB_HOME={home}\n"
            f"ExecStartPre=/usr/bin/rm -f {stop}\n"
            f'ExecStart=/usr/bin/bash -lc "exec {command}"\n'
            f'ExecStop=/usr/bin/bash -c "touch {q(str(stop))}; '
            'while kill -0 $$MAINPID 2>/dev/null; do sleep 5; done"\n'
            f"TimeoutStopSec={service.drain}\nKillSignal=SIGINT\nRestart=on-failure\nRestartSec=60\n\n"
            "[Install]\nWantedBy=default.target\n")


def install(service: Service, *, sh: Runner = run, directory: Path | None = None,
            checkout: Path | None = None, known: dict[str, machines.Host] | None = None) -> str:
    """Install or refresh service's unit on this machine at a deploy; return what was done, one
    line.

    known is the machines (default fab.hosts.load()), this one found by fab.hosts.this;
    directory defaults to $XDG_CONFIG_HOME/systemd/user, or ~/.config/systemd/user.
    - Without the role, no unit file: nothing.
    - Without the role, a unit file: `systemctl --user disable`, then `stop --no-block` (the
      command drains on its own; the file stays, disabled).
    - With the role: text(service, checkout=) through fab.atomic.write, then daemon-reload. A
      unit that was there and disabled (a pause, `systemctl --user disable --now <unit>`) is
      left so. Otherwise, a first install among them: `enable`, then `restart --no-block`,
      which drains the running command and starts it on the new code.
    Every systemctl command is check=True except `is-enabled`, which is asked first."""
    host = machines.this(known if known is not None else machines.load())
    directory = _directory(directory)
    path = directory / service.name
    present = path.exists()
    enabled = present and sh(["systemctl", "--user", "is-enabled", "--quiet", service.name]).ok
    if host is None or service.role not in host.roles:
        if not present:
            return f"{service.name}: no {service.role} role here: nothing to do"
        sh(["systemctl", "--user", "disable", service.name], check=True)
        sh(["systemctl", "--user", "stop", "--no-block", service.name], check=True)
        return f"{service.name}: no {service.role} role here: disabled and stopping"
    atomic.write(path, text(service, checkout=checkout))
    sh(["systemctl", "--user", "daemon-reload"], check=True)
    if present and not enabled:
        return f"{path} written; {service.name} left disabled"
    sh(["systemctl", "--user", "enable", service.name], check=True)
    sh(["systemctl", "--user", "restart", "--no-block", service.name], check=True)
    return f"{path} written; {service.name} enabled and restarting"


def _directory(directory: Path | None) -> Path:
    if directory is not None:
        return directory
    config = os.environ.get("XDG_CONFIG_HOME")
    return (Path(config) if config else Path.home() / ".config") / "systemd/user"


def _check(*words: str) -> None:
    for word in words:
        if any(character in word for character in '\n\r%$"\\'):
            raise ValueError(f"invalid unit argument {word!r}")


def _invocation(command: str, home: Path | None, checkout: Path | None) -> tuple[Path, str]:
    home = (home if home is not None else log.home()).absolute()
    checkout = (checkout if checkout is not None else home / "install").absolute()
    _check(str(home), str(checkout), command)
    script = shlex.join((str(checkout / "bin/fab"), *command.split()))
    return home, f'ExecStart=/usr/bin/bash -lc "exec {script}"\n'


def status_service(*, home: Path | None = None, checkout: Path | None = None) -> str:
    """The persistent status service, restarting on failure or a changed checkout. Pure.

    Paths default to FAB_HOME and its install, made absolute; unsafe unit arguments
    raise ValueError (docs/design/machines.md, 4, The texts).
    """
    home, invocation = _invocation("serve --port 8370 --bind 127.0.0.1", home, checkout)
    return ("[Unit]\nDescription=fab: the public status page\n\n"
            f"[Service]\nEnvironment=FAB_HOME={home}\n" + invocation +
            "Restart=on-failure\nRestartSec=5\nSuccessExitStatus=75\n"
            "RestartForceExitStatus=75\n\n[Install]\nWantedBy=default.target\n")


def timer_service(what: str, command: str, timeout: str, *, quiet: bool = False,
                  home: Path | None = None, checkout: Path | None = None) -> str:
    """A oneshot service with SIGINT cleanup and the supplied timeout. Pure.

    quiet discards stdout and sends stderr to the journal. Paths default to FAB_HOME
    and its install; paths and arguments reject unsafe unit characters with ValueError.
    """
    _check(what, command, timeout)
    home, invocation = _invocation(command, home, checkout)
    output = "StandardOutput=null\nStandardError=journal\n" if quiet else ""
    return (f"[Unit]\nDescription=fab: {what}\n\n[Service]\nType=oneshot\n"
            f"Environment=FAB_HOME={home}\nKillSignal=SIGINT\nTimeoutStartSec={timeout}\n"
            + output + invocation)


def timer(what: str, when: str, calendar: str, service: str, *,
          persistent: bool = False) -> str:
    """A calendar timer for service, optionally catching missed runs. Pure.

    Descriptions, calendar and service reject unsafe unit characters with ValueError.
    """
    _check(what, when, calendar, service)
    persistence = "Persistent=true\n" if persistent else ""
    return (f"[Unit]\nDescription=fab: {what}, {when}\n\n[Timer]\nOnCalendar={calendar}\n"
            + persistence + f"Unit={service}\n\n[Install]\nWantedBy=timers.target\n")


def status_units(*, home: Path | None = None, checkout: Path | None = None) -> dict[str, str]:
    """The status service keyed by its filename. Pure; paths follow status_service."""
    return {"fab-status.service": status_service(home=home, checkout=checkout)}


def issues_units(*, home: Path | None = None, checkout: Path | None = None) -> dict[str, str]:
    """The issue timer then service keyed by filename. Pure; paths follow timer_service."""
    what = "the user's questions as forge issues"
    return {"fab-issues.timer": timer(what, "every 2 minutes", "*:1/2", "fab-issues.service"),
            "fab-issues.service": timer_service(what, "issues sync", "infinity",
                                                home=home, checkout=checkout)}


def logins_check_units(*, home: Path | None = None, checkout: Path | None = None) -> dict[str, str]:
    """The login check timer then service; quiet checks at :05 and :35, limited to 1800 s.

    Pure; paths and unsafe argument checks follow timer_service.
    """
    what = "the logins' checks"
    return {"fab-logins-check.timer": timer(what, "at :05 and :35", "*:5/30",
                                            "fab-logins-check.service"),
            "fab-logins-check.service": timer_service(what, "logins check --all", "1800",
                                                      quiet=True, home=home, checkout=checkout)}


def report_daily_units(*, home: Path | None = None, checkout: Path | None = None) -> dict[str, str]:
    """The daily report timer then service; persistent at 00:33 UTC, limited to 1800 s.

    Pure; paths and unsafe argument checks follow timer_service.
    """
    what = "yesterday's reports"
    return {"fab-report-daily.timer": timer(what, "daily at 00:33 UTC", "*-*-* 00:33:00 UTC",
                                            "fab-report-daily.service", persistent=True),
            "fab-report-daily.service": timer_service(what, "report daily", "1800",
                                                      home=home, checkout=checkout)}


def _remove_transients(files: dict[str, str], primary: str, sh: Runner) -> None:
    transients = []
    for name in sorted(files, key=lambda name: not name.endswith(".timer")):
        result = sh(["systemctl", "--user", "show",
                     "--property=Transient,ActiveState", "--value", name], check=False)
        values = result.out.strip().splitlines()
        if result.ok and "yes" in values:
            state = next((value for value in values if value not in ("yes", "no")), "")
            transients.append((name, state))
    for name, state in transients:
        if primary.endswith(".timer") and name.endswith(".service") and state not in (
                "inactive", "failed"):
            raise ValueError(f"{name} is running; rerun when it ends")
    for name, _ in transients:
        sh(["systemctl", "--user", "stop", name], check=False)
        sh(["systemctl", "--user", "reset-failed", name], check=False)


def _linger(sh: Runner) -> list[str]:
    try:
        result = sh(["loginctl", "show-user", str(os.getuid()), "--property=Linger", "--value"],
                    check=False)
        if result.ok and result.out.strip() == "yes":
            return []
    except (OSError, Failed):
        pass
    return [f"linger is off for {getpass.getuser()}: the units start at boot only "
            "after loginctl enable-linger"]


def install_units(files: dict[str, str], *, primary: str, restartable: bool,
                  role: str = "dispatcher", sh: Runner = run, directory: Path | None = None,
                  known: dict[str, machines.Host] | None = None) -> tuple[list[str], list[str]]:
    """Install the dispatcher's persistent units; return stdout lines and warnings.

    Follow docs/design/machines.md, 4, An install: remove idle transients, preserve a
    manual pause, write atomically, reload, enable and restart changed primary text only
    for a timer or restartable service. A running transient timer service refuses before
    stops or writes. Without the role, disable and stop the primary only if files exist.
    directory follows install; known defaults to hosts.load(), resolved by hosts.this.
    Linger failures warn without failing. OSError, ValueError and sh.Failed propagate.
    """
    directory = _directory(directory)
    host = machines.this(known if known is not None else machines.load())
    paths = {name: directory / name for name in files}
    if host is None or role not in host.roles:
        action = "nothing to do"
        if any(path.exists() for path in paths.values()):
            sh(["systemctl", "--user", "disable", primary], check=True)
            sh(["systemctl", "--user", "stop", "--no-block", primary], check=True)
            action = "disabled and stopping"
        return [f"{primary}: no {role} role here: {action}"], []
    previous = {}
    for name, path in paths.items():
        try:
            previous[name] = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            pass
    _remove_transients(files, primary, sh)
    paused = primary in previous and sh(
        ["systemctl", "--user", "is-enabled", primary], check=False).out.strip() == "disabled"
    for name, path in paths.items():
        atomic.write(path, files[name])
    sh(["systemctl", "--user", "daemon-reload"], check=True)
    lines = [str(path) for path in paths.values()]
    if paused:
        lines.append(f"{primary} left disabled")
    else:
        sh(["systemctl", "--user", "enable", "--now", primary], check=True)
        if (primary in previous and previous[primary] != files[primary]
                and (restartable or primary.endswith(".timer"))):
            sh(["systemctl", "--user", "restart", primary], check=True)
        lines.append(f"enabled {primary}")
    return lines, _linger(sh)


def cli_install(command: str, files: dict[str, str], *, primary: str, restartable: bool,
                sh: Runner = run, directory: Path | None = None,
                known: dict[str, machines.Host] | None = None) -> int:
    """Print install_units' paths and result, prefixing warnings with fab command.

    OSError, ValueError or sh.Failed prints one error line and returns 1; otherwise 0.
    """
    try:
        lines, warnings = install_units(files, primary=primary, restartable=restartable,
                                        sh=sh, directory=directory, known=known)
        for line in lines:
            print(line)
        for warning in warnings:
            print(f"fab {command}: {warning}", file=sys.stderr)
        return 0
    except (OSError, ValueError, Failed) as error:
        print(f"fab {command}: " + " ".join(str(error).splitlines()), file=sys.stderr)
        return 1
