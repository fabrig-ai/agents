import unittest
from dataclasses import replace
from pathlib import Path

from fab.plan import (EFFORTS, KINDS, MODES, Part, Plan, PlanError, Slice, Task,
                     load_plan, load_tasks, parse_task, problems)
from fab.tests.support import tmp_home


MINIMAL = 'draft = "draft"\nrepo = "repo"\npart = []\n'
FULL = '''draft = "draft"
repo = "repo"
sources = ["design.md", "another source"]
[buffer]
low = 0.5
high = 3
[[part]]
id = "core"
title = "Core files"
mode = "feature"
needs = []
design = "docs/design/fab.md, 4"
[[slice]]
id = 1
story = "A task runs"
parts = ["core"]
walk = true
'''
HEADER = 'id = "task"\npart = "core"\nkind = "feature"\n'


def spec(header=HEADER, body="# Task\n\nDo it.\n"):
    return "+++\n" + header + "+++\n" + body


def task(identifier, needs=(), part="core"):
    return Task(identifier, part, "feature", "repo", needs, (), "high", 25, "", identifier + ".md")


class PlanTest(unittest.TestCase):
    def read(self, text):
        with tmp_home() as home:
            path = home / "plan.toml"
            path.write_text(text)
            return load_plan(path)

    def test_minimal_plan_defaults(self):
        self.assertEqual(self.read(MINIMAL), Plan("draft", "repo", (), 1.0, 2.0, {}, ()))

    def test_full_plan(self):
        expected = Plan("draft", "repo", ("design.md", "another source"), 0.5, 3.0,
                        {"core": Part("core", "Core files", "feature", (), "docs/design/fab.md, 4")},
                        (Slice(1, "A task runs", ("core",), True),))
        self.assertEqual(self.read(FULL), expected)
        self.assertIs(type(self.read(FULL).high), float)

    def test_partial_buffer_uses_the_other_default(self):
        self.assertEqual(self.read(MINIMAL + "[buffer]\nlow = 2\n").high, 2.0)
        self.assertEqual(self.read(MINIMAL + "[buffer]\nhigh = 4\n").low, 1.0)

    def test_each_mode_is_known(self):
        for mode in MODES:
            with self.subTest(mode=mode):
                self.assertEqual(self.read(FULL.replace('mode = "feature"', f'mode = "{mode}"'))
                                 .parts["core"].mode, mode)

    def test_missing_keys_name_the_file(self):
        for line in ('draft = "draft"\n', 'repo = "repo"\n', 'id = "core"\n',
                     'title = "Core files"\n', 'mode = "feature"\n', 'needs = []\n',
                     'design = "docs/design/fab.md, 4"\n', 'id = 1\n',
                     'story = "A task runs"\n', 'parts = ["core"]\n', 'walk = true\n'):
            with self.subTest(line=line), self.assertRaisesRegex(PlanError, r"plan\.toml: missing"):
                self.read(FULL.replace(line, ""))
        with self.assertRaisesRegex(PlanError, r"plan\.toml: missing part"):
            self.read(MINIMAL.replace("part = []\n", ""))

    def test_wrong_types_name_the_file(self):
        replacements = [
            ('draft = "draft"', 'draft = 1'), ('repo = "repo"', 'repo = false'),
            ('sources = ["design.md", "another source"]', 'sources = "x"'),
            ('sources = ["design.md", "another source"]', 'sources = [1]'),
            ('low = 0.5', 'low = "one"'), ('low = 0.5', 'low = true'),
            ('high = 3', 'high = false'), ('high = 3', 'high = []'),
            ('id = "core"', 'id = 1'), ('title = "Core files"', 'title = []'),
            ('mode = "feature"', 'mode = 1'), ('needs = []', 'needs = "core"'),
            ('needs = []', 'needs = [1]'),
            ('design = "docs/design/fab.md, 4"', 'design = false'),
            ('id = 1', 'id = "1"'), ('id = 1', 'id = true'),
            ('story = "A task runs"', 'story = 1'), ('parts = ["core"]', 'parts = "core"'),
            ('parts = ["core"]', 'parts = [1]'), ('walk = true', 'walk = "yes"'),
        ]
        texts = [FULL.replace(old, new) for old, new in replacements]
        texts += [MINIMAL.replace("part = []", "part = 1"),
                  MINIMAL.replace("part = []", 'part = ["core"]'),
                  MINIMAL + 'buffer = "bad"\n', MINIMAL + 'slice = "bad"\n',
                  MINIMAL + 'slice = [1]\n']
        for text in texts:
            with self.subTest(text=text), self.assertRaisesRegex(PlanError, r"plan\.toml:"):
                self.read(text)

    def test_unknown_mode_and_duplicate_part(self):
        with self.assertRaisesRegex(PlanError, r"plan\.toml:.*unknown mode"):
            self.read(FULL.replace('mode = "feature"', 'mode = "magic"'))
        duplicate = FULL.split("[[slice]]")[0]
        duplicate += "[[part]]" + FULL.split("[[part]]")[1].split("[[slice]]")[0]
        with self.assertRaisesRegex(PlanError, r"plan\.toml: duplicate part core"):
            self.read(duplicate)

    def test_bad_toml_and_missing_file(self):
        with self.assertRaisesRegex(PlanError, r"plan\.toml:"):
            self.read('draft = "unterminated')
        with tmp_home() as home, self.assertRaisesRegex(PlanError, r"absent\.toml:"):
            load_plan(home / "absent.toml")

    def test_repository_plan_and_specs_hold_together(self):
        with tmp_home():
            directory = Path(__file__).resolve().parents[2] / "docs/plan/agents-rebuild"
            plan = load_plan(directory / "plan.toml")
            tasks = load_tasks(directory / "tasks", plan.draft, plan.repo)
            self.assertTrue(tasks)
            self.assertIn("agents-rebuild/files", tasks)
            self.assertEqual(problems(plan, tasks), [])


