# The pipeline

2026-10-30. Owner: s/multi-coord. Code: `pipeline/coordinators.toml`,
`prompts/`, `tools/session/`, `tools/lease`. References: `tools/session/start.md`
and `tools/lease.md`. External role and tool locations are recorded in
`docs/design/pipeline.status.md`.

## 1. In one page

- **One coordinator per draft.** Each has its own ephemeral leads, one per
  coordinator, area and part. A lead carries one part; leads are not shared.
- **The director holds priorities and the user's questions.** Coordinators own
  designs, tasking and review. Leads turn a part into bounded Codex work.
- **Shared resources have owners.** Ops runs capacity and the queue. Coordinators
  lease packages and documents before tasking overlapping work.
- **Identity comes from the registry.** Launchers, wake ownership and watch use
  one naming contract instead of guessing supervisors from a branch or mailbox.
- **Land in the repository that owns the change.** Agents uses `tools/land` and
  `tools/check.sh`; fabrig uses its existing merge queue.

## 2. Roles and boundaries

| Role | Owns |
|---|---|
| Director | Draft priorities, scheduling coordinators, recorded user questions and decisions, unresolved disputes between coordinators |
| Coordinator | Its draft's designs and status, parts and ephemeral leads, task scope and review, its wave's leases |
| Lead | One part's brief/common/state working set, reconciliation, Codex tasks and reports to its coordinator |
| Codex implementer | A bounded task, its branch, checks and report in its own checkout |
| Codex owner | A persistent named worker receiving mail between turns; it can carry a lead when the registry selects Codex |
| Ops | Machines in operation, disk, credits, slots, capacity and fabrig's queue; branch or slot trouble goes to its coordinator |
| s/deploy | Machine configuration, fleet declarations, units, bootstrap, deployment and the agents gate |
| s/multi-coord | Pipeline conventions, registry and launcher/context contracts, leases, records, watch and public status tools |

**The director stays out of operating loops.** It receives matters requiring
judgement and matters belonging to the user. A lead reports to its coordinator.
Coordinators settle ordering directly; unresolved disputes go to the director
with both positions and a recommendation. Ops sends user matters there too.
Only the director batches questions to the user, with options and a recommendation.
Records hold decisions and questions (`docs/design/records.md`, sections 2–3).

## 3. Names, launches and tasks

**The registry is `pipeline/coordinators.toml`.** Handles map to unique `s/...`
mailboxes; exactly one is default. The default `dm` retains `lead/AREA`, branch
key `AREA` and coordinator prefix `coord`. Others use `lead/H/AREA`, branch key
`H-AREA` and coordinator prefix `H`. Areas are skein, smith, jig and temper.
`tools/session/start names --json` gives identities, aliases, supervisors and
pause state. `tools/session/names H [AREA]` gives derived paths and names.

**Prompts are launch inputs.** `prompts/lead.md`, `prompts/coordinator.md` and
`prompts/director.md` define starts; `prompts/coordinator-next.md` and
`prompts/director-next.md` define read-only warm-up and explicit takeover.
They name the role files and working state to read. The launcher substitutes
registry-derived values strictly. Launch and succession are
`docs/design/sessions.md`, sections 2–4.

**Every task carries its join keys.** A task file begins with `+++` TOML:

```toml
+++
task = "example"
branch = "q-skein/example"
coordinator = "s/qa"
draft = "qa"
area = "skein"
part = "example"
+++
```

**Required keys are task, coordinator and draft,** plus branch for writable
runs. Supply area and part when applicable. Values are double-quoted without
embedded quotes or backslashes. Resumes without a header inherit prior keys;
owner briefs need none. Enforcement and prompt coverage are tracked in
`docs/design/pipeline.status.md`. The collector consumes these joins; command
reference: `tools/records/record-collect.md`.

## 4. Sharing packages and documents

**Lease a wave before tasking it.** `tools/lease take OWNER WHAT SUBJECT...`
takes `pkg:NAME` or `doc:TREE/docs/design/NAME.md` (also foundation documents).
A document and its status companion share one lease. Validation reads committed
fabrig manifests and document paths, never a build. Release when the wave lands.

**Wait or obtain a named lend.** `want` queues FIFO, `lend --to BRANCH` grants
one branch access, and `release` notifies the first waiter after unlocking.
The borrower stacks on the holder's branch and preserves the holder's changes.
There is no expiry or automatic takeover. `list --json` exposes holder, lends
and waiters; `check OWNER --repo PATH --base REV --tip REV --branch NAME` checks
the branch's changed packages and documents. The command reference defines
exemptions and exit codes (`tools/lease.md`, "Branch checks").

**Change upstream interfaces in order: expand, move, contract.** Land the
upstream expand alone under a short lease. Before removing an old form, get
acknowledgement from each coordinator leasing a reader. Tell reader holders
about changes of meaning. Keep one writer per shared role or operations file;
other agents send that keeper their proposed change.

## 5. Landing and deployment

**Agents lands through its gate.** `tools/land` requires a clean named branch,
runs `tools/check.sh`, fetches and rebases on origin/main, reruns the gate if
HEAD changed, then pushes HEAD to main. A host lock serializes the gate through
publication. Run the gate with fixture services and temporary HOME. A commit
needing machine action says what action is needed.

**Fabrig keeps the merge queue.** Leads publish `ready/KEY/TASK`; the queue's
lead mapping routes results. Records read queue facts; they do not land work.
Fleet deployment belongs to s/deploy; see `tools/fleet-sync.md`.

## 6. Later

- Complete the role/tool move into agents and update prompts and keepers together.
- Enforce leases in fabrig's queue if advisory evidence warrants it.
- Extend lease subjects to agents design paths if cross-coordinator work needs it.
