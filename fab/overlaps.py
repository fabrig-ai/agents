"""Overlap decisions and the tick's probe (docs/design/fab.md, 13.17).

FAB_HOME/overlaps.json holds two JSON objects, trees and pairs. Their keys are
JSON lists of repository, checkout, main SHA, then one trunk tip (trees) or
both name-ordered tips (pairs). Values are a tree ID or {files: [...], more: n}.
Checkout scoping keeps tree IDs in their object store. Only successful results
are cached; missing, unreadable or malformed caches are empty.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from fab import atomic, integration, log
from fab.plan import Plan, Task
from fab.sh import Failed, Result, Runner, run

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


def probe(loaded: Sequence[tuple[Plan, dict[str, Task], Path, Path]], events: Sequence[dict],
          all_loaded: bool, *, sh: Runner = run, log_path: Path | None = None) -> list[str]:
    """Probe loaded trunks, log news and return printed lines (docs/design/fab.md, 13.17).

    Use one checkout per repository, chosen by draft name, and cache successful
    merges. Conflicted or failed catch-ups keep their pairs current but unprobed.
    Close absent open pairs only when all listed plans loaded. Repositories with
    no possible pair need no git commands. Checkout and cache-write errors may
    escape for the tick to print.
    """
    cache_path = log.home() / "overlaps.json"
    cache = _read_cache(cache_path)
    records = list(events)
    lines = []
    current = []
    checkouts = {plan.draft: checkout for plan, _, _, checkout in loaded}
    repositories = {}
    for plan in probe_plans([plan for plan, _, _, _ in loaded], records):
        repositories.setdefault(plan.repo, []).append(plan)
    for repo, candidates in repositories.items():
        if len(candidates) < 2:
            continue
        checkout = str(checkouts[candidates[0].draft])
        main = sh(["git", "rev-parse", "--verify", "origin/main"], cwd=checkout)
        if not main.ok:
            raise Failed(["git", "rev-parse", "--verify", "origin/main"], main)
        if not main.out.strip():
            raise ValueError(f"overlap {repo}: origin/main did not resolve")
        tips = {}
        present = []
        for plan in candidates:
            tip = sh(["git", "rev-parse", "--verify", f"origin/{plan.trunk}"], cwd=checkout)
            if tip.ok and tip.out.strip():
                tips[plan.draft] = tip.out.strip()
                present.append(plan)
        repo_pairs = pairs(present)
        current.extend(repo_pairs)
        if not repo_pairs:
            continue
        key_prefix = (repo, checkout, main.out.strip())
        trees, tree_keys, failures = _catch_up_trees(
            present, tips, key_prefix, cache, records, sh=sh, log_path=log_path)
        lines.extend(failures)
        lines.extend(_pair_results(repo_pairs, tips, key_prefix, trees, tree_keys,
                                   cache, records, sh=sh, log_path=log_path))
    if all_loaded:
        for fields in gone_pairs(current, records):
            records.append(log.append("trunks.overlap", path=log_path, **fields))
            lines.append(f"overlap {' '.join(fields['drafts'])} gone")
    atomic.write(cache_path, json.dumps(cache) + "\n")
    return lines


def _catch_up_trees(plans: Sequence[Plan], tips: dict[str, str],
                    key_prefix: tuple[str, str, str], cache: dict, records: list[dict], *,
                    sh: Runner, log_path: Path | None) -> tuple[dict[str, str], dict[str, str], list[str]]:
    """Return usable catch-up trees, cache keys and failure lines (docs/design/fab.md, 13.17).

    key_prefix is (repository, checkout, main SHA). Update the shared cache
    and records so failures deduplicate across all merges in this probe.
    """
    checkout = key_prefix[1]
    lines = []
    trees = {}
    tree_keys = {}
    for plan in plans:
        key = json.dumps([*key_prefix, tips[plan.draft]])
        tree_keys[plan.draft] = key
        tree = cache["trees"].get(key)
        if tree is None:
            result = _merge(["git", "merge-tree", "--write-tree", "--no-messages",
                             "origin/main", f"origin/{plan.trunk}"], checkout, sh)
            status, tree = parse_catch_up(result.code, result.out)
            if status == "failure":
                lines.append(_failure((plan.draft,), result, records, log_path))
            if tree is None:
                continue
            cache["trees"][key] = tree
        trees[plan.draft] = tree
    return trees, tree_keys, lines


def _pair_results(repo_pairs: Sequence[tuple[str, str]], tips: dict[str, str],
                  key_prefix: tuple[str, str, str], trees: dict[str, str], tree_keys: dict[str, str],
                  cache: dict, records: list[dict], *, sh: Runner, log_path: Path | None) -> list[str]:
    """Return pair news and failure lines, updating shared records and cache (docs/design/fab.md, 13.17).

    key_prefix is (repository, checkout, main SHA). Skip unavailable trees;
    on pair failure evict its trees from the cache while retaining them for this tick.
    """
    checkout = key_prefix[1]
    lines = []
    for pair in repo_pairs:
        a, b = pair
        if a not in trees or b not in trees:
            continue
        pair_tips = [tips[a], tips[b]]
        key = json.dumps([*key_prefix, *pair_tips])
        answer = cache["pairs"].get(key)
        if answer is None:
            result = _merge(["git", "merge-tree", "--write-tree", "--name-only",
                             "--no-messages", "-z", "--merge-base=origin/main",
                             trees[a], trees[b]], checkout, sh)
            parsed = parse_pair(result.code, result.out)
            if parsed is None:
                for draft in pair:
                    cache["trees"].pop(tree_keys[draft], None)
                lines.append(_failure(pair, result, records, log_path))
                continue
            files, more = parsed
            answer = dict(files=files, more=more)
            cache["pairs"][key] = answer
        if is_news(pair, answer["files"], answer["more"], records):
            records.append(log.append("trunks.overlap", path=log_path,
                                      **overlap_fields(pair, pair_tips, **answer)))
            lines.append(f"overlap {a} {b} {len(answer['files']) + answer['more']}")
    return lines


def _read_cache(path: Path) -> dict:
    """Read valid cached results; losing any malformed cache costs only merges."""
    try:
        cache = json.loads(path.read_text(encoding="utf-8"))
        if (isinstance(cache, dict) and isinstance(cache.get("trees"), dict)
                and isinstance(cache.get("pairs"), dict)
                and all(isinstance(tree, str) and _object_id(tree)
                        for tree in cache["trees"].values())
                and all(isinstance(answer, dict) and isinstance(answer.get("files"), list)
                        and len(answer["files"]) <= FILES
                        and all(isinstance(path, str) for path in answer["files"])
                        and type(answer.get("more")) is int and answer["more"] >= 0
                        for answer in cache["pairs"].values())):
            return cache
    except (OSError, ValueError, UnicodeError):
        pass
    return {"trees": {}, "pairs": {}}


def _merge(argv: list[str], checkout: str, sh: Runner) -> Result:
    """Run a merge without allowing a checkout failure to discard other pairs."""
    try:
        return sh(argv, cwd=checkout)
    except Failed as error:
        return error.result
    except (OSError, ValueError) as error:
        return Result(-1, err=str(error))


def _failure(drafts: Sequence[str], result: Result, events: list[dict],
             log_path: Path | None) -> str:
    """Return the failure line every tick, appending its note only when news."""
    prefix = failure_prefix(drafts)
    detail = result.err.splitlines()[0] if result.err else "unreadable merge-tree output"
    text = f"{prefix}exit {result.code}: {detail}"
    if failure_is_news(prefix, text, events):
        events.append(log.append("note", path=log_path, text=text))
    return text
