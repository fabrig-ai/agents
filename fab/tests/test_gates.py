import unittest
from dataclasses import replace
from pathlib import Path

from fab.calls import Signature
from fab.digest import Clone, Digest, Function
from fab.gates import Finding, banned_names, check, findings_text, words
from fab.plan import Task
from fab.run import brief
from fab.tests.support import tmp_home


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
