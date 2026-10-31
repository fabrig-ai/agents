"""Minimal Rust gates are pure; screen uses fake git and ratchet services (fab.md, 8)."""

from __future__ import annotations

import fcntl
import io
import tarfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from fab import atomic, log, rust_digest, rust_gates as gates
from fab.digest import Function
from fab.gates import Finding, findings_text
from fab.plan import Task
from fab.sh import Failed, Result
from fab.tests.support import FakeRunner, tmp_home

TASK = Task("draft/rust", "part", "feature", "fabrig", (), ("skein/**",),
            "high", 60, "Build Rust.", "task.md")
BASE = "b" * 40
TIP = "a" * 40


def summary(**fields) -> rust_digest.Digest:
    clean = rust_digest.Digest("draft/rust-1", TASK.id, TASK.kind, "draft/rust", BASE, TIP,
                               (), (), (), (), (), ())
    return replace(clean, **fields)


class CheckTest(unittest.TestCase):
    def test_files_then_ratchet_in_digest_order_size_is_only_flagged(self):
        result = summary(outside=("outside/a.rs", "outside/b.md"),
                         long=(Function("skein/a.rs", "large", 1, 61),),
                         ratchets=(rust_digest.Ratchet("skein", "fall", 5, 4),
                                   rust_digest.Ratchet("other", "max_out", 1, 2),
                                   rust_digest.Ratchet("skein", "JournalRoom", 0, 2),
                                   rust_digest.Ratchet("skein", "equal", 2, 2)))
        self.assertEqual(gates.check(result),
                         [Finding("files", "`outside/a.rs` is outside the task's files"),
                          Finding("files", "`outside/b.md` is outside the task's files"),
                          Finding("ratchet", "`other`: `max_out` rose from 1 to 2"),
                          Finding("ratchet", "`skein`: `JournalRoom` rose from 0 to 2")])
        self.assertEqual(gates.check(replace(result, outside=(), ratchets=())), [])

    def test_falls_and_equal_counts_pass_and_findings_work_in_repair_briefs(self):
        self.assertEqual(gates.check(summary(ratchets=(rust_digest.Ratchet("skein", "form", 2, 1),
                                                       rust_digest.Ratchet("other", "form", 0, 0)))), [])
        # A form the base does not count yet is the branch adding it to the ratchet, not a rise.
        self.assertEqual(gates.check(summary(ratchets=(rust_digest.Ratchet("skein", "io_resume", 0, 39, True),))), [])
        text = findings_text(gates.check(summary(ratchets=(rust_digest.Ratchet("skein", "form", 1, 2),))))
        self.assertEqual(text, "[gate:ratchet]\n- `skein`: `form` rose from 1 to 2\n")


