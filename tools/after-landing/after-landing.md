# after-landing command reference

Contract: `docs/design/after-landing.md`, sections 1–7 and 9.
Implementation status: `docs/design/after-landing.status.md`.

## Syntax

```sh
tools/after-landing/after-landing [OPTIONS] {follow,once,status}
```

- `follow`: poll, run pending work and retry delivery until stopped.
- `once`: one poll/work/delivery cycle; a run may include its bisection.
- `status`: print a JSON summary without creating state or calling services.
- `once --dry-run`: fetch `origin/main` and print its tip, suspects from
  `HEAD~3..origin/main` and configured profiles. This changes git fetch state,
  requires that history, and does not run tiers, write runner state or post.

## Options and defaults

Runtime paths below are relative to the invoking user's HOME when prefixed
with `~`. Path options expand `~` and become absolute.

| Option | Default / meaning |
|---|---|
| `--slot PATH` | `~/src/fabrig/slots/9`; checkout used for tests |
| `--state-dir PATH` | `~/src/fabrig/after-landing`; must be outside the slot |
| `--tiers PATH` | `tiers.toml` beside the command; ordered `profiles` array |
| `--poll-interval SECONDS` | `60`; finite positive number |
| `--post COMMAND` | `post`, resolved through PATH |
| `--record COMMAND` | `~/src/fabrig/current/tools/records/record` |
| `--registry COMMAND` | `~/src/fabrig/current/tools/session/start` |
| `--heavy COMMAND` | `~/src/fabrig/main/tools/heavy/heavy` |
| `--tiers-run PATH` | `<slot>/tools/tiers/run` |
| `--trim PATH` | `<slot>/tools/slots/trim` |
| `--lifetime PATH` | `~/src/fabrig/main/tools/slots/lifetime.py` |
| `--ops ADDRESS` | `ops@hel8` |
| `--coordinator ADDRESS` | `s/dynamic-memory@hel8`; coverage recipient |
| `--host NAME` | local hostname; records/log builder identity |
| `--dry-run` | preview only; requires `once` |
| `-h`, `--help` | print usage and exit |

Command options without a slash resolve through PATH; command values otherwise
expand `~` and become absolute. Numeric slots directly under
`~/src/fabrig/slots` acquire the slot lifetime lease. The state directory must
be owned by the user, mode 0700, with no symlink in its path. State is private
and replaced atomically, under `runner.lock`; guardians retain `execution.lock`
and inherited leases until heavy completion is known.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | status, dry run or help completed; or `once` has no active run/bisection |
| `1` | `once` retains an active run or bisection |
| `2` | argument/setup error, uncaught operational fault, or rewritten-history stop |

A completed red or partial attempt can exit 0. A queued retry or undelivered
outbox is not itself exit 1. Read verdict and pending state instead of treating
exit 0 as a green verdict. `follow` catches loop faults, queues an ops notice
and continues; a rewritten-history stop exits 2.

## State and output fields

`<state-dir>/state.json` is an internal recovery record, not an editing API.

| Field | Meaning |
|---|---|
| `version` | starts at 1; becomes 2 when the first bisection is scheduled; accepts both |
| `slot` | absolute checkout path; another slot is refused |
| `seen`, `cursor` | last observed tip; last tip completed without pair faults |
| `queue` | tips with suspects, coalesced tips, observation time, attempt and saved pair results |
| `tests` | JSON-encoded identity keys to last executed `pass`/`red` and commit |
| `active` | current tip/attempt, profiles, baseline, pair results, updates, events, selections, observations, invocation and start time; otherwise null |
| `bisect` | pending phase with tip/attempt, run id, routes, groups, absolute deadline, invocation count, probe, invocation, completion and arriving tips; otherwise null |
| `outbox` | groups of records and posts, publication/delivery flags, optional unresolved notification and preceding-group dependency (`after`) |
| `stopped` | rewritten-history stop; ops must reset the cursor before polling resumes |
| `fault_episode` | current operational-fault notification id, or null |
| `hour` | coverage interval start, seen/completed/coalesced counts, trim bytes and bisection seconds |
| `last_run` | last run id, verdict and faulted profiles, or null |
| `lease_holds` | lifetime tokens retained across interrupted invocations |
| `trim_pending` | verdict/phase id and whether trim was started, or null |
| `trim_fault_episode` | trim fault notification id until a successful trim |
| `last_trim` | last trim id, bytes freed, error and any captured command result |

`status` outputs `cursor`, `seen`, `waiting` (queued tips), `active` (tip,
attempt, `waiting_for_end`), `last_run`, `stopped` and `undelivered` (outbox
count). It does not expose the bisection phase; inspect the recovery record
when that detail is needed. Empty status prints defaults without creating files.

Invocation artifacts live in private `run-*` directories under the state
directory: output log, JUnit XML, generated nextest configuration, guardian
spec/result/waiting files and heavy shim. `details/*.json` holds immutable
content-addressed evidence referenced by events and posts. `post-body.txt` is
the current outgoing body. These runtime files are outside the mutable slot.

## Subcommands invoked and limits

- Fetch: `git fetch -q origin main`; checkout: detached, forced, then
  `git clean -fd` within the slot.
- Tier run: `<slot>/tools/tiers/run TREE TIER -- --config-file PATH`, with
  `-E FILTER` for isolated confirmations and grouped probes. JUnit
  `testsuite.name` is the binary id; `testcase.name` is the test name.
- Exact filter: `binary_id(=BINARY) & test(=TEST)`; identities must match
  `[A-Za-z0-9_:.-]+`. Group filters join parenthesized expressions with ` | `.
- Normal tier exits 0/100 are parsed as pass/test failure; other exits fault.
  Bisection additionally recognizes nextest build-failure exit 101 as
  unbuildable. A normal confirmation must execute exactly one matching test.
- Each invocation is bounded by the profile global timeout plus 30 minutes;
  bisection also has a persisted 45-minute deadline and 16-invocation budget,
  including confirmations. Cancellation calls `heavy --cancel TOKEN` from
  the submitting slot and waits for known completion. `HEAVY_CLASS=background`
  is set for test execution.
- Trim: `python3 -I -B <slot>/tools/slots/trim --older 0 <slot>`; `--trim`
  replaces the script. Freed-space output is parsed at one MB precision.
- Registry: `session/start names --json`; fallback addresses come from the
  run tip's `tools/queue/leads.txt` snapshot, including during historical probes.
- Records: `record append --as after-landing --batch HOST`, JSONL on stdin.
  Wire events stay below 16 KiB; oversized data goes into private detail files.
  Compacted event ids exceeding 1024 bytes become deterministic `sha256:` ids.
- Post: `post send --as after-landing ADDRESS SUBJECT BODY_FILE`;
  exits 0 and 3 count as delivered. Other results remain pending.

## Service invocation

`fleet/units/after-landing.service` declares:

```ini
# fleet-sync: start-once
Type=exec
ExecStart=/bin/bash -lc 'exec "$$HOME/src/fabrig/current/tools/after-landing/after-landing" --slot "$$HOME/src/fabrig/slots/4" --host hetzner7 follow'
Restart=on-failure
RestartSec=60
RestartPreventExitStatus=2
WorkingDirectory=%h
```

The snippet combines the fleet-sync marker and service settings; see the unit
for its complete sections. Host assignment is in `fleet/hosts.toml` and
`fleet/units/roles.toml`. Ops claims the slot before activation using
`claim claim HOST N ops after-landing`. Deployment status and its limits are in
`docs/design/after-landing.status.md`.
