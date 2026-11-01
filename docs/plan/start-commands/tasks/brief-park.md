+++
id = "brief-park"
part = "brief-park"
kind = "feature"
needs = []
files = ["fab/calls.py", "fab/designer.py", "fab/triage.py", "fab/dispatch.py", "fab/channel.py", "fab/forge.py", "fab/tests/test_calls.py", "fab/tests/test_designer.py", "fab/tests/test_triage.py", "fab/tests/test_dispatch.py", "fab/tests/test_channel.py", "fab/tests/test_forge.py"]
effort = "high"
minutes = 75
+++
# A call whose brief cannot be compiled parks its subject

Read first: `docs/plan/start-commands/notes/common.md`,
`docs/plan/start-commands/notes/decisions.md` (4, 5), then
`docs/design/calls.md` 2, "A call whose brief cannot be compiled parks its
subject", whole, and `docs/design/channel.md` 2 on parked asks.

The request's item 3: today `fab call` exits 1 before `call.started` and
the tick starts it again every tick.

## What to build

- **`fab/calls.py`:** `BriefError` and `park` (decision 4). `_parse_args`
  (~640) adds `--tick` (store_true) to every role it parses. `main`
  (~727): the brief text's builders (`skeleton_brief`, `review_brief`,
  `answer_brief`, and in `_chain_call` ~667 `amend_brief` and
  `settle_brief`, after the chain-state checks) raise BriefError from
  their ValueError or OSError; `main` catches it before the generic
  handler: with `--tick` (and not `--brief-only`) it parks, then prints
  `fab call: <error>` and exits 1 as today. Amend and settle park with
  `call` the chain's root and `subject` the chain's subject (decision 5);
  the others with `call` "". The git fetch of `_retire_designs` is a
  `Failed`, never a park.
- **`fab/designer.py`:** `_arguments` (~516) adds `--tick`; `main` (~466)
  parks alike: in `_compile` (~564) the preconditions (unknown part, not
  a contract, already retired) stay plain ValueErrors and only the
  builders (`cut_brief`, `skeleton_brief`, `decision_brief`,
  `changed_designs` and `retire_brief`) raise BriefError. `_prepare`'s
  refusals never park. The subject is `subject(plan.draft, role, part)`.
- **`fab/triage.py` `main`** (~306): `--tick`; `brief(...)` raises
  BriefError; the rungs/ladder refusal does not park; the subject is
  `subject(plan.draft)`, the role `ROLE`.
- **`fab/dispatch.py`:** `_call` (~896) appends `--tick` to every role's
  argv; `_parked_subjects` (~177) adds the subjects of open `parked` asks
  whose `call` is ""; `call_actions` (~109) starts triage only when
  `triage.subject(plan.draft)` is outside the parked set.
- **`fab/channel.py` `_log_asks`** (~660): a `call.started` closes the open
  parked ask of its subject when that ask's `call` is "" (before its
  `continue`); a chain's park (call set) is untouched.
- **`fab/forge.py`:** a parked ask with report "" shows its reason alone:
  `question` (~62) gives no "(report missing)" excerpt for it, and the
  issue body (~215) and `reply_brief` (~70) leave out the `Read:` line.

## Acceptance

- `fab/tests/test_calls.py`: with `--tick`, a brief past `BRIEF_LIMIT` (and
  an unreadable source or design) logs one `call.parked` (subject, role,
  `brief failed: <first line>`, report "", call "") and a want line
  `park <subject>` (`fab.wake.want_path()`), exit 1, no `call.started`;
  without `--tick`, and with `--brief-only --tick`, nothing logged; an
  unknown part, an amend whose chain is not in amend, and a `Failed` with
  `--tick` log nothing; an amend's and a settle's park name the root and
  the chain's subject, and `call_review.chains` folds the chain `parked`.
- `fab/tests/test_designer.py`: a retire brief that cannot compile parks
  with `--tick`; `fab call retire` on a retired plan with `--tick` does not.
- `fab/tests/test_triage.py`: triage parks alike; a plan without rungs
  does not.
- `fab/tests/test_dispatch.py`: `_call`'s argv ends with `--tick` for
  each role (skeleton, settle, triage at least); a call-less park blocks
  its subject's call, the triage start included; an answer or a later
  `call.started` lifts it.
- `fab/tests/test_channel.py`: `asks` shows a call-less `call.parked` as a
  parked ask (testing what exists); a later `call.started` of its subject
  closes it; a chain's park stays open across a `call.started`.
- `fab/tests/test_forge.py`: such an ask's issue body and reply brief have
  the reason and no excerpt and no `Read:`.
- `bin/fab test` green.

## Pre-approved defaults

- Existing tests that pin `_call`'s argv gain `--tick` at its end.
- `mechanisms-out` may land first and change `_chain_call`'s amend path:
  rebase over it, keeping its rebase step before the brief.
- The want path in tests is the one `fab.wake.want` uses under
  `tmp_home()`'s FAB_HOME.

## Report

Which builders raise BriefError in each main, the park's fields as
logged, and the tests added.
