import fcntl
import shutil
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from fab import atomic, gates, log, run as runs, state
from fab.calls import Signature
from fab.digest import Clone, Digest, Function
from fab.gates import Finding, banned_names, check, findings_text, words
from fab.plan import Task
from fab.run import brief
from fab.sh import Failed, Result, run
from fab.tests.support import FakeRunner, git, git_pair, tmp_home


CLEAN = Digest("draft/task-1", "draft/task", "feature", "draft/task", "a" * 40, "b" * 40,
               (), (), (), (), (), (), (), ())
ITEM = Signature("fab/work.py", "work", "def work()", "Do the work.")


class BannedNamesTest(unittest.TestCase):
    def test_banned_names_from_taste(self):
        with tmp_home():
            taste = (Path(__file__).resolve().parents[1] / "taste.md").read_text()
        self.assertTrue({"util", "manager"} <= banned_names(taste))

    def test_banned_names_stop_at_next_section(self):
        taste = ("- `before`\n## Banned names\n\nExplanation with `ignored`.\n"
                 "- `UTIL` and `ignored`\n- `Manager` — a role\n"
                 "  - `indented`\n- `unterminated\n## Pairs\n- `after`\n")
        self.assertEqual(banned_names(taste), frozenset({"util", "manager"}))

    def test_banned_names_without_heading(self):
        for taste in ("", "## Pairs\n- `util`\n", "### Banned names\n- `manager`\n"):
            with self.subTest(taste=taste):
                self.assertEqual(banned_names(taste), frozenset())


class WordsTest(unittest.TestCase):
    def test_words_examples(self):
        for name, expected in (("fetch_all", ["fetch", "all"]),
                               ("TaskView", ["task", "view"]),
                               ("HTTPError", ["http", "error"]),
                               ("sha256", ["sha", "256"]),
                               ("_private_x", ["private", "x"])):
            with self.subTest(name=name):
                self.assertEqual(words(name), expected)

    def test_words_boundaries(self):
        for name, expected in (("", []), ("___", []), ("HTTP", ["http"]),
                               ("sha256Sum", ["sha", "256", "sum"]),
                               ("XML2HTTPError__", ["xml", "2", "http", "error"]),
                               ("metadata", ["metadata"])):
            with self.subTest(name=name):
                self.assertEqual(words(name), expected)


class GatesTest(unittest.TestCase):
    def test_files_in_digest_order(self):
        digest = replace(CLEAN, outside=("z.txt", "a.txt"))
        self.assertEqual(check(digest, ()), [
            Finding("files", "`z.txt` is outside the task's files"),
            Finding("files", "`a.txt` is outside the task's files")])

    def test_shape_removed_then_changed(self):
        removed = replace(ITEM, name="old", text="def old()")
        changed = replace(ITEM, text="def work(count)")
        digest = replace(CLEAN, removed=(removed,), changed=((ITEM, changed),))
        self.assertEqual(check(digest, ()), [
            Finding("shape", "`fab/work.py`: `def old()` removed"),
            Finding("shape", "`fab/work.py`: `def work()` changed to `def work(count)`")])

    def test_shape_exempt_kinds(self):
        for kind in ("interface", "migration"):
            with self.subTest(kind=kind):
                digest = replace(CLEAN, kind=kind, removed=(ITEM,),
                                 changed=((ITEM, replace(ITEM, text="def work(count)")),))
                self.assertEqual(check(digest, ()), [])
                self.assertEqual(check(replace(digest, outside=("extra",)), ()),
                                 [Finding("files", "`extra` is outside the task's files")])

    def test_size(self):
        digest = replace(CLEAN, long=(Function("fab/work.py", "Queue.work", 10, 61),))
        self.assertEqual(check(digest, ()), [
            Finding("size", "`fab/work.py:10` Queue.work is 61 lines (cap 60)")])

    def test_names_new_module(self):
        digest = replace(CLEAN, modules=("fab/utils.py", "fab/work.py"))
        self.assertEqual(check(digest, iter(["UTILS"])), [
            Finding("names", "`fab/utils.py` uses the banned word `utils`")])

    def test_names_added_item_and_existing_class_method(self):
        digest = replace(CLEAN, added=(
            replace(ITEM, name="TaskManager", text="class TaskManager"),
            replace(ITEM, name="Queue.handle_task", text="def handle_task(self)")))
        self.assertEqual(check(digest, ["MANAGER", "handle"]), [
            Finding("names", "`fab/work.py`: `TaskManager` uses the banned word `manager`"),
            Finding("names", "`fab/work.py`: `Queue.handle_task` uses the banned word `handle`")])

    def test_names_first_word_module_before_items(self):
        digest = replace(CLEAN, modules=("fab/helper_manager.py",),
                         added=(replace(ITEM, name="ManagerHelper"),))
        self.assertEqual(check(digest, ["manager", "helper"]), [
            Finding("names", "`fab/helper_manager.py` uses the banned word `helper`"),
            Finding("names", "`fab/work.py`: `ManagerHelper` uses the banned word `manager`")])

    def test_names_whole_words_and_last_component_only(self):
        digest = replace(CLEAN, modules=("fab/metadata.py",), added=(
            replace(ITEM, name="metadata"), replace(ITEM, name="Manager.work")))
        self.assertEqual(check(digest, ["data", "manager"]), [])

    def test_docs_for_added_functions_classes_and_methods(self):
        added = (replace(ITEM, doc=""),
                 Signature("fab/work.py", "Queue", "class Queue", ""),
                 Signature("fab/work.py", "Queue.work", "def work(self)", ""),
                 replace(ITEM, name="documented"))
        self.assertEqual(check(replace(CLEAN, added=added), ()), [
            Finding("docs", "`fab/work.py`: `def work()` has no docstring"),
            Finding("docs", "`fab/work.py`: `class Queue` has no docstring"),
            Finding("docs", "`fab/work.py`: `def work(self)` has no docstring")])

    def test_clones(self):
        digest = replace(CLEAN, clones=(Clone("fab/work.py", 9, 20, "fab/queue.py", 3),))
        self.assertEqual(check(digest, ()), [
            Finding("clones", "`fab/work.py:9-20` repeats `fab/queue.py:3`")])

    def test_clean_digest(self):
        self.assertEqual(check(CLEAN, ["util", "manager"]), [])
        self.assertEqual(check(replace(CLEAN, modules=("fab/work.py",), added=(ITEM,)),
                               ["util", "manager"]), [])

    def test_order_across_gates(self):
        digest = replace(CLEAN, outside=("extra",), removed=(ITEM,),
                         long=(Function("fab/work.py", "work", 1, 80),),
                         added=(replace(ITEM, name="TaskManager", doc=""),),
                         clones=(Clone("fab/work.py", 1, 8, "fab/other.py", 1),))
        self.assertEqual([finding.gate for finding in check(digest, ["manager"])],
                         ["files", "shape", "size", "names", "docs", "clones"])


