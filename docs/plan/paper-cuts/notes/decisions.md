# The cut's decisions

What the request and its designs left to the cut, each settled with its
reason. The specs bind them.

1. **Three direct parts, four tasks.** The request asks for a small plan.
   Retire's brief is one task. The probe's paper cuts are two tasks
   (the cache, then the records), since both change `fab/overlaps.py` and
   are ordered; the real-git test is a task of its own in a new test
   module, so it shares no file and starts at once.
2. **Retire gathers its own quotes.** `retire_brief` gains `rev` and `sh`
   keywords and runs the git commands itself through a new public helper
   beside `changed_designs` (calls.md 3: "A helper gives the plan's
   start and the diffs"), so `_compile` passes the runner it already uses.
   `changed_designs`' signature and return are unchanged, and so is
   `fab/call_review.py`. The task is kind `interface`: it adds parameters
   to a public function (`docs/design/gates.md`, 2).
3. **The list lines are reserved up front.** The budget is `BRIEF_LIMIT`
   less every other section's compiled text less a list line for every
   changed design, as if all were listed. That keeps calls.md 3's
   promise ("the brief passes the limit only if its other sections alone
   do") without a second pass, at the cost of at most a few hundred
   characters of budget.
4. **A bad tree on real git is a planted cache entry**: a tree id of full
   hex length that is not in the object store, under the key the probe
   looks up, in the cache's first format. The pair's merge-tree then fails;
   that is the failure integration.md 4 means, as no real catch-up
   yields a bad tree.
5. **The real-git test sits in `fab/tests/test_overlaps_git.py`**, not
   `fab/tests/test_overlaps.py`, so it shares no file with the two probe
   tasks. If real git shows the probe wrong, its report is a `Question:`
   with the failing case and the fix; it does not change `fab/overlaps.py`.
6. **The malformed-record rule is one public predicate in `fab.overlaps`**
   read by every fold (`is_news`, `open_pairs`, and through it
   `gone_pairs` and `fab/serve.py`'s `_public_overlaps`), so the probe and
   the page cannot disagree on what a record is.
7. **No walk.** No slice completes a story a user sees anew: the page shows
   what it showed, and only stops breaking on a bad line.
8. **No user questions.** The request settles what is built and where;
   nothing in it is a budget, a machine or hard to reverse.
9. **No counted forms:** the request sets no counts.
10. **No overlap with the drafts beside this one:** findings-repair's tasks
    change `fab/fixes.py`, `fab/channel.py`, `fab/buffer.py`,
    `fab/integration.py`, `fab/fix.py`, `fab/tier_reds.py`,
    `fab/dispatch.py`, `fab/wake.py` and their tests; this plan changes
    none of them.

## The critical path

`overlaps-cache` (50) -> `overlaps-records` (35): 85 implementer-minutes.
`retire-diffs` (55) and `overlaps-git` (40) need nothing and end within it.
