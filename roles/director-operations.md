# The director's operations

Provisional, 2026-10-26. How the director does its work day to day: the
recipes, the checklists and what it keeps track of between wakes. It is
the director's to write, beside [director.md](director.md), which is the
user's: what the director is and does lives there, how it goes about it
here. Durable know-how belongs here, not in the session's memory or in
`tmp/`.

## 1. In one page

- **Codex does the work; Claude only where taste is the point.** A
  survey, a cleanup, a migration, an investigation, a record chore or a
  machine task goes to a Codex task the director runs (section 10), not to
  a Claude owner. An owner is for a mission whose design, names or tests
  need judgement.
- **Questions to the user in chat are tracked** in the record's
  `STATUS.md`, "Asked in chat", each with its time. One unanswered at the
  first check two hours after it was asked becomes an issue (section 6).
- **A paused mission resumes only on the user's explicit yes** to a
  proposal naming the mission, its machine, why now and its first step. A
  general go ("schedule the next", "saturate") is no resume.
- **A brief is committed and pulled before its session starts,** and the
  commit's output is read: `record` refuses a summary over 60 words, a
  description over 65 characters and a README over 8 KiB (section 2).
- **Kit rollouts go through the gate lane, between landings,** twice,
  skipping a machine with a landing in flight (section 4).
- **The status page is public:** every change to what it shows is read for
  private text before it lands (section 5).
- **Credentials are never read or printed:** tokens live in 0600 files
  and reach a request through a 0600 curl config or a header read from the
  file (section 8).
- **The record is the memory:** decisions numbered, STATUS rewritten,
  times from `date -u`, `unknown` where unknown, never a guess (section
  9).

## 2. Starting a mission

1. **The brief** is `records/missions/<m>/README.md`: the front matter
   (`roadmap`, `feature`, `description` of at most 65 characters, public on
   the status page, `parent`, `owner`, `machine`, `model`, `effort`,
   `started` from `date -u`, `ended`, `state`, `end`), a first paragraph
   of at most 60 words, then: who it is (one line naming its role file),
   the mission with the user's words, why now, where it stands (for a
   resume: the branches, the notes' paths, "check main first"), what
   stays as decided, who is near, budgets and the machine, channels. At
   most 8 KiB: a long input stays in the owner's scratch, named by path.
2. **Commit it** with `record commit -m ... <path>` and read the output:
   "pushed", or the refusal to fix before anything starts.
3. **Pull it on the machine** (`record pull` there), then start the
   session there, in `~/src/rust`, as owners.md 2 says (a designer:
   `-n design/<d>`). Check it is busy with `claude agents --json`.
4. **Notes on another machine** (a resumed mission whose machine retired or
   changed) are copied to the new machine's
   `tmp/owners/<m>/from-<machine>/` with `tar` over ssh, without
   worktrees, `target/` or `.git`, and nothing printed into the stream.
5. **Record it:** a decision, STATUS.md's row, and a post to the owners
   whose files it touches ("whoever lands second rebases").

## 3. Watching

- **The waiter** is `post wait director`, started as a tracked background
  task (the harness's background run), never with `&` in a shell: an
  untracked waiter wakes nobody. After each wake: `post read director`,
  act, start it again.
- **Landings** say what they taught in their `Taught:` trailer, in the
  feed: `landings taught --since TIME` at each check. Owners under the
  director post only questions, escalations, a red's repair and their
  closing.
- **The two-hourly check** (director.md 7), by hand while its tools are
  missing: `record pull`; `agents/scripts/devel/status-page --no-pull
  --out FILE --json FILE` for every machine's disk, memory, load and
  sessions; the subscriptions' use from the live page's Subscriptions
  section; `landings taught --since` the last check; STATUS.md's "Asked
  in chat" (section 6); `tidy` on machines with no landing since the last
  check; a decision recording it.
- **A session that stopped on its own** (state done, no pid, post says
  "nobody will wake it") is resumed in place with `claude --bg --resume
  <sessionId> "<what to read>"` and checked busy.
- **An ended mission's session** is stopped with `claude stop <id>` once
  its closing is committed; a paused one once its resume point is.

## 4. The kit on the machines

- **A rollout** is `heavy --gate -- ~/src/rust/agents/scripts/infra/setup
  --fix`, run twice (setup runs its old copy after moving agents, so a new
  tool link needs the second pass), then `setup` reads clean.
- **Between landings:** a kit move under a queued landing changes its gate
  policy and costs it a retry. Skip a machine whose heavy ledger
  (`tmp/heavy/state.json`) holds an unreleased task labelled `land...` or
  in the gate lane, and come back to it.
- **The runner's machine** (after landing's, on hetzner3) waits for its
  tier run to end before the gate lane drains: up to about twenty minutes.
- **hel8's checkout** feeds the status page's timer: move it after each
  page landing, and run `status-page install --out
  /var/www/status/index.html` when the units change.

## 5. The status page

- **Before a landing that changes what the page shows,** the owner sends a
  page rendered from its worktree against the live fleet. The director
  copies it and scans it: email addresses, UUIDs, session names (`o/`,
  `d/`, `design/`), the user's names and their sessions' names, 40-digit
  hex strings; then reads the changed section. Clean: "land it", and a
  decision. The `--json` file stays private (0600, never served).
