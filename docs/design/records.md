# Records

2026-10-30, s/multi-coord. The pipeline's memory: what was decided, what happened, where each role stands, and what the work cost. It replaces free-form notes and handovers wherever another agent or a retrospective needs them. Code: `tools/records/` (`record`, `record-collect`), the session launcher's hooks (`docs/design/sessions.md`). The stuck-work watch is `docs/design/watch.md`, the status pages `docs/design/status-page.md`.

## 1. In one page

- **Two stores:**
  - **The records repository** (`fabrig-ai/records`, git): durable, small and readable. It holds decisions, incidents, each role's state and journal, parts, task summaries and the slow-tier verdicts. `record` is its only writer.
  - **Each host's event spool** (`~/src/fabrig/events/`, not git): raw events for the live tools, kept for 2 hours.
- **Agents keep their own working files** (scratch notes, task files, reports) for their own use only. Anything another agent picking up the work needs, or that a retrospective would want, goes into records.
- **Least effort:** one short command per fact. The writer and its role come from the session's environment. The launcher, the hooks and the collectors write everything they can see themselves: part starts and ends, handovers, task summaries.
- **The questions records answer:**
  - Is each line of work moving: landed, rejected, waiting?
  - Where is time lost?
  - What does it cost?
  - Where does each role stand, and what did it decide, and why?
  - What went wrong, and what was done about it?

## 2. The records repository

| Path | Written by | What |
|---|---|---|
| `drafts/<draft>/draft.toml`, `director/priorities.toml`, `director/questions/NNNN.toml` | the director (`record draft`, `priority`, `ask`; anyone `answer`s) | the drafts, their order, and the user's questions |
| `drafts/<draft>/decisions/NNNN.md`, `director/decisions/NNNN.md` | `record decide` | one decision per file: context, options, choice, why, who |
| `drafts/<draft>/parts/<area>-<part>/brief.md` | the launcher, at `start lead` | the part's brief as given |
| `drafts/<draft>/parts/<area>-<part>/closing.toml` + `closing.md` | `record close part`, at a lead's end (or its coordinator's) | landed, withdrawn, open; what the code taught |
| `sessions/<role>/<mailbox>/state.toml` | `record state` | the role's current state (section 3); a successor inherits it |
| `sessions/<role>/<mailbox>/journal/<YYYY-MM-DD>.jsonl` | `record log`, and the tools themselves | the role's timeline (section 3) |
| `incidents/<YYYY>/NNNN.md` | `record incident` | one incident per file (section 3) |
| `tasks/<YYYY-MM-DD>/<task key>.toml` | the summarizer (section 4) | one summary per finished task |
| `events/after-landing/<host>/<YYYY-MM-DD>.jsonl` | after-landing's writer | the slow tiers' verdict per main commit; durable, because QA chooses commits from it |
| `releases/<release>/` | `record item`, `record page` | the public release page's data (`docs/design/status-page.md`) |
| `old/` | nobody | the legacy archive, read only |

- **`record` validates every write:** the path's schema, size caps, a secret scan, and the writer's right to the path. It commits under a lock and pushes with a rebase retry. Each call makes one commit; the summarizer makes one per run.
- **Git history is the archive.** Nothing is deleted to save space, so what enters must be worth keeping. Raw events never enter through the writer. After the spool tools are deployed
  on every host, a separate history rewrite removes historical raw events while
  keeping `events/after-landing/`; see `docs/design/records.status.md`.
- **A rewritten upstream must not be replayed.** Before pulling or rebasing,
  `record` refuses more than 20 local-only commits or any local-only commit
  touching raw `events/` paths; `events/after-landing/` is exempt. The refusal
  directs the caller to `record reset`. Reset locks the clone, fetches, saves
  every local-only commit as a binary/full-index patch with a commit manifest
  in permanent `~/src/fabrig/archive/records-local-<UTC stamp>/`, and resets to
  `origin/main`. It prints the archive path/count and old/new HEAD. Untracked
  files remain; tracked edits and untracked paths that would be overwritten
  refuse. Repeating reset leaves HEAD unchanged. Review saved patches before
  restoring judgements; never replay raw-event history.

## 3. A role's state, journal and incidents

