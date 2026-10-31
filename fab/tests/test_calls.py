"""Calls use compiled briefs and a fake Claude (docs/design/fab.md, 8 and 10)."""

from __future__ import annotations

import io
import json
import os
import unittest
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

from fab import call_review, calls, channel, cli, log
from fab.plan import Part, Plan, Question, Slice, Task, load_tasks
from fab.sh import Failed, Result
from fab.tests.support import FakeRunner, tmp_home

ROOT = Path(__file__).resolve().parents[2]


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    sibling = path.with_name(path.name + ".tmp")
    sibling.write_text(text, encoding="utf-8")
    sibling.replace(path)


def fixture(root):
    parts = {
        "base": Part("base", "Base primitives", "feature", (), "design.md, 1"),
        "core": Part("core", "Call core", "feature", ("base",), "design.md, 2 and 8"),
        "next": Part("next", "Next part", "probe", ("core",), "design.md, 3"),
    }
    plan = Plan("demo", "agents", (), 1.0, 2.0, parts,
                (Slice(1, "Build the core", ("base", "core"), True),
                 Slice(2, "Explore next", ("next",), False)))
    tasks = {}
    for name, part in (("one", "base"), ("two", "base"), ("three", "core")):
        path = f"docs/plan/demo/tasks/{name}.md"
        spec = (f'+++\nid = "{name}"\npart = "{part}"\nkind = "feature"\n'
                f'files = ["fab/{name}.py"]\n+++\n# Spec {name}\nDo {name}.\n')
        write(root / path, spec)
        tasks[f"demo/{name}"] = Task(f"demo/{name}", part, "feature", "agents", (),
                                      (f"fab/{name}.py",), "high", 25, f"# Spec {name}\nDo {name}.\n", path)
    write(root / "design.md", "# Full design\n\n## 1. First\nContract.\n\n## 8. Last\nKeep all sections.\n")
    write(root / "fab/api.py", 'def primitive(value: int) -> str:\n    """Existing primitive."""\n    return str(value)\n')
    write(root / "docs/plan/demo/plan.toml", '\n'.join([
        'draft = "demo"', 'repo = "agents"',
        *[f'[[part]]\nid = "{part.id}"\ntitle = "{part.title}"\nmode = "{part.mode}"\n'
          f'needs = {json.dumps(part.needs)}\ndesign = "{part.design}"' for part in parts.values()],
        '[[slice]]\nid = 1\nstory = "Build the core"\nparts = ["base", "core", "next"]\nwalk = true',
    ]))
    return plan, tasks


class InventoryTest(unittest.TestCase):
    def test_public_functions_classes_methods_annotations_and_order(self):
        with tmp_home() as root:
            write(root / "pkg/a.py", '''def first(a: int, /, b: str = "x", *args: bytes, flag: bool = True, **kw: float) -> list[str]:
    """First line.

    More details.
    """
    def nested(): pass

class Public:
    """Public class."""
    def __init__(self): pass
    def _hidden(self): pass
    async def fetch(self, value: int) -> str:
        """Fetch one value."""
        pass

class _Private:
    def visible(self): pass

def _private(): pass
''')
            write(root / "pkg/z.py", "def last(): pass\n")
            write(root / "pkg/test_ignore.py", "invalid syntax !")
            write(root / "pkg/api_test.py", "invalid syntax !")
            write(root / "pkg/tests/test_nested.py", "invalid syntax !")
            entries = calls.inventory(root, "pkg")
            self.assertEqual([(item.module, item.name) for item in entries],
                             [("pkg/a.py", "first"), ("pkg/a.py", "Public"),
                              ("pkg/a.py", "Public.fetch"), ("pkg/z.py", "last")])
            self.assertEqual(entries[0].text, "def first(a: int, /, b: str='x', *args: bytes, flag: bool=True, **kw: float) -> list[str]")
            self.assertEqual(entries[0].doc, "First line.")
            self.assertEqual(entries[1].text, "class Public")
            self.assertEqual(entries[2].text, "async def fetch(self, value: int) -> str")
            self.assertEqual(entries[-1].doc, "")

    def test_repository_inventory_includes_log_append(self):
        with tmp_home():
            entries = calls.inventory(ROOT)
        append = next(item for item in entries if (item.module, item.name) == ("fab/log.py", "append"))
        self.assertIn("path: Path | None=None", append.text)
        self.assertIn("Append one record", append.doc)
        self.assertTrue(all("tests/" not in item.module for item in entries))

    def test_render_inventory(self):
        entries = [calls.Signature("fab/a.py", "a", "def a()", "A."),
                   calls.Signature("fab/a.py", "b", "class B", "B."),
                   calls.Signature("fab/z.py", "z", "def z()", "")]
        self.assertEqual(calls.render_inventory(iter(entries)),
                         "## fab/a.py\n\n- `def a()` — A.\n- `class B` — B.\n\n## fab/z.py\n\n- `def z()` — ")
        self.assertEqual(calls.render_inventory([]), "")

    def test_design_text_found_and_missing(self):
        with tmp_home() as root:
            write(root / "design.md", "# Design\nAll sections.\n")
            self.assertEqual(calls.design_text(root, "design.md, 6 and 8"), "# Design\nAll sections.\n")
            note = calls.design_text(root, "missing.md, 2")
            self.assertIn("missing.md", note)
            self.assertEqual(len(note.splitlines()), 1)
            write(root / "broken.md", "unused")
            sibling = root / "broken.tmp"
            sibling.write_bytes(b"\xff")
            sibling.replace(root / "broken.md")
            self.assertIn("Design unavailable", calls.design_text(root, "broken.md"))


