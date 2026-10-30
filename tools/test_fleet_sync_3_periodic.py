"""Exhaustive process/compatibility sweeps; run in the periodic tier."""

from test_fleet_sync_3 import *


class PeriodicFleetSync3Test(FleetSync3Test):
    def test_bad_candidate_manifests_block_promotion(self):
        self.sha = self.publish()
        self.sync()
        current = self.current()
        manifest = self.source / "tools/installed"
        original = manifest.read_text()
        outside = self.directory / "outside"
        fixture.put(outside, "#!/bin/sh\nexit 0\n", True)
        (self.source / "tools/escape").symlink_to(outside)
        (self.source / "tools/loop").symlink_to("loop")
        fixture.put(self.source / "tools/not-executable", "no\n")
        (self.source / "tools/directory").mkdir()
        cases = ("Upper fleet-sync", "bad_name fleet-sync", "1bad fleet-sync",
                 "bad ../tools/fleet-sync", "bad /bin/sh", "bad escape", "bad missing",
                 "bad not-executable", "bad directory", "bad loop", "bad a b",
                 "fleet-sync fleet-sync", "one fleet-sync\none lease")
        for entry in cases:
            with self.subTest(entry=entry):
                fixture.put(manifest, original + entry + "\n")
                self.process("python3", "-I", "-B", self.source / "tools/fleet-sync",
                             "--self-check", "--host", "hel8", expected=2)
                self.publish()
                state = self.sync(script=current / "tools/fleet-sync", expected=1)
                self.assertEqual(self.current(), current)
                self.assertTrue(any(i["item"] == "agents" and i["result"] == "failed" for i in state["items"]))

    def test_unit_mtimes_after_reload_first_exec_upgrade_and_timer_race(self):
        self.sha = self.publish()
        self.sync(env={**self.env, "FAKE_ENABLE_TIMER_RUN": "1"})
        self.assertEqual(json.loads((self.home / "timer-race.json").read_text()), [0, "", ""])
        self.assertEqual(len(self.assert_units_unchanged_since_reload()), 1)
        unit = self.source / "fleet/units/fleet-sync.timer"
        fixture.put(unit, unit.read_text().replace("[Unit]", "[Unit]\n# upgraded"))
        self.publish()
        self.sync(script=self.current() / "tools/fleet-sync")
        self.assertEqual(len(self.assert_units_unchanged_since_reload()), 2)
        self.sync()
        self.assertEqual(len(self.assert_units_unchanged_since_reload()), 2)


def load_tests(loader, tests, pattern):
    cls = PeriodicFleetSync3Test
    return unittest.TestSuite(cls(name) for name in cls.__dict__ if name.startswith("test_"))