- **State** (`state.toml`, one per role mailbox, overwritten; history keeps every version) is what the role's handover and `state.md` were. Its fields:
  - `doing`: one line;
  - `in_flight`: the role's runs, branches, slots, leases and questions, each with what, ref and since;
  - `next`: actions in order;
  - `blocked_on`: what, on whom, since;
  - `owed`: to whom, what;
  - `notes`: at most 2 KB.

  `record state` sets or edits one field per call (`--doing`, `--add`, `--done REF`, `--next`, `--blocked`, `--owed`), or replaces all of it from a file. A successor reads it first. `start ... --next` journals the handover against the state's commit.
- **Journal** (append-only, one file per role and day): typed one-line entries. Each has a time, a kind and a text of at most 300 characters, plus refs (a branch, run, decision, incident, question or commit). The kinds: `started`, `ended`, `handed-over`, `decided`, `incident`, `asked`, `answered`, `landed`, `rejected`, `note`.
  - Agents add a `note` with `record log TEXT` for a milestone a successor or a retrospective needs.
  - The tools add the rest themselves: the launcher at start and handover; `record decide`, `incident`, `ask` and `answer` journal their own entry.
- **Incidents** (`incidents/<YYYY>/NNNN.md`): something broke or went wrong beyond a red test. One file per incident, with front matter (title, opened, by, status `open|resolved`, refs) and sections for what happened, impact, cause, fix and follow-ups. `record incident open|update|resolve` writes it. `record status` lists the open ones.
- **`record status`** shows, on one screen, the drafts and priorities, each role's `doing` and `blocked_on`, open incidents, open questions, and the last day's task summaries per draft.

## 4. Events on hosts, and task summaries

- **Each host's collectors** (`record-collect`, timer units declared in `fleet/units`) copy what producers write into the host's spool, `~/src/fabrig/events/<source>/<YYYY-MM-DD>.jsonl`. Each event has a stable id, so a re-collection never duplicates. Each run then drops events older than 2 hours, rewriting files atomically under the source's lock. Producers keep their own files, which are only read.
- **Sources:**
  - `runs`: Codex runs: task header keys, model, effort, minutes, tokens, exit;
  - `queue`: the merge queue's batches and attempts;
  - `heavy`: build and test commands;
  - `sessions`: session starts and ends, handover firings, `files current`; no context readings;
  - `claims`, `leases`;
  - `post`: mail and read metadata, never bodies;
  - `post-sent`;
  - `watch`: alerts and heartbeat.
- **Readers** take events from each host's spool: locally, or over the watch's ssh probe. They are the watch (`docs/design/watch.md`), the status page and the summarizer.
- **The summarizer** (`record-collect summarize`, on hel8 after each collection) joins events into tasks.
  - **The join:**
    - the task header's keys;
    - the branch, with `ready/` stripped;
    - the coordinator, normalized to its handle through the registry and the drafts.
  - **A task ends** when its branch lands or is withdrawn, or when a run without a branch ends. Its summary then goes into `tasks/<date>/`. It holds the task, branch, draft, coordinator, area and part; the launch, ready, landed or ended times; the outcome; runs (count, minutes, tokens, model, effort); queue attempts and rejected steps; and the waits (run end to first attempt, first attempt to landing).
  - Open tasks are carried in the summarizer's local state across the 2-hour window.
- **The task header** (`codex-run`'s check, `+++` TOML at the top of each task file) is what makes the join exact: `task`, `coordinator`, `draft`, and `branch` unless read-only.
  Unclosed or invalid TOML headers, invalid join values and unreadable task files
  do not stop run collection. Affected events omit task and recipient joins and
  carry a short, content-free `header_error`; run identity, lifecycle and cost
  remain. The runs summary counts annotated events, so affected start and end
  events count twice. Other producer failures still fail collection.

## 5. Habits (for the prompts and role files)

- Keep your state with `record state` after each event that changes it. It is your handover.
- A decision: `record decide`. Something broke: `record incident`. A milestone: `record log`.
- Ask the user only through the director (`record ask`).
- Scratch files are for your own working. Never leave the only copy of a decision, an incident or your state in them.

## 6. Later

- `record report` over task summaries: throughput, waits and cost per draft and coordinator, and a task's timeline.
- The release page tool (`docs/design/status-page.md`).
- User questions mirrored as Forgejo issues.
- Search across journals and incidents.
- Remove R1's `sessions/<role>/<name>/<stamp>-{handover,state,common}.md` snapshot paths once `state.toml` and journals have replaced them.
