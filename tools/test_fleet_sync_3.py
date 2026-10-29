"""Nested manifests and manager reload recovery, using only disposable HOME."""

import json
import os
import unittest
from unittest.mock import patch

import test_fleet_sync as fixture


class FleetSync3Test(fixture.FleetTest):
    def setUp(self):
        super().setUp()
        # Exercise nested manifests even in the support-only rollout commit.
        manifest = self.source / "tools/installed"
        original = manifest.read_text()
        enabled = original
        for name, path in {"session-start": "session/start", "record": "records/record",
                           "record-collect": "records/record-collect", "watch": "records/watch",
                           "status-page": "records/status-page"}.items():
            enabled = enabled.replace(f"# {name} {path}", f"{name} {path}")
            fixture.put(self.source / "tools" / path, (fixture.ROOT / "tools" / path).read_text(), True)
        if enabled != original:
            fixture.put(manifest, enabled)
            self.sha = self.publish()

    def test_nested_links_follow_manifest_paths(self):
        self.sync()
        expected = {"session-start": "session/start", "record": "records/record",
                    "record-collect": "records/record-collect", "watch": "records/watch",
                    "status-page": "records/status-page", "fleet-sync": "fleet-sync", "lease": "lease"}
        for name, path in expected.items():
            self.assertEqual(os.readlink(self.home / ".local/bin" / name),
                             str(self.home / "src/fabrig/current/tools" / path))
        self.assertEqual(set(self.state()["managed_links"]), expected.keys())

    def test_bad_candidate_manifests_block_promotion(self):
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

    def test_manifest_allows_whitespace_and_inside_release_symlink(self):
        manifest = self.source / "tools/installed"
        (self.source / "tools/inside").symlink_to("session/start")
        fixture.put(manifest, manifest.read_text() + "  alias\tinside  \n")
        self.publish()
        self.sync()
        self.assertEqual(os.readlink(self.home / ".local/bin/alias"),
                         str(self.home / "src/fabrig/current/tools/inside"))

    def test_removed_tools_cleanup_only_recorded_fleet_links(self):
        self.sync()
        release = self.current()
        links = self.home / ".local/bin"
        # Record at a release rather than current; both forms must be removed.
        (links / "record").unlink()
        (links / "record").symlink_to(release / "tools/records/record")
        (links / "record-collect").unlink()
        (links / "record-collect").symlink_to("../../src/fabrig/current/tools/records/record-collect")
        (links / "watch").unlink()
        (links / "watch").symlink_to("/personal/watch")
        (links / "status-page").unlink()
        fixture.put(links / "status-page", "user file\n")
        (links / "unowned").symlink_to(self.home / "src/fabrig/current/tools/fleet-sync")
        manifest = self.source / "tools/installed"
        fixture.put(manifest, "fleet-sync\nlease\n")
        self.publish()
        with patch.dict(os.environ, self.env, clear=True):
            _, runner = self.runner(check=True)
            runner.links()
            self.assertTrue(any(i["item"] == "link:record" and i["result"] == "drift"
                                for i in runner.state["items"]))
        before = self.snapshot()
        preview = self.process("python3", "-I", "-B", self.source / "tools/fleet-sync", "--host", "hel8",
                               "--preview", self.directory / "cleanup-preview")
        self.assertIn(".local/bin/record:", preview.stdout)
        self.assertIn("-> None", preview.stdout)
        self.assertEqual(before, self.snapshot())
        self.assertTrue((links / "record").is_symlink())
        self.sync(script=release / "tools/fleet-sync")
        for name in ("record", "record-collect", "session-start"):
            self.assertFalse((links / name).is_symlink())
        self.assertEqual(os.readlink(links / "watch"), "/personal/watch")
        self.assertEqual((links / "status-page").read_text(), "user file\n")
        self.assertTrue((links / "unowned").is_symlink())
        self.assertEqual(self.state()["managed_links"], ["fleet-sync", "lease", "status-page"])

    def test_preexisting_matching_link_is_not_claimed_or_removed(self):
        link = self.home / ".local/bin/lease"
        link.parent.mkdir(parents=True)
        link.symlink_to(self.home / "src/fabrig/current/tools/lease")
        self.sync()
        self.assertNotIn("lease", self.state()["managed_links"])
        manifest = self.source / "tools/installed"
        fixture.put(manifest, manifest.read_text().replace("lease\n", ""))
        self.publish()
        self.sync(script=self.current() / "tools/fleet-sync")
        self.assertTrue(link.is_symlink())

    def test_link_journal_survives_failure_before_final_state(self):
        with patch.dict(os.environ, self.env, clear=True):
            _, runner = self.runner()
            runner.links()
            self.assertFalse((self.home / ".local/state/fleet-sync/state.json").exists())
            manifest = self.source / "tools/installed"
            fixture.put(manifest, "fleet-sync\n")
            _, recovered = self.runner()
            recovered.links()
            self.assertFalse((self.home / ".local/bin/lease").is_symlink())

    def test_failed_creation_does_not_claim_an_unmade_link(self):
        with patch.dict(os.environ, self.env, clear=True):
            _, runner = self.runner()
            with patch.object(runner.safe, "link", side_effect=OSError("simulated link failure")):
                with self.assertRaises(OSError):
                    runner.links()
            self.assertEqual(runner.link_owned, set())

    def test_legacy_change_history_proves_link_ownership(self):
        links = self.home / ".local/bin"
        links.mkdir(parents=True)
        (links / "removed").symlink_to(self.home / "src/fabrig/current/tools/removed")
        fixture.put(self.home / ".local/state/fleet-sync/runs.jsonl", json.dumps({"items": [
            {"item": "link:removed", "result": "changed", "reason": "linked to current release"}]}) + "\n")
        with patch.dict(os.environ, self.env, clear=True):
            _, runner = self.runner()
            runner.links()
        self.assertFalse((links / "removed").is_symlink())

    def assert_units_unchanged_since_reload(self):
        reloads = json.loads((self.home / "unit-reloads.json").read_text())
        directory = self.home / ".config/systemd/user"
        self.assertEqual(reloads[-1], {p.name: p.stat().st_mtime_ns
                                      for p in directory.iterdir() if p.is_file()})
        return reloads

    def test_unit_mtimes_after_reload_first_exec_upgrade_and_timer_race(self):
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

    def test_manager_pending_reload_heals_once_without_file_changes(self):
        self.sync()
        directory = self.home / ".config/systemd/user"
        before = self.snapshot(root=directory)
        fixture.put(self.home / "systemctl.log", "")
        fixture.put(self.home / "manager-needs-reload", "fleet-sync.timer\n")
        self.sync()
        self.assertEqual(self.snapshot(root=directory), before)
        self.assertEqual(self.calls().count(["--user", "daemon-reload"]), 1)
        self.assertIn(["--user", "show", "-p", "NeedDaemonReload", "fleet-sync.service", "fleet-sync.timer"], self.calls())
        self.assert_units_unchanged_since_reload()
        self.sync()
        self.assertEqual(self.calls().count(["--user", "daemon-reload"]), 1)
        self.assertFalse(self.state()["unit_reload_pending"])

    def test_manager_reload_failure_keeps_intent_until_success(self):
        self.sync()
        fixture.put(self.home / "manager-needs-reload", "fleet-sync.timer\n")
        with patch.dict(os.environ, self.env, clear=True):
            _, runner = self.runner()
            command = runner.cmd
            def fail_reload(*args, **kwargs):
                if "daemon-reload" in args:
                    raise OSError("simulated reload failure")
                return command(*args, **kwargs)
            with patch.object(runner, "cmd", side_effect=fail_reload), self.assertRaises(OSError):
                runner.units()
        journal = self.home / ".local/state/fleet-sync/units.json"
        self.assertTrue(json.loads(journal.read_text())["reload_pending"])
        (self.home / "manager-needs-reload").unlink()
        self.sync()
        self.assertFalse(json.loads(journal.read_text())["reload_pending"])
        self.assert_units_unchanged_since_reload()

    def test_check_and_preview_never_probe_manager_or_mutate_links(self):
        self.sync()
        fixture.put(self.home / "manager-needs-reload", "fleet-sync.timer\n")
        before = self.snapshot(exclude_mirror=True)
        self.sync("--check")
        self.process("python3", "-I", "-B", self.source / "tools/fleet-sync", "--host", "hel8",
                     "--preview", self.directory / "preview")
        self.assertEqual(before, self.snapshot(exclude_mirror=True))


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(FleetSync3Test(name) for name in FleetSync3Test.__dict__ if name.startswith("test_"))
