import io
import json
import shlex
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from fab import log, run
from fab.hosts import Host
from fab.plan import Task
from fab.sh import Failed, Result, ssh
from fab.tests.support import FakeRunner, git, git_pair, tmp_home


HOST = Host("builder", "worker@builder.invalid", ("builder",))
TASK = Task("draft/task", "part", "feature", "agents", (), ("src/*.py", "tests/test_x.py"),
            "high", 25, "# Implement it\n\nAcceptance goes here.\n", "docs/plan/draft/tasks/task.md")
ROOT = Path("/home/worker/src/fabrig/fab")


def command(call):
    """Unwrap ssh's login shell without executing it."""
    return shlex.split(shlex.split(call.argv[-1])[2])


def starter(pushed=False):
    """A builder whose slot 2 is idle; pushed says whether the task's branch is on origin."""
    def answer(call):
        argv = command(call)
        if argv[3:6] == ["rev-parse", "-q", "--verify"]:
            return Result(0 if pushed else 1)
        if argv[:2] == ["codex-run", "task"] or argv[:3] == ["fab", "codex", "start"]:
            return Result(0, "codex-123 /state/codex-123\n")
        if argv == ["fab", "slot", "list"]:
            return Result(0, json.dumps({"slot": 1, "claim": {"run": "busy"}, "idle": None})
                          + "\n" + json.dumps({"slot": 2, "claim": None, "idle": 0}) + "\n")
        return Result(0)
    return FakeRunner().on(["ssh"], answer)


def started(**fields):
    return {"ev": "run.started", "ts": "2026-10-30T12:00:00.000Z", "run": "draft/task-1",
            "task": TASK.id, "kind": "implement", "host": HOST.name,
            "dir": str(ROOT / "wt/draft/task-1"), "branch": TASK.id, "base": "origin/main",
            "codex": "codex-123", "state": "/state/codex-123", "report": "/remote/report.md",
            **fields}


class RunPureTest(unittest.TestCase):
    def test_remote_home_uses_the_ssh_user(self):
        self.assertEqual(run.remote_home(HOST), str(ROOT))
        self.assertEqual(run.remote_home(replace(HOST, ssh="other@192.0.2.1")),
                         "/home/other/src/fabrig/fab")
        for target in ("builder", "@builder", "user@", "../user@builder"):
            with self.subTest(target=target), self.assertRaises(ValueError):
                run.remote_home(replace(HOST, ssh=target))

    def test_next_run_counts_only_the_tasks_starts(self):
        self.assertEqual(run.next_run(TASK.id, []), "draft/task-1")
        events = [started(), started(run="draft/task-99"), started(task="other/task"),
                  {"ev": "run.ended", "task": TASK.id}]
        self.assertEqual(run.next_run(TASK.id, iter(events)), "draft/task-3")

    def test_branch_for_every_kind(self):
        for kind in run.KINDS:
            with self.subTest(kind=kind):
                expected = TASK.id + "-r1" if kind == "rebase" else TASK.id
                self.assertEqual(run.branch_for(TASK, kind, []), expected)
        events = [started(), started(kind="rebase", branch="draft/task-r1"),
                  started(task="other/task", kind="rebase", branch="unrelated"),
                  {"ev": "run.ended", "task": TASK.id, "kind": "rebase"}]
        self.assertEqual(run.branch_for(TASK, "repair", iter(events)), "draft/task-r1")
        self.assertEqual(run.branch_for(TASK, "rebase", iter(events)), "draft/task-r2")
        self.assertEqual(run.branch_for(TASK, "implement", events), TASK.id)
        self.assertEqual(run.branch_for(TASK, "review", events), TASK.id)
        with self.assertRaises(ValueError):
            run.branch_for(TASK, "unknown", [])

    def test_outcome_uses_the_first_nonblank_line(self):
        cases = [("Done: checked\n", "done"), ("Question: which?\n", "question"),
                 ("Infra: disk full\n", "infra"), ("Failed: no\n", "failed"),
                 ("\n \n  Done: checked\n", "done"), ("unknown\nDone: later", "failed"),
                 ("", "failed"), ("\n\t\n", "failed"), ("Done without colon", "failed")]
        for report, expected in cases:
            with self.subTest(report=report):
                self.assertEqual(run.outcome(report), expected)

    def test_brief_contains_role_run_facts_and_verbatim_body(self):
        text = run.brief(TASK, "# Role\nFollow the rules.\n", run_id="draft/task-3",
                         branch="draft/task-r1", base="origin/main", report="/remote/report.md")
        self.assertTrue(text.startswith("# Role\nFollow the rules.\n\n# Your task\n"))
        for fact in (TASK.id, TASK.path, TASK.repo, "draft/task-3", "draft/task-r1", "origin/main",
                     "/remote/report.md", *TASK.files, "25"):
            self.assertIn(fact, text)
        self.assertTrue(text.endswith(TASK.body))
        self.assertNotIn("## The landing refused this branch", text)

    def test_brief_adds_only_non_main_trunk_after_base(self):
        facts = dict(run_id="draft/task-1", branch=TASK.id, base="checked-tip", report="/report.md")
        plain = run.brief(TASK, "role", **facts)
        self.assertNotIn("- Trunk:", plain)
        self.assertEqual(run.brief(TASK, "role", **facts, trunk="main"), plain)
        self.assertEqual(run.brief(TASK, "role", **facts, trunk="component-kit/integration"),
                         plain.replace("- Base: `checked-tip`\n",
                                       "- Base: `checked-tip`\n"
                                       "- Trunk: `origin/component-kit/integration`\n"))

    def test_brief_quotes_section_verbatim_between_facts_and_refusal(self):
        rejection = {"step": "test", "log": "red", "text": "failure"}
        facts = dict(run_id="draft/task-2", branch=TASK.id, base="origin/main", report="/report.md")
        plain = run.brief(TASK, "# Role", **facts, rejection=rejection)
        for section in ("## Repair\n\n  Keep trailing spaces.  \n\nLast line.\n",
                        "## Rebase\n\nNo final newline."):
            with self.subTest(section=section):
                text = run.brief(TASK, "# Role", **facts, rejection={**rejection, "section": section})
                suffix = "\n" if section.endswith("\n") else "\n\n"
                heading = "## The landing refused this branch"
                self.assertEqual(text, plain.replace(heading, section + suffix + heading))
                self.assertLess(text.index("- Expected:"), text.index(section))
        self.assertEqual(run.brief(TASK, "# Role", **facts, rejection={**rejection, "section": ""}), plain)

    def refusal(self, text):
        return run.brief(TASK, "# Role", run_id="draft/task-2", branch=TASK.id,
                         base="origin/main", report="/report.md",
                         rejection={"step": "default", "log": "/queue/red.log", "text": text})

    def test_brief_refusal_starts_at_last_failed_step_and_ends_at_next_step(self):
        text = self.refusal("[default] old attempt (cwd /repo)\nstale failure\n"
                            "[build] cargo build (cwd /repo)\nunrelated output\n"
                            "[default] heavy check (cwd /repo)\n[ERROR] umask 022\nlast failure\n"
                            "[later] true (cwd /repo)\nlater output\n")
        self.assertIn("## The landing refused this branch", text)
        self.assertIn("The landing's checks failed; reproduce this first, in the lowest tier "
                      "that shows it. If it does not reproduce, say so in your report's first line.", text)
        self.assertIn("- Step: `default`", text)
        self.assertIn("- Queue log: `/queue/red.log`", text)
        self.assertIn("[default] heavy check (cwd /repo)\n[ERROR] umask 022\nlast failure", text)
        for absent in ("stale failure", "unrelated output", "later output", "[later]"):
            self.assertNotIn(absent, text)
        self.assertLess(text.index("implementer-minutes"), text.index("## The landing refused"))
        self.assertTrue(text.endswith(TASK.body))

    def test_brief_refusal_caps_log_at_120_lines_including_step_header(self):
        lines = ["[default] check (cwd /repo)", *(f"line {i}" for i in range(150))]
        text = self.refusal("earlier step\n" + "\n".join(lines))
        self.assertEqual(text.split("```text\n", 1)[1].split("\n```", 1)[0].splitlines(), lines[:120])

    def test_brief_refusal_keeps_path_when_log_unreadable_or_step_missing(self):
        for log_text, why in (("(log unreadable: permission denied)", "permission denied"),
                              ("", "step [default] not found"),
                              ("[build] true (cwd /repo)\nok", "step [default] not found")):
            with self.subTest(log_text=log_text):
                text = self.refusal(log_text)
                self.assertIn("## The landing refused this branch", text)
                self.assertIn("`/queue/red.log`", text)
                self.assertIn(f"(log unreadable: {why})", text)


