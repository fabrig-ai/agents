# Status page

Provisional, 2026-10-25, with the user. One page for the whole fleet,
https://status.fabrig.ai. It shows the work in flight and what
building, testing and landing cost. `scripts/devel/status-page` writes
it every 10 minutes on hel8 from what the tools already keep, and Caddy
serves it.

## 1. In one page

- **Why.** The facts are all recorded, but on six machines and in
  seven formats. `landings report` answers for landing alone, on the
  coordinator, and `record runs` only per mission. "A script that
  generates an HTML status/dashboard page from those records … all
  in-flight work and their status plus statistics about
  build/test/landing times" (the user, 10-25).
- **It reads and never writes.** Each machine's part is read from the
  files and commands its tools keep (section 2). Nothing new is
  recorded, and no tool changes for the page.
- **Nothing to install on the fleet.** The writer pipes its own source
  to each machine over SSH, into `bash -lc 'exec python3 -I - collect'`
  (a login shell, infra.md 2), with the options `landings` uses, so
  that every machine runs the version that renders.
- **One failure leaves the rest.** An unreachable machine, a source it
  cannot read, a field of the wrong type or a section whose data makes
  no sense is named in the page's footer, and everything else is still
  written. A field of the wrong type is a missing one, as in
  `landings`. The detail goes to the journal.
- **Public, without the director's notes.** The page is served to
  anyone, so it holds no text from `records`' `STATUS.md` nor from a
  mission's README beyond its front matter's state, owner and machine
  (the user, 10-25). Only a background Claude session, which the
  launchers name, shows its name; any other is someone's own. An
  unreachable machine shows why in a few words (refused, timed out, key
  refused); ssh's own, which name the target, go to the journal.

## 2. Sources

| Source | Where | What the page takes |
|---|---|---|
| heavy's rows | each machine's `tmp/logs/heavy.tsv` | the last week's commands: wait, run, exit, kind, mission |
| heavy's ledger | `tmp/heavy/state.json` | the tasks queued and running, and whether a gate holds the machine |
| the landings feed | the coordinator's `~/.local/state/agents-land-set/feed.jsonl` | set runs and their results' gate steps (landing-flow.md 10) |
| the landing turns | `tmp/landing-turn/events.jsonl` | each turn's wait and hold, and the turns open now; a `fail-open` closes one |
| codex-run | `tmp/codex-run/*/meta`, `runs.tsv`, `tmp/owners/*/codex/` and the `codex-*` user units | runs and owners running, and the runs that ended |
| post | `tmp/post/*/new` | unread mail per box |
| Claude | `claude agents --json --all` | the live sessions, busy or idle |
| the records | `records/missions/*/README.md`, after `record pull` | each mission's state, owner and machine |
| the machine | `/proc`, the disk under `tmp/` | load, free memory and disk |

A command's kind is `record runs`' (records.md 5.1): `land <repo>` and
`land <repo> prebuild` labels are land's gate and prebuild, and the
rest by the cargo command. A command's mission is its working
directory's under `tmp/owners/`.

## 3. The page

- **Tiles:** missions, sets landing now, heavy commands now, agents
  working, commands and land gates in the last 24 hours.
- **In flight:** what is landing (set runs, `land`'s prebuilds and
  gates, landing turns) and the last eight set runs. A set is in flight
  when its latest run, as `landings` finds it, has not ended and was
  heard from in 6 hours: a killed `land-set` writes no end, and a turn
  is lost the same way. the missions; one
  card per machine with its heavy tasks, Codex runs and owners, Claude
  sessions and unread post.
- **Costs,** for the last 24 hours or 7 days: command time per hour or
  4 hours, running and waiting; each kind's medians and p90s; each
  machine's; land's gates and prebuilds per repository; land-set's gate
  steps; set runs' lock wait and run; the landing turn; Codex runs and
  tokens per model.
- **A mission shows** when the record holds it active or paused, when
  anything runs for it now, or when it has commands in the last 24
  hours and the record doesn't say it ended. Directories under
  `tmp/owners/` alone bring in nothing: the sweeps touch ended ones.
- The page reloads itself every 5 minutes, carries `noindex`, and works
  in light and dark. Every chart has a table beside it.

## 4. Serving

On hel8, whose name `status.fabrig.ai` is (a CNAME of `fabrig.ai`):

- hel8's own key reaches every machine of `tmp/post/machines` with a
  shell, and each is in its `known_hosts` (checked 10-25). post's
  restricted key is not enough.
- `~/src/rust/agents/scripts/devel/status-page install --out
  /var/www/status/index.html`, from the checkout and never a worktree,
  writes the user units `status-page.service` and `status-page.timer`
  (`OnCalendar=*:0/10`) and starts the timer. The service runs the
  checkout's script in a login shell (infra.md 2), so that `setup`'s
  fast-forward brings each change.
- `/var/www/status` belongs to `free`. The page is replaced atomically,
  mode 0644, so Caddy never reads half of one; `--json` writes 0600.
- `/etc/caddy/Caddyfile` holds:

  ```
  status.fabrig.ai {
  	root * /var/www/status
  	file_server
  	header Cache-Control "no-cache"
  }
  ```

To take it down: `systemctl --user disable --now status-page.timer`,
remove the two units from `~/.config/systemd/user/`, then the Caddy
block (`/etc/caddy/Caddyfile.pre-status-page` is the file before it)
and `systemctl reload caddy`.

## 5. Testing

`scripts/devel/test-status-page`, in `scripts/check.sh`: temporary
trees for two machines and the records, a fake `ssh` that runs the
piped collector on the second and fails the third, and fake `claude`,
`systemctl` and `record`. It checks each source's figures, a machine
with none of them, the page (no private text, the down machine, the
sets in flight, mode 0644), a failing pull and a missing records tree,
fields of the wrong type and markup in names, a machine answering
nonsense, a page that cannot be written, and the units `install`
writes.

## 6. Open

- Mission names are public. If one ever must not be, the page needs a
  filter, or a login in front of it.
- The roles don't point at the page yet.
