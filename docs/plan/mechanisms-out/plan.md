# mechanisms-out: the plan

Three direct parts, one task each, one per request item, in the request's
order (`retired-code` -> `plan-options` -> `land-code-first`). Specs in
`tasks/`, the standing rules in `notes/common.md`, the decisions and the
critical path in `notes/decisions.md`.

The draft beside this one, `hel8-units` (`fab/units.py`, `fab/logins.py`,
`fab/report.py` and their tests), shares no file with this plan.

Within the plan the overlap could not be avoided: all three tasks change
`fab/dispatch.py` and `fab/tests/test_dispatch.py` (the tick's finish),
`retired-code` and `plan-options` share the pre-delivery helper in `_take`
"finish", and `plan-options` and `land-code-first` share `fab/calls.py`.
The request orders them by needs (1, 2, 3), so no two branches are on
those files at once.