class RejectionTextTest(unittest.TestCase):
    def test_log_is_read_on_gate_in_one_quoted_ssh(self):
        gate = Host("gate", "gate@invalid", ("gate",))
        record = {"step": "default", "log": "/queue/a b'$(touch NEVER).log"}
        output = "[build] true (cwd /repo)\n[default] false (cwd /repo)\nred\n"
        fake = FakeRunner().on(["ssh"], Result(0, output))
        self.assertEqual(run.rejection_text(record, gate, sh=fake), output)
        self.assertEqual(len(fake.calls), 1)
        self.assertEqual(fake.calls[0].argv[5], gate.ssh)
        self.assertEqual(command(fake.calls[0]), ["tail", "-n", "+1", "--", record["log"]])

    def test_missing_unreadable_and_unavailable_logs_give_diagnostic(self):
        gate = Host("gate", "gate@invalid", ("gate",))
        def unavailable(call):
            raise OSError("ssh unavailable")

        for answer, why in ((Result(1, err="permission denied"), "permission denied"),
                             (Result(255, err="offline"), "offline"), (unavailable, "ssh unavailable")):
            with self.subTest(why=why):
                fake = FakeRunner().on(["ssh"], answer)
                text = run.rejection_text({"log": "/queue/red.log"}, gate, sh=fake)
                self.assertTrue(text.startswith("(log unreadable: "))
                self.assertIn(why, text)
                self.assertEqual(len(fake.calls), 1)
        fake = FakeRunner()
        self.assertIn("no log path", run.rejection_text({}, gate, sh=fake))
        self.assertEqual(fake.calls, [])


