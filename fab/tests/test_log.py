import json
import unittest

from fab import log
from fab.tests.support import tmp_home


class LogTest(unittest.TestCase):
    def test_append_then_read_in_order(self):
        with tmp_home() as home:
            first = log.append("run.started", run="a/b-1", task="a/b")
            log.append("run.ended", run="a/b-1", outcome="done", minutes=12)
            records = log.read()
            self.assertEqual([r["ev"] for r in records], ["run.started", "run.ended"])
            self.assertEqual(records[0], first)
            self.assertEqual(records[1]["minutes"], 12)
            self.assertTrue((home / "fab" / "log.jsonl").exists())

    def test_a_torn_last_line_is_skipped_and_closed_off(self):
        with tmp_home() as home:
            log.append("note", text="one")
            path = home / "fab" / "log.jsonl"
            with open(path, "a") as torn:
                torn.write('{"ts": "x", "ev": "no')
            log.append("note", text="two")
            self.assertEqual([r["text"] for r in log.read()], ["one", "two"])
            self.assertEqual(len(path.read_text().splitlines()), 3)

    def test_fields_must_be_flat(self):
        with self.assertRaises(ValueError):
            log.record("note", nested={"a": 1})
        with self.assertRaises(ValueError):
            log.record("Not.Valid")
        self.assertEqual(log.record("note", files=("a", "b"))["files"], ["a", "b"])

    def test_missing_log_reads_empty(self):
        with tmp_home():
            self.assertEqual(log.read(), [])

    def test_timestamps_are_utc_milliseconds(self):
        stamp = log.now()
        self.assertRegex(stamp, r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$")
        self.assertEqual(json.loads(json.dumps(log.record("note", ts=stamp)))["ts"], stamp)


class RecordsTest(unittest.TestCase):
    def test_records_keep_objects_in_line_order_without_requiring_an_event(self):
        first = {"ts": "002", "text": "café"}
        second = {"ts": "001", "ev": "landed", "branch": "draft/a"}
        self.assertEqual(log.records(json.dumps(first) + "\n" + json.dumps(second)),
                         [first, second])
        self.assertEqual(log.records('{"ts":""}'), [{"ts": ""}])

    def test_records_skip_blank_malformed_non_objects_and_non_string_timestamps(self):
        lines = ("", "  ", '{"ts":', "stray output", "[]", "null", "true", "3", "1.5",
                 '"text"', "{}", '{"ev":"landed"}', '{"ts":null}', '{"ts":1}',
                 '{"ts":true}', '{"ts":[]}', '{"ts":{}}', '{"ts":"003"}')
        self.assertEqual(log.records("\n".join(lines)), [{"ts": "003"}])
        self.assertEqual(log.records(""), [])
