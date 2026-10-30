"""Accounting: what Claude and Codex spend, folded from the log (docs/design/fab.md, 13.5).

The producers record it: a call's call.ended carries Claude's usage (`fab.calls.claude_usage`),
a run's run.ended carries Codex's tokens (`fab.codex.tokens_field`). This module only reads
those records. The weight puts both on one scale, as the user's execution model weighs them;
the code report shows it beside each call's peak context. A call is measured, not capped:
nothing here ends a call, and TARGET only flags.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

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
    raise NotImplementedError


def call_weight(event: dict) -> float | None:
    """A call.ended's Claude weight, in tokens: input x CLAUDE["input"] + cache_write x
    CLAUDE["cache_write"] + cached x CLAUDE["cache_read"] + output x CLAUDE["output"], the
    counts from token_counts(event.get("tokens")) (Claude's input excludes both cache reads
    and cache writes) and cache_write from the event's `cache_write` field, 0 when it is
    missing or not a non-negative int (records before accounting have none). None when
    token_counts is None."""
    raise NotImplementedError


def run_weight(event: dict) -> float | None:
    """A run.ended's Codex weight, in tokens, from token_counts(event.get("tokens")):
    Codex's input includes its cached tokens, so max(0, input - cached) x CODEX["input"] +
    cached x CODEX["cache_read"] + output x CODEX["output"]. None when token_counts is None
    (runs ended before accounting, or a launcher that wrote no result)."""
    raise NotImplementedError


def draft_calls(draft: str, events: Iterable[dict]) -> list[dict]:
    """The draft's call.ended records, in log order: those whose subject is the draft
    itself (its answer calls) or starts `<draft>/` (its parts', and its cut, review,
    retire and decision calls; an amend call carries its root's subject)."""
    raise NotImplementedError


def draft_runs(draft: str, events: Iterable[dict]) -> list[dict]:
    """The draft's run.ended records, in log order: those whose task starts `<draft>/`
    (implement, repair, rebase and foreman runs), and those whose task is the call of a
    call.started of the draft (subject as draft_calls takes it): the review runs of its
    calls' chains, whose task is the root call's id. One pass collects the call ids, so a
    review run's record may come before or after its call's."""
    raise NotImplementedError


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
    raise NotImplementedError


def call_rows(draft: str, events: list[dict], window: Window) -> list[tuple]:
    """One row per call of draft_calls whose ts the window holds, in log order, for the
    code report's Calls table: (call, role, subject, minutes as a float, turns, peak,
    call_weight / MILLION, over). turns and peak are the record's ints, None when missing or
    not ints; the weight is None when call_weight is; over is "yes" when peak is over
    TARGET, "no" when it is not, "-" when peak is None. A missing call, role or subject is
    "". Pure."""
    raise NotImplementedError
