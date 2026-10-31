+++
id = "run-defaults"
part = "replay"
kind = "migration"
needs = ["integration-check", "replay-roles"]
files = ["fab/plan.py", "fab/designer.py", "docs/plan/agents-rebuild/plan.toml", "fab/tests/**"]
effort = "high"
minutes = 30
+++
# The run's flow becomes fab's default

docs/design/fab.md 13.12 ("The options"): the defaults are now the run's
flow, `landing = "integration"`, `ready = true`, `reviews = false`,
`direct = true`; the old flow is the options `landing = "queue"`,
`reviews = true`, `direct = false`.

## What to change

- `fab/plan.py`: the `Plan` dataclass defaults and `load_plan`'s defaults
  for the four options become the run's flow (one place for them, so the
  two cannot differ); docstrings say so.
- `fab/designer.py`: `uncut` follows (it already takes the dataclass's
  defaults; check it).
- `docs/plan/agents-rebuild/plan.toml`: the three old-flow keys at the
  top, so the agents repository's own plan keeps its flow
  (`bin/fab status docs/plan/agents-rebuild` shows no problems).
- `fab/tests/**`: tests that build a `Plan` or a plan.toml relying on the
  old flow name it explicitly (a helper in `fab/tests/support.py` that
  gives a Plan with the old options is fine); tests of the defaults assert
  the new ones. Change no test's meaning otherwise.

## Acceptance

- A plan.toml without the keys loads as an integration plan with reviews
  off and every part direct; the agents-rebuild plan loads with its three
  keys and no problems.
- `bin/fab test` passes within its budget.
