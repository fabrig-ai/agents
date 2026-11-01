+++
id = "land-chain"
part = "land-refusal"
kind = "interface"
needs = []
files = ["fab/call_review.py", "fab/calls.py", "fab/roles/amender.md", "fab/tests/test_call_review.py", "fab/tests/test_calls.py"]
effort = "high"
minutes = 50
+++
# A `fab land` refusal in the chain: its hold reason and its briefs

Read first: `docs/plan/call-rebase/notes/common.md`,
`docs/plan/call-rebase/notes/decisions.md` (2, 3, 4 and 6).

The request: "the amend brief's heading and the retire's extra designs
(`amend_brief` and `_findings` in `fab/call_review.py`, the design list
computed in `_chain_call`, `fab/calls.py`, and passed in), the hold reason,
its settle briefs [...] and the amender's role text (`fab/roles/amender.md`)
for a rebase. The chain fold already counts the refusal." Design:
`docs/design/calls.md`, 2, "A `fab land` refusal counts as a refusal of the
chain", its second and third sub-bullets (the amend brief, the hold).
`land-finish` builds the tick's side against what you bind here.

## What to build

- `fab/call_review.py`, constants near line 30: `LAND_HOLD = "refused by fab
  land after its amendment"` and the tuple of `fab land`'s steps
  (decisions 2, 3). A public `land_refusal(refusal: str) -> dict | None`
  (decision 2), near `_findings` (line 415).
- `_state` (line 383), its last line: the hold's reason is `LAND_HOLD` when
  the chain's last refusal (`chain["refusals"][-1]`) is a `fab land`
  refusal, else `refused after its amendment`. `chains`' docstring lists
  the new hold.
- `_findings` (line 415): a `fab land` refusal is headed `` ## `fab land`
  refused at <step> `` (not `Queue rejection`), its text `Step: <step>`,
  then `Log:` and the record's `log` (fab land's last 20 lines, whose
  `CONFLICT` lines name the paths). Queue rejections and review runs keep
  their form. `settle_brief` uses `_findings` too, so it gets the heading.
- `amend_brief` (line 236) gains the keyword `designs: Sequence[str] = ()`.
  Non-empty, a fifth section `Designs main changed since your branch`: one
  `` - `<design>` (status `<design>.status.md`) `` line each (the status
  path as `fab.designer.status_path` gives it), then the line `Main changed
  these designs after your branch's tip: check each one's status file
  against what your branch writes.` Empty, no section. Its docstring says
  so.
- `settle_brief` (line 199), its restriction line: on a `LAND_HOLD` hold,
  the first settle reads `A land verdict would land the tip fab land just
  refused (refused again at rebase, paths or test): choose amend or user.`;
  the second `Amend is no longer an option, and land would land the tip fab
  land refused: user only.` Other holds keep today's two lines.
- `fab/calls.py`, `_chain_call` (line 651): for an amend of a chain with
  role `retire` whose last refusal is a `fab land` refusal, compute the
  designs of decision 4 and pass them as `designs=`; every other amend
  passes none. `_chain_call` is private: give it the draft and plan path it
  needs as keywords (`main` has `plan.draft` and `plan_path`).
- `fab/roles/amender.md`: a bullet under "What you do" for a refusal headed
  `` `fab land` refused at ``: at `rebase`, `git fetch origin`, rebase the
  branch onto `origin/main`, resolve each conflict keeping both sides'
  intent (main's side is others' landed work), run the checks and push with
  `git push --force-with-lease origin HEAD` (the worktree tracks
  `origin/calls/<root>`); at `paths` or `test`, fix what the log names; at
  `fetch` or `push`, when the branch did not cause it, change nothing and
  end `Done:` saying so (decision 6). For a retire, check the status files
  of the designs the brief lists. "Ending" says the rebase case replaces
  "one commit" and `git push origin HEAD`.

## Acceptance

Tests in `fab/tests/test_call_review.py` (beside the queue-refusal tests
near lines 96 and 119, the brief tests near 430 and 468) and
`fab/tests/test_calls.py`:
- `land_refusal`: a `fab land` record (no `queue_ts`, step `rebase`) is
  returned; one with `queue_ts`, one with step `merge` or `catch-up`, and a
  review run id give None.
- A chain whose first `fab land` refusal comes before any amend is in state
  `amend`; refused again by `fab land` after an amend that ended done, it is
  `hold` with reason `LAND_HOLD`; refused second by a review run or a queue
  rejection, the reason stays `refused after its amendment`.
- The amend brief quotes the refusal under `` ## `fab land` refused at
  rebase `` with its `CONFLICT` line; a queue rejection keeps `## Queue
  rejection`; `designs=("docs/design/x.md",)` adds the section with
  `docs/design/x.status.md`, none leaves the brief as before.
- The settle brief of a `LAND_HOLD` hold says amend or user on the first
  attempt and user only on the second; other holds as before.
- `_chain_call` for a retire chain refused by `fab land` passes the designs
  at `origin/main` less those at the branch's tip; for a skeleton chain,
  or a retire refused by a review run, it computes none.

## Pre-approved defaults

- `_chain_call`'s tests may patch `fab.calls.run` with a `FakeRunner` and
  `fab.designer.changed_designs` with a function keyed on `rev`.
- `changed_designs` raising ValueError at either rev: pass no designs; the
  amend still runs.
- Existing tests that pin `_findings`' text for queue rejections or the
  settle restriction lines keep passing unchanged; if one pins a `fab land`
  record as `Queue rejection`, update it to the new heading.

## Report

`land_refusal`'s rule as built, the amend brief's new heading and section
as they print for a sample retire, and the amender text you added.
