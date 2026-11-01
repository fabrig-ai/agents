# Request: acceptance fixes for precheck-starved and df-followups

From agents/loop, 2026-11-01: the acceptance review on main 7e143f7 (df-followups ACCEPT,
precheck-starved REFUSE on item 1 below). Item 1 is live now and comes first.

1. **A starved receipt never stands in for the gate** (`docs/design/landing.md` 3, changed in
   this request's commit). Since `precheck-starved`, `fab.receipts.reusable` returns True for
   `outcome: green, starved: 7`. A batch of one on the same main then runs only fmt, so in the
   case that plan was for, 7 killed and 938 never-run tests land with no gate run. Build:
   - in `fab/precheck.py`, add `"unobserved": 0` to the receipt and count `case.result ==
     "skipped"` into it, beside `starved`;
   - in `fab/receipts.py` `reusable`, add `not receipt.get("starved") and not
     receipt.get("unobserved")`, and update the docstring (a missing key counts as 0: older
     receipts stay reusable);
   - `covers` stays as it is;
   - tests:
     - `fab/tests/test_precheck.py`'s `assert_receipt` key set;
     - a `fab/tests/test_receipts.py` case: False for `starved` 1 and for `unobserved` 1, True
       for 0 and for a missing key;
   - `docs/design/landing.status.md`: say so.
2. **Collector directories are removed from builders.** A full precheck leaves 127 MB and about
   24,500 files under `FAB_HOME/precheck/<tip>/` (hetzner6), and nothing reads them. At the end
   of `fab/precheck.py` `_checks`: `shutil.rmtree(directory / profile / "records",
   ignore_errors=True)` for each profile in `reports`, keeping what the receipt and the log need.
3. **A foreman or repair settled after a trunk landed** (`docs/design/integration.md` 3, "Retire
   waits for main"). `fab/dispatch.py` `_settle` (~1643) and `_remedy` (~1733) still pass
   `trunk=plan.trunk`, so their worktree fails each tick once `origin/<trunk>` is pruned. Build:
   `trunk=integration.call_base(plan, events)` at both sites. Add landed subtests to
   `test_answer_and_repair_specs_use_trunk_and_settle_only_after_merge`, and delete the gap
   bullet in `docs/design/integration.status.md`.
4. **A task started from main after landing can land.** `_landing_actions` (~2015) still emits
   `merge`, and `_merge_branch` resets to `origin/<trunk>`, which fails each tick.
   `task_rebase` (~2010) compares with `origin/<plan.trunk>`. Build: add `and not
   integration.trunk_landed(plan, events)` to the `merge` condition, and pass
   `trunk=integration.call_base(plan, events)` at ~2010. Name the case in the status file.
5. **A test for `_foreman`'s fix-kind base:** a fix-kind subtest beside
   `test_foremen_start_on_trunk_then_main_after_queue_landing`.

The user's rule: dogfood. Built by fab's loop (landed through `bin/fab land`); the plan's landing
is `queue` (the cut is started with `--set 'landing="queue"'`). Two tasks: items 1-2 together
(first), items 3-5 together.
