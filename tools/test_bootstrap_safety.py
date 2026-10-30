"""Landing safety: isolated HOME/services only; live evidence is a separate preview."""

import json
import os
from pathlib import Path
import tomllib
import unittest
from unittest.mock import patch

import test_bootstrap as bootstrap
import test_fleet_sync as fixture


class BootstrapSafetyTest(unittest.TestCase):
    def setUp(self):
        self.h = bootstrap.ProvisionTest(methodName="runTest")
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)
        self.f, self.runner, self.module = self.h.f, self.h.runner, self.h.module

    def test_live_roles_timer_leaves_ops_kache_bytes_modes_links_and_ownership_unchanged(self):
        for host in ("hel8",):
            with self.subTest(host=host):
                self.f.deployed()
                for relative, text in {
                    ".config/kache/config.toml": '[cache]\nlocal_max_size = "99GiB"\n[cache.remote]\ntype = "s3"\n',
                    ".config/kache/store.env": "PRIVATE FIXTURE: must not be opened",
                    ".cache/kache/store/retain": "old cache data",
                    ".config/systemd/user/kache.service": "# ops-owned\n[Service]\nExecStart=/ops/kache daemon run\n",
                    ".config/systemd/user/kache.service.d/20-shared-store.conf": "# ops-owned credential reference\n",
                }.items():
                    fixture.put(self.f.home / relative, text)
                kache = self.f.home / ".local/bin/kache"
                fixture.put(kache, "#!/bin/bash\necho kache 1.2.2-gitrev.2\n", True)
                before = {p: (self.f.home / p).read_bytes() for p in (
                    ".config/kache/config.toml", ".config/kache/store.env", ".cache/kache/store/retain",
                    ".config/systemd/user/kache.service", ".config/systemd/user/kache.service.d/20-shared-store.conf",
                    ".local/bin/kache")}
                modes = {p: (self.f.home / p).stat().st_mode for p in before}
                calls = len(self.f.calls())
                state = self.f.sync("--host", host, "--timer")
                self.assertFalse(any(i["result"] == "changed" for i in state["items"]), state["items"])
                self.assertNotIn("kache.service", state["managed_units"])
                self.assertNotIn(".config/kache/config.toml", state["managed_files"])
                self.assertNotIn(".config/systemd/user/kache.service", state["managed_files"])
                for path, data in before.items():
                    self.assertEqual((self.f.home / path).read_bytes(), data, path)
                    self.assertEqual((self.f.home / path).stat().st_mode, modes[path])
                self.assertFalse(any(row[1] in ("enable", "disable", "start", "stop", "restart", "daemon-reload") for row in self.f.calls()[calls:]))
                self.assertFalse(any("kache.service" in row for row in self.f.calls()[calls:]))
                self.assertFalse((self.f.home / "downloads.json").exists())

    def test_normal_empty_home_never_creates_kache_config_unit_or_cache(self):
        (self.f.bin / "kache").unlink()
        state = self.f.component_sync("render", "units", "versions", timer=True)
        for path in (".config/kache", ".cache/kache", ".local/bin/kache", ".config/systemd/user/kache.service"):
            self.assertFalse((self.f.home / path).exists(), path)
        self.assertTrue(any(i["item"] == ".config/systemd/user/kache.service" and i["result"] == "warn" for i in state["items"]))
        self.assertNotIn("kache.service", state["managed_units"])

    def test_explicit_provision_will_not_replace_an_existing_wrong_version(self):
        self.runner.d.versions = {"kache": self.module.Declarations(self.f.source, self.f.home).versions["kache"]}
        fixture.put(self.f.bin / "kache", "#!/bin/bash\necho kache 0.0.1\n", True)
        before = (self.f.bin / "kache").read_bytes()
        with patch.object(self.runner, "install_pin", side_effect=AssertionError("existing kache was installed")):
            self.runner.provision()
        self.assertEqual((self.f.bin / "kache").read_bytes(), before)
        self.assertFalse(self.runner.kache_bootstrapped)
        self.assertFalse((self.f.home / ".config/kache").exists())
        self.assertFalse((self.f.home / ".config/systemd/user/kache.service").exists())
        self.assertIn("left to ops", self.h.results()[-1]["reason"])

    def test_lost_binary_with_existing_cache_is_not_treated_as_a_fresh_machine(self):
        (self.f.bin / "kache").unlink()
        fixture.put(self.f.home / ".cache/kache/store/retain", "private fixture cache")
        self.runner.d.versions = {"kache": self.module.Declarations(self.f.source, self.f.home).versions["kache"]}
        with patch.object(self.runner, "install_pin", side_effect=AssertionError("cache takeover")):
            self.runner.provision()
        self.assertFalse(self.runner.kache_bootstrapped)
        self.assertEqual((self.f.home / ".cache/kache/store/retain").read_text(), "private fixture cache")
        self.assertFalse((self.f.home / ".local/bin/kache").exists())

    def test_readonly_unit_already_in_a_journal_is_not_disabled_removed_or_queried(self):
        self.f.deployed()
        self.module, self.runner = self.f.runner()
        fixture.put(self.f.home / ".config/systemd/user/kache.service", "# ops-owned different unit\n")
        self.runner.unit_owned.add("kache.service")
        calls = len(self.f.calls())
        self.runner.units()
        self.assertIn("kache.service", self.runner.unit_owned)
        self.assertEqual((self.f.home / ".config/systemd/user/kache.service").read_text(), "# ops-owned different unit\n")
        self.assertFalse(any("kache.service" in row for row in self.f.calls()[calls:]))

    def test_preview_and_check_kache_differences_warn_without_writing(self):
        self.f.deployed()
        fixture.put(self.f.home / ".config/kache/config.toml", "# ops-owned config\n")
        fixture.put(self.f.home / ".config/systemd/user/kache.service", "# ops-owned unit\n")
        before = self.f.snapshot(exclude_mirror=True)
        result = self.f.process("python3", "-I", "-B", self.f.source / "tools/fleet-sync",
                                "--host", "hel8", "--preview", self.f.directory / "preview")
        self.assertNotIn("changed", result.stdout)
        self.assertIn("warn", result.stdout)
        self.assertNotIn("+++ ", result.stdout)
        state = self.f.inspect_sync("--check")
        self.assertTrue(any(i["item"] == ".config/kache/config.toml" and i["result"] == "warn" for i in state["items"]))
        self.assertTrue(any(i["item"] == ".config/systemd/user/kache.service" and i["result"] == "warn" for i in state["items"]))
        self.assertEqual(before, self.f.snapshot(exclude_mirror=True))

    def test_store_env_is_not_even_statted_by_rendering(self):
        fixture.put(self.f.home / ".config/kache/store.env", "private fixture")
        original = self.module.os.stat
        def forbid(path, *args, **kwargs):
            self.assertNotEqual(str(path), "store.env")
            self.assertFalse(str(path).endswith("/store.env"))
            return original(path, *args, **kwargs)
        with patch.object(self.module.os, "stat", side_effect=forbid):
            self.runner.kache_config()
        self.assertFalse((self.f.home / ".config/kache/config.toml").exists())

    def test_hel8_chromium_is_version_only_warning_without_tree_hashing(self):
        pin = self.module.Declarations(self.f.source, self.f.home).versions["chromium"]
        self.runner.d.versions = {"chromium": pin}
        self.runner.name = "hel8"
        fixture.put(self.f.bin / "chromium", "#!/bin/bash\necho Chromium 147.0.7727.101\n", True)
        with patch.object(self.runner, "seed_matches", side_effect=AssertionError("normal tree hashing")):
            self.runner.versions()
        row = next(i for i in self.runner.state["items"] if i["item"] == "version:chromium")
        self.assertEqual(row["result"], "warn")
        self.assertIn("version-only", row["reason"])

    def test_canonical_chromium_is_h3_and_hel8_is_not_an_eligible_seed(self):
        pin = self.module.Declarations(self.f.source, self.f.home).versions["chromium"]
        self.assertEqual(pin["install"]["seed_hosts"], ["hetzner3"])
        self.assertEqual(pin["install"]["manifest"], "seeds/chromium.sha256")
        self.assertNotIn("disagreement", pin["install"])
        entries = self.module.seed_entries(self.f.source, pin["install"])
        self.assertEqual(entries["bin/chromium"]["sha256"], "bd85bf00571aeda9573b75107beb07e1be4fd926068755251058a737e465f7bc")
        self.assertFalse((self.f.source / "fleet/seeds/chromium-hel8.sha256").exists())
        self.runner.d.versions = {"chromium": pin}
        self.runner.name = "hetzner3"  # Cannot seed from self or fall back to hel8.
        with patch.object(self.runner, "cmd", side_effect=AssertionError("unauthorized seed")):
            self.runner.provision()
        self.assertEqual(self.h.results()[-1]["result"], "failed")
        self.assertIn("no other seed hosts", self.h.results()[-1]["reason"])


if __name__ == "__main__":
    unittest.main()
