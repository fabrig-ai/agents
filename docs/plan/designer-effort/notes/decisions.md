# designer-effort: the cut's decisions

What the request left to the cut, each settled with its reason. The spec binds
them.

1. **One task,** as the request says: one direct part, four files.
2. **`fab/calls.py` lists the four roles by name.** `fab/designer.py` imports
   `fab.calls`, so `EFFORTS` cannot read `fab.designer.ROLES`; the test loops
   over `designer.ROLES`, so a fifth designer role with no entry fails it.
3. **The wiring needs no change.** Every call takes its effort at
   `fab/calls.py` ~575, `claude_argv(..., effort=role_effort(role))`, and
   `fab/designer.py` ~581 starts all four roles through `calls.start`.
4. **`claude_argv`'s default stays `EFFORT`, `high`.** Its tests call it
   without a role. `fab/tests/test_calls.py`'s `claude_argv` expectations
   (~835, ~903, ~962) start `skeleton` and `amend`, which stay high, so they
   hold; `test_claude_argv` ~578 pins the default.
5. **No test pins the old role text.** The request asks to check:
   `grep -rn "codex exec" fab/tests` and `fab/roles/` beside `cut-run.md` give
   nothing, and `fab/tests/test_designer.py` compares the role files with
   themselves, not with their words. So no test moves; the new test's
   fragments pin the new text instead.
6. **`amend` of a designer's chain stays high:** the request keeps amend's
   effort, and the role is `amend`, not the role it amends.
7. **Wording bound in the spec.** The two role texts are the deliverable, and
   the implementer is left no prose to choose.
8. **`docs/design/` and status files stay.** Commit `3e9e59f` changed the
   designs with the request; `docs/design/tick.md` 7 already notes today's
   surveys. The retire brings the status files current.
9. **`kind = "feature"`, `effort = "medium"`:** no signature changes, and the
   edits are mechanical.
10. **No counted forms and no user's questions:** the request sets no counts
    and leaves nothing to the user.
11. **Critical path:** `effort`, 20 implementer-minutes.
