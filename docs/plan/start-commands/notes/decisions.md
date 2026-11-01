# start-commands: the cut's decisions

What the request and its designs left to the cut, each settled with its
reason. The specs bind them.

1. **Four direct parts, one task each, one per request item.** The request
   names three tasks; its item 4 (F12) was added after and is a fourth.
   Each is one concept with no contract another part reads.
2. **trunk-make and plan-inputs run beside each other** although both add
   a `COMMANDS` entry to `fab/cli.py`: the request makes them independent
   and puts the entries at different places so the rebase is clean.
   `"trunk": ("fab.trunk", ...)` goes right after `"check"`;
   `"plan": ("fab.inputs", ...)` right after `"status"`.
3. **Modules:** `fab/trunk.py` (`fab trunk make`) and `fab/inputs.py`
   (`fab plan inputs`; the name `fab/plan.py` is the loader's, which the
   request keeps apart). Each has `main(argv)` and one public function
   doing the work with an injected runner: `trunk.make(plan_path, *,
   base="origin/main", sh=run, log_path=None) -> Path` (the plan directory
   in the new worktree) and `inputs.add(plan_dir, files, *, replace=False,
   sh=run, log_path=None) -> list[str]` (the repository paths for `fab
   call cut --source`). A refusal is a ValueError, printed `fab trunk:
   <error>` / `fab plan: <error>`, exit 1; usage errors exit 2.
4. **brief-park separates the brief from its preconditions** with one new
   public exception in `fab/calls.py`, `class BriefError(ValueError)`: the
   brief builders' ValueError or OSError is re-raised as BriefError at the
   three mains' compile step, never inside the builders (their callers and
   tests stay as they are). Preconditions (unknown part, chain state,
   retired plan, no rungs) raise as today before the compile step, and a
   `fab.sh.Failed` (a RuntimeError) never becomes one. One shared helper,
   `calls.park(role, subject, error, *, call="", log_path=None) -> None`,
   logs `call.parked` (subject, role, `reason="brief failed: <first line
   of str(error)>"`, `report=""`, call) and then `wake.want(f"park
   {subject}")`; the three mains call it only with `--tick`.
5. **Settle's park** names `call` the chain's root and `subject` the
   chain's subject (not `<subject>/settle`), as the design says, so
   `call_review.chains` folds the chain as parked.
6. **retired-import keeps `_load_plans`' return shape**, since
   `fab.designer._compile` unpacks it: retired plans come back through a
   new keyword, `retired: list[Plan] | None = None`, to which `_load_plans`
   appends each retired plan it skips (still printing `retired <draft>`).
   `_round` passes their drafts on to `_reconcile_reds` and `_import_queue`
   (`plan_drafts`) and then records the finish (decision 7). A retired plan
   is never in `loaded`: no decisions, no overlap probe, no strays.
7. **The retired finish** is one new private function in `fab/dispatch.py`:
   for each retired plan, each retire chain of its draft
   (`call_review.chains`, role `retire`, subject under the draft) with no
   `call.finished` for its calls and a `branch.landed` with `queue_ts` for
   its branch logs `call.finished` (call the chain's latest, role
   `retire`, outcome `done`, `tip` from its latest `call.checked` when
   there is one), once: the record a loaded plan's finish writes after
   `_queue_branch` sees the landing.
8. **No user questions.** The request settles what is built and how it
   lands; the commands are the operator's to use on hel8 afterwards.

## Critical path

`brief-park` (75) -> `retired-import` (45): 120 implementer-minutes, about
2 hours. Both own `fab/dispatch.py` and `fab/tests/test_dispatch.py`, so
they are ordered, in the request's order; `trunk-make` (45) and
`plan-inputs` (60) run beside them.

| Task | Needs | Minutes | Ends near |
|---|---|---|---|
| trunk-make | | 45 | 45 |
| plan-inputs | | 60 | 60 |
| brief-park | | 75 | 75 |
| retired-import | brief-park | 45 | 120 |
