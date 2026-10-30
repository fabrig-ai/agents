+++
id = "cutover-fabrig"
part = "cutover-landing"
kind = "migration"
repo = "fabrig"
needs = ["queue", "precheck", "codex", "run-slots"]
files = ["tools/**", ".config/gate/**", "AGENTS.md"]
effort = "medium"
minutes = 20
+++
# fabrig: hand its landing tools over to fab

fabrig's merge queue, precheck, heavy, slots and Codex launcher now live in
the agents repository as fab (`docs/design/fab.md` there, sections 6-7).
Remove fabrig's copies and point its rules at fab. This change is the first
to land through fab's queue.

## What to change

- Move `tools/queue/always.txt` and `tools/queue/read-by-tests.txt` to
  `.config/gate/` (git mv, contents unchanged).
- Delete `tools/queue/`, `tools/heavy/`, `tools/slots/`, `tools/codex-run/`,
  `tools/session/`, `tools/install`, `tools/installed` and
  `tools/test_install.py`. Keep `tools/tiers/`: after-landing still uses it.
- Search the rest of the repository for those paths (`rg -n
  'tools/(queue|heavy|slots|codex-run|session|install)'`) and for
  `precheck`, `ready-check` and `claim`; a mention outside `agents/` that
  states a rule must follow the new tools. `agents/*.md` (the old role files)
  stay as they are: they retire with the old roles.
- In `AGENTS.md`:
  - section 5: the builders are hetzner6 (8 cores, 15 GB; heavy admits three
    builds); hetzner8 runs the gate; hel8 builds nothing. heavy waits for
    disk by itself, reclaiming idle slots, up to 20 minutes; its exit 75 is
    `Infra: disk`, reported, never worked around. Drop the 40 GB floor and
    `heavy --cancel`.
  - section 6 and wherever precheck is named: `fab precheck SLOT TIP`.

## Acceptance

- The moves and deletions above, and `AGENTS.md` as described, in one or two
  commits.
- No remaining reference to a deleted path outside `agents/`.
- `fab precheck` on your tip in your slot is green (a full selection: the
  change touches `.config`), with its receipt path in your report.
