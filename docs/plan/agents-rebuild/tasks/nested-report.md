+++
id = "nested-report"
part = "fabrig-calls"
kind = "feature"
needs = ["nested-plans", "report-measures"]
files = ["fab/code_report.py", "fab/tests/test_code_report.py"]
effort = "high"
minutes = 25
+++
# The code report finds the checkout of a nested plan

docs/design/fab.md 13.11 ("A fabrig plan", at any depth). `fab/code_report.py`
infers a task's checkout from a fixed number of parents above its spec; for
a spec at `skein/docs/plan/<draft>/tasks/<task>.md` it lands on `skein/`, not
the repository root, so the per-part line counts (`git diff --numstat` over
the part's `files`) read the wrong tree.

## What to change

- Find the checkout root with `git rev-parse --show-toplevel` from the
  plan directory through the runner seam (or by walking up to the
  directory holding `.git`), for root-level and nested plans alike; keep
  this repository's figures unchanged. Signatures and helpers inside
  `fab/code_report.py` are yours; do not ask.

## Acceptance

- A test with a nested plan in a fake checkout: the numstat runs at the
  checkout root with the part's repository-relative `files`; a root-level
  plan behaves as before.
- `bin/fab test` passes within the 30 s budget.
