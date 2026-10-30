"""Exhaustive process/compatibility sweeps; run in the periodic tier."""

from test_bootstrap import *


class PeriodicProvisionTest(ProvisionTest):
    def test_archive_traversal_and_symlinks_are_refused(self):
        for member in ("../escape", "/tmp/escape", "link"):
            with self.subTest(member=member):
                archive = self.archive("unsafe.tgz", {member: "#!/bin/bash\necho 1.2.3\n"})
                if member == "link":
                    with tarfile.open(archive, "w:gz") as tar:
                        info = tarfile.TarInfo("link")
                        info.type, info.linkname = tarfile.SYMTYPE, "/etc/passwd"
                        tar.addfile(info)
                self.pin("unsafe", "1.2.3", "tar", archive, member=member, destination=".local/bin/unsafe")
                self.runner.provision()
                self.assertEqual(self.results()[-1]["result"], "failed")
                self.assertIn("unsafe provision archive", self.results()[-1]["reason"])
        self.assertFalse((self.f.home / ".local/bin/unsafe").exists())


    def test_user_script_repeated_with_temporary_home_and_fake_services(self):
        self.only_toolchain_and_cache_pins()
        rust = self.module.Declarations(self.f.source, self.f.home).versions["rustc"]["install"]
        outputs = {
            "show active-toolchain": "1.95.0-x86_64-unknown-linux-gnu (default)",
            "toolchain list": "1.95.0-x86_64-unknown-linux-gnu\nnightly-2026-10-21-x86_64-unknown-linux-gnu",
            "component list --installed --toolchain 1.95.0": "\n".join(c + "-x86_64-unknown-linux-gnu" for c in rust["components"]),
            "target list --installed --toolchain 1.95.0": "\n".join(rust["targets"]),
        }
        fixture.put(self.f.bin / "rustup", "#!/usr/bin/env python3\nimport sys\n"
                    f"print({outputs!r}.get(' '.join(sys.argv[1:]), ''))\n", True)
        spec = importlib.util.spec_from_file_location("bootstrap_fixture", self.f.source / "fleet/bootstrap/bootstrap.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        bootstrap = module.Bootstrap(argparse.Namespace(dry_run=False, host=self.host))
        def run(*argv, capture=False):
            return self.f.process(*argv).stdout
        # Exercise actual cloning, validation, directory creation and both fleet
        # invocations. Only account identity and external services are simulated.
        state = self.f.home / "src/rust/tmp/codex-run/retain"
        fixture.put(state, "retained runtime evidence")
        with patch.object(module.os, "geteuid", return_value=1000), \
             patch.object(module.pwd, "getpwuid", return_value=argparse.Namespace(pw_name="free")), \
             patch.object(bootstrap, "run", side_effect=run), contextlib.redirect_stdout(io.StringIO()):
            bootstrap.user()
            agents = self.f.home / "src/fabrig/agents"
            first_head = self.f.git(agents, "rev-parse", "HEAD")
            call_count = len(self.f.calls())
            bootstrap.user()
        self.assertEqual(self.f.git(agents, "rev-parse", "HEAD"), first_head)
        self.assertEqual(state.read_text(), "retained runtime evidence")
        self.assertEqual(self.f.git(agents, "status", "--porcelain"), "")
        self.assertFalse(any(row[1] in ("enable", "daemon-reload", "start", "restart") for row in self.f.calls()[call_count:]))
        self.assertFalse((self.f.home / "downloads.json").exists())

    def test_explicit_provision_survives_release_handoff_and_is_idempotent(self):
        self.f.sha = self.f.publish()
        self.only_toolchain_and_cache_pins()
        rust = self.module.Declarations(self.f.source, self.f.home).versions["rustc"]["install"]
        outputs = {
            "show active-toolchain": "1.95.0-x86_64-unknown-linux-gnu (default)",
            "toolchain list": "1.95.0-x86_64-unknown-linux-gnu\nnightly-2026-10-21-x86_64-unknown-linux-gnu",
            "component list --installed --toolchain 1.95.0": "\n".join(c + "-x86_64-unknown-linux-gnu" for c in rust["components"]),
            "target list --installed --toolchain 1.95.0": "\n".join(rust["targets"]),
        }
        fixture.put(self.f.bin / "rustup", "#!/usr/bin/env python3\nimport sys\n"
                    f"print({outputs!r}[' '.join(sys.argv[1:])])\n", True)
        state = self.f.sync("--provision", "--host", self.host)
        rows = [row for row in state["items"] if row["item"].startswith("provision:")]
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row["result"] == "ok" for row in rows), rows)
        self.assertEqual(next(r for r in rows if r["item"] == "provision:kache")["result"], "ok")
        self.assertFalse((self.f.home / ".config/systemd/user/default.target.wants/kache.service").exists())
        self.assertFalse((self.f.home / ".config/kache/config.toml").exists())
        count = len(self.f.calls())
        self.f.sync("--provision", "--host", self.host)
        self.assertFalse(any(row[1] in ("enable", "daemon-reload", "start", "restart") for row in self.f.calls()[count:]))
        self.assertFalse((self.f.home / "downloads.json").exists())


def load_tests(loader, tests, pattern):
    cls = PeriodicProvisionTest
    return unittest.TestSuite(cls(name) for name in cls.__dict__ if name.startswith("test_"))
