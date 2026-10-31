"""Designer calls compile contracts from plans and history (docs/design/fab.md, 13.3)."""

import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

from fab import atomic, calls, cli, designer, log
from fab import run as runs
from fab.plan import Part, Plan, Task, load_plan, load_tasks
from fab.sh import Failed, Result
from fab.tests.support import FakeRunner, git, git_pair, tmp_home

FACTS = dict(call_id="call-1", branch="calls/call-1", report="/reports/call-1.md")
SOURCE = "docs/design/draft/demo.md"
DESIGN = "docs/design/core.md"


def fixture(root):
    atomic.write(root / SOURCE, "The user's draft, whole.\n")
    atomic.write(root / DESIGN, "# Core design\n\n## 1. Contract\nKeep this contract.\n")
    atomic.write(root / "docs/design/core.status.md", "Core is designed.\n")
    atomic.write(root / "fab/api.py", 'def existing():\n    """Existing primitive."""\n    return 1\n')
    atomic.write(root / "docs/plan/demo/plan.toml", '''draft = "demo"
repo = "agents"
sources = ["docs/design/draft/demo.md"]
[[part]]
id = "base"
title = "Shared base"
mode = "feature"
needs = []
design = "docs/design/core.md, 1"
contract = true
[[part]]
id = "probe"
title = "Measure it"
mode = "probe"
needs = ["base"]
design = "docs/design/core.md, 2"
[[part]]
id = "reader"
title = "Use the measurement"
mode = "feature"
needs = ["probe", "base"]
design = "docs/design/core.md, 3"
[[slice]]
id = 1
story = "Build it"
parts = ["base", "probe", "reader"]
walk = true
''')
    atomic.write(root / "docs/plan/demo/tasks/base.md",
                 '+++\nid = "base"\npart = "base"\nkind = "interface"\n+++\nBase spec.\n')
    atomic.write(log.home() / "runs/demo/probe-1/report.md", "Done: measured 42\nAll measurements.\n")
    plan = load_plan(root / "docs/plan/demo/plan.toml")
    return plan, load_tasks(root / "docs/plan/demo/tasks", plan.draft, plan.repo)


def runner(root):
    return (FakeRunner().on(["git", "rev-parse"], Result(0, str(root) + "\n"))
            .on(["git", "remote"], Result(0, runs.REMOTES["agents"] + "\n"))
            .on(["git", "log"], Result(0, "start\n"))
            .on(["git", "diff"], Result(0, DESIGN + "\n")))


class SubjectTest(unittest.TestCase):
    def test_subject_for_each_role(self):
        for role, part, expected in (("cut", None, "draft/cut"), ("retire", None, "draft/retire"),
                                     ("contract", "core", "draft/core"),
                                     ("decision", "probe", "draft/probe/decision")):
            with self.subTest(role=role):
                self.assertEqual(designer.subject("draft", role, part), expected)

    def test_invalid_role_and_part_combinations(self):
        for role, part in (("unknown", None), ("contract", None), ("decision", None),
                           ("contract", ""), ("decision", ""), ("cut", "core"),
                           ("retire", "core"), ("cut", "")):
            with self.subTest(role=role, part=part), self.assertRaises(ValueError):
                designer.subject("draft", role, part)

    def test_uncut_defaults_and_sources(self):
        sources = [SOURCE, "another.md"]
        self.assertEqual(designer.uncut("draft", "agents", sources),
                         Plan("draft", "agents", tuple(sources), 1.0, 2.0, {}, ()))
        self.assertEqual(designer.uncut("draft", "agents").sources, ())


