"""Issue conversations use a fake forge and call runner, never a live service."""

import fcntl
import io
import json
import unittest
import urllib.error
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

from fab import atomic, calls, channel, cli, forge, log, wake
from fab.sh import Failed, Result
from fab.tests.support import FakeRunner, tmp_home


class Forge:
    def __init__(self):
        self.issues = {}
        self.comments = {}
        self.requests = []
        self.fail = None

    def __call__(self, method, path, payload=None):
        self.requests.append((method, path, payload))
        if self.fail and self.fail(method, path, payload):
            raise forge.ForgeError(f"{method} {path}")
        if method == "POST" and path == forge.ISSUES:
            number = len(self.issues) + 1
            self.issues[number] = {**payload, "number": number, "state": "open"}
            self.comments[number] = []
            return self.issues[number]
        suffix = path.removeprefix(forge.ISSUES + "/")
        number = int(suffix.split("/", 1)[0])
        if method == "GET":
            page = int(path.split("page=")[1].split("&")[0])
            return self.comments[number][(page - 1) * forge.PAGE_SIZE:page * forge.PAGE_SIZE]
        if method == "POST":
            return self.comment(number, payload["body"], author="bot")
        if method == "PATCH":
            self.issues[number].update(payload)
            return self.issues[number]
        raise AssertionError((method, path, payload))

    def comment(self, number, body, *, author="free", identifier=None):
        entry = dict(id=identifier or max((entry["id"] for entries in self.comments.values()
                                         for entry in entries), default=0) + 1,
                     user=dict(login=author), body=body, created_at=log.now())
        self.comments[number].append(entry)
        return entry


