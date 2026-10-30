"""Backoff and preview regressions, using disposable HOME and local origins."""

import datetime as dt
import fcntl
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import test_fleet_sync as fixture


class FleetSync2Test(fixture.FleetTest):
    def fail_timer(self):
        self.sync()
        fixture.put(self.home / "src/fabrig/agents/untracked", "dirty\n")
        self.sync("--timer", expected=1)
        state = self.state()
        self.assertEqual(state["consecutive_failures"], 1)
        self.assertTrue(state["last_failure"])
        return state

    def preview_run(self, directory=None, expected=0):
        directory = directory or self.directory / "preview"
        result = self.process("python3", "-I", "-B", self.source / "tools/fleet-sync",
                              "--host", "hel8", "--preview", directory, expected=expected)
        return directory / "home", result

    def test_failed_timer_waits_quietly_without_advancing_state(self):
        first = self.fail_timer()
        before_calls = self.calls()
        result = self.sync("--timer")
        self.assertIsNone(result)
        self.assertEqual(self.state(), first)
        self.assertEqual(self.calls(), before_calls)
        self.assertIn("backoff until", (self.home / ".local/state/fleet-sync/run.log").read_text().splitlines()[-1])

    def test_backoff_boundaries_and_cap(self):
        with patch.dict(os.environ, self.env):
            module, runner = self.runner()
            instant = dt.datetime.now(dt.UTC)
            for failures, minutes in ((1, 1), (2, 2), (3, 4), (6, 32), (7, 60), (1000000, 60)):
                with self.subTest(failures=failures):
                    runner.state.update(consecutive_failures=failures, last_failure=instant.isoformat())
                    self.assertEqual(dt.datetime.fromisoformat(runner.backoff_until()), instant + dt.timedelta(minutes=minutes))
                    self.assertIn(f"({failures} failures)", runner.backoff_reason())
            runner.state.update(consecutive_failures=1,
                                last_failure=(instant - dt.timedelta(minutes=1, seconds=1)).isoformat())
            self.assertIsNone(runner.backoff_reason())

    def test_expired_wait_increments_then_manual_success_resets(self):
        state = self.fail_timer()
        state["last_failure"] = (dt.datetime.now(dt.UTC) - dt.timedelta(minutes=2)).isoformat()
        fixture.put(self.home / ".local/state/fleet-sync/state.json", json.dumps(state))
        self.sync("--timer", expected=1)
        self.assertEqual(self.state()["consecutive_failures"], 2)
        self.assertNotEqual(self.state()["last_failure"], state["last_failure"])
        self.sync(expected=1)  # Manual failure runs immediately and preserves the timer counter.
        self.assertEqual(self.state()["consecutive_failures"], 2)
        (self.home / "src/fabrig/agents/untracked").unlink()
        self.sync()
        self.assertEqual(self.state()["consecutive_failures"], 0)
        self.assertIsNone(self.state()["last_failure"])
        self.assertIsNone(self.state()["backoff_until"])

    def test_retry_is_consumed_and_overrides_wait(self):
        self.fail_timer()
        retry = self.home / ".config/fleet-sync/retry"
        fixture.put(retry, "")
        self.sync("--timer", expected=1)
        self.assertFalse(retry.exists())
        self.assertEqual(self.state()["consecutive_failures"], 2)
        self.assertIsNone(self.sync("--timer"))

    def test_new_main_bypasses_wait_and_handoff_counts_once(self):
        self.fail_timer()
        (self.home / "src/fabrig/agents/untracked").unlink()
        fixture.put(self.source / "fleet/env", (self.source / "fleet/env").read_text() + "NEW_MAIN=yes\n")
        sha = self.publish()
        self.sync("--timer", script=self.current() / "tools/fleet-sync")
        self.assertEqual(self.state()["agents_sha"], sha)
        self.assertEqual(self.state()["consecutive_failures"], 0)
        # Fail after promotion and exec, ensuring the new runner increments only once.
        fixture.put(self.source / "fleet/env", (self.source / "fleet/env").read_text() + "NEXT_MAIN=yes\n")
        self.publish()
        self.sync("--timer", env={**self.env, "FAKE_NO_BUS": "1"}, expected=1)
        self.assertEqual(self.state()["consecutive_failures"], 1)

    def test_check_and_status_show_wait_without_consuming_retry(self):
        self.fail_timer()
        fixture.put(self.home / ".config/fleet-sync/retry", "operator\n")
        before = self.snapshot(exclude_mirror=True)
        state = self.sync("--check", expected=1)
        reason = next(i["reason"] for i in state["items"] if i["item"] == "backoff")
        self.assertRegex(reason, r"backoff until \d\d:\d\dZ \(1 failures\)")
        self.assertEqual(self.snapshot(exclude_mirror=True), before)
        result = self.process("python3", "-I", "-B", self.source / "tools/fleet-sync", "status", "--host", "hel8", expected=1)
        self.assertIn(reason, result.stdout)
        self.assertTrue((self.home / ".config/fleet-sync/retry").exists())

    def test_hold_and_busy_timer_leave_retry_untouched(self):
        self.fail_timer()
        fixture.put(self.home / ".config/fleet-sync/retry", "")
        fixture.put(self.home / ".config/fleet-sync/hold", "maintenance\n")
        before = self.snapshot()
        self.sync("--timer")
        self.assertEqual(before, self.snapshot())
        (self.home / ".config/fleet-sync/hold").unlink()
        with (self.home / ".local/state/fleet-sync/lock").open("rb") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            before = self.snapshot()
            self.assertIsNone(self.sync("--timer"))
            self.assertEqual(before, self.snapshot())

    def test_unreachable_origin_keeps_backoff(self):
        before = self.fail_timer()
        fixture.put(self.bin / "git", '#!/bin/bash\nif [ "$1" = ls-remote ]; then exit 1; fi\nexec /usr/bin/git "$@"\n', True)
        self.assertIsNone(self.sync("--timer"))
        self.assertEqual(before, self.state())
        last = (self.home / ".local/state/fleet-sync/run.log").read_text().splitlines()[-1]
        self.assertIn("backoff until", last)
        self.assertIn("origin/main probe failed", last)

    def test_legacy_handoff_initializes_counter_and_records_failure(self):
        with patch.dict(os.environ, self.env):
            module, runner = self.runner()
            runner.args.timer = True
            legacy = {key: value for key, value in runner.state.items()
                      if key not in ("consecutive_failures", "last_failure")}
            legacy["items"] = [{"item": "units", "result": "failed", "reason": "fixture failure"}]
            resumed = module.Runner(runner.args, runner.d, "hel8", legacy)
            self.assertEqual(resumed.finish(), 1)
        self.assertEqual(self.state()["consecutive_failures"], 1)
        self.assertTrue(self.state()["last_failure"])

    def test_retry_refuses_symlink_and_fifo_without_removing_them(self):
        self.fail_timer()
        retry = self.home / ".config/fleet-sync/retry"
        retry.parent.mkdir(exist_ok=True)
        retry.symlink_to(self.source / "fleet/env")
        self.sync("--timer", expected=1)
        self.assertTrue(retry.is_symlink())
        retry.unlink()
        os.mkfifo(retry)
        self.sync("--timer", expected=1)
        self.assertTrue(retry.exists())

    def test_records_units_render_by_role_without_activation(self):
        expected = {
            "hel8": {"fleet-sync", "record-collect-session", "pipeline-watch", "status-page", "mirror"},
            "hetzner6": {"fleet-sync", "record-collect-builder"},
            "hetzner8": {"fleet-sync", "record-collect-gate"},
        }
        # Long-running services, started once by fleet-sync: a preview shows their first start pending.
        services = {"hetzner6": {"qa-watch.service"}}
        before = self.snapshot()
        for host, names in expected.items():
            with self.subTest(host=host):
                directory = self.directory / ("preview-" + host)
                self.process("python3", "-I", "-B", self.source / "tools/fleet-sync",
                             "--host", host, "--preview", directory,
                             expected=1 if host in services else 0)
                units = directory / "home/.config/systemd/user"
                self.assertEqual({p.name for p in units.iterdir()},
                                 {name + suffix for name in names for suffix in (".service", ".timer")}
                                 | services.get(host, set()))
                if "mirror" in names:
                    self.assertIn("tools/fleet-scale/mirror", (units / "mirror.service").read_text())
                    self.assertIn("OnUnitActiveSec=60s", (units / "mirror.timer").read_text())
                for name in names - {"fleet-sync", "mirror"}:
                    service = (units / (name + ".service")).read_text()
                    timer = (units / (name + ".timer")).read_text()
                    self.assertIn("Type=oneshot\nWorkingDirectory=%h\n", service)
                    self.assertIn('ExecStart=/bin/bash -lc \'exec "$$HOME/src/fabrig/current/tools/records/', service)
                    self.assertIn("Persistent=true", timer)
                    self.assertIn("OnBootSec=", timer)
                    self.assertIn("AccuracySec=", timer)
                    if name != "status-page":
                        self.assertIn("RandomizedDelaySec=60\n", timer)
                    self.assertIn("WantedBy=timers.target", timer)
        self.assertEqual(before, self.snapshot())
        self.assertFalse((self.home / "systemctl.log").exists())

    def test_status_page_takes_over_legacy_units_once(self):
        units = self.home / ".config/systemd/user"
        legacy = "# legacy status page\n"
        for suffix in ("service", "timer"):
            fixture.put(units / ("status-page." + suffix), legacy)
        self.sync()
        for suffix in ("service", "timer"):
            name = "status-page." + suffix
            self.assertEqual((units / name).read_text(), (self.source / "fleet/units" / name).read_text())
            self.assertEqual((units / (name + ".pre-fleet-sync")).read_text(), legacy)
        self.assertIn("TimeoutStartSec=8min", (units / "status-page.service").read_text())
        self.assertIn("OnCalendar=*:0/10", (units / "status-page.timer").read_text())
        self.assertIn(["--user", "enable", "--now", "--no-reload", "status-page.timer"], self.calls())
        before = self.calls()
        self.sync()
        self.assertEqual(self.calls()[len(before):], [["--user", "show", "-p", "NeedDaemonReload", *sorted(self.state()["managed_units"])]] + [["--user", "is-active", "--quiet", name]
                         for name in sorted(("fleet-sync.timer", "record-collect-session.timer", "pipeline-watch.timer", "status-page.timer", "mirror.timer"))])

    def test_preview_first_run_renders_real_home_without_deployment(self):
        fixture.put(self.home / ".bashrc", "# personal\n")
        fixture.put(self.home / ".codex/config.toml", '# personal\n[projects."/tmp/example"]\ntrust_level = "trusted"\n')
        before = self.snapshot()
        copied, result = self.preview_run()
        self.assertEqual(before, self.snapshot())
        self.assertIn("--- " + str(self.home / ".bashrc"), result.stdout)
        self.assertIn("+++ " + str(copied / ".bashrc"), result.stdout)
        self.assertIn("New files:", result.stdout)
        self.assertIn(".local/bin/fleet-sync", result.stdout)
        self.assertIn("fabrig: preview", result.stdout)
        self.assertIn(".bashrc.pre-fleet-sync", result.stdout)
        self.assertEqual((copied / ".bashrc.pre-fleet-sync").read_text(), "# personal\n")
        self.assertIn("# personal", (copied / ".bashrc").read_text())
        self.assertIn('[projects."/tmp/example"]', (copied / ".codex/config.toml").read_text())
        env = (copied / ".config/environment.d/90-fabrig.conf").read_text()
        self.assertIn(str(self.home) + "/.local/bin", env)
        self.assertNotIn(str(copied), env)
        self.assertIn(str(self.home), (copied / ".cargo/config.toml").read_text())
        self.assertEqual(os.readlink(copied / ".local/bin/fleet-sync"), str(self.home / "src/fabrig/current/tools/fleet-sync"))
        self.assertFalse((copied / "src/fabrig/releases").exists())
        self.assertFalse((copied / "src/rust/tmp/post/machines").exists())

    def test_preview_existing_home_uses_checkout_and_real_conflicts(self):
        self.sync()
        fixture.put(self.source / "fleet/env", (self.source / "fleet/env").read_text() + "FROM_CHECKOUT=yes\n")
        fixture.put(self.home / ".config/plan/environment.sh", "export DISABLE_AUTOUPDATER=0\n")
        fixture.put(self.bin / "claude", '#!/bin/bash\nprintf "wrong-version-from-real-environment\\n"\n', True)
        fixture.put(self.home / "src/rust/tmp/post/machines", "operator routing\n")
        before = self.snapshot()
        copied, result = self.preview_run()
        self.assertEqual(before, self.snapshot())
        self.assertIn("FROM_CHECKOUT=yes", (copied / ".config/fabrig/env.sh").read_text())
        self.assertIn("conflict:.config/plan/environment.sh", result.stdout)
        self.assertNotIn("wrong-version-from-real-environment", result.stdout)
        self.assertIn("versions: not probed in preview; see --check", result.stdout)
        self.assertEqual((copied / "src/rust/tmp/post/machines").read_text(), "operator routing\n")
        self.assertEqual((copied / ".profile").read_bytes(), (self.home / ".profile").read_bytes())

    def test_preview_keeps_existing_backups_and_reports_link_conflicts(self):
        fixture.put(self.home / ".bashrc", "# personal\n")
        fixture.put(self.home / ".bashrc.pre-fleet-sync", "# older backup\n")
        fixture.put(self.home / ".local/bin/fleet-sync", "operator tool\n")
        before = self.snapshot()
        copied, result = self.preview_run(expected=1)
        self.assertEqual(before, self.snapshot())
        self.assertEqual((copied / ".bashrc.pre-fleet-sync").read_text(), "# older backup\n")
        self.assertEqual((copied / ".local/bin/fleet-sync").read_text(), "operator tool\n")
        self.assertIn("failed  link:fleet-sync", result.stdout)
        self.assertNotIn(".bashrc.pre-fleet-sync", result.stdout.split("New files:")[1])

    def test_preview_refuses_symlink_fifo_and_unsafe_destination(self):
        for kind in ("leaf", "parent", "fifo"):
            with self.subTest(kind=kind):
                path = self.home / ".cargo/config.toml"
                path.parent.mkdir(exist_ok=True)
                if kind == "leaf":
                    path.symlink_to(self.source / "fleet/cargo/config.toml")
                elif kind == "parent":
                    path.parent.rmdir()
                    path.parent.symlink_to(self.source / "fleet/cargo", target_is_directory=True)
                else:
                    os.mkfifo(path)
                # Avoid snapshot() following the fixture FIFO.
                if kind != "fifo":
                    before = self.snapshot()
                self.preview_run(self.directory / ("preview-" + kind), expected=1)
                if kind != "fifo":
                    self.assertEqual(before, self.snapshot())
                else:
                    self.assertTrue(path.exists())
                if kind == "parent":
                    path.parent.unlink()
                else:
                    path.unlink()
        output = self.directory / "elsewhere"
        output.mkdir()
        alias = self.directory / "alias"
        alias.symlink_to(output, target_is_directory=True)
        self.preview_run(alias / "preview", expected=1)
        self.assertEqual(list(output.iterdir()), [])
        missing = self.directory / "missing" / "preview"
        self.preview_run(missing, expected=1)
        self.assertFalse(missing.parent.exists())

    def test_preview_rejects_nonempty_and_incompatible_options(self):
        directory = self.directory / "preview"
        directory.mkdir(mode=0o700)
        fixture.put(directory / "keep", "untouched\n")
        self.preview_run(directory, expected=1)
        self.assertEqual((directory / "keep").read_text(), "untouched\n")
        for option in ("--check", "--timer", "--json", "status"):
            self.process("python3", "-I", "-B", self.source / "tools/fleet-sync", "--host", "hel8",
                         "--preview", directory, option, expected=2)


def load_tests(loader, tests, pattern):
    # The fixture supplies helpers; run only this module's new regressions here.
    return unittest.TestSuite(FleetSync2Test(name) for name in FleetSync2Test.__dict__ if name.startswith("test_"))
