# The cut's decisions

What the request and fab.md 13.15 left to the cut, each settled with its
reason. The specs bind them.

1. **`rung.passed` is in this plan.** The request's tick bullet names the
   triage steps only, but it builds "the first cut of items 2-4", and item
   4 is "the pass ... is recorded"; 13.15's "Now" list has `rung.passed` in
   the tick's steps. `fab.findings.passes` (rungs-fold) and its logging
   (tick-triage).
2. **`finding-<n>` is left out, `backlog:<draft>` is in.** The request puts
   the `finding-<n>` signal with the repair path, a later plan. The backlog
   signal is part of readying the backlog (13.15: "the tick readies no more
   until the render changes or the signal is cleared") and the design's
   tests pin it; its rule is one copy, `fab.triage.backlog_held`, read by
   the tick and the page.
3. **The fold holds the repair states now.** `fab.findings.findings` folds
   foreman, deciding, decided, repairing, landed, fixed, unfixed and left
   from records only the second plan writes, tested with synthetic records:
   the fold is this plan's (the request), and the second plan then adds
   writers, not states.
4. **The backend check moves to rungs-fold.** 13.15 lists it among
   `fab.plan.problems`' additions, against `fab.findings.BACKENDS`. So that
   `ladder-plan` and `findings-fold` start at once, `findings-fold` creates
   `fab/findings.py` with `BACKENDS`, and `rungs-fold` (which needs both)
   adds the check to `fab.plan.problems`.
5. **A brief file missing is checked with the plan directory:**
   `fab.plan.problems(plan, tasks, plan_dir=None)`, `load` passing it; with
   no directory the check is skipped (the plan alone does not know where it
   is).
6. **An edition hashes each brief's path as plan.toml writes it** (relative
   to the plan directory) and its text at `origin/main`: moving the
   checkout never changes an edition; renaming a brief does, as any edit.
7. **Triage's thresholds are constants of `fab.triage`** equal to the
   answerer's (`AT`, `AFTER`), a test pinning the equality: fab.dispatch
   imports fab.triage, so fab.triage cannot import fab.dispatch.
8. **A `brief` decision's rung is its `owner` field** (`finding.triaged`
   has no rung field): owner names what is at fault, a tree for `path`, a
   rung's brief for `brief`.
9. **`fab qa rungs` is qa-intake's,** printing `fab.findings.line` for each
   rung, so the page and the command share one line.
10. **No user questions.** The request settles what is built and where it
    runs (hel8, the existing calls); nothing in it is a budget, a machine or
    hard to reverse.
11. **Test vocabulary in two new modules** (`fab/tests/qa_records.py` from
    findings-fold, `fab/tests/ladder_plans.py` from ladder-plan) rather
    than `fab/tests/support.py`, so the two first tasks own disjoint files.
12. **Status and design:** `docs/design/fab.status.md` is the designer's
    (the retire call brings 13.15's line current); a task edits fab.md
    13.15 and the status line only for a departure it must make.

## The critical path

`findings-fold` (55) -> `triage-decisions` (55) -> `tick-triage` (45) ->
`backlog-branch` (50): 205 implementer-minutes, about 3.4 hours. It is
longer than the longest task plus its contract (about 115) because the loop
reads in three layers (the fold, triage's rules, the tick), and the two tick
tasks share `fab/dispatch.py`, so they are ordered. Merging them into one
80-minute task would save 20 minutes at the cost of a task past the size
band; splitting `fab/triage.py` further would add tasks on the same file,
ordered again. Every other chain is shorter: `ladder-page` and `qa-intake`
end near 160, `triage-brief` near 155, `qa-figures` and `triage-shell`
start at once.

| Task | Needs | Minutes | Ends near |
|---|---|---|---|
| findings-fold | | 55 | 55 |
| ladder-plan | | 40 | 40 |
| triage-shell | | 40 | 40 |
| qa-figures | | 35 | 35 |
| rungs-fold | findings-fold, ladder-plan | 45 | 100 |
| triage-decisions | findings-fold, ladder-plan | 55 | 110 |
| qa-intake | rungs-fold | 60 | 160 |
| triage-brief | triage-decisions, triage-shell, rungs-fold | 45 | 155 |
| tick-triage | triage-decisions, rungs-fold | 45 | 155 |
| ladder-page | triage-decisions, rungs-fold | 50 | 160 |
| backlog-branch | tick-triage | 50 | 205 |
