# Request: mechanisms out of the LLM calls

From the user via the director, 2026-11-01 (the lab page's proposal 3, approved): an LLM for
judgement, code for mechanisms. Three mechanisms that calls do today move to code. The designs
now say how, each marked "the user, 11-01". Build them as designed, with the role texts in step.

There are three tasks, ordered by needs (1, 2, 3). Tasks 1 and 2 share one pre-delivery helper in
`_take` "finish" (`fab/dispatch.py`). These test pins change: `fab/tests/test_dispatch.py` ~2575
(fetch/push → amend) and `fab/tests/test_designer.py` ~612 and ~965 (the `Plan options` text).

1. **`retired = true` is code's** (`docs/design/calls.md` 3, "retire").
   - Today the retire call writes it (`fab/roles/retire.md`, "What you write").
   - Build: at the finish of a retire call that ended done, before `_deliver`, commit it on the
     call's branch with `fab.spec_edit.commit_path(..., branch=<call branch>, trunk=<call branch>,
     worktree=FAB_HOME/retire/<root>)`. The guards, the edit and the retry are as the design says.
     A failure before the delivery logs a note and records no `call.finished` (`_take`'s
     `finally` → `_record_finish`).
   - Re-ready a queue plan's branch when origin's tip differs from its last `branch.ready`'s
     `tip` (`_queue_branch`).
   - Role texts:
     - remove the `retired = true` bullet from `fab/roles/retire.md` and say there that fab sets it;
     - remove "The plan not retired" and "and marked the plan retired" from
       `fab/roles/consistency.md`;
     - fix `fab/designer.py`'s module docstring ("marks the plan retired").
2. **Plan options written by code** (`docs/design/integration.md` 3, "The cut's inputs").
   - Today `fab.designer._cut_role_options` tells the cut to write the `--set` keys verbatim, and
     `fab/roles/cut-run.md`'s template has `# the plan options, verbatim`.
   - Build:
     - `fab.calls.start` gains `seed: Mapping[str, str] = {}` (repository path → text), written
       and committed after `worktree add` and before `call.started`.
     - `fab call cut` (`fab/designer.py` `main`) seeds plan.toml with `draft`, `repo`, `sources`
       and the options under the design's comment.
     - The `Plan options` brief text, `fab/roles/cut.md` and `fab/roles/cut-run.md`: "plan.toml
       already exists on your branch with fab's plan options at its top, under `# Plan options,
       written by fab call cut --set; keep them`. Write the tables below those lines, and never
       repeat or change them." Drop the template's `# the plan options, verbatim` line.
     - The restore:
       - for an integration plan, in the trunk after each clean merge of the cut's branch in
         `_merge_branch`, never on the cut's branch;
       - for a queue plan, on the cut's branch before `_deliver`, once the call has ended;
       - comparing by parsed value, against the root cut's `call.started` `options`.
3. **`fab land` refusals: code first** (`docs/design/calls.md` 2, "A `fab land` refusal counts as
   a refusal of the chain").
   - `fetch`/`push`:
     - no amend call; retried `LAND_AFTER` (10) minutes after the chain's last refusal at that
       step;
     - counted per chain since the later of the latest call's `call.ended` and the chain's last
       reset, never by `tip`;
     - the third parks the chain (`call.parked` with subject, the root as call, the reason and
       the refusal's log as report);
     - these refusals do not count toward the amend. Code: `fab/call_review.py` `_fold_review`
       and `land_refusal`, `fab/dispatch.py` `_finish_outcome` and the amend start.
   - `test`:
     - `fab call amend` (`fab/calls.py` `_chain_call`), before compiling the brief, rebases
       `origin/calls/<root>` onto `origin/main` in a detached worktree of its own, once per amend
       start;
     - it pushes with `--force-with-lease=refs/heads/calls/<root>:<fetched tip>`;
     - it passes the outcome to `amend_brief` (`fab/call_review.py`).
   - `fab/roles/amender.md`:
     - `fetch` and `push` no longer reach it;
     - at `test` the branch comes rebased (it rebases first only when the brief says that rebase
       conflicted);
     - `rebase` and `paths` stay as they are.

Other north-star breaches found on the way are not for this plan; agents/loop lists them in its
README.

The user's rule: dogfood. Built by fab's loop (landed through `bin/fab land`); the plan's landing
is `queue` (the cut is started with `--set 'landing="queue"'`). Each task brings its tests in
`fab/tests/` (fakes and fixture logs, as the touched modules' tests are). Run after
`docs/plan/dogfood-faults` has landed its tasks.
