"""Peer seeding: fake SSH exports tar from temporary peer HOMEs, never the fleet."""

import hashlib
import io
import json
import os
from pathlib import Path
import shlex
import stat
import subprocess
import sys
import tarfile
import unittest

import test_bootstrap as bootstrap
import test_fleet_sync as fixture


SSH = r'''#!/usr/bin/env python3
import json, os, pathlib, shlex, shutil, subprocess, sys
home = pathlib.Path.home()
log = home / "seed-ssh.json"
rows = json.loads(log.read_text()) if log.exists() else []
rows.append(sys.argv[1:])
sibling = log.with_suffix(".new")
sibling.write_text(json.dumps(rows))
sibling.replace(log)
if os.environ.get("FAKE_SEED_ARCHIVE"):
    with open(os.environ["FAKE_SEED_ARCHIVE"], "rb") as source:
        shutil.copyfileobj(source, sys.stdout.buffer)
    sys.exit(0)
peer = json.loads(os.environ["FAKE_SEED_PEERS"])[sys.argv[-2]]
result = subprocess.run(shlex.split(sys.argv[-1]), env={**os.environ, "HOME": peer}, timeout=20)
sys.exit(result.returncode)
'''


def manifest(root):
    lines = []
    def walk(path, relative):
        mode = stat.S_IMODE(path.lstat().st_mode)
        if path.is_symlink():
            lines.append(f"symlink {mode:04o}  " + json.dumps([relative, os.readlink(path)]))
        elif path.is_dir():
            lines.append(f"directory {mode:04o}  {relative}")
            for child in sorted(path.iterdir()):
                walk(child, child.relative_to(root).as_posix())
        else:
            lines.append(hashlib.sha256(path.read_bytes()).hexdigest() + "  " + relative)
            lines.append(f"mode {mode:04o}  {relative}")
    walk(root, ".")
    return "\n".join(lines) + "\n"


