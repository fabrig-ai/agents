"""The machines and their disk budget (docs/design/fab.md, 2; machines.md, 2)."""

from __future__ import annotations

import argparse
import os
import socket
import sys
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from fab import log

DEFAULT = Path(__file__).resolve().parent / "hosts.toml"
ROLES = {"dispatcher", "builder", "gate", "after-landing"}
LOCAL = "hosts.local.toml"  # FAB_HOME's live overrides of this file, never in git (docs/design/machines.md, 2)
OVERRIDES = frozenset({"roles", "disk_gb", "places", "slots", "slot_bound_gb", "kache_gb",
                       "headroom_gb", "builds", "after_landing_slot"})  # what an override may change: not a host's identity


@dataclass(frozen=True)
class Host:
    name: str
    ssh: str
    roles: tuple[str, ...]
    hostname: str = ""  # what the machine calls itself, so tools find their own entry
    disk_gb: int = 0
    places: int = 0
    slots: int = 0
    slot_bound_gb: int = 0
    kache_gb: int = 0
    headroom_gb: int = 0
    builds: int = 0
    after_landing_slot: int = 0  # the slot claimed for after landing, with that role

    def budget_gb(self) -> int:
        """What fab's own use of the disk may reach: kache + slots x bound + headroom, and one
        bound more on a gate for the queue's target, which each batch sweeps as a slot's."""
        queue = self.slot_bound_gb if "gate" in self.roles else 0
        return self.kache_gb + self.slots * self.slot_bound_gb + queue + self.headroom_gb


def local_path() -> Path:
    """FAB_HOME/LOCAL: this machine's live overrides of fab/hosts.toml."""
    return log.home() / LOCAL


def tables(text: str, local: str | None = None) -> dict[str, dict]:
    """The tables of a hosts file's text with local's applied key by key. Pure.

    local is the text of an overrides file (LOCAL): tables named after hosts of text, each
    holding only OVERRIDES keys. Anything else, or TOML that does not parse, is a ValueError
    naming LOCAL."""
    entries = tomllib.loads(text)
    if not local:
        return entries
    try:
        changes = tomllib.loads(local)
    except tomllib.TOMLDecodeError as error:
        raise ValueError(f"{LOCAL}: {error}") from None
    for name, table in changes.items():
        if name not in entries or not isinstance(table, dict):
            raise ValueError(f"{LOCAL}: {name}: not a host of fab/hosts.toml")
        fixed = set(table) - OVERRIDES
        if fixed:
            raise ValueError(f"{LOCAL}: {name}: keys an override cannot change {sorted(fixed)}")
        entries[name] = {**entries[name], **table}
    return entries


def parse(text: str, local: str | None = None) -> dict[str, Host]:
    """The machines of a hosts file's text, with the overrides text local applied (tables)."""
    hosts = {}
    for name, table in tables(text, local).items():
        unknown = set(table) - set(Host.__dataclass_fields__)
        if unknown:
            raise ValueError(f"{name}: unknown keys {sorted(unknown)}")
        roles = tuple(table.get("roles", ()))
        if not set(roles) <= ROLES:
            raise ValueError(f"{name}: unknown roles {sorted(set(roles) - ROLES)}")
        hosts[name] = Host(name=name, **{**table, "roles": roles})
    return hosts


def load(path: Path = DEFAULT, local: Path | None = None) -> dict[str, Host]:
    """The machines of path, with this machine's live overrides (local, default local_path())
    applied when that file exists. Every reader of the machines goes through here, so an
    override holds from the next tick, the next heavy command and the next deploy."""
    local = local_path() if local is None else local
    return parse(path.read_text(), local.read_text() if local.exists() else None)


def this_name(hostnames: Mapping[str, str], name: str | None = None) -> str:
    """This machine's entry name: name when given, else the FAB_HOST environment variable
    when set, else the first key of hostnames (entry name to its hostname) whose value equals
    socket.gethostname(), else "". A given or FAB_HOST name is returned as it is, even ""
    or a name hostnames lacks. fab.heavy.settings and this use it."""
    if name is not None:
        return name
    if "FAB_HOST" in os.environ:
        return os.environ["FAB_HOST"]
    hostname = socket.gethostname()
    return next((entry for entry, value in hostnames.items() if value == hostname), "")


def this(hosts: Mapping[str, Host], name: str | None = None) -> Host | None:
    """This machine's Host: hosts[this_name({entry: host.hostname}, name)], None when hosts
    has no such entry."""
    return hosts.get(this_name({entry: host.hostname for entry, host in hosts.items()}, name))


def problems(host: Host) -> list[str]:
    """A builder whose budget exceeds its disk, or that lacks the figures to say; an
    after-landing machine that is no builder or names no slot of its own."""
    if "after-landing" in host.roles and not (
            "builder" in host.roles and 0 < host.after_landing_slot <= host.slots):
        return [f"{host.name}: after-landing needs the builder role and one of its slots "
                "as after_landing_slot"]
    if "builder" not in host.roles:
        return []
    if not (host.disk_gb and host.slots and host.slot_bound_gb and host.places and host.builds):
        return [f"{host.name}: a builder needs disk_gb, places, slots, slot_bound_gb and builds"]
    if host.budget_gb() > host.disk_gb:
        return [f"{host.name}: budget {host.budget_gb()} GB exceeds the disk's {host.disk_gb} GB"]
    return []


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="fab hosts", description=__doc__)
    parser.add_argument("action", choices=["check"])
    parser.parse_args(argv)
    found = []
    local = local_path()
    if local.exists():
        try:
            tables(DEFAULT.read_text(), local.read_text())
        except ValueError as error:
            print(f"fab hosts: {local}: {error}", file=sys.stderr)
            return 1
        for name, changed in tomllib.loads(local.read_text()).items():
            print(f"{name}: overridden in {local}: "
                  + ", ".join(f"{key} = {value!r}" for key, value in sorted(changed.items())))
    for host in load().values():
        if "builder" in host.roles:
            queue = f" + {host.slot_bound_gb} (queue)" if "gate" in host.roles else ""
            print(f"{host.name}: {host.kache_gb} + {host.slots} x {host.slot_bound_gb}{queue}"
                  f" + {host.headroom_gb} = {host.budget_gb()} of {host.disk_gb} GB")
        found += problems(host)
    for problem in found:
        print(problem)
    return 1 if found else 0
