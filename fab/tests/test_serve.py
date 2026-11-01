import copy
import io
import json
import os
import tempfile
import threading
import unittest
from contextlib import contextmanager, redirect_stdout
from datetime import datetime, timedelta, timezone
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from fab import cli, log, serve

NOW = datetime(2026, 11, 1, 0, 30, tzinfo=timezone.utc)


def event(kind, age=0, **fields):
    return {"ev": kind, "ts": (NOW - timedelta(seconds=age)).isoformat(), **fields}


def write(path, text):
    sibling = path.with_name(path.name + ".new")
    sibling.write_text(text)
    sibling.replace(path)


class SnapshotTest(unittest.TestCase):
    def test_serve_empty_and_invalid_timestamps(self):
        empty = serve.snapshot([], NOW, [])
        self.assertEqual(empty["updated"], "2026-11-01T00:30:00.000Z")
        self.assertEqual(empty["log"], "ok")
        self.assertIsNone(empty["last_event_age_s"])
        self.assertIsNone(empty["waiting_on_user"]["oldest_age_s"])
        self.assertEqual(empty["runs_in_flight"], {"total": 0, "by_host": {}})
        self.assertEqual(empty["calls_in_flight"], {"total": 0, "by_role": {}})
        self.assertEqual(empty["drafts"], {})
        for stamp in (None, "bad", "2026-11-01", "2026-11-01T00:00:00", 1, [],
                      "0001-01-01T00:00:00+23:00"):
            with self.subTest(stamp=stamp):
                self.assertEqual(serve.snapshot([{"ev": "branch.landed", "ts": stamp}], NOW, []), empty)
        self.assertEqual(serve.snapshot([event("branch.landed", -1)], NOW, []), empty)

    def test_serve_pairs_ids_and_bounds_starts_to_24_hours(self):
        events = [
            event("run.started", 86401, run="stale", task="stale/t", host="builder"),
            event("run.started", 86400, run="edge", task="edge/t", host="builder"),
            event("run.started", 80000, run="ended", task="ended/t", host="builder"),
            event("run.ended", 70000, run="ended", outcome="done"),
            event("run.ended", 60000, run="before", outcome="done"),
            event("run.started", 50000, run="before", task="ended/t", host="builder"),
            event("run.started", 20, run="active", task="active/t", host="private-host"),
            event("run.started", 20, run="active", task="active/t", host="private-host"),
            event("run.started", 15, task="missing/t", host="builder"),
            event("call.started", 86401, call="stale", role="review"),
            event("call.started", 86400, call="edge", role="review"),
            event("call.started", 500, call="ended", role="answer"),
            event("call.ended", 400, call="ended"),
            event("call.ended", 300, call="before"),
            event("call.started", 200, call="before", role="answer"),
            event("call.started", 42, call="active", role="private-role"),
            event("call.started", 42, call="active", role="private-role"),
        ]
        before = copy.deepcopy(events)
        current = serve.snapshot(events, NOW, ["builder"])
        self.assertEqual(events, before)
        self.assertEqual(current["last_event_age_s"], 42)
        self.assertEqual(current["runs_in_flight"], {"total": 2, "by_host": {"builder": 1, "other": 1}})
        self.assertEqual(current["calls_in_flight"], {"total": 2, "by_role": {"review": 1, "other": 1}})
        self.assertEqual(current["drafts"], {
            "active": {"runs_in_flight": 1, "landed_today": 0},
            "edge": {"runs_in_flight": 1, "landed_today": 0},
        })

    def test_serve_waiting_uses_latest_question_and_subject_in_log_order(self):
        events = [
            event("question.asked", 90000, task="reasked/t"),
            event("question.asked", 80000, task="closed/t"),
            event("question.answered", 70000, task="closed/t"),
            event("call.parked", 60000, subject="closed", call="old"),
            event("call.answered", 50000, subject="closed", call="different"),
            event("call.parked", 40000, subject="open", call="first"),
            event("call.parked", 30000, subject="open", call="second"),
            event("question.asked", 20000, task="reasked/t"),
            event("question.asked", 10000, task="another/t"),
            event("call.answered", 9000, subject="another/t"),
            event("question.answered", 8000, task="open"),
            event("question.asked", 7000),
            event("call.parked", 6000),
            {"ev": "question.answered", "ts": "bad", "task": "another/t"},
        ]
        self.assertEqual(serve.snapshot(events, NOW, [])["waiting_on_user"], {
            "questions": 2, "parked_calls": 1, "oldest_age_s": 30000,
        })
        events.extend([event("question.answered", task="reasked/t"),
                       event("question.answered", task="another/t"),
                       event("call.answered", subject="open")])
        self.assertEqual(serve.snapshot(events, NOW, [])["waiting_on_user"], {
            "questions": 0, "parked_calls": 0, "oldest_age_s": None,
        })

    def test_serve_waiting_has_no_expiry_and_invalid_endings_do_not_pair(self):
        events = [
            event("question.asked", 172800, task="old/t"),
            event("call.parked", 90000, subject="older-call"),
            event("run.started", 100, run="r", task="draft/t", host="builder"),
            event("call.started", 100, call="c", role="cut"),
            {"ev": "run.ended", "ts": "bad", "run": "r"},
            {"ev": "call.ended", "call": "c"},
        ]
        current = serve.snapshot(events, NOW, ["builder"])
        self.assertEqual(current["waiting_on_user"], {
            "questions": 1, "parked_calls": 1, "oldest_age_s": 172800,
        })
        self.assertEqual(current["runs_in_flight"]["total"], 1)
        self.assertEqual(current["calls_in_flight"]["by_role"], {"cut": 1})

    def test_serve_today_hour_outcomes_and_weights(self):
        events = [
            event("branch.landed", 3601, task="old/t"),
            event("branch.landed", 3600, task="hour/t"),
            event("branch.landed", 1801, task="yesterday/t"),
            event("branch.landed", 1800, task="today/one"),
            {"ev": "branch.landed", "ts": "2026-10-31T20:15:00-04:00", "task": "today/two"},
            event("branch.landed", -86400, task="tomorrow/t"),
            event("branch.rejected", 1801), event("branch.rejected", 1800),
            event("run.ended", 1801, outcome="done", tokens="9000000/0/0"),
            event("call.ended", 1801, tokens="9000000/0/0"),
            event("run.ended", 1800, outcome="done", tokens="2000000/1000000/100000"),
            event("run.ended", 1700, outcome="question", tokens="bad"),
            event("run.ended", 1600, outcome="infra"),
            event("run.ended", 1500, outcome="failed"),
            event("run.ended", 1400, outcome="private-outcome"),
            event("run.ended", 1300),
            event("call.ended", 1200, tokens="1000000/1000000/100000", cache_write=400000),
            event("call.ended", 1100, tokens="bad"),
            event("call.ended", 1000),
        ]
        local_now = NOW.astimezone(timezone(timedelta(hours=5)))
        current = serve.snapshot(events, local_now, [])
        self.assertEqual(current["updated"], "2026-11-01T00:30:00.000Z")
        self.assertEqual(current["landed"], {"last_hour": 4, "today": 2})
        self.assertEqual(current["rejected_today"], 1)
        self.assertEqual(current["runs_ended_today"], {
            "done": 1, "question": 1, "infra": 1, "failed": 1, "other": 2,
        })
        self.assertEqual(current["weight_today"], {"codex_m": 1.9, "claude_m": 2.1})
        self.assertEqual(current["drafts"], {"today": {"runs_in_flight": 0, "landed_today": 2}})

    def test_serve_drafts_are_bounded_public_names(self):
        valid = ["a", "release-1.2", "a" * 64]
        invalid = ["a" * 65, "Upper", "-dash", "path<secret>", "", "../hidden"]
        events = [event("branch.landed", task=name + "/private-task") for name in valid + invalid]
        events += [event("branch.landed"), event("branch.landed", task=["bad"]),
                   event("branch.landed", task="private-call-id")]
        current = serve.snapshot(events, NOW, [])
        self.assertEqual(current["drafts"]["other"], {"runs_in_flight": 0, "landed_today": 9})
        for name in valid:
            self.assertEqual(current["drafts"][name], {"runs_in_flight": 0, "landed_today": 1})

    def test_serve_privacy_in_json_and_html(self):
        private = {
            "run": "secret-run-id", "call": "secret-call-id", "login": "secret-login-id",
            "task": "<secret-draft>/secret-task-id", "branch": "secret-branch", "sha": "secret-sha",
            "path": "/secret/path", "text": "secret question text", "answer": "secret answer text",
            "notes": "secret notes", "report": "/secret/report", "holder": "secret holder",
            "subject": "secret-subject", "host": "secret-host", "role": "secret-role",
            "outcome": "secret-outcome",
        }
        events = [event(kind, **private) for kind in (
            "run.started", "call.started", "question.asked", "call.parked", "branch.landed",
            "branch.rejected", "note",
        )]
        events.append(event("run.ended", **{**private, "run": "another-secret-run"}))
        events.append(event("run.started", run="review-run", task="private-call-id"))
        current = serve.snapshot(events, NOW, ["builder"])
        for output in (json.dumps(current), serve.render(current)):
            for secret in private.values():
                self.assertNotIn(secret, output)
            self.assertNotIn("another-secret-run", output)
            self.assertNotIn("private-call-id", output)
            self.assertNotIn("review-run", output)
        self.assertEqual(current["runs_in_flight"]["by_host"], {"other": 2})
        self.assertEqual(current["calls_in_flight"]["by_role"], {"other": 1})
        self.assertEqual(current["runs_ended_today"]["other"], 1)

    def test_serve_render_escapes_text_and_formats_ages(self):
        label = '<host & "name">'
        current = serve.snapshot([event("run.started", 42, run="r", task="draft/t", host=label)], NOW, [label])
        page = serve.render(current)
        self.assertNotIn(label, page)
        self.assertIn("&lt;host &amp; &quot;name&quot;&gt;", page)
        self.assertIn('<title>fab status</title>', page)
        self.assertIn('<meta http-equiv="refresh" content="30">', page)
        self.assertIn("prefers-color-scheme: dark", page)
        self.assertIn("width=device-width", page)
        self.assertNotIn("<script", page)
        for title in ("Now", "Waiting on the user", "Today", "Drafts"):
            self.assertIn(f"<h2>{title}</h2>", page)
        for age, expected in ((42, "42 s"), (420, "7 min"), (10800, "3 h"), (None, "none")):
            current["last_event_age_s"] = age
            current["waiting_on_user"]["oldest_age_s"] = age
            self.assertIn(f"<dd>{expected}</dd>", serve.render(current))
        failure = serve.render({"updated": "now", "log": "unreadable"})
        self.assertIn("Log unreadable", failure)
        self.assertNotIn("Runs in flight", failure)


