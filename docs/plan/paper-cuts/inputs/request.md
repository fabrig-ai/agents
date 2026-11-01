# Request: paper cuts in fab

From the user, 2026-11-01 (via the session fab-landing-queue-concurrency):
"repair any paper cut you found". Build, as designed:

1. `docs/design/fab-calls.md` section 3, retire: the brief quotes each
   changed design as the shorter of its diff since the plan started and its
   text, fills its section only up to `BRIEF_LIMIT` less the other sections
   and lists the designs that do not fit (`fab.designer.retire_brief`, a new
   helper beside `changed_designs`, which keeps returning paths); the retire
   role text (`fab/roles/retire.md`) and `retire_brief`'s docstring say so.
2. `docs/design/fab-integration.md` section 4, the overlap probe's cache
   (results only, catch-up conflicts included, pruned to this tick's keys,
   written only when changed) and **A malformed record is ignored, never
   fatal** (the probe's folds and `fab/serve.py`'s overlaps).
3. A test of the probe against real git (`fab.tests.support.git_pair()`):
   two trunks off main with one conflicting path containing a space, main
   moved ahead; the probe logs that path; a bad tree is a failure, not an
   overlap.

The user's rule: dogfood. Built by fab's loop (this plan's tasks, landed
through `bin/fab land`). Small work: keep the plan small. The plan's landing
is `queue` (the cut is started with `--set 'landing="queue"'`).
