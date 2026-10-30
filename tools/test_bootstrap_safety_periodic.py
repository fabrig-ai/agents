"""All-host historical/ops compatibility, run every two hours."""
from test_bootstrap_safety import *


class PeriodicBootstrapSafetyTest(BootstrapSafetyTest):
    def test_live_roles_timer_leaves_ops_kache_bytes_modes_links_and_ownership_unchanged(self):
        self.f.sha = self.f.publish()
        for host in tomllib.loads((self.f.source / "fleet/hosts.toml").read_text())["hosts"]:
            with self.subTest(host=host):
                self.f.sync("--host", host)
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


def load_tests(loader, tests, pattern):
    return unittest.TestSuite([PeriodicBootstrapSafetyTest("test_live_roles_timer_leaves_ops_kache_bytes_modes_links_and_ownership_unchanged")])