class RunStartTest(unittest.TestCase):
    def test_start_passes_rejection_log_to_remote_and_local_brief_without_mutating_record(self):
        with tmp_home() as home:
            gate = Host("gate", "gate@invalid", ("gate",))
            record = {"step": "default", "log": "/queue/red.log", "tip": "same"}
            red = "[build] true (cwd /repo)\n[default] false (cwd /repo)\nred umask\n"
            fake = FakeRunner().on(ssh(gate.ssh, ["tail", "-n", "+1", "--", record["log"]]),
                                   Result(0, red))
            fake.rules.extend(starter().rules)
            with patch.object(run.hosts, "load", return_value={HOST.name: HOST, gate.name: gate}):
                run_id = run.start(TASK, HOST, kind="repair", sh=fake, rejection=record)
            text = (home / "fab/runs" / run_id / "brief.md").read_text()
            self.assertEqual(fake.calls[-2].input, text)
            self.assertEqual(command(fake.calls[0]),
                             ["tail", "-n", "+1", "--", record["log"]])
            self.assertEqual(fake.calls[0].argv[5], gate.ssh)
            self.assertIn("red umask", text)
            self.assertNotIn("[build]", text)
            self.assertEqual(record, {"step": "default", "log": "/queue/red.log", "tip": "same"})

    def test_start_uses_gate_findings_without_reading_a_gate(self):
        findings = "files: changed path outside task: fab/other.py\nshape: signature changed\n"
        for text in (findings, ""):
            with self.subTest(findings=text), tmp_home() as home:
                record = {"step": "gate:files", "log": "/digests/task.md", "findings": text}
                fake = starter()
                with patch.object(run.hosts, "load") as load:
                    run_id = run.start(TASK, HOST, kind="repair", sh=fake, rejection=record)
                load.assert_not_called()
                self.assertTrue(all(call.argv[5] == HOST.ssh for call in fake.calls))
                self.assertFalse(any(command(call)[0] == "tail" for call in fake.calls))
                brief = (home / "fab/runs" / run_id / "brief.md").read_text()
                self.assertEqual(fake.calls[-2].input, brief)
                refusal = brief.split("## The landing refused this branch\n", 1)[1]
                self.assertIn("- Step: `gate:files`", refusal)
                self.assertEqual(refusal.split("```text\n", 1)[1].split("\n```", 1)[0],
                                 text.rstrip("\n"))
                self.assertEqual(record, {"step": "gate:files", "log": "/digests/task.md",
                                          "findings": text})

    def test_start_still_launches_when_gate_log_cannot_be_read(self):
        with tmp_home() as home:
            gate = Host("gate", "gate@invalid", ("gate",))
            record = {"step": "default", "log": "/queue/missing.log"}
            fake = FakeRunner().on(ssh(gate.ssh, ["tail", "-n", "+1", "--", record["log"]]),
                                   Result(1, err="No such file or directory"))
            fake.rules.extend(starter().rules)
            with patch.object(run.hosts, "load", return_value={gate.name: gate}):
                run_id = run.start(TASK, HOST, kind="repair", sh=fake, rejection=record)
            text = (home / "fab/runs" / run_id / "brief.md").read_text()
            self.assertIn("## The landing refused this branch", text)
            self.assertIn("`/queue/missing.log`", text)
            self.assertIn("(log unreadable:", text)
            self.assertIn("No such file or directory", text)
            self.assertEqual(command(fake.calls[-1])[:3], ["fab", "codex", "start"])
            self.assertEqual(log.read()[-1]["ev"], "run.started")

    def test_start_still_launches_when_no_gate_is_configured(self):
        with tmp_home() as home, patch.object(run.hosts, "load", return_value={}):
            fake = starter()
            run_id = run.start(TASK, HOST, sh=fake, rejection={"log": "/red", "step": "default"})
            text = (home / "fab/runs" / run_id / "brief.md").read_text()
            self.assertIn("(log unreadable: no gate host configured)", text)
            self.assertEqual(command(fake.calls[-1])[:3], ["fab", "codex", "start"])

    def test_start_commands_and_event_for_every_kind(self):
        for kind in run.KINDS:
            with self.subTest(kind=kind), tmp_home() as home:
                fake = starter()
                events = [started(kind="rebase", branch="draft/task-r1")]
                run_id = run.start(TASK, HOST, kind=kind, events=iter(events), sh=fake)
                self.assertEqual(run_id, "draft/task-2")
                branch = {"repair": "draft/task-r1", "rebase": "draft/task-r2"}.get(kind, TASK.id)
                repo = ROOT / "repos/agents"
                worktree = ROOT / "wt" / run_id
                directory = ROOT / "runs" / run_id
                commands = [command(call) for call in fake.calls]
                self.assertEqual(len(commands), 7 if kind == "repair" else 6)
                self.assertTrue(all(call.argv[5] == HOST.ssh for call in fake.calls))
                self.assertEqual(commands[0], ["mkdir", "-p", str(repo.parent), str(ROOT / "wt"),
                                               str(ROOT / "runs")])
                self.assertEqual(commands[1][:2], ["bash", "-c"])
                self.assertIn(f"if ! test -d {repo}/.git; then ", commands[1][2])
                self.assertIn(shlex.join(["git", "clone", "--", run.REMOTES[TASK.repo], str(repo)]),
                              commands[1][2])
                self.assertEqual(commands[2], ["git", "-C", str(repo), "fetch", "origin"])
                if kind == "repair":
                    self.assertEqual(commands[3], ["git", "-C", str(repo), "worktree", "add", "--detach",
                                                   str(worktree), "origin/" + branch])
                    self.assertEqual(commands[4], ["git", "-C", str(worktree), "checkout",
                                                   "--ignore-other-worktrees", "-B", branch, "origin/" + branch])
                else:
                    self.assertEqual(commands[3], ["git", "-C", str(repo), "worktree", "add", "-B",
                                                   branch, str(worktree), "origin/main"])
                self.assertEqual(commands[-2], ["bash", "-c",
                    f"mkdir -p {directory} && cat > {directory}/brief.md.tmp && mv -- {directory}/brief.md.tmp {directory}/brief.md"])
                expected = ["fab", "codex", "start", "--effort", run.EFFORTS.get(kind, "high"), "--model", run.MODEL]
                if kind == "review":
                    expected.append("--read-only")
                self.assertEqual(commands[-1], [*expected, str(directory / "brief.md"), str(worktree),
                                               str(directory / "report.md")])
                text = (home / "fab/runs" / run_id / "brief.md").read_text()
                self.assertEqual(fake.calls[-2].input, text)
                self.assertTrue(text.startswith(run.ROLE.read_text().rstrip()))
                self.assertIn(branch, text)
                self.assertIn(str(directory / "report.md"), text)
                self.assertTrue(text.endswith(TASK.body))
                record, = log.read()
                self.assertEqual({key: value for key, value in record.items() if key != "ts"},
                                 {"ev": "run.started", "run": run_id, "task": TASK.id, "kind": kind,
                                  "host": HOST.name, "dir": str(worktree), "branch": branch,
                                  "base": "origin/main", "codex": "codex-123",
                                  "state": "/state/codex-123", "report": str(directory / "report.md")})

    def test_start_uses_trunk_in_worktrees_slots_briefs_and_events(self):
        for repo in ("agents", "fabrig"):
            for kind in run.KINDS:
                with self.subTest(repo=repo, kind=kind), tmp_home():
                    fake = starter()
                    task = replace(TASK, repo=repo)
                    run_id = run.start(task, HOST, kind=kind, events=[started()], sh=fake,
                                       trunk="component-kit/integration")
                    entry, = log.read()
                    branch = entry["branch"]
                    base = "origin/component-kit/integration"
                    self.assertEqual(entry["base"], base)
                    text = (log.home() / "runs" / run_id / "brief.md").read_text()
                    self.assertTrue(text.startswith(run.role_text(repo, "component-kit/integration")))
                    self.assertIn(f"- Base: `{base}`\n- Trunk: `{base}`\n", text)
                    self.assertEqual(fake.calls[-2].input, text)
                    commands = [command(call) for call in fake.calls]
                    source = f"origin/{branch}" if kind == "repair" else base
                    if repo == "fabrig":
                        self.assertIn(["git", "-C", str(ROOT.parent / "slots/2"), "switch", "--discard-changes",
                                       "-C", branch, source], commands)
                        self.assertIn(["git", "-C", str(ROOT.parent / "slots/2"), "clean", "-fdq"], commands)
                    elif kind == "repair":
                        self.assertIn(["git", "-C", str(ROOT / "repos/agents"), "worktree", "add",
                                       "--detach", str(ROOT / "wt" / run_id), source], commands)
                    else:
                        self.assertIn(["git", "-C", str(ROOT / "repos/agents"), "worktree", "add",
                                       "-B", branch, str(ROOT / "wt" / run_id), source], commands)

    def test_start_names_spec_relative_to_checkout_when_inside(self):
        for kind in ("implement", "rebase"):
            with self.subTest(kind=kind), tmp_home() as home:
                checkout = home / "checkout"
                inside = str(checkout / TASK.path)
                outside = str(home / "checkout-other" / TASK.path)
                for path, root, expected in ((inside, None, inside),
                                              (inside, checkout, TASK.path),
                                              (outside, checkout, outside),
                                              (TASK.path, checkout, TASK.path)):
                    with self.subTest(path=path, checkout=root):
                        task = replace(TASK, path=path)
                        fake = starter()
                        rejection = (dict(step="rebase", findings="amended", skeleton="root",
                                          old_tip="old-skeleton", tip="new-skeleton")
                                     if kind == "rebase" else None)
                        run_id = run.start(task, HOST, kind=kind, events=[started()], sh=fake,
                                           rejection=rejection, checkout=root)
                        text = (log.home() / "runs" / run_id / "brief.md").read_text()
                        self.assertIn(f"- Task: {TASK.id} (spec `{expected}`)\n", text)
                        self.assertEqual(fake.calls[-2].input, text)
                        self.assertEqual(task.path, path)

    def test_skeleton_rebase_instructions_and_base_use_trunk(self):
        for trunk in ("main", "component-kit/integration"):
            with self.subTest(trunk=trunk), tmp_home():
                fake = starter()
                rejection = dict(step="rebase", findings="amended", skeleton="root",
                                 old_tip="old-skeleton", tip="new-skeleton")
                run_id = run.start(TASK, HOST, kind="rebase", events=[started()], sh=fake,
                                   rejection=rejection, trunk=trunk)
                text = (log.home() / "runs" / run_id / "brief.md").read_text()
                base = f"origin/{trunk}"
                self.assertIn(f"git rebase --onto {base} old-skeleton", text)
                self.assertIn("git reset --hard origin/draft/task", text)
                self.assertIn(f"- Base: `{base}`", text)
                self.assertEqual(log.read()[0]["base"], base)
                self.assertIn(["git", "-C", str(ROOT / "repos/agents"), "diff",
                               "old-skeleton", "new-skeleton"], [command(call) for call in fake.calls])

    def test_skeleton_rebase_uses_integration_role(self):
        with tmp_home():
            fake = starter()
            task = replace(TASK, repo="fabrig")
            rejection = dict(step="rebase", findings="amended", skeleton="root",
                             old_tip="old-skeleton", tip="new-skeleton")
            run_id = run.start(task, HOST, kind="rebase", events=[started()], sh=fake,
                               rejection=rejection, trunk="component-kit/integration")
            text = (log.home() / "runs" / run_id / "brief.md").read_text()
            self.assertTrue(text.startswith(run.role_text("fabrig", "component-kit/integration")))
            self.assertEqual(fake.calls[-2].input, text)

    def test_start_fabrig_medium_effort_and_explicit_log(self):
        with tmp_home() as home:
            fake = starter()
            path = home / "custom/events.jsonl"
            run.start(replace(TASK, repo="fabrig", effort="medium"), HOST, sh=fake, log_path=path)
            self.assertIn(run.REMOTES["fabrig"], command(fake.calls[1])[2])
            # An implement run is high whatever the spec says: the model's implementer.
            self.assertEqual(command(fake.calls[-1])[3:5], ["--effort", "high"])
            self.assertEqual(len(log.read(path)), 1)
            self.assertEqual(log.read(), [])

    def test_an_early_start_merges_its_needs_pushed_work_and_says_so(self):
        with tmp_home():
            fake = starter()
            run_id = run.start(replace(TASK, repo="fabrig"), HOST, kind="implement", sh=fake,
                               early=(("draft/need", "draft/need"),))
            commands = [command(call) for call in fake.calls]
            self.assertIn(["git", "-C", str(ROOT.parent / "slots/2"), "-c", "user.name=fab", "-c",
                           "user.email=fab@localhost", "merge", "--no-edit", "origin/draft/need"], commands)
            self.assertIn("# Started early", (log.home() / "runs" / run_id / "brief.md").read_text())
            self.assertEqual(log.read()[-1]["early"], ["draft/need"])

    def test_an_early_start_whose_need_conflicts_is_refused(self):
        def answer(call):
            argv = command(call)
            if "merge" in argv and "--no-edit" in argv:
                return Result(1, err="conflict")
            return base(call)
        base = starter().rules[0][1]
        fake = FakeRunner().on(["ssh"], answer)
        with tmp_home():
            with self.assertRaisesRegex(ValueError, "^early: draft/need"):
                run.start(replace(TASK, repo="fabrig"), HOST, kind="implement", sh=fake,
                          early=(("draft/need", "draft/need"),))
            self.assertIn(["git", "-C", str(ROOT.parent / "slots/2"), "merge", "--abort"],
                          [command(call) for call in fake.calls])

    def test_an_implement_rerun_continues_from_its_pushed_branch(self):
        with tmp_home():
            fake = starter(pushed=True)
            run.start(replace(TASK, repo="fabrig"), HOST, kind="implement",
                      events=[started(kind="implement")], sh=fake)
            commands = [command(call) for call in fake.calls]
            self.assertIn(["git", "-C", str(ROOT.parent / "slots/2"), "switch", "--discard-changes",
                           "-C", TASK.id, f"origin/{TASK.id}"], commands)
            self.assertIn(["git", "-C", str(ROOT.parent / "slots/2"), "-c", "user.name=fab", "-c",
                           "user.email=fab@localhost", "merge", "--no-edit", "origin/main"], commands)

    def test_start_fabrig_claims_slot_and_switches_for_every_kind(self):
        for kind in run.KINDS:
            with self.subTest(kind=kind), tmp_home() as home:
                fake = starter()
                task = replace(TASK, repo="fabrig")
                events = [started(kind="rebase", branch="draft/task-r1")]
                run_id = run.start(task, HOST, kind=kind, events=events, sh=fake)
                branch = {"repair": "draft/task-r1", "rebase": "draft/task-r2"}.get(kind, TASK.id)
                source = "origin/" + branch if kind == "repair" else "origin/main"
                slot = ROOT.parent / "slots/2"
                directory = ROOT / "runs" / run_id
                commands = [command(call) for call in fake.calls]
                probe = ([["git", "-C", str(slot), "rev-parse", "-q", "--verify", f"refs/remotes/origin/{branch}"]]
                         if kind == "implement" else [])
                self.assertEqual(commands[3:8 + len(probe)], [
                    ["fab", "slot", "list"],
                    ["fab", "slot", "claim", "2", run_id, TASK.id],
                    ["git", "-C", str(slot), "fetch", "origin"], *probe,
                    ["git", "-C", str(slot), "clean", "-fdq"],
                    ["git", "-C", str(slot), "switch", "--discard-changes", "-C", branch, source]])
                expected = ["fab", "codex", "start", "--effort", run.EFFORTS.get(kind, task.effort), "--model", run.MODEL]
                if kind == "review":
                    expected.append("--read-only")
                self.assertEqual(commands[-1], [*expected, str(directory / "brief.md"), str(slot),
                                               str(directory / "report.md")])
                self.assertEqual(len(commands), 10 + len(probe))
                record, = log.read()
                self.assertEqual({key: value for key, value in record.items() if key != "ts"},
                                 {"ev": "run.started", "run": run_id, "task": TASK.id, "kind": kind,
                                  "host": HOST.name, "dir": str(slot), "branch": branch,
                                  "base": "origin/main", "codex": "codex-123", "slot": 2,
                                  "state": "/state/codex-123", "report": str(directory / "report.md")})
                self.assertEqual((home / "fab/runs" / run_id / "brief.md").read_text(),
                                 fake.calls[-2].input)

    def test_start_fabrig_selects_the_oldest_idle_rank(self):
        fallback = starter()
        def answer(call):
            if command(call) == ["fab", "slot", "list"]:
                return Result(0, '\n'.join(json.dumps(entry) for entry in [
                    {"slot": 1, "claim": None, "idle": 1},
                    {"slot": 2, "claim": None, "idle": 0},
                    {"slot": 3, "claim": None, "idle": 2}]) + "\n")
            return fallback(call.argv, input=call.input)

        with tmp_home():
            fake = FakeRunner().on(["ssh"], answer)
            run.start(replace(TASK, repo="fabrig"), HOST, sh=fake)
            self.assertEqual(command(fake.calls[4]),
                             ["fab", "slot", "claim", "2", "draft/task-1", TASK.id])
            self.assertEqual(log.read()[0]["slot"], 2)

    def test_start_fabrig_refuses_when_no_slot_is_idle(self):
        for listing in ("", json.dumps({"slot": 1, "claim": {"run": "busy"}, "idle": None}) + "\n"):
            with self.subTest(listing=listing), tmp_home() as home:
                def answer(call):
                    return Result(0, listing) if command(call) == ["fab", "slot", "list"] else Result(0)

                fake = FakeRunner().on(["ssh"], answer)
                with self.assertRaisesRegex(ValueError, HOST.name + ": no idle slot"):
                    run.start(replace(TASK, repo="fabrig"), HOST, sh=fake)
                self.assertEqual(command(fake.calls[-1]), ["fab", "slot", "list"])
                # The fifth call is the failed start's undo, looking for its own claim.
                self.assertEqual(len(fake.calls), 5)
                self.assertEqual(log.read(), [])
                self.assertFalse((home / "fab/runs").exists())

    def test_start_fabrig_does_not_launch_if_the_claim_fails(self):
        fallback = starter()
        def answer(call):
            if command(call)[:3] == ["fab", "slot", "claim"]:
                return Result(1, err="already claimed")
            return fallback(call.argv, input=call.input)

        with tmp_home():
            fake = FakeRunner().on(["ssh"], answer)
            with self.assertRaises(Failed):
                run.start(replace(TASK, repo="fabrig"), HOST, sh=fake)
            commands = [command(call)[:3] for call in fake.calls]
            self.assertIn(["fab", "slot", "claim"], commands)
            self.assertNotIn(["fab", "codex", "start"], commands)
            self.assertEqual(log.read(), [])

    def test_start_with_fab_launcher_preserves_arguments_and_events(self):
        for repo in ("agents", "fabrig"):
            for kind in run.KINDS:
                with self.subTest(repo=repo, kind=kind), tmp_home(), patch.object(run, "LAUNCHER", "fab"):
                    fake = starter()
                    task = replace(TASK, repo=repo, effort="medium")
                    run_id = run.start(task, HOST, kind=kind, sh=fake)
                    worktree = ROOT.parent / "slots/2" if repo == "fabrig" else ROOT / "wt" / run_id
                    directory = ROOT / "runs" / run_id
                    expected = ["fab", "codex", "start", "--effort", run.EFFORTS.get(kind, "medium"), "--model", run.MODEL]
                    if kind == "review":
                        expected.append("--read-only")
                    self.assertEqual(command(fake.calls[-1]), [*expected, str(directory / "brief.md"),
                                                               str(worktree), str(directory / "report.md")])
                    record, = log.read()
                    self.assertEqual(record["codex"], "codex-123")
                    self.assertEqual(record["state"], "/state/codex-123")

    def test_start_quotes_shell_paths(self):
        with tmp_home():
            fake = starter()
            task = replace(TASK, id="draft/a b'$(touch NEVER)")
            run.start(task, HOST, sh=fake)
            commands = [command(call) for call in fake.calls]
            self.assertEqual(commands[3][-3], task.id)
            tokens = shlex.split(commands[4][2])
            self.assertEqual(tokens[6], str(ROOT / "runs" / (task.id + "-1") / "brief.md.tmp"))
            self.assertEqual(commands[-1][-2], str(ROOT / "wt" / (task.id + "-1")))

    def test_start_refuses_bad_kind_or_repo_before_ssh(self):
        with tmp_home():
            fake = starter()
            with self.assertRaises(ValueError):
                run.start(TASK, HOST, kind="bad", sh=fake)
            with self.assertRaises(ValueError):
                run.start(replace(TASK, repo="bad"), HOST, sh=fake)
            self.assertEqual(fake.calls, [])
            self.assertEqual(log.read(), [])

    def test_start_command_failure_does_not_log_a_start(self):
        with tmp_home():
            fake = FakeRunner().on(["ssh"], Result(1, err="unavailable"))
            with self.assertRaises(Failed):
                run.start(TASK, HOST, sh=fake)
            self.assertEqual(len(fake.calls), 1)
            self.assertEqual(log.read(), [])

    def test_start_rejects_malformed_codex_response(self):
        for output in ("", "id", "id relative/state", "id /state\nextra /state"):
            with self.subTest(output=output), tmp_home():
                fake = FakeRunner().on(["ssh"], Result(0, output))
                with self.assertRaises(ValueError):
                    run.start(TASK, HOST, sh=fake)
                self.assertEqual(log.read(), [])

    def test_repair_can_reuse_a_branch_in_an_older_worktree(self):
        # Real git checks that repair can reset a branch still checked out by the previous run.
        with tmp_home() as home:
            _, clone = git_pair(home)
            git(clone, "switch", "-c", TASK.id)
            git(clone, "push", "origin", TASK.id)
            git(clone, "commit", "--allow-empty", "-m", "Local branch differs from origin")
            self.assertNotEqual(git(clone, "rev-parse", "HEAD"),
                                git(clone, "rev-parse", f"origin/{TASK.id}"))
            fake = starter()
            run.start(TASK, HOST, kind="repair", events=[started()], sh=fake)
            argv = command(fake.calls[3])
            argv[2] = str(clone)
            argv[-2] = str(home / "repair")
            git(home, *argv[1:])
            argv = command(fake.calls[4])
            argv[2] = str(home / "repair")
            git(home, *argv[1:])
            self.assertEqual(git(home / "repair", "branch", "--show-current"), TASK.id)
            self.assertEqual(git(home / "repair", "rev-parse", "HEAD"),
                             git(clone, "rev-parse", f"origin/{TASK.id}"))


