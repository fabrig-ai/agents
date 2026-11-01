# Request: hel8's services as persistent units fab owns

From the user, 2026-11-01 (lab.html item 3, approved; via the director, led by agents/status).

Build `docs/design/machines.md` section 4 whole, as designed: `fab serve --install`,
`fab issues --install`, `fab logins check --install` and `fab report daily --install` through one
new installer in `fab/units.py` (`install_units`, beside the queue's and after-landing's, which
stay unchanged), the units' exact texts, `fab serve`'s HEAD watch (exit 75), `fab report daily`
with no plan dir, and the design lines changed in `channel.md` 3 and `reports.md` 2 and 4-5. The
design's rules to keep, as written there: transient units are stopped only when `systemctl show
--property=Transient` says `yes`, and an active transient timer's service refuses the install;
only `fab-status.service` is ever restarted (a timer's service never); a pause stays; no unit
fetches (the tick alone moves `FAB_HOME/install`); `StandardOutput=null` with
`StandardError=journal` for the login check; `KillSignal=SIGINT` on the timers' services.

Owners agreed (11-01): `fab logins check` is agents/creds' (`*:5/30`, TimeoutStartSec 1800,
stdout to null, stderr to the journal, no extra lock); `fab report daily` is agents/loop's code
(written here; daily at 00:33 UTC over the listed, unretired plans); `fab serve` and `fab issues`
are agents/status'. Deployment on hel8 is ops', after landing, not this plan's.

Split, so no two tasks edit `fab/units.py` at once: task 1, the installer and its texts plus
`fab serve --install` (with the watch) and `fab issues --install`; task 2, needing task 1, `fab
logins check --install` and `fab report daily --install` (with no plan dir).

Tests (fab.md 4: `FakeRunner`, temporary HOME and FAB_HOME): each unit's text pinned byte for
byte by its pure function; without the role, no systemctl call but the disable of a present file;
a first install over transient units in argv order (`show Transient`, `stop`, `reset-failed`, the
writes, `daemon-reload`, `enable --now`); an active transient timer's service refuses with exit 1
and nothing stopped or written; a rerun with unchanged text stops and restarts nothing; changed
`fab-status` text restarts it, a changed timer service's text does not; a pause is left disabled;
linger other than `yes`, or a failing `loginctl`, warns and exits 0; the serve watch returns 75 on
an injected HEAD change and keeps serving on an unreadable one; `report daily` with no plan dir
skips a plan without `plan.toml` and a retired one; each `--install`'s usage errors.

The user's rule: dogfood. Built by fab's loop (the tick, `bin/fab land`), not by hand. Landing
`queue` (the cut is started with `--set 'landing="queue"'`).
