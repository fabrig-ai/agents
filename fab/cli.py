"""The command's dispatch: `bin/fab COMMAND ...` (docs/design/fab.md, 2)."""

from __future__ import annotations

import importlib
import sys

# Each command lives in its own module and is imported only when used.
COMMANDS = {
    "call": ("fab.calls", "run a Claude call on a compiled brief"),
    "tick": ("fab.dispatch", "collect, land and start every plan's tasks"),
    "test": ("fab.testrun", "run every test; fail past the 30 s budget"),
    "page": ("fab.channel", "the user's page: their questions and the latest reports; their answers"),
    "report": ("fab.report", "the standing reports of a plan and of the landing"),
    "status": ("fab.state", "a plan's tasks and their status"),
    "land": ("fab.land", "land a branch of this repository"),
    "run": ("fab.run", "start, inspect and collect Codex runs"),
    "codex": ("fab.codex", "start a Codex run as a user unit (the builder's side of fab run)"),
    "hosts": ("fab.hosts", "the machines and their disk budget"),
    "slot": ("fab.slots", "a builder's slots: claim, release, reclaim"),
    "queue": ("fab.queue", "fabrig's merge queue"),
    "precheck": ("fab.precheck", "the queue's checks on a branch, in its slot"),
    "tiers": ("fab.tiers", "run or verify one of fabrig's slow tiers"),
    "after-landing": ("fab.after_landing", "fabrig's slow tiers on each new main"),
}


def usage() -> str:
    width = max(map(len, COMMANDS))
    lines = ["usage: fab COMMAND [ARGS...]", ""]
    lines += [f"  {name:<{width}}  {text}" for name, (_, text) in COMMANDS.items()]
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(usage())
        return 0 if argv else 2
    name, rest = argv[0], argv[1:]
    if name not in COMMANDS:
        print(f"fab: unknown command {name!r}\n\n{usage()}", file=sys.stderr)
        return 2
    module = importlib.import_module(COMMANDS[name][0])
    return module.main(rest)