class RunStatusTest(unittest.TestCase):
    def test_status_while_running(self):
        fake = FakeRunner().on(["ssh"], Result(0, "running\n"))
        self.assertEqual(run.status(started(), HOST, sh=fake),
                         {"run": "draft/task-1", "ended": False, "outcome": None, "report": None, "tokens": None})
        self.assertEqual(len(fake.calls), 1)
        script = command(fake.calls[0])[2]
        self.assertIn("test -f /state/codex-123/ended", script)
        self.assertIn("cat -- /remote/report.md", script)
        self.assertIn("IFS= read -r line < /state/codex-123/result.json", script)
        self.assertIn("printf '%s\\n' \"$line\"", script)

    def test_status_after_ended_reads_report_in_the_same_ssh(self):
        report = "\nDone: complete\nDetails.\n"
        fake = FakeRunner().on(["ssh"], Result(0, "ended\n\n" + report))
        self.assertEqual(run.status(started(), HOST, sh=fake),
                         {"run": "draft/task-1", "ended": True, "outcome": "done", "report": report, "tokens": None})
        self.assertEqual(len(fake.calls), 1)

    def test_status_reads_tokens_and_report_in_one_ssh(self):
        with tmp_home():
            result = json.dumps({"tokens": {"input_tokens": 10, "cached_input_tokens": 3, "output_tokens": 4}})
            fake = FakeRunner().on(["ssh"], Result(0, "ended\n" + result + "\nDone: complete\n"))
            self.assertEqual(run.status(started(), HOST, sh=fake),
                             {"run": "draft/task-1", "ended": True, "outcome": "done",
                              "report": "Done: complete\n", "tokens": "10/3/4"})
            self.assertEqual(len(fake.calls), 1)

    def test_status_missing_or_unknown_report_is_failed(self):
        for report in ("", "codex-run: reserved\n"):
            with self.subTest(report=report):
                fake = FakeRunner().on(["ssh"], Result(0, "ended\n\n" + report))
                self.assertEqual(run.status(started(), HOST, sh=fake)["outcome"], "failed")

    def test_status_quotes_remote_paths(self):
        record = started(state="/a b's/state", report="/a b's/report.md")
        fake = FakeRunner().on(["ssh"], Result(0, "running\n"))
        run.status(record, HOST, sh=fake)
        script = command(fake.calls[0])[2]
        self.assertIn(shlex.quote(record["state"] + "/ended"), script)
        self.assertIn("cat -- " + shlex.quote(record["report"]), script)
        self.assertIn(shlex.quote(record["state"] + "/result.json"), script)

    def test_status_propagates_ssh_errors_and_refuses_invalid_response(self):
        fake = FakeRunner().on(["ssh"], Result(255, err="offline"))
        with self.assertRaises(Failed):
            run.status(started(), HOST, sh=fake)
        with self.assertRaises(ValueError):
            run.status(started(), HOST, sh=FakeRunner())


