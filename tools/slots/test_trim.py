"""Trim policy against disposable files and a fake proc tree."""

import argparse
from contextlib import redirect_stdout
import importlib.machinery
import importlib.util
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


DIRECTORY = Path(__file__).resolve().parent
ROOT = DIRECTORY.parent.parent
LOADER = importlib.machinery.SourceFileLoader("trim", str(DIRECTORY / "trim"))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
trim = importlib.util.module_from_spec(SPEC)
LOADER.exec_module(trim)
CUTOFF = 10_000_000_000_000
OLD = CUTOFF - 1


class TrimTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=ROOT.parent, prefix=".trim-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.slot = self.root / "slot"
        self.deps = self.slot / "target/debug/deps"
        self.deps.mkdir(parents=True)

    def file(self, name, *, mode=0o700, modified=OLD):
        path = self.deps / name
        path.write_bytes(b"test executable\n")
        path.chmod(mode)
        os.utime(path, ns=(modified, modified))
        return path

    def test_only_old_user_executable_regular_files_are_deleted(self):
        removed = self.file("old-test")
        kept = [self.file(name) for name in ("lib.so", "lib.rlib", "lib.rmeta", "lib.d")]
        kept += [self.file("nonexec", mode=0o600), self.file("group-exec", mode=0o610),
                 self.file("at-cutoff", modified=CUTOFF), self.file("new", modified=CUTOFF + 1)]
        directory = self.deps / "directory"
        directory.mkdir()
        symlink = self.deps / "symlink"
        symlink.symlink_to(removed)
        self.assertEqual(trim.trim(self.slot, CUTOFF, held_files=lambda: (set(), 0)), (1, 16, 0))
        self.assertFalse(removed.exists())
        self.assertTrue(all(path.exists() for path in kept))
        self.assertTrue(directory.is_dir())
        self.assertTrue(symlink.is_symlink())

    def test_open_inode_protects_every_hard_link(self):
        opened = self.file("opened")
        os.link(opened, self.deps / "hardlink")
        proc = self.root / "proc"
        fd = proc / "101/fd"
        fd.mkdir(parents=True)
        (fd / "3").symlink_to(opened)
        (fd / "4").symlink_to(self.root / "vanished")
        held = lambda: trim.open_files(proc)
        self.assertEqual(trim.trim(self.slot, CUTOFF, held_files=held), (0, 0, 1))
        self.assertTrue(opened.exists())
        self.assertTrue((self.deps / "hardlink").exists())

    def test_dry_run_counts_candidates_without_unlinking(self):
        old = self.file("old")
        held = self.file("held")
        info = held.stat()
        self.assertEqual(trim.trim(self.slot, CUTOFF, dry_run=True,
                                   held_files=lambda: ({(info.st_dev, info.st_ino)}, 0)),
                         (1, 16, 0))
        self.assertTrue(old.exists())
        self.assertTrue(held.exists())

    def test_other_users_processes_are_not_inspected(self):
        proc = self.root / "proc"
        (proc / "101/fd").mkdir(parents=True)
        with patch.object(Path, "iterdir", side_effect=AssertionError("fd inspected")):
            # Supply the proc directory's iteration without permitting an fd scan.
            class Proc:
                def iterdir(inner):
                    return [proc / "101"]
            self.assertEqual(trim.open_files(Proc(), uid=os.getuid() + 1), (set(), 0))

    def test_scan_failure_prevents_deletion(self):
        path = self.file("old")
        with self.assertRaises(PermissionError):
            trim.trim(self.slot, CUTOFF, held_files=lambda: (_ for _ in ()).throw(PermissionError()))
        self.assertTrue(path.exists())

    def test_unreadable_or_vanished_fd_directory_is_counted_and_trim_continues(self):
        opened = self.file("opened")
        os.link(opened, self.deps / "hardlink")
        proc = self.root / "proc"
        blocked = proc / "101/fd"
        blocked.mkdir(parents=True)
        readable = proc / "102/fd"
        readable.mkdir(parents=True)
        (readable / "3").symlink_to(opened)
        original = Path.iterdir

        for error in (PermissionError, FileNotFoundError, ProcessLookupError):
            with self.subTest(error=error.__name__):
                removed = self.file("old")

                def scan(path):
                    if path == blocked:
                        raise error("fd directory unavailable")
                    return original(path)

                with patch.object(Path, "iterdir", scan):
                    result = trim.trim(self.slot, CUTOFF, held_files=lambda: trim.open_files(proc))
                self.assertEqual(result, (1, 16, 1))
                self.assertFalse(removed.exists())
                self.assertTrue(opened.exists())
                self.assertTrue((self.deps / "hardlink").exists())

    def test_unreadable_or_vanished_fd_link_counts_process_once(self):
        proc = self.root / "proc"
        fd = proc / "101/fd"
        fd.mkdir(parents=True)
        (fd / "3").touch()
        (fd / "4").touch()
        original = Path.stat

        for error in (PermissionError, FileNotFoundError, ProcessLookupError):
            with self.subTest(error=error.__name__):
                def scan(path, *args, **kwargs):
                    if path.parent == fd:
                        raise error("fd link unavailable")
                    return original(path, *args, **kwargs)

                with patch.object(Path, "stat", scan):
                    self.assertEqual(trim.open_files(proc), (set(), 1))

    def test_vanished_process_is_counted(self):
        proc = self.root / "proc"
        proc.mkdir()

        class Proc:
            def iterdir(inner):
                return [proc / "101"]

        self.assertEqual(trim.open_files(Proc()), (set(), 1))

    def test_unexpected_fd_error_prevents_deletion(self):
        path = self.file("old")
        proc = self.root / "proc"
        (proc / "101").mkdir(parents=True)
        (proc / "101/fd").touch()
        with self.assertRaises(NotADirectoryError):
            trim.trim(self.slot, CUTOFF, held_files=lambda: trim.open_files(proc))
        self.assertTrue(path.exists())

    def test_rewritten_candidates_stay(self):
        path = self.file("old")

        def scan():
            path.write_text("replacement")
            return set(), 0

        self.assertEqual(trim.trim(self.slot, CUTOFF, held_files=scan), (0, 0, 0))
        self.assertEqual(path.read_text(), "replacement")

    def test_symlinked_deps_path_is_rejected(self):
        self.deps.rmdir()
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()
        self.deps.symlink_to(elsewhere, target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError, "symlink"):
            trim.trim(self.slot, CUTOFF, held_files=lambda: (set(), 0))

    def test_missing_deps_directory_is_empty(self):
        self.deps.rmdir()
        self.assertEqual(trim.trim(self.slot, CUTOFF), (0, 0, 0))

    def test_cli_reports_each_slot_and_free_space(self):
        self.file("old", modified=0)
        with patch.object(sys, "argv", ["trim", "--older", "0", str(self.slot)]), \
                patch.object(trim, "trim", return_value=(1, 1_000_000_000, 2)), \
                patch.object(trim.shutil, "disk_usage", return_value=trim.shutil._ntuple_diskusage(
                    10_000_000_000, 4_000_000_000, 6_000_000_000)), \
                redirect_stdout(io.StringIO()) as output:
            self.assertEqual(trim.main(), 0)
        self.assertIn("1 executables, 1.000 GB freed; 6.000 GB free; 2 processes skipped", output.getvalue())

    def test_standalone_stdin_invocation_needs_no_repo_imports(self):
        result = subprocess.run([sys.executable, "-I", "-B", "-", "--older", "120", str(self.slot)],
                                input=(DIRECTORY / "trim").read_text(), text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("0 executables", result.stdout)

    def test_age_rejects_negative_and_nonfinite_values(self):
        for value in ("-1", "nan", "inf"):
            with self.subTest(value=value), self.assertRaises(argparse.ArgumentTypeError):
                trim.minutes(value)


if __name__ == "__main__":
    unittest.main()
