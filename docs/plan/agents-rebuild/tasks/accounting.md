+++
id = "accounting"
part = "accounting"
kind = "feature"
needs = []
files = ["fab/accounting.py", "fab/calls.py", "fab/codex.py", "fab/run.py", "fab/code_report.py", "fab/tests/test_accounting.py", "fab/tests/test_calls.py", "fab/tests/test_codex.py", "fab/tests/test_run.py", "fab/tests/test_code_report.py"]
effort = "high"
minutes = 50
+++
# Codex tokens in the log; the Claude to Codex weight; calls measured

Today run.ended holds no Codex tokens, call.ended holds Claude's without
cache writes, peak context or turns, and the code report shows no weight.
Fill what the docstrings say. Design: `docs/design/fab.md`, 13.5 (and
section 3's table of events, section 10's code report).

## What to fill

- `fab/accounting.py`: every body (`token_counts`, `call_weight`,
  `run_weight`, `draft_calls`, `draft_runs`, `figures`, `call_rows`).
- `fab/calls.py`: `Usage.log_fields`, `claude_usage`; then `claude_argv` and
  `start` as their amended docstrings say (stream-json with `--verbose`,
  stdout kept as `stream.jsonl` instead of `result.json`, call.ended with
  `**claude_usage(result.out).log_fields()` in place of today's `tokens`).
  `_call_result` keeps only the report's outcome, or goes.
- `fab/codex.py`: `tokens_field`.
- `fab/run.py`: `status` and `collect` as their amended docstrings say (one
  ssh still; `tokens` into run.ended only when status gives it).
- `fab/code_report.py`: splice `*accounting.FIGURES` into `FIGURES` in place
  of today's `calls`, `call_minutes`, `input_tokens` and `output_tokens`
  entries (the same place, after `infra_minutes`); `figures` takes those
  keys from `accounting.figures` and drops its own subjects, calls and
  token lines; `render` adds the `## Calls` section after `## Parts`.

## Acceptance

- `fab/tests/test_accounting.py`, with plain event dicts (ts strings in
  `fab.log.now()`'s format) and a `fab.report.Window`, covers:
  - `token_counts` on `"10/3/4"` and each refused value (`None`, `42`,
    `"1/2"`, `"1/2/3/4"`, `"1/oops/3"`, `"-1/2/3"`, `""`);
  - `call_weight` with and without `cache_write`, and a bad `cache_write`;
    `run_weight` with cached above input; both None without tokens;
  - `draft_calls` taking `demo`, `demo/core`, `demo/review` and
    `demo/core/decision` and leaving `demo2/x` and `elsewhere`;
  - `draft_runs` taking a task run, a foreman run and a review run whose
    call.started comes after it in the log, and leaving another draft's;
  - `figures`: every FIGURES key, each computed once, a window edge, a
    ratio None without Codex runs, peak and over_target ignoring records
    without a peak;
  - `call_rows` for a measured call over TARGET and an old call without
    peak or turns (`-`).
- `fab/tests/test_calls.py`: `claude_usage` on a stream written in the test
  (a message split over two events, a subagent's larger message left out of
  peak, the result's totals and num_turns), on one with no result event
  (summed, turns counted), on the old single JSON object and on garbage;
  `log_fields`; the new argv; `start` writing `stream.jsonl` and logging
  call.ended with tokens, cache_write, peak and turns.
- `fab/tests/test_codex.py`: `tokens_field` on what `execute` writes, a
  missing key, and text that is not JSON.
- `fab/tests/test_run.py`: `status` with and without the result line, and
  `collect` logging tokens or leaving them out.
- `fab/tests/test_code_report.py`: the existing tests updated to the new
  keys and the widened subjects, and `render` showing `## Calls`.
- `bin/fab test` passes; `test_accounting.py` takes under half a second and
  the touched modules stay under a second each.

## Options, settled up front

- The weights are the model's table: input 1, cache write 1.25, cache read
  0.1, output 5 for Claude and 8 for Codex; Codex has no cache writes and
  its input holds its cached tokens.
- call.ended's `tokens` keeps its shape and meaning; the cache writes are a
  new field, so old readers and records stay right.
- Peak context is the main thread's only; subagents are left out.
- No cap, turn limit or new stop: a call is measured (13.5). No signal is
  raised for a call over TARGET; the report's figure and its Calls table
  flag it.
- `fab.code_report.figures` must not grow (the `size` gate's ratchet): the
  call and token lines move out of it.
- Private helpers are yours; the public functions keep their signatures.
