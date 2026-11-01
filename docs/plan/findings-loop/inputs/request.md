# The request: QA findings handled by fab's loop

From the operator of the findings-loop run (2026-11-01), passing on the user's request. The
design is `docs/design/fab.md`, 13.15 (QA findings); this file says only what the user asked
and what this plan, `findings-loop`, builds of it. The user's drafts stay the rule
(`docs/design/draft/execution-modes.md`: Fix mode, "QA's findings enter Fix mode").

## What the user asked

QA of temper v0.1.0 is run by hand today: a session writes rung briefs, has a Claude subagent
walk each one, triages the findings itself, surveys their causes, has Codex repair the on-path
ones, lands them through fabrig's queue as hand-pushed ready refs, then reruns each brief
unchanged. Off-path findings pile up in a file with no owner. The user wants fab to run this
loop:

1. **Walks** as a fab run kind: a Claude call with the QA role in a box, changing nothing
   outside its scratch; it borrows its login from the shelf, and the tick schedules it with
   logins as resources (one live box per login).
2. **Findings** as events (`finding.raised`), with their rung, reproduction and the component
   they name. A finding with the same reproduction merges with the earlier one.
3. **Triage** by a director-role call: on the path, a repair task in a plan, with "a test in
   the lowest world, red then green" as its acceptance; off the path, the backlog; needs the
   user, a question on the user's page.
4. **Acceptance by itself:** when a rung's repairs have landed, its brief is rerun unchanged,
   and the pass, or a new finding, is recorded.
5. **Then it holds:** a passed rung's story joins the live tier; its fake twin goes into the
   worlds (fab.md 14, Later).

## What this plan builds

The first cut of items 2-4, on walks a session still starts by hand: the parts 13.15 lists
under "Built in this order" as **Now, independent**:

- the plan's `[[rung]]` and `[ladder]` (`fab/plan.py`);
- the findings' and rungs' fold (`fab/findings.py`);
- `fab qa` and the intake (`fab/walks.py`, `fab/cli.py`);
- the triage call: its role text, brief and decisions (`fab/triage.py`,
  `fab/roles/triager.md`, `fab/calls.py`), and the tick's triage steps: starting the call
  when due, recording its decisions, rendering and readying the backlog;
- the page's `finding` asks and `## The ladder` (`fab/channel.py`);
- the landing report's QA figures (section 10).

**Not in this plan:** what 13.15 says waits for red-routing's tick wiring and page
(the repair path: `fab/fixes.py`, `fab/roles/foreman-finding.md`, what 13.15 factors out of
`fab/tier_reds.py`, the tick's foreman and repair steps, the `finding-<n>` signal) and walks run by fab.
They are a second plan, cut once red-routing's code has landed on main.

Every task lands through `bin/fab land` (this repository), with `bin/fab test` green.
