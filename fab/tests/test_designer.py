"""Designer calls compile whole contracts and use fake services (docs/design/fab.md, 13.3)."""

import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

from fab import atomic, calls, cli, designer, log
from fab import run as runs
from fab.plan import Part, Plan, Task
from fab.sh import Failed, Result
from fab.tests.support import FakeRunner, git, git_pair, tmp_home

FACTS = dict(call_id="c1", branch="calls/c1", report="/reports/c1.md")


def fixture(root):
    parts = {
        "probe": Part("probe", "Measure", "probe", (), "docs/design/measure.md, 1"),
        "reader": Part("reader", "Read the result", "feature", ("probe",), "docs/design/reader.md"),
        "contract": Part("contract", "Shared contract", "feature", (), "docs/design/measure.md", contract=True),
    }
    atomic.write(root / "docs/design/measure.md", "# Measurement\nAll the design.\n")
    atomic.write(root / "docs/design/measure.status.md", "Measured.\n")
    atomic.write(root / "docs/design/draft/user.md", "The user's whole draft.\n")
    atomic.write(root / "fab/api.py", 'def primitive():\n    """A primitive."""\n    pass\n')
    plan = Plan("demo", "agents", ("docs/design/draft/user.md",), 1.0, 2.0, parts, ())
    atomic.write(root / "docs/plan/demo/plan.toml", '\n'.join([
        'draft = "demo"', 'repo = "agents"', 'sources = ["docs/design/draft/user.md"]',
        *[f'[[part]]\nid = "{part.id}"\ntitle = "{part.title}"\nmode = "{part.mode}"\n'
          f'needs = {list(part.needs)!r}\ndesign = "{part.design}"\ncontract = {str(part.contract).lower()}'
          for part in parts.values()],
    ]))
    atomic.write(log.home() / "runs/demo/probe-1/report.md", "Done: 42 milliseconds\nFull measurement.\n")
    return plan


