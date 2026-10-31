import io
import json
import os
import sys
import textwrap
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from fab import codex
from fab.sh import Failed, Result
from fab.tests.support import FakeRunner, tmp_home


class CodexPureTest(unittest.TestCase):
    def test_new_id_uses_utc_seconds_and_four_random_hex_digits(self):
        with patch.object(codex.secrets, "token_hex", return_value="abcd") as random:
            self.assertEqual(codex.new_id(lambda: "2026-10-30T14:34:56.789+02:00"),
                             "20261030T123456Z-abcd")
            random.assert_called_once_with(2)
        before = datetime.now(timezone.utc)
        value = codex.new_id()
        after = datetime.now(timezone.utc)
        self.assertRegex(value, r"^\d{8}T\d{6}Z-[0-9a-f]{4}$")
        stamp = datetime.strptime(value[:16], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        self.assertLessEqual(before.replace(microsecond=0), stamp)
        self.assertLessEqual(stamp, after)

    def test_command_fresh_resume_read_only_and_model(self):
        for thread in (None, "thread-123"):
            for read_only in (False, True):
                for model in (None, "chosen-model"):
                    with self.subTest(thread=thread, read_only=read_only, model=model):
                        expected = ["codex", "exec"] + (["resume"] if thread else [])
                        if model:
                            expected += ["-m", model]
                        expected += ["-c", "model_reasoning_effort=xhigh"]
                        if not read_only:
                            expected += ["--dangerously-bypass-approvals-and-sandbox"]
                        elif not thread:
                            expected += ["--sandbox", "read-only"]
                        expected += ["--skip-git-repo-check", "--json", "-o", "/state/last.md"]
                        expected += ([thread] if thread else []) + ["-"]
                        self.assertEqual(codex.command(effort="xhigh", read_only=read_only,
                                                      model=model, last=Path("/state/last.md"),
                                                      thread=thread), expected)

    def test_tokens_field_missing_invalid_and_partial_result(self):
        for result in ("not JSON", "", "null", "[]", "42", "{}", '{"tokens": null}'):
            with self.subTest(result=result):
                self.assertIsNone(codex.tokens_field(result))
        self.assertEqual(codex.tokens_field('{"tokens":{"output_tokens":4}}'), "0/0/4")
        for value in (None, -1, True, "3", 1.5):
            with self.subTest(value=value):
                self.assertEqual(codex.tokens_field(json.dumps({"tokens": {
                    "input_tokens": value, "cached_input_tokens": value, "output_tokens": value}})), "0/0/0")

    def test_tokens_sum_completed_turns_and_default_missing_counts_to_zero(self):
        empty = {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0}
        self.assertEqual(codex.tokens([]), empty)
        events = [
            {"type": "turn.completed", "usage": {"input_tokens": 12, "cached_input_tokens": 4,
                                                "output_tokens": 3}},
            {"type": "turn.completed", "usage": {"input_tokens": 7, "output_tokens": 2}},
            {"type": "turn.failed", "usage": {"input_tokens": 999}},
            {"type": "turn.completed"}, {"type": "turn.completed", "usage": None},
            {"type": "turn.completed", "usage": {"input_tokens": None}},
        ]
        self.assertEqual(codex.tokens(events),
                         {"input_tokens": 19, "cached_input_tokens": 4, "output_tokens": 5})

    def test_capacity_requires_an_error_or_failed_turn_or_stderr(self):
        for event in ({"type": "error", "message": codex.CAPACITY},
                      {"type": "turn.failed", "error": {"message": codex.CAPACITY}}):
            with self.subTest(event=event):
                self.assertTrue(codex.at_capacity([event], ""))
        self.assertTrue(codex.at_capacity([], "prefix: " + codex.CAPACITY + "\n"))
        for event in ({"type": "error", "message": codex.CAPACITY + " extra"},
                      {"type": "turn.completed", "message": codex.CAPACITY},
                      {"type": "turn.failed", "error": None},
                      {"type": "error", "message": "another failure"}):
            with self.subTest(event=event):
                self.assertFalse(codex.at_capacity([event], "unrelated stderr"))
        self.assertFalse(codex.at_capacity([], ""))


class CodexFilesTest(unittest.TestCase):
    def setUp(self):
        self.home = self.enterContext(tmp_home())
        self.brief = self.home / "brief.md"
        self.workdir = self.home / "work tree"
        self.report = self.home / "reports/report.md"
        self.write(self.brief, "Do the task.\n")
        self.workdir.mkdir()
        self.fake = FakeRunner()

    @staticmethod
    def write(path, text):
        path.parent.mkdir(parents=True, exist_ok=True)
        sibling = path.with_name(path.name + ".tmp")
        sibling.write_text(text)
        sibling.replace(path)

    def launch(self, **kwargs):
        return codex.start(self.brief, self.workdir, self.report, sh=self.fake, **kwargs)

    def test_state_root_honors_fab_home_and_defaults_under_home(self):
        self.assertEqual(codex.state_root(), self.home / "fab/codex")
        with patch.dict(os.environ, {"FAB_HOME": ""}):
            self.assertEqual(codex.state_root(), self.home / "src/fabrig/fab/codex")

    def test_start_publishes_metadata_before_the_unit_and_uses_this_python(self):
        stamp = "2026-10-30T12:00:00.000Z"
        run_id = "20261030T120000Z-abcd"
        state = codex.state_root() / run_id
        expected = {"brief": str(self.brief), "dir": str(self.workdir), "report": str(self.report),
                    "effort": "medium", "read_only": True, "model": "chosen-model", "started": stamp}

        def launched(call):
            self.assertEqual(json.loads((state / "meta.json").read_text()), expected)
            self.assertFalse((state / "ended").exists())
            return Result(0)

        self.fake.on(["systemd-run"], launched)
        with patch.object(codex, "new_id", return_value=run_id), patch.object(codex.log, "now", return_value=stamp):
            self.assertEqual(self.launch(effort="medium", read_only=True, model="chosen-model"),
                             (run_id, state))
        launcher = Path(codex.__file__).resolve().parent.parent / "bin/fab"
        self.assertEqual(self.fake.argvs(), [["systemd-run", "--user", "--collect", "--quiet",
                          "--unit", "fab-codex-" + run_id, "--property=UMask=0077",
                          f"--property=ExecStopPost=-{sys.executable} -I -B {launcher} wake codex {run_id}", "--",
                          sys.executable, "-I", "-B", str(launcher), "codex", "_exec", run_id]])
        self.assertFalse(self.report.exists())

    def test_start_defaults_and_retries_an_id_collision(self):
        old = codex.state_root() / "collision"
        old.mkdir(parents=True)
        self.write(old / "meta.json", "existing")
        with patch.object(codex, "new_id", side_effect=["collision", "new"]):
            run_id, state = self.launch()
        self.assertEqual(run_id, "new")
        meta = json.loads((state / "meta.json").read_text())
        self.assertEqual((meta["effort"], meta["read_only"], meta["model"]), ("high", False, None))
        self.assertEqual((old / "meta.json").read_text(), "existing")

    def test_start_refuses_bad_paths_existing_reports_and_efforts_before_launch(self):
        for name in ("brief", "workdir", "report"):
            args = dict(brief=self.brief, workdir=self.workdir, report=self.report)
            args[name] = Path("relative")
            with self.subTest(relative=name), self.assertRaisesRegex(ValueError, "absolute"):
                codex.start(**args, sh=self.fake)
        for brief, directory in ((self.home / "missing", self.workdir),
                                  (self.workdir, self.workdir),
                                  (self.brief, self.home / "missing"), (self.brief, self.brief)):
            with self.subTest(brief=brief, directory=directory), self.assertRaises(ValueError):
                codex.start(brief, directory, self.report, sh=self.fake)
        with self.assertRaisesRegex(ValueError, "effort"):
            self.launch(effort="low")
        self.write(self.report, "Keep me.\n")
        with self.assertRaisesRegex(ValueError, "report already exists"):
            self.launch()
        self.report.unlink()
        self.report.symlink_to(self.home / "missing")
        with self.assertRaisesRegex(ValueError, "report already exists"):
            self.launch()
        self.assertEqual(self.fake.calls, [])
        self.assertFalse(codex.state_root().exists())

    def test_start_propagates_a_failed_unit_launch(self):
        self.fake.on(["systemd-run"], Result(1, err="service unavailable"))
        with self.assertRaises(Failed):
            self.launch()

    def fake_codex(self, attempts):
        executable = self.home / "bin/codex"
        self.write(executable, "#!" + sys.executable + " -B\n" + textwrap.dedent("""\
            import json
            import sys
            from pathlib import Path

            def write(path, text):
                path.parent.mkdir(parents=True, exist_ok=True)
                sibling = path.with_name(path.name + ".tmp")
                sibling.write_text(text)
                sibling.replace(path)

            calls_path = Path("calls.json")
            calls = json.loads(calls_path.read_text()) if calls_path.exists() else []
            attempts = ATTEMPTS
            step = attempts[min(len(calls), len(attempts) - 1)]
            calls.append({"argv": sys.argv[1:], "prompt": sys.stdin.read(), "cwd": str(Path.cwd())})
            write(calls_path, json.dumps(calls))
            last = Path(sys.argv[sys.argv.index("-o") + 1])
            assert not (last.parent / "ended").exists()
            assert not (last.parent / "result.json").exists()
            thread = step.get("thread", "thread-1")
            if thread:
                print(json.dumps({"type": "thread.started", "thread_id": thread}))
            print("not JSON")
            print("[]")
            code = step.get("code", 0)
            if code:
                message = CAPACITY if step.get("capacity") else "another failure"
                if step.get("stderr"):
                    print(message, file=sys.stderr)
                else:
                    print(json.dumps({"type": "turn.failed", "error": {"message": message}}))
            else:
                print(json.dumps({"type": "turn.completed", "usage": {
                    "input_tokens": 10, "cached_input_tokens": 4, "output_tokens": 2}}))
            if "last" in step:
                write(last, step["last"])
            if "report" in step:
                write(Path(REPORT), step["report"])
            sys.exit(code)
            """).replace("ATTEMPTS", repr(attempts)).replace("CAPACITY", repr(codex.CAPACITY))
                .replace("REPORT", repr(str(self.report))))
        executable.chmod(0o700)
        self.enterContext(patch.dict(os.environ, {"PATH": str(executable.parent) + os.pathsep + os.environ["PATH"]}))

    def calls(self):
        return json.loads((self.workdir / "calls.json").read_text())

    def test_execute_preserves_the_report_and_publishes_ended_last(self):
        self.fake_codex([{"report": "Done: completed.\n", "last": "Last words.\n"}])
        run_id, state = self.launch()
        published = []
        replace = Path.replace

        def observe(path, target):
            if Path(target) == state / "ended":
                self.assertEqual(self.report.read_text(), "Done: completed.\n")
                result = json.loads((state / "result.json").read_text())
                self.assertEqual(codex.tokens_field((state / "result.json").read_text()), "10/4/2")
                self.assertEqual(result["exit"], 0)
                self.assertEqual(result["tries"], 1)
                self.assertEqual(result["tokens"], {"input_tokens": 10, "cached_input_tokens": 4,
                                                    "output_tokens": 2})
                self.assertLessEqual(datetime.fromisoformat(result["ended"]), datetime.now(timezone.utc))
                self.assertFalse((state / "ended").exists())
                self.assertIn(state / "result.json", published)
            published.append(Path(target))
            return replace(path, target)

        with patch.object(Path, "replace", observe):
            self.assertEqual(codex.execute(run_id, sh=self.fake), 0)
        self.assertEqual(published[-1], state / "ended")
        self.assertEqual((state / "thread").read_text(), "thread-1\n")
        self.assertEqual((state / "ended").read_bytes(), b"")
        self.assertIn('"type": "turn.completed"', (state / "events.jsonl").read_text())
        self.assertEqual((state / "stderr.log").read_text(), "")
        self.assertEqual(self.calls()[0]["prompt"], self.brief.read_text())
        self.assertEqual(self.calls()[0]["cwd"], str(self.workdir))
        self.assertEqual(len(self.fake.calls), 1)

    def test_execute_missing_report_includes_last_message(self):
        self.fake_codex([{"last": "The last message.\n"}])
        run_id, state = self.launch()
        self.assertEqual(codex.execute(run_id), 0)
        self.assertEqual(self.report.read_text(),
                         "Failed: the run wrote no report.\nThe last message.\n")
        self.assertTrue((state / "ended").exists())

    def test_a_read_only_runs_report_is_its_last_message(self):
        self.fake_codex([{"last": "Done: approve\n"}])
        run_id, state = self.launch(read_only=True)
        self.assertEqual(codex.execute(run_id), 0)
        self.assertEqual(self.report.read_text(), "Done: approve\n")

    def test_execute_failure_without_report_or_last_message(self):
        self.fake_codex([{"code": 9}])
        run_id, state = self.launch()
        sleep = Mock()
        self.assertEqual(codex.execute(run_id, sleep=sleep), 9)
        sleep.assert_not_called()
        self.assertEqual(self.report.read_text(), "Failed: the run wrote no report.\n")
        result = json.loads((state / "result.json").read_text())
        self.assertEqual((result["exit"], result["tries"]), (9, 1))
        self.assertEqual(result["tokens"]["input_tokens"], 0)

    def test_execute_capacity_retries_resume_with_first_thread_and_settings(self):
        self.fake_codex([{"code": 1, "capacity": True},
                         {"thread": "thread-2", "report": "Done: resumed.\n"}])
        run_id, state = self.launch(effort="xhigh", read_only=True, model="chosen-model")

        def sleeping(delay):
            self.assertEqual(delay, codex.DELAYS[0])
            self.assertEqual((state / "thread").read_text(), "thread-1\n")
            self.assertIn(codex.CAPACITY, (state / "events.jsonl").read_text())
            self.assertFalse((state / "ended").exists())

        sleep = Mock(side_effect=sleeping)
        self.assertEqual(codex.execute(run_id, sleep=sleep), 0)
        sleep.assert_called_once_with(codex.DELAYS[0])
        calls = self.calls()
        self.assertEqual(len(calls), 2)
        for index, thread in enumerate((None, "thread-1")):
            self.assertEqual(calls[index]["argv"], codex.command(effort="xhigh", read_only=True,
                             model="chosen-model", last=state / "last.md", thread=thread)[1:])
        self.assertEqual(calls[1]["prompt"], "Go on with the task: the model was at capacity.")
        self.assertEqual((state / "thread").read_text(), "thread-1\n")
        self.assertEqual(json.loads((state / "result.json").read_text())["tries"], 2)
        self.assertEqual(self.report.read_text(), "Done: resumed.\n")

    def test_execute_capacity_retries_are_bounded(self):
        self.fake_codex([{"code": 7, "capacity": True, "stderr": True}])
        run_id, state = self.launch()
        sleep = Mock()
        self.assertEqual(codex.execute(run_id, sleep=sleep), 7)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], list(codex.DELAYS))
        self.assertEqual(len(self.calls()), 1 + len(codex.DELAYS))
        result = json.loads((state / "result.json").read_text())
        self.assertEqual(result["tries"], 1 + len(codex.DELAYS))
        self.assertEqual((state / "stderr.log").read_text().count(codex.CAPACITY), result["tries"])

    def test_execute_does_not_retry_a_different_error_after_capacity(self):
        self.fake_codex([{"code": 1, "capacity": True, "stderr": True}, {"code": 8}])
        run_id, state = self.launch()
        sleep = Mock()
        self.assertEqual(codex.execute(run_id, sleep=sleep), 8)
        sleep.assert_called_once_with(codex.DELAYS[0])
        self.assertEqual(json.loads((state / "result.json").read_text())["tries"], 2)

    def test_execute_does_not_retry_capacity_without_a_thread(self):
        self.fake_codex([{"code": 1, "capacity": True, "thread": None}])
        run_id, _ = self.launch()
        sleep = Mock()
        self.assertEqual(codex.execute(run_id, sleep=sleep), 1)
        sleep.assert_not_called()

    def test_execute_records_a_missing_executable(self):
        run_id, state = self.launch()
        with patch.dict(os.environ, {"PATH": str(self.home / "no-binaries")}):
            self.assertEqual(codex.execute(run_id), 127)
        self.assertIn("codex", (state / "stderr.log").read_text())
        self.assertEqual(json.loads((state / "result.json").read_text())["exit"], 127)
        self.assertTrue((state / "ended").exists())

    def test_main_start_prints_id_and_state_and_exec_returns_the_exit_code(self):
        out = io.StringIO()
        with patch.object(codex, "run", self.fake), redirect_stdout(out):
            self.assertEqual(codex.main(["start", str(self.brief), str(self.workdir), str(self.report),
                                         "--effort", "medium", "--read-only", "--model", "chosen"]), 0)
        run_id, directory = out.getvalue().strip().split(maxsplit=1)
        self.assertEqual(Path(directory), codex.state_root() / run_id)
        meta = json.loads((Path(directory) / "meta.json").read_text())
        self.assertEqual((meta["effort"], meta["read_only"], meta["model"]), ("medium", True, "chosen"))
        with patch.object(codex, "execute", return_value=7) as execute:
            self.assertEqual(codex.main(["_exec", run_id]), 7)
        execute.assert_called_once_with(run_id)

    def test_main_refusals_return_two_with_a_reason(self):
        for args in ([], ["unknown"], ["start"], ["_exec"],
                     ["start", str(self.brief), str(self.workdir), str(self.report), "--effort", "low"],
                     ["start", "relative", str(self.workdir), str(self.report)]):
            with self.subTest(args=args), redirect_stderr(io.StringIO()) as err:
                self.assertEqual(codex.main(args), 2)
                self.assertIn("fab codex:", err.getvalue())
        self.fake.on(["systemd-run"], Result(1, err="service unavailable"))
        with patch.object(codex, "run", self.fake), redirect_stderr(io.StringIO()) as err:
            self.assertEqual(codex.main(["start", str(self.brief), str(self.workdir), str(self.report)]), 2)
        self.assertIn("service unavailable", err.getvalue())


if __name__ == "__main__":
    unittest.main()
