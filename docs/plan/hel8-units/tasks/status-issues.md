+++
id = "status-issues"
part = "dispatcher-units"
kind = "feature"
needs = []
files = ["fab/units.py", "fab/serve.py", "fab/forge.py", "fab/tests/test_units.py", "fab/tests/test_serve.py", "fab/tests/test_forge.py"]
effort = "high"
minutes = 60
+++
# The dispatcher's installer, `fab serve --install` and `fab issues --install`

Read first: `docs/plan/hel8-units/notes/common.md`,
`docs/plan/hel8-units/notes/decisions.md` (2-5), then
`docs/design/machines.md` 4 whole.

The request's task 1.

## What to build

- **`fab/units.py`** (94 lines; `Service`, `text`, `install` unchanged):
  the text builders and `status_units` / `issues_units` (decisions 3),
  `install_units` and `cli_install` (decision 2), doing the design's
  install steps 1-6 in order. The role through `fab.hosts.load()` and
  `fab.hosts.this`; the directory defaults as `install` does (factor the
  default into one private helper both use). The linger check reads the
  uid and user from `os` (`os.getuid()`, `getpass.getuser()` or
  `pwd`), never from systemd.
- **`fab/serve.py`, `main`** (~579): `--install`, alone (with `--port` or
  `--bind`: usage error, exit 2), calls `units.cli_install("serve",
  units.status_units(), primary="fab-status.service", restartable=True)`.
  Otherwise `head_of` and `serve` (decision 5), the checkout
  `Path(__file__).resolve().parent.parent`; `main` returns `serve`'s code.
  KeyboardInterrupt still returns 0.
- **`fab/forge.py`, `main`** (~245): `command` becomes optional
  (`nargs="?"`); `--install` with no command calls `units.cli_install(
  "issues", units.issues_units(), primary="fab-issues.timer",
  restartable=False)`; `--install` with `sync`, or neither: usage error,
  exit 2. Its docstring loses "deployment on hel8 is by hand".

## Acceptance

The request's tests that are this task's, in `fab/tests/test_units.py`
unless named:

- `fab-status.service`, `fab-issues.timer` and `fab-issues.service` texts
  pinned byte for byte by their pure functions; a `%` in FAB_HOME is a
  ValueError.
- Without the role: no unit file, no systemctl call; a file present,
  `disable` then `stop --no-block` of the primary only.
- A first install over transient units, argv in order: `show
  --property=Transient,ActiveState --value` for each unit, `stop` and
  `reset-failed` for each transient one (timer before service), the
  writes, `daemon-reload`, `enable --now <primary>`. A non-transient unit
  is never stopped.
- An active transient timer's service refuses: exit 1, the design's
  message, nothing stopped or written.
- A rerun with unchanged text stops and restarts nothing; changed
  `fab-status` text restarts it; a changed timer's text restarts the timer;
  a changed timer service's text restarts nothing.
- A pause (file present, `is-enabled` prints `disabled`): files written,
  `daemon-reload`, nothing enabled or restarted, `<primary> left disabled`.
- Linger other than `yes`, or a failing `loginctl`: the warning on stderr,
  exit 0.
- `fab/tests/test_serve.py`: `serve` returns 75 on an injected head
  change within a short interval, keeps serving (until a test shutdown,
  returning 0) on an unreadable one; `--install` with `--port`: exit 2.
- `fab/tests/test_forge.py`: `fab issues --install` installs (FakeRunner);
  `--install sync` and no arguments: exit 2.
- `bin/fab test` green.

## Pre-approved defaults

- `serve`'s test binds port 0 on 127.0.0.1 and an interval of about 0.05 s.
- A `known=` and `sh=` reach `cli_install` from tests by patching
  `fab.units`' defaults or by calling `cli_install` directly with them;
  the mains need no new parameters.

## Report

The public surface as built (signatures), the argv of a first install, and
the tests added.
