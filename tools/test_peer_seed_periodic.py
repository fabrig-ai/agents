"""Exhaustive process/compatibility sweeps; run in the periodic tier."""

from test_peer_seed import *


class PeriodicPeerSeedTest(PeerSeedTest):
    def test_all_single_file_locations_including_claude_are_allowlisted(self):
        for name, version in (("cargo-nextest", "0.9.148"), ("claude", "2.1.312"), ("forgejo-runner", "13.2.0")):
            with self.subTest(name=name):
                source, pin = self.file_pin(name, version)
                self.module.validate_install(name, pin["install"], version)
                self.runner.provision()
                self.assertEqual(self.result()["result"], "changed", self.result())
                self.assertEqual((self.f.home / pin["install"]["destination"]).read_bytes(), source.read_bytes())
        self.assertTrue((self.f.home / ".local/bin/claude").is_symlink())
        self.assertFalse((self.f.home / ".claude").exists())
        self.assertFalse((self.f.home / ".claude.json").exists())

    def test_peer_cannot_send_unlisted_files_or_replace_mode_or_symlink(self):
        _, pin = self.tree_pin()
        entries = self.module.seed_entries(self.f.source, pin["install"])
        for kind in ("extra", "mode", "link", "hardlink", "duplicate"):
            with self.subTest(kind=kind):
                archive = self.f.directory / "unsafe.tar"
                with tarfile.open(archive, "w") as tar:
                    root = tarfile.TarInfo(".")
                    root.type, root.mode = tarfile.DIRTYPE, entries["."]["mode"]
                    tar.addfile(root)
                    if kind == "extra":
                        item = tarfile.TarInfo("../escape")
                    elif kind == "duplicate":
                        item = root
                    elif kind in ("link", "hardlink"):
                        item = tarfile.TarInfo("shortcut")
                        item.type = tarfile.SYMTYPE if kind == "link" else tarfile.LNKTYPE
                        item.mode, item.linkname = 0o777, "../../auth.json"
                    else:
                        item = tarfile.TarInfo("bin/chromium")
                        item.mode = 0o4755
                    tar.addfile(item)
                os.environ["FAKE_SEED_ARCHIVE"] = str(archive)
                self.runner.provision()
                self.assertEqual(self.result()["result"], "failed")
                self.assertFalse((self.f.home / pin["install"]["release"]).exists())

    def test_manifest_rejects_escape_missing_modes_and_symlink_parents(self):
        bad = (
            "directory 0755  .\n" + "0" * 64 + "  ../auth.json\nmode 0600  ../auth.json\n",
            "directory 0755  .\n" + "0" * 64 + "  payload\n",
            'directory 0755  .\nsymlink 0777  ["bin", "../../auth"]\n',
            'directory 0755  .\nsymlink 0777  ["bin", "other"]\n' + "0" * 64 + "  bin/payload\nmode 0755  bin/payload\n",
        )
        for text in bad:
            with self.subTest(text=text), self.assertRaises(ValueError):
                self.module.parse_seed_manifest(text)

    def test_seed_cannot_name_credentials_or_arbitrary_home_paths(self):
        _, pin = self.file_pin()
        for path in (".codex/auth.json", ".claude/.credentials.json", "src/rust/tmp/logins", ".ssh/id_ed25519"):
            install = {**pin["install"], "source": path, "destination": path}
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.module.validate_install("forgejo", install, "17.0.0")


def load_tests(loader, tests, pattern):
    cls = PeriodicPeerSeedTest
    return unittest.TestSuite(cls(name) for name in cls.__dict__ if name.startswith("test_"))