class PeerSeedTest(unittest.TestCase):
    def setUp(self):
        self.h = bootstrap.ProvisionTest(methodName="runTest")
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)
        self.f, self.runner, self.module = self.h.f, self.h.runner, self.h.module
        self.runner.name = self.h.host
        self.primary, self.alternative = "seed-a", "seed-b"
        hosts = self.f.source / "fleet/hosts.toml"
        # Transfer fixtures do not depend on the live roster or its seed policy.
        fixture.put(hosts, hosts.read_text() + "".join(
            f'\n[hosts.{name}]\nseed = true\nhostname = "{name}"\nssh = "free@{name}.invalid"\nroles = ["fixture"]\nmachine_env = {{}}\nenv = {{}}\n'
            for name in (self.primary, self.alternative)))
        self.runner.d.hosts = self.module.Declarations(self.f.source, self.f.home).hosts
        self.peers = {}
        for name in (self.primary, self.alternative):
            home = self.f.directory / ("peer-" + name)
            home.mkdir()
            self.peers[name] = home
        os.environ["FAKE_SEED_PEERS"] = json.dumps({self.runner.d.hosts[n]["ssh"]: str(p) for n, p in self.peers.items()})
        fixture.put(self.f.bin / "ssh", SSH, True)

    def file_pin(self, name="forgejo", version="17.0.0", mode=0o755):
        relative = self.module.seed_location(name, version)
        source = self.peers[self.primary] / relative
        fixture.put(source, f"#!/bin/bash\necho '{version}'\n", True)
        source.chmod(mode)
        pin = dict(version=version, command=[name, "--version"], install=dict(
            kind="binary", seed="peer", seed_hosts=[self.primary, self.alternative],
            source=relative, destination=relative,
            sha256=hashlib.sha256(source.read_bytes()).hexdigest(), mode=f"{mode:04o}"))
        self.runner.d.versions = {name: pin}
        return source, pin

    def tree_pin(self, name="chromium", version="147.0.7727.101"):
        relative = self.module.seed_location(name, version)
        source = self.peers[self.primary] / relative
        source.mkdir(parents=True)
        if name == "chromium":
            entrypoint = "usr/lib/chromium/chromium"
            fixture.put(source / entrypoint, f"#!/bin/bash\necho Chromium {version}\n", True)
            fixture.put(source / "bin/chromium", "launcher bytes", True)
            (source / "empty").mkdir(mode=0o750)
            (source / "empty").chmod(0o750)
            (source / "shortcut").symlink_to(entrypoint)
            kind = "opt-tar"
        else:
            entrypoint = "bin/codex"
            fixture.put(source / entrypoint, f"#!/bin/bash\necho codex-cli {version}\n", True)
            fixture.put(source / "bin/codex-code-mode-host", "code mode host", True)
            fixture.put(source / "codex-resources/example", "resource bytes")
            fixture.put(source / "codex-path/rg", "ripgrep", True)
            fixture.put(source / "codex-package.json", json.dumps(dict(version=version)))
            (source / "codex").symlink_to("bin/codex")
            kind = "codex-package"
        text = manifest(source)
        fixture.put(self.f.source / f"fleet/seeds/{name}.sha256", text)
        pin = dict(version=version, command=[name, "--version"], install=dict(
            kind=kind, seed="peer", seed_hosts=[self.primary, self.alternative],
            source=relative, release=relative,
            manifest=f"seeds/{name}.sha256", entrypoint=entrypoint))
        self.runner.d.versions = {name: pin}
        return source, pin

    def result(self):
        return self.h.results()[-1]

    def calls(self):
        path = self.f.home / "seed-ssh.json"
        return json.loads(path.read_text()) if path.exists() else []

    def test_seed_manifest_rejects_escape(self):
        text = "directory 0755  .\n" + "0" * 64 + "  ../auth.json\nmode 0600  ../auth.json\n"
        with self.assertRaises(ValueError):
            self.module.parse_seed_manifest(text)

    def test_seed_destination_refuses_credentials(self):
        _, pin = self.file_pin()
        install = {**pin["install"], "source": ".codex/auth.json", "destination": ".codex/auth.json"}
        with self.assertRaises(ValueError):
            self.module.validate_install("forgejo", install, "17.0.0")

    def test_file_transfer_links_mode_and_already_matching_noop(self):
        source, pin = self.file_pin(mode=0o775)
        self.runner.provision()
        self.assertEqual(self.result()["result"], "changed", self.result())
        target = self.f.home / pin["install"]["destination"]
        self.assertEqual(target.read_bytes(), source.read_bytes())
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o775)
        self.assertEqual((self.f.home / ".local/bin/forgejo").resolve(), target)
        self.assertIn("StrictHostKeyChecking=yes", self.calls()[0])
        before = self.f.snapshot()
        self.runner.provision()
        self.assertEqual(self.result()["result"], "ok")
        self.assertEqual(before, self.f.snapshot())
        self.assertEqual(len(self.calls()), 1)


    def test_matching_content_missing_link_repairs_without_transfer(self):
        _, pin = self.file_pin()
        self.runner.provision()
        (self.f.home / ".local/bin/forgejo").unlink()
        calls = len(self.calls())
        inode = (self.f.home / pin["install"]["destination"]).stat().st_ino
        self.runner.provision()
        self.assertEqual(self.result()["result"], "changed")
        self.assertEqual(len(self.calls()), calls)
        self.assertEqual((self.f.home / pin["install"]["destination"]).stat().st_ino, inode)

    def test_matching_version_with_wrong_content_is_replaced_without_execution(self):
        _, pin = self.file_pin()
        target = self.f.home / pin["install"]["destination"]
        fixture.put(target, '#!/bin/bash\ntouch "$HOME/EXECUTED"\necho 17.0.0\n', True)
        self.runner.provision()
        self.assertEqual(self.result()["result"], "changed", self.result())
        self.assertFalse((self.f.home / "EXECUTED").exists())

    def test_mismatched_peer_content_is_refused_before_execution_or_install(self):
        source, pin = self.file_pin()
        fixture.put(source, '#!/bin/bash\ntouch "$HOME/EXECUTED"\necho 17.0.0\n', True)
        target = self.f.home / pin["install"]["destination"]
        fixture.put(target, "old bytes", True)
        self.runner.provision()
        self.assertEqual(self.result()["result"], "failed")
        self.assertIn("SHA256 mismatch", self.result()["reason"])
        self.assertEqual(target.read_text(), "old bytes")
        self.assertFalse((self.f.home / "EXECUTED").exists())
        self.assertFalse((self.f.home / ".local/bin/forgejo").exists())

    def test_tree_transfer_preserves_every_file_empty_directory_symlink_and_mode(self):
        source, pin = self.tree_pin()
        self.runner.provision()
        self.assertEqual(self.result()["result"], "changed", self.result())
        target = self.f.home / pin["install"]["release"]
        self.assertEqual(manifest(target), manifest(source))
        self.assertTrue((target / "shortcut").is_symlink())
        self.assertEqual(stat.S_IMODE((target / "empty").stat().st_mode), 0o750)
        before = self.f.snapshot()
        self.runner.provision()
        self.assertEqual(before, self.f.snapshot())

    def test_tree_same_version_modified_resource_is_repaired(self):
        source, pin = self.tree_pin()
        self.runner.provision()
        target = self.f.home / pin["install"]["release"]
        fixture.put(target / "bin/chromium", "broken launcher", True)
        self.runner.provision()
        self.assertEqual(self.result()["result"], "changed", self.result())
        self.assertEqual(manifest(target), manifest(source))

    def test_codex_full_package_current_and_command_links_without_auth_or_state(self):
        source, pin = self.tree_pin("codex", "0.162.1")
        # No auth directory is part of either source manifest or transfer.
        fixture.put(self.peers[self.primary] / ".codex/auth.json", "never copy this")
        fixture.put(self.peers[self.primary] / ".codex/state.json", "never copy this either")
        self.runner.provision()
        self.assertEqual(self.result()["result"], "changed", self.result())
        current = self.f.home / ".codex/packages/standalone/current"
        self.assertEqual(current.resolve(), self.f.home / pin["install"]["release"])
        self.assertEqual(manifest(current.resolve()), manifest(source))
        self.assertTrue((current / "codex").is_symlink())
        self.assertFalse((self.f.home / ".codex/auth.json").exists())
        self.assertFalse((self.f.home / ".codex/state.json").exists())

    def test_partial_tree_archive_is_refused_and_old_tree_remains(self):
        _, pin = self.tree_pin()
        archive = self.f.directory / "partial.tar"
        with tarfile.open(archive, "w") as tar:
            info = tarfile.TarInfo(".")
            info.type, info.mode = tarfile.DIRTYPE, self.module.seed_entries(self.f.source, pin["install"])["."]["mode"]
            tar.addfile(info)
        os.environ["FAKE_SEED_ARCHIVE"] = str(archive)
        target = self.f.home / pin["install"]["release"]
        fixture.put(target / "old", "previous tree")
        self.runner.provision()
        self.assertEqual(self.result()["result"], "failed")
        self.assertIn("partial seed tree", self.result()["reason"])
        self.assertEqual(list(target.iterdir()), [target / "old"])
        self.assertEqual((target / "old").read_text(), "previous tree")

    def test_changed_tree_file_checksum_is_refused_before_promotion(self):
        source, pin = self.tree_pin()
        fixture.put(source / "bin/chromium", "corrupt bytes", True)
        self.runner.provision()
        self.assertEqual(self.result()["result"], "failed")
        self.assertIn("SHA256 mismatch", self.result()["reason"])
        self.assertFalse((self.f.home / pin["install"]["release"]).exists())


    def test_peer_source_symlink_cannot_escape_artifact_allowlist(self):
        source, _ = self.file_pin()
        outside = self.peers[self.primary] / ".ssh/never-read"
        fixture.put(outside, "private fixture bytes")
        source.unlink()
        source.symlink_to(outside)
        self.runner.provision()
        self.assertEqual(self.result()["result"], "failed")
        self.assertIn("artifact type changed", self.result()["reason"])

    def test_upstream_raw_file_url_uses_exact_same_content_pin(self):
        source, pin = self.file_pin()
        url, digest = self.h.download(source)
        self.assertEqual(digest, pin["install"]["sha256"])
        pin["install"]["url"] = url
        self.runner.provision()
        self.assertEqual(self.result()["result"], "changed", self.result())
        self.assertFalse(self.calls())

    def test_upstream_tree_tar_requires_archive_sha256_and_the_full_manifest(self):
        source, pin = self.tree_pin()
        archive = self.f.directory / "approved-tree.tar"
        with tarfile.open(archive, "w", dereference=False) as tar:
            tar.add(source, arcname=".")
        url, digest = self.h.download(archive)
        pin["install"].update(url=url, sha256=digest)
        self.module.validate_install("chromium", pin["install"], pin["version"])
        self.runner.provision()
        self.assertEqual(self.result()["result"], "changed", self.result())
        self.assertEqual(manifest(self.f.home / pin["install"]["release"]), manifest(source))
        self.assertFalse(self.calls())

    def test_disagreement_is_reported_without_selecting_or_transferring_a_peer(self):
        _, pin = self.tree_pin()
        pin["install"]["disagreement"] = "observed seed-a/seed-b launcher disagreement"
        self.runner.provision()
        self.assertEqual(self.result()["result"], "warn")
        self.assertIn("peer disagreement", self.result()["reason"])
        self.assertFalse(self.calls())
        self.assertFalse((self.f.home / pin["install"]["release"]).exists())

    def test_unlisted_peer_state_is_not_opened_or_transferred(self):
        source, pin = self.tree_pin()
        # A FIFO would hang a recursive tar/hash scan; it is not in the pin list.
        os.mkfifo(source / "auth-state-not-an-artifact")
        self.runner.provision()
        self.assertEqual(self.result()["result"], "changed", self.result())
        target = self.f.home / pin["install"]["release"]
        self.assertFalse((target / "auth-state-not-an-artifact").exists())

    def test_seed_file_provision_survives_full_release_handoff(self):
        self.f.sha = self.f.publish()
        _, pin = self.file_pin()
        # Keep kache available for explicit activation, and one real seeded item.
        import tomllib
        current = tomllib.loads((self.f.source / "fleet/versions.toml").read_text())
        rows = []
        for name, item in (("kache", current["kache"]), ("forgejo", pin)):
            rows += [f"[{name}]", f"version = {json.dumps(item['version'])}",
                     f"command = {json.dumps(item['command'])}", f"[{name}.install]"]
            rows += [f"{key} = {json.dumps(value)}" for key, value in item["install"].items()]
        fixture.put(self.f.source / "fleet/versions.toml", "\n".join(rows) + "\n")
        self.f.publish()
        self.f.env["FAKE_SEED_PEERS"] = os.environ["FAKE_SEED_PEERS"]
        state = self.f.sync("--provision", "--host", self.h.host)
        item = next(row for row in state["items"] if row["item"] == "provision:forgejo")
        self.assertEqual(item["result"], "changed", item)
        calls = len(self.calls())
        state = self.f.component_sync("provision", host=self.h.host)
        item = next(row for row in state["items"] if row["item"] == "provision:forgejo")
        self.assertEqual(item["result"], "ok", item)
        self.assertEqual(len(self.calls()), calls)


    def test_alternative_seed_is_used_only_when_it_matches_the_same_pin(self):
        source, pin = self.file_pin()
        alternative = self.peers[self.alternative] / pin["install"]["source"]
        fixture.put(alternative, source.read_text(), True)
        source.unlink()
        self.runner.provision()
        self.assertEqual(self.result()["result"], "changed", self.result())
        self.assertIn(f"from {self.alternative}", self.result()["reason"])
        self.assertEqual([call[-2] for call in self.calls()],
                         [self.runner.d.hosts[name]["ssh"] for name in (self.primary, self.alternative)])


if __name__ == "__main__":
    unittest.main()
