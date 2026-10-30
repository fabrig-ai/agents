"""Retirement process/preview and full bootstrap exclusions, using fakes only."""

from test_fleet_sync_retired_links import *
import argparse
import contextlib
import importlib.util
import io
from pathlib import Path

from test_bootstrap import ProvisionTest


class PeriodicRetiredLinksTest(RetiredLinksTest):
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


    def test_reappeared_links_fail_check_and_status_without_writes(self):
        self.seed(relative=True, dangling=True)
        self.retire()
        texts = self.seed(dangling=True)  # New spelling must still fail by name.
        before = self.snapshot()
        state = self.sync("--check", expected=1)
        expected = [{"item": f"retired-link:{name}", "result": "failed",
                     "reason": f"retired link reappeared: {name} (-> {text})"}
                    for name, text in texts.items()]
        self.assertEqual([i for i in state["items"] if i["item"].startswith("retired-link:")], expected)
        with patch.dict(os.environ, self.env, clear=True):
            module, runner = self.runner()
            runner.args.json = True
            runner.args.host = "hel8"
            runner.d.hosts = {"hel8": runner.d.hosts["hel8"]}
            with patch("builtins.print") as output:
                self.assertEqual(module.status(runner.args, runner.d, "hel8"), 1)
            items = json.loads(output.call_args.args[0])["hosts"][0]["items"]
            self.assertEqual([i for i in items if i["item"].startswith("retired-link:")], expected)
        self.assertEqual(before, self.snapshot())



class BootstrapExclusionTest(ProvisionTest):
    def test_full_bootstrap_user_and_sync_never_provision_legacy_paths(self):
        self.only_toolchain_and_cache_pins()
        # Include a real fake download/install, beyond already-present tools.
        artifact = self.artifact("fixture-tool", "fixture-tool 1.2.3")
        url, digest = self.download(artifact)
        self.f.env["FAKE_DOWNLOADS"] = os.environ["FAKE_DOWNLOADS"]
        pins = self.f.source / "fleet/versions.toml"
        fixture.put(pins, pins.read_text() + f"""
[fixture-tool]
version = "1.2.3"
command = ["fixture-tool", "--version"]
[fixture-tool.install]
kind = "binary"
url = "{url}"
sha256 = "{digest}"
destination = ".local/bin/fixture-tool"
""")
        self.f.publish()
        rust = self.module.Declarations(self.f.source, self.f.home).versions["rustc"]["install"]
        outputs = {
            "show active-toolchain": "1.95.0-x86_64-unknown-linux-gnu (default)",
            "toolchain list": "1.95.0-x86_64-unknown-linux-gnu\nnightly-2026-10-21-x86_64-unknown-linux-gnu",
            "component list --installed --toolchain 1.95.0": "\n".join(c + "-x86_64-unknown-linux-gnu" for c in rust["components"]),
            "target list --installed --toolchain 1.95.0": "\n".join(rust["targets"]),
        }
        fixture.put(self.f.bin / "rustup", "#!/usr/bin/env python3\nimport sys\n"
                    f"print({outputs!r}.get(' '.join(sys.argv[1:]), ''))\n", True)
        spec = importlib.util.spec_from_file_location("bootstrap_exclusion", self.f.source / "fleet/bootstrap/bootstrap.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        bootstrap = module.Bootstrap(argparse.Namespace(dry_run=False, host=self.host))
        legacy = self.f.home / "src/rust/agents"
        fleet_runs = []

        def assert_excluded():
            self.assertFalse(os.path.lexists(legacy))
            for path in self.f.home.rglob("*"):
                if path.is_symlink():
                    target = Path(os.path.normpath(path.parent / os.readlink(path)))
                    self.assertFalse(target.is_relative_to(legacy), str(path))
            for name in NAMES:
                self.assertFalse(os.path.lexists(self.f.home / ".local/bin" / name))

        def run(*argv, capture=False):
            self.assertNotIn(str(legacy), " ".join(map(str, argv)))
            result = self.f.process(*argv).stdout
            if "--host" in argv:
                fleet_runs.append(argv)
                assert_excluded()
            return result

        with patch.object(module.os, "geteuid", return_value=1000), \
             patch.object(module.pwd, "getpwuid", return_value=argparse.Namespace(pw_name="free")), \
             patch.object(bootstrap, "run", side_effect=run), contextlib.redirect_stdout(io.StringIO()):
            bootstrap.user()
        self.assertEqual(len(fleet_runs), 2)
        self.assertIn("--provision", fleet_runs[0])
        self.assertNotIn("--provision", fleet_runs[1])
        self.assertTrue((self.f.home / ".local/bin/fixture-tool").is_file())
        self.assertEqual(json.loads((self.f.home / "downloads.json").read_text()), [url])
        assert_excluded()


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(cls(name) for cls in (PeriodicRetiredLinksTest, BootstrapExclusionTest)
                              for name in cls.__dict__ if name.startswith("test_"))