class RunCollectTest(unittest.TestCase):
    def test_collect_logs_and_copies_once_even_with_a_stale_event_snapshot(self):
        with tmp_home() as home:
            record = started()
            fake = FakeRunner().on(["ssh"], Result(0, "ended\n\nDone: checked\nDetails.\n"))
            path = home / "events.jsonl"
            with patch.object(log, "now", return_value="2026-10-30T12:12:30.000Z"):
                self.assertEqual(run.collect(record["run"], iter([record]), {HOST.name: HOST},
                                             sh=fake, log_path=path), "done")
            report_path = home / "fab/runs/draft/task-1/report.md"
            self.assertEqual(report_path.read_text(), "Done: checked\nDetails.\n")
            entry, = log.read(path)
            self.assertEqual(entry, {"ts": "2026-10-30T12:12:30.000Z", "ev": "run.ended",
                                    "run": record["run"], "task": TASK.id, "outcome": "done",
                                    "report": str(report_path), "minutes": 12.5})
            self.assertIsNone(run.collect(record["run"], [record], {HOST.name: HOST},
                                          sh=fake, log_path=path))
            self.assertEqual(len(fake.calls), 2)
            self.assertEqual(command(fake.calls[-1]),
                             ["git", "-C", record["dir"], "worktree", "remove", "--force", record["dir"]])
            self.assertEqual(log.read(path), [entry])
            self.assertEqual(log.read(), [])

    def test_collect_logs_tokens_only_when_result_provides_them(self):
        for result, tokens in (("", None), ('{"tokens":{"input_tokens":10}}', "10/0/0")):
            with self.subTest(result=result), tmp_home():
                record = started()
                fake = FakeRunner().on(["ssh"], Result(0, "ended\n" + result + "\nDone: checked\n"))
                self.assertEqual(run.collect(record["run"], [record], {HOST.name: HOST}, sh=fake), "done")
                entry, = log.read()
                if tokens is None:
                    self.assertNotIn("tokens", entry)
                else:
                    self.assertEqual(entry["tokens"], tokens)

    def test_collect_command_removes_a_dirty_linked_worktree_and_keeps_its_branch(self):
        # Real git checks removal from inside the linked worktree, including untracked files.
        with tmp_home() as home:
            _, clone = git_pair(home)
            worktree = home / "run checkout"
            git(clone, "worktree", "add", "-b", TASK.id, str(worktree), "origin/main")
            sibling = worktree / "untracked.tmp"
            sibling.write_text("left by the run\n")
            sibling.replace(worktree / "untracked")
            record = started(dir=str(worktree))
            fake = FakeRunner().on(["ssh"], Result(0, "ended\n\nDone: checked\n"))
            self.assertEqual(run.collect(record["run"], [record], {HOST.name: HOST}, sh=fake), "done")
            argv = command(fake.calls[-1])
            git(home, *argv[1:])
            self.assertFalse(worktree.exists())
            self.assertEqual(git(clone, "rev-parse", TASK.id), git(clone, "rev-parse", "origin/main"))

    def test_collect_slot_releases_and_logs_bytes_freed_once(self):
        for freed in (0, 123456789):
            with self.subTest(freed=freed), tmp_home():
                record = started(slot=2, dir=str(ROOT.parent / "slots/2"))
                def answer(call):
                    if command(call)[:3] == ["fab", "slot", "release"]:
                        return Result(0, f"{freed}\n")
                    return Result(0, "ended\n\nDone: checked\n")

                fake = FakeRunner().on(["ssh"], answer)
                self.assertEqual(run.collect(record["run"], [record], {HOST.name: HOST}, sh=fake), "done")
                self.assertEqual([command(call) for call in fake.calls][1:],
                                 [["fab", "slot", "release", "2", record["run"]]])
                entry, = log.read()
                self.assertEqual(entry["freed"], freed)
                self.assertNotIn("free_error", entry)
                self.assertEqual(Path(entry["report"]).read_text(), "Done: checked\n")
                self.assertIsNone(run.collect(record["run"], [record], {HOST.name: HOST}, sh=fake))
                self.assertEqual(len(fake.calls), 2)
                self.assertEqual(log.read(), [entry])

    def test_collect_cleanup_failure_still_collects_and_records_the_question(self):
        for slotted in (False, True):
            for failure in ("command", "os", "bad output"):
                if failure == "bad output" and not slotted:
                    continue
                with self.subTest(slotted=slotted, failure=failure), tmp_home():
                    record = started(**({"slot": 0, "dir": str(ROOT.parent / "slots/0")} if slotted else {}))
                    def answer(call):
                        if command(call)[0] == "bash":
                            return Result(0, "ended\n\nQuestion: choose?\nDetails.\n")
                        if failure == "os":
                            raise OSError("cannot execute ssh")
                        if failure == "bad output":
                            return Result(0, "invalid bytes\n")
                        return Result(1, err="cleanup unavailable")

                    fake = FakeRunner().on(["ssh"], answer)
                    self.assertEqual(run.collect(record["run"], [record], {HOST.name: HOST}, sh=fake),
                                     "question")
                    ended, question = log.read()
                    self.assertIn({"command": "cleanup unavailable", "os": "cannot execute ssh",
                                   "bad output": "invalid bytes"}[failure], ended["free_error"])
                    self.assertNotIn("freed", ended)
                    self.assertEqual(ended["outcome"], "question")
                    self.assertEqual(Path(ended["report"]).read_text(), "Question: choose?\nDetails.\n")
                    self.assertEqual(question["ev"], "question.asked")
                    self.assertIsNone(run.collect(record["run"], [record], {HOST.name: HOST}, sh=fake))
                    self.assertEqual(len(fake.calls), 2)

    def test_collect_question_logs_first_fifteen_lines(self):
        with tmp_home():
            report = "Question: which option?\n" + "\n".join(f"line {i}" for i in range(20)) + "\n"
            fake = FakeRunner().on(["ssh"], Result(0, "ended\n\n" + report))
            self.assertEqual(run.collect("draft/task-1", [started()], {HOST.name: HOST}, sh=fake),
                             "question")
            ended, question = log.read()
            self.assertEqual(ended["outcome"], "question")
            self.assertEqual({k: v for k, v in question.items() if k != "ts"},
                             {"ev": "question.asked", "run": "draft/task-1", "task": TASK.id,
                              "text": "\n".join(report.splitlines()[:15])})

    def test_collect_failed_task_run_parks_for_judgement(self):
        for kind, early, parks in (("implement", None, True), ("repair", None, True),
                                   ("implement", ["draft/need"], False), ("foreman", None, False),
                                   ("check", None, False)):
            with self.subTest(kind=kind, early=early), tmp_home():
                record = started(kind=kind, **({"early": early} if early else {}))
                fake = FakeRunner().on(["ssh"], Result(0, "ended\n\nFailed: no report\nwhy\n"))
                self.assertEqual(run.collect("draft/task-1", [record], {HOST.name: HOST}, sh=fake), "failed")
                questions = [event for event in log.read() if event["ev"] == "question.asked"]
                if parks:
                    self.assertEqual({k: v for k, v in questions[0].items() if k != "ts"},
                                     {"ev": "question.asked", "run": "draft/task-1", "task": TASK.id,
                                      "text": "Failed: no report\nwhy", "park": True})
                else:
                    self.assertEqual(questions, [])

    def test_collect_while_running_does_not_write(self):
        with tmp_home() as home:
            fake = FakeRunner().on(["ssh"], Result(0, "running\n"))
            self.assertIsNone(run.collect("draft/task-1", [started()], {HOST.name: HOST}, sh=fake))
            self.assertEqual(log.read(), [])
            self.assertFalse((home / "fab/runs").exists())

    def test_collect_already_ended_does_not_ssh(self):
        with tmp_home():
            fake = FakeRunner()
            events = [started(), {"ev": "run.ended", "run": "draft/task-1"}]
            self.assertIsNone(run.collect("draft/task-1", iter(events), {}, sh=fake))
            self.assertEqual(fake.calls, [])
            self.assertEqual(log.read(), [])

    def test_collect_unknown_run_refuses(self):
        with tmp_home(), self.assertRaisesRegex(ValueError, "unknown run"):
            run.collect("unknown", [], {}, sh=FakeRunner())


