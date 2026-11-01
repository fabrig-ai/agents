"""Pure decisions for the overlap probe (docs/design/fab.md, 13.17)."""

from __future__ import annotations

from collections.abc import Sequence

from fab import integration
from fab.plan import Plan

FILES = 40  # conflicting paths retained in one trunks.overlap record (13.17)


def probe_plans(plans: Sequence[Plan], events: Sequence[dict]) -> list[Plan]:
    """Ready, active integration plans whose trunks have not landed, by draft name.

    The shell also checks that each trunk is on origin (docs/design/fab.md, 13.17).
    """
    return sorted((plan for plan in plans if plan.landing == "integration" and plan.ready
                   and not plan.retired and not integration.trunk_landed(plan, events)),
                  key=lambda plan: plan.draft)


def pairs(plans: Sequence[Plan]) -> list[tuple[str, str]]:
    """Every pair of probed drafts sharing a repo, in name order (docs/design/fab.md, 13.17)."""
    ordered = sorted(plans, key=lambda plan: plan.draft)
    return [(a.draft, b.draft) for position, a in enumerate(ordered)
            for b in ordered[position + 1:] if a.repo == b.repo]


def parse_catch_up(code: int, stdout: str) -> tuple[str, str | None]:
    """Return (clean, tree), (conflict, None), or (failure, None) for a trunk merge.

    Exits 0 and 1 require a full hex object id on the first newline-separated
    line; only exit 0 supplies a usable tree (docs/design/fab.md, 13.17).
    """
    tree = stdout.partition("\n")[0]
    if code not in (0, 1) or not _object_id(tree):
        return "failure", None
    return ("clean", tree) if code == 0 else ("conflict", None)


def parse_pair(code: int, stdout: str) -> tuple[list[str], int] | None:
    """Return (files, more) for a pair merge, or None on failure (docs/design/fab.md, 13.17).

    Exit 0 is empty. Exit 1 requires a full hex object id as the first NUL
    field; subsequent nonempty fields are paths, kept in order up to FILES.
    Spaces and newlines in paths are literal; every other exit is a failure.
    """
    if code == 0:
        return [], 0
    fields = stdout.split("\0")
    if code != 1 or not _object_id(fields[0]):
        return None
    paths = [path for path in fields[1:] if path]
    return paths[:FILES], max(0, len(paths) - FILES)


def is_news(pair: tuple[str, str], files: Sequence[str], more: int,
            events: Sequence[dict]) -> bool:
    """Whether (files, more) differs from the pair's last overlap, absent as empty.

    Compare paths in merge-tree order; tips and reason do not make news
    (docs/design/fab.md, 13.17).
    """
    last = next((event for event in reversed(events)
                 if event.get("ev") == "trunks.overlap" and event.get("drafts") == list(pair)), {})
    return (list(files), more) != (last.get("files", []), last.get("more", 0))


def open_pairs(events: Sequence[dict]) -> dict[tuple[str, str], dict]:
    """Open pairs to their last overlap record, by name (docs/design/fab.md, 13.17).

    Open means the last record has files. Skip records whose drafts are not
    a list of two strings; log order, rather than timestamps, decides last.
    """
    latest = {}
    for event in events:
        drafts = event.get("drafts")
        if (event.get("ev") == "trunks.overlap" and isinstance(drafts, list)
                and len(drafts) == 2 and all(isinstance(draft, str) for draft in drafts)):
            latest[tuple(drafts)] = event
    return {pair: latest[pair] for pair in sorted(latest) if latest[pair].get("files")}


def gone_pairs(current: Sequence[tuple[str, str]], events: Sequence[dict]) -> list[dict]:
    """Closing fields for open pairs absent this tick, by name (docs/design/fab.md, 13.17).

    Keep their last tips, empty files and more, and reason gone. The shell
    calls this only when every listed plan loaded; skipped probes remain current.
    """
    present = set(current)
    return [overlap_fields(pair, last["tips"], [], 0, reason="gone")
            for pair, last in open_pairs(events).items() if pair not in present]


def failure_prefix(drafts: Sequence[str]) -> str:
    """The failure-note prefix for one trunk or a name-ordered pair (docs/design/fab.md, 13.17)."""
    return f"trunks.overlap {' '.join(drafts)}: "


def failure_is_news(prefix: str, text: str, events: Sequence[dict]) -> bool:
    """Whether full failure text differs from the last note with prefix, absent as new.

    Ignore notes for other trunks or pairs and other event kinds
    (docs/design/fab.md, 13.17).
    """
    last = next((event["text"] for event in reversed(events) if event.get("ev") == "note"
                 and isinstance(event.get("text"), str) and event["text"].startswith(prefix)), None)
    return text != last


def overlap_fields(pair: tuple[str, str], tips: Sequence[str], files: Sequence[str],
                   more: int, *, reason: str = "probe") -> dict:
    """Flat trunks.overlap fields with fresh lists, in the supplied pair's name order.

    tips follows pair order; parsed files and more already obey FILES. The shell
    supplies ev and ts through log.append (docs/design/fab.md, 13.17).
    """
    return dict(drafts=list(pair), tips=list(tips), files=list(files), more=more, reason=reason)


def _object_id(value: str) -> bool:
    """A full SHA-1 or SHA-256 hex object id from merge-tree (docs/design/fab.md, 13.17)."""
    return len(value) in (40, 64) and all(char in "0123456789abcdefABCDEF" for char in value)
