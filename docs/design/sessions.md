# Sessions

2026-10-30. Owner: s/multi-coord. Code: `tools/session/start`,
`tools/session/session_lib.py`, `tools/session/names`,
`tools/session/session-context` and `prompts/`. Command reference:
`tools/session/start.md`. Code departures: `docs/design/sessions.status.md`.

## 1. In one page

- **Start through the launcher.** It derives names, prepares working files and
  clones, publishes hooks, and refuses an already live identity.
- **A successor warms up before taking over.** The incumbent keeps serving its
  mailbox until it explicitly transfers it. A lead ends its part or hands its
  current files back to its coordinator.
- **Context asks for handover at 85%.** Below that, ordinary Stop turns are
  silent. At or above it, every turn asks again. Compaction also asks; this is
  the user's 10-30 decision. The current threshold gap is in the status file.
- **Changed role text is delivered separately.** Notices identify changed
  sections. Fired markers let the collector distinguish actual handover
  requests from context measurements.

## 2. Launch and succession

**Use registry names** (`docs/design/pipeline.md`, section 3). The interface is:

```text
tools/session/start lead H AREA [--model M] [--effort E] [--dry-run]
tools/session/start coordinator H [--next] [--model M] [--effort E] [--dry-run]
tools/session/start director [--next] [--effort E] [--dry-run]
tools/session/start names --json
tools/session/start wire H|director [--dry-run]
tools/session/start owns NAME
```

**A lead starts from a written brief.** Its scratch contains brief, common and
state files and separate repo and survey clones. Preserve inherited files;
create missing common/state files by sibling rename. Clone missing checkouts
from fabrig using the reference clone. Reconcile state against real runs,
claims, reports and ready refs before continuing.

**Claude starts get project hooks.** The launcher checks exact live names via
`claude agents --json`, prepares the start directory and runs the rendered
prompt with `claude --bg`. Default effort is high for leads, xhigh for
coordinators/director. Model choice is left to shared settings unless supplied.
Dry-run previews preparation and probes without launching or writing files.

**`--next` means read-only warm-up** for coordinators and director. The successor
uses its warm-up post name and asks the incumbent questions, then reports ready.
It takes the real mailbox only on explicit takeover. A recent live warm-up
blocks another for two hours. The launcher records successful warm-ups privately.
It does not stop the incumbent or transfer the mailbox itself.

**Codex leads are owners.** A registry `lead_kind = "codex"` selects
`codex-run owner`, using the lead's name and scratch brief. Preparation preserves
common/state and the two clones. A live user unit refuses launch. These leads
have no Claude start directory or Claude hooks; `wire` skips them. Inventory
exposes kind, unit and owner state. The collector measures owners through
`session-context --owner NAME` and observes their user units.

## 3. Published hooks and context

**Publish settings atomically** into each Claude start directory's
`.claude/settings.json`. `wire` refreshes a coordinator and its existing Claude
lead directories, or the director alone. Preserve unrelated settings. Owned
Stop, SessionStart and UserPromptSubmit entries are replaced together.

**Probe capabilities before wiring.** With hook-gating, shell-quoted commands
match the lead's exact name or the coordinator/director's explicit prefixes and
legacy aliases. Without it, only leads get a plain Stop hook; other role hooks
are skipped with a reason. Role-drift adds watched files on all three events;
otherwise SessionStart matches compaction only. Each command has a timeout.

**Handover is persistent advice, not an automatic restart.** Each ordinary Stop
at 85% or more blocks that stop with the role's handover instructions, every
turn until it acts. Below 85%, there is no context reminder unless compaction
has occurred. Compact SessionStart supplies the same instructions as additional
context. Compaction remains a handover cause even below threshold. A recursive
Stop already active because of the hook is exempt to avoid a hook loop.

**Manual readings return a signal.** `session-context` uses the explicit session
id or `CLAUDE_CODE_SESSION_ID`. Without either, it requires one recent transcript
in the current project; ambiguity is an error, never a guess. Exit 0 means below
threshold, 3 means hand over, and 2 means selection/reading failed. Claude usage
comes from the transcript's latest call; owner readings use the Codex thread's
own context window. Hooks always exit 0 and express their result in hook JSON.

## 4. Drift and fired evidence

**Watch role contracts, not changing ledgers.** Coordinator/lead watches include
fabrig's AGENTS, role and operations text; a lead also watches its brief and a
coordinator the lead role. The director watches the current external director
role and records plans. Baseline silently on first sight. Deliver changed
headings once at prompt submit, resume/compact SessionStart or ordinary Stop.
Pending changes wait for a delivery event. A due handover appears first.

**A fired marker records the request.** Private per-session JSON holds identity,
role, reason, first firing and last firing. Later requests preserve the first
time and update the last. Files are locked and replaced atomically. A failed
marker write must not hide a due request. `session-context --fired --json` lists
markers read-only; the collector projects them as `handover-needed` events.
A `files current` lead post or a successor acknowledges the request for watch
(`docs/design/watch.md`, sections 2–4). Raw context samples do not prove firing.

**`owns` and `names` are local contracts.** They use the registry and local draft
pause state, without querying sessions or fetching records. `owns` returns 0
silently when owned and unpaused, 1 when not, 2 on error. Inventory also names
supervisors and always-watched ops/deploy roles for wake and watch.

## 5. Later

- Land cleanup hooks and `retire` from `mc/reap-hooks`, then describe the lifecycle.
- Commit briefs, handovers and part closings through records at lifecycle points.
- Replace file handovers with the role state and journal in
  `docs/design/records.md`, section 3.
