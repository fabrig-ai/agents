# Request: designers at xhigh, their surveys on Claude sub-agents

From the user, 2026-11-01: "claude designers should run at xhigh, if they deem appropriate to run
surveys, those should be run with claude sub-agents at high. Opus 5.5". The designs say so
(`docs/design/calls.md` 1, `docs/design/integration.md` 3, `docs/design/tick.md` 7). The designer
is `fab.designer.ROLES`: cut, contract, decision and retire. This departs from
`execution-modes.md`'s roles table at the user's word; `docs/design/integration.md` 3 records it.

Build:

1. **`fab/calls.py`:** `EFFORTS` gains `cut`, `contract`, `decision` and `retire` at `xhigh`
   (`EFFORT` stays `high` for the skeleton author, its amendments and the structure reviewer;
   amend and settle keep theirs). Update the comment above `EFFORTS`. Test `role_effort` for
   each designer role and for one role that stays, and the `--effort` a designer call passes
   through `claude_argv`.
2. **`fab/roles/cut-run.md`:**
   - "Surveys": a survey is a read-only Claude sub-agent you start with the Agent tool, `model`
     `opus` (Opus 5.5), `effort` `high`, in the background, and only where you judge it worth it;
     each answers its brief and builds nothing. Remove the `codex exec` command. Several may run
     at once.
   - "Designers": a designer sub-agent runs with `model` `opus` and `effort` `xhigh`.
   - Line ~56's "reverse-dependency survey" stays, as such a survey.
3. **`fab/roles/cut-direct.md`:** its Explore sub-agents are started with `model` `opus` and
   `effort` `high`, where you judge a survey worth it.

Check that a test pinning the old role text (`fab/tests/test_designer.py`, `codex exec`) moves
with it. No other role changes.

The user's rule: dogfood. Built by fab's loop (landed through `bin/fab land`); the plan's landing
is `queue` (the cut is started with `--set 'landing="queue"'`). One direct part, one task.
