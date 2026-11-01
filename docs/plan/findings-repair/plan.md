# findings-repair

The repair path of QA findings (`docs/design/qa.md`, 2): the plan is
`plan.toml`, the task specs `tasks/`, the shared notes `notes/`, and the
cut's decisions, critical path and overlaps `notes/decisions.md`.

Overlaps with `findings-loop` that could not be avoided:
`fab/dispatch.py` and its tests (fix-pair, tick-findings beside
backlog-branch) and `fab/channel.py` and its tests (finding-signal beside
ladder-page, delayed until finding-repair has merged). The first three
tasks (fix-module, fix-kinds, finding-repair) touch none of their files.
