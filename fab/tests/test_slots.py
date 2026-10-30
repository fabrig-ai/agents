import io
import json
import os
import stat
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import patch

from fab import cli, slots
from fab.tests.support import tmp_home


class SlotsTest(unittest.TestCase):
    SINCE = 1_735_689_600_123_000_000
    STAMP = "2025-01-01T00:00:00.123Z"

    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.home = self.stack.enter_context(tmp_home())
        self.root = self.home / "slots"
        self.root.mkdir()
        self.stack.enter_context(patch.dict(os.environ, {"FAB_SLOTS": str(self.root)}))

    def slot(self, number):
        target = self.root / str(number) / "target"
        for name in ("deps", "incremental", "build"):
            (target / "debug" / name).mkdir(parents=True)
        return target

    def file(self, path, *, executable=False, suffix="", mtime=None):
        path = path.with_name(path.name + suffix)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_bytes(b"artifact\n" * 512)
        temporary.replace(path)
        path.chmod(0o755 if executable else 0o644)
        stamp = self.SINCE - 1 if mtime is None else mtime
        os.utime(path, ns=(stamp, stamp))
        return path

    def blocks(self, path):
        try:
            info = path.lstat()
        except FileNotFoundError:
            return 0
        total = info.st_blocks * 512
        if stat.S_ISDIR(info.st_mode):
            total += sum(self.blocks(child) for child in path.iterdir())
        return total

    def usage(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            with self.assertRaises(SystemExit) as raised:
                slots.main(argv)
        self.assertEqual(raised.exception.code, 2)
        return err.getvalue()

    def test_slots_default_override_and_numbered_checkouts(self):
        with patch.dict(os.environ, {"FAB_SLOTS": ""}):
            self.assertEqual(slots.slots_dir(), self.home / "src/fabrig/slots")
            self.assertEqual(slots.slots(), [])
        self.assertEqual(slots.slots_dir(), self.root)
        self.slot(10)
        self.slot(2)
        self.slot(0)
        (self.root / "notes").mkdir()
        self.file(self.root / "3")
        (self.root / "4").symlink_to(self.root / "2", target_is_directory=True)
        self.assertEqual(slots.slots(), [0, 2, 10])

    def test_claim_is_exclusive_and_round_trips(self):
        self.slot(1)
        self.assertIsNone(slots.read_claim(1))
        with patch.object(slots.log, "now", return_value=self.STAMP):
            held = slots.claim(1, "plan/task-1", "plan/task")
        self.assertEqual(held, slots.Claim(1, "plan/task-1", "plan/task", self.STAMP))
        self.assertEqual(slots.read_claim(1), held)
        self.assertIsNone(slots.claim(1, "other", "other"))
        self.assertEqual(slots.read_claim(1), held)
        self.assertEqual(list(self.root.glob(".*.claim.*")), [])

    def test_concurrent_claims_have_exactly_one_holder(self):
        self.slot(1)
        barrier = Barrier(8)

        def claiming(number):
            barrier.wait(timeout=5)
            return slots.claim(1, f"run-{number}", "task")

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(claiming, range(8)))
        holders = [held for held in results if held is not None]
        self.assertEqual(len(holders), 1)
        self.assertEqual(slots.read_claim(1), holders[0])
        self.assertEqual(list(self.root.glob(".*.claim.*")), [])

    def test_claim_requires_an_existing_checkout(self):
        with self.assertRaises(ValueError):
            slots.claim(9, "run", "task")
        self.assertFalse((self.root / "9.claim").exists())

    def test_claim_failed_publication_removes_reservation(self):
        self.slot(1)
        with patch.object(Path, "replace", side_effect=OSError("rename failed")):
            with self.assertRaisesRegex(OSError, "rename failed"):
                slots.claim(1, "run", "task")
        self.assertIsNone(slots.read_claim(1))
        self.assertEqual(list(self.root.glob(".*.claim.*")), [])

    def test_release_sweeps_old_outputs_and_marks_the_slot(self):
        target = self.slot(1)
        old = self.file(target / "debug/deps/old", executable=True)
        fresh = self.file(target / "debug/deps/new", executable=True, mtime=self.SINCE + 1)
        equal = self.file(target / "debug/deps/equal", executable=True, mtime=self.SINCE)
        library = self.file(target / "debug/deps/lib.rlib", executable=True)
        incremental = target / "debug/incremental"
        self.file(incremental / "session/cache")
        build = self.file(target / "debug/build/build-script")
        with patch.object(slots.log, "now", return_value=self.STAMP):
            slots.claim(1, "run", "task")
        marker = self.root / "1.released"
        marker.touch()
        os.utime(marker, ns=(1, 1))
        expected = self.blocks(old) + self.blocks(incremental)
        self.assertEqual(slots.release(1, "run"), expected)
        self.assertFalse(old.exists())
        self.assertFalse(incremental.exists())
        self.assertTrue(all(p.exists() for p in (fresh, equal, library, build)))
        self.assertIsNone(slots.read_claim(1))
        self.assertGreater(marker.stat().st_mtime_ns, 1)

    def test_release_by_another_run_leaves_everything_alone(self):
        target = self.slot(1)
        artifact = self.file(target / "debug/deps/old", executable=True)
        held = slots.claim(1, "holder", "task")
        with self.assertRaisesRegex(ValueError, "holder"):
            slots.release(1, "other")
        self.assertEqual(slots.read_claim(1), held)
        self.assertTrue(artifact.exists())
        self.assertFalse((self.root / "1.released").exists())

    def test_release_without_a_claim_does_nothing(self):
        target = self.slot(1)
        artifact = self.file(target / "debug/deps/old", executable=True)
        self.assertEqual(slots.release(1, "run"), 0)
        self.assertEqual(slots.release(9, "run"), 0)
        self.assertTrue(artifact.exists())
        self.assertFalse((self.root / "1.released").exists())

    def test_failed_release_keeps_the_claim(self):
        self.slot(1)
        held = slots.claim(1, "run", "task")
        with patch.object(slots, "remove", side_effect=OSError("disk error")):
            with self.assertRaisesRegex(OSError, "disk error"):
                slots.release(1, "run")
        self.assertEqual(slots.read_claim(1), held)
        self.assertFalse((self.root / "1.released").exists())

    def test_sweep_plan_all_profiles_and_strict_mtime_cutoff(self):
        target = self.slot(1)
        expected = [target / "debug/incremental"]
        for profile in ("debug", "release", "custom"):
            base = target / profile
            for name in ("incremental-a", "incremental-cache"):
                path = base / name
                path.mkdir(parents=True)
                self.file(path / "data")
                expected.append(path)
            expected.append(self.file(base / "deps/old", executable=True))
            self.file(base / "deps/new", executable=True, mtime=self.SINCE + 1)
            self.file(base / "deps/equal", executable=True, mtime=self.SINCE)
            self.file(base / "deps/plain")
            self.file(base / "incremental-file")
            self.file(base / "build/script", executable=True)
            self.file(base / "test-at-profile-root", executable=True)
            self.file(base / "deps/group-exec").chmod(0o654)
            (base / "deps/executable-directory").mkdir()
            for suffix in slots.NOT_EXECUTABLES:
                self.file(base / "deps/library", executable=True, suffix=suffix)
        self.assertEqual(slots.sweep_plan(target, self.SINCE), sorted(expected))

    def test_sweep_without_a_cutoff_takes_every_test_executable(self):
        target = self.slot(1)
        expected = [target / "debug/incremental"]
        for name, stamp in (("old", self.SINCE - 1), ("equal", self.SINCE),
                            ("new", self.SINCE + 1)):
            expected.append(self.file(target / "debug/deps" / name,
                                      executable=True, mtime=stamp))
        self.assertEqual(slots.sweep_plan(target, None), sorted(expected))

    def test_sweep_never_lists_or_traverses_symlinks(self):
        target = self.slot(1)
        outside = self.home / "outside"
        executable = self.file(outside / "deps/test", executable=True)
        (outside / "incremental").mkdir()
        (target / "linked-profile").symlink_to(outside, target_is_directory=True)
        (target / "debug/incremental-link").symlink_to(outside, target_is_directory=True)
        (target / "debug/deps/linked-test").symlink_to(executable)
        (target / "debug/deps/broken").symlink_to(outside / "absent")
        (target / "custom").mkdir()
        (target / "custom/deps").symlink_to(outside / "deps", target_is_directory=True)
        self.assertEqual(slots.sweep_plan(target, None), [target / "debug/incremental"])
        alias = self.root / "target-link"
        alias.symlink_to(target, target_is_directory=True)
        self.assertEqual(slots.sweep_plan(alias, None), [])
        self.assertEqual(slots.sweep_plan(target / "missing", None), [])
        self.assertEqual(slots.sweep_plan(executable, None), [])

    def test_remove_counts_allocated_blocks_and_skips_missing_paths(self):
        target = self.slot(1)
        tree = target / "debug/incremental"
        artifact = self.file(tree / "session/cache")
        outside = self.file(self.home / "outside/data")
        (tree / "outside").symlink_to(outside.parent, target_is_directory=True)
        plain = self.file(target / "debug/deps/test", executable=True)
        expected = self.blocks(tree) + self.blocks(plain)
        self.assertEqual(slots.remove([tree, artifact, plain, plain, target / "missing"]), expected)
        self.assertFalse(tree.exists())
        self.assertFalse(plain.exists())
        self.assertTrue(outside.exists())

    def test_remove_counts_hard_linked_data_once(self):
        target = self.slot(1)
        one = self.file(target / "debug/deps/one")
        two = one.with_name("two")
        os.link(one, two)
        expected = one.stat().st_blocks * 512
        self.assertEqual(slots.remove([one, two]), expected)
        self.assertFalse(one.exists())
        self.assertFalse(two.exists())

    def test_remove_unlinks_a_symlink_without_touching_its_target(self):
        artifact = self.file(self.home / "outside/data")
        link = self.root / "link"
        link.symlink_to(artifact)
        expected = link.lstat().st_blocks * 512
        self.assertEqual(slots.remove([link]), expected)
        self.assertFalse(link.is_symlink())
        self.assertTrue(artifact.exists())

    def test_free_bytes_uses_blocks_available_to_the_user(self):
        fake = SimpleNamespace(f_bavail=7, f_bfree=11, f_frsize=4096, f_bsize=8192)
        with patch.object(slots.os, "statvfs", return_value=fake) as statvfs:
            self.assertEqual(slots.free_bytes(), 7 * 4096)
            statvfs.assert_called_once_with(self.root)
            self.assertEqual(slots.free_bytes(self.home), 7 * 4096)
            self.assertEqual(statvfs.call_args.args, (self.home,))

    def test_idle_orders_never_released_then_oldest_with_stable_ties(self):
        for number in (10, 3, 2, 1, 4, 5):
            self.slot(number)
        for number, stamp in ((3, 300), (2, 200), (4, 200)):
            marker = self.root / f"{number}.released"
            marker.touch()
            os.utime(marker, ns=(stamp, stamp))
        slots.claim(5, "busy", "task")
        self.assertEqual(slots.idle(), [1, 10, 2, 4, 3])

    def test_reclaim_stops_in_first_pass_in_idle_order(self):
        later = self.slot(1)
        first = self.slot(2)
        marker = self.root / "1.released"
        marker.touch()
        os.utime(marker, ns=(123, 123))
        self.file(first / "debug/incremental/cache")
        executable = self.file(first / "debug/deps/test", executable=True)
        library = self.file(first / "debug/deps/lib.rlib")
        total = self.blocks(first) + self.blocks(later)
        free = lambda: 100 + total - self.blocks(first) - self.blocks(later)
        expected = self.blocks(first / "debug/incremental") + self.blocks(executable)
        real_remove = slots.remove

        def removing(paths):
            self.assertEqual(slots.read_claim(2).run, "reclaim")
            return real_remove(paths)

        with patch.object(slots, "remove", side_effect=removing) as remove:
            self.assertEqual(slots.reclaim(100 + expected, free=free), expected)
        self.assertEqual(remove.call_count, 1)
        self.assertTrue(library.exists())
        self.assertTrue((later / "debug/incremental").exists())
        self.assertIsNone(slots.read_claim(2))
        self.assertFalse((self.root / "2.released").exists())
        self.assertEqual(marker.stat().st_mtime_ns, 123)

    def test_reclaim_uses_two_passes_in_the_same_order_and_skips_claimed(self):
        first, second, busy = self.slot(1), self.slot(2), self.slot(3)
        for target in (first, second, busy):
            self.file(target / "debug/incremental/cache")
            self.file(target / "debug/deps/test", executable=True)
            self.file(target / "debug/deps/lib.rlib")
        held = slots.claim(3, "builder", "task")
        for number in (1, 2):
            marker = self.root / f"{number}.released"
            marker.touch()
            os.utime(marker, ns=(number * 100, number * 100))
        total = self.blocks(first) + self.blocks(second)
        free = lambda: total - self.blocks(first) - self.blocks(second)
        real_remove = slots.remove
        seen = []

        def removing(paths):
            number = 1 if paths[0].is_relative_to(first) else 2
            self.assertEqual(slots.read_claim(number).run, "reclaim")
            seen.append(paths)
            return real_remove(paths)

        with patch.object(slots, "remove", side_effect=removing):
            self.assertEqual(slots.reclaim(total + 1, free=free), total)
        self.assertEqual(seen, [
            [first / "debug/deps/test", first / "debug/incremental"],
            [second / "debug/deps/test", second / "debug/incremental"],
            [first], [second],
        ])
        self.assertFalse(first.exists())
        self.assertFalse(second.exists())
        self.assertTrue((busy / "debug/deps/test").exists())
        self.assertEqual(slots.read_claim(3), held)
        for number in (1, 2):
            self.assertIsNone(slots.read_claim(number))
            self.assertEqual((self.root / f"{number}.released").stat().st_mtime_ns, number * 100)

    def test_reclaim_stops_during_whole_target_pass(self):
        first, second = self.slot(1), self.slot(2)
        self.file(first / "debug/deps/lib.rlib")
        library = self.file(second / "debug/deps/lib.rlib")
        first_size = self.blocks(first)
        total = first_size + self.blocks(second)
        free = lambda: total - self.blocks(first) - self.blocks(second)
        freed = slots.reclaim(first_size, free=free)
        self.assertGreaterEqual(freed, first_size)
        self.assertFalse(first.exists())
        self.assertTrue(library.exists())
        self.assertIsNone(slots.read_claim(1))
        self.assertIsNone(slots.read_claim(2))

    def test_reclaim_with_enough_space_never_claims(self):
        self.slot(1)
        with patch.object(slots, "claim") as claim:
            self.assertEqual(slots.reclaim(100, free=lambda: 100), 0)
        claim.assert_not_called()

    def test_reclaim_skips_a_slot_claimed_after_the_idle_snapshot(self):
        target = self.slot(1)
        artifact = self.file(target / "debug/deps/test", executable=True)
        held = slots.claim(1, "builder", "task")
        with patch.object(slots, "idle", return_value=[1]):
            self.assertEqual(slots.reclaim(1, free=lambda: 0), 0)
        self.assertTrue(artifact.exists())
        self.assertEqual(slots.read_claim(1), held)

    def test_failed_reclaim_removes_its_claim_without_a_release_marker(self):
        self.slot(1)
        with patch.object(slots, "remove", side_effect=OSError("disk error")):
            with self.assertRaisesRegex(OSError, "disk error"):
                slots.reclaim(1, free=lambda: 0)
        self.assertIsNone(slots.read_claim(1))
        self.assertFalse((self.root / "1.released").exists())

    def test_reclaim_without_slots_returns_zero(self):
        self.assertEqual(slots.reclaim(1, free=lambda: 0), 0)

    def test_main_list_prints_sorted_json_lines_with_claims_and_idle_ranks(self):
        self.slot(2)
        self.slot(1)
        held = slots.claim(2, "builder", "task")
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(cli.main(["slot", "list"]), 0)
        lines = out.getvalue().splitlines()
        records = [json.loads(line) for line in lines]
        self.assertEqual(records, [
            {"slot": 1, "claim": None, "idle": 0},
            {"slot": 2, "claim": {"slot": 2, "run": "builder", "task": "task",
                                  "since": held.since}, "idle": None},
        ])
        self.assertEqual(lines, [json.dumps(record, sort_keys=True) for record in records])

    def test_main_claim_and_release(self):
        target = self.slot(1)
        old = self.file(target / "debug/deps/test", executable=True)
        expected = self.blocks(old) + self.blocks(target / "debug/incremental")
        self.assertEqual(slots.main(["claim", "1", "run", "task"]), 0)
        self.assertEqual(slots.main(["claim", "1", "other", "task"]), 1)
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(slots.main(["release", "1", "run"]), 0)
            self.assertEqual(slots.main(["release", "1", "run"]), 0)
        self.assertEqual(out.getvalue().splitlines(), [str(expected), "0"])
        self.assertIsNone(slots.read_claim(1))

    def test_main_reclaim_reports_freed_and_available_bytes_and_shortfall(self):
        for available, status in ((1_500_000_000, 0), (1_499_999_999, 1)):
            with self.subTest(available=available):
                out = io.StringIO()
                with patch.object(slots, "reclaim", return_value=4096) as reclaim, \
                        patch.object(slots, "free_bytes", return_value=available), redirect_stdout(out):
                    self.assertEqual(slots.main(["reclaim", "--need-gb", "1.5"]), status)
                reclaim.assert_called_once_with(1_500_000_000)
                self.assertEqual(json.loads(out.getvalue()), {"freed": 4096, "free": available})

    def test_main_reports_invalid_commands_and_claim_errors(self):
        for args in ([], ["sweep"], ["claim", "x", "run", "task"],
                     ["claim", "9", "run", "task"], ["release", "1"],
                     ["reclaim"], ["reclaim", "--need-gb", "-1"],
                     ["reclaim", "--need-gb", "nan"], ["reclaim", "--need-gb", "inf"]):
            with self.subTest(args=args):
                self.assertIn("error:", self.usage(args))
        self.slot(1)
        held = slots.claim(1, "holder", "task")
        self.assertIn("holder", self.usage(["release", "1", "other"]))
        self.assertEqual(slots.read_claim(1), held)
