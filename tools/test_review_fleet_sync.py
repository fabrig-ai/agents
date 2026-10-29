"""Regressions for the seven independent review findings."""

import fcntl
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

import test_fleet_sync as fixture


class ReviewTest(fixture.FleetTest):
    def setUp(self):
        super().setUp()
        fixture.put(self.bin / "systemd-analyze", '''#!/usr/bin/env python3
import json, pathlib, sys
with (pathlib.Path.home() / "verify.log").open("a") as stream:
    stream.write(json.dumps(sys.argv[1:]) + "\\n")
sys.exit(int(any("BROKEN" in pathlib.Path(p).read_text() for p in sys.argv[3:])))
''', True)

    def test_bad_service_cannot_be_promoted(self):
        self.sync()
        previous = self.current()
        service = self.source / "fleet/units/fleet-sync.service"
        fixture.put(service, service.read_text().replace("/bin/bash -lc", "/definitely-missing/fleet-sync -lc"))
        self.publish()
        self.sync(script=previous / "tools/fleet-sync", expected=1)
        self.assertEqual(self.current(), previous)

    def test_bad_smoke_json_cannot_be_promoted(self):
        self.sync()
        previous = self.current()
        script = self.source / "tools/fleet-sync"
        fixture.put(script, script.read_text().replace("    if args.self_check:\n", '    if args.check:\n        print("not state JSON")\n        return 0\n    if args.self_check:\n'), True)
        self.publish()
        self.sync(script=previous / "tools/fleet-sync", expected=1)
        self.assertEqual(self.current(), previous)

    def test_fixed_launcher_rejects_hidden_or_misplaced_assignments(self):
        service = self.source / "fleet/units/fleet-sync.service"
        original = service.read_text()
        cases = [original + "  ExecStart = /definitely-missing/fleet-sync\n",
                 original.replace("Type=oneshot\n", "Type=oneshot\n[Unit]\n")]
        for content in cases:
            with self.subTest(content=content):
                fixture.put(service, content)
                self.process("python3", "-I", "-B", self.source / "tools/fleet-sync", "--self-check", "--host", "hel8", expected=2)

    def test_verify_every_host_unit_and_skip_missing_verifier(self):
        self.sync()
        previous = self.current()
        service = self.source / "fleet/units/extra.service"
        fixture.put(service, "[Unit]\nDescription=BROKEN\n[Service]\nExecStart=/bin/true\n")
        roles = self.source / "fleet/units/roles.toml"
        fixture.put(roles, roles.read_text() + '"extra.service" = ["session"]\n')
        self.publish()
        self.sync(script=previous / "tools/fleet-sync", expected=1)
        self.assertEqual(self.current(), previous)
        calls = [json.loads(line) for line in (self.home / "verify.log").read_text().splitlines()]
        self.assertTrue(any(any(str(p).endswith("extra.service") for p in call) for call in calls))
        with patch.dict(os.environ, self.env, clear=True):
            module, runner = self.runner()
            with patch.object(module.shutil, "which", return_value=None):
                runner.verify_units(runner.d)
            self.assertTrue(any(i["result"] == "warn" and "systemd-analyze" in i["reason"] for i in runner.state["items"]))

    def test_previous_release_status_and_revert_recovery(self):
        self.sync()
        previous = self.current()
        env = self.source / "fleet/env"
        fixture.put(env, env.read_text() + "NEW_SETTING=1\n")
        bad_commit = self.publish()
        self.sync()
        status = self.sync("status", expected=1)
        local = next(row for row in status["hosts"] if row["host"] == "hel8")
        self.assertEqual(local["previous_release"], previous.name)
        text = self.process("python3", "-I", "-B", self.source / "tools/fleet-sync", "status", "--host", "hel8", expected=1).stdout
        self.assertIn(previous.name, text)
        self.assertIn("recover=ssh", text)
        # A bad release has already been promoted; main is reverted, and the
        # operator invokes the previous immutable runner (SSH is fake in tests).
        self.git(self.source, "revert", "--no-edit", bad_commit)
        self.git(self.source, "push", "origin", "main")
        self.sync(script=previous / "tools/fleet-sync")
        self.assertNotIn("NEW_SETTING", (self.home / ".config/fabrig/env.sh").read_text())
        self.assertEqual(self.current().name, "agents-" + self.git(self.source, "rev-parse", "HEAD").strip())

    def test_concurrent_codex_shell_and_claude_edits(self):
        with patch.dict(os.environ, self.env, clear=True):
            module, runner = self.runner()
            cases = [
                (".codex/config.toml", 'model = "old"\n', '[projects."/new"]\ntrust_level = "trusted"\n', runner.codex),
                (".profile", "# profile\n", "# concurrent profile\n", lambda: runner.shell_block(".profile", False)),
                (".bashrc", "# bashrc\n", "# concurrent bashrc\n", lambda: runner.shell_block(".bashrc", True)),
            ]
            for relative, initial, concurrent, operation in cases:
                with self.subTest(relative=relative):
                    path = self.home / relative
                    fixture.put(path, initial)
                    runner.owned.add(relative)
                    sync = module.os.fsync
                    edits = []
                    def interleave(fd):
                        sync(fd)
                        if not edits:
                            fixture.put(path, initial + concurrent)
                            edits.append(True)
                    with patch.object(module.os, "fsync", side_effect=interleave):
                        operation()
                    self.assertIn(concurrent, path.read_text())
            path = self.home / ".claude/settings.json"
            fixture.put(path, '{"before": true}\n')
            runner.owned.add(".claude/settings.json")
            sync = module.os.fsync
            count = []
            def twice(fd):
                sync(fd)
                count.append(True)
                fixture.put(path, json.dumps({"concurrent": len(count)}))
            with patch.object(module.os, "fsync", side_effect=twice):
                runner.write(".claude/settings.json", '{"fleet": true}\n', semantic=True)
            self.assertEqual(json.loads(path.read_text()), {"concurrent": 2})
            self.assertEqual(runner.state["items"][-1]["reason"], "busy; retry next run")

    def test_claude_concurrent_edit_retries_whole_owned_file(self):
        with patch.dict(os.environ, self.env, clear=True):
            module, runner = self.runner()
            path = self.home / ".claude/settings.json"
            fixture.put(path, '{"before": true}')
            runner.owned.add(".claude/settings.json")
            sync = module.os.fsync
            count = []
            def once(fd):
                sync(fd)
                count.append(True)
                if len(count) == 1:
                    fixture.put(path, '{"client": true}')
            with patch.object(module.os, "fsync", side_effect=once):
                runner.write(".claude/settings.json", '{"fleet": true}', semantic=True)
            self.assertEqual(len(count), 2)
            self.assertEqual(json.loads(path.read_text()), {"fleet": True})

    def test_symlinked_parent_and_leaf_are_refused_before_access(self):
        outside = self.directory / "outside"
        outside.mkdir()
        fixture.put(outside / "config.toml", "private outside bytes\n")
        (self.home / ".cargo").symlink_to(outside)
        with patch.dict(os.environ, self.env, clear=True):
            _, runner = self.runner()
            with self.assertRaises((OSError, ValueError)):
                runner.write(".cargo/config.toml", "fleet\n")
            self.assertEqual((outside / "config.toml").read_text(), "private outside bytes\n")
            self.assertFalse((outside / "config.toml.pre-fleet-sync").exists())
            (self.home / ".cargo").unlink()
            (self.home / ".cargo").mkdir()
            (self.home / ".cargo/config.toml").symlink_to(outside / "config.toml")
            with self.assertRaises((OSError, ValueError)):
                runner.write(".cargo/config.toml", "fleet\n")
            self.assertTrue((self.home / ".cargo/config.toml").is_symlink())

    def test_timeout_kills_descendants_before_unlock(self):
        pidfile = self.home / "descendant.pid"
        script = '''import os, signal, subprocess, sys, time
signal.signal(signal.SIGTERM, signal.SIG_IGN)
child = subprocess.Popen([sys.executable, "-c", "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(120)"])
open(sys.argv[1], "w").write(str(child.pid))
time.sleep(120)
'''
        child = None
        try:
            with patch.dict(os.environ, self.env, clear=True):
                _, runner = self.runner()
                with runner.install_lock() as acquired:
                    self.assertTrue(acquired)
                    with self.assertRaises(subprocess.TimeoutExpired):
                        runner.cmd(sys.executable, "-c", script, pidfile, timeout=0.4)
                    child = int(pidfile.read_text())
                    try:
                        fd = os.pidfd_open(child)
                    except ProcessLookupError:
                        fd = None  # The entire group has already been reaped.
                    if fd is not None:
                        poll = select.poll()
                        poll.register(fd, select.POLLIN)
                        try:
                            self.assertTrue(poll.poll(100), "descendant survived command timeout while install lock is about to close")
                        finally:
                            os.close(fd)
        finally:
            if child is None and pidfile.exists():
                child = int(pidfile.read_text())
            if child is not None:
                try:
                    os.kill(child, signal.SIGKILL)
                except ProcessLookupError:
                    pass

    def test_fifo_managed_state_locks_and_controls_do_not_block(self):
        for relative in (".cargo/config.toml", ".local/state/fleet-sync/lock", ".local/state/fabrig/install.lock",
                         ".local/state/fleet-sync/state.json", ".config/fleet-sync/hold",
                         ".config/fleet-sync/pin", ".config/fleet-sync/defer-fabrig"):
            with self.subTest(relative=relative):
                home = self.directory / ("fifo-" + relative.replace("/", "-"))
                path = home / relative
                path.parent.mkdir(parents=True)
                os.mkfifo(path, 0o600)
                process = subprocess.Popen(["python3", "-I", "-B", str(self.source / "tools/fleet-sync"), "--check", "--json", "--host", "hel8"],
                                           env={**self.env, "HOME": str(home)}, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
                try:
                    output, error = process.communicate(timeout=3)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.communicate()
                    self.fail(f"FIFO blocked: {relative}")
                self.assertEqual(process.returncode, 1, output + error)
                self.assertIn("regular", output + error)

    def test_interrupted_unit_write_retains_ownership_and_reload(self):
        roles = self.source / "fleet/units/roles.toml"
        fixture.put(roles, roles.read_text() + '"role.service" = ["session"]\n"role.timer" = ["session"]\n')
        fixture.put(self.source / "fleet/units/role.service", "[Unit]\nDescription=Role\n[Service]\nType=oneshot\nExecStart=/bin/true\n")
        fixture.put(self.source / "fleet/units/role.timer", "[Unit]\nDescription=Role\n[Timer]\nOnCalendar=minutely\n[Install]\nWantedBy=timers.target\n")
        with patch.dict(os.environ, self.env, clear=True):
            _, runner = self.runner()
            command = runner.cmd
            def interrupt(*args, **kwargs):
                if "daemon-reload" in args:
                    raise OSError("simulated interruption before finish")
                return command(*args, **kwargs)
            with patch.object(runner, "cmd", side_effect=interrupt), self.assertRaises(OSError):
                runner.units()
            _, recovered = self.runner()
            recovered.d.hosts["hel8"]["roles"] = ["builder"]
            recovered.units()
            self.assertFalse((self.home / ".config/systemd/user/role.timer").exists())
            self.assertIn(["--user", "daemon-reload"], self.calls())

    def test_interrupted_unit_removal_resumes_after_unlink(self):
        roles = self.source / "fleet/units/roles.toml"
        fixture.put(roles, roles.read_text() + '"role.service" = ["session"]\n')
        fixture.put(self.source / "fleet/units/role.service", "[Unit]\nDescription=Role\n[Service]\nType=oneshot\nExecStart=/bin/true\n")
        with patch.dict(os.environ, self.env, clear=True):
            _, runner = self.runner()
            runner.units()
            runner.d.hosts["hel8"]["roles"] = ["builder"]
            unlink = runner.safe.unlink
            def unlink_then_interrupt(relative):
                unlink(relative)
                raise OSError("interrupted after unlink")
            with patch.object(runner.safe, "unlink", side_effect=unlink_then_interrupt), self.assertRaises(OSError):
                runner.units()
            _, recovered = self.runner()
            recovered.d.hosts["hel8"]["roles"] = ["builder"]
            command = recovered.cmd
            def reject_missing_disable(*args, **kwargs):
                if "disable" in args and args[-1] == "role.service":
                    self.fail("recovery tried to disable an already removed unit")
                return command(*args, **kwargs)
            with patch.object(recovered, "cmd", side_effect=reject_missing_disable):
                recovered.units()
            self.assertNotIn("role.service", recovered.unit_owned)

    def test_unchanged_run_has_no_state_changing_systemctl_calls(self):
        self.sync()
        fixture.put(self.home / "systemctl.log", "")
        self.sync()
        mutations = {"enable", "disable", "daemon-reload", "start", "stop", "restart", "reload"}
        self.assertFalse([call for call in self.calls() if mutations & set(call)])
        self.assertTrue(any("is-active" in call for call in self.calls()))

    def test_smoke_checks_configuration_without_writing_home(self):
        self.sync()
        with patch.dict(os.environ, self.env, clear=True):
            module, runner = self.runner()
            self.assertTrue(runner.acquire())
            command = runner.cmd
            observed = []
            def check_smoke(*args, **kwargs):
                if "--check" in args and "--json" in args:
                    before = self.snapshot()
                    result = command(*args, **kwargs)
                    self.assertEqual(before, self.snapshot())
                    state = json.loads(result)
                    self.assertTrue(any(i["item"] == ".cargo/config.toml" for i in state["items"]))
                    observed.append(True)
                    return result
                return command(*args, **kwargs)
            try:
                with patch.object(runner, "cmd", side_effect=check_smoke), patch.object(module.os, "execve"):
                    runner.release()
                self.assertEqual(observed, [True])
            finally:
                os.close(runner.lock_fd)

    def test_inactive_or_unlinked_timer_enables_without_reload(self):
        self.sync()
        fixture.put(self.home / "systemctl.log", "")
        self.sync(env={**self.env, "FAKE_INACTIVE": "1"})
        self.assertIn(["--user", "enable", "--now", "--no-reload", "fleet-sync.timer"], self.calls())
        self.assertFalse(any("daemon-reload" in call for call in self.calls()))
        fixture.put(self.home / "systemctl.log", "")
        (self.home / ".config/systemd/user/timers.target.wants/fleet-sync.timer").unlink()
        self.sync()
        self.assertIn(["--user", "enable", "--now", "--no-reload", "fleet-sync.timer"], self.calls())
        self.assertFalse(any("daemon-reload" in call for call in self.calls()))


def load_tests(loader, tests, pattern):
    # Reuse the integration fixture, without rerunning its inherited tests.
    return unittest.TestSuite(ReviewTest(name) for name in ReviewTest.__dict__ if name.startswith("test_"))


if __name__ == "__main__":
    unittest.main()
