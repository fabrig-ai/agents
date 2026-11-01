# The cut's decisions

What the request and fab.md 13.17 left to the cut, each settled with its
reason. The specs bind them.

1. **Three direct parts, four tasks.** The request asks for a small plan.
   The probe is two tasks (the pure part, then its shell, cache and tick
   call, which share `fab/overlaps.py` and so are ordered); the page and
   the cut's section are one task each.
2. **`fab.integration.trunk_landed(plan, events) -> bool` is extracted from
   `queue_step`** (overlaps-pure): the probe and the cut's section both ask
   "has this trunk landed" (13.17 cites `queue_step`'s reading), so the rule
   has one copy. That is why `cut-beside` needs `overlaps-pure`.
3. **`fab.overlaps.open_pairs` is the one rule for an open pair,** read by
   the probe's pairs gone and by the page (`notes/overlaps.md`).
4. **The probe runs once per `_round`, after every plan's `_tick_loaded`,
   and not with `only`.** `only` is a replay's own tick over its given plans
   (no page, no strays): there the listed plans are not loaded, so the
   "every listed plan loaded" rule for closing pairs could not hold, and a
   replay is never probed anyway (`ready` false). "Every listed plan
   loaded" is: `_load_plans` returned no `load` action.
5. **Failure notes carry a fixed prefix per pair or trunk**
   (`trunks.overlap <a> <b>: `), so "differs from that pair's last failure
   note" is read from the log alone, as section 3's `note` has `text` only.
6. **The cut's section is built in `fab.designer`, the plans loaded through
   `fab.dispatch._load_plans(..., fetch=False)` by a deferred import**
   (the dry-run's path, as 13.17 says "as the tick does without
   fetching"); `fab.dispatch` imports `fab.designer`, so the import stays
   inside the function. Its prints go to stderr, so `--brief-only` prints
   the brief alone.
7. **`cut_brief(..., beside: str | None = None)`:** `None` (a replay, or
   the default) adds no section; a string adds `Drafts beside this one`,
   `(none)` when empty. The task is kind `interface`: it adds a parameter
   to a public function (`docs/design/fab.md`, 12).
8. **A cut in flight** is a plan whose latest cut `call.started` (subject
   `fab.designer.subject(draft, "cut")`) has no `call.ended` for its call;
   its tasks are those its directory already holds (none when plan.toml is
   absent).
9. **13.14's page order line** (`docs/design/fab.md`, 13.14, "tiles,
   Waiting on the user, Subscriptions, Drafts, Today, In flight") gains
   Overlaps after Drafts in the page task, so 13.14 agrees with 13.17.
10. **No user questions.** The request settles what is built and where it
    runs; nothing in it is a budget, a machine or hard to reverse.
11. **No counted forms:** the request sets no counts.
12. **Status and design:** `docs/design/fab.status.md` is the designer's;
    a task edits fab.md 13.17 and its status line only for a departure it
    must make.

## The critical path

`overlaps-pure` (45) -> `overlaps-tick` (50): 95 implementer-minutes. The
other two tasks (`overlaps-page`, 35; `cut-beside`, 45) start when
`overlaps-pure` merges and end within it. It is the longest task plus the
one it builds on: the shell and the tick share `fab/overlaps.py` with the
pure part, so they are ordered.
