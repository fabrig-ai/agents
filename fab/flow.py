"""The flow: how many runs a plan keeps in flight, and when a builder may pass its places
(docs/design/fab.md, 13.2).

`target` and `calm` are pure. `measure` asks each builder once over ssh. The dispatcher
starts runs while the plan's runs in flight are below its target, on builders with a free
place, or one more on a calm builder (fab.dispatch.places).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from fab.hosts import Host
from fab.sh import Runner, run

START = 2  # the target when a plan starts
FLOOR = 1  # the target never drops below this
LOAD_LOW = 0.7  # a builder is calm below this 5-minute load per CPU
WAIT_MINUTES = 30  # heavy's records this far back count toward calm
WAIT_LOW = 5.0  # and their lane and disk waits, summed in minutes, stay below this
# One ssh per builder: the load, the CPUs, then heavy's last records (none when absent).
PROBE = ["sh", "-c", 'cat /proc/loadavg && nproc && { test ! -e "$1" || tail -n 1000 "$1"; }', "sh"]


def target(draft: str, events: Iterable[dict]) -> int:
    """The draft's target for runs in flight after the events, folded in log order.

    Only events whose task starts with `<draft>/` count; other types are ignored. The target
    starts at START. The fold keeps the draft's runs in flight (run.started adds its run,
    run.ended removes it) and, per task, its run.started count, whether it was ever
    rejected, and whether its latest run ended while the window was full: at that run.ended
    the runs in flight, counting the ending run itself, were at least the target then.
    - run.ended with outcome infra: the target drops by one, never below FLOOR.
    - branch.rejected: the task is marked rejected; the target drops by one, never below FLOOR.
    - branch.landed: the target grows by one when it is the task's first branch.landed, the
      task has exactly one run.started, was never rejected, and its latest run ended while
      the window was full. A landing from a run that ended with fewer runs in flight than
      the target does not grow it: an unused target says nothing about a larger one.
    A run.ended without its run.started still updates the target (infra) but is not counted
    as in flight. Never raises on a record missing a field: it is skipped for that rule."""
    raise NotImplementedError


def calm(output: str, now: str) -> bool:
    """Whether a builder may take a run beyond its places, from PROBE's output at ts now.

    The output's first line is /proc/loadavg (its second field the 5-minute load), its second
    nproc's count, the rest heavy.jsonl's lines; a line that does not parse as a JSON object
    with a string ts is skipped. Calm when all hold: the 5-minute load divided by the count is
    below LOAD_LOW; over fab.report.Window(now - WAIT_MINUTES, now) (stamped with
    fab.report.stamp), fab.report.heavy_waits gives lane_wait + disk_wait below WAIT_LOW and
    disk_refused 0. A first or second line that does not parse, or a count below 1, is not
    calm. Never raises."""
    raise NotImplementedError


def measure(hosts: Mapping[str, Host], now: str, *, sh: Runner = run) -> dict[str, bool]:
    """Every builder's calm, keyed by name in sorted order: one `sh(ssh(host.ssh, PROBE +
    [fab.run.remote_home(host) + "/heavy.jsonl"]))` each, then calm(output, now). A command
    that fails is False for that builder and the others are still measured. Hosts without the
    builder role are left out. Never raises for a remote failure."""
    raise NotImplementedError
