"""Calls use compiled briefs and a fake Claude (docs/design/fab.md, 4; reports.md, 2)."""

from __future__ import annotations

import io
import json
import os
import unittest
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

from fab import call_review, calls, channel, cli, designer, log
from fab.plan import Part, Plan, Question, Slice, Task, load_tasks
from fab.sh import Failed, Result
from fab.tests.ladder_plans import write_ladder
from fab.tests.support import FakeRunner, call_started, call_ended, tmp_home

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
                 Slice(2, "Explore next", ("next",), False)),
                landing="queue", reviews=True, direct=False)
    tasks = {}
    for name, part in (("one", "base"), ("two", "base"), ("three", "core")):
        path = f"docs/plan/demo/tasks/{name}.md"
        spec = (f'+++\nid = "{name}"\npart = "{part}"\nkind = "feature"\n'
                f'files = ["fab/{name}.py"]\n+++\n# Spec {name}\nDo {name}.\n')
        write(root / path, spec)
        tasks[f"demo/{name}"] = Task(f"demo/{name}", part, "feature", "agents", (),
                                      (f"fab/{name}.py",), "high", 25, f"# Spec {name}\nDo {name}.\n", path)
    write(root / "design.md", "# Full design\n\n## 1. First\nContract.\n\n## 2. Core\nUse `fab/api.py`.\n\n## 8. Last\nKeep all sections.\n")
    write(root / "fab/api.py", 'def primitive(value: int) -> str:\n    """Existing primitive."""\n    return str(value)\n')
    write(root / "docs/plan/agents-rebuild/tasks/files.md", "# Fixed example\nA format example.\n")
    write(root / "docs/plan/demo/plan.toml", '\n'.join([
        'draft = "demo"', 'repo = "agents"',
        'landing = "queue"', 'reviews = true', 'direct = false',
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

    def test_heading_spans_keep_children_and_ignore_fenced_headings(self):
        text = ("# Draft\nIntro.\n\n## 1. Parent\nParent words.\n\n"
                "### 1.1 Child\nChild words.\n~~~md\n## Fenced\n~~~\n\n## 2. Sibling\nOutside.\n")
        headings = calls._headings(text)
        self.assertEqual([(level, title) for level, title, _, _ in headings],
                         [(1, "Draft"), (2, "1. Parent"), (3, "1.1 Child"), (2, "2. Sibling")])
        selected = [(start, end) for _, title, start, end in headings if title in ("1. Parent", "1.1 Child")]
        self.assertEqual(calls._excerpt(text, selected),
                         "## 1. Parent\nParent words.\n\n### 1.1 Child\nChild words.\n~~~md\n## Fenced\n~~~")
        self.assertEqual(calls._excerpt(text, []), "")

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

    def test_last_review_filters_draft_and_done_independently(self):
        events = [call_started("one-done", "review", "one/review", ts="001"),
                  call_ended("one-done", ts="002"),
                  call_started("two-done", "review", "two/review", ts="003"),
                  call_ended("two-done", ts="004"),
                  call_started("one-failed", "review", "one/review", ts="005"),
                  call_ended("one-failed", outcome="failed", ts="006"),
                  call_started("prefix", "review", "one/reviewing", ts="007"),
                  call_started("answer", "answer", "one/review", ts="008")]
        self.assertEqual(calls.last_review(iter(events)), "007")
        self.assertEqual(calls.last_review(iter(events), done=True), "003")
        self.assertEqual(calls.last_review(iter(events), draft="one"), "005")
        self.assertEqual(calls.last_review(iter(events), draft="one", done=True), "001")
        self.assertEqual(calls.last_review(events, draft="two", done=True), "003")
        self.assertIsNone(calls.last_review(events, draft="missing"))
        self.assertIsNone(calls.last_review([], draft="one", done=True))

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
    def test_review_accepts_a_landed_red_task_without_a_plan_part(self):
        with tmp_home() as root:
            plan, tasks = fixture(root)
            red = replace(tasks["demo/one"], id="demo/red-1", kind="red", part="after-landing", path="")
            tasks[red.id] = red
            events = [dict(ev="branch.landed", task=red.id, branch=red.id, tip="tip", main="main", ts="now")]
            text = calls.review_brief(plan, tasks, events, root, call_id="c", branch="b", report="r")
            self.assertIn("## demo/red-1", text)

    def test_skeleton_sections_one_spec_and_part_statuses(self):
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
                             (root / tasks["demo/one"].path).read_text()):
                self.assertIn(fragment, text)
            self.assertNotIn("# Spec two", text)
            self.assertNotIn("# Spec three", text)
            partial = calls.skeleton_brief(plan, "core", tasks, {"demo/one": "landed", "demo/two": "done"},
                                           root, call_id="c", branch="b", report="r")
            self.assertIn("| base | Base primitives | feature | - | designed |", partial)

    def test_skeleton_two_needs_reach_only_cited_drafts_and_modules_and_one_example(self):
        with tmp_home() as root:
            plan, tasks = fixture(root)
            sources = ("docs/draft/code.md", "docs/draft/landing.md", "docs/draft/execution.md")
            drafts = (
                "# Code\nUnselected introduction.\n\n## 1. Other\nOther code.\n\n"
                "## 3. Metrics\nCode metrics.\n\n### 3.1 Detail\nNested metrics.\n\n"
                "## 4. Signals\nUnselected signals.\n\n## 5. Reports\nCode reports.\n",
                "# Landing\n\n## 3. Metrics\nUnselected landing metrics.\n\n"
                "## 6. Reds\nLearn from reds.\n",
                "# Execution\n\n## Skeletons\nUnselected skeletons.\n\n"
                "## Questions\nAsk the user.\n\n## One mechanism\nA single mechanism.\n\n"
                "## Example: `model.md`\nAn example flow.\n\n"
                "## Later\nUnselected later.\n",
            )
            for source, text in zip(sources, drafts):
                write(root / source, text)
            plan = replace(plan, sources=sources)
            plan.parts["core"] = replace(plan.parts["core"], title="Call core: Questions",
                                          needs=("base", "next"))
            tasks["demo/two"] = replace(tasks["demo/two"], files=("fab/base_*.py",))
            tasks["demo/three"] = replace(tasks["demo/three"], part="next", files=("fab/needed.py",))
            write(root / "design.md", "# Design\n\n## 1. Outside\n`fab/unrelated.py`; `docs/draft/code.md`, 4.\n\n"
                  "## 2. Core\n`fab/api.py` and `fab.extra.public`; `docs/draft/code.md`, 3 and 5;\n"
                  "`code.md`, 3.1; `landing.md`, 6. One mechanism applies.\n\n### 2.1 Child\n`fab/nested.py`.\n\n"
                  '## 8. Flow\n`execution.md`, "Example".\n')
            modules = {"api", "extra", "nested", "one", "base_extra", "needed",
                       "sh", "log", "atomic", "plan", "state"}
            for name in modules | {"unrelated", "own"}:
                write(root / f"fab/{name}.py", f'def {name}():\n    """{name} primitive."""\n    pass\n')
            tasks["demo/own"] = replace(tasks["demo/one"], id="demo/own", part="core", files=("fab/own.py",))
            statuses = {key: "landed" for key in tasks}
            # Reversing the tasks leaves the example's path order unchanged.
            text = calls.skeleton_brief(plan, "core", dict(reversed(list(tasks.items()))), statuses, root,
                                        call_id="c", branch="b", report="r")
            inventory = text.split("# Inventory\n\n", 1)[1].split("\n\n# Task spec examples", 1)[0]
            self.assertEqual({line for line in inventory.splitlines() if line.startswith("## ")},
                             {f"## fab/{name}.py" for name in modules})
            examples = text.split("# Task spec examples\n\n", 1)[1]
            self.assertEqual(examples.count("+++"), 2)
            self.assertIn((root / tasks["demo/one"].path).read_text(), examples)
            self.assertNotIn("# Spec two", examples)
            self.assertNotIn("# Spec three", examples)
            excerpts = text.split("# The user's drafts\n\n", 1)[1].split("\n\n# Cited design", 1)[0]
            for fragment in ("Code metrics.", "Code reports.", "Nested metrics.", "Learn from reds.",
                             "Ask the user.", "A single mechanism.", "An example flow."):
                self.assertIn(fragment, excerpts)
            self.assertEqual(excerpts.count("Nested metrics."), 1)
            for fragment in ("Unselected", "Other code."):
                self.assertNotIn(fragment, excerpts)
            whole = calls.review_brief(plan, tasks, [], root, call_id="r", branch="b", report="r")
            for source, draft in zip(sources, drafts):
                self.assertIn(f"## {source}\n\n{draft}", whole)

    def test_skeleton_example_uses_only_first_need_landed_specs_or_fixed_fallback(self):
        with tmp_home() as root:
            plan, tasks = fixture(root)
            for needs, statuses, expected in (
                    (("base", "core"), {"demo/one": "done", "demo/three": "landed"}, "Fixed example"),
                    (("base",), {"demo/one": "running", "demo/two": "landed"}, "Spec two"),
                    (("core", "base"), {"demo/one": "landed", "demo/three": "landed"}, "Spec three"),
                    ((), {"demo/one": "landed"}, "Fixed example")):
                with self.subTest(needs=needs, statuses=statuses):
                    plan.parts["next"] = replace(plan.parts["next"], needs=needs)
                    text = calls.skeleton_brief(plan, "next", tasks, statuses, root,
                                               call_id="c", branch="b", report="r")
                    example = text.split("# Task spec examples\n\n", 1)[1]
                    self.assertIn("# " + expected, example)
                    self.assertEqual(sum(example.count("# " + title) for title in
                                         ("Spec one", "Spec two", "Spec three", "Fixed example")), 1)

    def test_fixed_example_can_come_from_fab_when_the_plan_checkout_lacks_it(self):
        with tmp_home() as root:
            plan_root = root / "plan"
            plan, tasks = fixture(plan_root)
            relative = Path("docs/plan/agents-rebuild/tasks/files.md")
            (plan_root / relative).unlink()
            write(root / "installed" / relative, "# Installed format example\nA fixed spec.\n")
            with patch.object(calls, "__file__", str(root / "installed/fab/calls.py")):
                text = calls.skeleton_brief(plan, "base", tasks, {}, plan_root,
                                            call_id="c", branch="b", report="r")
            self.assertIn("# Task spec examples\n\n## " + relative.as_posix() +
                          "\n\n# Installed format example\nA fixed spec.\n", text)

    def test_skeleton_dotted_design_section_and_named_parent_keep_children_only_once(self):
        with tmp_home() as root:
            plan, tasks = fixture(root)
            source = "docs/draft/execution.md"
            write(root / source, "# Execution\n\n## Feature mode\nParent.\n\n"
                  "### Skeletons\nChild.\n```md\n## Questions\nFenced heading.\n```\n\n"
                  "## Other\nUnselected other.\n")
            write(root / "design.md", "# Design\n\n## 13. Flow\n\n### 13.1 Calls\n`fab/api.py`.\n\n"
                  "### 13.10 Later\n`fab/unrelated.py`; `execution.md`, 2.\n")
            plan = replace(plan, sources=(source, "not a file"))
            plan.parts["core"] = replace(plan.parts["core"], title="Feature mode and Skeletons",
                                          design="design.md, 13.1")
            text = calls.skeleton_brief(plan, "core", tasks, {}, root, call_id="c", branch="b", report="r")
            excerpts = text.split("# The user's drafts\n\n", 1)[1].split("\n\n# Cited design", 1)[0]
            self.assertIn("Parent.", excerpts)
            self.assertEqual(excerpts.count("Child."), 1)
            self.assertIn("Fenced heading.", excerpts)
            self.assertNotIn("Unselected other.", excerpts)
            reached = calls._cited_design(root, "design.md, 13.1")
            self.assertIn("`fab/api.py`", reached)
            self.assertNotIn("fab/unrelated.py", reached)
            # A design citation may name a draft section directly.
            plan.parts["core"] = replace(plan.parts["core"], title="Core", design=source + ", 2")
            write(root / source, "# Execution\n\n## 1. Other\nOutside.\n\n## 2. Calls\nDirect draft.\n")
            text = calls.skeleton_brief(plan, "core", tasks, {}, root, call_id="c", branch="b", report="r")
            self.assertIn("# The user's drafts\n\n## " + source + "\n\n## 2. Calls\nDirect draft.", text)

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

    def test_fabrig_briefs_select_cited_and_needed_crates_and_plan_example(self):
        with tmp_home() as root:
            plan, tasks = fixture(root)
            plan = replace(plan, repo="fabrig")
            plan.parts["core"] = replace(plan.parts["core"], needs=("base",))
            write(root / "design.md", "# Design\n\n## 1. Outside\n`skein/crates/outside`.\n\n"
                  "## 2. Core\n`skein/crates/cited/src/lib.rs`; `named`.\n\n## 8. Rules\nRust.\n")
            for name in ("cited", "named", "needed", "outside", "own"):
                crate = root / "skein/crates" / name
                write(crate / "Cargo.toml", f'[package]\nname = "{name}"\n')
                write(crate / "src/lib.rs", f"/// {name} contract.\npub struct {name.title()};\n")
                write(crate / "src/other.rs", f"pub fn {name}_sibling() {{}}\n")
            write(root / "fab/broken.py", "This is not Python!")
            tasks["demo/one"] = replace(tasks["demo/one"], files=("skein/crates/needed/src/*.rs",))
            tasks["demo/two"] = replace(tasks["demo/two"], part="core", files=("skein/crates/own/**",))
            # A landed spec elsewhere in this plan is useful even before the first need lands.
            statuses = {"demo/three": "landed"}
            for role in ("skeleton", "contract"):
                with self.subTest(role=role):
                    text = calls.skeleton_brief(plan, "core", tasks, statuses, root,
                                                call_id="c", branch="b", report="r", role=role)
                    variant = calls.ROLES[role].with_name(f"{role}-fabrig.md").read_text()
                    self.assertIn(variant, text)
                    self.assertIn("todo!()", text)
                    inventory = text.split("# Inventory\n\n", 1)[1].split("\n\n# Task spec examples", 1)[0]
                    for name in ("cited", "named", "needed"):
                        self.assertIn(f"pub struct {name.title()}", inventory)
                        self.assertIn(f"pub fn {name}_sibling()", inventory)
                    for name in ("outside", "own", "fab/"):
                        self.assertNotIn(name, inventory)
                    self.assertIn("# Spec three", text.split("# Task spec examples", 1)[1])
                    self.assertNotIn("# Fixed example", text)

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
            skeleton = calls.skeleton_brief(plan, "core", tasks, {"demo/one": "landed"}, root,
                                            call_id="c", branch="b", report="r")
            answer = calls.answer_brief([{"task": "demo/one", "run": "demo/one-1", "text": "Choose?"}],
                                         tasks, root, call_id="c", branch="b", report="r")
            for text in (skeleton, answer):
                self.assertIn("(docs/plan/demo/tasks/one.md)", text)
                self.assertNotIn(f"({root}/docs/plan", text)
                self.assertIn("# Spec one", text)

    def test_review_plan_path_keeps_root_default_and_names_nested_specs(self):
        with tmp_home() as root:
            plan, tasks = fixture(root)
            facts = dict(call_id="c", branch="b", report="r")
            expected = calls.review_brief(plan, tasks, [], root, **facts)
            self.assertEqual(calls.review_brief(plan, tasks, [], root,
                                                plan_path="docs/plan/demo", **facts), expected)
            self.assertEqual(calls.review_brief(plan, tasks, [], root,
                                                plan_path="skein/docs/plan/demo", **facts),
                             expected.replace("Specs: docs/plan/demo/tasks/",
                                              "Specs: skein/docs/plan/demo/tasks/"))

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
            events = [first, {"ev": "call.started", "role": "review", "subject": "demo/review", "call": "done", "ts": "002"},
                      {"ev": "branch.landed", "task": "demo/three", "branch": "demo/three",
                       "main": "m2", "tip": "tip-three", "ts": "003"},
                      {"ev": "call.ended", "call": "done", "outcome": "done", "ts": "004"},
                      {"ev": "call.started", "role": "review", "subject": "demo/review", "call": "failed", "ts": "005"},
                      {"ev": "call.ended", "call": "failed", "outcome": "failed", "ts": "006"}]
            text = calls.review_brief(plan, tasks, events, root, call_id="c", branch="b", report="r")
            self.assertNotIn("## demo/one", text)
            self.assertIn("## demo/three", text)
            empty = calls.review_brief(plan, tasks, [], root, call_id="c", branch="b", report="r")
            self.assertIn("# Landed since the last review\n\n(none)", empty)
            self.assertNotIn("# Full design", empty)

    def test_review_brief_uses_own_drafts_last_done_review(self):
        with tmp_home() as root:
            plan, tasks = fixture(root)
            events = [dict(ev="branch.landed", task="demo/one", branch="demo/one", main="m0", tip="t0", ts="001"),
                      call_started("own-done", "review", "demo/review", ts="002"),
                      call_ended("own-done", ts="003"),
                      dict(ev="branch.landed", task="demo/two", branch="demo/two", main="m1", tip="t1", ts="004"),
                      call_started("other-done", "review", "other/review", ts="005"),
                      call_ended("other-done", ts="006"),
                      call_started("own-failed", "review", "demo/review", ts="007"),
                      call_ended("own-failed", outcome="failed", ts="008"),
                      dict(ev="branch.landed", task="demo/three", branch="demo/three", main="m2", tip="t2", ts="009")]
            text = calls.review_brief(plan, tasks, events, root, call_id="c", branch="b", report="r")
            self.assertNotIn("## demo/one", text)
            self.assertIn("## demo/two", text)
            self.assertIn("## demo/three", text)
            self.assertLess(text.index("## demo/two"), text.index("## demo/three"))

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

    def test_answer_stop_section_has_its_report_and_no_spec(self):
        for report in ("/runs/demo/check-3/report.md", "gate:/queue/rejected.log", ""):
            with self.subTest(report=report), tmp_home() as root:
                plan, tasks = fixture(root)
                question = dict(task="demo/integration", run="demo/check-3", text="Third red: choose a repair?",
                                stop=report)
                text = calls.answer_brief([question], tasks, root, plan=plan,
                                          call_id="a", branch="b", report="r")
                section = text.split("# Question:", 1)[1].split("# Inventory", 1)[0]
                self.assertEqual(section, f" demo/integration (stop)\n\n- Task: demo/integration\n"
                                         f"- Report: `{report}`\n\nThird red: choose a repair?\n\n")
                self.assertNotIn("Task spec", text)
                self.assertNotIn("- Run:", section)

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
        self.assertEqual(argv[3:], ["--model", calls.MODEL, "--effort", "high", "--output-format", "stream-json", "--verbose",
                                    "--dangerously-skip-permissions", f"--add-dir={worktree}"])
        self.assertEqual(calls.claude_argv(brief, worktree, effort="medium")[6], "medium")
        self.assertEqual((calls.role_effort("answer"), calls.role_effort("skeleton")), ("medium", "high"))
        self.assertEqual(len(argv[2].splitlines()), 1)
        self.assertIn("Read and follow", argv[2])
        self.assertIn("brief.md", argv[2])
        self.assertEqual(calls.claude_argv(brief, worktree, model="another")[4], "another")


class ClaudeUsageTest(unittest.TestCase):
    def stream(self, result=True):
        events = [
            {"type": "assistant", "message": {"id": "main", "usage": {
                "input_tokens": 10, "cache_creation_input_tokens": 20,
                "cache_read_input_tokens": 30, "output_tokens": 1}}},
            {"type": "assistant", "message": {"id": "main", "usage": {
                "input_tokens": 10, "cache_creation_input_tokens": 20,
                "cache_read_input_tokens": 30, "output_tokens": 4}}},
            {"type": "assistant", "parent_tool_use_id": "tool", "message": {"id": "sub", "usage": {
                "input_tokens": 1000, "cache_creation_input_tokens": 2000,
                "cache_read_input_tokens": 3000, "output_tokens": 5}}},
            {"type": "assistant", "parent_tool_use_id": None, "message": {"usage": {
                "input_tokens": 3, "output_tokens": 2}}},
            {"type": "assistant", "message": {"usage": {"input_tokens": 2}}},
            {"type": "assistant", "message": None},
            {"type": "assistant", "message": {"id": "main"}},
        ]
        if result:
            events += [{"type": "result", "usage": {"input_tokens": 1}},
                       {"type": "result", "num_turns": 7, "usage": {"input_tokens": 50,
                        "cache_creation_input_tokens": 60, "cache_read_input_tokens": 70, "output_tokens": 80}}]
        events.append({"usage": {"input_tokens": 9999}})
        return "not JSON\n[]\n" + "\n".join(map(json.dumps, events)) + '\n{"type":'

    def test_claude_usage_result_totals_last_message_usage_and_main_peak(self):
        self.assertEqual(calls.claude_usage(self.stream()), calls.Usage(50, 60, 70, 80, 60, 7))

    def test_claude_usage_without_result_sums_each_message_once_and_counts_main_turns(self):
        self.assertEqual(calls.claude_usage(self.stream(False)), calls.Usage(1015, 2020, 3030, 11, 60, 3))

    def test_claude_usage_legacy_object_and_unreadable_stream(self):
        old = {"usage": {"input_tokens": 10, "cache_creation_input_tokens": 20,
                         "cache_read_input_tokens": 30, "output_tokens": 4}, "num_turns": 2}
        self.assertEqual(calls.claude_usage(json.dumps(old, indent=2)), calls.Usage(10, 20, 30, 4, 0, 2))
        for stream in ("", "garbage", "[]", "null", "42", '{"type":"result","usage":null}'):
            with self.subTest(stream=stream):
                self.assertEqual(calls.claude_usage(stream), calls.Usage(0, 0, 0, 0, 0, 0))

    def test_claude_usage_invalid_counts_and_turns_are_zero(self):
        for value in (None, -1, True, 2.5, "10"):
            usage = dict.fromkeys(("input_tokens", "cache_creation_input_tokens",
                                   "cache_read_input_tokens", "output_tokens"), value)
            events = [{"type": "assistant", "message": {"usage": usage}},
                      {"type": "result", "usage": usage, "num_turns": value if value != -1 else None}]
            with self.subTest(value=value):
                self.assertEqual(calls.claude_usage("\n".join(map(json.dumps, events))),
                                 calls.Usage(0, 0, 0, 0, 0, 0))

    def test_claude_usage_log_fields_keep_tokens_shape(self):
        self.assertEqual(calls.Usage(10, 20, 30, 4, 60, 2).log_fields(),
                         {"tokens": "10/30/4", "cache_write": 20, "peak": 60, "turns": 2})


class StartTest(unittest.TestCase):
    def test_reply_report_only_call_uses_medium_effort_and_records_usage(self):
        with tmp_home() as root:
            def claude(call):
                directory = Path(call.cwd).parent
                brief = (directory / "brief.md").read_text()
                self.assertIn(f"Report: write it to `{directory / 'report.md'}`", brief)
                self.assertIn(calls.ROLES["reply"].read_text(), brief)
                write(directory / "report.md", "Done: reply\n\nHere is the context.\n")
                return Result(0, json.dumps({"type": "result", "num_turns": 1,
                                             "usage": {"input_tokens": 5, "output_tokens": 8}}))

            fake = FakeRunner().on(["claude"], claude)
            brief = calls.ROLES["reply"].read_text() + "\n\n# Call facts\n\n(assigned)\n"
            result = calls.start("reply", "issues/7", root, brief, sh=fake)
            self.assertEqual(result["outcome"], "done")
            command = next(argv for argv in fake.argvs() if argv[0] == "claude")
            self.assertEqual(command[command.index("--effort") + 1], "medium")
            self.assertFalse(any(argv[:2] == ["git", "push"] for argv in fake.argvs()))
            started, ended = log.read()
            self.assertEqual((started["role"], started["subject"]), ("reply", "issues/7"))
            self.assertEqual((ended["outcome"], ended["tokens"], ended["turns"]), ("done", "5/0/8", 1))
            self.assertEqual(call_review.chains(log.read()), {})
            self.assertEqual(channel.asks((), log.read()), [])

    def test_report_only_detaches_logs_no_branch_and_never_pushes(self):
        for fabrig in (False, True):
            for base in ("main", "demo/integration"):
                with self.subTest(fabrig=fabrig, base=base), tmp_home() as root:
                    repo = log.home() / "repos/fabrig" if fabrig else root
                    repo.mkdir(parents=True, exist_ok=True)

                    def claude(call):
                        directory = Path(call.cwd).parent
                        brief = (directory / "brief.md").read_text()
                        self.assertIn(f"- Call: {directory.name}", brief)
                        self.assertIn(str(directory / "report.md"), brief)
                        self.assertNotIn(f"calls/{directory.name}`", brief)
                        self.assertNotIn("branch", log.read()[-1])
                        write(directory / "report.md", "Done: 1 decisions\nfinding-1: backlog: off path\n")
                        return Result(0, "{}")

                    fake = FakeRunner().on(["claude"], claude)
                    fields = {"draft": "demo", "branch": "must-not-be-logged"}
                    result = calls.start("answer", "demo/triage", repo,
                                         "# Call facts\n\npreview\n", sh=fake,
                                         base=base, fields=fields, report_only=True)
                    directory = Path(result["report"]).parent
                    self.assertEqual(result, {"call": directory.name, "branch": "",
                                              "outcome": "done", "report": str(directory / "report.md")})
                    self.assertEqual(fake.argvs(), [
                        ["git", "fetch", "origin"],
                        ["git", "worktree", "add", "--detach", str(directory / "wt"), f"origin/{base}"],
                        calls.claude_argv(directory / "brief.md", directory / "wt", effort="medium"),
                        ["git", "worktree", "remove", "--force", str(directory / "wt")],
                    ])
                    self.assertEqual([call.cwd for call in fake.calls],
                                     [str(repo), str(repo), str(directory / "wt"), str(repo)])
                    started, ended = log.read()
                    expected = {"ev": "call.started", "call": directory.name, "role": "answer",
                                "subject": "demo/triage", "draft": "demo"}
                    if base != "main":
                        expected["trunk"] = base
                    self.assertEqual({key: value for key, value in started.items() if key != "ts"}, expected)
                    self.assertEqual(ended["outcome"], "done")
                    self.assertEqual(fields, {"draft": "demo", "branch": "must-not-be-logged"})
                    self.assertEqual((log.home() / "tick.want").read_text(), f"call {result['call']}\n")

    def test_report_only_failure_removes_worktree_and_never_pushes(self):
        for raises in (False, True):
            with self.subTest(raises=raises), tmp_home():
                def claude(call):
                    if raises:
                        raise OSError("cannot launch Claude")
                    return Result(1, "{}", "failed")

                fake = FakeRunner().on(["claude"], claude)
                repo = log.home() / "repos/fabrig"
                if raises:
                    with self.assertRaisesRegex(OSError, "cannot launch"):
                        calls.start("answer", "demo/triage", repo, "Brief.", sh=fake, report_only=True)
                    self.assertEqual([event["ev"] for event in log.read()], ["call.started"])
                else:
                    result = calls.start("answer", "demo/triage", repo, "Brief.", sh=fake, report_only=True)
                    self.assertEqual(result["outcome"], "failed")
                    self.assertEqual(log.read()[-1]["outcome"], "failed")
                self.assertEqual(fake.argvs()[-1][:4], ["git", "worktree", "remove", "--force"])
                self.assertFalse(any(argv[:2] == ["git", "push"] for argv in fake.argvs()))
                self.assertNotIn("branch", log.read()[0])

    def test_report_only_rejects_a_branch_before_starting(self):
        for branch in ("calls/root", ""):
            with self.subTest(branch=branch), tmp_home() as root:
                fake = FakeRunner()
                with self.assertRaisesRegex(ValueError, "branch"):
                    calls.start("answer", "demo/triage", root, "Brief.", sh=fake,
                                branch=branch, report_only=True)
                self.assertEqual(fake.calls, [])
                self.assertFalse((log.home() / "calls").exists())
                self.assertEqual(log.read(), [])

    def test_report_only_preparation_failure_never_launches_claude(self):
        for command in (["git", "fetch"], ["git", "worktree", "add"]):
            with self.subTest(command=command), tmp_home() as root:
                fake = FakeRunner().on(command, Result(1, err="cannot prepare worktree"))
                with self.assertRaises(Failed):
                    calls.start("answer", "demo/triage", root, "Brief.", sh=fake, report_only=True)
                self.assertEqual(fake.argvs()[0], ["git", "fetch", "origin"])
                self.assertEqual(fake.argvs()[-1][:len(command)], command)
                self.assertEqual(log.read(), [])

    def test_start_commands_artifacts_events_usage_and_outcome(self):
        with tmp_home() as root:
            plan, tasks = fixture(root)
            text = calls.skeleton_brief(plan, "core", tasks, {"demo/one": "landed"}, root,
                                        call_id="preview", branch="preview", report="preview")
            result_json = "\n".join(json.dumps(event) for event in [
                {"type": "assistant", "message": {"id": "main", "usage": {
                    "input_tokens": 23, "cache_creation_input_tokens": 7, "cache_read_input_tokens": 50}}},
                {"type": "result", "num_turns": 2, "usage": {"input_tokens": 23,
                    "cache_creation_input_tokens": 7, "cache_read_input_tokens": 50, "output_tokens": 9}},
            ])

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
                self.assertFalse((root / "tick.want").exists())
                write(directory / "report.md", "\nDone: designed core\nDetails.\n")
                return Result(0, result_json, "Claude diagnostic\n")

            def removed(call):
                self.assertEqual(log.read(root / "custom.jsonl")[-1]["ev"], "call.ended")
                self.assertEqual((root / "tick.want").read_text(), f"call {Path(call.argv[-1]).parent.name}\n")
                return Result(0)

            fake = FakeRunner().on(["claude"], claude).on(["git", "worktree", "remove"], removed)
            runner = Mock(wraps=fake)
            with patch.object(calls.time, "monotonic", side_effect=[100.0, 190.0]):
                result = calls.start("skeleton", "demo/core", root, text, sh=runner, log_path=root / "custom.jsonl")
            self.assertEqual((root / "tick.want").read_text(), f"call {result['call']}\n")
            self.assertFalse((root / "fab/tick.want").exists())
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
            self.assertEqual((directory / "stream.jsonl").read_text(), result_json)
            self.assertEqual((directory / "stderr.log").read_text(), "Claude diagnostic\n")
            started, ended = log.read(root / "custom.jsonl")
            self.assertEqual({key: value for key, value in started.items() if key != "ts"},
                             {"ev": "call.started", "call": directory.name, "role": "skeleton",
                              "subject": "demo/core", "branch": result["branch"]})
            self.assertEqual({key: value for key, value in ended.items() if key != "ts"},
                             {"ev": "call.ended", "call": directory.name, "role": "skeleton", "subject": "demo/core",
                              "outcome": "done", "tokens": "23/50/9", "cache_write": 7,
                              "peak": 80, "turns": 2, "minutes": 1.5})

    def test_integration_base_fetches_sets_start_and_logs_trunk_and_fields(self):
        for branch in (None, "calls/root"):
            with self.subTest(branch=branch), tmp_home() as root:
                fields = {"options": ['landing="integration"', "reviews=false"]}
                fake = FakeRunner()
                result = calls.start("amend" if branch else "cut", "demo/cut", root, "Brief.",
                                     sh=fake, base="demo/integration", fields=fields,
                                     branch=branch, amends="root" if branch else None)
                worktree = Path(result["report"]).parent / "wt"
                self.assertEqual(fake.argvs()[:2], [
                    ["git", "fetch", "origin"],
                    ["git", "worktree", "add", "-B" if branch else "-b", result["branch"],
                     str(worktree), f"origin/{branch}" if branch else "origin/demo/integration"],
                ])
                self.assertEqual([call.cwd for call in fake.calls[:2]], [str(root), str(root)])
                started = log.read()[0]
                self.assertEqual(started["trunk"], "demo/integration")
                self.assertEqual(started["options"], fields["options"])
                self.assertEqual(fields, {"options": ['landing="integration"', "reviews=false"]})
                if branch:
                    self.assertEqual(started["amends"], "root")
                else:
                    self.assertNotIn("amends", started)

    def test_integration_base_fetch_failure_starts_nothing(self):
        with tmp_home() as root:
            fake = FakeRunner().on(["git", "fetch"], Result(1, err="offline"))
            with self.assertRaises(Failed):
                calls.start("cut", "demo/cut", root, "Brief.", sh=fake, base="demo/integration")
            self.assertEqual(fake.argvs(), [["git", "fetch", "origin"]])
            self.assertEqual(log.read(), [])

    def test_fabrig_call_fetches_builds_and_pushes_in_its_clone(self):
        for branch in (None, "calls/root"):
            with self.subTest(branch=branch), tmp_home() as root:
                repo = log.home() / "repos/fabrig"
                repo.mkdir(parents=True)

                def claude(call):
                    write(Path(call.cwd).parent / "report.md", "Done: Rust skeleton\n")
                    return Result(0, "{}")

                fake = FakeRunner().on(["claude"], claude)
                result = calls.start("amend" if branch else "skeleton", "demo/core", repo,
                                     "Brief.", sh=fake, branch=branch)
                worktree = Path(result["report"]).parent / "wt"
                target = branch or f"calls/{result['call']}"
                self.assertEqual(result["branch"], target)
                self.assertEqual(fake.argvs(), [
                    ["git", "fetch", "origin"],
                    ["git", "worktree", "add", "-B" if branch else "-b", target,
                     str(worktree), f"origin/{target}" if branch else "origin/main"],
                    calls.claude_argv(worktree.parent / "brief.md", worktree),
                    ["git", "push", "origin", target],
                    ["git", "worktree", "remove", "--force", str(worktree)],
                ])
                self.assertEqual([call.cwd for call in fake.calls],
                                 [str(repo), str(repo), str(worktree), str(repo), str(repo)])

    def test_fabrig_push_failure_removes_worktree_without_reporting_done(self):
        with tmp_home():
            fake = FakeRunner().on(["git", "push"], Result(1, err="offline"))
            with self.assertRaises(Failed):
                calls.start("skeleton", "demo/core", log.home() / "repos/fabrig", "Brief.", sh=fake)
            self.assertEqual(fake.argvs()[-1][:4], ["git", "worktree", "remove", "--force"])
            self.assertEqual([event["ev"] for event in log.read()], ["call.started"])

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
                self.assertEqual((root / "fab/tick.want").read_text(), f"call {result['call']}\n")

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
            self.assertFalse((root / "fab/tick.want").exists())

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


class ChainCallTest(unittest.TestCase):
    def compile_amend(self, root, role="retire", *, queue=False, review=False):
        events = [call_started("root", role, "demo/" + role), call_ended("root")]
        if review:
            events += [dict(ev="run.started", run="review-1", kind="review", task="root"),
                       dict(ev="run.ended", run="review-1", outcome="failed")]
        else:
            rejection = dict(ev="branch.rejected", branch="calls/root", step="rebase", log="CONFLICT in x")
            events.append(dict(rejection, queue_ts="queued") if queue else rejection)
        return calls._chain_call("amend", "root", root, events,
                                 dict(call_id="amend", branch="calls/root", report="/report"),
                                 draft="demo", plan_path="nested/docs/plan/demo")

    def test_retire_land_amend_compares_main_and_branch_designs_after_fetch(self):
        with tmp_home() as root:
            fake = FakeRunner()

            def changed(checkout, draft, *, rev, sh, plan_path):
                self.assertEqual((checkout, draft, sh, plan_path),
                                 (root, "demo", fake, "nested/docs/plan/demo"))
                self.assertEqual(fake.argvs(), [["git", "fetch", "origin"]])
                return {"origin/main": ["docs/design/z.md", "docs/design/x.md", "docs/design/shared.md"],
                        "origin/calls/root": ["docs/design/shared.md", "docs/design/branch.md"]}[rev]

            with patch.object(calls, "run", fake), \
                 patch.object(designer, "changed_designs", side_effect=changed) as changes:
                text, subject, options = self.compile_amend(root)
            self.assertEqual([call.kwargs["rev"] for call in changes.call_args_list],
                             ["origin/main", "origin/calls/root"])
            self.assertEqual(subject, "demo/retire")
            self.assertEqual(options, dict(branch="calls/root", amends="root"))
            self.assertIn("- `docs/design/x.md` (status `docs/design/x.status.md`)", text)
            self.assertIn("- `docs/design/z.md` (status `docs/design/z.status.md`)", text)
            self.assertLess(text.index("- `docs/design/x.md`"), text.index("- `docs/design/z.md`"))
            self.assertNotIn("docs/design/shared.md", text)
            self.assertNotIn("docs/design/branch.md", text)
            self.assertTrue(all(call.cwd == str(root) for call in fake.calls))

    def test_other_amendments_do_not_fetch_or_compute_designs(self):
        for role, options in (("skeleton", {}), ("retire", dict(review=True)), ("retire", dict(queue=True))):
            with self.subTest(role=role, options=options), tmp_home() as root:
                fake = FakeRunner()
                with patch.object(calls, "run", fake), patch.object(designer, "changed_designs") as changes:
                    text, _, _ = self.compile_amend(root, role, **options)
                changes.assert_not_called()
                self.assertEqual(fake.argvs(), [])
                self.assertNotIn("# Designs main changed since your branch", text)

    def test_missing_plan_history_at_either_revision_still_compiles_amend(self):
        for missing in ("origin/main", "origin/calls/root"):
            with self.subTest(missing=missing), tmp_home() as root:
                fake = FakeRunner()

                def changed(checkout, draft, *, rev, **kwargs):
                    if rev == missing:
                        raise ValueError("plan history missing")
                    return ["docs/design/x.md"]

                with patch.object(calls, "run", fake), \
                     patch.object(designer, "changed_designs", side_effect=changed):
                    text, subject, options = self.compile_amend(root)
                self.assertNotIn("# Designs main changed since your branch", text)
                self.assertIn("## `fab land` refused at rebase", text)
                self.assertEqual((subject, options["amends"]), ("demo/retire", "root"))
                self.assertEqual(fake.argvs(), [["git", "fetch", "origin"]])


class MainTest(unittest.TestCase):
    def test_triage_runs_report_only_with_medium_effort_in_the_plan_repository(self):
        cases = (("agents", "queue", "done", 0), ("agents", "integration", "done", 0),
                 ("fabrig", "integration", "question", 1), ("fabrig", "queue", "failed", 1))
        for repo_name, landing, outcome, code in cases:
            with self.subTest(repo=repo_name, landing=landing, outcome=outcome), tmp_home() as root:
                directory = write_ladder(root / "docs/plan/ladder")
                path = directory / "plan.toml"
                write(path, path.read_text().replace('repo = "agents"', f'repo = "{repo_name}"')
                      .replace('landing = "queue"', f'landing = "{landing}"'))
                write(root / "docs/design/draft/path.md", "## 2. Story\nThe story.\n## 4. Bar\nThe bar.\n")

                def claude(call):
                    call_dir = Path(call.cwd).parent
                    text = (call_dir / "brief.md").read_text()
                    self.assertIn(calls.ROLES["triage"].read_text(), text)
                    self.assertIn(f"- Call: {call_dir.name}", text)
                    self.assertIn("# The happy path\n\n", text)
                    write(call_dir / "report.md", f"{outcome.capitalize()}: decisions\n")
                    return Result(0, "{}")

                fake = FakeRunner().on(["git", "rev-parse"], Result(0, str(root)))
                fake.on(["git", "show"], Result(0, "Committed rung brief.\n")).on(["claude"], claude)
                output = io.StringIO()
                with patch.object(calls, "run", fake), redirect_stdout(output):
                    self.assertEqual(cli.main(["call", "triage", "--plan", str(directory)]), code)
                self.assertEqual(output.getvalue(), f"{outcome}\n")
                started, ended = log.read()
                self.assertEqual((started["role"], started["subject"]), ("triage", "ladder/triage"))
                self.assertNotIn("branch", started)
                self.assertEqual(ended["outcome"], outcome)
                self.assertEqual(call_review.chains(log.read()), {})
                command = next(call for call in fake.calls if call.argv[0] == "claude")
                self.assertEqual(command.argv[command.argv.index("--effort") + 1], "medium")
                repo = log.home() / "repos/fabrig" if repo_name == "fabrig" else root
                trunk = "ladder/integration" if landing == "integration" else "main"
                worktree = str(Path(command.cwd))
                self.assertIn(["git", "worktree", "add", "--detach", worktree, f"origin/{trunk}"], fake.argvs())
                self.assertIn(["git", "worktree", "remove", "--force", worktree], fake.argvs())
                for call in fake.calls:
                    if call.argv[:2] == ["git", "worktree"] or call.argv[:2] == ["git", "fetch"]:
                        self.assertEqual(call.cwd, str(repo))
                self.assertFalse(any(argv[:2] == ["git", "push"] for argv in fake.argvs()))
                self.assertEqual([argv for argv in fake.argvs() if argv[:2] == ["git", "show"]], [
                    ["git", "show", f"origin/main:docs/plan/ladder/briefs/{name}.md"]
                    for name in ("kit", "b0", "kit", "b1")])

    def test_triage_brief_only_prints_context_and_starts_nothing(self):
        with tmp_home() as root:
            directory = write_ladder(root / "docs/plan/ladder")
            write(root / "docs/design/draft/path.md", "## 2. Story\nThe story.\n## 4. Bar\nThe bar.\n")
            fake = FakeRunner().on(["git", "rev-parse"], Result(0, str(root)))
            fake.on(["git", "show"], Result(0, "Committed rung brief.\n"))
            output = io.StringIO()
            with patch.object(calls, "run", fake), patch.object(calls, "start") as start, redirect_stdout(output):
                self.assertEqual(calls.main(["triage", "--plan", str(directory), "--brief-only"]), 0)
            start.assert_not_called()
            self.assertIn(calls.ROLES["triage"].read_text(), output.getvalue())
            self.assertIn("# New findings\n\n", output.getvalue())
            self.assertIn("The story.", output.getvalue())
            self.assertEqual(log.read(), [])
            self.assertTrue(all(argv[:2] in (["git", "rev-parse"], ["git", "show"]) for argv in fake.argvs()))

    def test_triage_refuses_non_ladder_missing_plan_and_brief_compilation_errors(self):
        for failure, reason in (("no-rungs", "plan with rungs"), ("missing-plan", "plan.toml"),
                                ("edition", "cannot read brief"), ("checkout", "git rev-parse"),
                                ("oversize", "brief exceeds BRIEF_LIMIT")):
            with self.subTest(failure=failure), tmp_home() as root:
                directory = write_ladder(root / "docs/plan/ladder")
                write(root / "docs/design/draft/path.md", "## 2. Story\nStory.\n## 4. Bar\nBar.\n")
                if failure == "no-rungs":
                    write(directory / "plan.toml", 'draft = "ladder"\nrepo = "agents"\n')
                elif failure == "missing-plan":
                    (directory / "plan.toml").unlink()
                fake = FakeRunner().on(["git", "rev-parse"],
                                       Result(1 if failure == "checkout" else 0, str(root)))
                fake.on(["git", "show"], Result(1 if failure == "edition" else 0, "Brief.\n"))
                errors = io.StringIO()
                with patch.object(calls, "run", fake), patch.object(calls, "start") as start, \
                     patch.object(calls, "BRIEF_LIMIT", 1 if failure == "oversize" else calls.BRIEF_LIMIT), \
                     redirect_stderr(errors):
                    self.assertEqual(calls.main(["triage", "--plan", str(directory)]), 1)
                start.assert_not_called()
                self.assertIn(reason, errors.getvalue())

    def test_answer_includes_red_task_questions_for_both_landing_modes(self):
        from fab.tests.test_tier_reds import repair_events
        for landing in ("queue", "integration"):
            with self.subTest(landing=landing), tmp_home() as root:
                fixture(root)
                directory = root / "docs/plan/demo"
                path = directory / "plan.toml"
                write(path, path.read_text().replace('landing = "queue"', f'landing = "{landing}"'))
                for record in repair_events():
                    log.append(**record)
                log.append("run.started", task="demo/red-1", run="demo/red-1-1", kind="implement")
                log.append("run.ended", task="demo/red-1", run="demo/red-1-1", outcome="question")
                log.append("question.asked", task="demo/red-1", run="demo/red-1-1", text="Which red fix?")
                fake = FakeRunner().on(["git", "rev-parse"], Result(0, str(root)))
                output = io.StringIO()
                with patch.object(calls, "run", fake), redirect_stdout(output):
                    self.assertEqual(calls.main(["answer", "--plan", str(directory), "--brief-only"]), 0)
                self.assertIn("Which red fix?", output.getvalue())
                self.assertIn("# Repair a red after landing", output.getvalue())
                self.assertIn("## Task spec (none: its body)", output.getvalue())

    def test_answer_stop_reports_follow_each_open_ask_even_with_equal_fields(self):
        with tmp_home() as root:
            _, tasks = fixture(root)
            ask = dict(ev="question.asked", ts="03", task="demo/integration", run="", text="Stopped", park=True)
            events = [{"ev": "question.asked"}, {"ev": "question.answered"},
                      {"ev": "question.asked", "task": "demo/integration"},
                      dict(ask), dict(ev="plan.stopped", task="demo/integration", report="/one.md"),
                      dict(ask), dict(ev="plan.stopped", task="demo/integration", report="/two.md")]
            expected = dict(task="demo/integration", run="", text="Stopped", foreman="")
            self.assertEqual(calls._answer_questions(tasks, events),
                             [dict(expected, stop=""), dict(expected, stop="/one.md")])
            events.extend([dict(ev="question.answered", task="demo/integration"), dict(ask)])
            self.assertEqual(calls._answer_questions(tasks, events), [dict(expected, stop="/two.md")])

    def test_answer_stop_uses_last_report_before_ask_and_keeps_repair_question(self):
        with tmp_home() as root:
            fixture(root)
            directory = root / "docs/plan/demo"
            path = directory / "plan.toml"
            write(path, path.read_text().replace('landing = "queue"', 'landing = "integration"'))
            log.append("branch.landed", task="demo/one", branch="demo/one", into="demo/integration", main="tip")
            log.append("run.started", task="demo/integration", run="demo/check-1", kind="check", base="tip")
            log.append("run.ended", run="demo/check-1", outcome="failed")
            log.append("run.started", task="demo/repair-1", run="demo/repair-1-1", kind="implement")
            log.append("run.ended", run="demo/repair-1-1", outcome="question")
            log.append("question.asked", task="demo/repair-1", run="demo/repair-1-1", text="Which repair?")
            stamp = log.now()
            records = [dict(ev="plan.stopped", task="demo/integration", report="/old.md"),
                       dict(ev="question.asked", task="demo/integration", run="", text="Old stop", park=True),
                       dict(ev="question.answered", task="demo/integration"),
                       dict(ev="plan.stopped", task="demo/integration", report="/previous.md"),
                       dict(ev="plan.stopped", task="demo/integration", report="gate:/latest.log"),
                       dict(ev="plan.stopped", task="other/integration", report="/other.md"),
                       dict(ev="question.asked", task="demo/integration", run="", text="Third refusal?", park=True),
                       dict(ev="plan.stopped", task="demo/integration", report="/after.md")]
            for record in records:
                log.append(**record, ts=stamp)
            fake = FakeRunner().on(["git", "rev-parse"], Result(0, str(root)))
            output = io.StringIO()
            with patch.object(calls, "run", fake), patch.object(calls, "start") as start, redirect_stdout(output):
                self.assertEqual(calls.main(["answer", "--plan", str(directory), "--brief-only"]), 0)
            start.assert_not_called()
            text = output.getvalue()
            self.assertIn("# Question: demo/integration (stop)\n\n- Task: demo/integration\n"
                          "- Report: `gate:/latest.log`\n\nThird refusal?", text)
            self.assertIn("# Question: demo/repair-1 (demo/repair-1-1)", text)
            self.assertIn("Which repair?", text)
            self.assertIn("## Task spec (none: its body)\n\n# Repair the integration check", text)
            self.assertIn(f"- Report: `{log.home()}/runs/demo/repair-1-1/report.md`", text)
            self.assertEqual(text.count("## Task spec"), 1)
            for excluded in ("Old stop", "/old.md", "/previous.md", "/other.md", "/after.md"):
                self.assertNotIn(excluded, text)
            self.assertEqual(fake.argvs(), [["git", "rev-parse", "--show-toplevel"]])

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

    def test_nested_plan_briefs_use_repository_relative_specs(self):
        for role in ("skeleton", "answer", "review"):
            with self.subTest(role=role), tmp_home() as root:
                fixture(root)
                relative = "trees/skein/docs/plan/demo"
                directory = root / relative
                directory.parent.mkdir(parents=True)
                (root / "docs/plan/demo").rename(directory)
                log.append("question.asked", task="demo/one", run="demo/one-1", text="Which type?")
                fake = FakeRunner().on(["git", "rev-parse"], Result(0, str(root)))
                output = io.StringIO()
                args = ["core"] if role == "skeleton" else []
                with patch.object(calls, "run", fake), patch.object(calls, "start") as start, redirect_stdout(output):
                    self.assertEqual(cli.main(["call", role, *args, "--plan", str(directory),
                                               "--brief-only"]), 0)
                start.assert_not_called()
                text = output.getvalue()
                if role == "review":
                    self.assertIn(f"Specs: {relative}/tasks/", text)
                    self.assertNotIn("Specs: docs/plan/demo/tasks/", text)
                elif role == "answer":
                    self.assertIn(f"## Task spec ({relative}/tasks/one.md)", text)
                    self.assertIn("# Spec one", text)
                    self.assertNotIn(f"({root}/", text)
                else:
                    self.assertIn("- Id: core", text)
                self.assertEqual(fake.argvs(), [["git", "rev-parse", "--show-toplevel"]])

    def test_fabrig_main_starts_each_call_in_dispatcher_clone(self):
        for role in ("skeleton", "answer", "review", "amend"):
            with self.subTest(role=role), tmp_home() as root:
                fixture(root)
                path = root / "docs/plan/demo/plan.toml"
                write(path, path.read_text().replace('repo = "agents"', 'repo = "fabrig"'))
                self.amend_chain()
                fake = FakeRunner().on(["git", "rev-parse"], Result(0, str(root)))
                args = {"skeleton": ["core"], "amend": ["root"]}.get(role, [])
                with patch.object(calls, "run", fake), redirect_stdout(io.StringIO()), \
                     patch.object(calls, "start", return_value=dict(outcome="done", branch="calls/id")) as start:
                    self.assertEqual(calls.main([role, *args, "--plan", str(path.parent)]), 0)
                self.assertEqual(start.call_args.args[2], log.home() / "repos/fabrig")

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

    def test_main_calls_start_on_plan_trunk(self):
        for role in ("skeleton", "answer", "review", "amend"):
            with self.subTest(role=role), tmp_home() as root:
                fixture(root)
                path = root / "docs/plan/demo/plan.toml"
                write(path, path.read_text().replace('landing = "queue"', 'landing = "integration"'))
                self.amend_chain()
                fake = FakeRunner().on(["git", "rev-parse"], Result(0, str(root)))
                args = {"skeleton": ["core"], "amend": ["root"]}.get(role, [])
                with patch.object(calls, "run", fake), redirect_stdout(io.StringIO()), \
                     patch.object(calls, "start", return_value=dict(outcome="done", branch="calls/id")) as start:
                    self.assertEqual(calls.main([role, *args, "--plan", str(path.parent)]), 0)
                self.assertEqual(start.call_args.kwargs["base"], "demo/integration")

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

    def test_main_retire_land_amend_passes_plan_context_to_design_comparison(self):
        with tmp_home() as root:
            fixture(root)
            log.append("call.started", call="root", role="retire", subject="demo/retire", branch="calls/root")
            log.append("call.ended", call="root", outcome="done")
            log.append("branch.rejected", branch="calls/root", step="rebase", log="CONFLICT in x")
            fake = FakeRunner().on(["git", "rev-parse"], Result(0, str(root)))
            output = io.StringIO()
            with patch.object(calls, "run", fake), redirect_stdout(output), \
                 patch.object(designer, "changed_designs", side_effect=[["docs/design/x.md"], []]) as changes:
                self.assertEqual(calls.main(["amend", "root", "--plan", str(root / "docs/plan/demo"),
                                             "--brief-only"]), 0)
            for call in changes.call_args_list:
                self.assertEqual(call.args, (root, "demo"))
                self.assertEqual(call.kwargs["plan_path"], "docs/plan/demo")
                self.assertIs(call.kwargs["sh"], fake)
            self.assertIn("# Designs main changed since your branch", output.getvalue())
            self.assertEqual(fake.argvs(), [["git", "rev-parse", "--show-toplevel"], ["git", "fetch", "origin"]])

    def test_main_amend_runs_on_chain_branch_and_subject(self):
        with tmp_home() as root:
            fixture(root)
            self.amend_chain()
            fake = FakeRunner().on(["git", "rev-parse"], Result(0, str(root)))
            with patch.object(calls, "run", fake), redirect_stdout(io.StringIO()), \
                 patch.object(calls, "start", return_value={"outcome": "done", "branch": "calls/root"}) as start:
                self.assertEqual(calls.main(["amend", "root", "--plan", str(root / "docs/plan/demo")]), 0)
            self.assertEqual(start.call_args.args[:3], ("amend", "demo", root))
            self.assertEqual(start.call_args.kwargs, dict(sh=fake, base="main", branch="calls/root", amends="root"))

    def test_main_settle_is_report_only_medium_and_uses_chain_repository(self):
        for repo_name in ("agents", "fabrig"):
            with self.subTest(repo=repo_name), tmp_home() as root:
                fixture(root)
                path = root / "docs/plan/demo/plan.toml"
                write(path, path.read_text().replace('repo = "agents"', f'repo = "{repo_name}"'))
                self.amend_chain()
                log.append("call.started", call="amend", role="amend", amends="root")
                log.append("call.ended", call="amend", outcome="failed")
                repository = log.home() / "repos/fabrig" if repo_name == "fabrig" else root

                def rev(call):
                    return Result(0, str(root) if call.argv[-1] == "--show-toplevel" else "tip")

                def claude(call):
                    directory = Path(call.cwd).parent
                    text = (directory / "brief.md").read_text()
                    self.assertIn(calls.ROLES["settle"].read_text(), text)
                    self.assertIn("- Hold: the amend call ended failed", text)
                    self.assertIn("+held diff", text)
                    write(directory / "report.md", "Done: land\nKeep the branch.\n")
                    return Result(0, "{}")

                fake = FakeRunner().on(["git", "rev-parse"], rev)
                fake.on(["git", "merge-base"], Result(0, "base"))
                fake.on(["git", "diff"], Result(0, "+held diff\n")).on(["claude"], claude)
                with patch.object(calls, "run", fake), redirect_stdout(io.StringIO()):
                    self.assertEqual(calls.main(["settle", "root", "--plan", str(path.parent)]), 0)
                started, ended = log.read()[-2:]
                self.assertEqual((started["role"], started["subject"], started["settles"]),
                                 ("settle", "demo/settle", "root"))
                self.assertNotIn("branch", started)
                command = next(call for call in fake.calls if call.argv[0] == "claude")
                self.assertEqual(command.argv[command.argv.index("--effort") + 1], "medium")
                worktree = str(Path(command.cwd))
                self.assertIn(["git", "worktree", "add", "--detach", worktree, "origin/main"], fake.argvs())
                self.assertFalse(any(call.argv[:2] == ["git", "push"] for call in fake.calls))
                self.assertTrue(all(call.cwd == str(repository) for call in fake.calls
                                    if call.argv[:2] in (["git", "merge-base"], ["git", "diff"])))
                self.assertEqual(ended["outcome"], "done")
                self.assertEqual(list(call_review.chains(log.read())), ["root"])
                with patch.object(calls, "run", fake), patch.object(calls, "start") as start, \
                     redirect_stderr(io.StringIO()):
                    self.assertEqual(calls.main(["settle", "root", "--plan", str(path.parent)]), 1)
                start.assert_not_called()

    def test_settle_amend_guidance_reaches_next_real_amend_brief(self):
        with tmp_home() as root:
            fixture(root)
            self.amend_chain()
            log.append("chain.settled", call="root", subject="demo", settle="settle-1",
                       verdict="amend", text="Include extern blocks.\nKeep the parser.")
            log.append("run.started", run="root-2", task="root", kind="review")
            log.append("run.ended", run="root-2", outcome="failed")

            def claude(call):
                directory = Path(call.cwd).parent
                text = (directory / "brief.md").read_text()
                self.assertIn("Settlement (settle-1): Include extern blocks.\nKeep the parser.", text)
                self.assertLess(text.index(channel.SECTION), text.index("# The call you amend"))
                write(directory / "report.md", "Done: amended\n")
                return Result(0, "{}")

            fake = FakeRunner().on(["git", "rev-parse"], Result(0, str(root))).on(["claude"], claude)
            with patch.object(calls, "run", fake), redirect_stdout(io.StringIO()):
                self.assertEqual(calls.main(["amend", "root", "--plan", str(root / "docs/plan/demo")]), 0)
            self.assertEqual(log.read()[-2]["amends"], "root")

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
