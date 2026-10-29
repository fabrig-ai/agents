# Starting pipeline sessions

`pipeline/coordinators.toml` maps handles (`[a-z][a-z0-9]{0,7}`) to unique
mailboxes (`s/[a-z0-9][a-z0-9-]*`). Exactly one entry is default: today `dm`,
mailbox `s/dynamic-memory`. Invalid entries and duplicates fail validation.

`names(handle, area)` derives identities; `tools/session/names H [AREA]` prints
`key=value` lines with absolute HOME paths. Areas: skein, smith, jig, temper.
H is the handle, A the area, T the current UTC minute (`%Y%m%dT%H%MZ`).

| Name | Default coordinator | Other coordinator H |
|---|---|---|
| Lead mailbox/session | `lead/A` | `lead/H/A` |
| Branch key (`ready/KEY/<task>`) | `A` | `H-A` |
| Lead scratch | `~/src/fabrig/leads/A` | `~/src/fabrig/leads/H-A` |
| Lead start directory | `~/src/rust/tmp/supervise/leads/A` | `~/src/rust/tmp/supervise/leads/H-A` |
| Coordinator start directory | `~/src/rust/tmp/supervise/coordinator` | `~/src/rust/tmp/supervise/coordinators/H` |
| Coordinator handover | `~/src/rust/tmp/supervise/handover.md` | `~/src/rust/tmp/supervise/coordinators/H/handover.md` |
| Coordinator branches | `coord/<task>` | `H/<task>` |
| Warm-up post name | `coord-next` | `H-next` |
| Coordinator session | `coordinator/dm/T` | `coordinator/H/T` |

Coordinator post mailboxes remain `s/<draft>`; their clone and optional brief
are `repo/` and `brief.md` inside their start directory. Lead delivered-mail
directories replace mailbox slashes with `+` under `~/src/rust/tmp/post/`.

`names director` prints mailbox `director`, session `director/T`, warm-up post
name `director-next`, start directory `~/src/rust/tmp/supervise/director`, and
its `handover.md` and `state.md` paths. Session names differ from post names.
All start directories stay under `~/src/rust/` for Claude's directory trust.

```
tools/session/start lead H AREA [--model M] [--effort E] [--dry-run]
tools/session/start coordinator H [--next] [--model M] [--effort E] [--dry-run]
tools/session/start director [--next] [--effort E] [--dry-run]
tools/session/start wire H|director [--dry-run]
tools/session/start owns NAME
```

Default effort: high for leads, xhigh for coordinators/director. Omit `--model`
unless explicitly supplied; shared settings select the model/context window.
Prompts use strict `string.Template.substitute`; unknown placeholders fail.

Write the lead's scratch `brief.md` first. Preserve inherited `common.md` and
`state.md`; create missing ones as `(empty)` plus newline by sibling rename.
The first Z timestamp in state supplies reconciliation time, else `unknown`.
Clone missing lead `repo/` and `survey/`, or a fresh coordinator's `repo/`,
using `git clone --reference ~/src/fabrig/main git@github.com:fabrig-ai/fabrig.git`.

Before setup, query `claude agents --json`; an exact live name refuses launch.
Only stopped/completed statuses permit reuse (missing status falls back to state).
A fresh director also refuses the hand-started live `director`; `--next` may
warm up alongside that incumbent. Coordinator/director `--next` refuses another
live warm-up with its prefix recorded less than two hours ago. Successful
warm-ups are recorded in `~/.local/state/session-start/warmups.json` (0600,
sibling rename). Serialize concurrent starts; these checks are preflights.

Prepare hooks, then run `claude --bg --name NAME [--model M] --effort E PROMPT`
from the start directory. Print its session id or unrecognized launch report.
Exit codes: 0 success, 1 refused, 2 usage/configuration/command error.

## Hooks and compatibility

`start` writes `<start dir>/.claude/settings.json`; `wire` refreshes the
coordinator plus existing lead directories, or just the director. Replace owned
Stop/SessionStart/UserPromptSubmit entries; preserve other settings/hooks.
Files are written to siblings and renamed.

Probe PATH's `session-context --capabilities` once. With hook-gating, install
shell-quoted PATH commands with a 30-second timeout. Lead gates match their name;
coordinators match `coordinator/H/` (plus `coord-next` for the incumbent);
the director matches `director/` plus `director`, using role `director`.
Without hook-gating, leads get only plain `session-context --hook` as Stop;
coordinators/director get no owned hooks. Print why.

With role-drift, all three events use the same command and repeatable `--watch`
paths; SessionStart has no matcher. Otherwise use Stop and compact SessionStart
without watch arguments. `watched(role, handle, area)` centralizes paths:
main's AGENTS.md, role and operations files, plus lead scratch brief or, for
coordinators, the lead role. Directors watch `monorepo/{director-role,director-records}.md`
under `~/src/rust/tmp/supervise/`. Never watch ledger/backlog.

Hooks cache names privately under SESSION_CONTEXT_STATE (default
`~/.local/state/session-context`); failed lookups stay silent and uncached.
Stop hands over at threshold or compaction; compact SessionStart adds context.
Usage reads the tail; compaction detection scans until the first boundary.
Watched files baseline silently under `seen/SESSION_ID/` (0700 directories,
0600 copies/index, sibling renames). Drift delivers once on prompt submit,
resume/compact SessionStart or inactive Stop, naming up to eight changed headings.
A due handover comes first in the same output. Changes on other events remain
pending. Cleanup runs daily for sessions idle over seven days. Hooks always exit 0.

## Ownership for post wake

`owns NAME` is local: no session query, network or pull; target latency under
100 ms. Exit 0 is silent for owned, unpaused names. Exit 1 prints one stderr
line saying not ours or paused; exit 2 prints one stderr line for an error.
Owned names: registered leads, coordinator mailboxes/warm-up names/session
prefixes, plus `director` and `director/`. Only explicit prefixes use prefix
matching; addresses with `@hel8` are not names.

Any `drafts/*/draft.toml` containing `coordinator="H"`, `state="paused"`
pauses that coordinator and its leads. Read RECORDS_REPO or
`~/src/fabrig/records`; missing records/drafts mean active. The director is
never paused. Executable `fixtures/start-owns-stub NAME` supplies this contract
to post's tests using space-separated exact names in START_OWNS_ALLOW and
START_OWNS_PAUSED (paused wins); wrong arity exits 2.

Dry runs print settings instead of writing; launch previews also print cwd,
argv and prompt before refusal. They run only capabilities and session listing;
wire previews run only capabilities. They create nothing and start nothing.
Director prompts follow monorepo/director-role.md sections 4–6, with read-only
warm-up on director-next until explicit takeover. Keep installed links unchanged.

Tests: `python3 -I -B tools/test_session_start.py` and
`python3 -I -B tools/session/test_session_context.py`, temporary HOME and fakes.
