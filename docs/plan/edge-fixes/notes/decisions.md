# edge-fixes: the cut's decisions

What the request and its designs left to the cut, each settled with its
reason. The specs bind them.

1. **One direct part, two tasks,** as the request says. Neither is a contract,
   and neither reads the other's code.
2. **No `needs` between the tasks.** The request numbers its items but does
   not order them, and they share no file or code, so neither waits.
3. **`--ignored` alone is enough.** Tried on real git: an ignored file or a
   wholly ignored directory gives one `!!` line, a tracked directory holding an
   ignored file gives that file, and an absent path gives nothing, even under
   an ignored directory. A destination absent locally is therefore still
   accepted. The default `traditional` mode stays.
4. **The refusal's text stays** `input is untracked or changed in checkout`.
   The request says "as already done", and an ignored file is untracked.
5. **A `--replace` over a tracked directory holding a local ignored file is
   refused too.** It is what the request's "nonempty result" says, and the
   design's "exists untracked".
6. **The third spelling.** The request lists `"retired"`, `'retired'` and
   `"retired"`, the first and last the same bytes. A unicode escape in the
   key is the one spelling left, and a tool layer decodes such an escape in
   text it carries (this cut's own first draft of this note lost one that
   way), so that is probably what the third was. The tests cover the bare key,
   both quotings and `"r\u0065tired"` (the `e` written as backslash, `u`,
   `0065`): the bare key is the old code's case. Neither needs code past the
   request's: `tomllib.loads(statement)` decodes the key.
7. **The whole statement is replaced, so a trailing comment goes.** The request
   says to replace the statement with `retired = true`, and nothing reads such
   a comment. Two tests pin `retired = true # pending` and are updated;
   `calls.md` 3's "replaces a `retired = false` line" still holds. This also
   drops an assignment's indentation.
8. **The final parse also requires `retired` to be True.** The request says
   parse; parsing alone misses `[retired]`. There the key is present, no header
   statement holds it, and `_retire_plan` would return its text unchanged, so
   `commit_path` would commit nothing and delivery would go on without the
   flag. Neither that nor split dotted keys (`retired.a`, `retired.b`) passes
   `load_plan`, but `_pre_deliver` does not load the plan. Both now raise
   `ValueError` inside the edit, before any commit, and `_take` notes
   `finish <root> failed`, leaving the finish open.
9. **`designer._plan_header` is called by its private name,** as the request
   writes it; `fab/dispatch.py` already imports `designer`. `fab/designer.py`
   is not renamed or changed, which keeps this task's files at three. `re`
   stays imported in `fab/dispatch.py`: ~1404 still uses it.
10. **No design changes:** the request says the designs stand. The status
    edits it asks for describe the code as built.
11. **`kind = "feature"` for both:** `_check_paths` and `_retire_plan` are
    private and keep their signatures.
12. **No machine action:** `fab/inputs.py` runs from `bin/fab` and
    `_retire_plan` in the tick, which follows main.
13. **No counted forms and no user's questions:** the request sets no counts,
    this repository has no `scripts/old_forms.py`, and the request settles
    everything that is the user's.
14. **No survey subagents:** the request names both sites, and they were read
    directly.
15. **Critical path:** the longer task alone, `retire-spelling`, 30 minutes.