class ReviewHistoryTest(unittest.TestCase):
    def test_last_review_uses_start_timestamp_and_matching_done_outcome(self):
        failed = {"ev": "call.started", "role": "review", "call": "failed", "ts": "003"}
        done = {"ev": "call.started", "role": "review", "call": "done", "ts": "001"}
        events = [done, {"ev": "call.ended", "call": "done", "outcome": "done", "ts": "002"},
                  failed, {"ev": "call.ended", "call": "failed", "outcome": "failed", "ts": "004"}]
        self.assertIsNone(calls.last_review([]))
        self.assertIsNone(calls.last_review([failed], done=True))
        self.assertEqual(calls.last_review([failed]), "003")
        self.assertEqual(calls.last_review(iter(events)), "003")
        self.assertEqual(calls.last_review(iter(events), done=True), "001")
        events.append({"ev": "call.started", "role": "answer", "call": "answer", "ts": "005"})
        events.append({"ev": "call.ended", "call": "answer", "outcome": "done", "ts": "006"})
        self.assertEqual(calls.last_review(events, done=True), "001")
        events.append({"ev": "call.started", "role": "review", "call": "running", "ts": "007"})
        self.assertEqual(calls.last_review(events), "007")
        self.assertEqual(calls.last_review(events, done=True), "001")

    def test_landed_after_filters_tasks_and_timestamp_in_log_order(self):
        tasks = {"demo/one": object(), "demo/two": object()}
        first = {"ev": "branch.landed", "task": "demo/two", "ts": "001"}
        second = {"ev": "branch.landed", "task": "demo/one", "ts": "003"}
        events = [first, {"ev": "branch.landed", "task": "other/one", "ts": "004"},
                  {"ev": "run.started", "task": "demo/one", "ts": "002"}, second]
        self.assertEqual(calls.landed_after(iter(events), tasks, None), [first, second])
        self.assertEqual(calls.landed_after(events, tasks, "001"), [second])
        self.assertEqual(calls.landed_after(events, tasks, "003"), [])