class RunMainTest(unittest.TestCase):
    def invoke(self, argv, fake):
        output = io.StringIO()
        with patch.object(run, "run", fake), patch.object(run.hosts, "load", return_value={HOST.name: HOST}), \
                redirect_stdout(output):
            code = run.main(argv)
        return code, output.getvalue()

    def test_main_start_then_status_then_collect(self):
        with tmp_home() as home:
            fake = starter()
            with patch.object(run, "_load_spec", return_value=TASK) as load:
                code, output = self.invoke(["start", TASK.path, "--host", HOST.name], fake)
            self.assertEqual((code, output), (0, "draft/task-1\n"))
            load.assert_called_once_with(Path(TASK.path))
            running = FakeRunner().on(["ssh"], Result(0, "running\n"))
            self.assertEqual(self.invoke(["status", "draft/task-1"], running),
                             (0, "draft/task-1 running\n"))
            done = FakeRunner().on(["ssh"], Result(0, "ended\n\nDone: checked\n"))
            self.assertEqual(self.invoke(["status", "draft/task-1"], done), (0, "draft/task-1 done\n"))
            self.assertEqual(self.invoke(["collect", "draft/task-1"], done), (0, "draft/task-1 done\n"))
            self.assertTrue((home / "fab/runs/draft/task-1/report.md").exists())
            self.assertEqual(self.invoke(["collect", "draft/task-1"], done),
                             (0, "draft/task-1 pending or already collected\n"))
            self.assertEqual([event["ev"] for event in log.read()], ["run.started", "run.ended"])

    def test_main_start_passes_kind_and_prior_events(self):
        with tmp_home():
            record = started()
            log.append("run.started", **{k: v for k, v in record.items() if k not in ("ev", "ts")})
            fake = starter()
            with patch.object(run, "_load_spec", return_value=TASK):
                self.assertEqual(self.invoke(["start", TASK.path, "--host", HOST.name,
                                              "--kind", "review"], fake), (0, "draft/task-2\n"))
            self.assertIn("--read-only", command(fake.calls[-1]))

    def test_main_refuses_unknown_host_or_run(self):
        with tmp_home():
            for argv, reason in [(["start", TASK.path, "--host", "unknown"], "unknown host"),
                                 (["status", "unknown"], "unknown run"),
                                 (["collect", "unknown"], "unknown run")]:
                with self.subTest(argv=argv):
                    fake = FakeRunner()
                    code, output = self.invoke(argv, fake)
                    self.assertEqual(code, 1)
                    self.assertIn(reason, output)
                    self.assertEqual(len(output.splitlines()), 1)
                    self.assertEqual(fake.calls, [])

    def test_main_invalid_arguments_are_one_line_refusals(self):
        with tmp_home():
            for argv in ([], ["unknown"], ["start", TASK.path],
                         ["start", TASK.path, "--host", HOST.name, "--kind", "bad"]):
                with self.subTest(argv=argv):
                    fake = FakeRunner()
                    code, output = self.invoke(argv, fake)
                    self.assertEqual(code, 1)
                    self.assertEqual(len(output.splitlines()), 1)
                    self.assertTrue(output.startswith("fab run: "))
                    self.assertEqual(fake.calls, [])

    def test_main_ssh_failure_is_a_one_line_refusal(self):
        with tmp_home():
            record = started()
            log.append("run.started", **{k: v for k, v in record.items() if k not in ("ev", "ts")})
            fake = FakeRunner().on(["ssh"], Result(255, err="offline\ntry again"))
            code, output = self.invoke(["status", record["run"]], fake)
            self.assertEqual(code, 1)
            self.assertEqual(len(output.splitlines()), 1)
            self.assertIn("try again", output)

    def test_load_spec_uses_the_plan_two_directories_up(self):
        with tmp_home() as home:
            path = home / "docs/plan/draft/tasks/task.md"
            path.parent.mkdir(parents=True)
            sibling = path.with_suffix(".tmp")
            sibling.write_text("spec text")
            sibling.replace(path)
            with patch.object(run.plan, "load_plan") as load, \
                    patch.object(run.plan, "parse_task", return_value=TASK) as parse:
                load.return_value.draft = "draft"
                load.return_value.repo = "agents"
                self.assertEqual(run._load_spec(path), TASK)
                load.assert_called_once_with(path.parent.parent / "plan.toml")
                parse.assert_called_once_with("spec text", str(path), "draft", "agents")


class RoleTextTest(unittest.TestCase):
    def test_repository_notes_follow_the_role_and_taste(self):
        role = run.ROLE.read_text().rstrip("\n")
        taste = run.TASTE.read_text().rstrip("\n")
        notes = run.ROLE.with_name("fabrig.md").read_text().rstrip("\n")
        self.assertEqual(run.role_text("agents"), role + "\n\n" + taste + "\n")
        self.assertEqual(run.role_text("fabrig"), role + "\n\n" + taste + "\n\n" + notes + "\n")

    def test_non_main_fabrig_trunk_uses_only_run_text(self):
        text = run.role_text("fabrig", "component-kit/integration")
        self.assertEqual(text, run.ROLE.with_name("fabrig-run.md").read_text())
        for path in (run.ROLE, run.TASTE, run.ROLE.with_name("fabrig.md"),
                     run.ROLE.with_name("fabrig-integration.md")):
            self.assertNotIn(path.read_text().rstrip("\n"), text)
        self.assertEqual(run.role_text("fabrig", "main"), run.role_text("fabrig"))

    def test_non_main_trunk_keeps_usual_role_without_integration_text(self):
        self.assertEqual(run.role_text("agents", "component-kit/integration"),
                         run.role_text("agents"))


class StartUndoTest(unittest.TestCase):
    def test_a_failed_launch_gives_back_its_worktree_and_branch(self):
        def answer(call):
            if command(call)[:3] == ["fab", "codex", "start"]:
                return Result(2, err="refused")
            return Result(0)

        with tmp_home():
            fake = FakeRunner().on(["ssh"], answer)
            with self.assertRaises(Failed):
                run.start(TASK, HOST, sh=fake)
            undo = command(fake.calls[-1])
            self.assertEqual(undo[:2], ["bash", "-c"])
            self.assertIn("worktree remove --force", undo[2])
            self.assertIn("branch -D", undo[2])
            self.assertEqual(log.read(), [])


