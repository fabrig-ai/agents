# mechanisms-out: the cut's decisions

What the request left to the cut, each settled with its reason. The specs
bind them.

1. **Three direct parts, one task each, ordered by needs (1, 2, 3).** The
   request names three tasks in that order. All three change the tick's
   finish in `fab/dispatch.py`, 1 and 2 share its pre-delivery helper, and
   2 and 3 share `fab/calls.py`, so the order is also the files' order.
2. **One pre-delivery helper, `_pre_deliver`, in `fab/dispatch.py`.**
   `retired-code` adds it with retire's commit; `plan-options` adds the
   queue plan's options restore to it. It runs in `_take`'s `finish` case
   before `_deliver`, with the guards both share: no `branch.landed` names
   the branch, and `origin/<branch>` exists after a fetch (otherwise it
   commits nothing and the delivery takes its path as today: done if landed
   by hand, failed at fetch if gone). A failure in it logs a note
   (`finish <root> failed: <error>`) and leaves the finish open:
   `_take`'s `finally` skips `_record_finish` when the delivery never ran,
   so no `call.finished` is logged and the next tick tries again.
3. **The plan.toml path** is the plan directory relative to the checkout,
   as `_check_call` finds it (`plan_dir.resolve().relative_to(
   checkout.resolve())`), joined with `plan.toml`.
4. **`_queue_branch` re-readies a moved tip:** it reads origin's tip first
   and readies again when it differs from the last `branch.ready`'s `tip`,
   in addition to today's `call.ended` rule (calls.md 3).
5. **The seed's commit message** is `<draft>: plan options`, the draft being
   the subject's first segment; `fab.calls.start` takes no other new
   parameter (`seed: Mapping[str, str] = {}`, as the request gives it).
   `plan-options` is kind `interface` (a parameter added to a public
   function).
6. **One writer of the option lines:** a public helper in
   `fab/designer.py` renders the seed (`draft`, `repo`, `sources`, then the
   comment `# Plan options, written by fab call cut --set; keep them` and
   `<key> = <json.dumps(value)>` per option) and another restores options
   in a plan.toml text; the cut seeds with the first, the tick's two
   restores (integration trunk, queue branch) use the second. Both are
   `plan-options`'.
7. **fetch/push land tries live in `fab.call_review`:** a pure public
   helper `land_tries(chain, events, step) -> list[dict]` (the `fab land`
   refusals at that step for the chain's branch since the later of its
   latest call's `call.ended` and its last reset), not a new `Chain` field,
   so no test comparing a `Chain` changes. `_fold_review` no longer folds
   `fab land` refusals at `fetch` or `push` into the chain's refusals.
8. **The third fetch/push refusal parks through a new action kind,**
   `land-park`, taken by a `_land_park` in `fab/dispatch.py` that logs
   `call.parked` (subject, the root as call, reason `fab land refused at
   <step> 3 times`, report the refusal's `log`). Not `hold`: `_settle_actions`
   turns holds into settle calls, and this park is the user's (machines).
   `LAND_AFTER = 10` and `LAND_TRIES = 3` are `fab/dispatch.py` constants.
9. **`amend_brief` takes the rebase's outcome** as `rebase: str = ""`:
   `"rebased"`, `"conflicted"` (aborted; main moved), `"pending"` (a
   `--brief-only` brief: the branch would be rebased first) or `""` (no
   `test` refusal). `land-code-first` is kind `interface`.
10. **No counted forms:** the draft sets no counts, so no task touches
    `scripts/old_forms.py`.
11. **No user questions.** The request settles what is built, where, and
    how it lands; nothing in it is a budget, a machine or hard to reverse.

## Critical path

`retired-code` (50) -> `plan-options` (60) -> `land-code-first` (60): 170
implementer-minutes, about 2.8 hours. It is longer than the longest task
plus a contract because the request orders all three on the tick's finish
(1).

| Task | Needs | Minutes | Ends near |
|---|---|---|---|
| retired-code | | 50 | 50 |
| plan-options | retired-code | 60 | 110 |
| land-code-first | plan-options | 60 | 170 |
