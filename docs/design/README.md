# Design contracts

## 1. In one page

- **The design is the contract.** The code in this repository must be
  rebuildable from `docs/design/` at a high level. Describe responsibilities,
  inputs, outputs, state, failure handling and boundaries, without restating code.
- **Cite a design by repository-root path and section,** for example
  `docs/design/fab-tick.md`, section 3.
- **Each design has a keeper.** Its designer keeps the document and its adjacent
  status file, such as `fab-tick.md` and `fab-tick.status.md`, current.
- **Every design closes with Later.** Put deferred work there. The status file
  says where code lags or departs, with the code or check that establishes it.
- **Change both in the same branch** when a change alters a design. A planned
  contract may precede code only when its status file makes that gap explicit.
- **The user's input lives in `docs/design/draft/`.** Agents read it and never
  edit it. A designer turns the input into a design outside that directory.

## 2. Writing and references

**Use numbered sections,** starting with "In one page". Write short plain
sentences with bold leads. Keep implementation detail in the code and command
reference. Index and draft READMEs explain the directory; they are not designs.

**Command syntax stays in the code** (`bin/fab` and its modules' docstrings).
Designs cite it for options and detailed limits; they do not replace it.
Paths are relative to this repository unless labelled otherwise. Runtime
paths (`FAB_HOME`, other repositories) are labelled where they are introduced.

## 3. Index

All of the pipelines' code is fab (`fab/`, `bin/fab`); its designs are owned
by the user's pipeline session. `docs/design/fab.md` is the overview and holds
what the others share; its section 6 maps citations of older names.

| Document | Subsystem |
|---|---|
| `docs/design/fab.md` | overview, where things live, the event log, tests, what is left out |
| `docs/design/fab-tick.md` | plans, runs and the tick |
| `docs/design/fab-calls.md` | Claude calls, review and the designer |
| `docs/design/fab-landing.md` | landing |
| `docs/design/fab-machines.md` | builders, slots, disk and logins |
| `docs/design/fab-reports.md` | reports, accounting and the status page |
| `docs/design/fab-after-landing.md` | after landing |
| `docs/design/fab-gates.md` | gates and the structure review |
| `docs/design/fab-channel.md` | the channel to the user |
| `docs/design/fab-integration.md` | plans on fabrig and integration trunks |
| `docs/design/fab-qa.md` | QA findings |

The old pipeline's designs were deleted with its code on 2026-11-01; they
are in history at 7a7df4f.

## 4. Later

- None.
