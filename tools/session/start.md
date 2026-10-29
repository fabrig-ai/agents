# Starting coordinators and leads

`pipeline/coordinators.toml` is the identity registry. Each table is a handle
matching `[a-z][a-z0-9]{0,7}`, with a unique mailbox matching
`s/[a-z0-9][a-z0-9-]*`. Exactly one table has `default = true`; other entries
may omit `default`. Duplicate handles (including duplicate TOML tables), duplicate
mailboxes, invalid values and unknown fields fail validation. The incumbent is
`dm`, mailbox `s/dynamic-memory`; addresses append `@hel8`.

`names(handle, area)` in `session_lib.py` derives all identities. Its command
`tools/session/names H [AREA]` prints `key=value` lines with absolute paths under
the current HOME. Areas are `skein`, `smith`, `jig`, `temper`. Without AREA it
prints just the coordinator values. Add a registry entry to start a new pipeline;
never assemble names in callers.

In this table H is the handle, A the area, and `~` is HOME:

| Name | Default coordinator | Other coordinator H |
|---|---|---|
| Lead mailbox / session | `lead/A` | `lead/H/A` |
| Branch key (`ready/KEY/<task>`) | `A` | `H-A` |
| Lead scratch | `~/src/fabrig/leads/A` | `~/src/fabrig/leads/H-A` |
| Lead start directory | `~/src/rust/tmp/supervise/leads/A` | `~/src/rust/tmp/supervise/leads/H-A` |
| Coordinator start directory | `~/src/rust/tmp/supervise/coordinator` | `~/src/rust/tmp/supervise/coordinators/H` |
| Coordinator handover | `~/src/rust/tmp/supervise/handover.md` | `~/src/rust/tmp/supervise/coordinators/H/handover.md` |
| Coordinator branches | `coord/<task>` | `H/<task>` |
| Successor warm-up name | `coord-next` | `H-next` |

Coordinator session names equal their `s/<draft>` mailbox. The coordinator's own
clone and brief are `repo/` and `brief.md` inside its start directory. Start
directories stay under `~/src/rust/` for Claude's directory trust. Lead delivered
mail lives in `~/src/rust/tmp/post/MAILBOX/cur/`, replacing mailbox slashes with
`+`.

## Launch behavior

```
tools/session/start lead H AREA [--model M] [--effort E] [--dry-run]
tools/session/start coordinator H [--next] [--model M] [--effort E] [--dry-run]
```

Defaults are `opus` / `high` for leads and `opus` / `xhigh` for coordinators.
Write the lead's scratch `brief.md` first: a missing brief refuses the launch.
Rendering uses strict `string.Template.substitute`: missing or malformed
placeholders fail. The lead prompt's state timestamp is the first Z timestamp
found while reading `state.md` in order, or `unknown`.

Before making directories, writing files or cloning, query `claude agents
--json`. A matching session with any status except `stopped` or `completed`
refuses launch (a missing status falls back to state and otherwise is treated as
live). Invalid session-list output fails closed. Live-session checking is a
preflight; concurrent invocations must be serialized by the coordinator.

For a lead, create the start directory and any absent `common.md` / `state.md`
with `(empty)` plus a newline, publishing each through a sibling temporary file
and rename; preserve existing files. Clone absent `repo/` and `survey/` using
`git clone --reference ~/src/fabrig/main git@github.com:fabrig-ai/fabrig.git`.
A fresh coordinator creates its start directory and clones its own absent
`repo/` the same way; its prompt reads a handover if present, role files from its
clone and the plans its brief names. A warm-up creates only the start directory,
reads its incumbent's handover and waits on its own warm-up mailbox.

Launch with argv `claude --bg --name NAME --model M --effort E PROMPT`, using the
derived start directory as cwd. Print the reported session id (JSON or text);
unrecognized successful output is printed whole. Nonzero Claude or git results
are errors. Exit codes: 0 success, 1 refused, 2 usage/configuration/command error.

`--dry-run` prints cwd, full shell-quoted argv and the rendered prompt before
the live-session check; it creates nothing, skips clones, and runs only
`claude agents --json`. Live sessions still cause exit 1 after printing.

Run `python3 -I -B tools/test_session_start.py`. Tests use temporary HOME and
fake Claude/git commands, checking names, validation, state preservation,
rendering, refusals, flags, cwd, launch reports and dry-run immutability.
