# Gate

2026-10-30. Owner: s/deploy. Code: `tools/check.sh`, `tools/land`.
Code departures: `docs/design/gate.status.md`.

## 1. In one page

- **Agents has no merge queue.** A branch lands by `tools/land`; that is the
  required workflow, not an enforced one. It checks,
  rebases onto origin/main, checks again if anything moved, and fast-forwards
  main. It never force-pushes.
- **Main deploys itself.** Every landing reaches all hosts within a minute
  (`docs/design/fleet.md`), so the gate is the only review the fleet gets
  before running new code.
- **One gate per host at a time.** Concurrent full gates starve each other and
  the sessions on the host, so both commands serialize on one host lock
  (by convention: see section 4).
- **Tests keep off the real host's state.** Each test file runs with its own
  HOME and temporary directory, with fixtures that fake services and remotes.
  Local git and processes are real; there is no sandbox.

## 2. Check

**`tools/check.sh [FILES]`** runs every `tools/**/test_*.py`, or only the
named files, in parallel worker processes. Each file gets a fresh interpreter
with an isolated HOME and TMPDIR and no stdin. The output is in discovery
order, followed by a one-line summary. The exit code is 1 if any file failed.

**Use focused files while developing.** Run the full gate once before landing.
`tools/land` runs it anyway.

## 3. Land

**`tools/land`** takes no arguments. It refuses a dirty tree, `main` and a
detached HEAD. The sequence:

1. Run the full check.
2. Fetch, then rebase onto origin/main.
3. Run the full check again if the rebase moved HEAD.
4. Push `HEAD:main`.

If someone else pushed in between, the push fails, and the lander rebases and
lands again.

**Rebase first.** Rebase onto origin/main before `tools/land`, so the first
check already covers current main and the second rarely runs.

## 4. Host lock

**`~/.local/state/agents-gate.lock`** (override: `AGENTS_GATE_LOCK`):
- `check.sh` re-executes itself under `flock` on it;
- `tools/land` holds it across both checks, the rebase and the push;
- a waiting gate prints one line saying so.

**`AGENTS_GATE_HELD`** marks the nested run inside an outer holder. Any
nonempty value skips the lock, because the callers are trusted rather than
verified. Sessions never set it themselves and never wrap the gate in their
own `flock`. Test fixtures strip both variables, so the gate's own tests never
take the real lock.

## 5. Later

- An enforced landing entrypoint, so main moves only through `tools/land`
  (ops request).
- Keep the per-file timings that the gate already prints with the landing
  record, to spot slow or flaky tests.
