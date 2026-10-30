import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from unittest.mock import patch

from fab import atomic, hosts, log, report
from fab.heavy import EX_TEMPFAIL
from fab.sh import Result, ssh
from fab.tests.support import FakeRunner, tmp_home


START = "2026-10-29T00:00:00.000Z"
END = "2026-10-30T00:00:00.000Z"
MID = "2026-10-29T12:00:00.000Z"
HOSTS = '''
[zgate]
ssh = "gate@z"
roles = ["gate", "builder"]
[builder]
ssh = "build@b"
roles = ["builder"]
[dispatcher]
ssh = "dispatch@d"
roles = ["dispatcher"]
[agate]
ssh = "gate@a"
roles = ["gate"]
'''


def heavy_argv(target, user):
    return ssh(target, ["sh", "-c", 'test ! -e "$1" || cat "$1"', "sh",
                        f"/home/{user}/src/fabrig/fab/heavy.jsonl"])


def lines(*records):
    return "\n".join(json.dumps(record) for record in records) + "\n"


class ReportTest(unittest.TestCase):
    def test_report_day_windows(self):
        self.assertEqual(report.day_window("2026-10-29", END), report.Window(START, END))
        self.assertEqual(report.day_window(None, MID), report.Window(START, MID))
        self.assertEqual(report.day_window("2026-10-29", MID), report.Window(START, END))
        for day in ("bad", "2026-02-30", "2026-1-01", "2026-10-31"):
            with self.subTest(day=day), self.assertRaises(ValueError):
                report.day_window(day, MID)

    def test_report_window_edges_and_previous(self):
        window = report.Window(START, MID)
        self.assertTrue(window.holds(START))
        self.assertFalse(window.holds(MID))
        self.assertFalse(window.holds("2026-10-28T23:59:59.999Z"))
        self.assertEqual(window.hours(), 12.0)
        self.assertEqual(window.previous(), report.Window("2026-10-28T12:00:00.000Z", START))
        records = [{"ts": START}, {}, {"ts": MID}, {"ts": START, "n": 2}]
        self.assertEqual(report.within(iter(records), window), [records[0], records[3]])

    def test_report_timestamps_and_minutes(self):
        ts = log.now()
        self.assertEqual(report.stamp(report.moment(ts)), ts)
        self.assertEqual(report.moment(ts).tzinfo, timezone.utc)
        self.assertEqual(report.stamp(datetime(2026, 10, 29, microsecond=123456,
                                               tzinfo=timezone.utc)), "2026-10-29T00:00:00.123Z")
        self.assertEqual(report.minutes(START, MID), 720.0)
        self.assertEqual(report.minutes(MID, START), -720.0)
        for bad in ("bad", "2026-10-29T00:00:00Z", "2026-10-29T00:00:00.000+00:00",
                    "2026-10-29T00:00:00.0000Z", "2026-02-30T00:00:00.000Z"):
            with self.subTest(ts=bad), self.assertRaises(ValueError):
                report.moment(bad)

    def test_report_nearest_rank_quantiles(self):
        self.assertIsNone(report.quantile([], 0.5))
        self.assertEqual(report.quantile([7], 0.9), 7)
        self.assertEqual(report.quantile(iter([4, 1, 3, 2]), 0.5), 2)
        self.assertEqual(report.quantile([4, 1, 3, 2], 0.9), 4)
        self.assertEqual(report.quantile([2, 1], 0), 1)

    def test_report_figures_and_tables(self):
        for value, expected in ((None, "-"), (2, "2"), (True, "True"), (False, "False"),
                                (2.26, "2.3")):
            with self.subTest(value=value):
                self.assertEqual(report.show(value), expected)
        self.assertEqual(report.trend(1.0, None), "1.0 (prev -)")
        self.assertEqual(report.table(("a|b", "c\nd"), [("e|f\ng", 1)]),
                         ["| a\\|b | c d |", "| --- | --- |", "| e\\|f g | 1 |"])
        self.assertEqual(report.table(["empty"], []), ["| empty |", "| --- |"])
        self.assertEqual(report.figure_table([("b", "Bee"), ("a", "Aye")],
                                             {"a": 2}, {"b": 1.0}),
                         ["| Figure | Value |", "| --- | --- |",
                          "| Bee | - (prev 1.0) |", "| Aye | 2 (prev -) |"])

    def test_report_heavy_waits(self):
        record = {"ts": START, "ev": "heavy", "lane_wait": 30.0,
                  "disk_wait": 60.0, "code": EX_TEMPFAIL}
        heavy = {"a": [record, {**record, "ts": END}, {**record, "ev": "other"}],
                 "b": [{**record, "lane_wait": 90.0, "code": 0}], "other": [record]}
        self.assertEqual(report.heavy_waits(heavy, ["a", "b", "missing"], report.Window(START, END)),
                         {"commands": 2, "lane_wait": 2.0, "disk_wait": 2.0, "disk_refused": 1})
        empty = report.heavy_waits({}, ["missing"], report.Window(START, END))
        self.assertEqual(empty, {"commands": 0, "lane_wait": 0.0, "disk_wait": 0.0, "disk_refused": 0})
        self.assertIsInstance(empty["lane_wait"], float)
        self.assertIsInstance(empty["disk_wait"], float)

    def test_report_signal_lines(self):
        self.assertEqual(report.signal_lines([]), ["- none"])
        self.assertEqual(report.signal_lines([report.Signal("2 errors", "Read errors", "operator")]),
                         ["- **2 errors:** Read errors (operator)"])

    def test_report_gather_sources_and_commands(self):
        queue = {"ts": START, "ev": "queue"}
        heavy = {"ts": START, "ev": "heavy"}
        invalid = '\n{"ts":\n[]\n{"ts": 5}\n{}\n'
        queue_argv = ssh("gate@a", ["fab", "queue", "log", "--since", START])
        argv_a = heavy_argv("gate@a", "gate")
        argv_b = heavy_argv("build@b", "build")
        argv_z = heavy_argv("gate@z", "gate")
        runner = FakeRunner().on(queue_argv, Result(0, lines(queue) + invalid))
        runner.on(argv_a, Result(0, lines({**heavy, "ts": "2026-10-28T23:59:59.999Z"}, heavy) + invalid))
        runner.on(argv_b, Result(0, lines({**heavy, "ts": MID})))
        with tmp_home() as home:
            event = log.append("note", ts="2026-10-28T00:00:00.000Z")
            sources = report.gather(hosts.parse(HOSTS), START, sh=runner)
            self.assertTrue((home / "fab" / "log.jsonl").is_file())
        self.assertEqual(sources.log, [event])
        self.assertEqual(sources.queue, [queue])
        self.assertEqual(sources.heavy, {"agate": [heavy], "builder": [{**heavy, "ts": MID}], "zgate": []})
        self.assertEqual(sources.unread, [])
        self.assertEqual(runner.argvs(), [queue_argv, argv_a, argv_b, argv_z])

    def test_report_gather_failures_do_not_stop_other_reads(self):
        queue_argv = ssh("gate@a", ["fab", "queue", "log", "--since", START])
        record = {"ts": START, "ev": "heavy"}
        runner = FakeRunner().on(queue_argv, Result(1, "stdout", "details\nqueue unavailable\n"))
        runner.on(heavy_argv("gate@a", "gate"), Result(1, "details\nheavy unavailable\n"))
        runner.on(heavy_argv("build@b", "build"), Result(0, lines(record)))
        with tmp_home():
            sources = report.gather(hosts.parse(HOSTS), START, sh=runner)
        self.assertEqual(sources.unread, ["queue agate: queue unavailable", "heavy agate: heavy unavailable"])
        self.assertEqual(sources.queue, [])
        self.assertEqual(sources.heavy, {"agate": [], "builder": [record], "zgate": []})
        self.assertEqual(len(runner.calls), 4)

    def test_report_gather_without_gate_and_explicit_log(self):
        selected = hosts.parse(HOSTS)
        selected = {name: host for name, host in selected.items() if "gate" not in host.roles}
        runner = FakeRunner()
        with tmp_home() as home:
            path = home / "fab" / "custom.jsonl"
            event = log.append("note", path=path, ts=START)
            sources = report.gather(selected, START, sh=runner, log_path=path)
        self.assertEqual(sources.unread, ["queue: no gate host"])
        self.assertEqual(sources.queue, [])
        self.assertEqual(sources.log, [event])
        self.assertEqual(sources.heavy, {"builder": []})
        self.assertEqual(runner.argvs(), [heavy_argv("build@b", "build")])

    def test_report_path(self):
        with tmp_home() as home:
            self.assertEqual(report.report_path("plan", "2026-10-29"),
                             home / "fab" / "reports" / "plan" / "2026-10-29.md")
            self.assertEqual(report.report_path(report.LANDING, "2026-10-29"),
                             home / "fab" / "reports" / "landing" / "2026-10-29.md")