class BriefTest(unittest.TestCase):
    def test_skeleton_sections_full_specs_and_part_statuses(self):
        with tmp_home() as root:
            plan, tasks = fixture(root)
            text = calls.skeleton_brief(plan, "core", tasks,
                                        {"demo/one": "landed", "demo/two": "landed"}, root,
                                        call_id="c1", branch="calls/c1", report="/reports/c1.md")
            for fragment in (calls.ROLES["skeleton"].read_text(), "Call: c1", "calls/c1", "/reports/c1.md",
                             "Plan: demo", "Repository: agents", "| base | Base primitives | feature | - | done |",
                             "| core | Call core | feature | base | designed |",
                             "| next | Next part | probe | core | not designed |",
                             "| 1 | Build the core | base, core | True |", "Explore next",
                             "- Id: core", "- Title: Call core", "- Mode: feature", "- Needs: base",
                             "- Design: design.md, 2 and 8", (root / "design.md").read_text(),
                             "## fab/api.py", "def primitive(value: int) -> str", "Existing primitive.",
                             (root / tasks["demo/one"].path).read_text(),
                             (root / tasks["demo/two"].path).read_text()):
                self.assertIn(fragment, text)
            self.assertNotIn("# Spec three", text)
            partial = calls.skeleton_brief(plan, "core", tasks, {"demo/one": "landed", "demo/two": "done"},
                                           root, call_id="c", branch="b", report="r")
            self.assertIn("| base | Base primitives | feature | - | designed |", partial)

    def test_skeleton_and_contract_show_marker_readers_and_all_questions_in_order(self):
        with tmp_home() as root:
            plan, tasks = fixture(root)
            plan.parts["base"] = replace(plan.parts["base"], contract=True)
            plan.parts["next"] = replace(plan.parts["next"], needs=("base", "core"))
            plan = replace(plan, questions=(Question("z", "Which budget?", ("base",)),
                                            Question("other", "Unrelated?", ("core",)),
                                            Question("a", "Which format?", ("base",), "TOML")))
            for role in ("skeleton", "contract"):
                with self.subTest(role=role):
                    text = calls.skeleton_brief(plan, "base", tasks, {}, root,
                                                call_id="c", branch="b", report="r", role=role)
                    self.assertIn(calls.ROLES[role].read_text(), text)
                    details = text.split("# Part to design\n\n")[1].split("\n\n# ")[0]
                    expected = ("- Id: base\n- Title: Base primitives\n- Mode: feature\n"
                                "- Needs: (none)\n- Design: design.md, 1\n- Contract: yes\n")
                    if role == "contract":
                        expected += "- Readers: core, next\n"
                    expected += ("- Question z: Which budget?\n  Answer: (open)\n"
                                 "- Question a: Which format?\n  Answer: TOML")
                    self.assertEqual(details, expected)
            text = calls.skeleton_brief(plan, "next", tasks, {}, root,
                                        call_id="c", branch="b", report="r", role="contract")
            self.assertIn("- Readers: (none)", text)
            self.assertNotIn("- Contract: yes", text)

    def test_skeleton_refuses_another_role(self):
        with tmp_home() as root:
            plan, tasks = fixture(root)
            with self.assertRaisesRegex(ValueError, "role"):
                calls.skeleton_brief(plan, "core", tasks, {}, root,
                                     call_id="c", branch="b", report="r", role="answer")

    def test_absolute_spec_paths_are_presented_relative_to_the_checkout(self):
        with tmp_home() as root:
            plan, _ = fixture(root)
            tasks = load_tasks(root / "docs/plan/demo/tasks", plan.draft, plan.repo)
            skeleton = calls.skeleton_brief(plan, "core", tasks, {}, root, call_id="c", branch="b", report="r")
            answer = calls.answer_brief([{"task": "demo/one", "run": "demo/one-1", "text": "Choose?"}],
                                         tasks, root, call_id="c", branch="b", report="r")
            for text in (skeleton, answer):
                self.assertIn("(docs/plan/demo/tasks/one.md)", text)
                self.assertNotIn(f"({root}/docs/plan", text)
                self.assertIn("# Spec one", text)

    def test_skeleton_limit_names_largest_section(self):
        with tmp_home() as root:
            plan, tasks = fixture(root)
            write(root / "design.md", "x" * calls.BRIEF_LIMIT)
            with self.assertRaisesRegex(ValueError, "BRIEF_LIMIT.*largest section: Cited design"):
                calls.skeleton_brief(plan, "core", tasks, {}, root, call_id="c", branch="b", report="r")

    def test_review_sections_digests_shared_design_and_missing_digest(self):
        with tmp_home() as root:
            plan, tasks = fixture(root)
            write(log.home() / "digests/demo/one-1.md", "Stale digest")
            write(log.home() / "digests/demo/one-2.md", "# Digest: public changes\nKeep this text.")
            write(log.home() / "digests/demo/one-3.md", "Future digest")
            events = [
                {"ev": "run.started", "task": "demo/one", "run": "demo/one-1"},
                {"ev": "run.started", "task": "demo/one", "run": "demo/one-2"},
                {"ev": "branch.landed", "task": "demo/one", "branch": "demo/one-r1",
                 "main": "1234567890abcdef", "tip": "tip-one", "ts": "001"},
                {"ev": "run.started", "task": "demo/one", "run": "demo/one-3"},
                {"ev": "branch.landed", "task": "demo/three", "branch": "demo/three",
                 "main": "fedcba0987654321", "tip": "tip-three", "ts": "002"},
            ]
            for has_run in (False, True):
                with self.subTest(has_run=has_run):
                    history = events[:]
                    if has_run:
                        history.insert(-1, {"ev": "run.started", "task": "demo/three", "run": "demo/three-1"})
                    text = calls.review_brief(plan, tasks, history, root,
                                              call_id="r1", branch="calls/r1", report="/review.md")
                    for section in ("Role", "Call facts", "Plan parts and slices",
                                    "Landed since the last review", "Taste", "Designs", "Inventory"):
                        self.assertIn(f"# {section}\n\n", text)
                    for fragment in (calls.ROLES["review"].read_text(), "Call: r1", "calls/r1", "/review.md",
                                     "Plan: demo", "Repository: agents", "Specs: docs/plan/demo/tasks/",
                                     "| base | Base primitives | feature | - | designed |",
                                     "| core | Call core | feature | base | done |",
                                     "| next | Next part | probe | core | not designed |",
                                     "| 1 | Build the core | base, core | True |", "Explore next",
                                     "## demo/one (`demo/one-r1`, main `1234567890ab`)",
                                     "## demo/three (`demo/three`, main `fedcba098765`)",
                                     "# Digest: public changes\nKeep this text.", "(no digest)",
                                     calls.TASTE.read_text(), "Existing primitive."):
                        self.assertIn(fragment, text)
                    self.assertLess(text.index("## demo/one"), text.index("## demo/three"))
                    self.assertEqual(text.count("## design.md\n"), 1)
                    self.assertEqual(text.count((root / "design.md").read_text()), 1)
                    self.assertNotIn("Stale digest", text)
                    self.assertNotIn("Future digest", text)

    def test_review_empty_and_done_review_cutoff(self):
        with tmp_home() as root:
            plan, tasks = fixture(root)
            first = {"ev": "branch.landed", "task": "demo/one", "branch": "demo/one",
                     "main": "m1", "tip": "tip-one", "ts": "001"}
            events = [first, {"ev": "call.started", "role": "review", "call": "done", "ts": "002"},
                      {"ev": "branch.landed", "task": "demo/three", "branch": "demo/three",
                       "main": "m2", "tip": "tip-three", "ts": "003"},
                      {"ev": "call.ended", "call": "done", "outcome": "done", "ts": "004"},
                      {"ev": "call.started", "role": "review", "call": "failed", "ts": "005"},
                      {"ev": "call.ended", "call": "failed", "outcome": "failed", "ts": "006"}]
            text = calls.review_brief(plan, tasks, events, root, call_id="c", branch="b", report="r")
            self.assertNotIn("## demo/one", text)
            self.assertIn("## demo/three", text)
            empty = calls.review_brief(plan, tasks, [], root, call_id="c", branch="b", report="r")
            self.assertIn("# Landed since the last review\n\n(none)", empty)
            self.assertNotIn("# Full design", empty)

    def test_review_limit_names_largest_section(self):
        with tmp_home() as root:
            plan, tasks = fixture(root)
            write(log.home() / "digests/run.md", "x" * calls.BRIEF_LIMIT)
            events = [{"ev": "run.started", "task": "demo/one", "run": "run"},
                      {"ev": "branch.landed", "task": "demo/one", "branch": "branch",
                       "main": "main", "tip": "tip", "ts": "001"}]
            with self.assertRaisesRegex(ValueError, "BRIEF_LIMIT.*largest section: Landed since the last review"):
                calls.review_brief(plan, tasks, events, root, call_id="c", branch="b", report="r")

    def test_answer_sections_and_empty_questions(self):
        with tmp_home() as root:
            _, tasks = fixture(root)
            question = {"task": "demo/one", "run": "demo/one-1", "text": "Question: which type?"}
            text = calls.answer_brief([question], tasks, root, call_id="a1", branch="calls/a1", report="/answer.md")
            for fragment in (calls.ROLES["answer"].read_text(), "Call: a1", "calls/a1", "/answer.md",
                             "Task: demo/one", "Run: demo/one-1", question["text"],
                             str(root / "fab/runs/demo/one-1/report.md"),
                             (root / tasks["demo/one"].path).read_text(), "# Inventory", "Existing primitive."):
                self.assertIn(fragment, text)
            empty = calls.answer_brief([], tasks, root, call_id="a", branch="b", report="r")
            self.assertIn("# Inventory", empty)
            self.assertNotIn("# Question:", empty)

    def test_answer_limit(self):
        with tmp_home() as root:
            _, tasks = fixture(root)
            question = {"task": "demo/one", "run": "demo/one-1", "text": "x" * calls.BRIEF_LIMIT}
            with self.assertRaisesRegex(ValueError, "largest section: Question: demo/one"):
                calls.answer_brief([question], tasks, root, call_id="a", branch="b", report="r")

    def test_open_questions_answers_clear_only_earlier_questions_for_task(self):
        def asked(task, run):
            return {"ev": "question.asked", "task": task, "run": run, "text": "Choose?"}
        first, other, again, last = asked("a", "a-1"), asked("b", "b-1"), asked("a", "a-2"), asked("a", "a-3")
        events = [{"ev": "question.answered", "task": "a"}, first, other, again,
                  {"ev": "run.ended", "task": "b"}, {"ev": "question.answered", "task": "a"}, last]
        self.assertEqual(calls.open_questions(iter(events)), [other, last])
        self.assertEqual(calls.open_questions([first, again]), [first, again])
        self.assertEqual(calls.open_questions([]), [])

    def test_claude_argv(self):
        brief, worktree = Path("/a b's/brief.md"), Path("/work tree")
        argv = calls.claude_argv(brief, worktree)
        self.assertEqual(argv[:2], ["claude", "-p"])
        self.assertEqual(argv[3:], ["--model", calls.MODEL, "--effort", "high", "--output-format", "json",
                                    "--dangerously-skip-permissions", f"--add-dir={worktree}"])
        self.assertEqual(calls.claude_argv(brief, worktree, effort="medium")[6], "medium")
        self.assertEqual((calls.role_effort("answer"), calls.role_effort("skeleton")), ("medium", "high"))
        self.assertEqual(len(argv[2].splitlines()), 1)
        self.assertIn("Read and follow", argv[2])
        self.assertIn("brief.md", argv[2])
        self.assertEqual(calls.claude_argv(brief, worktree, model="another")[4], "another")


