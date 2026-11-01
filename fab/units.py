"""fab's own long-running user units, written at a deploy on the machines whose role in
fab/hosts.toml wants them (docs/design/fab-landing.md, 2; fab-after-landing.md, 2): the queue on the gate, after landing
on its builder.

A deploy runs each unit's install on every machine. A machine with the role gets the unit and
a restart on the new code; one without it has a unit it finds disabled, so moving the role
moves the unit. A unit disabled by hand is a pause, and a deploy leaves it disabled.
"""

from __future__ import annotations

import os
import shlex
from dataclasses import dataclass
from pathlib import Path

from fab import atomic, hosts as machines, log
from fab.sh import Runner, run


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
    if directory is None:
        config = os.environ.get("XDG_CONFIG_HOME")
        directory = (Path(config) if config else Path.home() / ".config") / "systemd/user"
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
