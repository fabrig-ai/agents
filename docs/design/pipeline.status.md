# Pipeline status

2026-10-30. Owner: s/multi-coord. Baseline: origin/main `1335337`.
Contract: `docs/design/pipeline.md`, sections 2–5.

## Present

- Registry, derived names, JSON inventory, launch prompts and the standalone
  lease tool are here. The registry currently has dm, q and u; u selects Codex
  leads. The rules also describe roles not registered as active coordinators.
- Agents' gate and landing command exist. This branch changes docs only and
  does not invoke landing or deployment.

## Gaps and departures

- **The repository split is incomplete.** The working plans say roles and
  codex-run, post, slots, heavy and queue tools move here. They have no live
  counterparts here yet. Prompts and drift watches still refer to fabrig's
  `agents/{lead,coordinator,operations,ledger,backlog}.md` as external inputs.
  Director prompts still use the external monorepo role/records plans under
  `~/src/rust/tmp/supervise/monorepo/`. These are runtime dependencies of today's
  launcher, not files in this repository or dependencies on this tree's `old/`.
- **Task headers are a pipeline requirement ahead of local prompt coverage.**
  `tools/records/record-collect` parses them, with legacy prose fallbacks. This
  checkout has no codex-run implementation or header checker, and
  `prompts/lead.md` does not fill a header template. The working plan names
  `codex-run header TASK` and warning-only task launch; those are external
  commands, not verified implementations here. `mc/task-header` is in flight.
- **Lease checks are advisory integration.** The standalone tool refuses bad
  lease mutations and returns outside-subject failures from `check`, but agents
  has no precheck or fabrig merge-queue implementation to enforce them. The
  early plan's `tools/slots/lease` path and positional command grammar were
  replaced by `tools/lease` and the syntax in `tools/lease.md`.
- **Leases cover fabrig tree documents only.** The current subject validator
  accepts skein/smith/jig/temper design and foundation paths. Root agents
  `docs/design/` paths cannot yet be leased with this tool.
- **Pause handling is partial.** Inventory and `owns` read local records and
  suppress paused pipelines for wake/watch. `start coordinator` itself does
  not enforce pause, contrary to the director-records plan's durable start ban.
- **Escalation follows the later director decision.** The older
  multi-coordinator plan sent unresolved disputes straight to the user. The
  later director and coordinator rules route them through the director.
- **Keepers are not yet consolidated here.** The older plan gave incumbent
  coordination the shared coordinator/lead/implementer text, ops the operations,
  operator and ledger text, and both the backlog. Preserve those external
  boundaries until their owner moves the files; this branch edits none of them.
- **Director automation remains partial.** The launcher and judgement commands
  exist; `record digest`, automatic retirement and a complete scheduling/pause
  lifecycle do not. Records' remaining gaps are `docs/design/records.status.md`.

## Verification

Sources: `pipeline/coordinators.toml`, `prompts/`, `tools/session/start`,
`tools/session/session_lib.py`, `tools/lease`, `tools/land`, `tools/check.sh`.
The gate covers launcher, names, lease and landing-related fixture tests.
