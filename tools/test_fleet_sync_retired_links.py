"""Retired PATH links: disposable HOME, fake services and local git origins."""

import datetime as dt
import json
import os
import unittest
from unittest.mock import patch

import test_fleet_sync as fixture

NAMES = ("after-landing", "land", "land-set", "repin", "setup")
JOURNAL = ".local/state/fleet-sync/retired_links.json"


class RetiredLinksTest(fixture.FleetTest):
    def link(self, name, text):
        path = self.home / ".local/bin" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.symlink_to(text)
        return path

    def seed(self, relative=False, dangling=False):
        texts = {}
        for name in NAMES:
            target = self.home / "src/rust/agents/scripts" / ("infra" if name == "setup" else "devel") / name
            if not dangling:
                fixture.put(target, "legacy script bytes\n", True)
            text = os.path.relpath(target, self.home / ".local/bin") if relative else str(target)
            texts[name] = text
            self.link(name, text)
        return texts

    def retire(self, check=False):
        with patch.dict(os.environ, self.env, clear=True):
            _, runner = self.runner(check=check)
            runner.retire_links()
        return runner

    def assert_removed(self, texts):
        for name in texts:
            self.assertFalse(os.path.lexists(self.home / ".local/bin" / name))
        records = json.loads((self.home / JOURNAL).read_text())
        self.assertEqual({r["name"]: r["text"] for r in records}, texts)
        for record in records:
            self.assertEqual(record["release"], self.sha)
            self.assertIsNotNone(dt.datetime.fromisoformat(record["time"]).tzinfo)
        self.assertEqual((self.home / JOURNAL).stat().st_mode & 0o777, 0o600)

    def test_all_five_absolute_targets_retired_without_changing_kit_or_other_links(self):
        texts = self.seed()
        other = self.link("record", str(self.home / "src/rust/agents/scripts/devel/record"))
        before = self.snapshot(root=self.home / "src/rust/agents")
        state = self.sync()
        self.assertEqual([i["result"] for i in state["items"]
                          if i["item"].startswith("retired-link:")], ["changed"] * 5)
        self.assert_removed(texts)
        self.assertTrue(other.is_symlink())
        self.assertEqual(before, self.snapshot(root=self.home / "src/rust/agents"))

    def test_all_five_relative_targets_retired(self):
        texts = self.seed(relative=True)
        self.retire()
        self.assert_removed(texts)

    def test_all_five_dangling_targets_retired(self):
        texts = self.seed(dangling=True)
        self.retire()
        self.assert_removed(texts)

    def test_other_targets_files_directories_and_symlink_hops_warn_and_survive(self):
        self.link("after-landing", str(self.directory / "elsewhere"))
        fixture.put(self.home / ".local/bin/land", "user replacement\n")
        (self.home / ".local/bin/land-set").mkdir()
        root = self.home / "src/rust/agents"
        root.mkdir(parents=True)
        outside = self.directory / "outside"
        outside.mkdir()
        (root / "escape").symlink_to(outside)
        self.link("repin", str(root / "escape/repin"))
        # A final symlink is also a further hop, even if it is dangling.
        (root / "setup").symlink_to(outside / "setup")
        self.link("setup", str(root / "setup"))
        before = self.snapshot()
        runner = self.retire()
        self.assertEqual(before, self.snapshot())
        self.assertEqual([i["result"] for i in runner.state["items"]], ["warn"] * 5)

    def test_symlink_hop_cannot_be_hidden_by_dotdot(self):
        root = self.home / "src/rust/agents"
        root.mkdir(parents=True)
        (root / "escape").symlink_to(self.directory)
        path = self.link("land", str(root / "escape/../land"))
        self.retire()
        self.assertTrue(path.is_symlink())
        self.assertFalse((self.home / JOURNAL).exists())

    def test_root_prefix_collision_is_kept(self):
        path = self.link("land", str(self.home / "src/rust/agents-other/land"))
        self.retire()
        self.assertTrue(path.is_symlink())

    def test_journal_precedes_unlink_and_rerun_is_idempotent(self):
        texts = self.seed(relative=True, dangling=True)
        with patch.dict(os.environ, self.env, clear=True):
            _, runner = self.runner()
            save = runner.safe.save

            def journal_first(path, data, *args):
                records = json.loads(data)
                self.assertEqual(os.readlink(self.home / ".local/bin" / records[-1]["name"]), records[-1]["text"])
                save(path, data, *args)

            with patch.object(runner.safe, "save", side_effect=journal_first):
                runner.retire_links()
        self.assert_removed(texts)
        before = self.snapshot()
        runner = self.retire()
        self.assertEqual(before, self.snapshot())
        self.assertEqual([i["result"] for i in runner.state["items"]], ["ok"] * 5)

    def test_failed_journal_keeps_link(self):
        path = self.link("land", str(self.home / "src/rust/agents/land"))
        with patch.dict(os.environ, self.env, clear=True):
            _, runner = self.runner()
            with patch.object(runner.safe, "save", side_effect=OSError("journal unavailable")):
                runner.retire_links()
        self.assertTrue(path.is_symlink())

    def test_replacement_during_journal_write_is_kept(self):
        path = self.link("land", str(self.home / "src/rust/agents/land"))
        with patch.dict(os.environ, self.env, clear=True):
            _, runner = self.runner()
            save = runner.safe.save

            def replace_link(*args):
                save(*args)
                path.unlink()
                fixture.put(path, "user replacement\n")

            with patch.object(runner.safe, "save", side_effect=replace_link):
                runner.retire_links()
        self.assertEqual(path.read_text(), "user replacement\n")

    def test_check_reports_drift_without_writes(self):
        texts = self.seed(relative=True, dangling=True)
        before = self.snapshot()
        state = self.sync("--check", expected=1)
        for name, text in texts.items():
            self.assertIn({"item": f"retired-link:{name}", "result": "drift",
                           "reason": f"would retire {name} (-> {text})"}, state["items"])
        self.assertEqual(before, self.snapshot())

    def test_preview_shows_removals_and_keeps_real_home(self):
        texts = self.seed(relative=True)
        before = self.snapshot()
        destination = self.directory / "preview"
        result = self.process("python3", "-I", "-B", self.source / "tools/fleet-sync",
                              "--host", "hel8", "--preview", destination)
        for name, text in texts.items():
            self.assertIn(f"would retire {name} (-> {text})", result.stdout)
            self.assertIn(f"link {self.home}/.local/bin/{name}: {text} -> None", result.stdout)
            self.assertFalse(os.path.lexists(destination / "home/.local/bin" / name))
        self.assertEqual(before, self.snapshot())
        self.assertFalse((self.home / "systemctl.log").exists())
        self.assertTrue((destination / "home" / JOURNAL).is_file())

    def test_preview_conflicts_warn_without_reading_files_or_directories(self):
        fixture.put(self.home / ".local/bin/land", "user replacement\n")
        (self.home / ".local/bin/setup").mkdir()
        root = self.home / "src/rust/agents"
        root.mkdir(parents=True)
        (root / "escape").symlink_to(self.directory)
        self.link("repin", str(root / "escape/repin"))
        before = self.snapshot()
        result = self.process("python3", "-I", "-B", self.source / "tools/fleet-sync",
                              "--host", "hel8", "--preview", self.directory / "preview")
        for name in NAMES:
            self.assertRegex(result.stdout, rf"warn\s+retired-link:{name}:")
        self.assertEqual(before, self.snapshot())

    def test_hold_suppresses_apply_check_preview_and_status(self):
        self.seed()
        fixture.put(self.home / ".config/fleet-sync/hold", "ops hold\n")
        before = self.snapshot()
        self.assertEqual([i["item"] for i in self.sync()["items"]], ["hold"])
        self.assertEqual([i["item"] for i in self.sync("--check")["items"]], ["hold"])
        destination = self.directory / "preview"
        self.process("python3", "-I", "-B", self.source / "tools/fleet-sync", "--host", "hel8", "--preview", destination)
        self.assertFalse(destination.exists())
        self.assertEqual(before, self.snapshot())
        with patch.dict(os.environ, self.env, clear=True):
            module, runner = self.runner()
            runner.args.json = True
            runner.args.host = "hel8"
            declarations = runner.d
            declarations.hosts = {"hel8": declarations.hosts["hel8"]}
            with patch("builtins.print") as output:
                self.assertEqual(module.status(runner.args, declarations, "hel8"), 0)
            state = json.loads(output.call_args.args[0])["hosts"][0]
            self.assertEqual([i["item"] for i in state["items"]], ["hold"])
        self.assertEqual(before, self.snapshot())

    def test_status_reports_retirement_drift_without_writes(self):
        texts = self.seed(dangling=True)
        before = self.snapshot()
        with patch.dict(os.environ, self.env, clear=True):
            module, runner = self.runner()
            runner.args.json = True
            runner.args.host = "hel8"
            runner.d.hosts = {"hel8": runner.d.hosts["hel8"]}
            with patch("builtins.print") as output:
                self.assertEqual(module.status(runner.args, runner.d, "hel8"), 1)
            items = json.loads(output.call_args.args[0])["hosts"][0]["items"]
            for name, text in texts.items():
                self.assertIn({"item": f"retired-link:{name}", "result": "drift",
                               "reason": f"would retire {name} (-> {text})"}, items)
        self.assertEqual(before, self.snapshot())

    def test_self_check_refuses_installed_and_retired_overlap(self):
        fixture.put(self.source / "tools/land", "#!/bin/sh\nexit 0\n", True)
        manifest = self.source / "tools/installed"
        fixture.put(manifest, manifest.read_text() + "land\n")
        before = self.snapshot()
        result = self.process("python3", "-I", "-B", self.source / "tools/fleet-sync",
                              "--host", "hel8", "--self-check", expected=2)
        self.assertIn("both installed and retired: land", result.stderr)
        self.assertEqual(before, self.snapshot())


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(RetiredLinksTest(name) for name in RetiredLinksTest.__dict__
                              if name.startswith("test_"))