class FetchCloneTest(unittest.TestCase):
    def test_clone_commands_and_returned_path(self):
        with tmp_home():
            fake = FakeRunner()
            clone = run.fetch_clone(HOST, "agents", sh=fake)
            self.assertEqual(clone, ROOT / "repos/agents")
            self.assertEqual([command(call) for call in fake.calls], [
                ["mkdir", "-p", str(ROOT / "repos"), str(ROOT / "wt"), str(ROOT / "runs")],
                ["bash", "-c", f"if ! test -d {clone}/.git; then "
                 + shlex.join(["git", "clone", "--", run.REMOTES["agents"], str(clone)]) + "; fi"],
                ["git", "-C", str(clone), "fetch", "origin"]])
            self.assertTrue(all(call.argv[5] == HOST.ssh for call in fake.calls))
            self.assertEqual(log.read(), [])

    def test_unknown_repository_is_refused_before_commands(self):
        with tmp_home():
            fake = FakeRunner()
            with self.assertRaisesRegex(ValueError, "unknown repository"):
                run.fetch_clone(HOST, "unknown", sh=fake)
            self.assertEqual(fake.calls, [])

    def test_command_failure_is_checked(self):
        for step in range(3):
            with self.subTest(step=step), tmp_home():
                fake = FakeRunner()
                def answer(call):
                    return Result(1 if len(fake.calls) == step + 1 else 0)
                fake.on(["ssh"], answer)
                with self.assertRaises(Failed):
                    run.fetch_clone(HOST, "agents", sh=fake)
                self.assertEqual(len(fake.calls), step + 1)


class LaunchTest(unittest.TestCase):
    def launch(self, fake, **fields):
        """Launch in a prepared directory with explicit review facts."""
        return run.launch(HOST, "call-2", task="call", kind="review", workdir="/checkout",
                          branch="calls/call", base="base-sha", brief="Review this.\n",
                          effort="medium", sh=fake, **fields)

    def test_launch_writes_atomically_and_carries_flat_event_fields(self):
        with tmp_home() as home:
            fake = starter()
            path = home / "custom/log.jsonl"
            run_id = self.launch(fake, read_only=True, log_path=path, call="amend-1", tip="tip-sha", slot=2)
            self.assertEqual(run_id, "call-2")
            directory = ROOT / "runs/call-2"
            self.assertEqual([command(call) for call in fake.calls], [
                ["bash", "-c", f"mkdir -p {directory} && cat > {directory}/brief.md.tmp "
                 f"&& mv -- {directory}/brief.md.tmp {directory}/brief.md"],
                ["fab", "codex", "start", "--effort", "medium", "--model", run.MODEL, "--read-only",
                 str(directory / "brief.md"), "/checkout", str(directory / "report.md")]])
            self.assertEqual(fake.calls[0].input, "Review this.\n")
            self.assertEqual((home / "fab/runs/call-2/brief.md").read_text(), "Review this.\n")
            record, = log.read(path)
            self.assertEqual({key: value for key, value in record.items() if key != "ts"},
                             {"ev": "run.started", "run": run_id, "task": "call", "kind": "review",
                              "host": HOST.name, "dir": "/checkout", "branch": "calls/call",
                              "base": "base-sha", "codex": "codex-123", "state": "/state/codex-123",
                              "report": str(directory / "report.md"), "call": "amend-1",
                              "tip": "tip-sha", "slot": 2})
            self.assertEqual(log.read(), [])

    def test_launch_custom_command_appends_paths_and_keeps_event_contract(self):
        with tmp_home() as home:
            fake = FakeRunner().on(["ssh"], Result(0, "check-1 /check/check-1\n"))
            command = ("fab", "check", "start", "--tip", "tip", "--onto", "origin/draft/integration")
            self.launch(fake, command=command, slot=2)
            argv = shlex.split(shlex.split(fake.calls[-1].argv[-1])[2])
            directory = ROOT / "runs/call-2"
            self.assertEqual(argv, [*command, str(directory / "brief.md"), "/checkout", str(directory / "report.md")])
            record, = log.read()
            self.assertEqual((record["codex"], record["state"], record["slot"]), ("check-1", "/check/check-1", 2))
            self.assertEqual((home / "fab/runs/call-2/brief.md").read_text(), "Review this.\n")

    def test_both_launchers_respect_read_only(self):
        for launcher in ("fab", "codex-run"):
            for read_only in (False, True):
                with self.subTest(launcher=launcher, read_only=read_only), tmp_home(), \
                        patch.object(run, "LAUNCHER", launcher):
                    fake = starter()
                    self.launch(fake, read_only=read_only)
                    argv = command(fake.calls[-1])
                    expected = (["fab", "codex", "start", "--effort", "medium", "--model", run.MODEL] if launcher == "fab"
                                else ["codex-run", "task", "--effort", "medium", "--model", run.MODEL, "--to", run.NOTIFY])
                    if read_only:
                        expected.append("--read-only")
                    self.assertEqual(argv[:-3], expected)

    def test_malformed_answer_is_refused_without_logging(self):
        for answer in ("", "id", "id relative", "id /state\nextra /state", "id /state\rwrong"):
            with self.subTest(answer=answer), tmp_home():
                fake = FakeRunner().on(["ssh"], Result(0, answer))
                with self.assertRaisesRegex(ValueError, "id and absolute state directory"):
                    self.launch(fake)
                self.assertEqual(log.read(), [])

    def test_failed_write_never_launches(self):
        with tmp_home() as home:
            fake = FakeRunner().on(["ssh"], Result(1, err="write failed"))
            with self.assertRaises(Failed):
                self.launch(fake)
            self.assertEqual(len(fake.calls), 1)
            self.assertFalse((home / "fab/runs/call-2/brief.md").exists())
            self.assertEqual(log.read(), [])


class LaunchDetachedTest(unittest.TestCase):
    def launch(self, fake):
        """Use the shared launch path with foreman-specific event fields."""
        return run.launch_detached(HOST, "draft/task/foreman-1", "agents", "origin/main",
                                   task="draft/task/foreman", kind="foreman", branch=TASK.id,
                                   base="origin/main", brief="Decide this.\n", effort="medium",
                                   asked="draft/task-1", sh=fake)

    def test_worktree_is_detached_after_fetch_and_launch_is_read_only(self):
        with tmp_home() as home:
            fake = starter()
            run_id = self.launch(fake)
            clone, worktree = str(ROOT / "repos/agents"), str(ROOT / "wt" / run_id)
            self.assertEqual(command(fake.calls[2]), ["git", "-C", clone, "fetch", "origin"])
            self.assertEqual(command(fake.calls[3]),
                             ["git", "-C", clone, "worktree", "add", "--detach", worktree, "origin/main"])
            self.assertEqual(command(fake.calls[-1]),
                             ["fab", "codex", "start", "--effort", "medium", "--model", run.MODEL,
                              "--read-only", str(ROOT / "runs" / run_id / "brief.md"), worktree,
                              str(ROOT / "runs" / run_id / "report.md")])
            self.assertEqual((home / "fab/runs" / run_id / "brief.md").read_text(), "Decide this.\n")
            record, = log.read()
            self.assertEqual(record["run"], run_id)
            self.assertEqual(record["kind"], "foreman")
            self.assertEqual(record["task"], "draft/task/foreman")
            self.assertEqual(record["asked"], "draft/task-1")
            self.assertEqual(record["dir"], worktree)

    def test_failed_launch_removes_added_worktree_and_reraises(self):
        with tmp_home():
            fake = FakeRunner()
            def answer(call):
                argv = command(call)
                if argv[:3] == ["fab", "codex", "start"]:
                    return Result(2, err="launch refused")
                if "remove" in argv:
                    return Result(1, err="cleanup refused")
                return Result(0)
            fake.on(["ssh"], answer)
            with self.assertRaisesRegex(Failed, "launch refused"):
                self.launch(fake)
            self.assertEqual(command(fake.calls[-1]),
                             ["git", "-C", str(ROOT / "repos/agents"), "worktree", "remove", "--force",
                              str(ROOT / "wt/draft/task/foreman-1")])
            self.assertEqual(log.read(), [])

    def test_cleanup_exception_does_not_mask_launch_error(self):
        with tmp_home():
            def answer(call):
                argv = command(call)
                if "remove" in argv:
                    raise OSError("cleanup unavailable")
                if argv[:3] == ["fab", "codex", "start"]:
                    return Result(2, err="launch refused")
                return Result(0)
            fake = FakeRunner().on(["ssh"], answer)
            with self.assertRaisesRegex(Failed, "launch refused"):
                self.launch(fake)
            self.assertEqual(log.read(), [])

    def test_failed_worktree_add_does_not_remove_or_launch(self):
        with tmp_home():
            add = ssh(HOST.ssh, ["git", "-C", str(ROOT / "repos/agents"), "worktree", "add",
                                "--detach", str(ROOT / "wt/draft/task/foreman-1"), "origin/main"])
            fake = FakeRunner().on(add, Result(1, err="add refused"))
            with self.assertRaisesRegex(Failed, "add refused"):
                self.launch(fake)
            self.assertEqual(fake.calls[-1].argv, add)
            self.assertEqual(len(fake.calls), 4)
            self.assertEqual(log.read(), [])

    def test_failed_brief_write_removes_added_worktree(self):
        with tmp_home():
            fake = FakeRunner()
            def answer(call):
                argv = command(call)
                if argv[:2] == ["bash", "-c"] and "cat >" in argv[2]:
                    return Result(1, err="write refused")
                return Result(0)
            fake.on(["ssh"], answer)
            with self.assertRaisesRegex(Failed, "write refused"):
                self.launch(fake)
            self.assertIn("remove", command(fake.calls[-1]))
            self.assertEqual(log.read(), [])

    def test_custom_log_path_is_forwarded(self):
        with tmp_home() as home:
            path = home / "custom/log.jsonl"
            run.launch_detached(HOST, "review-1", "agents", "tip-sha", task="call", kind="review",
                                branch="calls/call", base="base-sha", brief="Review.\n", effort="medium",
                                call="call", tip="tip-sha", sh=starter(), log_path=path)
            record, = log.read(path)
            self.assertEqual(record["call"], "call")
            self.assertEqual(record["tip"], "tip-sha")
            self.assertEqual(log.read(), [])


