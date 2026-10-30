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
from fab.sh import Failed, Result
from fab.tests.support import FakeRunner, git, git_pair, tmp_home


HOST = Host("builder", "worker@builder.invalid", ("builder",))
TASK = Task("draft/task", "part", "feature", "agents", (), ("src/*.py", "tests/test_x.py"),
            "high", 25, "# Implement it\n\nAcceptance goes here.\n", "docs/plan/draft/tasks/task.md")
ROOT = Path("/home/worker/src/fabrig/fab")


def command(call):
    """Unwrap ssh's login shell without executing it."""
    return shlex.split(shlex.split(call.argv[-1])[2])


def starter():
    def answer(call):
        argv = command(call)
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


class RunStartTest(unittest.TestCase):
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
                self.assertEqual(commands[0], ["mkdir", "-p", str(repo.parent), str(worktree.parent),
                                               str(directory)])
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
                    self.assertEqual(commands[3], ["git", "-C", str(repo), "worktree", "add", "-b",
                                                   branch, str(worktree), "origin/main"])
                self.assertEqual(commands[-2], ["bash", "-c",
                    f"cat > {directory}/brief.md.tmp && mv -- {directory}/brief.md.tmp {directory}/brief.md"])
                expected = ["fab", "codex", "start", "--effort", "high", "--to", run.NOTIFY]
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

    def test_start_fabrig_medium_effort_and_explicit_log(self):
        with tmp_home() as home:
            fake = starter()
            path = home / "custom/events.jsonl"
            run.start(replace(TASK, repo="fabrig", effort="medium"), HOST, sh=fake, log_path=path)
            self.assertIn(run.REMOTES["fabrig"], command(fake.calls[1])[2])
            self.assertEqual(command(fake.calls[-1])[3:5], ["--effort", "medium"])
            self.assertEqual(len(log.read(path)), 1)
            self.assertEqual(log.read(), [])

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
                self.assertEqual(commands[3:7], [
                    ["fab", "slot", "list"],
                    ["fab", "slot", "claim", "2", run_id, TASK.id],
                    ["git", "-C", str(slot), "fetch", "origin"],
                    ["git", "-C", str(slot), "switch", "-C", branch, source]])
                expected = ["fab", "codex", "start", "--effort", task.effort, "--to", run.NOTIFY]
                if kind == "review":
                    expected.append("--read-only")
                self.assertEqual(commands[-1], [*expected, str(directory / "brief.md"), str(slot),
                                               str(directory / "report.md")])
                self.assertEqual(len(commands), 9)
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
                self.assertEqual(len(fake.calls), 4)
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
            self.assertEqual(command(fake.calls[-1])[:3], ["fab", "slot", "claim"])
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
                    expected = ["fab", "codex", "start", "--effort", "medium", "--to", run.NOTIFY]
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
            self.assertEqual(tokens[2], str(ROOT / "runs" / (task.id + "-1") / "brief.md.tmp"))
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
                         {"run": "draft/task-1", "ended": False, "outcome": None, "report": None})
        self.assertEqual(len(fake.calls), 1)
        script = command(fake.calls[0])[2]
        self.assertIn("test -f /state/codex-123/ended", script)
        self.assertIn("cat -- /remote/report.md", script)

    def test_status_after_ended_reads_report_in_the_same_ssh(self):
        report = "\nDone: complete\nDetails.\n"
        fake = FakeRunner().on(["ssh"], Result(0, "ended\n" + report))
        self.assertEqual(run.status(started(), HOST, sh=fake),
                         {"run": "draft/task-1", "ended": True, "outcome": "done", "report": report})
        self.assertEqual(len(fake.calls), 1)

    def test_status_missing_or_unknown_report_is_failed(self):
        for report in ("", "codex-run: reserved\n"):
            with self.subTest(report=report):
                fake = FakeRunner().on(["ssh"], Result(0, "ended\n" + report))
                self.assertEqual(run.status(started(), HOST, sh=fake)["outcome"], "failed")

    def test_status_quotes_remote_paths(self):
        record = started(state="/a b's/state", report="/a b's/report.md")
        fake = FakeRunner().on(["ssh"], Result(0, "running\n"))
        run.status(record, HOST, sh=fake)
        script = command(fake.calls[0])[2]
        self.assertIn(shlex.quote(record["state"] + "/ended"), script)
        self.assertIn("cat -- " + shlex.quote(record["report"]), script)

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
            fake = FakeRunner().on(["ssh"], Result(0, "ended\nDone: checked\nDetails.\n"))
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
            fake = FakeRunner().on(["ssh"], Result(0, "ended\nDone: checked\n"))
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
                    return Result(0, "ended\nDone: checked\n")

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
                            return Result(0, "ended\nQuestion: choose?\nDetails.\n")
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
            fake = FakeRunner().on(["ssh"], Result(0, "ended\n" + report))
            self.assertEqual(run.collect("draft/task-1", [started()], {HOST.name: HOST}, sh=fake),
                             "question")
            ended, question = log.read()
            self.assertEqual(ended["outcome"], "question")
            self.assertEqual({k: v for k, v in question.items() if k != "ts"},
                             {"ev": "question.asked", "run": "draft/task-1", "task": TASK.id,
                              "text": "\n".join(report.splitlines()[:15])})

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
            done = FakeRunner().on(["ssh"], Result(0, "ended\nDone: checked\n"))
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
    def test_repository_notes_follow_the_role(self):
        self.assertTrue(run.role_text("fabrig").startswith(run.ROLE.read_text()))
        self.assertIn("# Working in fabrig", run.role_text("fabrig"))
        self.assertEqual(run.role_text("agents"), run.ROLE.read_text())
