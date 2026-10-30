# Design contracts

## 1. In one page

- **The design is the contract.** The code in this repository must be
  rebuildable from `docs/design/` at a high level. Describe responsibilities,
  inputs, outputs, state, failure handling and boundaries, without restating code.
- **Cite a design by repository-root path and section,** for example
  `docs/design/sessions.md`, section 3.
- **Each design has a keeper.** Its designer keeps the document and its adjacent
  status file, such as `sessions.md` and `sessions.status.md`, current.
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

**Command references stay beside code** in `tools/**/*.md`. Designs cite those
references for syntax, options and detailed limits. They do not replace them.
Paths below are relative to this repository unless labelled otherwise. Runtime
paths and records-repository data paths are labelled where they are introduced.

## 3. Index

| Document | Owner | Code covered / migration |
|---|---|---|
| `docs/design/pipeline.md` | s/multi-coord | `pipeline/coordinators.toml`, `prompts/`, `tools/lease`; role and landing boundaries |
| `docs/design/sessions.md` | s/multi-coord | `tools/session/`, `prompts/`; launch, context and succession |
| `docs/design/records.md` | s/multi-coord | `tools/records/record`, `tools/records/record-collect`; durable memory and event collection |
| `docs/design/watch.md` | s/multi-coord | `tools/records/watch`, `tools/records/watch.toml`; stuck-work detection |
| `docs/design/status-page.md` | s/multi-coord | `tools/records/status-page`; public index and planned release data |
| `docs/design/fleet.md` | s/deploy | `fleet/`, `tools/fleet-sync`, `tools/installed`, `fleet/bootstrap/`; references `tools/fleet-sync.md`, `fleet/**/README.md` |
| `docs/design/gate.md` | s/deploy | `tools/check.sh`, `tools/land`; host gate lock |
| `docs/design/qa.md` | s/qa | `tools/qa/`; custody, rung walks and planned passes, evidence and live tiers |
| `docs/design/reaper.md` | s/deploy | `tools/reap/`, `fleet/reap.toml`, `fleet/units/reap.service`, `fleet/units/reap.timer`; disposable output and lifetime records |
| `docs/design/after-landing.md` | s/dynamic-memory | `tools/after-landing/`; published-tip checks, verdicts, routing and bisection |

**Migration is owned work.** The remaining migration rows list current text and coverage
responsibility. They do not assert that every tool already has a full design.
Command-reference material remains beside code when its owner extracts a design.

## 4. Later

- Complete the remaining owners' design moves and fill uncovered code contracts.
- Bring the remaining pipeline tools and role files over from fabrig, with designs.
