# The cut's decisions

What the request and `docs/design/qa.md` 2 left to the cut, each settled
with its reason. `tasks/guard.md` binds them.

1. **One direct part, one task** (the request). Its three items are one
   concept in one branch, so there is no `notes/common.md`: the spec carries
   the standing rules.
2. **The check runs after `rust_gates.screen` finds nothing.** The request
   says only "before `_ready`". After the screen the repo is cloned and
   fetched and the digest exists, so the check adds no second clone, fetch or
   lock, and shares `_screen_ready`'s `rejected gate:` line.
3. **Every rung's briefs, not only the finding's rung's.** The request says
   "the plan's rung brief files", and the kit that caused this is shared by
   all of them: an edit to any brief changes that rung's edition.
4. **Paths are compared repository-relative:** the plan directory under the
   checkout, as `fab/walks.py` `_briefs` does; `_take` has both. The plan's
   own paths are plan-relative, and the fabrig ladder's plan sits at
   `temper/docs/plan/v0.1.0-ladder`.
5. **`rust_digest.changes` reads the diff,** so no second numstat parser, and
   its `--no-renames` lists a renamed or deleted brief under its old path.
6. **`_screen_ready` takes `plan`, `plan_dir` and `checkout`,** not computed
   paths: the request allows either, and only a finding task then computes
   the relative path, so no other task's readying can fail on it.
7. **`findings` goes through `gates.findings_text`,** `[gate:briefs]` then a
   line per path, since `fab.run.brief` looks for `[<step>]`; `refusal_text`
   quotes it, and the refusal foreman reads "drop the edit". `log` names the
   screen's digest, for the shape.
8. **`briefs` stays out of `gates.GATES`:** no digest decides it. Only the
   comment on `Finding.gate` changes, so `fab/gates.py` is in `files`.
9. **Kind `feature`:** `_screen_ready` is private, and no public signature
   changes (`docs/design/gates.md`, 2).
10. **`walk = false`:** nothing user-visible completes, and a walk could not
    show it short of a repair editing a brief. The tests are the check.
11. **No user questions.** The request settles what is built and where.
12. **Status and design:** `docs/design/qa.md` 2 already says this (landed with
    the request). `docs/design/qa.status.md` is the designer's; the retire call
    brings it current.

## The critical path

`guard` (45): 45 implementer-minutes, the one task. No counted forms: the
draft sets none.

## Overlaps with designer-effort

None. That draft changes `fab/calls.py`, its tests and the cut's role files;
this one changes none of them.
