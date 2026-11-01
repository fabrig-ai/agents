# hel8-units: the cut's decisions

What the request and `docs/design/machines.md` 4 left to the cut, each
settled with its reason. The specs bind them.

1. **One direct part, two tasks, as the request splits them:**
   `status-issues` (the installer, its texts, `fab serve --install` with
   the watch, `fab issues --install`), then `logins-report` (`fab logins
   check --install`, `fab report daily --install`, daily with no plan dir),
   which needs it: both change `fab/units.py` and
   `fab/tests/test_units.py`. One concept (the dispatcher's units) and one
   slice: the story ends when all four install. Not walked: deployment is
   ops', after landing.
2. **The installer's surface, binding:** `install_units(files, *, primary,
   restartable, role="dispatcher", sh=run, directory=None, known=None) ->
   tuple[list[str], list[str]]` as the design names it, returning the
   stdout lines and the stderr warnings (the linger line without its `fab
   <command>: ` prefix, since the design's signature has no command). One
   more public function, `cli_install(command, files, *, primary,
   restartable, sh=run, directory=None, known=None) -> int`, prints those
   (warnings prefixed `fab <command>: `) and maps OSError, ValueError and
   `fab.sh.Failed` to `fab <command>: <error on one line>`, exit 1, so the
   four mains share it and the clones gate holds.
3. **The texts:** three pure builders in `status-issues`,
   `status_service(*, home=None, checkout=None) -> str`,
   `timer_service(what, command, timeout, *, quiet=False, home=None,
   checkout=None) -> str` (`quiet` adds the two output lines) and
   `timer(what, when, calendar, service, *, persistent=False) -> str`, and
   one pure `<x>_units(*, home=None, checkout=None) -> dict[str, str]` per
   command, timer first then service (`fab-status.service` alone for
   serve). Arguments are checked for newline, `%`, `$`, `"` and backslash
   as `units.text` checks them, through one shared private check.
4. **Restarts:** `fab-status.service` restarts when `restartable` and its
   file had other text; a `.timer` whose text changed restarts (the
   design's step 5); a timer's service never. Both are decided from the
   texts read before the writes.
5. **The serve watch is a new public function,** so `fab.serve.main(argv)`
   keeps its signature and both tasks are kind `feature`:
   `serve(server, head, *, interval=60.0) -> int` runs
   `server.serve_forever()` with a daemon thread calling `head()` (a
   `Callable[[], str | None]`) every interval, returning 75 after a change
   and 0 otherwise; `head_of(checkout, *, sh=run) -> str | None` is the
   reader (`git -C <checkout> rev-parse HEAD`, check=False; None when it
   fails or prints nothing). An unreadable first read is no change: the
   first readable hash becomes the baseline.
6. **`fab report daily` skips only when no plan dir is given:** over
   `fab.channel.plan_dirs()`, a directory without `plan.toml` or a plan
   with `retired = true` prints `<dir> skipped` and is not a failure; plan
   dirs given are reported exactly, as today.
7. **Status files are the retire call's,** as the plans beside this one
   do; `smith-live/kind` also edits `docs/design/machines.status.md`.
8. **No user questions.** The request settles what is built and how it
   lands; deployment, the one machine action, is ops' after landing.

## Critical path

`status-issues` (60) -> `logins-report` (45): 105 implementer-minutes,
about 1.75 hours. The request orders them (both own `fab/units.py`), so it
is the longest task plus its successor; nothing else runs beside them.

| Task | Needs | Minutes | Ends near |
|---|---|---|---|
| status-issues | | 60 | 60 |
| logins-report | status-issues | 45 | 105 |
