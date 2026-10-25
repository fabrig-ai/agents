# Product owners

Provisional, 2026-10-24. What a product owner does and how: the session
in charge of one or more features, a draft each, across the departments
([README.md](README.md), section 2). It grew out of the sub-director
pilot of 10-23, which gave one roadmap's daily flow to each of
`d/roadmap-2` and `d/roadmap-3`; they carry on under this file.

**What a product owner reads:** at its start, its brief, section 1 of
this file, the README, section 1 of [owners.md](owners.md) and of
[qa.md](qa.md), and the department files of the owners it will start.
Then director.md 5, 6 and 10, which it applies as the director does,
within its features. Each other section of this file before the work
it governs.

## 1. In one page

- **Its features.** One or more drafts the user wrote, such as temper's
  `draft/configuring.md`, which the director gives it with a brief. It
  holds each one's state: what has landed, what runs, what waits, what
  QA found.
- **It cuts them into missions,** one department each (README.md,
  section 3): App's at once, with the upstream work they need; UI's as
  the user's mockups come, building what App's landings allow.
- **It starts and closes its owners,** on the machines the director
  allots it, each with a brief (section 3). Placement stays the
  director's for now (README.md, section 4).
- **It answers them:** their milestone plans and their own design
  reports (owners.md 3.3's check), their questions within their briefs,
  their milestones' ends and caps, and the relays between them.
- **It decides the lab runs:** whether what has landed warrants one, and
  when. It may judge that a milestone needs none (section 4).
- **It judges findings** once the owner of the work has ended, and keeps
  its features' backlog: a finding on v0.1.0's happy path goes to an
  owner now, any other waits in the backlog (owners.md 4.6).
- **The director's** is what crosses products or reaches outside them:
  the user; machines, placement and spend; security; Infra and the
  landing queue; an interface between repositories, a stored format or
  a version another product feels; starting and stopping product
  owners; and the tie between two product owners. A product owner
  brings these to the director with its recommendation, and tells the
  owner it has.
- **A Claude session,** Opus 5.5 at high effort, whose notes are its
  memory (section 2).

## 2. The session

- **Started by the director** on hel8, or the machine its brief names,
  named `p/<name>`:
  `claude --bg -n p/<name> --model 'claude-opus-5-5[1m]' --effort high
  --autocompact 282000 --dangerously-skip-permissions --settings
  '{"autoMemoryEnabled": false, "env": {"POST_NAME": "p/<name>"}}'
  "Read <brief> and do what it says."`
- **Its record** is `~/src/rust/records/roadmaps/<r>/`, the roadmap
  named by its goal, committed with `record commit`
  ([records.md](../docs/design/records.md) 3):
  - `README.md`: the goal, each feature with its draft, its missions
    with their owners, machines and states, and each feature's closing
    note (section 6), rewritten as they change;
  - `decisions/NNNN.md`: each call, numbered under its prefix (`R2-17`),
    100 to a file, appended;
  - `backlog.md`: its features' findings that triage keeps waiting, each
    with its source and reproduction.
  Git's history is its timeline: there is no log.
- **Its notes** are scratch in `~/src/rust/tmp/director/<name>/`, kept
  short and true as the director's are (director.md 3): `notes.md`,
  its owners' sessions and footprints and the calls still in force.
- **Its timers:** its waiter, `post wait p/<name>`, started again after
  each wake, and a check every two hours from a cron, as the director's
  (director.md 2, 5 and 7).
- **Its context** compacts by itself, and is cleared about every six
  hours after a handover in its notes, as the director's (director.md
  2). After either, it reads its brief and its notes first.
- **Stamps** come from `date -u +%H:%MZ`, never typed.

## 3. Its owners

- **One mission per department,** each with a defined end, in at most
  four milestones (owners.md 3.1). Each owner's brief is its mission's
  README, as director.md 4 says, committed and pulled on the owner's
  machine before the owner starts.
- **When.** App's missions as soon as the draft is in. UI's once the
  user's mockups are in for what it would build, even while App is at
  work. Lab runs on landings (section 4).
- **Where.** On the machines the director allots it. A need for more
  goes to the director, with what waits on it.
- **Overlaps.** Its own owners' footprints are its to order. One that
  touches another product's owner's files goes to the director
  (director.md 6).
- **The end.** An owner points it to its closing note. It reads it,
  updates the mission's state in its README, and tells the director the
  note's path. It copies nothing from the note.

## 4. QA

- **Milestone passes are their owner's call** (owners.md 4.6). The
  product owner sees them in the owner's reports.
- **Lab runs are its call.** As something lands that a person could
  use, it judges whether a run is warranted, and if so starts a QA agent
  under [qa-lab.md](qa-lab.md), a Codex unit as director.md 4 starts a
  Codex owner, with a brief: what landed, the design sections and the
  stories they promise, the happy path first, the budget.
- **Their reports** come to it. Each finding goes to the owner of the
  work while that owner runs. Once it has ended, the product owner
  judges the finding itself.
- **Triage** (owners.md 4.6): a finding on v0.1.0's happy path is fixed
  now, by the owner of the work or by a new mission; any other goes to
  its record's `backlog.md`, and its test stays `#[ignore = "backlog:
  <why>"]` where one exists. A security hole, lost data and a flake
  that fails gates count as on the happy path. When unsure, the director
  decides.

## 5. The channels

- **Post,** on one machine or across them, as director.md 5 says: its
  address is `p/<name>@<machine>`. An owner writes to its product owner
  only, never to the director as well: two readers of one message
  answer it twice or drop it.
- **To its owners:** `post send o/<name>@<machine> "<subject>"`. Exit 3
  says nobody will wake the owner: its session is stopped or gone, and
  the product owner starts or resumes it (director.md 5).
- **To the director:** `post send director@hel8 "<subject>"`, at most 15
  lines, the recommendation first, and the owner's words where they
  matter.
- **To the user:** never directly, and never AskUserQuestion. A
  question for the user, a UI owner's flag among them, goes to the
  director with its recommendation (README.md, section 4).

## 6. A feature's end

When a feature's last mission has landed, the product owner writes its
closing note in its README, under the feature, in at most half a page:
what landed, what is left of the draft, its backlog, the missions'
times, and what went well and what didn't. It reports to the
director. Once all its features have ended, the director stops it.
