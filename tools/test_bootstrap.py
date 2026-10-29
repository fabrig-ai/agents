"""Bootstrap/provision tests: disposable HOME, local origins, fake downloaders."""

import argparse
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import unittest
from unittest.mock import patch

import test_fleet_sync as fixture


CURL = r'''#!/usr/bin/env python3
import json, os, pathlib, shutil, sys
home = pathlib.Path.home()
record = home / "downloads.json"
rows = json.loads(record.read_text()) if record.exists() else []
rows.append(sys.argv[-1])
sibling = record.with_suffix(".new")
sibling.write_text(json.dumps(rows))
sibling.replace(record)
source = json.loads(os.environ["FAKE_DOWNLOADS"])[sys.argv[-1]]
shutil.copyfile(source, sys.argv[sys.argv.index("--output") + 1])
'''


class ProvisionTest(unittest.TestCase):
    def setUp(self):
        # Composition avoids running FleetTest's inherited tests twice.
        self.f = fixture.FleetTest(methodName="runTest")
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.environment = patch.dict(os.environ, self.f.env, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.module, self.runner = self.f.runner()
        self.runner.d.versions = {}
        fixture.put(self.f.bin / "curl", CURL, True)
        self.downloads = {}
        os.environ["FAKE_DOWNLOADS"] = "{}"

    def download(self, path):
        url = "https://fixture.invalid/" + path.name
        self.downloads[url] = str(path)
        os.environ["FAKE_DOWNLOADS"] = json.dumps(self.downloads)
        return url, hashlib.sha256(path.read_bytes()).hexdigest()

    def pin(self, name, version, kind, path, **options):
        url, digest = self.download(path)
        pin = dict(version=version, command=[name, "--version"],
                   install=dict(kind=kind, url=url, sha256=digest, **options))
        self.runner.d.versions[name] = pin
        # A deliberately old executable: the new per-user install must shadow it.
        fixture.put(self.f.bin / name, "#!/bin/bash\necho 'tool 0.0.1'\n", True)
        return pin

    def artifact(self, name, version):
        path = self.f.directory / name
        fixture.put(path, f"#!/bin/bash\necho '{version}'\n", True)
        return path

    def archive(self, name, files):
        archive = self.f.directory / name
        with tarfile.open(archive, "w:gz") as tar:
            for path, content in files.items():
                info = tarfile.TarInfo(path)
                data = content.encode()
                info.size, info.mode = len(data), 0o755
                tar.addfile(info, io.BytesIO(data))
        return archive

    def results(self):
        return [row for row in self.runner.state["items"] if row["item"].startswith("provision:")]

    def test_tar_install_version_change_and_second_run_no_download(self):
        archive = self.archive("nextest.tgz", {"cargo-nextest": "#!/bin/bash\necho cargo-nextest 0.9.148\n"})
        self.pin("cargo-nextest", "0.9.148", "tar", archive,
                 member="cargo-nextest", destination=".cargo/bin/cargo-nextest")
        target = self.f.home / ".cargo/bin/cargo-nextest"
        fixture.put(target, "#!/bin/bash\necho 0.0.1\n", True)
        old_inode = target.stat().st_ino
        self.runner.provision()
        self.assertEqual(self.results()[-1]["result"], "changed", self.results())
        self.assertNotEqual(old_inode, target.stat().st_ino)
        before = self.f.snapshot()
        self.runner.provision()
        self.assertEqual(self.results()[-1]["result"], "ok")
        self.assertEqual(before, self.f.snapshot())
        self.assertEqual(len(json.loads((self.f.home / "downloads.json").read_text())), 1)

    def test_checksum_failure_preserves_installed_binary_and_other_items_continue(self):
        path = self.artifact("new-forgejo", "17.0.0")
        pin = self.pin("forgejo", "17.0.0", "binary", path,
                       destination=".local/opt/forgejo-17.0.0/forgejo")
        pin["install"]["sha256"] = "0" * 64
        destination = self.f.home / pin["install"]["destination"]
        fixture.put(destination, "previous bytes", True)
        self.runner.d.versions["manual"] = dict(version="1.2.3", command=["missing", "--version"])
        self.runner.provision()
        self.assertEqual(destination.read_text(), "previous bytes")
        self.assertEqual([r["result"] for r in self.results()], ["failed", "warn"])
        self.assertIn("SHA256 mismatch", self.results()[0]["reason"])

    def test_wrong_download_version_is_not_installed(self):
        path = self.artifact("bad-version", "forgejo 0.1.2")
        self.pin("forgejo", "17.0.0", "binary", path,
                 destination=".local/opt/forgejo-17.0.0/forgejo")
        self.runner.provision()
        self.assertEqual(self.results()[-1]["result"], "failed")
        self.assertFalse((self.f.home / ".local/opt").exists())

    def test_manual_pin_warns_without_download(self):
        self.runner.d.versions["absent"] = dict(version="1.2.3", command=["absent", "--version"],
            install=dict(kind="tar", url="TODO-USER: versioned URL", sha256="TODO-USER: SHA256"))
        self.runner.provision()
        self.assertEqual(self.results()[-1]["result"], "warn")
        self.assertIn("manual: TODO-USER absent 1.2.3", self.results()[-1]["reason"])
        self.assertFalse((self.f.home / "downloads.json").exists())

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

    def test_binary_forgejo_build_metadata_and_opt_link(self):
        path = self.artifact("forgejo-bin", "forgejo version 17.0.0+gitea-1.22.0")
        self.pin("forgejo", "17.0.0", "binary", path,
                 destination=".local/opt/forgejo-17.0.0/forgejo")
        self.runner.provision()
        self.assertEqual(self.results()[-1]["result"], "changed", self.results())
        self.assertEqual((self.f.home / ".local/bin/forgejo").resolve(),
                         self.f.home / ".local/opt/forgejo-17.0.0/forgejo")

    def test_runner_v_prefix_is_accepted(self):
        path = self.artifact("forgejo-runner-bin", "forgejo-runner version v13.2.0")
        self.pin("forgejo-runner", "13.2.0", "binary", path,
                 destination=".local/opt/forgejo-runner-13.2.0/forgejo-runner")
        self.runner.provision()
        self.assertEqual(self.results()[-1]["result"], "changed", self.results())

    def test_chromium_four_part_version_and_bundle_launcher(self):
        archive = self.archive("browser.tgz", {
            "usr/lib/chromium/chromium": "#!/bin/bash\necho Chromium 147.0.7727.101\n",
            "bin/chromium": "#!/bin/bash\necho Chromium 147.0.7727.101\n"})
        self.pin("chromium", "147.0.7727.101", "opt-tar", archive,
                 release=".local/opt/chromium-147.0.7727.101", entrypoint="usr/lib/chromium/chromium")
        self.runner.provision()
        self.assertEqual(self.results()[-1]["result"], "changed", self.results())
        self.assertTrue((self.f.home / ".local/opt/chromium-147.0.7727.101/bin/chromium").is_file())
        self.assertTrue((self.f.home / ".local/bin/chromium").is_symlink())

    def test_codex_complete_standalone_package_and_current_link(self):
        archive = self.archive("codex.tgz", {
            "bin/codex": "#!/bin/bash\necho codex-cli 0.162.1\n",
            "bin/codex-code-mode-host": "host bytes",
            "codex-resources/example": "resource bytes", "codex-path/rg": "path resource",
            "codex-package.json": json.dumps(dict(version="0.162.1", entrypoint="bin/codex",
                target="x86_64-unknown-linux-musl", layoutVersion=1, variant="codex",
                resourcesDir="codex-resources", pathDir="codex-path"))})
        self.pin("codex", "0.162.1", "codex-package", archive,
                 release=".codex/packages/standalone/releases/0.162.1-x86_64-unknown-linux-musl", entrypoint="bin/codex")
        self.runner.provision()
        self.assertEqual(self.results()[-1]["result"], "changed", self.results())
        current = self.f.home / ".codex/packages/standalone/current"
        self.assertTrue(current.is_symlink())
        self.assertEqual((current / "codex-resources/example").read_text(), "resource bytes")
        before = self.f.snapshot()
        self.runner.provision()
        self.assertEqual(before, self.f.snapshot())

    def test_destination_parent_symlink_is_refused(self):
        outside = self.f.directory / "outside"
        outside.mkdir()
        (self.f.home / ".local").symlink_to(outside)
        path = self.artifact("runner", "13.2.0")
        self.pin("forgejo-runner", "13.2.0", "binary", path,
                 destination=".local/opt/forgejo-runner-13.2.0/forgejo-runner")
        self.runner.provision()
        self.assertEqual(self.results()[-1]["result"], "failed")
        self.assertEqual(list(outside.iterdir()), [])

    def test_rust_reconciles_missing_targets_even_with_matching_rustc(self):
        rust = dict(self.module.Declarations(self.f.source, self.f.home).versions["rustc"])
        self.runner.d.versions = {"rustc": rust}
        fixture.put(self.f.bin / "rustup", r'''#!/usr/bin/env python3
from pathlib import Path
import sys
ready = Path.home() / "rust.ready"
args = sys.argv[1:]
if args == ["show", "active-toolchain"]: print("1.95.0-x86_64-unknown-linux-gnu (default)")
elif args == ["toolchain", "list"]: print("1.95.0-x86_64-unknown-linux-gnu\nnightly-2026-10-21-x86_64-unknown-linux-gnu")
elif args[0] == "component": print("clippy-x86_64-unknown-linux-gnu\nrustfmt-x86_64-unknown-linux-gnu\nrust-docs-x86_64-unknown-linux-gnu")
elif args[0] == "target" and ready.exists(): print("x86_64-unknown-linux-gnu\nwasm32-unknown-unknown\naarch64-apple-darwin\nx86_64-unknown-linux-musl")
elif args[:2] == ["toolchain", "install"]:
    sibling = ready.with_suffix(".new")
    sibling.write_text("ready")
    sibling.replace(ready)
''', True)
        self.runner.provision()
        self.assertEqual(self.results()[-1]["result"], "changed", self.results())
        self.runner.provision()
        self.assertEqual(self.results()[-1]["result"], "ok", self.results())
        self.assertFalse((self.f.home / "downloads.json").exists())

    def test_claude_installer_is_checked_and_uses_staged_home(self):
        artifact = self.artifact("claude-payload", "2.1.312 (Claude Code)")
        url, digest = self.download(artifact)
        script = self.f.directory / "install.sh"
        fixture.put(script, '#!/bin/bash\nset -eu\nmkdir -p "$HOME/.local/share/claude/versions"\n'
                    'cp "$CLAUDE_FIXTURE" "$HOME/.local/share/claude/versions/$1"\n')
        os.environ["CLAUDE_FIXTURE"] = str(artifact)
        self.pin("claude", "2.1.312", "claude-script", script, payload_url=url, payload_sha256=digest)
        self.runner.provision()
        self.assertEqual(self.results()[-1]["result"], "changed", self.results())
        self.assertTrue((self.f.home / ".local/bin/claude").is_symlink())
        self.assertFalse((self.f.home / ".claude.json").exists())

    def test_kache_source_uses_exact_commit_patches_and_checked_musl(self):
        pin = self.module.Declarations(self.f.source, self.f.home).versions["kache"]
        self.runner.d.versions = {"kache": pin}
        fixture.put(self.f.bin / "kache", "#!/bin/bash\necho 0.0.1\n", True)
        archive = self.archive("musl.tgz", {"musl-1.2.5/README": "fixture"})
        pin["install"]["musl_url"], pin["install"]["musl_sha256"] = self.download(archive)
        rev = pin["install"]["rev"]
        fixture.put(self.f.bin / "git", f'''#!/usr/bin/env python3
from pathlib import Path
import json, sys
args = sys.argv[1:]
if args[0] == "init": Path(args[-1]).mkdir()
elif args[0] == "-C" and args[2] == "rev-parse": print({rev!r})
elif args[0] == "-C" and args[2] == "apply":
    log = Path.home() / "patches.json"
    rows = json.loads(log.read_text()) if log.exists() else []
    rows.append(args[3:])
    sibling = log.with_suffix(".new")
    sibling.write_text(json.dumps(rows))
    sibling.replace(log)
''', True)
        fixture.put(self.f.bin / "bash", r'''#!/usr/bin/env python3
from pathlib import Path
import sys
work = Path(sys.argv[-1])
(work / "out").mkdir()
sibling = work / "out/.kache.new"
sibling.write_text("#!/bin/bash\necho kache 1.2.2-gitrev.2\n")
sibling.chmod(0o755)
sibling.replace(work / "out/kache")
''', True)
        self.runner.provision()
        self.assertEqual(self.results()[-1]["result"], "changed", self.results())
        rows = json.loads((self.f.home / "patches.json").read_text())
        self.assertEqual([Path(r[-1]).name for r in rows],
                         ["git-checkout-rev.patch"] * 2 + ["upload-bound.patch"] * 2)
        self.assertFalse((self.f.home / "src/rust/tmp/heavy").exists())

    def test_kache_secret_metadata_only_and_host_specific_config(self):
        secret = self.f.home / ".config/kache/store.env"
        fixture.put(secret, "fixture secret contents never consumed")
        original = self.runner.safe.open_regular
        def forbid(directory, leaf, *args, **kwargs):
            self.assertNotEqual(leaf, "store.env", "credential contents were opened")
            return original(directory, leaf, *args, **kwargs)
        self.runner.name = "hetzner2"
        with patch.object(self.runner.safe, "open_regular", side_effect=forbid):
            self.runner.kache_config()
        config = (self.f.home / ".config/kache/config.toml").read_text()
        self.assertIn('local_max_size = "25GiB"', config)
        self.assertIn("69793218560", config)
        self.assertIn('[cache.remote]', config)
        self.assertNotIn("fixture secret", config)
        self.assertTrue((self.f.home / ".config/systemd/user/kache.service.d/20-shared-store.conf").is_file())

    def test_kache_fresh_home_needs_no_shared_credential(self):
        self.runner.name = "hetzner3"
        self.runner.kache_config()
        config = (self.f.home / ".config/kache/config.toml").read_text()
        self.assertIn('local_max_size = "40GiB"', config)
        self.assertIn("local_only = true", config)
        self.assertNotIn("[cache.remote]", config)
        self.assertFalse((self.f.home / ".config/kache/store.env").exists())
        before = self.f.snapshot()
        self.runner.kache_config()
        self.assertEqual(before, self.f.snapshot())

    def test_explicit_provision_survives_release_handoff_and_is_idempotent(self):
        rust = self.module.Declarations(self.f.source, self.f.home).versions["rustc"]["install"]
        outputs = {
            "show active-toolchain": "1.95.0-x86_64-unknown-linux-gnu (default)",
            "toolchain list": "1.95.0-x86_64-unknown-linux-gnu\nnightly-2026-10-21-x86_64-unknown-linux-gnu",
            "component list --installed --toolchain 1.95.0": "\n".join(c + "-x86_64-unknown-linux-gnu" for c in rust["components"]),
            "target list --installed --toolchain 1.95.0": "\n".join(rust["targets"]),
        }
        fixture.put(self.f.bin / "rustup", "#!/usr/bin/env python3\nimport sys\n"
                    f"print({outputs!r}[' '.join(sys.argv[1:])])\n", True)
        state = self.f.sync("--provision")
        rows = [row for row in state["items"] if row["item"].startswith("provision:")]
        self.assertEqual(len(rows), 8)
        self.assertEqual(sum(row["result"] == "warn" and "manual: TODO-USER" in row["reason"] for row in rows), 6)
        self.assertEqual(next(r for r in rows if r["item"] == "provision:kache")["result"], "ok")
        self.assertTrue((self.f.home / ".config/systemd/user/default.target.wants/kache.service").is_symlink())
        count = len(self.f.calls())
        self.f.sync("--provision")
        self.assertFalse(any(row[1] in ("enable", "daemon-reload", "start", "restart") for row in self.f.calls()[count:]))
        self.assertFalse((self.f.home / "downloads.json").exists())

    def test_user_script_repeated_with_temporary_home_and_fake_services(self):
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
        bootstrap = module.Bootstrap(argparse.Namespace(dry_run=False, host="hel8"))
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

    def test_timer_check_preview_status_reject_provision_before_writes(self):
        before = self.f.snapshot()
        for args in (("--timer",), ("--check",), ("--preview", str(self.f.directory / "preview")), ("status",)):
            result = self.f.process("python3", "-I", "-B", self.f.source / "tools/fleet-sync",
                                    "--provision", "--host", "hel8", *args, expected=2)
            self.assertIn("--provision accepts only", result.stderr)
        self.assertEqual(before, self.f.snapshot())

    def test_bad_install_declaration_is_rejected(self):
        for install in (dict(kind="binary", url="http://bad", sha256="0" * 64),
                        dict(kind="tar", url="https://fixture.invalid", sha256="missing"),
                        dict(kind="binary", url="https://fixture.invalid", sha256="0" * 64,
                             destination=".codex/auth.json")):
            with self.subTest(install=install), self.assertRaises(ValueError):
                self.module.validate_install("fake", install)

    def test_root_and_user_dry_runs_are_repeatable_and_write_nothing(self):
        before = self.f.snapshot()
        for name in ("root", "user"):
            script = self.f.source / f"fleet/bootstrap/{name}.sh"
            self.f.process("bash", "-n", script)
            first = self.f.process("bash", script, "--dry-run", "--host", "hetzner2")
            second = self.f.process("bash", script, "--dry-run", "--host", "hetzner2")
            self.assertEqual(first.stdout, second.stdout)
            self.assertIn("rustup" if name == "user" else "enable-linger", first.stdout)
        self.assertEqual(before, self.f.snapshot())
        self.f.process("bash", "-n", self.f.source / "fleet/kache/build")


if __name__ == "__main__":
    unittest.main()