class ScreenTest(unittest.TestCase):
    def setUp(self):
        self.home = self.enterContext(tmp_home())
        self.repo = log.home() / "repos/fabrig"
        (self.repo / ".git").mkdir(parents=True)
        self.path = self.home / "events.jsonl"
        self.written = log.home() / "digests/draft/rust-2.md"
        self.events = [dict(ev="run.started", task=TASK.id, run="draft/rust-1", branch="draft/old"),
                       dict(ev="run.started", task=TASK.id, run="draft/rust-2", branch="draft/rust"),
                       dict(ev="run.started", task="draft/other", run="draft/other-1", branch="draft/other")]
        self.trees = {BASE: {"skein/src/lib.rs": "pub struct Gone;\n",
                             "skein/scripts/old_forms.py": "# fake service\n",
                             "skein/scripts/old-forms.txt": "form 5\n"},
                      TIP: {"skein/src/lib.rs": "pub struct New;\n",
                            "skein/scripts/old_forms.py": "# fake service\n",
                            "skein/scripts/old-forms.txt": "form 5\n"}}
        self.current = {"base": 2, "tip": 2}
        self.fake = (FakeRunner().on(["git", "rev-parse"], Result(0, TIP + "\n"))
                     .on(["git", "merge-base"], Result(0, BASE + "\n"))
                     .on(["git", "diff"], Result(0, "1\t1\tskein/src/lib.rs\0"))
                     .on(["git", "archive"], self.archive)
                     .on(["python3"], self.ratchet))

    def archive(self, call):
        with tarfile.open(call.argv[call.argv.index("-o") + 1], "w") as tree:
            for path, text in self.trees[call.argv[-1]].items():
                content = text.encode()
                entry = tarfile.TarInfo(path)
                entry.size = len(content)
                tree.addfile(entry, io.BytesIO(content))
        return Result(0)

    def ratchet(self, call):
        side = "base" if "/base/" in call.cwd else "tip"
        self.assertEqual((Path(call.cwd) / "scripts/old-forms.txt").read_text(), "form 0\n")
        return Result(1, err=f"form: count {self.current[side]}, baseline 0\nRule.\n")

    def test_pass_writes_digest_selects_last_run_uses_seam_and_removes_archives(self):
        self.assertEqual(gates.screen(TASK, iter(self.events), sh=self.fake, log_path=self.path), [])
        text = self.written.read_text()
        self.assertIn("# Rust digest: draft/rust-2", text)
        self.assertIn(f"Base: `{BASE[:12]}`; tip: `{TIP[:12]}`", text)
        self.assertIn("added `pub struct New`", text)
        self.assertIn("removed `pub struct Gone`", text)
        self.assertIn("`skein` `form`: 2 -> 2 (+0)", text)
        self.assertEqual(log.read(self.path), [])
        self.assertEqual(sorted(path.name for path in log.home().iterdir()), ["digests", "land-fabrig.lock", "repos"])
        self.assertEqual(self.fake.argvs()[:4],
                         [["git", "fetch", "origin", "--prune"],
                          ["git", "rev-parse", "--verify", "refs/remotes/origin/draft/rust^{commit}"],
                          ["git", "merge-base", "refs/remotes/origin/main", TIP],
                          ["git", "diff", "--numstat", "-z", "--no-renames", BASE, TIP, "--"]])
        self.assertEqual([call.cwd for call in self.fake.calls[:4]], [str(self.repo)] * 4)
        self.assertEqual(len([argv for argv in self.fake.argvs() if argv[:1] == ["python3"]]), 2)
        self.assertFalse(any(argv[1] in ("checkout", "worktree", "push") for argv in self.fake.argvs()))

    def test_screen_uses_merge_base_with_plan_trunk(self):
        self.assertEqual(gates.screen(TASK, self.events, sh=self.fake, log_path=self.path,
                                       trunk="component-kit/integration"), [])
        self.assertEqual(self.fake.argvs()[2],
                         ["git", "merge-base", "refs/remotes/origin/component-kit/integration", TIP])
        self.assertIn(f"Base: `{BASE[:12]}`", self.written.read_text())

    def test_ratchet_rise_with_unchanged_baselines_rejects_after_unlock(self):
        self.current["tip"] = 3
        append = log.append

        def rejected(event, **fields):
            with open(log.home() / "land-fabrig.lock", "a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return append(event, **fields)

        def locked(argv, **kwargs):
            with open(log.home() / "land-fabrig.lock", "a") as lock:
                with self.assertRaises(BlockingIOError):
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if argv[0] == "git":
                self.assertTrue(kwargs["check"])
            return self.fake(argv, **kwargs)

        with patch("fab.log.append", side_effect=rejected):
            findings = gates.screen(TASK, self.events, sh=locked, log_path=self.path)
        self.assertEqual(findings, [Finding("ratchet", "`skein`: `form` rose from 2 to 3")])
        record, = log.read(self.path)
        self.assertEqual({key: value for key, value in record.items() if key != "ts"},
                         dict(ev="branch.rejected", task=TASK.id, branch="draft/rust", tip=TIP,
                              step="gate:ratchet", log=str(self.written), findings=findings_text(findings)))
        self.assertEqual(log.read(), [])

    def test_path_outside_files_rejects_and_records_all_findings(self):
        self.current["tip"] = 3
        findings = gates.screen(replace(TASK, files=("skein/src/other.rs",)), self.events,
                               sh=self.fake, log_path=self.path)
        self.assertEqual([finding.gate for finding in findings], ["files", "ratchet"])
        record, = log.read(self.path)
        self.assertEqual(record["step"], "gate:files")
        self.assertEqual(record["findings"], findings_text(findings))
        self.assertTrue(self.written.is_file())

    def test_ratchet_fall_and_long_function_pass(self):
        self.current["tip"] = 1
        self.trees[TIP]["skein/src/lib.rs"] = "pub fn long() {\n" + "    call();\n" * 59 + "}\n"
        self.assertEqual(gates.screen(TASK, self.events, sh=self.fake, log_path=self.path), [])
        self.assertIn("long: 61 lines", self.written.read_text())
        self.assertEqual(log.read(self.path), [])

    def test_existing_debt_above_its_recorded_baseline_is_compared_by_count(self):
        self.fake.rules.insert(0, (["python3"], Result(1, err="form: count 6, baseline 0\nRule.\n")))
        # Each side's actual count is six, so no branch increase even though each script exits one.
        self.assertEqual(gates.screen(TASK, self.events, sh=self.fake, log_path=self.path), [])
        self.assertIn("`skein` `form`: 6 -> 6 (+0)", self.written.read_text())

    def test_no_run_raises_before_commands_or_creating_home(self):
        with self.assertRaisesRegex(ValueError, TASK.id):
            gates.screen(TASK, self.events[-1:], sh=self.fake, log_path=self.path)
        self.assertEqual(self.fake.calls, [])
        self.assertFalse((log.home() / "land-fabrig.lock").exists())

    def test_git_and_script_failure_raise_without_digest_or_rejection(self):
        for command in (["git", "fetch"], ["git", "rev-parse"], ["git", "merge-base"],
                        ["git", "diff"], ["git", "archive"], ["git", "init"], ["git", "add"], ["python3"]):
            self.fake.rules.insert(0, (command, Result(2, err="service unavailable")))
            with self.subTest(command=command), self.assertRaises(Failed):
                gates.screen(TASK, self.events, sh=self.fake, log_path=self.path)
            self.fake.rules.pop(0)
            self.assertFalse(self.written.exists())
            self.assertEqual(log.read(self.path), [])
            self.assertEqual(sorted(path.name for path in log.home().iterdir()), ["land-fabrig.lock", "repos"])

    def test_invalid_count_and_missing_baseline_raise_without_digest(self):
        for baseline in (None, "form broken\n"):
            if baseline is None:
                self.trees[TIP].pop("skein/scripts/old-forms.txt")
                error = FileNotFoundError
            else:
                self.trees[TIP]["skein/scripts/old-forms.txt"] = baseline
                error = ValueError
            with self.subTest(baseline=baseline), self.assertRaises(error):
                gates.screen(TASK, self.events, sh=self.fake, log_path=self.path)
            self.assertFalse(self.written.exists())
            self.assertEqual(log.read(self.path), [])

    def test_missing_clone_uses_fabrig_remote_and_clone_failure_raises(self):
        (self.repo / ".git").rmdir()
        self.assertEqual(gates.screen(TASK, self.events, sh=self.fake, log_path=self.path), [])
        self.assertEqual(self.fake.argvs()[0], ["git", "clone", "git@github.com:fabrig-ai/fabrig.git", str(self.repo)])
        self.written.unlink()
        self.fake.rules.insert(0, (["git", "clone"], Result(1, err="clone failed")))
        with self.assertRaises(Failed):
            gates.screen(TASK, self.events, sh=self.fake, log_path=self.path)
        self.assertFalse(self.written.exists())
        self.assertEqual(log.read(self.path), [])

    def test_no_script_tree_still_checks_files_and_writes_digest(self):
        for files in self.trees.values():
            files.pop("skein/scripts/old_forms.py")
            files.pop("skein/scripts/old-forms.txt")
        self.assertEqual(gates.screen(TASK, self.events, sh=self.fake, log_path=self.path), [])
        self.assertFalse(any(argv[0] == "python3" for argv in self.fake.argvs()))
        self.assertIn("## Old forms by tree\n- none\n", self.written.read_text())
