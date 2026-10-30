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
| Coordinator clone | `~/src/fabrig/coord/next2` | `~/src/fabrig/coord/H/repo` |
| Coordinator brief | `~/src/fabrig/coord/dm/brief.md` | `~/src/fabrig/coord/H/brief.md` |
| Coordinator branches | `coord/<task>` | `H/<task>` |
| Warm-up post name | `coord-next` | `H-next` |
| Coordinator session | `coordinator/dm/T` | `coordinator/H/T` |

Coordinator post mailboxes remain `s/<draft>`. Fresh starts create clone/brief
parent directories as needed, preserving existing files and clones. Lead delivered-mail
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
tools/session/start retire lead H AREA [--yes]
tools/session/start retire coordinator H [--yes]
tools/session/start owns NAME
tools/session/start names [--json]
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

Manual context measurements run `session-context` from the session's start
directory. It selects `CLAUDE_CODE_SESSION_ID` when set. Without that variable,
exactly one transcript must have been written in the project's last 30 minutes;
if several have, pass a session id explicitly (exit 2 lists their ids and mtimes).

## Hooks and compatibility

`start` writes `<start dir>/.claude/settings.json`; `wire` refreshes the
coordinator plus existing lead directories, or just the director. Replace owned
session-context and session-reap-hook commands (including legacy reap-hook paths) in Stop/SessionStart/UserPromptSubmit/SessionEnd;
preserve foreign commands and their order, even inside mixed hook groups.
Files are written to siblings and renamed.

Probe PATH's `session-context --capabilities` once. With hook-gating, install
shell-quoted PATH commands with a 30-second timeout. Lead gates match their name;
coordinators match `coordinator/H/` (plus `coord-next` for the incumbent);
the director matches `director/` plus `director`, using role `director`.
Without hook-gating, leads get only plain `session-context --hook` as Stop;
coordinators/director get no context hooks. Print why. All Claude roles still
get the reaper hooks described below.

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


When `session-reap-hook` resolves on PATH, every Claude role also gets
`session-reap-hook ROLE_NAME` on every SessionStart source and on SessionEnd,
regardless of context capabilities. `tools/installed` maps that stable PATH name
to `session/reap-hook`; fleet-sync manages its link through the current release.
Published commands never embed a release or checkout path.

If the executable is absent, launch/wire omits both reap hooks, removes obsolete
owned reap hooks, and prints why. A missing command is not silent in Claude Code:
its [hooks reference](https://code.claude.com/docs/en/hooks#other-exit-codes)
describes a non-blocking hook-error notice, including shell exit 127 for missing
executables. Deploy with fleet-sync first, then `session-start wire H` for each
coordinator and `session-start wire director` to enable or migrate live settings.
Both the old absolute `reap-hook` command and `session-reap-hook` are owned;
foreign hook commands keep their order. The hook reads Claude's
JSON from stdin. Start records `claude-session`, the full session id and
`~/.claude/jobs/<first eight id characters>`. Owner comes from session-context's
`names.json` cache (including short/full id matches), with the launcher's role
name as fallback; the hook never queries Claude. End records the same id and
starts `systemctl --user start --no-block reap.service`. Missing reap, command
failures and malformed input are silent; the hook always exits 0, with a 1.5 s
budget and 0.4 s command timeouts. Resumed starts safely repeat the start record.
`wire H` / `wire director` refresh these hooks too. Codex leads use codex-run's
lifecycle instead of Claude hooks.

## Retiring dropped roles

`start retire lead H AREA` and `start retire coordinator H` print the derived
paths and every observed refusal, then exit 0 without writing anything. Keep H
in `pipeline/coordinators.toml` until retirement has been handed over. Lead paths
are scratch (including clones) and start directory. Coordinator paths are clone,
brief, start directory (including handover), plus handover's directory if separate.
A default coordinator's shared start directory always refuses retirement; any
path overlapping another role's paths, including through symlinks, also refuses.

Retirement refuses live role names/prefixes and aliases, slots claimed by the
role's mailbox, and (for coordinators) held leases. Leads also refuse any live
same-area successor under another coordinator, or an active Codex owner unit.
Unavailable or malformed observations fail closed. Retire queries `claude agents
--json`, `claim list`, and for coordinators `lease list --json`; it does not query
or change the records repository.

Add `--yes` to hand the paths to reap: start and end records of kind
`retired-scratch`, followed by a nonblocking start of reap.service. The record
owner is `lead/H/AREA` (incumbent: `lead/AREA`) or the stable coordinator role
`coordinator/H`; the id is `retire-<owner with / replaced by +>-<UTC timestamp>`.
Only after successful handover are matching launcher warm-up records removed.
No scratch, clone or start directory is deleted by the launcher. Missing reap
refuses `--yes`, as do all blockers (exit 1; command/configuration failures exit 2).
Serialize retirement with launches and role reassignment: observations are preflights.
Removing a dropped coordinator from `pipeline/coordinators.toml` remains a
**separate manual commit**, after handover; retirement never edits the registry.

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

`start names --json` supplies watch's JSON array; unflagged `start names` also
returns JSON. Coordinator rows include handle, mailbox, warmup_name, name_prefix,
legacy_names, aliases, start_dir, supervisor and paused. Lead rows add name,
area, branch_key, scratch and coordinator_mailbox. The director has no supervisor;
ops, s/deploy and s/multi-coord have always_watched=true and supervisor director.
The multi coordinator matches `s/multi-coord/<stamp>` or `s/multi-coord-next`. Pause state
uses the same local records reader as owns, also inherited by leads. No network
or session query; target latency under 150 ms. `tools/session/names` is unchanged.

Due handovers record `fired/SESSION_ID.json` under SESSION_CONTEXT_STATE, with
session_id, name, role, reason and first_fired/last_fired (UTC RFC3339). First
firing stays fixed; later firings update the last time. Reason is the handover
message, excluding drift. Ungated lookups may leave name/role null. Files are
0600, sibling-renamed under a directory lock; write failures preserve hook output.
`session-context --fired [--json]` lists them read-only (JSON array; malformed
files skipped). Capability: fired-markers. These are local evidence, not records
sessions-stream events; a collector must adapt them for watch's event input.

Dry runs print settings instead of writing; launch previews also print cwd,
argv and prompt before refusal. They run only capabilities and session listing;
wire previews run only capabilities. Retire previews perform their read-only
session/claim/lease checks instead. They create nothing and start nothing.
Director prompts follow monorepo/director-role.md sections 4–6, with read-only
warm-up on director-next until explicit takeover. Keep installed links unchanged.

Tests: `python3 -I -B tools/test_session_start.py` and
`python3 -I -B tools/session/test_session_context.py` and
`python3 -I -B tools/session/test_reap_hook.py`, temporary HOME and fakes.

Coordinators may set `lead_kind = "claude" | "codex"` (default `claude`);
`u` uses Codex. Lead inventory rows include `kind`; Codex rows have `unit`
(systemd string escaping) and `owner_state` instead of `start_dir`.
Codex leads preserve the same brief/scratch/common/state and clone preparation,
then run `codex-run owner --effort E [--model M] NAME <scratch>/brief.md`
(default effort `high`). No start directory or Claude hook is created. Missing
briefs and active user units refuse launch; dry runs print argv and check only
the unit. `wire` announces and skips every Codex lead.
