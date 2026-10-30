"""Expanded timer/release compatibility for the periodic tier."""
from test_fleet_sync_2 import *


class PeriodicFleetSync2Test(FleetSync2Test):
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


def load_tests(loader, tests, pattern):
    cls = PeriodicFleetSync2Test
    return unittest.TestSuite(cls(name) for name in cls.__dict__ if name.startswith("test_"))