class StartTest(unittest.TestCase):
    def test_start_commands_artifacts_events_usage_and_outcome(self):
        with tmp_home() as root:
            plan, tasks = fixture(root)
            text = calls.skeleton_brief(plan, "core", tasks, {}, root,
                                        call_id="preview", branch="preview", report="preview")
            result_json = json.dumps({"usage": {"input_tokens": 23, "cache_read_input_tokens": 50, "output_tokens": 9}})

            def claude(call):
                directory = Path(call.cwd).parent
                brief = (directory / "brief.md").read_text()
                self.assertIn(f"Call: {directory.name}", brief)
                self.assertIn(f"calls/{directory.name}", brief)
                self.assertIn(str(directory / "report.md"), brief)
                self.assertNotIn("preview", brief)
                self.assertIn("# Inventory", brief)
                self.assertNotIn(channel.SECTION, brief)
                self.assertIn((root / tasks["demo/one"].path).read_text(), brief)
                self.assertEqual([event["ev"] for event in log.read(root / "custom.jsonl")], ["call.started"])
                write(directory / "report.md", "\nDone: designed core\nDetails.\n")
                return Result(0, result_json, "Claude diagnostic\n")

            fake = FakeRunner().on(["claude"], claude)
            runner = Mock(wraps=fake)
            with patch.object(calls.time, "monotonic", side_effect=[100.0, 190.0]):
                result = calls.start("skeleton", "demo/core", root, text, sh=runner, log_path=root / "custom.jsonl")
            directory = root / "fab/calls" / result["call"]
            self.assertEqual(result, {"call": directory.name, "branch": f"calls/{directory.name}",
                                      "outcome": "done", "report": str(directory / "report.md")})
            self.assertEqual(fake.argvs(), [
                ["git", "worktree", "add", "-b", result["branch"], str(directory / "wt"), "origin/main"],
                calls.claude_argv(directory / "brief.md", directory / "wt"),
                ["git", "worktree", "remove", "--force", str(directory / "wt")],
            ])
            self.assertEqual([call.cwd for call in fake.calls], [str(root), str(directory / "wt"), str(root)])
            self.assertEqual(runner.call_args_list[1].kwargs["timeout"], calls.TIMEOUT)
            self.assertEqual((directory / "result.json").read_text(), result_json)
            self.assertEqual((directory / "stderr.log").read_text(), "Claude diagnostic\n")
            started, ended = log.read(root / "custom.jsonl")
            self.assertEqual({key: value for key, value in started.items() if key != "ts"},
                             {"ev": "call.started", "call": directory.name, "role": "skeleton",
                              "subject": "demo/core", "branch": result["branch"]})
            self.assertEqual({key: value for key, value in ended.items() if key != "ts"},
                             {"ev": "call.ended", "call": directory.name, "role": "skeleton", "subject": "demo/core",
                              "outcome": "done", "tokens": "23/50/9", "minutes": 1.5})

    def test_start_binds_subject_answers_after_facts_before_next_section_or_end(self):
        for tail in ("", "\n\n# The task\n\nKeep the task.\n"):
            with self.subTest(tail=tail), tmp_home() as root:
                path = root / "custom/log.jsonl"
                log.append(channel.ANSWERED, path=path, subject="demo/core", call="earlier",
                           question="Which host?", by="user", answer="Use hel8")
                log.append(channel.ANSWERED, subject="demo/core", answer="Wrong log")
                log.append(channel.ANSWERED, path=path, subject="other", answer="Wrong subject")
                fake = FakeRunner().on(["claude"], Result(0, "{}"))
                result = calls.start("skeleton", "demo/core", root, "# Call facts\n\npreview" + tail,
                                     sh=fake, log_path=path)
                brief = (log.home() / "calls" / result["call"] / "brief.md").read_text()
                expected = ("# Call facts\n\n" + calls._facts(result["call"], result["branch"], result["report"])
                            + "\n\n" + channel.SECTION + "\n\n"
                            + channel.answers_text("demo/core", log.read(path)) + tail)
                self.assertEqual(brief, expected)
                self.assertIn("Question: Which host?\nAnswer (user): Use hel8", brief)
                self.assertNotIn("Wrong", brief)

    def test_start_on_existing_branch_fetches_and_records_amends(self):
        with tmp_home() as root:
            branch = "calls/root"

            def claude(call):
                directory = Path(call.cwd).parent
                brief = (directory / "brief.md").read_text()
                self.assertIn(f"- Call: {directory.name}", brief)
                self.assertIn(f"- Branch: `{branch}`", brief)
                self.assertIn(str(directory / "report.md"), brief)
                write(directory / "report.md", "Done: amended\n")
                return Result(0, "{}")

            fake = FakeRunner().on(["claude"], claude)
            result = calls.start("amend", "demo/core", root, "# Call facts\n\npreview\n\n# Findings\nFix it.\n",
                                 sh=fake, branch=branch, amends="root")
            directory = root / "fab/calls" / result["call"]
            self.assertEqual(result["branch"], branch)
            self.assertEqual(result["outcome"], "done")
            self.assertTrue(result["call"].startswith("amend-"))
            self.assertNotEqual(result["call"], "root")
            self.assertEqual(calls.ROLES["amend"], call_review.AMENDER)
            self.assertEqual(fake.argvs(), [
                ["git", "fetch", "origin"],
                ["git", "worktree", "add", "-B", branch, str(directory / "wt"), f"origin/{branch}"],
                calls.claude_argv(directory / "brief.md", directory / "wt"),
                ["git", "worktree", "remove", "--force", str(directory / "wt")],
            ])
            self.assertEqual([call.cwd for call in fake.calls],
                             [str(root), str(root), str(directory / "wt"), str(root)])
            first, last = log.read()
            self.assertEqual((first["amends"], first["subject"], first["branch"]),
                             ("root", "demo/core", branch))
            self.assertEqual(first["call"], last["call"])
            self.assertEqual(last["outcome"], "done")

    def test_fetch_failure_on_existing_branch_starts_nothing(self):
        with tmp_home() as root:
            fake = FakeRunner().on(["git", "fetch"], Result(1, err="offline"))
            with self.assertRaises(Failed):
                calls.start("amend", "demo/core", root, "Brief.", sh=fake,
                            branch="calls/root", amends="root")
            self.assertEqual(fake.argvs(), [["git", "fetch", "origin"]])
            self.assertEqual(log.read(), [])

    def test_claude_receives_environment_without_nested_session_markers(self):
        with tmp_home() as root:
            environment = {"HOME": str(root), "FAB_HOME": str(root / "fab"),
                           "PATH": "/fake/bin", "KEEP_ME": "yes", "CLAUDECODE": "1",
                           "CLAUDECODE_EXTRA": "nested", "CLAUDE_CODE_SESSION": "nested",
                           "CLAUDE_CODE_": "nested", "CLAUDE_OTHER": "keep"}
            fake = FakeRunner()
            runner = Mock(wraps=fake)
            with patch.dict(os.environ, environment, clear=True):
                result = calls.start("answer", "demo", root, "Brief.", sh=runner)
                self.assertEqual(dict(os.environ), environment)
            expected = {key: value for key, value in environment.items()
                        if key in ("HOME", "FAB_HOME", "PATH", "KEEP_ME", "CLAUDE_OTHER")}
            self.assertEqual(runner.call_args_list[1].kwargs["env"], expected)
            self.assertNotIn("env", runner.call_args_list[0].kwargs)
            self.assertNotIn("env", runner.call_args_list[2].kwargs)
            self.assertEqual((Path(result["report"]).parent / "stderr.log").read_text(), "")

    def test_missing_report_fails_and_malformed_or_missing_usage_is_zero(self):
        for output, tokens in (("not JSON", "0/0/0"), ("{}", "0/0/0"), ("[]", "0/0/0"),
                               ('{"usage": null}', "0/0/0"), ('{"usage": {"output_tokens": 4}}', "0/0/4")):
            with self.subTest(output=output), tmp_home() as root:
                fake = FakeRunner().on(["claude"], Result(1, output, "failed"))
                result = calls.start("answer", "demo", root, "Brief.", sh=fake)
                self.assertEqual(result["outcome"], "failed")
                self.assertFalse(Path(result["report"]).exists())
                self.assertEqual((Path(result["report"]).parent / "stderr.log").read_text(), "failed")
                self.assertEqual(log.read()[-1]["tokens"], tokens)
                self.assertEqual(fake.argvs()[-1][:4], ["git", "worktree", "remove", "--force"])

    def test_report_sets_outcome_even_when_claude_exits_nonzero(self):
        for prefix, expected in (("Question", "question"), ("Infra", "infra"), ("Failed", "failed"), ("Unexpected", "failed")):
            with self.subTest(prefix=prefix), tmp_home() as root:
                def claude(call):
                    write(Path(call.cwd).parent / "report.md", f"{prefix}: details\n")
                    return Result(1, "{}")
                result = calls.start("answer", "demo", root, "Brief.", sh=FakeRunner().on(["claude"], claude))
                self.assertEqual(result["outcome"], expected)
                self.assertEqual(log.read()[-1]["outcome"], expected)

    def test_worktree_removed_when_runner_raises(self):
        with tmp_home() as root:
            def fail(call):
                raise OSError("cannot launch Claude")
            fake = FakeRunner().on(["claude"], fail)
            with self.assertRaisesRegex(OSError, "cannot launch"):
                calls.start("answer", "demo", root, "Brief.", sh=fake)
            self.assertEqual(fake.argvs()[-1][:4], ["git", "worktree", "remove", "--force"])

    def test_worktree_creation_failure_never_launches_claude(self):
        with tmp_home() as root:
            fake = FakeRunner().on(["git", "worktree", "add"], Result(1, err="cannot add"))
            with self.assertRaises(Failed):
                calls.start("answer", "demo", root, "Brief.", sh=fake)
            self.assertEqual(len(fake.calls), 1)
            self.assertEqual(log.read(), [])

    def test_invalid_role_does_not_start(self):
        with tmp_home() as root:
            fake = FakeRunner()
            with self.assertRaisesRegex(ValueError, "unknown call role"):
                calls.start("unknown", "demo", root, "Brief.", sh=fake)
            self.assertEqual(fake.calls, [])