class ForgeTest(unittest.TestCase):
    def setUp(self):
        self.home = tmp_home()
        self.root = self.home.__enter__()
        self.addCleanup(self.home.__exit__, None, None, None)
        self.api = Forge()
        self.sh = FakeRunner()
        self.report = "Done: reply\n\nHere is more context.\n"
        self.briefs = []
        self.call_patch = patch.object(calls, "start", side_effect=self.call)
        self.start = self.call_patch.start()
        self.addCleanup(self.call_patch.stop)

    def ask(self, subject="draft/core", *, kind="call", name="asking", text="Question: Which option?\n\nUse A or B."):
        report = log.home() / "calls" / name / "report.md"
        atomic.write(report, text)
        if kind == "call":
            log.append("call.ended", subject=subject, call=name, outcome="question")
        else:
            log.append("call.parked", subject=subject, call=name, reason="The review refused twice.",
                       report=str(report))
        return report

    def call(self, role, subject, repo, brief, **kwargs):
        self.assertEqual((role, subject, repo, kwargs["sh"]),
                         ("reply", "issues/1", self.root, self.sh))
        identifier = f"reply-{len(self.briefs)}"
        self.briefs.append(brief)
        report = log.home() / "calls" / identifier / "report.md"
        atomic.write(report, self.report)
        log.append("call.started", role=role, subject=subject, call=identifier)
        log.append("call.ended", role=role, subject=subject, call=identifier, outcome="done")
        return dict(call=identifier, report=str(report), outcome="done")

    def sync(self):
        return forge.sync(self.root, api=self.api, sh=self.sh)

    def records(self, ev):
        return [entry for entry in log.read() if entry["ev"] == ev]

    def bodies(self):
        return [entry["body"] for entry in self.api.comments[1]]

    def test_ask_opens_once_with_label_title_report_and_footer(self):
        report = self.ask(text="\nQuestion: Which option?\n\nA or B.")
        self.assertEqual(self.sync(), 0)
        self.assertEqual(self.sync(), 0)
        self.assertEqual(len(self.api.issues), 1)
        issue = self.api.issues[1]
        self.assertEqual(issue["title"], "draft/core: Question: Which option?")
        self.assertEqual(issue["labels"], [1])
        self.assertIn(f"Read: {report}", issue["body"])
        self.assertTrue(issue["body"].endswith(forge.FOOTER))
        opened = self.records("issue.opened")
        self.assertEqual(len(opened), 1)
        self.assertEqual((opened[0]["subject"], opened[0]["kind"], opened[0]["number"], opened[0]["url"]),
                         ("draft/core", "call", 1, "https://git.fabrig.ai/fabrig-ai/agents/issues/1"))

    def test_parked_question_and_long_title(self):
        report = self.ask(kind="parked", text="Failed: review\nDetails.")
        self.sync()
        self.assertIn(f"The review refused twice.\n\nFailed: review\nDetails.\n\nRead: {report}",
                      self.api.issues[1]["body"])
        self.ask("draft/long", name="long", text="Question: " + "x" * 300)
        self.sync()
        self.assertEqual(len(self.api.issues[2]["title"]), 200)

    def test_no_plans_or_asks_means_no_forge_requests(self):
        self.assertEqual(self.sync(), 0)
        self.assertEqual(self.api.requests, [])

    def test_both_ask_kinds_share_one_subject_issue(self):
        self.ask()
        self.ask(kind="parked")
        self.sync()
        self.assertEqual(len(self.api.issues), 1)
        self.assertEqual(self.records("issue.opened")[0]["kind"], "parked")

    def test_comment_runs_one_reply_with_report_path_and_thread(self):
        report = self.ask()
        self.sync()
        self.api.comment(1, "Bot context", author="bot")
        comment = self.api.comment(1, "Why recommend A?")
        self.sync()
        self.sync()
        self.assertEqual(self.start.call_count, 1)
        brief = self.briefs[0]
        for text in (calls.ROLES["reply"].read_text(), "Question: Which option?", str(report),
                     "**bot**", "Bot context", "**free**", "Why recommend A?"):
            self.assertIn(text, brief)
        self.assertEqual(self.bodies()[-1], "Here is more context.")
        self.assertEqual(self.records("issue.comment")[0]["comment"], comment["id"])
        self.assertEqual(self.records("issue.replied")[0]["call"], "reply-0")
        self.assertEqual(len(channel.asks((), log.read())), 1)

    def test_answer_records_user_answer_wakes_and_closes(self):
        self.ask()
        self.sync()
        self.api.comment(1, "Yes, A.")
        self.report = "Done: answer\n\nUse option A for the core.\n"
        self.sync()
        self.assertEqual(self.sync(), 0)
        answered = self.records("call.answered")
        self.assertEqual(len(answered), 1)
        self.assertEqual((answered[0]["subject"], answered[0]["by"], answered[0]["answer"]),
                         ("draft/core", "user", "Use option A for the core."))
        self.assertIn("Recorded as your answer: Use option A for the core.", self.bodies())
        self.assertEqual(self.bodies()[-1], "Answered; closing.")
        self.assertEqual(self.api.issues[1]["state"], "closed")
        self.assertEqual(len(self.records("issue.closed")), 1)
        self.assertIn("answer draft/core", wake.want_path().read_text())

    def test_bot_other_author_and_logged_comments_are_ignored(self):
        self.ask()
        self.sync()
        self.api.comment(1, "Use B", author="bot")
        self.api.comment(1, "Use B", author="stranger")
        entry = self.api.comment(1, "Use A")
        log.append("issue.comment", number=1, subject="draft/core", comment=entry["id"])
        self.sync()
        self.start.assert_not_called()

    def test_hand_answer_closes_without_reading_more_comments(self):
        self.ask()
        self.sync()
        self.api.comment(1, "What about B?")
        channel.answer("draft/core", "Use A", log.read())
        self.sync()
        self.assertEqual(self.api.issues[1]["state"], "closed")
        self.start.assert_not_called()

    def test_failed_or_unreadable_call_consumes_comment_without_retry(self):
        self.ask()
        self.sync()
        self.api.comment(1, "Explain")
        self.report = "Question: Cannot read it\n"
        self.sync()
        self.sync()
        self.assertEqual(self.start.call_count, 1)
        self.assertEqual(self.bodies()[-1], forge.UNREADABLE)
        self.assertEqual(self.records("issue.replied")[0]["outcome"], "failed")
        self.assertFalse(self.records("call.answered"))
        self.api.comment(1, "Try this context")
        self.start.side_effect = Failed(["claude"], Result(1, err="private failure"))
        self.sync()
        self.assertEqual(self.bodies()[-1], forge.UNREADABLE)
        self.assertEqual(len(self.records("issue.replied")), 2)

    def test_comments_are_paginated_and_read_oldest_first_without_future_context(self):
        self.ask()
        self.sync()
        self.api.comment(1, "Later question", identifier=20)
        self.api.comment(1, "Earlier question", identifier=10)
        with patch.object(forge, "PAGE_SIZE", 1):
            self.sync()
        self.assertEqual(len(self.briefs), 2)
        self.assertIn("Earlier question", self.briefs[0])
        self.assertNotIn("Later question", self.briefs[0])
        self.assertIn("Later question", self.briefs[1])
        self.assertIn("Here is more context.", self.briefs[1])
        self.assertEqual([entry["comment"] for entry in self.records("issue.comment")], [10, 20])

    def test_an_answer_stops_later_comments_in_the_same_pass(self):
        self.ask()
        self.sync()
        self.api.comment(1, "Choose A")
        self.api.comment(1, "Another comment")
        self.report = "Done: answer\n\nUse A.\n"
        self.sync()
        self.assertEqual(self.start.call_count, 1)

    def test_closed_subject_asked_again_opens_new_issue_even_at_same_timestamp(self):
        with patch.object(log, "now", return_value="2026-11-01T00:00:00.000Z"):
            self.ask()
            self.sync()
            channel.answer("draft/core", "A", log.read())
            self.sync()
            self.ask(name="asking-again")
            self.sync()
            self.sync()
        self.assertEqual(len(self.api.issues), 2)
        self.assertEqual(self.api.issues[2]["state"], "open")

    def test_forge_failure_stops_and_keeps_earlier_opens(self):
        self.ask()
        self.ask("draft/next", name="next")
        self.api.fail = lambda method, path, payload: method == "POST" and len(self.api.issues) == 1
        err = io.StringIO()
        with redirect_stderr(err):
            self.assertEqual(self.sync(), 1)
        self.assertEqual(len(self.records("issue.opened")), 1)
        self.assertEqual(err.getvalue(), f"fab issues: open: POST {forge.ISSUES}\n")
        self.api.fail = None
        self.assertEqual(self.sync(), 0)
        self.assertEqual(len(self.api.issues), 2)

    def test_forge_failure_after_call_does_not_repeat_the_call(self):
        self.ask()
        self.sync()
        self.api.comment(1, "Explain")
        self.api.fail = lambda method, path, payload: method == "POST"
        with redirect_stderr(io.StringIO()) as err:
            self.assertEqual(self.sync(), 1)
        self.assertIn("converse: POST", err.getvalue())
        self.assertEqual(len(self.records("issue.comment")), 1)
        self.api.fail = None
        self.sync()
        self.assertEqual(self.start.call_count, 1)

    def test_close_patch_failure_resumes_from_log(self):
        self.ask()
        self.sync()
        channel.answer("draft/core", "A", log.read())
        self.api.fail = lambda method, path, payload: method == "PATCH"
        with redirect_stderr(io.StringIO()) as err:
            self.assertEqual(self.sync(), 1)
        self.assertIn("close: PATCH", err.getvalue())
        self.assertFalse(self.records("issue.closed"))
        self.api.fail = None
        self.sync()
        self.assertEqual(len(self.records("issue.closed")), 1)
        self.assertEqual(self.api.issues[1]["state"], "closed")

    def test_second_pass_exits_while_lock_is_held(self):
        log.home().mkdir(parents=True, exist_ok=True)
        with open(log.home() / "issues.lock", "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertEqual(self.sync(), 0)
        self.assertEqual(self.api.requests, [])

    def test_bad_forge_comment_shape_stops_without_a_call(self):
        self.ask()
        self.sync()
        self.api.comments[1].append(dict(id=1, body="text", user=None))
        with redirect_stderr(io.StringIO()) as err:
            self.assertEqual(self.sync(), 1)
        self.assertIn("converse: GET", err.getvalue())
        self.start.assert_not_called()


class ReplyResultTest(unittest.TestCase):
    def test_report_grammar(self):
        cases = [("Done: reply\n\nFirst.\n\nSecond.\n", ("reply", "First.\n\nSecond.")),
                 ("Done: answer\n\nUse A.\n", ("answer", "Use A.")),
                 ("Reply: Hello", ("", "")), ("Answer: A", ("", "")),
                 ("Done: reply\nHello", ("", "")), ("Done: reply\n\n", ("", "")),
                 ("Done: answer\n\nOne\nTwo", ("answer", "One Two")),
                 ("Done: answer\n\nOne\n\nTwo", ("", "")),
                 ("Done: answer extra\n\nA", ("", "")), ("Failed: no\n\nA", ("", ""))]
        with tmp_home() as root:
            path = root / "report.md"
            self.assertEqual(forge.reply_result(dict(outcome="done", report=str(path))), ("", ""))
            for text, expected in cases:
                with self.subTest(text=text):
                    atomic.write(path, text)
                    result = dict(outcome="done", report=str(path))
                    self.assertEqual(forge.reply_result(result), expected)
                    self.assertEqual(forge.reply_result({**result, "outcome": "failed"}), ("", ""))


class RequestTest(unittest.TestCase):
    def test_request_auth_json_and_errors_never_expose_the_token(self):
        with tmp_home() as root:
            token = "fake-secret-token-for-test"
            atomic.write(root / forge.TOKEN, token + "\n")
            opener = MagicMock()
            response = opener.open.return_value.__enter__.return_value
            response.read.return_value = b'{"number":1}'
            out, err = io.StringIO(), io.StringIO()
            with patch.object(forge.urllib.request, "build_opener", return_value=opener), \
                    redirect_stdout(out), redirect_stderr(err):
                self.assertEqual(forge.request("POST", forge.ISSUES, {"title": "Question"}), {"number": 1})
                req = opener.open.call_args.args[0]
                self.assertEqual(req.full_url, forge.API + forge.ISSUES)
                self.assertEqual(req.get_header("Authorization"), "token " + token)
                self.assertEqual(json.loads(req.data), {"title": "Question"})
                self.assertEqual(opener.open.call_args.kwargs["timeout"], 30)
                for error in (OSError(token), ValueError(token), urllib.error.HTTPError(
                        req.full_url, 401, token, None, None)):
                    opener.open.side_effect = error
                    with self.assertRaises(forge.ForgeError) as caught:
                        forge.request("POST", forge.ISSUES, {})
                    self.assertEqual(str(caught.exception), f"POST {forge.ISSUES}")
                log.append("call.ended", subject="draft/core", call="question", outcome="question")
                self.assertEqual(forge.sync(), 1)
            self.assertNotIn(token, out.getvalue() + err.getvalue() + log.default_path().read_text())
            self.assertEqual(err.getvalue(), f"fab issues: open: POST {forge.ISSUES}\n")

    def test_missing_token_is_a_sanitized_failure_and_redirects_are_refused(self):
        with tmp_home():
            with self.assertRaisesRegex(forge.ForgeError, "GET /test"):
                forge.request("GET", "/test")
            atomic.write(Path.home() / forge.TOKEN, "fake-token")
            opener = Mock()
            opener.open.side_effect = urllib.error.HTTPError("elsewhere", 302, "redirect", None, None)
            with patch.object(forge.urllib.request, "build_opener", return_value=opener) as build:
                with self.assertRaises(forge.ForgeError):
                    forge.request("GET", "/test")
                self.assertIsNone(build.call_args.args[0].redirect_request(None, None, 302, "", {}, "elsewhere"))

    def test_command_dispatch(self):
        with tmp_home(), patch.object(forge, "sync", return_value=0) as sync:
            self.assertEqual(cli.main(["issues", "sync"]), 0)
            sync.assert_called_once_with()