class FilesTest(unittest.TestCase):
    def setUp(self):
        self.root = self.enterContext(tmp_home())

    def test_repository_matches_every_remote_and_checks_git(self):
        for name, url in runs.REMOTES.items():
            with self.subTest(name=name):
                fake = FakeRunner().on(["git"], Result(0, "  " + url + "\n"))
                checked = Mock(wraps=fake)
                self.assertEqual(designer.repository(self.root, sh=checked), name)
                self.assertEqual(fake.argvs(), [["git", "remote", "get-url", "origin"]])
                self.assertEqual(checked.call_args.kwargs, dict(cwd=str(self.root), check=True))
        with self.assertRaisesRegex(ValueError, "unknown.example/repo"):
            designer.repository(self.root, sh=FakeRunner().on(["git"], Result(0, "unknown.example/repo")))
        with self.assertRaises(Failed):
            designer.repository(self.root, sh=FakeRunner().on(["git"], Result(1)))

    def test_designs_exclude_readme_status_drafts_and_directories(self):
        self.assertEqual(designer.designs(self.root), [])
        for name in ("z.md", "a.md", "README.md", "a.status.md", "draft/input.md", "notes.txt"):
            atomic.write(self.root / "docs/design" / name, "text\n")
        (self.root / "docs/design/directory.md").mkdir()
        self.assertEqual(designer.designs(self.root), ["docs/design/a.md", "docs/design/z.md"])

    def test_status_paths(self):
        self.assertEqual(designer.status_path(DESIGN), "docs/design/core.status.md")
        for name in ("core", "core.txt", "core.status.md"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                designer.status_path(name)

    def test_design_index_titles_lines_status_and_no_title(self):
        self.assertEqual(designer.design_index(self.root), "(none)")
        atomic.write(self.root / "docs/design/a.md", "before\n# First title\n# Second title\nlast")
        atomic.write(self.root / "docs/design/a.status.md", "Present")
        atomic.write(self.root / "docs/design/z.md", "No heading\n\n")
        self.assertEqual(designer.design_index(self.root),
                         "- `docs/design/a.md` — First title (4 lines; status `docs/design/a.status.md`)\n"
                         "- `docs/design/z.md` — (untitled) (2 lines; no status file)")

    def test_enlist_creates_once_keeps_order_and_compares_resolved_paths(self):
        first, second = self.root / "one", self.root / "two"
        self.assertFalse(first.exists())
        self.assertTrue(designer.enlist(first))
        self.assertTrue(designer.enlist(second))
        with patch.object(designer.atomic, "write", wraps=atomic.write) as write:
            self.assertFalse(designer.enlist(first / ".." / "one"))
        write.assert_not_called()
        self.assertEqual((log.home() / "plans").read_text(), f"{first}\n{second}\n")

    def test_enlist_recognizes_existing_relative_line(self):
        relative = Path("docs/plan/demo")
        atomic.write(log.home() / "plans", f"{relative}\n")
        self.assertFalse(designer.enlist(relative.resolve()))
        self.assertEqual((log.home() / "plans").read_text(), f"{relative}\n")


class HistoryTest(unittest.TestCase):
    def setUp(self):
        self.home = self.enterContext(tmp_home())
        _, self.root = git_pair(self.home)

    def commit(self, title):
        git(self.root, "add", ".")
        git(self.root, "commit", "-qm", title)
        return git(self.root, "rev-parse", "HEAD")

    def test_changes_include_cut_commit_later_status_and_deleted_designs(self):
        atomic.write(self.root / "docs/design/before.md", "# Only before\n")
        atomic.write(self.root / "docs/design/status.md", "# Status later\n")
        atomic.write(self.root / "docs/design/removed.md", "# Removed later\n")
        self.commit("Before cut")
        atomic.write(self.root / "docs/plan/demo/plan.toml", "part = []\n")
        atomic.write(self.root / "docs/design/cut.md", "# At cut\n")
        self.commit("Cut")
        atomic.write(self.root / "docs/design/after.md", "# After cut\n")
        atomic.write(self.root / "docs/design/status.status.md", "Status changed\n")
        (self.root / "docs/design/removed.md").unlink()
        for name in ("README.md", "README.status.md", "draft/input.md", "notes.txt"):
            atomic.write(self.root / "docs/design" / name, "Ignored\n")
        tip = self.commit("After cut")
        git(self.root, "update-ref", "refs/remotes/origin/main", tip)
        self.assertEqual(designer.changed_designs(self.root, "demo"), [
            "docs/design/after.md", "docs/design/cut.md", "docs/design/removed.md", "docs/design/status.md",
        ])

    def test_plan_deleted_and_readded_uses_first_cut(self):
        atomic.write(self.root / "docs/plan/demo/plan.toml", "part = []\n")
        self.commit("First cut")
        (self.root / "docs/plan/demo/plan.toml").unlink()
        atomic.write(self.root / DESIGN, "# Between cuts\n")
        self.commit("Delete plan")
        atomic.write(self.root / "docs/plan/demo/plan.toml", "part = []\n")
        self.commit("Second cut")
        self.assertEqual(designer.changed_designs(self.root, "demo", rev="HEAD"), [DESIGN])

    def test_root_commit_uses_tree_and_missing_plan_names_path(self):
        git(self.root, "checkout", "--orphan", "root-cut")
        git(self.root, "rm", "-qf", "README.md")
        atomic.write(self.root / "docs/plan/demo/plan.toml", "part = []\n")
        atomic.write(self.root / DESIGN, "# Root cut\n")
        atomic.write(self.root / "docs/design/status-only.status.md", "Status\n")
        self.commit("Root cut")
        self.assertEqual(designer.changed_designs(self.root, "demo", rev="HEAD"),
                         [DESIGN, "docs/design/status-only.md"])
        with self.assertRaisesRegex(ValueError, "docs/plan/absent/plan.toml"):
            designer.changed_designs(self.root, "absent", rev="HEAD")

    def test_history_commands_check_failures_and_parent_probe_does_not(self):
        fake = (FakeRunner().on(["git", "log"], Result(0, "new\nold\n"))
                .on(["git", "rev-parse"], Result(1))
                .on(["git", "ls-tree"], Result(0, DESIGN + "\n")))
        checked = Mock(wraps=fake)
        self.assertEqual(designer.changed_designs(self.root, "demo", sh=checked), [DESIGN])
        self.assertEqual(fake.argvs(), [
            ["git", "log", "--format=%H", "--diff-filter=A", "origin/main", "--", "docs/plan/demo/plan.toml"],
            ["git", "rev-parse", "--verify", "-q", "old^"],
            ["git", "ls-tree", "-r", "--name-only", "origin/main", "--", "docs/design/"],
        ])
        self.assertEqual([item.kwargs["check"] for item in checked.call_args_list], [True, False, True])


class RetireDueTest(unittest.TestCase):
    def setUp(self):
        parts = {name: Part(name, name, "feature", (), DESIGN, done=True) for name in ("a", "b")}
        self.plan = Plan("demo", "agents", (), 1, 2, parts, ())

    def test_all_parts_marked_done_and_retired_or_empty_plan(self):
        self.assertTrue(designer.retire_due(self.plan, {}, []))
        self.assertFalse(designer.retire_due(replace(self.plan, retired=True), {}, []))
        self.assertFalse(designer.retire_due(replace(self.plan, parts={}), {}, []))

    def test_one_incomplete_and_every_task_must_land(self):
        self.plan.parts["b"] = replace(self.plan.parts["b"], done=False)
        tasks = {f"demo/{name}": Task(f"demo/{name}", "b", "feature", "agents", (), (), "high", 25, "", "")
                 for name in ("one", "two")}
        self.assertFalse(designer.retire_due(self.plan, {}, []))
        events = [{"ev": "branch.landed", "task": key, "tip": "tip", "main": "main"} for key in tasks]
        self.assertFalse(designer.retire_due(self.plan, tasks, events[:1]))
        self.assertTrue(designer.retire_due(self.plan, tasks, events))

    def test_matching_successful_retire_suppresses_another_call(self):
        start = dict(ev="call.started", call="retire-1", role="retire", subject="demo/retire")
        for outcome, expected in (("done", False), ("failed", True), ("question", True), ("infra", True)):
            with self.subTest(outcome=outcome):
                events = [start, dict(ev="call.ended", call="retire-1", outcome=outcome)]
                self.assertEqual(designer.retire_due(self.plan, {}, events), expected)
        self.assertTrue(designer.retire_due(self.plan, {}, [start]))
        for changes in (dict(subject="other/retire"), dict(role="review"), dict(call="other")):
            events = [{**start, **changes}, dict(ev="call.ended", call="retire-1", outcome="done")]
            self.assertTrue(designer.retire_due(self.plan, {}, events))


class BriefTest(unittest.TestCase):
    def setUp(self):
        self.root = self.enterContext(tmp_home())
        self.plan, self.tasks = fixture(self.root)

    def sections(self, text, expected):
        self.assertEqual([line[2:] for line in text.splitlines() if line.startswith("# ") and
                          line[2:] in expected], expected)
        for fact in ("Call: call-1", "calls/call-1", "/reports/call-1.md"):
            self.assertIn(fact, text)

    def cut(self):
        return designer.cut_brief(designer.uncut("new", "agents", [SOURCE]), self.root, **FACTS)

    def decision(self):
        return designer.decision_brief(self.plan, "probe", self.tasks, {"demo/base": "landed"},
                                       self.root, "demo/probe-1", **FACTS)

    def retire(self, changed=(DESIGN,)):
        return designer.retire_brief(self.plan, self.tasks, {}, self.root, changed, **FACTS)

    def test_cut_sections_index_existing_plans_and_inventory(self):
        text = self.cut()
        self.sections(text, ["Role", "Call facts", "The draft", "The user's drafts", "Designs", "Plans", "Inventory"])
        for fragment in (calls.ROLES["cut"].read_text(), "- Draft: new", "- Repository: agents",
                         "- Plan: write `docs/plan/new/plan.toml`", f"- Sources: `{SOURCE}`",
                         "The user's draft, whole.", f"- `{DESIGN}` — Core design (4 lines;",
                         "- `docs/plan/demo/plan.toml`", "Existing primitive."):
            self.assertIn(fragment, text)
        self.assertNotIn("Keep this contract.", text)

    def test_empty_cut_sections_and_sources_in_order(self):
        empty = self.root / "empty"
        text = designer.cut_brief(designer.uncut("new", "agents", ["a.md", "b.md"]), empty, **FACTS)
        for section in ("Designs", "Plans", "Inventory"):
            self.assertIn(f"# {section}\n\n(none)", text)
        self.assertIn("- Sources: `a.md`, `b.md`", text)

    def test_decision_sections_report_readers_and_cited_design(self):
        text = self.decision()
        self.sections(text, ["Role", "Call facts", "Plan parts and slices", "The probe", "The probe's report",
                             "Its readers", "The user's drafts", "Cited design"])
        for fragment in (calls.ROLES["decision"].read_text(), "Plan: `docs/plan/demo/plan.toml`",
                         "- Part: probe", "- Title: Measure it", f"- Design: {DESIGN}, 2",
                         "- Run: demo/probe-1", f"- Report: `{log.home()}/runs/demo/probe-1/report.md`",
                         "Done: measured 42\nAll measurements.",
                         f"- reader — Use the measurement (design: {DESIGN}, 3; not designed)",
                         "| base | Shared base | feature | - | done |", "Keep this contract."):
            self.assertIn(fragment, text)
        alone = replace(self.plan, parts={"probe": self.plan.parts["probe"]})
        text = designer.decision_brief(alone, "probe", {}, {}, self.root, "demo/probe-1", **FACTS)
        self.assertIn("# Its readers\n\n(none)", text)

    def test_decision_refuses_unknown_or_non_probe_and_unreadable_report(self):
        for part, reason in (("missing", "unknown part"), ("base", "not a probe")):
            with self.subTest(part=part), self.assertRaisesRegex(ValueError, reason):
                designer.decision_brief(self.plan, part, {}, {}, self.root, "demo/probe-1", **FACTS)
        path = log.home() / "runs/demo/probe-1/report.md"
        path.unlink()
        with self.assertRaisesRegex(ValueError, str(path)):
            self.decision()
        atomic.write(path, "bad encoding")
        sibling = path.with_suffix(".bytes")
        sibling.write_bytes(b"\xff")
        sibling.replace(path)
        with self.assertRaisesRegex(ValueError, str(path)):
            self.decision()

    def test_retire_sections_full_design_status_removed_and_missing(self):
        text = self.retire((DESIGN, "docs/design/removed.md"))
        self.sections(text, ["Role", "Call facts", "Plan parts and slices", "The user's drafts",
                             "Designs changed since the plan started", "Inventory"])
        self.assertIn(calls.ROLES["retire"].read_text(), text)
        self.assertIn(f"## {DESIGN}\n\n" + (self.root / DESIGN).read_text(), text)
        self.assertIn("## docs/design/core.status.md\n\nCore is designed.", text)
        self.assertIn("## docs/design/removed.md\n\n(removed)", text)
        self.assertIn("## docs/design/removed.status.md\n\n(no status file)", text)
        self.assertLess(text.index(f"## {DESIGN}"), text.index("## docs/design/core.status.md"))
        self.assertIn("Existing primitive.", text)
        self.assertIn("# Designs changed since the plan started\n\n(none)", self.retire(()))

    def test_each_brief_refuses_past_limit(self):
        for compile in (self.cut, self.decision, self.retire):
            with self.subTest(compile=compile.__name__), patch.object(calls, "BRIEF_LIMIT", 10):
                with self.assertRaisesRegex(ValueError, "BRIEF_LIMIT.*largest section"):
                    compile()


class MainTest(unittest.TestCase):
    def setUp(self):
        self.root = self.enterContext(tmp_home())
        fixture(self.root)
        self.directory = self.root / "docs/plan/demo"
        self.fake = runner(self.root)

    def invoke(self, role, *args, brief_only=True, directory=None):
        output, errors = io.StringIO(), io.StringIO()
        argv = ["call", role, *args, "--plan", str(directory or self.directory)]
        if brief_only:
            argv.append("--brief-only")
        with patch.object(designer, "run", self.fake), redirect_stdout(output), redirect_stderr(errors):
            result = cli.main(argv)
        return result, output.getvalue(), errors.getvalue()

    def test_brief_only_for_each_role_through_cli(self):
        for role, args, directory in (("cut", ("--source", SOURCE), self.root / "docs/plan/new"),
                                      ("contract", ("base",), self.directory),
                                      ("decision", ("probe", "--run", "demo/probe-1"), self.directory),
                                      ("retire", (), self.directory)):
            with self.subTest(role=role), patch.object(calls, "start") as start:
                result, text, errors = self.invoke(role, *args, directory=directory)
                self.assertEqual((result, errors), (0, ""))
                self.assertIn(calls.ROLES[role].read_text(), text)
                self.assertIn("# Call facts", text)
                start.assert_not_called()
                self.assertFalse((log.home() / "plans").exists())

    def test_cut_refuses_existing_plan_elsewhere_and_missing_source(self):
        cases = ((self.directory, SOURCE, "plan.toml already exists"),
                 (self.root / "elsewhere/new", SOURCE, "PLAN_DIR"),
                 (self.root / "docs/plan/new", "missing.md", "source"),
                 (self.root / "docs/plan/new", str(self.root / SOURCE), "source"),
                 (self.root / "docs/plan/new", "../outside.md", "source"))
        for directory, source, reason in cases:
            with self.subTest(directory=directory, source=source), patch.object(calls, "start") as start:
                result, _, error = self.invoke("cut", "--source", source, directory=directory, brief_only=False)
                self.assertEqual(result, 1)
                self.assertIn(reason, error)
                start.assert_not_called()
                self.assertFalse((log.home() / "plans").exists())

    def test_cut_refuses_symlink_source_outside_root(self):
        checkout = self.root / "checkout"
        checkout.mkdir()
        atomic.write(self.root / "outside.md", "outside")
        (checkout / "source.md").symlink_to(self.root / "outside.md")
        self.fake = runner(checkout)
        result, _, error = self.invoke("cut", "--source", "source.md", directory=checkout / "docs/plan/new")
        self.assertEqual(result, 1)
        self.assertIn("source", error)

    def test_cut_enlists_before_start_and_passes_subject_and_checkout(self):
        directory = self.root / "docs/plan/new"
        def start(role, subject, root, brief, **options):
            self.assertEqual((log.home() / "plans").read_text(), f"{directory}\n")
            self.assertEqual((role, subject, root), ("cut", "new/cut", self.root))
            self.assertIn("The user's draft, whole.", brief)
            self.assertEqual(options, dict(sh=self.fake))
            return dict(outcome="done", branch="calls/cut-id")
        with patch.object(calls, "start", side_effect=start) as launch:
            result, text, errors = self.invoke("cut", "--source", SOURCE, directory=directory, brief_only=False)
        self.assertEqual((result, text, errors), (0, "done calls/cut-id\n", ""))
        launch.assert_called_once()
        self.assertEqual(self.fake.calls[0].cwd, str(self.root / "docs/plan"))

    def test_roles_start_with_correct_subject_and_exit_status(self):
        for role, args, subject in (("contract", ("base",), "demo/base"),
                                    ("decision", ("probe", "--run", "demo/probe-1"), "demo/probe/decision"),
                                    ("retire", (), "demo/retire")):
            with self.subTest(role=role), patch.object(calls, "start", return_value={
                    "outcome": "failed", "branch": "calls/id"}) as start:
                result, text, errors = self.invoke(role, *args, brief_only=False)
                self.assertEqual((result, text, errors), (1, "failed calls/id\n", ""))
                self.assertEqual(start.call_args.args[:3], (role, subject, self.root))

    def test_contract_and_retire_preconditions(self):
        for part, reason in (("missing", "unknown part"), ("reader", "not a contract")):
            with self.subTest(part=part), patch.object(calls, "start") as start:
                result, _, errors = self.invoke("contract", part)
                self.assertEqual(result, 1)
                self.assertIn(reason, errors)
                start.assert_not_called()
        path = self.directory / "plan.toml"
        atomic.write(path, "retired = true\n" + path.read_text())
        with patch.object(calls, "start") as start:
            result, _, errors = self.invoke("retire")
        self.assertEqual(result, 1)
        self.assertIn("already retired", errors)
        start.assert_not_called()

    def test_git_failure_prints_error_and_starts_nothing(self):
        self.fake = FakeRunner().on(["git"], Result(1, err="git unavailable"))
        with patch.object(calls, "start") as start:
            result, _, errors = self.invoke("cut", "--source", SOURCE, directory=self.root / "docs/plan/new")
        self.assertEqual(result, 1)
        self.assertIn("fab call:", errors)
        start.assert_not_called()
