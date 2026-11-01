# citation-sweep: the cut's decisions

What the request and `docs/design/fab.md` 6 left to the cut, each settled with
its reason. The spec binds them.

1. **One task, not two.** The request allows one or two, by directory, but
   `fab/tests/` holds a single rewrite and `fab/roles/` none. A second task
   would be one line.
2. **`fab.md, 2`, `3` and `4` stay.** They already use the split's numbers,
   and the text is there. The split itself rewrote old 8 to `fab.md, 4`, so a
   test module's `fab.md, 4` means Tests, not old 4 (Plans and tasks). This
   covers `fab/log.py`, `fab/hosts.py`, `fab/hosts.toml`, `fab/cli.py`,
   `fab/state.py`, `fab/testrun.py` (both), `fab/sh.py` and every test
   module's header.
3. **`fab.md, 6` is rewritten, though the table gives it.** The split mapped
   old 13 to section 6, which only lists the designs, and the request keeps
   sections 1-5 alone. So `fab/dispatch.py`'s header becomes
   `docs/design/tick.md, 1` ("reads them and the event log and decides every
   action") and `fab/calls.py`'s becomes `docs/design/calls.md, 1`, the
   overview of the design that now holds Claude calls.
4. **`bin/heavy`'s `fab.md, 7` becomes `docs/design/machines.md, 2`.** It is
   old 7, Slots and disk, which the split missed; `fab.md` 7 is now Later.
5. **`fab/forge.py`'s bare `(13.6)` is in scope and goes to
   `docs/design/channel.md, 3`, not the table's 2.** The request's greps miss
   it, but it is an old number. The text it cites, the issue body's excerpt
   and parked reason, is in `channel.md` 3 (old 13.16), which the module's
   header already cites.
6. **`fab/atomic.py`'s `fab.md, 2` stays and the report names it.** Section 2
   never held the hidden-sibling rule, and no design does: it is `AGENTS.md`'s
   rule, and the designs only use `fab.atomic.write`. The number is not an old
   one, so the sweep has nothing to rewrite it to.
7. **`fab/tests/test_dispatch.py` ~665 stays and the report names it.**
   `"see fab-gates.md, 2"` is a test's answer value, neither a comment nor a
   docstring. No assertion reads it, but the request limits the sweep to
   comments and docstrings.
8. **`fab/calls.py` ~139 stays.** Its `fab.md, 4` is an example of a `design`
   value, and a valid one.
9. **`fab/roles/` and `bin/fab` need nothing.** `fab/roles/implementer.md`'s
   `fab.md`, section 4 means Tests and holds; `bin/fab` cites the whole
   document.
10. **Other bare `section N` hits are not citations of fab's design:**
    `fab/landing_report.py` ~312 and `fab/designer.py` ~368 name other
    documents' sections, and `fab/tests/test_calls.py` ~308 is a fixture's own
    `design.md`.
11. **`docs/design/qa.status.md`'s "Stale citations" bullet goes.** It records
    the four `13.15` citations this sweep rewrites and would be false once
    they land. `docs/design/fab.md` 6 keeps its tables: plans, commits and
    status files still use the old names.
12. **`kind = "feature"`:** no signature changes, and `status-current`, a
    task that changed only status files, set this precedent.
13. **No counted forms and no user's questions:** the request sets no counts,
    this repository has no `scripts/old_forms.py`, and nothing here is the
    user's.
14. **Critical path:** `sweep`, 15 implementer-minutes.
