# Request: two edge cases from the acceptance of start-commands and mechanisms-out

From agents/loop, 2026-11-01: the Codex acceptance review on main 992fce7 refused each plan on one
edge case. The rest of both plans holds, with 27 regression tests checked against the old code.
The designs stand; the code falls short of them:

1. **`fab plan inputs` refuses an ignored destination** (`docs/design/integration.md` 3: refuses
   an `inputs/<name>` that "exists untracked or changed in the checkout"). `fab/inputs.py`
   `_check_paths` (~66) uses `git status --porcelain`, which hides ignored files, so a local input
   hidden by a `.gitignore` is overwritten by the fast-forward. Build: add `--ignored`, and reject
   a nonempty result as already done. Add real-git refusal tests for both `--replace` settings,
   asserting that the local bytes, remote refs, HEAD and worktrees are unchanged.
2. **Retiring a plan that spells the key another way** (`docs/design/calls.md` 3). `_retire_plan`
   (`fab/dispatch.py` ~869) recognises only the bare `retired = false`. Valid TOML such as
   `"retired" = false` passes `load_plan`, keeps its assignment and gains `retired = true`. The
   output no longer loads (`Cannot overwrite a value`), and `_pre_deliver` publishes it. Build:
   split the header into statements with `designer._plan_header`, find the retired assignment with
   `tomllib.loads(statement)` and replace that statement with `retired = true`; insert only when
   the parsed key is absent; parse the final text before committing. Add tests that load a
   complete plan before and after retirement for `"retired"`, `'retired'` and `"retired"`.

Remove any status claim these make too broad (`docs/design/integration.status.md` ~85,
`docs/design/calls.status.md` ~71).

The user's rule: dogfood. Built by fab's loop (landed through `bin/fab land`); the plan's landing
is `queue` (the cut is started with `--set 'landing="queue"'`). One direct part, two tasks.