- **After it lands:** hel8's checkout moved, the service run once by hand
  (`systemctl --user start status-page.service`), the change checked live.

## 6. The user

- **Asked in chat:** every question put to the user in chat goes into
  STATUS.md's "Asked in chat" with its time and decision. At each check,
  one unanswered for two hours becomes an issue on git.fabrig.ai (section
  7) in the repository it concerns, and leaves the list.
- **Issues** carry the label `waiting-on-user`; the asker closes its issue
  once answered, even when no action is due. What may go into a public
  repository's issue is the user's word (skein, smith, jig, hearth and
  temper there are public mirrors; agents and qa private).
- **Paused missions** resume only on an explicit yes (section 1).
- **Push the user** only for what needs them; a longer matter as a file in
  `tmp/director/for-user/`, sent.

## 7. git.fabrig.ai

- Forgejo 17 on hel8, run by the `fabrig` user as temper's live
  deployment's forge (`/var/lib/fabrig/data/forge-1/forgejo`, Caddy to
  127.0.0.1:3000). The user's account there is `free`.
- **The director's account** `fabrig-director` (site admin); the bot
  `fabrig-agents`, a write collaborator on fabrig-ai/agents, skein, smith,
  jig, hearth, temper and qa. Labels `waiting-on-user`: agents 1, skein 2,
  smith 3, jig 4, hearth 5, temper 6, qa 7.
- **Tokens** in hel8 `~/src/rust/tmp/git-fabrig/` (0600; its README names
  them): `director.token` (the director's alone), `agents-issues.token`
  (copied to machines for the issue tool), `status-read.token` (the page).
- **Accounts and tokens** are made with the Forgejo CLI as `fabrig`
  (`sudo -n -u fabrig <forgejo> --work-path ... --config .../app.ini admin
  user ...`), the CLI's output sent to `/dev/null` or a 0600 file, never
  shown.

## 8. Credentials and the machines

- **Never read** a key, a token, an `auth.json` or `.credentials.json`;
  check a file by `stat` and its sha256 at most. A request takes a token
  through a 0600 curl config built with `printf` (deleted after) or a
  header read from the file, never an argv.
- **A refreshing login** (Claude's, Codex's, ChatGPT's) is never copied;
  the held ChatGPT login is moved, one copy at a time, under its lock,
  through hel8 unread, its sha256 compared on both ends before the source
  goes (it is on hetzner6, `tmp/carry-b/`, since 10-26).
- **The Hetzner Cloud token** (hel8 `tmp/hetzner/api-token`) goes to a
  task only on the user's word for that task.
- **Machines:** hel8 (the director, the status page, dev.fabrig.ai and
  git.fabrig.ai; builds nothing; floor 15 GB, 4 GB memory), and the
  builders hetzner, hetzner2, hetzner3 (Garage, land's turn coordinator,
  after landing's runner), hetzner4 (to retire), hetzner6 (one XFS root),
  each `free@<address>` from `tmp/post/machines`, floor 40 GB. At most two
  building owners each.
- **Retiring a machine:** archive to a kept machine what lives only there:
  branches not on GitHub as bundles, dirty worktrees' diffs,
  `tmp/owners`, `tmp/logs` (with `heavy.tsv`), `tmp/codex-run`,
  `tmp/heavy`, `tmp/post`, the transcripts and rollouts; never the
  sign-ins or keys. Then the post routes, keys and known hosts on every
  machine, then the server. A redeploy keeps the same list.
- **Disk:** a paused or ended mission's `target/` directories are the
  director's to remove once its implementers have stopped.

## 9. The record

- **Decisions** are numbered, a hundred to a file; the 101st opens the next
  file with its `# Decisions N to M` heading. A call answering a post
  cites the post's id.
- **Times** come from `date -u` before writing; what is not known is
  `unknown`, never the time of recording.
- **Text with `%`** goes into records through a here-document or Python,
  never `printf`'s format.
- **The backlog** is capped at 32 KiB: prune what landed or was
  superseded, each with its reason in a decision.
- **No git in a primary checkout** (agents' AGENTS.md): read origin's
  state through a fresh clone or a worktree, never `git fetch` there.


## 10. Codex first

- **The rule** (the user, 10-26: "offload to codex as much as possible"):
  the director spends Claude on judgement (answers, briefs, choices,
  reviews of what is public) and hands everything else to Codex. Before
  starting a Claude owner, ask whether the mission needs taste: a design,
  names, an interface, test worlds. If it is reading, sorting, moving,
  measuring, repairing a machine or filing, it is a Codex task.
- **A Codex task:** a brief in `tmp/director/briefs/t-<name>.md` (the
  goal in the user's words, the sources by path, what it may and may not
  touch, the rules: no credential read, no `pueue`, no scripts in
  `~/src/rust/tmp/`, background commands with `</dev/null`), a work
  directory `tmp/<name>/` (0700) with a one-line README, then `codex-run
  task --effort high --to director@hel8 BRIEF DIR DIR/report.md` from
  hel8. Not `--read-only`: its sandbox blocks ssh and the report. Its end
  comes by post; read the report, act, record a decision.
- **Examples from 10-26:** hetzner6's redeploy, hetzner5's retirement, the
  gate-timeout investigation, the findings' cleanup.