class ReportCommandTest(unittest.TestCase):
    def setUp(self):
        self.home = self.enterContext(tmp_home())
        self.sources = report.Sources([], [], {}, ["queue: unavailable"])
        self.selected = hosts.parse(HOSTS)
        self.gather = self.enterContext(patch("fab.report.gather", return_value=self.sources))
        self.load_hosts = self.enterContext(patch("fab.hosts.load", return_value=self.selected))
        self.enterContext(patch("fab.log.now", return_value=END))

    def plan(self, draft="sample"):
        directory = self.home / draft
        atomic.write(directory / "plan.toml", f'''draft = "{draft}"
repo = "agents"
[[part]]
id = "core"
title = "Core"
mode = "feature"
needs = []
design = "docs/design/fab.md"
[[slice]]
id = 1
story = "Report"
parts = ["core"]
walk = false
''')
        atomic.write(directory / "tasks" / "task.md", '''+++
id = "task"
part = "core"
kind = "feature"
+++
Implement the task.
''')
        return directory

    def command(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = report.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_report_command_code_print_and_write(self):
        directory = self.plan()
        code, text, err = self.command(["code", str(directory)])
        self.assertEqual((code, err), (0, ""))
        self.assertTrue(text.startswith("# Code report: sample, 2026-10-30\n"))
        self.assertIn(f"{END} to {END}", text)
        self.assertIn("queue: unavailable", text)
        self.assertFalse((self.home / "fab" / "reports").exists())
        self.load_hosts.assert_called_once_with()
        self.gather.assert_called_once_with(self.selected, "2026-10-23T00:00:00.000Z")
        code, written, err = self.command(["code", str(directory), "--write"])
        path = self.home / "fab" / "reports" / "sample" / "2026-10-30.md"
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(written, text + str(path) + "\n")
        self.assertEqual(path.read_text(), text)

    def test_report_command_landing_day_and_write(self):
        code, text, err = self.command(["landing", "--day", "2026-10-29", "--write"])
        path = self.home / "fab" / "reports" / "landing" / "2026-10-29.md"
        self.assertEqual((code, err), (0, ""))
        self.assertTrue(text.startswith("# Landing report, 2026-10-29\n"))
        self.assertIn(f"{START} to {END}", text)
        self.assertEqual(text, path.read_text() + str(path) + "\n")
        self.gather.assert_called_once_with(self.selected, "2026-10-21T00:00:00.000Z")

    def test_report_command_daily_keeps_existing_reports(self):
        directories = [self.plan(), self.plan("another")]
        argv = ["daily", *(str(path) for path in directories)]
        code, text, err = self.command(argv)
        paths = [self.home / "fab" / "reports" / name / "2026-10-29.md"
                 for name in ("sample", "another", "landing")]
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(text.splitlines(), [f"{path} written" for path in paths])
        self.gather.assert_called_once_with(self.selected, "2026-10-21T00:00:00.000Z")
        contents = [path.read_bytes() for path in paths]
        # Kept means not rewritten: same inode, size and mtime (atime moves on every read).
        stats = [(s.st_ino, s.st_size, s.st_mtime_ns) for s in (path.stat() for path in paths)]
        self.assertTrue(contents[0].startswith(b"# Code report: sample, 2026-10-29\n"))
        with patch("fab.atomic.write") as write:
            code, text, err = self.command(argv)
        write.assert_not_called()
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(text.splitlines(), [f"{path} kept" for path in paths])
        self.assertEqual([path.read_bytes() for path in paths], contents)
        self.assertEqual([(s.st_ino, s.st_size, s.st_mtime_ns) for s in (path.stat() for path in paths)],
                         stats)

    def test_report_command_daily_continues_after_plan_errors(self):
        valid = self.plan()
        broken = self.plan("broken")
        task = broken / "tasks" / "task.md"
        atomic.write(task, task.read_text().replace('part = "core"', 'part = "missing"'))
        missing = self.home / "missing"
        code, text, err = self.command(["daily", str(missing), str(broken), str(valid)])
        self.assertEqual(code, 1)
        self.assertIn(str(missing / "plan.toml"), err)
        self.assertIn("task broken/task names unknown part missing", err)
        self.assertFalse((self.home / "fab" / "reports" / "broken").exists())
        for name in ("sample", "landing"):
            path = self.home / "fab" / "reports" / name / "2026-10-29.md"
            self.assertTrue(path.is_file())
            self.assertIn(f"{path} written", text)
        self.gather.assert_called_once_with(self.selected, "2026-10-21T00:00:00.000Z")

    def test_report_command_code_plan_error(self):
        directory = self.home / "missing"
        code, text, err = self.command(["code", str(directory), "--write"])
        self.assertEqual((code, text), (1, ""))
        self.assertIn(str(directory / "plan.toml"), err)
        self.assertFalse((self.home / "fab" / "reports").exists())

    def test_report_command_bad_arguments(self):
        for argv in (["landing", "--day", "bad"], ["landing", "--day", "2026-10-31"],
                     ["code", "missing", "--day", "2026-02-30"], [], ["daily"],
                     ["code"], ["daily", "missing", "--write"]):
            with self.subTest(argv=argv), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    report.main(argv)
                self.assertEqual(error.exception.code, 2)
        self.load_hosts.assert_not_called()
        self.gather.assert_not_called()
