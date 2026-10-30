"""Exhaustive process/compatibility sweeps; run in the periodic tier."""

from test_review_fleet_sync import *


class PeriodicReviewTest(ReviewTest):
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
        broken = self.current() / "tools/fleet-sync"
        fixture.put(broken, "raise SystemExit(99)\n", True)
        self.process("python3", "-I", "-B", broken, "--check", "--host", "hel8", expected=99)
        self.git(self.source, "revert", "--no-edit", bad_commit)
        self.git(self.source, "push", "origin", "main")
        self.sync(script=previous / "tools/fleet-sync")
        self.assertNotIn("NEW_SETTING", (self.home / ".config/fabrig/env.sh").read_text())
        self.assertEqual(self.current().name, "agents-" + self.git(self.source, "rev-parse", "HEAD").strip())

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


def load_tests(loader, tests, pattern):
    cls = PeriodicReviewTest
    return unittest.TestSuite(cls(name) for name in cls.__dict__ if name.startswith("test_"))