class FindingsTextTest(unittest.TestCase):
    def test_group_by_first_gate_and_keep_finding_order(self):
        findings = [Finding("docs", "first"), Finding("names", "second"),
                    Finding("docs", "third"), Finding("names", "fourth")]
        self.assertEqual(findings_text(findings),
                         "[gate:docs]\n- first\n- third\n[gate:names]\n- second\n- fourth\n")
        self.assertEqual(findings_text([]), "")

    def test_brief_quotes_all_gates(self):
        findings = [Finding("files", "`extra` is outside the task's files"),
                    Finding("docs", "`fab/work.py`: `def work()` has no docstring")]
        text = findings_text(findings)
        task = Task("draft/task", "part", "feature", "agents", (), ("fab/work.py",),
                    "high", 20, "Implement work.\n", "docs/plan/draft/tasks/task.md")
        result = brief(task, "Role", run_id=CLEAN.run, branch=CLEAN.branch,
                       base="origin/main", report="/report.md",
                       rejection={"step": "gate:files", "log": "/digest.md", "text": text})
        quoted = result.split("```text\n", 1)[1].split("\n```", 1)[0]
        self.assertEqual(quoted + "\n", text)


class ScreenTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = cls.enterClassContext(tmp_home())
        cls.fixture_origin, cls.fixture_repo = git_pair(root)
        atomic.write(cls.fixture_repo / "fab/x.py", 'def x():\n    """Return a count."""\n    return 1\n')
        git(cls.fixture_repo, "add", "fab/x.py")
        git(cls.fixture_repo, "commit", "-q", "-m", "Add package")
        git(cls.fixture_repo, "push", "-q", "origin", "HEAD:main")
        cls.base = git(cls.fixture_repo, "rev-parse", "HEAD")

    def setUp(self):
        self.home = self.enterContext(tmp_home())
        self.origin, self.branch_repo = self.home / "origin.git", self.home / "clone"
        shutil.copytree(self.fixture_origin, self.origin)
        shutil.copytree(self.fixture_repo, self.branch_repo)
        git(self.branch_repo, "remote", "set-url", "origin", str(self.origin))
        self.repo = log.home() / "repos" / "agents"
        shutil.copytree(self.branch_repo, self.repo)
        git(self.branch_repo, "checkout", "-qb", "draft/task-r1")
        self.task = Task("draft/task", "part", "feature", "agents", (), ("fab/x.py",),
                         "high", 20, "Implement x.", "task.md")
        self.events = [dict(ev="run.started", task=self.task.id, run="draft/task-1",
                            branch="draft/missing"),
                       dict(ev="run.started", task=self.task.id, run="draft/task-2",
                            branch="draft/task-r1"),
                       dict(ev="run.started", task="draft/other", run="draft/other-1",
                            branch="draft/other")]
        self.path = self.home / "events.jsonl"
        self.digest = log.home() / "digests" / "draft/task-2.md"

    def push(self, path="fab/x.py", text='def x():\n    """Return a count."""\n    return 2\n'):
        atomic.write(self.branch_repo / path, text)
        git(self.branch_repo, "add", path)
        git(self.branch_repo, "commit", "-q", "-m", "Change task file")
        git(self.branch_repo, "push", "-q", "origin", "HEAD")
        return git(self.branch_repo, "rev-parse", "HEAD")

    def test_clean_branch_writes_digest_without_logging_or_changing_checkout(self):
        tip = self.push()
        self.assertEqual(gates.screen(self.task, iter(self.events), log_path=self.path), [])
        rendered = self.digest.read_text()
        self.assertIn("# Digest: draft/task-2\n", rendered)
        self.assertIn(f"Base: `{self.base[:12]}`; tip: `{tip[:12]}`", rendered)
        self.assertIn("`fab/x.py` production +1 -1", rendered)
        self.assertEqual(log.read(self.path), [])
        self.assertEqual(log.read(), [])
        self.assertEqual(git(self.repo, "rev-parse", "HEAD"), self.base)
        self.assertEqual(sorted(p.name for p in log.home().iterdir()),
                         ["digests", "land-agents.lock", "repos"])

    def test_outside_files_rejects_after_releasing_lock_with_digest_and_findings(self):
        tip = self.push("extra.md", "Outside the task.\n")
        append = log.append

        def rejected(ev, **fields):
            with open(log.home() / "land-agents.lock", "a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return append(ev, **fields)

        def locked_git(argv, **kwargs):
            self.assertTrue(kwargs["check"])
            with open(log.home() / "land-agents.lock", "a") as lock:
                with self.assertRaises(BlockingIOError):
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return run(argv, **kwargs)

        with patch("fab.log.append", side_effect=rejected):
            findings = gates.screen(self.task, self.events, sh=locked_git, log_path=self.path)
        self.assertEqual(findings, [Finding("files", "`extra.md` is outside the task's files")])
        records = log.read(self.path)
        self.assertEqual(len(records), 1)
        self.assertEqual({key: value for key, value in records[0].items() if key != "ts"},
                         dict(ev="branch.rejected", task=self.task.id, branch="draft/task-r1",
                              tip=tip, step="gate:files", log=str(self.digest),
                              findings=findings_text(findings)))
        self.assertTrue(self.digest.is_file())
        self.assertEqual(log.read(), [])
        self.assertEqual(state.fold({self.task.id: self.task}, self.events + records)[self.task.id].status,
                         "rejected")

    def test_parse_failure_rejects_without_digest(self):
        tip = self.push(text="def x(:\n")
        findings = gates.screen(self.task, self.events, log_path=self.path)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].gate, "parse")
        self.assertIn("/tip/fab/x.py:1` invalid syntax", findings[0].text)
        record, = log.read(self.path)
        self.assertEqual((record["step"], record["log"], record["tip"]), ("gate:parse", "", tip))
        self.assertEqual(record["findings"], findings_text(findings))
        self.assertFalse(self.digest.exists())
        self.assertEqual(sorted(p.name for p in log.home().iterdir()), ["land-agents.lock", "repos"])

    def test_no_task_run_raises_before_commands_or_files(self):
        fake = FakeRunner()
        with self.assertRaisesRegex(ValueError, self.task.id):
            gates.screen(self.task, self.events[-1:], sh=fake, log_path=self.path)
        self.assertEqual(fake.calls, [])
        self.assertFalse((log.home() / "land-agents.lock").exists())
        self.assertEqual(log.read(self.path), [])

    def test_missing_origin_branch_raises_without_digest_or_log(self):
        with self.assertRaises(Failed):
            gates.screen(self.task, self.events, log_path=self.path)
        self.assertFalse(self.digest.exists())
        self.assertEqual(log.read(self.path), [])
        self.assertEqual(log.read(), [])

    def test_missing_clone_uses_repository_remote(self):
        self.push()
        shutil.rmtree(self.repo)
        with patch.dict(runs.REMOTES, agents=str(self.origin)):
            self.assertEqual(gates.screen(self.task, self.events, log_path=self.path), [])
        self.assertEqual(git(self.repo, "remote", "get-url", "origin"), str(self.origin))
        self.assertTrue(self.digest.is_file())

    def test_git_failure_never_writes_digest_or_rejection(self):
        for command in ("fetch", "rev-parse", "merge-base", "diff", "archive"):
            with self.subTest(command=command):
                fake = FakeRunner().on(["git", command], Result(1, err="git failed"))
                with self.assertRaises(Failed):
                    gates.screen(self.task, self.events, sh=fake, log_path=self.path)
                self.assertFalse(self.digest.exists())
                self.assertEqual(log.read(self.path), [])
                self.assertFalse(any(p.name.startswith("tmp") for p in log.home().iterdir()))
