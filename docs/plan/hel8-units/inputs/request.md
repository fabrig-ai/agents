# Request: hel8's services as persistent units fab owns

From the user, 2026-11-01 (lab.html item 3, approved; via the director, led by agents/status).

Build `docs/design/machines.md` section 4 whole, as designed: `fab serve --install`,
`fab issues --install`, `fab logins check --install` and `fab report daily --install`, all on
the one pattern of `fab/units.py` (dispatcher role only, transient unit of the same name stopped
first, enabled, idempotent, linger warning), every unit running fab from `FAB_HOME/install`
following main as the tick's units do, and `fab serve`'s exit with status 75 when its install's
`HEAD` moves. The design lines changed in `channel.md` 3 and `reports.md` 4-5 come with it.

Owners agreed (11-01): `fab logins check` is agents/creds' (schedule `*:5/30`, TimeoutStartSec
1800, `StandardOutput=null`, no extra lock); `fab report daily` is agents/loop's code (00:30 UTC
over `FAB_HOME/plans`, written here); `fab serve` and `fab issues` are agents/status'. Deployment
on hel8 is ops', after landing, not this plan's.

The user's rule: dogfood. Built by fab's loop (the tick, `bin/fab land`), not by hand. The work is
small; keep the plan small (one or two tasks). Landing `queue` (the cut is started with
`--set 'landing="queue"'`).
