"""Stage-2 manifest policy, exercised only with temporary HOME and fake services."""

import os
import unittest

import test_fleet_sync as fixture


class ManifestActivationTest(fixture.FleetTest):
    def test_agreed_manifest_links_preserve_legacy_record_and_system_watch(self):
        legacy = self.home / ".local/bin/record"
        legacy.parent.mkdir(parents=True)
        legacy.symlink_to(self.directory / "legacy-record")
        (self.home / ".local/bin/logins").symlink_to(self.directory / "legacy-logins")
        legacy_qa = self.home / ".local/bin/qa"
        legacy_qa.symlink_to(self.home / "src/rust/agents/scripts/devel/qa")
        fixture.put(self.home / ".config/fleet-sync/defer-fabrig", "preserve legacy installer links\n")
        self.component_sync("links")
        self.assertEqual(os.readlink(legacy), str(self.directory / "legacy-record"))
        self.assertFalse(os.path.lexists(self.home / ".local/bin/watch"))
        expected = {"fleet-sync": "fleet-sync", "lease": "lease", "session-start": "session/start",
                    "session-context": "session/session-context",
                    "session-reap-hook": "session/reap-hook",
                    "fabrig-record": "records/record", "record-collect": "records/record-collect",
                    "pipeline-watch": "records/watch", "status-page": "records/status-page",
                    "logins": "qa/logins", "qa": "qa/qa"}
        for name, path in expected.items():
            self.assertEqual(os.readlink(self.home / ".local/bin" / name),
                             str(self.home / "src/fabrig/current/tools" / path))
        self.assertEqual(set(self.state()["managed_links"]), expected.keys())


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(ManifestActivationTest(name) for name in ManifestActivationTest.__dict__
                              if name.startswith("test_"))
