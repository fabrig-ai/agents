"""Third-review regressions: private previews, deferred probes and local routing."""

import json
import os
import stat
import tomllib
import unittest
from unittest.mock import patch

import test_fleet_sync as fixture


class FleetSync2cTest(fixture.FleetFixture):
    def preview_run(self, directory, expected=0, cwd=None):
        return self.process("python3", "-I", "-B", self.source / "tools/fleet-sync",
                            "--host", "hel8", "--preview", directory, expected=expected, cwd=cwd)

    def test_preview_defers_all_version_launchers_but_check_keeps_them(self):
        versions = tomllib.loads((self.source / "fleet/versions.toml").read_text())
        for name, pin in versions.items():
            # Simulate a launcher that initializes a cache even for --version.
            fixture.put(self.bin / pin["command"][0],
                        '#!/usr/bin/env python3\nfrom pathlib import Path\n'
                        f'path = Path.home() / {json.dumps("probe-" + name)}\n'
                        'sibling = path.with_name(path.name + ".new")\n'
                        'sibling.write_text("cache initialized")\nsibling.replace(path)\n'
                        f'print({json.dumps(pin["version"])})\n', True)
        before = self.snapshot()
        result = self.preview_run(self.directory / "preview")
        self.assertIn("versions: not probed in preview; see --check", result.stdout)
        self.assertNotIn("version:", result.stdout)
        self.assertEqual(before, self.snapshot())
        self.assertTrue(all(not (self.home / ("probe-" + name)).exists() for name in versions))
        state = self.sync("--check", expected=1)
        for name in versions:
            self.assertTrue((self.home / ("probe-" + name)).exists())
            expected = "warn" if "hel8" in versions[name].get("version_only_hosts", []) else "ok"
            self.assertTrue(any(i["item"] == "version:" + name and i["result"] == expected for i in state["items"]))

    def test_preview_accepts_existing_private_dir_and_creates_private_relative_dir(self):
        existing = self.directory / "existing-preview"
        existing.mkdir(mode=0o700)
        before = self.snapshot()
        self.preview_run(existing)
        self.assertTrue((existing / "home/.cargo/config.toml").is_file())
        self.assertEqual(stat.S_IMODE(existing.lstat().st_mode), 0o700)
        self.preview_run("new-preview", cwd=self.directory)
        created = self.directory / "new-preview"
        self.assertEqual(created.lstat().st_uid, os.geteuid())
        self.assertEqual(stat.S_IMODE(created.lstat().st_mode), 0o700)
        self.assertTrue((created / "home/.cargo/config.toml").is_file())
        self.assertEqual(before, self.snapshot())

    def test_preview_refuses_nonprivate_modes_without_repair_or_output(self):
        for mode in (0o000, 0o500, 0o710, 0o755, 0o777, 0o1700, 0o2700, 0o4700):
            with self.subTest(mode=oct(mode)):
                directory = self.directory / f"preview-{mode:o}"
                directory.mkdir(mode=0o700)
                directory.chmod(mode)
                try:
                    result = self.preview_run(directory, expected=1)
                    self.assertIn("owned by the user with mode 0700", result.stderr)
                    self.assertEqual(stat.S_IMODE(directory.lstat().st_mode), mode)
                finally:
                    directory.chmod(0o700)
                self.assertEqual(list(directory.iterdir()), [])

    def test_preview_refuses_other_owner_before_copying(self):
        directory = self.directory / "other-owner-preview"
        directory.mkdir(mode=0o700)
        before = self.snapshot(root=directory)
        with patch.dict(os.environ, self.env):
            module, runner = self.runner()
            # Model a caller different from the directory owner without real chown.
            with patch.object(module.os, "geteuid", return_value=directory.lstat().st_uid + 1):
                with self.assertRaisesRegex(ValueError, "owned by the user with mode 0700"):
                    runner.preview(directory)
        self.assertEqual(before, self.snapshot(root=directory))

    def test_preview_refuses_symlinks_at_leaf_parent_and_ancestor(self):
        real = self.directory / "real"
        private = real / "middle/preview"
        private.mkdir(parents=True, mode=0o700)
        leaf = self.directory / "leaf-alias"
        leaf.symlink_to(private, target_is_directory=True)
        parent = self.directory / "parent-alias"
        parent.symlink_to(private.parent, target_is_directory=True)
        ancestor = self.directory / "ancestor-alias"
        ancestor.symlink_to(real, target_is_directory=True)
        before = self.snapshot(root=real)
        for destination in (leaf, parent / "preview", ancestor / "middle/preview",
                            ancestor / ".." / "collapsed-preview"):
            with self.subTest(destination=destination):
                result = self.preview_run(destination, expected=1)
                self.assertIn("no symlinked components", result.stderr)
                self.assertEqual(before, self.snapshot(root=real))
        self.assertFalse((self.directory / "collapsed-preview").exists())

    def test_preview_refuses_nondirectory_components(self):
        ordinary = self.directory / "ordinary-file"
        fixture.put(ordinary, "keep\n")
        fifo = self.directory / "fifo"
        os.mkfifo(fifo, 0o600)
        for destination in (ordinary, ordinary / "preview", fifo):
            with self.subTest(destination=destination):
                result = self.preview_run(destination, expected=1)
                self.assertIn("must be a directory", result.stderr)
        self.assertEqual(ordinary.read_text(), "keep\n")
        self.assertTrue(stat.S_ISFIFO(fifo.lstat().st_mode))

    def test_local_sentinel_differs_from_ssh_local_in_check_and_preview(self):
        hosts = tomllib.loads((self.source / "fleet/hosts.toml").read_text())["hosts"]
        text = "hel8 free@local\n" + "".join(f"{name} {host['ssh']}\n" for name, host in hosts.items() if name != "hel8")
        path = self.home / "src/rust/tmp/post/machines"
        fixture.put(path, text)
        before = self.snapshot()
        state = self.sync("--check", expected=1, env={**self.env, "USER": "free"})
        item = next(i for i in state["items"] if i["item"] == "src/rust/tmp/post/machines")
        self.assertEqual(item["result"], "warn")
        self.assertEqual(item["reason"], "names differ: hel8; check-only")
        output = self.directory / "preview"
        result = self.process("python3", "-I", "-B", self.source / "tools/fleet-sync", "--host", "hel8",
                              "--preview", output, env={**self.env, "USER": "free"})
        self.assertIn("names differ: hel8; check-only", result.stdout)
        self.assertEqual((output / "home/src/rust/tmp/post/machines").read_text(), text)
        self.assertEqual(before, self.snapshot())

    def test_username_default_applies_only_to_ssh_targets(self):
        with patch.dict(os.environ, self.env):
            module, runner = self.runner()
            self.assertEqual(runner.machine_map(b"hel8 local\n", "free"), {"hel8": "local"})
            self.assertEqual(runner.machine_map(b"hel8 free@local\n", "free"), {"hel8": "free@local"})
            self.assertEqual(runner.machine_map(b"other example.invalid\n", "free"),
                             runner.machine_map(b"other free@example.invalid\n", "free"))


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(FleetSync2cTest(name) for name in FleetSync2cTest.__dict__ if name.startswith("test_"))
