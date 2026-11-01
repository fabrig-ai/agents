# call-rebase-fixes: the cut's decisions

1. **One direct part, two tasks, no needs.** `fab-fetch` (fab/dispatch.py,
   its test, calls.status.md) and `role-texts` (fab/roles/settle.md,
   fab/roles/amender.md) share no file and neither reads the other's code,
   so both start at once. The request asks for one or two tasks; two keep
   the blocking fix's review apart from the prose.
2. **Exit 2 only.** `git ls-remote --exit-code` exits 2 when no ref
   matches; every other non-zero code (128: network, auth, a missing
   remote) is a passing failure and leaves the refusal open for its amend,
   as the design's "a passing `fetch` or `push` failure costs one amend"
   says. A runner that raises rather than returning a code is not a case
   today (the call is `check=False`); nothing new handles it.
3. **The status line, not the design.** calls.md 2 already says "gone from
   origin"; only `docs/design/calls.status.md` (~57) is reworded, in the
   request's words. The status file is the designer's; the request names
   the wording, so `fab-fetch` writes it.
4. **Role texts carry no tests.** No test pins `fab/roles/settle.md` or
   `fab/roles/amender.md` text; `role-texts` adds the request's sentences
   verbatim (settle) and in the file's voice (amender), and its check is
   `bin/fab test` green.

## Critical path

`fab-fetch` (30 min) alongside `role-texts` (20 min): 30
implementer-minutes, the longest single task.
