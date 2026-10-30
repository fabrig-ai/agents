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

    def test_check_marks_all_journaled_reappearances_failed(self):
        self.seed(relative=True, dangling=True)
        self.retire()
        self.seed(dangling=True)
        before = self.snapshot()
        runner = self.retire(check=True)
        self.assertEqual([i["result"] for i in runner.state["items"]], ["failed"] * 5)
        self.assertEqual(before, self.snapshot())

    def test_bootstrap_and_provision_sources_exclude_legacy_root(self):
        # Grep-level guard over executable bootstrap inputs and declarations.
        paths = [fixture.ROOT / "tools/fleet-sync", fixture.ROOT / "tools/installed"]
        paths += [p for p in (fixture.ROOT / "fleet").rglob("*") if p.is_file()
                  and p.suffix != ".md" and p.name != "retired-links.toml"]
        for path in paths:
            with self.subTest(path=str(path.relative_to(fixture.ROOT))):
                source = path.read_text()
                if path == fixture.ROOT / "tools/fleet-sync":
                    # The sole literal is the retirement schema's exclusion root.
                    exclusion = 'or entry["legacy_root"] != "~/src/rust/agents/"'
                    self.assertEqual(source.count(exclusion), 1)
                    source = source.replace(exclusion, "")
                self.assertNotRegex(source, r"src/+rust/+agents(?:/|[\s\"'])")

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