class MainTest(unittest.TestCase):
    def test_brief_only_for_all_roles_through_cli(self):
        for role in ("skeleton", "answer", "review"):
            with self.subTest(role=role), tmp_home() as root:
                fixture(root)
                log.append("question.asked", task="demo/one", run="demo/one-1", text="Which type?")
                log.append(channel.ANSWERED, subject="demo/core", answer="Bound only when starting")
                log.append("question.asked", task="other/task", run="other/task-1", text="Other plan")
                fake = FakeRunner().on(["git", "rev-parse"], Result(0, str(root) + "\n"))
                argv = ["call", role, *(["core"] if role == "skeleton" else []),
                        "--plan", str(root / "docs/plan/demo"), "--brief-only"]
                output = io.StringIO()
                with patch.object(calls, "run", fake), patch.object(calls, "start") as start, redirect_stdout(output):
                    self.assertEqual(cli.main(argv), 0)
                start.assert_not_called()
                text = output.getvalue()
                self.assertIn(calls.ROLES[role].read_text(), text)
                self.assertIn("# Call facts", text)
                self.assertNotIn(channel.SECTION, text)
                self.assertNotIn("Bound only when starting", text)
                self.assertIn("Existing primitive.", text)
                if role == "answer":
                    self.assertIn("Which type?", text)
                    self.assertNotIn("Other plan", text)
                self.assertEqual(fake.argvs(), [["git", "rev-parse", "--show-toplevel"]])
                self.assertEqual(fake.calls[0].cwd, str(root / "docs/plan/demo"))

    def test_answer_brief_only_lists_queued_questions_with_foreman_reports(self):
        with tmp_home() as root:
            fixture(root)
            for name in ("four", "five"):
                write(root / f"docs/plan/demo/tasks/{name}.md",
                      f'+++\nid = "{name}"\npart = "base"\nkind = "feature"\n+++\nSpec {name}.\n')
            for name, status in (("one", "queued"), ("two", "foreman"), ("three", "deciding"),
                                 ("four", "settled"), ("five", "parked")):
                task_id, run_id = f"demo/{name}", f"demo/{name}-1"
                if status != "parked":
                    log.append("run.started", task=task_id, run=run_id, kind="implement")
                    log.append("run.ended", task=task_id, run=run_id, outcome="question")
                log.append("question.asked", task=task_id, run=run_id, text=f"Choose for {name}?")
                if status in ("queued", "deciding", "settled"):
                    foreman = f"{task_id}/foreman-1"
                    log.append("run.started", task=f"{task_id}/foreman", run=foreman,
                               kind="foreman", asked=run_id)
                    if status != "deciding":
                        log.append("run.ended", task=f"{task_id}/foreman", run=foreman,
                                   outcome="done" if status == "settled" else "failed",
                                   report=str(log.home() / "runs" / foreman / "report.md"))
            log.append("question.asked", task="other/task", run="other/task-1", text="Other plan")
            fake = FakeRunner().on(["git", "rev-parse"], Result(0, str(root)))
            output = io.StringIO()
            with patch.object(calls, "run", fake), patch.object(calls, "start") as start, redirect_stdout(output):
                self.assertEqual(calls.main(["answer", "--plan", str(root / "docs/plan/demo"),
                                             "--brief-only"]), 0)
            start.assert_not_called()
            text = output.getvalue()
            self.assertIn("Choose for one?", text)
            self.assertIn("Choose for five?", text)
            for name in ("two", "three", "four"):
                self.assertNotIn(f"Choose for {name}?", text)
            self.assertNotIn("Other plan", text)
            self.assertIn(f"- Report: `{log.home()}/runs/demo/one-1/report.md`\n"
                          f"- Foreman: `{log.home()}/runs/demo/one/foreman-1/report.md`\n", text)
            self.assertEqual(text.count("- Foreman:"), 1)
            self.assertIn(f"- Report: `{log.home()}/runs/demo/five-1/report.md`\n\nChoose for five?", text)
            self.assertEqual(fake.argvs(), [["git", "rev-parse", "--show-toplevel"]])

    def test_main_runs_compiled_brief_and_returns_report_status(self):
        for role, outcome, code in (("skeleton", "done", 0), ("answer", "question", 1), ("review", "done", 0)):
            with self.subTest(role=role), tmp_home() as root:
                fixture(root)
                fake = FakeRunner().on(["git", "rev-parse"], Result(0, str(root)))
                result = {"outcome": outcome, "branch": "calls/id"}
                output = io.StringIO()
                argv = [role, *(["core"] if role == "skeleton" else []), "--plan", str(root / "docs/plan/demo")]
                with patch.object(calls, "run", fake), patch.object(calls, "start", return_value=result) as start, redirect_stdout(output):
                    self.assertEqual(calls.main(argv), code)
                subject = {"skeleton": "demo/core", "answer": "demo", "review": "demo/review"}[role]
                self.assertEqual(start.call_args.args[:3], (role, subject, root))
                self.assertIn("# Inventory", start.call_args.args[3])
                self.assertIs(start.call_args.kwargs["sh"], fake)
                self.assertEqual(output.getvalue(), f"{outcome} calls/id\n")

    def amend_chain(self):
        log.append("call.started", call="root", role="answer", subject="demo", branch="calls/root")
        log.append("call.ended", call="root", outcome="done")
        log.append("run.started", run="root-1", task="root", kind="review")
        log.append("run.ended", run="root-1", outcome="failed")

    def test_main_amend_brief_only_uses_chain_and_refusal(self):
        with tmp_home() as root:
            fixture(root)
            self.amend_chain()
            write(log.home() / "runs/root-1/report.md", "Failed: fix the signature\n")
            fake = FakeRunner().on(["git", "rev-parse"], Result(0, str(root)))
            output = io.StringIO()
            with patch.object(calls, "run", fake), patch.object(calls, "start") as start, redirect_stdout(output):
                self.assertEqual(calls.main(["amend", "root", "--plan", str(root / "docs/plan/demo"),
                                             "--brief-only"]), 0)
            start.assert_not_called()
            self.assertEqual(output.getvalue(), call_review.amend_brief(
                call_review.chains(log.read())["root"], call_id="(assigned at start)",
                branch="(assigned at start)", report="(assigned at start)") + "\n")
            self.assertIn("fix the signature", output.getvalue())
            self.assertEqual(fake.argvs(), [["git", "rev-parse", "--show-toplevel"]])

    def test_main_amend_runs_on_chain_branch_and_subject(self):
        with tmp_home() as root:
            fixture(root)
            self.amend_chain()
            fake = FakeRunner().on(["git", "rev-parse"], Result(0, str(root)))
            with patch.object(calls, "run", fake), redirect_stdout(io.StringIO()), \
                 patch.object(calls, "start", return_value={"outcome": "done", "branch": "calls/root"}) as start:
                self.assertEqual(calls.main(["amend", "root", "--plan", str(root / "docs/plan/demo")]), 0)
            self.assertEqual(start.call_args.args[:3], ("amend", "demo", root))
            self.assertEqual(start.call_args.kwargs, dict(sh=fake, branch="calls/root", amends="root"))

    def test_main_amend_refuses_unknown_root_and_every_other_state(self):
        for status in ("unknown", *[state for state in call_review.STATES if state != "amend"]):
            with self.subTest(status=status), tmp_home() as root:
                fixture(root)
                chain = call_review.Chain("root", "answer", "demo", "calls/root", ("root",), "root", (), status)
                fake = FakeRunner().on(["git", "rev-parse"], Result(0, str(root)))
                errors = io.StringIO()
                with patch.object(calls, "run", fake), patch.object(calls, "start") as start, \
                     patch.object(call_review, "chains", return_value={} if status == "unknown" else {"root": chain}), \
                     redirect_stderr(errors):
                    self.assertEqual(calls.main(["amend", "root", "--plan", str(root / "docs/plan/demo"),
                                                 "--brief-only"]), 1)
                start.assert_not_called()
                self.assertIn("must be in state amend", errors.getvalue())

    def test_main_refuses_unknown_part_and_missing_plan(self):
        with tmp_home() as root:
            fixture(root)
            fake = FakeRunner().on(["git", "rev-parse"], Result(0, str(root)))
            for directory, reason in ((root / "docs/plan/demo", "unknown part"), (root / "missing", "plan.toml")):
                with self.subTest(directory=directory):
                    output = io.StringIO()
                    with patch.object(calls, "run", fake), patch.object(calls, "start") as start, redirect_stderr(output):
                        self.assertEqual(calls.main(["skeleton", "absent", "--plan", str(directory)]), 1)
                    start.assert_not_called()
                    self.assertIn(reason, output.getvalue())


class DraftsTextTest(unittest.TestCase):
    def test_sources_that_are_files_are_carried_whole(self):
        with tmp_home() as root:
            (root / "docs").mkdir()
            (root / "docs/draft.md").write_text("The user's words.\n")
            spec = Plan("draft", "agents", ("docs/draft.md", "A doc elsewhere"), 1.0, 2.0, {}, ())
            text = calls.drafts_text(spec, root)
            self.assertIn("## docs/draft.md\n\nThe user's words.", text)
            self.assertIn("## A doc elsewhere\n\n(not a file in this repository)", text)
