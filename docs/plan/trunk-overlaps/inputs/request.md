# Request: drafts beside each other

From the user, 2026-11-01 (via the session fab-landing-queue-concurrency).

Build `docs/design/fab.md` section 13.17 whole, as designed: the overlap
probe (`fab/overlaps.py` and its call from the tick, the `trunks.overlap`
event), its line on the status page (13.14), and the cut brief's `Drafts
beside this one` section with its one line in the cut's role text. Report
only: nothing waits on an overlap. Its Later items (a build of the merged
trunks, landing at slice boundaries) are out of scope.

The user's rule for this work: dogfood. It is built by fab's loop (this
plan's tasks, run by the tick, landed through `bin/fab land`), not by hand.
The work is small; keep the plan small to match.
