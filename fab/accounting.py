"""Accounting: what Claude and Codex spend, folded from the log (docs/design/fab.md, 13.5).

The producers record it: a call's call.ended carries Claude's usage (`fab.calls.claude_usage`),
a run's run.ended carries Codex's tokens (`fab.codex.tokens_field`). This module only reads
those records. The weight puts both on one scale, as the user's execution model weighs them;
the code report shows it beside each call's peak context. A call is measured, not capped:
nothing here ends a call, and TARGET only flags.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from pathlib import Path

from fab import log

from fab.report import Figure, Window

CLAUDE = {"input": 1.0, "cache_write": 1.25, "cache_read": 0.1, "output": 5.0}  # weight per token
CODEX = {"input": 1.0, "cache_read": 0.1, "output": 8.0}  # Codex reports no cache writes
TARGET = 600_000  # tokens: the user's context target for one call (10-30); the report flags calls over it
MILLION = 1_000_000  # weights are reported in millions, as the model's tables give them
COUNTS = re.compile(r"^([0-9]+)/([0-9]+)/([0-9]+)$")  # a tokens field: `<input>/<cached>/<output>`

FIGURES = (  # (key, label): the code report's Claude and Codex figures, in its order
    ("calls", "Claude calls ended"),
    ("call_minutes", "Claude call minutes"),
    ("input_tokens", "Claude input tokens"),
    ("output_tokens", "Claude output tokens"),
    ("codex_input_tokens", "Codex input tokens"),
    ("codex_output_tokens", "Codex output tokens"),
    ("claude_weight", "Claude weight, millions"),
    ("codex_weight", "Codex weight, millions"),
    ("weight_ratio", "Claude to Codex weight"),
    ("peak_context", "largest Claude call context"),
    ("over_target", "Claude calls over the 600k context target"),
)


def token_counts(value: object) -> tuple[int, int, int] | None:
    """The three counts of a call.ended or run.ended `tokens` field, a string matching
    COUNTS: (input, cached, output). None for anything else: a missing field (None), a
    number, two or four parts, a part that is not decimal digits, the empty string."""
    if not isinstance(value, str):
        return None
    match = COUNTS.fullmatch(value)
    return tuple(map(int, match.groups())) if match else None


def call_weight(event: dict) -> float | None:
    """A call.ended's Claude weight, in tokens: input x CLAUDE["input"] + cache_write x
    CLAUDE["cache_write"] + cached x CLAUDE["cache_read"] + output x CLAUDE["output"], the
    counts from token_counts(event.get("tokens")) (Claude's input excludes both cache reads
    and cache writes) and cache_write from the event's `cache_write` field, 0 when it is
    missing or not a non-negative int (records before accounting have none). None when
    token_counts is None."""
    counts = token_counts(event.get("tokens"))
    if counts is None:
        return None
    incoming, cached, outgoing = counts
    return (incoming * CLAUDE["input"] + _cache_write(event) * CLAUDE["cache_write"]
            + cached * CLAUDE["cache_read"] + outgoing * CLAUDE["output"])


def run_weight(event: dict) -> float | None:
    """A run.ended's Codex weight, in tokens, from token_counts(event.get("tokens")):
    Codex's input includes its cached tokens, so max(0, input - cached) x CODEX["input"] +
    cached x CODEX["cache_read"] + output x CODEX["output"]. None when token_counts is None
    (runs ended before accounting, or a launcher that wrote no result)."""
    counts = token_counts(event.get("tokens"))
    if counts is None:
        return None
    incoming, cached, outgoing = counts
    return (max(0, incoming - cached) * CODEX["input"]
            + cached * CODEX["cache_read"] + outgoing * CODEX["output"])


def draft_calls(draft: str, events: Iterable[dict]) -> list[dict]:
    """The draft's call.ended records, in log order: those whose subject is the draft
    itself (its answer calls) or starts `<draft>/` (its parts', and its cut, review,
    retire and decision calls; an amend call carries its root's subject)."""
    return [event for event in events
            if event.get("ev") == "call.ended" and _subject(draft, event)]


def draft_runs(draft: str, events: Iterable[dict]) -> list[dict]:
    """The draft's run.ended records, in log order: those whose task starts `<draft>/`
    (implement, repair, rebase and foreman runs), and those whose task is the call of a
    call.started of the draft (subject as draft_calls takes it): the review runs of its
    calls' chains, whose task is the root call's id. One pass collects the call ids, so a
    review run's record may come before or after its call's."""
    events = list(events)
    calls = {event.get("call") for event in events
             if event.get("ev") == "call.started" and _subject(draft, event)}
    calls.discard(None)
    return [event for event in events if event.get("ev") == "run.ended"
            and (event.get("task", "").startswith(draft + "/") or event.get("task") in calls)]


def figures(draft: str, events: list[dict], window: Window) -> dict[str, Figure]:
    """Every FIGURES key for the window, over draft_calls and draft_runs of events whose ts
    the window holds:
    - calls: the calls; call_minutes: their `minutes` summed as floats (missing counts 0).
    - input_tokens: per call with token_counts, input + cached + its cache_write (as
      call_weight reads it); output_tokens: output. A call without counts adds 0.
    - codex_input_tokens: per run with token_counts, input (which holds cached);
      codex_output_tokens: output. A run without counts adds 0.
    - claude_weight, codex_weight: call_weight and run_weight summed over those that are
      not None, divided by MILLION; 0.0 when none.
    - weight_ratio: claude_weight / codex_weight; None when codex_weight is 0.
    - peak_context: the largest `peak` of the calls holding one as a non-negative int; None
      when none does. over_target: how many of those are over TARGET.
    Counts are ints, minutes and weights floats. Pure."""
    calls = [event for event in draft_calls(draft, events) if window.holds(event["ts"])]
    runs = [event for event in draft_runs(draft, events) if window.holds(event["ts"])]
    incoming = outgoing = codex_incoming = codex_outgoing = 0
    claude_weight = codex_weight = 0.0
    peaks = []
    for event in calls:
        counts = token_counts(event.get("tokens"))
        if counts is not None:
            incoming += counts[0] + counts[1] + _cache_write(event)
            outgoing += counts[2]
            claude_weight += call_weight(event)
        peak = event.get("peak")
        if type(peak) is int and peak >= 0:
            peaks.append(peak)
    for event in runs:
        counts = token_counts(event.get("tokens"))
        if counts is not None:
            codex_incoming += counts[0]
            codex_outgoing += counts[2]
            codex_weight += run_weight(event)
    return {
        "calls": len(calls),
        "call_minutes": sum((float(event.get("minutes", 0)) for event in calls), 0.0),
        "input_tokens": incoming,
        "output_tokens": outgoing,
        "codex_input_tokens": codex_incoming,
        "codex_output_tokens": codex_outgoing,
        "claude_weight": claude_weight / MILLION,
        "codex_weight": codex_weight / MILLION,
        "weight_ratio": claude_weight / codex_weight if codex_weight else None,
        "peak_context": max(peaks, default=None),
        "over_target": sum(peak > TARGET for peak in peaks),
    }


def call_rows(draft: str, events: list[dict], window: Window) -> list[tuple]:
    """One row per call of draft_calls whose ts the window holds, in log order, for the
    code report's Calls table: (call, role, subject, minutes as a float, turns, peak,
    call_weight / MILLION, over). turns and peak are the record's ints, None when missing or
    not ints; the weight is None when call_weight is; over is "yes" when peak is over
    TARGET, "no" when it is not, "-" when peak is None. A missing call, role or subject is
    "". Pure."""
    rows = []
    for event in draft_calls(draft, events):
        if not window.holds(event["ts"]):
            continue
        turns, peak = (event.get(key) if type(event.get(key)) is int else None
                       for key in ("turns", "peak"))
        weight = call_weight(event)
        rows.append((event.get("call", ""), event.get("role", ""), event.get("subject", ""),
                     float(event.get("minutes", 0)), turns, peak,
                     weight / MILLION if weight is not None else None,
                     "-" if peak is None else "yes" if peak > TARGET else "no"))
    return rows


def hand_usage(draft: str, *, home: Path | None = None,
               projects: Path | None = None) -> tuple[dict[str, Figure], list[str]]:
    """Read the draft's whole hand sessions, apart from windowed calls (13.11).

    home defaults to FAB_HOME, projects to ~/.claude/projects. No matching sessions
    gives no figures. Return input (including both caches), output and Claude weight M,
    with notes for unread transcripts. Each requestId counts once across all files.
    """
    manifest = (home if home is not None else log.home()) / "hand-sessions"
    notes = []
    try:
        lines = manifest.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return {}, notes
    except (OSError, UnicodeError) as error:
        return {}, [f"{manifest}: {error}"]
    sessions = set()
    for number, line in enumerate(lines, 1):
        fields = line.split("#", 1)[0].split()
        if not fields:
            continue
        if len(fields) != 2 or not re.fullmatch(r"[A-Za-z0-9_-]+", fields[0]):
            notes.append(f"{manifest}:{number}: expected <session id> <draft>")
        elif fields[1] == draft:
            sessions.add(fields[0])
    if not sessions:
        return {}, notes
    projects = projects if projects is not None else Path.home() / ".claude/projects"
    totals = [0, 0, 0, 0]
    seen = set()
    for session in sorted(sessions):
        try:
            transcripts = sorted(projects.glob(f"*/{session}.jsonl"))
            transcripts += sorted(projects.glob(f"*/{session}/subagents/*.jsonl"))
        except OSError as error:
            notes.append(f"{projects}/{session}: {error}")
            continue
        if not transcripts:
            notes.append(f"hand session {session}: no transcripts under {projects}")
        for path in transcripts:
            _hand_transcript(path, seen, totals, notes)
    incoming, written, cached, outgoing = totals
    weight = call_weight({"tokens": f"{incoming}/{cached}/{outgoing}", "cache_write": written})
    return {"hand_input_tokens": incoming + written + cached, "hand_output_tokens": outgoing,
            "hand_weight": weight / MILLION}, notes


def _hand_transcript(path: Path, seen: set[str], totals: list[int], notes: list[str]) -> None:
    """Add valid assistant usage once per request; torn lines do not stop a transcript."""
    try:
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(record, dict) or record.get("type") != "assistant":
                    continue
                request = record.get("requestId")
                message = record.get("message")
                usage = message.get("usage") if isinstance(message, dict) else None
                if not isinstance(request, str) or not request or request in seen or not isinstance(usage, dict):
                    continue
                seen.add(request)
                for index, key in enumerate(("input_tokens", "cache_creation_input_tokens",
                                             "cache_read_input_tokens", "output_tokens")):
                    value = usage.get(key)
                    if type(value) is int and value >= 0:
                        totals[index] += value
    except (OSError, UnicodeError) as error:
        notes.append(f"{path}: {error}")


def _cache_write(event: dict) -> int:
    value = event.get("cache_write")
    return value if type(value) is int and value >= 0 else 0


def _subject(draft: str, event: dict) -> bool:
    subject = event.get("subject")
    return isinstance(subject, str) and (subject == draft or subject.startswith(draft + "/"))
