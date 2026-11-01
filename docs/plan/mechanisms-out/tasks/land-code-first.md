+++
id = "land-code-first"
part = "land-code-first"
kind = "interface"
needs = ["plan-options"]
files = ["fab/call_review.py", "fab/tests/test_call_review.py", "fab/calls.py", "fab/tests/test_calls.py", "fab/dispatch.py", "fab/tests/test_dispatch.py", "fab/roles/amender.md"]
effort = "high"
minutes = 60
+++
# `fab land` refusals: code first

Read first: `docs/plan/mechanisms-out/notes/common.md`,
`docs/plan/mechanisms-out/notes/decisions.md` (7, 8, 9).

The request, item 3. Design: `docs/design/calls.md`, 2, "A `fab land`
refusal counts as a refusal of the chain" ("Code takes the mechanical
cases first ... (the user, 11-01)").

## What to build

- `fab/call_review.py`:
  - `_fold_review` (~478): a `fab land` refusal (no `queue_ts`) at `fetch`
    or `push` no longer joins the chain's refusals or reviews, so it never
    counts toward the amend; `rebase`, `paths`, `test` and queue
    rejections fold as today.
  - `land_tries(chain, events, step) -> list[dict]` (decision 7), pure:
    counted per chain since the later of its latest call's `call.ended`
    and its last reset (a `call.answered` for its subject or a
    `chain.settled` amend), never by `tip`.
- `fab/dispatch.py`:
  - `call_actions` (~59, has `now`) and `_chain_actions` (~133): an
    approved chain whose `land_tries` at `fetch` or `push` number
    `LAND_TRIES` gets a `land-park` action instead of a finish; with fewer,
    its finish waits until `LAND_AFTER` minutes after the last of them.
  - `_take`: the `land-park` kind -> `_land_park` (decision 8).
  - `_finish_outcome` (~930): a `fetch`/`push` refusal leaves the finish
    open (None); its exceptions stay (landed by hand -> done; `fetch` with
    the branch gone -> failed).
- `fab/calls.py` `_chain_call` (~670), for an amend whose chain's last
  refusal is a `fab land` `test` refusal, before compiling the brief:
  fetch, rebase `origin/calls/<root>` onto `origin/main` in a detached
  worktree of its own (`FAB_HOME/amend/<root>`, removed after) as fab
  (`-c user.name=fab -c user.email=fab@localhost`), push with
  `--force-with-lease=refs/heads/calls/<root>:<fetched tip>`; a conflict
  is aborted and pushes nothing. Once per amend start, never with
  `--brief-only`. Pass the outcome to `amend_brief` (decision 9), whose
  refusal section says it.
- `fab/roles/amender.md` (~15-25): `fetch` and `push` no longer reach it;
  at `test` the branch comes rebased, and it rebases first only when the
  brief says that rebase conflicted; `rebase` and `paths` stay as they are.

## Acceptance

- call_review: `fetch`/`push` refusals leave an approved chain approved;
  `test` still makes it amend; `land_tries` counts from the later of the
  latest `call.ended` and the reset, and ignores `tip`.
- dispatch: the request's pin
  `test_finish_land_refusal_steps_and_terminal_exceptions` (~2618) changes:
  fetch/push no longer amend. A second finish waits `LAND_AFTER` minutes
  after the last refusal at that step; an answer retries at once; the
  third parks with `call.parked` (subject, root, reason, the log as
  report) and no amend call.
- calls: an amend after a `test` refusal runs fetch, the detached
  worktree, the fab rebase and the leased push in order, and its brief
  says rebased; a conflict aborts, pushes nothing and says so;
  `--brief-only` runs none of it and says the branch would be rebased.
- `bin/fab test` green.

## Pre-approved defaults

- A `fetch` or `push` refusal that already exists before this lands simply
  stops counting toward the amend; no log migration.
- `amend_brief`'s default (`rebase=""`) keeps every other brief as today.

## Report

How `_fold_review` and `land_tries` count, where the finish waits and
parks, the amend's rebase as built, the role text, and the pins changed.
