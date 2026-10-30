"""All-host historical/ops compatibility, run every two hours."""
from test_bootstrap_stages import *


class PeriodicBootstrapStagesTest(BootstrapStagesTest):
    @unittest.skipUnless(HAS_BOOTSTRAP, "stage B declarations are not in the code-only stage")
    def test_stage_a_timer_promotes_real_stage_b_on_declared_hosts(self):
        for host in self.hosts:
            with self.subTest(host=host):
                self.simulate(host, self.script(STAGE_A), after_fleet=True)

    def test_main_version_only_kache_never_renders_or_enters_preview(self):
        self.legacy_fleet()
        if self.f.git(self.f.source, "status", "--porcelain"):
            self.f.publish()
        self.f.sync()
        with patch.dict("os.environ", self.f.env, clear=True):
            _, runner = self.f.runner()
            with patch.object(runner, "kache_config", side_effect=AssertionError("inactive kache renderer")):
                runner.render()
        self.assertFalse((self.f.home / ".config/kache").exists())
        preview = self.f.directory / "main-preview"
        self.f.process("python3", "-I", "-B", self.f.source / "tools/fleet-sync", "--preview", preview, "--host", "hel8")
        self.assertFalse((preview / "home/.config/kache").exists())


def load_tests(loader, tests, pattern):
    cls = PeriodicBootstrapStagesTest
    return unittest.TestSuite(cls(name) for name in cls.__dict__ if name.startswith("test_"))