class ExcerptTest(unittest.TestCase):
    def test_last_matching_step_until_next_command(self):
        text = ("[test] old (cwd /repo)\nstale\n[build] build (cwd /repo)\n"
                "[test] new (cwd /repo)\n[ERROR] failure\nred\n[next] true (cwd /repo)\nignored\n")
        self.assertEqual(run.excerpt("test", text), "[test] new (cwd /repo)\n[ERROR] failure\nred")

    def test_cut_at_120_lines_including_header(self):
        lines = ["[test] check (cwd /repo)", *(f"line {i}" for i in range(150))]
        self.assertEqual(run.excerpt("test", "\n".join(lines)), "\n".join(lines[:120]))

    def test_missing_step_and_empty_log(self):
        for text in ("", "[build] compile (cwd /repo)\nok"):
            with self.subTest(text=text):
                self.assertEqual(run.excerpt("test", text), "(log unreadable: step [test] not found)")

    def test_unreadable_diagnostic_kept_and_cut(self):
        lines = ["(log unreadable: offline)", *(f"line {i}" for i in range(150))]
        self.assertEqual(run.excerpt("test", "\n".join(lines)), "\n".join(lines[:120]))

    def test_diagnostic_takes_precedence_over_step_headers(self):
        text = "(log unreadable: offline)\n[test] stray\n"
        self.assertEqual(run.excerpt("test", text), text.rstrip("\n"))


class RefusalTextTest(unittest.TestCase):
    def test_findings_without_loading_hosts_or_commands(self):
        with patch.object(run.hosts, "load") as load:
            for findings in ("shape: signature changed\nfiles: outside task", ""):
                with self.subTest(findings=findings):
                    fake = FakeRunner()
                    self.assertEqual(run.refusal_text({"findings": findings, "log": "ignored"},
                                                       "agents", sh=fake), findings)
                    self.assertEqual(fake.calls, [])
            load.assert_not_called()

    def test_findings_cut_at_120_lines(self):
        lines = [f"finding {i}" for i in range(150)]
        self.assertEqual(run.refusal_text({"findings": "\n".join(lines)}, "fabrig",
                                         sh=FakeRunner()), "\n".join(lines[:120]))

    def test_landed_repository_uses_log_verbatim(self):
        text = "rebase conflict in fab/x.py\n  preserve indentation"
        with patch.object(run.hosts, "load") as load:
            fake = FakeRunner()
            self.assertEqual(run.refusal_text({"step": "rebase", "log": text}, "agents", sh=fake), text)
            self.assertEqual(fake.calls, [])
            load.assert_not_called()

    def test_landed_repository_log_missing(self):
        for record in ({}, {"log": ""}):
            with self.subTest(record=record), patch.object(run.hosts, "load") as load:
                self.assertEqual(run.refusal_text(record, "agents", sh=FakeRunner()),
                                 "(log unreadable: rejection has no log)")
                load.assert_not_called()

    def test_landed_repository_log_cut_at_120_lines(self):
        lines = [f"detail {i}" for i in range(150)]
        self.assertEqual(run.refusal_text({"log": "\n".join(lines)}, "agents", sh=FakeRunner()),
                         "\n".join(lines[:120]))

    def test_queue_log_on_first_gate_by_name_then_excerpt(self):
        first = Host("a-gate", "a@invalid", ("gate",))
        last = Host("z-gate", "z@invalid", ("gate",))
        hosts = {last.name: last, HOST.name: HOST, first.name: first}
        record = {"step": "test", "log": "/queue/red.log"}
        lines = ["[test] check (cwd /repo)", *(f"line {i}" for i in range(150))]
        text = "[build] build (cwd /repo)\n" + "\n".join(lines) + "\n[next] true (cwd /repo)\n"
        with tmp_home(), patch.object(run.hosts, "load", return_value=hosts):
            fake = FakeRunner().on(["ssh"], Result(0, text))
            self.assertEqual(run.refusal_text(record, "fabrig", sh=fake), "\n".join(lines[:120]))
            self.assertEqual(len(fake.calls), 1)
            self.assertEqual(fake.calls[0].argv[5], first.ssh)
            self.assertEqual(command(fake.calls[0]), ["tail", "-n", "+1", "--", record["log"]])
            self.assertEqual(record, {"step": "test", "log": "/queue/red.log"})

    def test_no_gate_host(self):
        with tmp_home(), patch.object(run.hosts, "load", return_value={HOST.name: HOST}):
            fake = FakeRunner()
            self.assertEqual(run.refusal_text({"step": "test"}, "fabrig", sh=fake),
                             "(log unreadable: no gate host configured)")
            self.assertEqual(fake.calls, [])

    def test_hosts_cannot_load(self):
        for error in (OSError("hosts missing\ntry again"), ValueError("bad hosts")):
            with self.subTest(error=error), tmp_home(), patch.object(run.hosts, "load", side_effect=error):
                fake = FakeRunner()
                self.assertEqual(run.refusal_text({}, "fabrig", sh=fake),
                                 "(log unreadable: " + " ".join(str(error).splitlines()) + ")")
                self.assertEqual(fake.calls, [])

    def test_gate_log_read_failure_stays_a_diagnostic(self):
        gate = Host("gate", "gate@invalid", ("gate",))
        with tmp_home(), patch.object(run.hosts, "load", return_value={gate.name: gate}):
            fake = FakeRunner().on(["ssh"], Result(1, err="permission denied"))
            text = run.refusal_text({"step": "test", "log": "/red"}, "fabrig", sh=fake)
            self.assertTrue(text.startswith("(log unreadable: "))
            self.assertIn("permission denied", text)


class OptimisticRunTest(unittest.TestCase):
    def test_checked_tip_is_base_in_worktrees_slots_briefs_and_events(self):
        for trunk in ("main", "component-kit/integration"):
            for repo in ("agents", "fabrig"):
                with self.subTest(repo=repo, trunk=trunk), tmp_home():
                    task = replace(TASK, repo=repo)
                    events = [dict(ev="call.started", call="root", role="skeleton", subject="draft/part", branch="calls/root"),
                              dict(ev="call.ended", call="root", outcome="done"),
                              dict(ev="call.checked", call="root", root="root", subject="draft/part", outcome="green",
                                   tip="checked-tip", tasks=[task.id])]
                    fake = starter()
                    run_id = run.start(task, HOST, events=events, sh=fake, trunk=trunk)
                    entry = log.read()[-1]
                    self.assertEqual(entry["base"], "checked-tip")
                    self.assertIn("- Base: `checked-tip`", (log.home() / "runs" / run_id / "brief.md").read_text())
                    commands = [command(call) for call in fake.calls]
                    if repo == "fabrig":
                        self.assertIn(["git", "-C", str(ROOT.parent / "slots/2"), "switch", "--discard-changes", "-C", task.id, "checked-tip"], commands)
                    else:
                        self.assertIn(["git", "-C", str(ROOT / "repos/agents"), "worktree", "add", "-B", task.id,
                                       str(ROOT / "wt" / run_id), "checked-tip"], commands)
