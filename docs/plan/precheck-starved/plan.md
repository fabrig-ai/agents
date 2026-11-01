# precheck-starved: the plan

One direct part, one task, as the request asks:

- `precheck-collector` (`docs/design/landing.md`, 2, "The selection and
  the steps are shared", already saying so; "Starvation stays green in
  the gate"): `fab precheck` runs its `default` and `fuzzy` steps through
  `fab.queue_cpu.run_steps`, in the build lane. A step red only by
  starvation is green, the receipt gains `starved`, the log names the
  starved tests.

The spec is `tasks/precheck-collector.md`; the standing rules are in
`notes/common.md`, the decisions and the critical path in
`notes/decisions.md`. The task leaves `docs/design/` alone: the design is
written, and its status line is the retire call's.

## Overlaps with drafts beside this one

- The task changes `fab/precheck.py`, `fab/queue_cpu.py`, their tests and
  perhaps `fab/tests/landing_checks.py`. No task of `mechanisms-out` or
  `start-commands` lists any of them: no shared file.
- `df-followups` is still being cut; its request is about calls after a
  trunk lands, not precheck or the collector.
