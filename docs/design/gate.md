# Gate

2026-10-30. Owner: s/deploy. Code: `tools/check.sh`, `tools/gate.py`,
`tools/land`, `tools/periodic`. Status: `docs/design/gate.status.md`.

## 1. In one page

- **Land on a claimed builder.** `tools/land` rebases, ships HEAD as a complete
  git bundle, checks selected tests at nice 19 and idle IO, then fast-forwards
  main. Agents work must not consume fabrig's pipeline capacity unclaimed.
- **Keep the merge below 60 seconds.** `tools/gate.toml` declares ownership,
  selection and CPU/wall budgets. Enforcement starts report-only; only the
  user turns it on. No force push, queue, or production service calls in tests.
- **Tests use disposable HOME and TMPDIR.** Each file has a fresh interpreter.
  Shared fixture classes carry no inherited test cases; each behavior runs once.
- **Main deploys itself.** Hosts poll main; this entrypoint remains policy,
  rather than remote branch protection (`docs/design/fleet.md`, section 3).

## 2. Check and budgets

`tools/check.sh [--tier gate|periodic] [--changed BASE] [FILES ...]` defaults
 to gate, excluding `test_*_periodic.py`; periodic selects only those files.
Explicit files override tier discovery. Changed selection uses
`git diff --name-only BASE...HEAD` and the glob map, plus the always-run smoke
set. Docs and Markdown select smoke; unmapped tools select their directory's
files (all files if empty); other unknown paths select every gate file.

Up to eight workers share a per-host lock. They use nice 19 and idle IO when
ionice is available. `wait4` reports each child's user+system CPU, including its
waited descendants, and wall time. The table names file, owner, CPU, wall,
budget and status. `--json PATH` saves the same observations atomically.
Defaults: file CPU 8 s, file wall 15 s, tier CPU 100 s, merge wall 60 s.
With enforcement enabled, CPU overruns fail by name and workers also receive
an OS CPU ceiling. Wall expiry kills the file's process group and warns
starved/unobserved; it never turns an unexecuted assertion into a pass. A
landing refuses an incomplete gate. Repair tier membership or inefficiency
before asking the user about budgets (fabrig testing-strategy, section 8.1).

## 3. Land and races

`tools/land [--host NAME] [--local] [--dry-run]` refuses dirty trees, main and
detached HEAD, then fetches and performs a plain rebase on origin/main.
Auto selection tries hetzner3, hetzner7, hetzner6 (h3/h7/h6 aliases), matching
pool slots from fabrig's slots inventory against hel8's central free list.
Hel8's SSH target comes from `fleet/hosts.toml`. Atomic claim admission is
still authoritative if that list races. Claims use owner `s/deploy-gate` and
a unique `agents-gate <sha> <token>` description. Finally releases with that
exact description, including failed runs and interrupts; release errors fail
loudly. There is no owner-only release or stale-claim stealing.

A builder receives a full HEAD bundle in a private temporary directory and
runs `nice -n 19 ionice -c3 tools/check.sh --tier gate --changed BASE` with a
65 s hard wall backstop, including lock waiting. Results return before cleanup.
On interruption cleanup cancels launch and kills this run's process group
before releasing. SSH errors fail closed. `--local` loudly announces its
unclaimed in-place fallback; selection, budgets and lock still apply.

After green, fetch again. A moved main is rebased; disjoint test selections
permit push, overlapping selections require one further check. A second
upstream race refuses and asks for a rerun. A plain `HEAD:main` push also
refuses a final race. `--dry-run` follows the real flow but stops before push.
Report the elapsed time from entry through push (or dry-run completion).

## 4. Lock and periodic checks

`~/.local/state/agents-gate.lock` (`AGENTS_GATE_LOCK` override) serializes
checks on each host. Local landing holds it through fetch/rebase/check/push.
`AGENTS_GATE_HELD` is a trusted nesting marker; fixture children strip it and
the lock override. This is cooperation, not verified exclusion.

Every two hours `agents-periodic.timer` runs `tools/periodic`: periodic first,
then the full gate without selection. Builder role units render only with
`machine_env.AGENTS_PERIODIC = 1`, currently hetzner3 alone. The service also
checks the runtime flag, uses nice 19 and idle IO. It mails each failed,
over-budget or starved file's owner using `post send --as agents-periodic
OWNER@hel8`; missing owners and runner failures go to ops. No periodic tests
have been invented or moved merely to escape a gate budget.

## 5. Later

- Enforce the landing entrypoint with remote main protection.
- Retain timing history with landing records; current tables are printed and
  optionally saved through `--json`.
