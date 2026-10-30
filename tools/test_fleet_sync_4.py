"""Start-once service regressions with disposable HOME and fake systemctl."""

import json
import os
import shutil
import unittest
from unittest.mock import patch

import test_fleet_sync as fixture


NAME = "owner-worker.service"
UNIT = """# fleet-sync: start-once
[Unit]
Description=Owned worker
[Service]
Type=simple
ExecStart=/bin/true
[Install]
WantedBy=default.target
"""
MUTATIONS = {"enable", "disable", "daemon-reload", "start", "stop", "restart", "reload"}


class StartOnceTest(fixture.FleetFixture):
    def setUp(self):
        super().setUp()
        self.declaration = self.source / "fleet/units" / NAME
        self.unit = self.home / ".config/systemd/user" / NAME
        self.link = self.unit.parent / "default.target.wants" / NAME
        self.journal = self.home / ".local/state/fleet-sync/units.json"
        fixture.put(self.declaration, UNIT)
        self.roles = self.source / "fleet/units/roles.toml"
        fixture.put(self.roles, self.roles.read_text() + f'"{NAME}" = ["session"]\n')
        self.publish()

    def reset_calls(self):
        fixture.put(self.home / "systemctl.log", "")

    def mutations(self):
        return [call for call in self.calls() if MUTATIONS & set(call)]

    def service_calls(self):
        return [call for call in self.calls() if call[-1] == NAME]

    def assert_pending(self, state):
        self.assertTrue(any(i["item"] == NAME and i["result"] == "warn"
                            and "restart pending" in i["reason"] for i in state["items"]))

    def test_first_write_starts_after_reload_once_and_unchanged_does_nothing(self):
        state = self.sync()
        enable = ["--user", "enable", "--now", "--no-reload", NAME]
        self.assertEqual(self.calls().count(enable), 1)
        self.assertLess(self.calls().index(["--user", "daemon-reload"]), self.calls().index(enable))
        self.assertTrue(self.link.is_symlink())
        self.assertTrue((self.home / (NAME + ".active")).exists())
        self.assertFalse(any(i["item"] == NAME and "restart pending" in i["reason"] for i in state["items"]))
        self.assertIn(NAME, json.loads(self.journal.read_text())["start_once_started"])
        self.reset_calls()
        self.sync()
        self.assertEqual(self.mutations(), [])
        self.assertIn(["--user", "is-active", "--quiet", NAME], self.calls())

    def test_takeover_of_identical_unowned_file_starts_once(self):
        fixture.put(self.unit, UNIT)
        self.sync()
        self.assertEqual(self.calls().count(["--user", "enable", "--now", "--no-reload", NAME]), 1)

    def test_absent_previously_owned_file_gets_first_start(self):
        self.sync()
        self.unit.unlink()
        self.reset_calls()
        self.sync()
        self.assertEqual(self.calls().count(["--user", "enable", "--now", "--no-reload", NAME]), 1)

    def test_changed_content_warns_without_restart(self):
        self.sync()
        fixture.put(self.declaration, UNIT.replace("Owned worker", "Updated worker"))
        self.publish()
        self.reset_calls()
        self.assert_pending(self.sync())
        self.assertEqual(self.unit.read_text(), self.declaration.read_text())
        self.assertEqual(self.mutations(), [["--user", "daemon-reload"]])

    def test_changed_oneshot_also_warns_without_restart(self):
        fixture.put(self.declaration, UNIT.replace("Type=simple", "Type=oneshot"))
        self.publish()
        self.sync()
        fixture.put(self.declaration, self.declaration.read_text().replace("Owned worker", "Updated worker"))
        self.publish()
        self.reset_calls()
        self.assert_pending(self.sync())
        self.assertEqual(self.mutations(), [["--user", "daemon-reload"]])

    def test_inactive_and_failed_warn_without_start(self):
        self.sync()
        for status in ("inactive", "failed"):
            with self.subTest(status=status):
                self.reset_calls()
                state = self.sync(env={**self.env, "FAKE_SERVICE_STATE": status})
                self.assertIn({"item": NAME, "result": "warn",
                               "reason": "start-once service not active; its owner restarts it"}, state["items"])
                self.assertEqual(self.mutations(), [])

    def test_missing_and_wrong_enablement_repaired_without_start(self):
        self.sync()
        for target in (None, "/previous/owner-worker.service"):
            with self.subTest(target=target):
                self.link.unlink()
                if target:
                    self.link.symlink_to(target)
                self.reset_calls()
                state = self.sync(env={**self.env, "FAKE_SERVICE_STATE": "inactive"})
                self.assertEqual(self.mutations(), [["--user", "enable", "--no-reload", NAME]])
                self.assertEqual(self.link.resolve(), self.unit)
                self.assertTrue(any(i["item"] == NAME and i["result"] == "warn" for i in state["items"]))

    def test_install_targets_and_aliases_are_repaired_without_start(self):
        fixture.put(self.declaration, UNIT.replace("WantedBy=default.target",
                    "WantedBy=custom.target other.target\nRequiredBy=required.target\nAlias=worker-alias.service"))
        self.publish()
        self.sync()
        links = [self.unit.parent / target / NAME for target in
                 ("custom.target.wants", "other.target.wants", "required.target.requires")]
        links.append(self.unit.parent / "worker-alias.service")
        self.assertTrue(all(link.resolve() == self.unit for link in links))
        links[-1].unlink()
        self.reset_calls()
        self.sync(env={**self.env, "FAKE_SERVICE_STATE": "inactive"})
        self.assertEqual(self.mutations(), [["--user", "enable", "--no-reload", NAME]])
        self.assertTrue(all(link.resolve() == self.unit for link in links))

    def test_relative_enablement_link_is_accepted(self):
        self.sync()
        self.link.unlink()
        self.link.symlink_to("../" + NAME)
        self.reset_calls()
        self.sync()
        self.assertEqual(self.mutations(), [])

    def test_enablement_regular_file_is_refused(self):
        self.sync()
        self.link.unlink()
        fixture.put(self.link, "owner data\n")
        self.reset_calls()
        self.sync(expected=1)
        self.assertEqual(self.link.read_text(), "owner data\n")
        self.assertEqual(self.mutations(), [])

    def test_interrupted_first_start_recovers_from_ownership_journal(self):
        with patch.dict(os.environ, self.env, clear=True):
            _, runner = self.runner()
            command = runner.cmd
            def fail_start(*args, **kwargs):
                if "enable" in args and args[-1] == NAME:
                    raise OSError("interrupted before first enable")
                return command(*args, **kwargs)
            with patch.object(runner, "cmd", side_effect=fail_start), self.assertRaises(OSError):
                runner.units()
        self.assertTrue(self.unit.exists())
        self.assertIn(NAME, json.loads(self.journal.read_text())["units"])
        self.assertFalse(self.link.exists())
        self.assertFalse((self.home / ".local/state/fleet-sync/state.json").exists())
        self.reset_calls()
        self.sync()
        self.assertEqual(self.calls().count(["--user", "enable", "--now", "--no-reload", NAME]), 1)

    def test_interruption_after_enable_does_not_start_inactive_service_again(self):
        with patch.dict(os.environ, self.env, clear=True):
            _, runner = self.runner()
            save = runner.save_unit_intent
            def fail_after_enable():
                if NAME in runner.start_once_started:
                    raise OSError("interrupted after enable before completion journal")
                save()
            with patch.object(runner, "save_unit_intent", side_effect=fail_after_enable), self.assertRaises(OSError):
                runner.units()
        self.assertTrue(self.link.is_symlink())
        self.reset_calls()
        self.sync(env={**self.env, "FAKE_SERVICE_STATE": "inactive"})
        self.assertEqual(self.mutations(), [])

    def test_role_removal_disables_without_stopping(self):
        self.sync()
        fixture.put(self.roles, self.roles.read_text().replace(f'"{NAME}" = ["session"]', f'"{NAME}" = ["unused"]'))
        self.publish()
        self.reset_calls()
        state = self.sync()
        self.assertIn(["--user", "disable", "--no-reload", NAME], self.calls())
        self.assertFalse(any("--now" in call or "stop" in call or "restart" in call for call in self.calls()))
        self.assertFalse(self.unit.exists())
        self.assertFalse(self.link.is_symlink())
        self.assertTrue((self.home / (NAME + ".active")).exists())
        self.assertTrue(any(i["item"] == NAME and "stopped by its owner" in i["reason"] for i in state["items"]))
        self.assertNotIn(NAME, json.loads(self.journal.read_text()).get("start_once_started", []))

    def test_marker_validation_self_check_changes_nothing(self):
        for name, text in ((NAME, UNIT.partition("[Install]")[0]),
                           ("invalid.timer", "# fleet-sync: start-once\n[Unit]\n[Timer]\nOnCalendar=minutely\n[Install]\nWantedBy=timers.target\n")):
            with self.subTest(name=name):
                fixture.put(self.declaration, UNIT)
                if name != NAME:
                    fixture.put(self.roles, self.roles.read_text() + f'"{name}" = ["session"]\n')
                fixture.put(self.source / "fleet/units" / name, text)
                before = self.snapshot()
                result = self.process("python3", "-I", "-B", self.source / "tools/fleet-sync", "--self-check", "--host", "hel8", expected=2)
                self.assertIn("start-once requires a service with [Install]", result.stderr)
                self.assertEqual(before, self.snapshot())

    def test_only_exact_first_line_opts_in(self):
        for text in ("# ordinary comment\n" + UNIT, UNIT.replace("start-once\n", "start-once \n", 1)):
            with self.subTest(text=text):
                fixture.put(self.declaration, text)
                with patch.dict(os.environ, self.env, clear=True):
                    _, runner = self.runner()
                    self.assertNotIn(NAME, runner.d.start_once)

    def test_check_and_preview_report_first_start_without_systemctl_writes(self):
        before = self.snapshot()
        state = self.sync("--check", expected=1)
        self.assertIn({"item": NAME, "result": "drift", "reason": "start-once service first start pending"}, state["items"])
        result = self.process("python3", "-I", "-B", self.source / "tools/fleet-sync", "--host", "hel8", "--preview", self.directory / "preview", expected=1)
        self.assertIn("start-once service first start pending", result.stdout)
        self.assertEqual(before, self.snapshot())

    def test_check_and_preview_report_content_activity_and_enablement_drift(self):
        self.sync()
        fixture.put(self.declaration, UNIT.replace("Owned worker", "Updated worker"))
        self.publish()
        self.link.unlink()
        self.reset_calls()
        before = self.snapshot(exclude_mirror=True)
        env = {**self.env, "FAKE_SERVICE_STATE": "failed"}
        self.assert_pending(self.sync("--check", expected=1, env=env))
        result = self.process("python3", "-I", "-B", self.source / "tools/fleet-sync", "--host", "hel8", "--preview", self.directory / "preview", expected=1, env=env)
        for reason in ("restart pending", "start-once service not active; its owner restarts it", "service enablement symlink"):
            self.assertIn(reason, result.stdout)
        self.assertEqual(self.mutations(), [])
        # Read-only probes append only to the fake's command log.
        after = self.snapshot(exclude_mirror=True)
        before.pop("systemctl.log")
        after.pop("systemctl.log")
        self.assertEqual(before, after)

    def test_1148127_runner_accepts_marker_and_new_journal_as_ordinary_service(self):
        self.sync()
        self.unit.unlink()
        old_script = self.process("git", "-C", fixture.ROOT, "show", "1148127:tools/fleet-sync").stdout
        old_script = old_script.replace('SYSTEM_TOOL_DIRS = (Path("/usr/bin"), Path("/bin"))',
                                        f'SYSTEM_TOOL_DIRS = tuple(map(Path, {json.dumps([str(p) for p in self.system_bins])}))')
        self.assertGreater(self.prepare_integer_machine_env(), 0)
        fixture.put(self.source / "tools/fleet-sync", old_script, True)
        # Bootstrap assets need a separate parser rollout. Record that limit,
        # then isolate marker/journal compatibility to legacy-readable inputs.
        refused = self.process("python3", "-I", "-B", self.source / "tools/fleet-sync",
                               "--host", "hel8", "--self-check", expected=2)
        self.assertIn("unknown fleet declaration: bootstrap/", refused.stderr)
        for name in ("bootstrap", "kache", "seeds"):
            shutil.rmtree(self.source / "fleet" / name)
        (self.source / "fleet/units/kache.service").unlink()
        fixture.put(self.roles, self.roles.read_text().replace('"kache.service" = ["*"]\n', ""))
        self.process("python3", "-I", "-B", self.source / "tools/fleet-sync", "--host", "hel8", "--self-check")
        self.reset_calls()
        with patch.dict(os.environ, self.env, clear=True):
            _, runner = self.runner()
            runner.units()
        self.assertEqual(self.unit.read_text(), UNIT)
        self.assert_pending(runner.state)
        self.assertEqual(self.service_calls(), [])
        self.assertEqual(self.mutations(), [["--user", "daemon-reload"]])


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(StartOnceTest(name) for name in StartOnceTest.__dict__ if name.startswith("test_"))


if __name__ == "__main__":
    unittest.main()