class TaskTest(unittest.TestCase):
    def parse(self, text):
        return parse_task(text, "task.md", "draft", "repo")

    def test_required_fields_and_defaults(self):
        result = self.parse(spec())
        self.assertEqual(result, Task("draft/task", "core", "feature", "repo", (), (),
                                      "high", 25, "# Task\n\nDo it.\n", "task.md"))
        self.assertEqual(result.draft, "draft")
        self.assertEqual(result.name, "task")

    def test_optional_fields_and_full_ids(self):
        header = HEADER.replace('id = "task"', 'id = "other/task"') + '''repo = "other-repo"
needs = ["first", "other/second"]
files = ["fab/*.py", "docs/**"]
effort = "medium"
minutes = 30
'''
        result = self.parse(spec(header))
        self.assertEqual(result.id, "other/task")
        self.assertEqual(result.needs, ("draft/first", "other/second"))
        self.assertEqual(result.repo, "other-repo")
        self.assertEqual(result.files, ("fab/*.py", "docs/**"))
        self.assertEqual((result.effort, result.minutes), ("medium", 30))

    def test_body_kept_verbatim(self):
        for body in ("", "\n# Title\n\n  indented\n+++\n", "no final newline", "\r\n# Body\r\n"):
            with self.subTest(body=body):
                self.assertEqual(self.parse(spec(body=body)).body, body)
        text = spec(body="\n# Body\n").replace("\n", "\r\n")
        self.assertEqual(self.parse(text).body, "\r\n# Body\r\n")

    def test_each_kind_and_effort(self):
        for kind in KINDS:
            with self.subTest(kind=kind):
                self.assertEqual(self.parse(spec(HEADER.replace('"feature"', f'"{kind}"'))).kind, kind)
        for effort in EFFORTS:
            with self.subTest(effort=effort):
                self.assertEqual(self.parse(spec(HEADER + f'effort = "{effort}"\n')).effort, effort)

    def test_missing_header_and_bad_toml(self):
        for text in ("", "# no header", "\n" + spec(), "+++\n" + HEADER,
                     '+++\nid = "broken\n+++\n'):
            with self.subTest(text=text), self.assertRaisesRegex(PlanError, r"task\.md:"):
                self.parse(text)

    def test_missing_required_fields(self):
        for line in HEADER.splitlines(keepends=True):
            with self.subTest(line=line), self.assertRaisesRegex(PlanError, r"task\.md: missing"):
                self.parse(spec(HEADER.replace(line, "")))

    def test_bad_values(self):
        headers = [HEADER.replace('id = "task"', 'id = 1'),
                   HEADER.replace('part = "core"', 'part = []'),
                   HEADER.replace('kind = "feature"', 'kind = 1'),
                   HEADER.replace('kind = "feature"', 'kind = "fix"')]
        headers += [HEADER + line + "\n" for line in (
            'repo = 1', 'needs = "task"', 'needs = [1]', 'files = false', 'files = [1]',
            'effort = 1', 'effort = "low"', 'minutes = 0', 'minutes = -1',
            'minutes = 1.5', 'minutes = true', 'minutes = "25"')]
        for header in headers:
            with self.subTest(header=header), self.assertRaisesRegex(PlanError, r"task\.md:"):
                self.parse(spec(header))

    def test_load_sorted_markdown_only_and_preserve_body(self):
        with tmp_home() as home:
            (home / "z.md").write_text(spec(HEADER.replace('"task"', '"a"')))
            body = "\r\n# Body\r\n"
            (home / "a.md").write_bytes(spec(HEADER.replace('"task"', '"z"'), body).encode())
            (home / "ignored.txt").write_text("not a spec")
            (home / "nested").mkdir()
            (home / "nested" / "ignored.md").write_text("not a spec")
            tasks = load_tasks(home, "draft", "repo")
            self.assertEqual(list(tasks), ["draft/z", "draft/a"])
            self.assertEqual(tasks["draft/z"].body, body)
            self.assertEqual(tasks["draft/z"].path, str(home / "a.md"))

    def test_duplicate_task_names_both_files(self):
        with tmp_home() as home:
            (home / "a.md").write_text(spec())
            (home / "b.md").write_text(spec(HEADER.replace('"task"', '"draft/task"')))
            with self.assertRaises(PlanError) as caught:
                load_tasks(home, "draft", "repo")
            for name in ("draft/task", "a.md", "b.md"):
                self.assertIn(name, str(caught.exception))

    def test_load_propagates_spec_error_with_path(self):
        with tmp_home() as home:
            (home / "bad.md").write_text("no header")
            with self.assertRaisesRegex(PlanError, r"bad\.md:"):
                load_tasks(home, "draft", "repo")


