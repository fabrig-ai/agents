# Starting coordinators and leads

`pipeline/coordinators.toml` is the identity registry. Each table is a handle
matching `[a-z][a-z0-9]{0,7}`, with a unique mailbox matching
`s/[a-z0-9][a-z0-9-]*`. Exactly one table has `default = true`; other entries
may omit it. Invalid values, unknown fields and duplicate handles/mailboxes fail.
The incumbent is `dm`, mailbox `s/dynamic-memory`; addresses append `@hel8`.

`names(handle, area)` in `session_lib.py` derives all identities. Its command
`tools/session/names H [AREA]` prints `key=value` lines with absolute HOME paths.
Areas are `skein`, `smith`, `jig`, `temper`; omitting AREA prints coordinator
values. Add a registry entry for each pipeline; callers never assemble names.

H is the handle, A the area, and T the current UTC minute, `%Y%m%dT%H%MZ`:

| Name | Default coordinator | Other coordinator H |
|---|---|---|
| Lead mailbox / session | `lead/A` | `lead/H/A` |
| Branch key (`ready/KEY/<task>`) | `A` | `H-A` |
| Lead scratch | `~/src/fabrig/leads/A` | `~/src/fabrig/leads/H-A` |
| Lead start directory | `~/src/rust/tmp/supervise/leads/A` | `~/src/rust/tmp/supervise/leads/H-A` |
| Coordinator start directory | `~/src/rust/tmp/supervise/coordinator` | `~/src/rust/tmp/supervise/coordinators/H` |
| Coordinator handover | `~/src/rust/tmp/supervise/handover.md` | `~/src/rust/tmp/supervise/coordinators/H/handover.md` |
| Coordinator branches | `coord/<task>` | `H/<task>` |
| Successor warm-up post name | `coord-next` | `H-next` |
| Coordinator session (fresh or warm-up) | `coordinator/dm/T` | `coordinator/H/T` |

Coordinator post mailboxes remain `s/<draft>`. Prompts distinguish session names
from post names. The coordinator's own clone and optional brief are `repo/` and
`brief.md` inside its start directory. Start directories stay under `~/src/rust/`
for directory trust. Lead delivered-mail directories replace mailbox `/` with `+`
under `~/src/rust/tmp/post/`.

```
tools/session/start lead H AREA [--model M] [--effort E] [--dry-run]
tools/session/start coordinator H [--next] [--model M] [--effort E] [--dry-run]
tools/session/start wire H [--dry-run]
```

Default effort is `high` for leads, `xhigh` for coordinators. Without `--model`,
omit the model flag so shared Claude settings select the model and context window
(currently `opus[1m]`). An explicit `--model M` passes that value unchanged.

Write the lead's scratch `brief.md` first. Missing briefs refuse launch. Strict
`string.Template.substitute` rejects unknown/malformed placeholders. The first
Z timestamp in `state.md` supplies the lead's reconciliation time, else `unknown`.
Query `claude agents --json` before setup; any matching session whose status is
neither `stopped` nor `completed` refuses launch. Missing status falls back to
state and otherwise counts as live; malformed listings fail closed.
`--next` also refuses a live `coordinator/H/` session recorded as a warm-up less
than two hours ago. Successful warm-ups are recorded with their start time and
session id in `~/.local/state/session-start/warmups.json` (0600, sibling rename).
Coordinators must serialize concurrent starts; these checks are preflight checks.

Create missing lead `common.md` / `state.md` as `(empty)` plus newline, by sibling
rename, preserving inherited files. Clone absent lead `repo/` and `survey/`, or a
fresh coordinator's `repo/`, with `git clone --reference ~/src/fabrig/main
git@github.com:fabrig-ai/fabrig.git`. Prepare project hooks, then execute
`claude --bg --name NAME [--model M] --effort E PROMPT` in the derived start
directory. Print its reported session id, or the whole unrecognized launch report.
Exit codes: 0 success, 1 refused, 2 usage/configuration/command error.

## Project hooks and compatibility

`start` writes `<start dir>/.claude/settings.json` before launching. `wire` writes
the coordinator's file and each existing lead start directory's file, starting
nothing. Replace the owned `Stop`, `SessionStart` and `UserPromptSubmit` entries, preserving all
other settings and hooks. Files are published by sibling rename.

Probe PATH's `session-context --capabilities` once per invocation. With
`hook-gating`, install shell-quoted PATH commands using `--hook --role ROLE`,
`--coordinator ADDRESS --handover PATH --handle H` and a 30-second hook timeout.
Lead gates use `--name lead/...`; coordinator gates use `--name-prefix
coordinator/H/`, plus `--name coord-next` for the default incumbent. SessionStart
uses matcher `compact`. If the probe fails or lacks `hook-gating`, explain why:
leads get only plain `session-context --hook` as Stop; coordinators get neither
owned hook. New hook options never reach the legacy copy. Do not change installed
links until the factory move.

With `role-drift` too, all three events use the same command with repeatable
`--watch` paths; SessionStart has no matcher. `watched(role, handle, area)` holds
the paths: main's AGENTS.md, the role and operations files, plus a lead's scratch
brief or, for a coordinator, the lead role. Ledger and backlog are excluded.
Without this capability, retain the launch-2 entries and pass no watch arguments.

Watched files get a silent first baseline under `seen/SESSION_ID/` in the state
directory, with 0700 directories, 0600 copies/index and sibling renames. Notices
name changed level-2/3 headings (eight maximum) and deliver once on prompt submit,
resume/compact SessionStart or inactive Stop; a due handover comes first in the
same output. Non-delivery events leave changes pending. Cleanup runs daily and
removes sessions idle over seven days.

`session-context` caches resolved session names in a private, atomically replaced
`names.json` under `SESSION_CONTEXT_STATE` (default
`~/.local/state/session-context`). Stop blocks once usage reaches the threshold
or any compaction exists; compact SessionStart adds the role's handover message.
Usage reads only the transcript tail; compaction detection scans records until a
boundary is found. Lookup failures/timeouts remain silent and uncached. Hook mode
always exits 0; the existing interactive Claude/Codex modes retain their behavior.

`--dry-run` prints settings instead of writing them. Launch dry runs also print
cwd, full argv and prompt before live-session refusal; they run only the capability
probe and session listing. Wire dry runs run only the probe. Neither creates files
or starts sessions. Tests: `python3 -I -B tools/test_session_start.py` and
`python3 -I -B tools/session/test_session_context.py`, with temporary HOME and fakes.

## Ownership for post wake

`tools/session/start owns NAME` is a local check, with no session query or network.
Exit 0 is silent: NAME belongs to an unpaused pipeline. Exit 1 prints one stderr
line saying `not ours` or `paused`; exit 2 prints one stderr line for an error.
Owned names are every registered lead, coordinator mailbox, warm-up name and
`coordinator/H/` prefix, plus `director` and the `director/` prefix. Match names
exactly except those explicit prefixes; post addresses with `@hel8` are not names.
A matching `coordinator = "H"`, `state = "paused"` in any
`drafts/*/draft.toml` pauses that coordinator and its leads. Read `RECORDS_REPO`,
default `~/src/fabrig/records`, without pulling. Missing records/drafts mean active;
the director is never paused. Target latency is below 100 ms.

For post's offline tests, executable `fixtures/start-owns-stub NAME` implements
the same exit/output contract using space-separated exact names from
`START_OWNS_ALLOW` and `START_OWNS_PAUSED`; paused wins. Wrong arity exits 2.