class DesignerTest(unittest.TestCase):
    def setUp(self):
        self.root = self.enterContext(tmp_home())

    def test_subject_roles_and_refusals(self):
        for role, part, expected in (("cut", None, "demo/cut"), ("retire", None, "demo/retire"),
                                     ("contract", "shared", "demo/shared"),
                                     ("decision", "probe", "demo/probe/decision")):
            self.assertEqual(designer.subject("demo", role, part), expected)
        for role, part in (("other", None), ("contract", None), ("decision", None),
                           ("contract", ""), ("decision", ""), ("cut", "part"),
                           ("retire", "part"), ("cut", "")):
            with self.subTest(role=role, part=part), self.assertRaises(ValueError):
                designer.subject("demo", role, part)

    def test_uncut_defaults_and_sources(self):
        self.assertEqual(designer.uncut("demo", "agents"), Plan("demo", "agents", (), 1.0, 2.0, {}, ()))
        self.assertEqual(designer.uncut("demo", "agents", ["draft.md"]).sources, ("draft.md",))

    def test_repository_matches_each_remote_and_refuses_unknown_or_failed_git(self):
        for name, url in runs.REMOTES.items():
            fake = FakeRunner().on(["git"], Result(0, f"  {url}\n"))
            runner = Mock(wraps=fake)
            self.assertEqual(designer.repository(self.root, sh=runner), name)
            runner.assert_called_once_with(["git", "remote", "get-url", "origin"],
                                           cwd=str(self.root), check=True)
        with self.assertRaisesRegex(ValueError, "unknown-url"):
            designer.repository(self.root, sh=FakeRunner().on(["git"], Result(0, "unknown-url")))
        with self.assertRaises(Failed):
            designer.repository(self.root, sh=FakeRunner().on(["git"], Result(1)))

    def test_designs_and_status_paths(self):
        self.assertEqual(designer.designs(self.root), [])
        for name in ("z.md", "a.md", "README.md", "a.status.md", "draft/input.md", "other.txt"):
            atomic.write(self.root / designer.DESIGNS / name, "content")
        (self.root / designer.DESIGNS / "directory.md").mkdir()
        self.assertEqual(designer.designs(self.root), ["docs/design/a.md", "docs/design/z.md"])
        self.assertEqual(designer.status_path("docs/design/a.md"), "docs/design/a.status.md")
        for name in ("a.txt", "a.status.md", "a.md.more"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                designer.status_path(name)

    def test_design_index_titles_lines_and_status_presence(self):
        self.assertEqual(designer.design_index(self.root), "(none)")
        atomic.write(self.root / "docs/design/a.md", "intro\n# Title\n# Later title\n")
        atomic.write(self.root / "docs/design/a.status.md", "present")
        atomic.write(self.root / "docs/design/b.md", "## No title\nlast")
        self.assertEqual(designer.design_index(self.root),
                         "- `docs/design/a.md` — Title (3 lines; status `docs/design/a.status.md`)\n"
                         "- `docs/design/b.md` — (untitled) (2 lines; no status file)")

    def test_retire_due_requires_nonempty_finished_plan_and_no_successful_retire(self):
        part = Part("core", "Core", "feature", (), "design.md")
        plan = Plan("demo", "agents", (), 1.0, 2.0, {"core": part}, ())
        task = Task("demo/a", "core", "feature", "agents", (), (), "high", 25, "", "a.md")
        tasks = {task.id: task}
        landed = [{"ev": "branch.landed", "task": task.id, "tip": "tip", "main": "main"}]
        self.assertFalse(designer.retire_due(plan, {}, []))
        self.assertTrue(designer.retire_due(replace(plan, parts={"core": replace(part, done=True)}), {}, []))
        self.assertTrue(designer.retire_due(plan, tasks, landed))
        self.assertFalse(designer.retire_due(replace(plan, parts={}), {}, []))
        self.assertFalse(designer.retire_due(replace(plan, retired=True), tasks, landed))
        starts = [{"ev": "call.started", "role": "retire", "subject": "demo/retire", "call": "r1"}]
        self.assertTrue(designer.retire_due(plan, tasks, landed + starts))
        for outcome, due in (("done", False), ("failed", True)):
            self.assertEqual(designer.retire_due(plan, tasks, landed + starts +
                             [{"ev": "call.ended", "call": "r1", "outcome": outcome}]), due)
        for role, subject in (("cut", "demo/retire"), ("retire", "other/retire")):
            events = [{"ev": "call.started", "role": role, "subject": subject, "call": "r1"},
                      {"ev": "call.ended", "call": "r1", "outcome": "done"}]
            self.assertTrue(designer.retire_due(plan, tasks, landed + events))

    def test_enlist_creates_adds_once_and_preserves_order_and_spelling(self):
        first = self.root / "missing/first"
        second = self.root / "second"
        self.assertTrue(designer.enlist(first))
        self.assertFalse(first.exists())
        self.assertFalse(designer.enlist(first.parent / "other/../first"))
        self.assertTrue(designer.enlist(second))
        self.assertEqual((log.home() / "plans").read_text(), f"{first}\n{second}\n")
        atomic.write(log.home() / "plans", f"{first.parent}/../missing/first\n{second}\n")
        self.assertFalse(designer.enlist(first))
        self.assertTrue(designer.enlist(self.root / "third"))
        self.assertEqual((log.home() / "plans").read_text(),
                         f"{first.parent}/../missing/first\n{second}\n{self.root}/third\n")

    def assert_sections(self, text, names):
        positions = [text.index(f"# {name}\n\n") for name in names]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("- Call: c1\n- Branch: `calls/c1`", text)
        self.assertIn("`/reports/c1.md`", text)

    def test_cut_brief_sections_index_plans_inventory_and_empty_repository(self):
        plan = fixture(self.root)
        atomic.write(self.root / "docs/plan/aaa/plan.toml", "other plan")
        text = designer.cut_brief(plan, self.root, **FACTS)
        self.assert_sections(text, ["Role", "Call facts", "The draft", "The user's drafts",
                                    "Designs", "Plans", "Inventory"])
        for fragment in (calls.ROLES["cut"].read_text(), "- Draft: demo", "- Repository: agents",
                         "- Plan: write `docs/plan/demo/plan.toml`", "- Sources: `docs/design/draft/user.md`",
                         "The user's whole draft.", "Measurement (2 lines; status", "A primitive."):
            self.assertIn(fragment, text)
        self.assertLess(text.index("- `docs/plan/aaa/plan.toml`"), text.index("- `docs/plan/demo/plan.toml`"))
        empty = self.root / "empty"
        empty.mkdir()
        text = designer.cut_brief(designer.uncut("new", "agents"), empty, **FACTS)
        for section in ("Designs", "Plans", "Inventory"):
            self.assertIn(f"# {section}\n\n(none)", text)

    def test_decision_brief_sections_readers_and_refusals(self):
        plan = fixture(self.root)
        text = designer.decision_brief(plan, "probe", {}, {}, self.root, "demo/probe-1", **FACTS)
        self.assert_sections(text, ["Role", "Call facts", "Plan parts and slices", "The probe",
                                    "The probe's report", "Its readers", "The user's drafts", "Cited design"])
        for fragment in (calls.ROLES["decision"].read_text(), "Plan: `docs/plan/demo/plan.toml`",
                         "- Part: probe\n- Title: Measure\n- Design: docs/design/measure.md, 1",
                         "- Run: demo/probe-1", f"- Report: `{log.home()}/runs/demo/probe-1/report.md`",
                         "Done: 42 milliseconds\nFull measurement.",
                         "- reader — Read the result (design: docs/design/reader.md; not designed)",
                         "All the design."):
            self.assertIn(fragment, text)
        task = Task("demo/read", "reader", "feature", "agents", (), (), "high", 25, "", "read.md")
        for status, expected in (("running", "designed"), ("landed", "done")):
            text = designer.decision_brief(plan, "probe", {task.id: task}, {task.id: status},
                                           self.root, "demo/probe-1", **FACTS)
            self.assertIn(f"design: docs/design/reader.md; {expected})", text)
        plan = replace(plan, parts={"probe": plan.parts["probe"]})
        self.assertIn("# Its readers\n\n(none)", designer.decision_brief(
            plan, "probe", {}, {}, self.root, "demo/probe-1", **FACTS))
        for part, run_id, reason in (("absent", "demo/probe-1", "unknown part"),
                                     ("probe", "missing", "runs/missing/report.md")):
            with self.subTest(part=part), self.assertRaisesRegex(ValueError, reason):
                designer.decision_brief(plan, part, {}, {}, self.root, run_id, **FACTS)
        path = log.home() / "runs/demo/probe-1/report.md"
        sibling = path.with_name("report.invalid")
        sibling.write_bytes(b"\xff")
        sibling.replace(path)
        with self.assertRaisesRegex(ValueError, "runs/demo/probe-1/report.md"):
            designer.decision_brief(plan, "probe", {}, {}, self.root, "demo/probe-1", **FACTS)
        with self.assertRaisesRegex(ValueError, "not a probe"):
            designer.decision_brief(replace(plan, parts={"probe": replace(plan.parts["probe"], mode="feature")}),
                                    "probe", {}, {}, self.root, "demo/probe-1", **FACTS)

    def test_retire_brief_whole_designs_statuses_removed_and_missing(self):
        plan = fixture(self.root)
        atomic.write(self.root / "docs/design/b.md", "# B\nWhole second design.\n")
        text = designer.retire_brief(plan, {}, {}, self.root,
                                     ["docs/design/measure.md", "docs/design/b.md", "docs/design/gone.md"], **FACTS)
        self.assert_sections(text, ["Role", "Call facts", "Plan parts and slices", "The user's drafts",
                                    "Designs changed since the plan started", "Inventory"])
        for fragment in (calls.ROLES["retire"].read_text(), "Plan: `docs/plan/demo/plan.toml`",
                         "## docs/design/measure.md\n\n# Measurement\nAll the design.",
                         "## docs/design/measure.status.md\n\nMeasured.",
                         "## docs/design/b.status.md\n\n(no status file)",
                         "## docs/design/gone.md\n\n(removed)", "A primitive."):
            self.assertIn(fragment, text)
        self.assertLess(text.index("## docs/design/measure.md"), text.index("## docs/design/b.md"))
        self.assertIn("# Designs changed since the plan started\n\n(none)",
                      designer.retire_brief(plan, {}, {}, self.root, [], **FACTS))

    def test_each_brief_refuses_past_limit(self):
        plan = fixture(self.root)
        with patch.object(calls, "BRIEF_LIMIT", 1):
            for compile_brief in (lambda: designer.cut_brief(plan, self.root, **FACTS),
                                  lambda: designer.decision_brief(plan, "probe", {}, {}, self.root,
                                                                 "demo/probe-1", **FACTS),
                                  lambda: designer.retire_brief(plan, {}, {}, self.root,
                                                               ["docs/design/measure.md"], **FACTS)):
                with self.assertRaisesRegex(ValueError, "BRIEF_LIMIT.*largest section"):
                    compile_brief()


class ChangedDesignsTest(unittest.TestCase):
    def setUp(self):
        self.home = self.enterContext(tmp_home())
        _, self.repo = git_pair(self.home)

    def commit(self, message):
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", message)

    def test_history_includes_cut_and_status_only_but_excludes_earlier_drafts_and_readme(self):
        for name in ("after", "before", "status-only", "gone"):
            atomic.write(self.repo / f"docs/design/{name}.md", "# Before\n")
        self.commit("Design before the plan")
        atomic.write(self.repo / "docs/plan/demo/plan.toml", "plan")
        atomic.write(self.repo / "docs/design/cut.md", "# Cut\n")
        self.commit("Cut the plan and its design")
        for name in ("after.md", "status-only.status.md", "README.md", "draft/user.md", "ignore.txt"):
            atomic.write(self.repo / "docs/design" / name, "Changed\n")
        (self.repo / "docs/design/gone.md").unlink()
        self.commit("Change a design and a status")
        expected = ["docs/design/after.md", "docs/design/cut.md", "docs/design/gone.md",
                    "docs/design/status-only.md"]
        self.assertEqual(designer.changed_designs(self.repo, "demo", rev="HEAD"), expected)
        (self.repo / "docs/plan/demo/plan.toml").unlink()
        self.commit("Remove the plan")
        atomic.write(self.repo / "docs/plan/demo/plan.toml", "plan again")
        self.commit("Add the plan again")
        git(self.repo, "update-ref", "refs/remotes/origin/main", "HEAD")
        self.assertEqual(designer.changed_designs(self.repo, "demo"), expected)
        with self.assertRaisesRegex(ValueError, "docs/plan/missing/plan.toml"):
            designer.changed_designs(self.repo, "missing", rev="HEAD")

    def test_root_cut_uses_tree_and_converts_status_paths(self):
        atomic.write(self.repo / "docs/plan/demo/plan.toml", "plan")
        atomic.write(self.repo / "docs/design/root.md", "# Root\n")
        atomic.write(self.repo / "docs/design/orphan.status.md", "Status without its design\n")
        atomic.write(self.repo / "docs/design/README.md", "Index\n")
        atomic.write(self.repo / "docs/design/nested.status.status.md", "Not a design's status\n")
        atomic.write(self.repo / "docs/design/README.status.md", "Index status\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "--amend", "-q", "--no-edit")
        self.assertEqual(designer.changed_designs(self.repo, "demo", rev="HEAD"),
                         ["docs/design/orphan.md", "docs/design/root.md"])


class MainTest(unittest.TestCase):
    def setUp(self):
        self.home = self.enterContext(tmp_home())
        self.root = self.home / "repo"
        fixture(self.root)
        self.fake = FakeRunner().on(["git", "rev-parse", "--show-toplevel"], Result(0, str(self.root)))
        self.fake.on(["git", "remote"], Result(0, runs.REMOTES["agents"]))
        self.fake.on(["git", "log"], Result(0, "cut-commit\n"))
        self.directory = self.root / "docs/plan/demo"

    def argv(self, role):
        args = ["call", role]
        if role == "contract":
            args.append("contract")
        elif role == "decision":
            args.extend(["probe", "--run", "demo/probe-1"])
        elif role == "cut":
            args.extend(["--source", "docs/design/draft/user.md"])
        return [*args, "--plan", str(self.directory)]

    def test_brief_only_each_role_through_cli(self):
        for role in designer.ROLES:
            with self.subTest(role=role):
                self.directory = self.root / "docs/plan" / ("new" if role == "cut" else "demo")
                output = io.StringIO()
                with patch.object(designer, "run", self.fake), patch.object(calls, "start") as start, \
                     redirect_stdout(output):
                    self.assertEqual(cli.main([*self.argv(role), "--brief-only"]), 0)
                start.assert_not_called()
                self.assertIn(calls.ROLES[role].read_text(), output.getvalue())
                self.assertIn("# Call facts", output.getvalue())
                self.assertFalse((log.home() / "plans").exists())
        self.assertEqual(self.fake.calls[0].cwd, str(self.root / "docs/plan"))

    def test_cut_runs_enlisted_with_subject_root_and_brief(self):
        self.directory = self.root / "docs/plan/new"
        def start(role, subject, root, text, **options):
            self.assertEqual((role, subject, root), ("cut", "new/cut", self.root))
            self.assertIn("# The draft", text)
            self.assertEqual(options, dict(sh=self.fake))
            self.assertEqual((log.home() / "plans").read_text(), f"{self.directory}\n")
            return dict(outcome="done", branch="calls/new")
        output = io.StringIO()
        with patch.object(designer, "run", self.fake), patch.object(calls, "start", side_effect=start), \
             redirect_stdout(output):
            self.assertEqual(cli.main(self.argv("cut")), 0)
        self.assertEqual(output.getvalue(), "done calls/new\n")

    def test_other_roles_start_and_return_outcome(self):
        for role, part, outcome in (("contract", "contract", "done"), ("decision", "probe", "question"),
                                    ("retire", None, "done")):
            with self.subTest(role=role), patch.object(designer, "run", self.fake), \
                 patch.object(calls, "start", return_value=dict(outcome=outcome, branch="calls/c")) as start, \
                 redirect_stdout(io.StringIO()):
                self.assertEqual(cli.main(self.argv(role)), 0 if outcome == "done" else 1)
                self.assertEqual(start.call_args.args[:3],
                                 (role, designer.subject("demo", role, part), self.root))

    def test_cut_refusals_start_nothing(self):
        cases = [(self.directory, "docs/design/draft/user.md", "already exists"),
                 (self.root / "elsewhere/new", "docs/design/draft/user.md", "PLAN_DIR"),
                 (self.root / "docs/plan/new", "missing.md", "source"),
                 (self.root / "docs/plan/new", str(self.root / "design.md"), "source"),
                 (self.root / "docs/plan/new", "../outside.md", "source")]
        atomic.write(self.root.parent / (self.root.name + "-outside.md"), "outside")
        outside = self.root.parent / (self.root.name + "-outside.md")
        try:
            (self.root / "linked.md").symlink_to(outside)
            cases.append((self.root / "docs/plan/new", "linked.md", "source"))
            for directory, source, reason in cases:
                errors = io.StringIO()
                with self.subTest(directory=directory, source=source), patch.object(designer, "run", self.fake), \
                     patch.object(calls, "start") as start, redirect_stderr(errors):
                    self.assertEqual(cli.main(["call", "cut", "--plan", str(directory), "--source", source]), 1)
                start.assert_not_called()
                self.assertIn(reason, errors.getvalue())
                self.assertFalse((log.home() / "plans").exists())
        finally:
            outside.unlink()

    def test_contract_retire_and_git_refusals(self):
        for args, reason in ((["contract", "absent"], "unknown part"),
                             (["contract", "reader"], "not a contract")):
            errors = io.StringIO()
            with patch.object(designer, "run", self.fake), patch.object(calls, "start") as start, redirect_stderr(errors):
                self.assertEqual(designer.main([*args, "--plan", str(self.directory)]), 1)
            start.assert_not_called()
            self.assertIn(reason, errors.getvalue())
        path = self.directory / "plan.toml"
        atomic.write(path, 'retired = true\n' + path.read_text())
        with patch.object(designer, "run", self.fake), patch.object(calls, "start") as start, redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(self.argv("retire")), 1)
        start.assert_not_called()
        fake = FakeRunner().on(["git"], Result(1, err="git failed"))
        with patch.object(designer, "run", fake), patch.object(calls, "start") as start, redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(self.argv("contract")), 1)
        start.assert_not_called()
