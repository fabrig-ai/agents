# dogfood-faults: the plan

Eight direct parts, ten tasks, one per request item (item 3 in two parts,
item 7's worktree rerun with item 5). Specs in `tasks/`, the standing rules
in `notes/common.md`, the decisions and the critical path in
`notes/decisions.md`.

No draft is beside this one, so no overlap with another draft's files.
Within the plan, five tasks change `fab/dispatch.py` and
`fab/tests/test_dispatch.py`: `retire-main`, `stop-record`, `stop-lift`,
`rebase-trunk` and `call-env`, ordered by `needs` in the request's order;
`stop-record` and `stop-lift` also share `fab/integration.py`. That
overlap could not be avoided: each fix's site is in the tick.
