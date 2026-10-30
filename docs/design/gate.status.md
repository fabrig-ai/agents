# Gate status

2026-10-30. Owner: s/deploy. Baseline: `deploy/design` `373b246`.
Contract: `docs/design/gate.md`, sections 1–4.

## Present

- Nested/focused test discovery, fresh interpreters, isolated HOME/TMPDIR,
  parallel execution, ordered results and per-file timing exist (`tools/check.sh:47`,
  `:59`, `:70`, `:78`; `tools/test_check.py:32`, `:40`, `:61`, `:88`).
- The lander refuses arguments, dirty trees, main and detached HEAD, then checks,
  fetches/rebases, checks again if HEAD moved, and pushes without force
  (`tools/land:14`; `tools/test_fleet_sync.py:1085`, `:1090`, `:1095`, `:1106`).
- Cooperating callers share a lock across checks, rebase and push; waiting and
  fixture lock isolation are tested (`tools/test_check.py:113`, `:135`).

## Gaps and departures

- **Land-only main updates remain unenforced by repository tooling.** The design
  now describes this as policy. `tools/land:37` is an ordinary push; neither it
  nor check.sh prevents another caller pushing main. Remote protection settings
  were not inspected; an enforced entrypoint remains deferred (gate.md, section 5).
- **AGENTS_GATE_HELD remains trusted.** Any nonempty value skips flock
  (`tools/check.sh:7`, `tools/land:17`); neither verifies lock ownership.
  AGENTS_GATE_LOCK may select another lock. Host exclusion relies on cooperation,
  as the corrected section 4 now states.
- **Timing is printed but not retained with a landing.** `tools/check.sh:80` prints
  elapsed time; `tools/land:31` does not persist it, matching the remaining Later item.

## Verification

Tools/fleet are unchanged since the previous full gate: 26 files, 0 failures.
This refresh changes documentation only; diff/line-count checks apply.
No machine action required; this branch is not landed.
