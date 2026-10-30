"""The machines and their disk budget (docs/design/fab.md, 2 and 7)."""

from __future__ import annotations

import argparse
import tomllib
from dataclasses import dataclass
from pathlib import Path

DEFAULT = Path(__file__).resolve().parent / "hosts.toml"
ROLES = {"dispatcher", "builder", "gate"}


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

    def budget_gb(self) -> int:
        """What fab's own use of the disk may reach: kache + slots x bound + headroom."""
        return self.kache_gb + self.slots * self.slot_bound_gb + self.headroom_gb


def parse(text: str) -> dict[str, Host]:
    hosts = {}
    for name, table in tomllib.loads(text).items():
        unknown = set(table) - set(Host.__dataclass_fields__)
        if unknown:
            raise ValueError(f"{name}: unknown keys {sorted(unknown)}")
        roles = tuple(table.get("roles", ()))
        if not set(roles) <= ROLES:
            raise ValueError(f"{name}: unknown roles {sorted(set(roles) - ROLES)}")
        hosts[name] = Host(name=name, **{**table, "roles": roles})
    return hosts


def load(path: Path = DEFAULT) -> dict[str, Host]:
    return parse(path.read_text())


def problems(host: Host) -> list[str]:
    """A builder whose budget exceeds its disk, or that lacks the figures to say."""
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
    for host in load().values():
        if "builder" in host.roles:
            print(f"{host.name}: {host.kache_gb} + {host.slots} x {host.slot_bound_gb} + {host.headroom_gb}"
                  f" = {host.budget_gb()} of {host.disk_gb} GB")
        found += problems(host)
    for problem in found:
        print(problem)
    return 1 if found else 0