class ServerTest(unittest.TestCase):
    @contextmanager
    def running(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.dict(os.environ, {"HOME": directory, "FAB_HOME": directory}), \
                patch.object(serve.machines, "load", return_value={"builder": None}), \
                ThreadingHTTPServer(("127.0.0.1", 0), serve._Request) as server:
            thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
            thread.start()
            try:
                yield server.server_port, Path(directory) / "log.jsonl"
            finally:
                server.shutdown()
                thread.join(timeout=2)
                self.assertFalse(thread.is_alive())

    def request(self, port, path, method="GET"):
        connection = HTTPConnection("127.0.0.1", port, timeout=2)
        try:
            connection.request(method, path)
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read().decode()
        finally:
            connection.close()

    def test_serve_routes_query_strings_fresh_reads_and_no_writes(self):
        with self.running() as (port, path):
            with patch.object(serve.log, "read", wraps=log.read) as reads:
                code, headers, body = self.request(port, "/?ignored=private")
                self.assertEqual(code, 200)
                self.assertTrue(headers["Content-Type"].startswith("text/html"))
                self.assertIn("fab status", body)
                self.assertFalse(path.exists())
                code, headers, body = self.request(port, "/api/status?ignored=yes")
                self.assertEqual(code, 200)
                self.assertTrue(headers["Content-Type"].startswith("application/json"))
                self.assertEqual(json.loads(body)["runs_in_flight"]["total"], 0)
                line = json.dumps({"ts": log.now(), "ev": "run.started", "run": "r",
                                   "task": "draft/t", "host": "builder"}) + '\n{"torn":'
                write(path, line)
                code, _, body = self.request(port, "/api/status")
                self.assertEqual(code, 200)
                self.assertEqual(json.loads(body)["runs_in_flight"], {"total": 1, "by_host": {"builder": 1}})
                self.assertEqual(self.request(port, "/healthz?ignored=yes")[::2], (200, "ok"))
                self.assertEqual(self.request(port, "/unknown?secret")[::2], (404, "not found"))
                self.assertEqual(reads.call_count, 5)
                self.assertEqual(path.read_text(), line)
                self.assertEqual(sorted(p.name for p in path.parent.iterdir()), ["log.jsonl"])

    def test_serve_all_other_methods_are_405(self):
        with self.running() as (port, path):
            for method in ("POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS", "TRACE", "CONNECT", "UNKNOWN"):
                with self.subTest(method=method):
                    code, headers, body = self.request(port, "/api/status", method)
                    self.assertEqual(code, 405)
                    self.assertEqual(headers["Allow"], "GET")
                    self.assertEqual(body, "" if method == "HEAD" else "method not allowed")
            self.assertFalse(path.exists())

    def test_serve_unreadable_log_returns_fixed_failure_and_no_figures(self):
        with self.running() as (port, path):
            path.mkdir()  # An unreadable log even when tests run as root.
            code, _, body = self.request(port, "/api/status")
            self.assertEqual(code, 200)
            current = json.loads(body)
            self.assertEqual(set(current), {"updated", "log"})
            self.assertEqual(current["log"], "unreadable")
            code, _, body = self.request(port, "/")
            self.assertEqual(code, 200)
            self.assertIn("Log unreadable", body)
            self.assertNotIn(str(path), body)
            self.assertEqual(self.request(port, "/healthz")[::2], (200, "ok"))

    def test_serve_host_failure_classifies_unknown_hosts(self):
        with self.running() as (port, path):
            write(path, json.dumps({"ts": log.now(), "ev": "run.started", "run": "r",
                                   "host": "private", "task": "draft/t"}) + "\n")
            with patch.object(serve.machines, "load", side_effect=ValueError("private reason")):
                code, _, body = self.request(port, "/api/status")
            self.assertEqual(code, 200)
            self.assertNotIn("private", body)
            self.assertEqual(json.loads(body)["runs_in_flight"]["by_host"], {"other": 1})

    def test_serve_command_registration_defaults_and_bound_port(self):
        self.assertEqual(cli.COMMANDS["serve"], ("fab.serve", "the public status page, live from the log"))
        for args, address in (([], ("127.0.0.1", 8370)),
                              (["--bind", "0.0.0.0", "--port", "0"], ("0.0.0.0", 0))):
            out = io.StringIO()
            with patch.object(serve, "ThreadingHTTPServer") as factory, redirect_stdout(out):
                server = factory.return_value.__enter__.return_value
                server.server_port = 12345
                server.serve_forever.side_effect = KeyboardInterrupt
                self.assertEqual(cli.main(["serve", *args]), 0)
                factory.assert_called_once_with(address, serve._Request)
                factory.return_value.__exit__.assert_called_once()
            self.assertEqual(out.getvalue(), f"serving on http://{address[0]}:12345\n")
