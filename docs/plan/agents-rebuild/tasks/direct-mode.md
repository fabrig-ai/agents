+++
id = "direct-mode"
part = "wide-start"
kind = "feature"
needs = ["designer"]
files = ["fab/plan.py", "fab/tests/test_plan.py", "fab/roles/cut.md", "fab/roles/call-reviewer.md"]
effort = "high"
minutes = 30
+++
# Direct mode: small parts skip the skeleton, the cut writes their spec

docs/design/fab.md 13.11 ("Direct mode").

## What to change

- `fab/plan.py`: `MODES` gains `direct`; loading a plan refuses (PlanError)
  a direct part marked `contract`. A direct part with task specs counts as
  designed like any part with specs, so the dispatcher needs no change;
  check that, and say so in the report.
- `fab/roles/cut.md`: when to mark a part direct (about 1-2 tasks, one
  concept, no shared contract, nothing another part reads from it). The cut
  then writes the part's task spec itself in the plan's `tasks/`, in the
  format of the specs in its brief, thin: what to build, the files, the
  acceptance. Other parts keep "no task specs".
- `fab/roles/call-reviewer.md`: a cut's review also checks each direct
  part's spec against the part and the drafts.

## Acceptance

- Tests in `fab/tests/test_plan.py`: a direct part loads; a direct contract
  part is refused with a message naming the part.
- `bin/fab test` passes within the 30 s budget.
