# Request: a finding repair leaves the plan's rung briefs

From fabrig/qa, 2026-11-01: repair task `v0.1.0-ladder/finding-17` (4ee24bd08e) edited
`temper/docs/plan/v0.1.0-ladder/kit.md`, a rung brief file. A brief change makes a new edition, so
it reopened every rung and reset 13 passes. fabrig/qa is reverting the kit by hand. A brief's edit
should be triage's `brief` decision. The design says how (`docs/design/qa.md` 2, "A repair leaves
the briefs").

Build:

1. **The check, by code.** In `fab/dispatch.py` `_screen_ready` (fabrig's readying), before
   `_ready`, for a task of the `finding` kind in `fab.fix.FIX_KINDS`: compare the task's branch
   with its merge base on `origin/main`. A changed path among the plan's rung brief files refuses
   it: `branch.rejected` with step `gate:briefs` and `findings` naming the paths, the shape
   `rust_gates.screen` logs. `_screen_ready` needs the plan (or the brief paths): pass it from
   `_take`. A refused repair then goes to its refusal foreman as any gate refusal does.
2. **The text.** `fab/fixes.py` `_body`'s Acceptance gains: "The plan's rung briefs are not this
   repair's to change: leave them, and say so in your report if one is at fault." The same line
   goes in `fab/roles/foreman-finding.md`, so a foreman never asks a repair to edit one.
3. **Tests:** a finding repair touching a brief file is refused and never readied; one touching
   other files is readied; a non-finding task touching a brief file is not checked. Fakes and
   fixture logs, as `fab/tests/test_dispatch.py`'s gate tests do.

The user's rule: dogfood. Built by fab's loop (landed through `bin/fab land`); the plan's landing
is `queue` (the cut is started with `--set 'landing="queue"'`). One direct part, one task.
