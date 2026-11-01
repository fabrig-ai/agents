# gates status

2026-11-01. Contract: `docs/design/gates.md`. Split from `docs/design/fab.status.md`.

## Present

- **The digest** (`docs/design/gates.md`, 2; since 10-30):
  `fab.digest.build` compares the base and tip's public items, modules,
  changed paths and line counts, paths outside the task, long functions
  and repeated blocks. `changes` reads the git diff, `archive` extracts
  both trees, and `render` bounds deterministic Markdown to 8,000
  characters. `fab.gates.screen` writes it to `FAB_HOME/digests/<run>.md`.
- **Task branches are gated** (`docs/design/gates.md`, 2; since 10-30):
  `fab.dispatch._land` calls `fab.gates.screen` before landing this
  repository's tasks. `screen` fetches and archives under the landing
  lock, then `check` enforces shape, size, names, docs and clones with
  `banned_names` reading the taste file. `fab.digest.long_functions`
  makes size a ratchet: only new or grown functions over 60 lines fail.
  `screen` records findings as `branch.rejected` with `gate:<name>`
  (`gate:parse` for invalid Python); git failures raise and prevent landing.
- **Taste reaches implementers** (`docs/design/gates.md`, 2; since
  10-30): `fab.run.role_text` includes `fab/taste.md` in the brief, and
  `fab.gates.banned_names` reads its banned list for the names check.
- **The structure review runs** (`docs/design/gates.md`, 2; since
  10-30): `fab.dispatch.call_actions` starts review calls when `_review_due`
  finds ten landings or four hours with any landed, unless reviews are
  disabled. `fab.calls.last_review` counts failed reviews toward the next
  threshold; `landed_after` restricts the landings to the plan's tasks.
  `review_brief` supplies landed digests since the last done review, taste,
  inventory and cited designs to `fab/roles/reviewer.md`, which asks for
  consolidation specs and taste pairs. `fab.dispatch._parked_subjects`
  and `call_actions` hold a subject with an unanswered call question.
- **Skeleton and contract tips are gated** (`docs/design/gates.md`, 2;
  since 10-31): `fab.dispatch._tick_loaded` invokes `_check_calls`;
  `_check_call` screens each completed design output, including amends,
  as an `interface` task owning `**`, using Python gates for this
  repository and Rust gates for fabrig. `_call_tests` runs `bin/fab test`
  in a detached worktree or `fab precheck` in a claimed idle slot.
  `_check_call` pins tip, task ids, specs, paths and findings in
  `call.checked`; infra failures leave it unchecked for a later retry.
  `fab.dispatch.decide` uses `fab.plan.checked_tasks` so tasks can start
  from a green tip while its review is still running.

## Gaps and departures

- **Review-call branches are not gated** (`docs/design/gates.md`, 3):
  `fab.dispatch._check_calls` selects skeleton and contract chains only;
  cut, answer, review, decision and retire tips do not pass through it.
