"""Exhaustive process/compatibility sweeps; run in the periodic tier."""

from test_fleet_sync_4 import *


class PeriodicStartOnceTest(StartOnceTest):
    def test_1148127_runner_accepts_marker_and_new_journal_as_ordinary_service(self):
        self.publish()
        self.sync()
        self.unit.unlink()
        old_script = fixture.historical_source("1148127")
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

    def test_first_write_starts_after_reload_once_and_unchanged_does_nothing(self):
        self.publish()
        state = self.sync()
        enable = ["--user", "enable", "--now", "--no-reload", NAME]
        self.assertEqual(self.calls().count(enable), 1)
        self.assertLess(self.calls().index(["--user", "daemon-reload"]), self.calls().index(enable))
        self.assertTrue(self.link.is_symlink())
        self.assertTrue((self.home / (NAME + ".active")).exists())
        self.assertFalse(any(i["item"] == NAME and "restart pending" in i["reason"] for i in state["items"]))
        self.assertIn(NAME, json.loads(self.journal.read_text())["start_once_started"])
        self.reset_calls()
        self.component_sync("units")
        self.assertEqual(self.mutations(), [])
        self.assertIn(["--user", "is-active", "--quiet", NAME], self.calls())


def load_tests(loader, tests, pattern):
    cls = PeriodicStartOnceTest
    return unittest.TestSuite(cls(name) for name in cls.__dict__ if name.startswith("test_"))
