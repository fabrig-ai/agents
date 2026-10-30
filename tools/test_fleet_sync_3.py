"""Nested manifests and manager reload recovery, using only disposable HOME."""

import json
import os
import shutil
import unittest
from unittest.mock import patch

import test_fleet_sync as fixture


class FleetSync3Test(fixture.FleetTest):
    def setUp(self):
        super().setUp()
        # Exercise path support independently of either production manifest stage.
        self.installed = {"fleet-sync": "fleet-sync", "lease": "lease"}
        for suffix in ("one", "two", "three", "four", "five"):
            self.installed[f"nested-{suffix}"] = f"nested/{suffix}"
            fixture.put(self.source / "tools/nested" / suffix, "#!/bin/sh\nexit 0\n", True)
        fixture.put(self.source / "tools/installed", "".join(
            f"{name}\n" if name == target else f"{name} {target}\n"
            for name, target in self.installed.items()))

    def link_release(self, revision="a" * 40):
        """Two private immutable trees suffice to prove stable current links.

        Real git promotion/exec and timer handoff are tested separately.
        """
        release = self.home / "src/fabrig/releases" / ("agents-" + revision)
        shutil.copytree(self.source, release, symlinks=True,
                        ignore=shutil.ignore_patterns(".git"))
        with patch.dict(os.environ, self.env, clear=True):
            module, _ = self.runner()
            module.atomic_link(self.home / "src/fabrig/current", release)
        return self.component_sync("links")

    def test_nested_links_follow_manifest_paths(self):
        self.component_sync("links")
        expected = self.installed
        for name, path in expected.items():
            self.assertEqual(os.readlink(self.home / ".local/bin" / name),
                             str(self.home / "src/fabrig/current/tools" / path))
        self.assertEqual(set(self.state()["managed_links"]), expected.keys())

    def test_session_reap_hook_production_mapping_survives_release_switch(self):
        manifest = dict((line.split()[0], line.split()[-1])
                        for line in (fixture.ROOT / "tools/installed").read_text().splitlines()
                        if line.strip() and not line.lstrip().startswith("#"))
        target = manifest["session-reap-hook"]
        self.assertEqual(target, "session/reap-hook")
        path = self.source / "tools/installed"
        fixture.put(path, path.read_text() + f"session-reap-hook {target}\n")
        self.link_release()
        link = self.home / ".local/bin/session-reap-hook"
        expected = str(self.home / "src/fabrig/current/tools" / target)
        self.assertEqual(os.readlink(link), expected)
        previous = link.resolve()
        fixture.put(self.source / "tools" / target, "#!/bin/sh\nexit 0\n", True)
        self.link_release("b" * 40)
        self.assertEqual(os.readlink(link), expected)
        self.assertNotEqual(link.resolve(), previous)
        self.assertTrue(link.is_file())


    def test_manifest_validation_table(self):
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
        before = self.snapshot()
        with patch.dict(os.environ, self.env, clear=True):
            module = self.load_runner()
            for entry in cases:
                with self.subTest(entry=entry):
                    fixture.put(manifest, original + entry + "\n")
                    with self.assertRaises(ValueError):
                        module.Declarations(self.source, self.home)
                    self.assertEqual(self.snapshot(), before)

    def test_manifest_allows_whitespace_and_inside_release_symlink(self):
        manifest = self.source / "tools/installed"
        (self.source / "tools/inside").symlink_to("nested/five")
        fixture.put(manifest, manifest.read_text() + "  alias\tinside  \n")
        self.component_sync("links")
        self.assertEqual(os.readlink(self.home / ".local/bin/alias"),
                         str(self.home / "src/fabrig/current/tools/inside"))

    def test_removed_tools_cleanup_only_recorded_fleet_links(self):
        self.link_release()
        release = self.current()
        links = self.home / ".local/bin"
        # Record at a release rather than current; both forms must be removed.
        (links / "nested-one").unlink()
        (links / "nested-one").symlink_to(release / "tools/nested/one")
        (links / "nested-two").unlink()
        (links / "nested-two").symlink_to("../../src/fabrig/current/tools/nested/two")
        (links / "nested-three").unlink()
        (links / "nested-three").symlink_to("/personal/watch")
        (links / "nested-four").unlink()
        fixture.put(links / "nested-four", "user file\n")
        (links / "unowned").symlink_to(self.home / "src/fabrig/current/tools/fleet-sync")
        manifest = self.source / "tools/installed"
        fixture.put(manifest, "fleet-sync\nlease\n")
        with patch.dict(os.environ, self.env, clear=True):
            _, runner = self.runner(check=True)
            runner.links()
            self.assertTrue(any(i["item"] == "link:nested-one" and i["result"] == "drift"
                                for i in runner.state["items"]))
        before = self.snapshot()
        preview = self.process("python3", "-I", "-B", self.source / "tools/fleet-sync", "--host", "hel8",
                               "--preview", self.directory / "cleanup-preview")
        self.assertIn(".local/bin/nested-one:", preview.stdout)
        self.assertIn("-> None", preview.stdout)
        self.assertEqual(before, self.snapshot())
        self.assertTrue((links / "nested-one").is_symlink())
        self.component_sync("links")
        for name in ("nested-one", "nested-two", "nested-five"):
            self.assertFalse((links / name).is_symlink())
        self.assertEqual(os.readlink(links / "nested-three"), "/personal/watch")
        self.assertEqual((links / "nested-four").read_text(), "user file\n")
        self.assertTrue((links / "unowned").is_symlink())
        self.assertEqual(self.state()["managed_links"], ["fleet-sync", "lease", "nested-four"])

    def test_preexisting_matching_link_is_not_claimed_or_removed(self):
        link = self.home / ".local/bin/lease"
        link.parent.mkdir(parents=True)
        link.symlink_to(self.home / "src/fabrig/current/tools/lease")
        self.component_sync("links")
        self.assertNotIn("lease", self.state()["managed_links"])
        manifest = self.source / "tools/installed"
        fixture.put(manifest, manifest.read_text().replace("lease\n", ""))
        self.component_sync("links")
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


    def test_first_exec_timer_race_preserves_unit_mtimes(self):
        with patch.dict(os.environ, {**self.env, "FAKE_ENABLE_TIMER_RUN": "1"}, clear=True):
            module, runner = self.runner()
            module.atomic_link(self.home / "src/fabrig/current", self.source)
            self.assertTrue(runner.acquire())
            try:
                runner.units()
            finally:
                os.close(runner.lock_fd)
        self.assertEqual(json.loads((self.home / "timer-race.json").read_text()), [0, "", ""])
        self.assertEqual(len(self.assert_units_unchanged_since_reload()), 1)

    def test_manager_pending_reload_heals_once_without_file_changes(self):
        self.component_sync("units")
        directory = self.home / ".config/systemd/user"
        before = self.snapshot(root=directory)
        fixture.put(self.home / "systemctl.log", "")
        fixture.put(self.home / "manager-needs-reload", "fleet-sync.timer\n")
        self.component_sync("units")
        self.assertEqual(self.snapshot(root=directory), before)
        self.assertEqual(self.calls().count(["--user", "daemon-reload"]), 1)
        self.assertEqual([call for call in self.calls() if call[1:4] == ["show", "-p", "NeedDaemonReload"]],
                         [["--user", "show", "-p", "NeedDaemonReload", *sorted(self.state()["managed_units"])]])
        self.assert_units_unchanged_since_reload()
        self.component_sync("units")
        self.assertEqual(self.calls().count(["--user", "daemon-reload"]), 1)
        self.assertFalse(self.state()["unit_reload_pending"])

    def test_manager_reload_failure_keeps_intent_until_success(self):
        self.component_sync("units")
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
        self.component_sync("units")
        self.assertFalse(json.loads(journal.read_text())["reload_pending"])
        self.assert_units_unchanged_since_reload()

    def test_check_and_preview_never_probe_manager_or_mutate_links(self):
        self.component_sync("links", "render", "units")
        fixture.put(self.home / "manager-needs-reload", "fleet-sync.timer\n")
        before = self.snapshot(exclude_mirror=True)
        self.component_sync("links", "render", "units", check=True)
        self.process("python3", "-I", "-B", self.source / "tools/fleet-sync", "--host", "hel8",
                     "--preview", self.directory / "preview")
        self.assertEqual(before, self.snapshot(exclude_mirror=True))


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(FleetSync3Test(name) for name in FleetSync3Test.__dict__ if name.startswith("test_"))
