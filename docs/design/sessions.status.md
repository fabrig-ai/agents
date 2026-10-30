# Sessions status

2026-10-30. Owner: s/multi-coord. Baseline: origin/main `1335337`.
Contract: `docs/design/sessions.md`, sections 2–4.

## Present

- Launcher roles, warm-ups, names, owns, wire and Codex-owner leads exist.
- **Context defaults to 85%.** Ordinary turns at or above the threshold ask
  for handover repeatedly; compaction also asks. Active recursive Stop hooks
  are suppressed. Without role watches, a quiet Stop below threshold returns
  before name lookup and creates no context state. Watched hooks retain their
  independent role-drift baseline and delivery behavior.
- Capability-gated hooks, role drift and locked fired markers exist. The sessions
  collector already turns markers into durable handover-needed events and
  records owner unit transitions and threshold crossings.

## Gaps and departures

- **Cleanup hooks and retire have not landed.** `mc/reap-hooks` is in flight;
  there is no `retire` launcher command or `tools/session/reap-hook` on this
  baseline. Existing daily pruning of role-drift snapshots older than seven
  idle days is unrelated to stopping sessions or reclaiming live resources.
- **Task-header prompt changes have not landed here.** See
  `docs/design/pipeline.status.md`. Codex owners receive the written brief
  directly rather than the rendered Claude lead prompt.
- **Lifecycle records are absent.** No brief, handover or closing commit is
  made by start or `--next`; see `docs/design/records.status.md`.
- **Published hooks need an explicit refresh.** Updating code does not rewrite
  existing project settings. `tools/session/start wire H` or `wire director`
  publishes settings for existing Claude start directories. This docs change
  requires no machine action.
- **External role paths remain.** The launcher still watches and prompts from
  fabrig and the monorepo working plans. The intended role-file move is tracked
  in `docs/design/pipeline.status.md`.

## Verification

`tools/test_session_start.py` and `tools/session/test_session_context.py` cover
launch refusal, warm-up, hook wiring, drift, repeated handover and fired markers
with temporary HOME and fake services. The complete gate is `bash tools/check.sh`.