class ProblemsTest(unittest.TestCase):
    def setUp(self):
        self.parts = {name: Part(name, name, "feature", (), "design.md") for name in ("core", "next")}
        self.plan = Plan("draft", "repo", (), 1.0, 2.0, self.parts,
                         (Slice(1, "story", ("core", "next"), True),))

    def test_sound_dependencies(self):
        self.parts["next"] = replace(self.parts["next"], needs=("core",))
        tasks = {"draft/a": task("draft/a"), "draft/b": task("draft/b", ("draft/a",))}
        self.assertEqual(problems(self.plan, tasks), [])

    def test_each_unknown_reference_and_missing_slice_in_stable_order(self):
        self.parts["core"] = replace(self.parts["core"], needs=("heavy-x",))
        plan = replace(self.plan, slices=(Slice(2, "story", ("core", "absent"), False),))
        tasks = {"draft/a": task("draft/a", ("draft/missing",), "no-part")}
        expected = ["part core needs unknown part heavy-x", "part next is in no slice",
                    "slice 2 names unknown part absent", "task draft/a names unknown part no-part",
                    "task draft/a needs unknown task draft/missing"]
        self.assertEqual(problems(plan, tasks), expected)
        self.assertEqual(problems(replace(plan, parts=dict(reversed(list(self.parts.items())))), tasks), expected)

    def test_part_cycle_and_self_cycle(self):
        self.parts["core"] = replace(self.parts["core"], needs=("next",))
        self.parts["next"] = replace(self.parts["next"], needs=("core",))
        self.assertEqual(problems(self.plan, {}), ["part cycle: core, next"])
        self.parts["core"] = replace(self.parts["core"], needs=("core",))
        self.parts["next"] = replace(self.parts["next"], needs=())
        self.assertEqual(problems(self.plan, {}), ["part cycle: core"])

    def test_task_cycles_once_with_sorted_members(self):
        tasks = {"draft/c": task("draft/c", ("draft/b",)),
                 "draft/b": task("draft/b", ("draft/c", "draft/a")),
                 "draft/a": task("draft/a", ("draft/b",))}
        self.assertEqual(problems(self.plan, tasks), ["task cycle: draft/a, draft/b, draft/c"])
        self.assertEqual(problems(self.plan, dict(reversed(list(tasks.items())))),
                         ["task cycle: draft/a, draft/b, draft/c"])

    def test_disjoint_task_cycles_and_acyclic_dependent(self):
        tasks = {"draft/a": task("draft/a", ("draft/a",)),
                 "draft/b": task("draft/b", ("draft/c",)),
                 "draft/c": task("draft/c", ("draft/b",)),
                 "draft/d": task("draft/d", ("draft/a", "draft/b"))}
        self.assertEqual(problems(self.plan, tasks), ["task cycle: draft/a", "task cycle: draft/b, draft/c"])

    def test_diamond_is_not_a_cycle(self):
        tasks = {"draft/a": task("draft/a"), "draft/b": task("draft/b", ("draft/a",)),
                 "draft/c": task("draft/c", ("draft/a",)),
                 "draft/d": task("draft/d", ("draft/b", "draft/c"))}
        self.assertEqual(problems(self.plan, tasks), [])
