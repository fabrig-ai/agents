import io
import os
import shlex
import unittest
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from fab import atomic, log, wake
from fab.sh import Failed, Result, ssh
from fab.tests.support import FakeRunner
from fab.tests.wakes import (
    BUILDER, DISPATCHER, HOSTS, WakeTestCase, ended, here, imported, landed, started,
)


class ExemplarTest(WakeTestCase):
    def test_red_settled_and_closed_wake_and_imported_reds_note_lost_events(self):
        records = [dict(ev="tiers.red", key="default::b::t", al_ts="1"),
                   dict(ev="tiers.recovered", key="default::b::t", al_ts="2"),
                   dict(ev="red.settled"), dict(ev="red.closed"), dict(ev="red.opened")]
        self.assertEqual(wake.wanted(records), ["red.settled", "red.closed"])
        wake.settle("backstop", None, records, path=self.want, log_path=self.log_path)
        self.assertEqual(self.notes(), ["lost event: tiers.red default::b::t; tiers.recovered default::b::t"])
        self.assertWanted("tick 1: red.settled, red.closed")

    def test_an_event_reaches_the_tick_once_and_a_lost_one_is_noted(self):
        fake = FakeRunner()
        # A builder's run ends: its wake goes over ssh to the dispatcher, where it is a want.
        self.assertTrue(wake.wake("codex 1", sh=fake, hosts=HOSTS, here=BUILDER))
        self.assertEqual(fake.argvs(), [ssh(HOSTS[DISPATCHER].ssh, ["fab", "wake", "codex 1"])])
        self.assertNoWant()
        self.assertTrue(wake.wake("codex 1", sh=fake, hosts=HOSTS, here=DISPATCHER))
        self.assertTrue(wake.wake("queue landed draft/a", sh=fake, hosts=HOSTS, here=DISPATCHER))
        self.assertEqual(len(fake.calls), 1)
        self.assertWanted("codex 1", "queue landed draft/a")
        # A burst is one want, taken once.
        self.assertEqual(wake.take(self.want), ["codex 1", "queue landed draft/a"])
        self.assertIsNone(wake.take(self.want))
        # A backstop round that collects an ended run found an event nobody announced.
        lines = wake.settle("backstop", None, [started("draft/b-1"), ended("draft/a-1")],
                            path=self.want, log_path=self.log_path)
        self.assertEqual(self.notes(), ["lost event: run.ended draft/a-1"])
        self.assertWanted("tick 1: run.ended")
        self.assertEqual(lines, ["lost - lost event: run.ended draft/a-1",
                                 "again - tick 1: run.ended"])


class WantTest(WakeTestCase):
    def test_want_path_is_beside_the_selected_log(self):
        self.assertEqual(wake.want_path(), self.want)
        self.assertEqual(wake.want_path(self.home / "elsewhere/events.jsonl"),
                         self.home / "elsewhere" / wake.WANT)

    def test_want_appends_lines_in_order_and_flattens_or_replaces_blank_reasons(self):
        self.assertEqual(wake.want("  codex 1  "), self.want)
        wake.want("first\nsecond\r\nthird\rlast")
        wake.want(" \n\t ")
        self.assertWanted("codex 1", "first second third last", "-")

    def test_want_creates_parents_and_a_private_file_with_one_append_write(self):
        path = self.home / "new/nested" / wake.WANT
        with patch.object(wake.os, "open", wraps=os.open) as opened, \
                patch.object(wake.os, "write", wraps=os.write) as written:
            self.assertEqual(wake.want("queue landed demo/a", path=path), path)
        opened.assert_called_once_with(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        self.assertEqual(written.call_count, 1)
        self.assertEqual(written.call_args.args[1], b"queue landed demo/a\n")
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(path.read_text(), "queue landed demo/a\n")
        self.assertNoWant()

    def test_take_absent_empty_and_stripped_nonblank_lines(self):
        self.assertIsNone(wake.take())
        atomic.write(self.want, "")
        self.assertEqual(wake.take(), [])
        atomic.write(self.want, "  first  \n\n  \n second\n")
        self.assertEqual(wake.take(), ["first", "second"])
        self.assertNoWant()
        self.assertFalse(self.want.with_name(wake.TAKEN).exists())

    def test_take_replaces_a_crashed_ticks_taken_file(self):
        atomic.write(self.want.with_name(wake.TAKEN), "stale\n")
        wake.want("fresh")
        self.assertEqual(wake.take(), ["fresh"])
        self.assertNoWant()
        self.assertFalse(self.want.with_name(wake.TAKEN).exists())

    def test_a_want_after_the_rename_survives_taking(self):
        wake.want("before")
        read_text = Path.read_text

        def read(path, *args, **kwargs):
            if path == self.want.with_name(wake.TAKEN):
                self.assertNoWant()
                wake.want("during")
            return read_text(path, *args, **kwargs)

        with patch.object(Path, "read_text", read):
            self.assertEqual(wake.take(), ["before"])
        self.assertWanted("during")
        self.assertEqual(wake.take(), ["during"])


class DeliveryTest(WakeTestCase):
    def test_dispatcher_appends_without_a_command(self):
        fake = FakeRunner()
        self.assertTrue(wake.wake("answer demo/core", hosts=HOSTS, here=DISPATCHER, sh=fake))
        self.assertWanted("answer demo/core")
        self.assertEqual(fake.argvs(), [])

    def test_builder_and_unknown_machine_send_reason_as_one_ssh_argument(self):
        reason = "call a b; '$literal'"
        for name in (BUILDER, "unknown"):
            with self.subTest(name=name):
                fake = FakeRunner()
                self.assertTrue(wake.wake(reason, hosts=HOSTS, here=name, sh=fake))
                self.assertEqual(fake.argvs(), [ssh(HOSTS[DISPATCHER].ssh, ["fab", "wake", reason])])
                self.assertNoWant()

    def test_first_dispatcher_by_name_receives_the_wake(self):
        hosts = {"z": replace(HOSTS[DISPATCHER], name="z", ssh="fab@second.invalid"),
                 "a": HOSTS[BUILDER], "b": HOSTS[DISPATCHER]}
        fake = FakeRunner()
        self.assertTrue(wake.wake("codex 1", hosts=hosts, here="a", sh=fake))
        self.assertEqual(fake.argvs(), [ssh(hosts["b"].ssh, ["fab", "wake", "codex 1"])])

    def test_failed_ssh_result_or_exception_is_false_without_retry(self):
        for failure in (Result(1, err="unreachable"), OSError("no ssh"),
                        Failed(["ssh"], Result(1))):
            def fail(call):
                if isinstance(failure, Exception):
                    raise failure
                return failure
            fake = FakeRunner().on(["ssh"], fail)
            with self.subTest(failure=failure):
                self.assertFalse(wake.wake("codex 1", hosts=HOSTS, here=BUILDER, sh=fake))
                self.assertEqual(len(fake.calls), 1)
                self.assertNoWant()

    def test_no_dispatcher_runs_nothing(self):
        fake = FakeRunner()
        self.assertFalse(wake.wake("codex 1", hosts={BUILDER: HOSTS[BUILDER]},
                                   here=BUILDER, sh=fake))
        self.assertFalse(wake.wake("codex 1", hosts={}, here=DISPATCHER, sh=fake))
        self.assertEqual(fake.argvs(), [])
        self.assertNoWant()

    def test_defaults_load_hosts_and_follow_fab_host(self):
        fake = FakeRunner()
        with patch.object(wake.machines, "load", return_value=HOSTS) as load, here(DISPATCHER):
            self.assertTrue(wake.wake("call 1", sh=fake))
        load.assert_called_once_with()
        self.assertWanted("call 1")
        self.assertEqual(fake.argvs(), [])
        with here(BUILDER):
            self.assertTrue(wake.wake("call 2", sh=fake, hosts=HOSTS, here=None))
        self.assertEqual(fake.argvs(), [ssh(HOSTS[DISPATCHER].ssh, ["fab", "wake", "call 2"])])


class RoundTest(WakeTestCase):
    def test_wanted_keeps_first_occurrences_in_record_order(self):
        records = [started("demo/a-1"), landed("demo/a"), ended("demo/a-1"),
                   landed("demo/b"), {"ev": "note"}]
        records += [{"ev": kind} for kind in reversed(wake.AGAIN)]
        expected = ["branch.landed", "run.ended"]
        expected += [kind for kind in reversed(wake.AGAIN) if kind not in expected]
        self.assertEqual(wake.wanted(iter(records)), expected)
        self.assertEqual(wake.wanted([started("demo/a-1"), {}]), [])

    def test_again_counts_up_to_the_limit_then_stops(self):
        kinds = ["run.ended", "branch.landed"]
        taken = []
        for number in range(1, wake.AGAIN_LIMIT + 1):
            reason = f"tick {number}: run.ended, branch.landed"
            self.assertEqual(wake.again(kinds, taken), reason)
            taken = [reason]
        self.assertIsNone(wake.again(kinds, taken))
        self.assertEqual(wake.again(kinds, ["tick 1: branch.landed", "tick 3: call.answered"]),
                         "tick 4: run.ended, branch.landed")

    def test_outside_or_malformed_tick_reason_resets_the_count(self):
        for reason in ("codex 1", "tick x: run.ended", "tick 0: run.ended", "tick -1: run.ended",
                       "tick 2", "tick 1:run.ended"):
            with self.subTest(reason=reason):
                self.assertEqual(wake.again(["run.ended"], ["tick 5: run.ended", reason]),
                                 "tick 1: run.ended")

    def test_lost_orders_wakes_then_ended_runs_and_queue_imports(self):
        records = [started("demo/a-1"), landed("demo/a"), ended("demo/a-1"),
                   imported("branch.landed", "demo/b"), ended("demo/c-1"),
                   imported("branch.rejected", "demo/d")]
        self.assertEqual(wake.lost(["codex 1", "queue landed demo/b"], iter(records)),
                         ["wake codex 1", "wake queue landed demo/b", "run.ended demo/a-1",
                          "branch.landed demo/b", "run.ended demo/c-1", "branch.rejected demo/d"])
        self.assertEqual(wake.lost(None, [landed("demo/a")]), [])
        self.assertEqual(wake.lost([], []), [])

    def test_lost_queue_records_without_a_task_name_the_branch(self):
        records = [dict(ev=kind, branch="hand/pushed", queue_ts="001") for kind in
                   ("queue.rejected", "queue.landed", "queue.collateral")]
        self.assertEqual(wake.lost(None, iter(records)),
                         ["queue.rejected hand/pushed", "queue.landed hand/pushed",
                          "queue.collateral hand/pushed"])
        lines = wake.settle("backstop", None, records)
        text = ("lost event: queue.rejected hand/pushed; queue.landed hand/pushed; "
                "queue.collateral hand/pushed")
        self.assertEqual(lines, ["lost - " + text])
        self.assertEqual(self.notes(), [text])
        self.assertNoWant()

    def test_hand_and_event_rounds_want_again_without_lost_notes(self):
        for trigger in ("hand", "event"):
            with self.subTest(trigger=trigger):
                lines = wake.settle(trigger, ["codex 1"], [ended("demo/a-1"), landed("demo/a")])
                self.assertEqual(lines, ["again - tick 1: run.ended, branch.landed"])
                self.assertWanted("tick 1: run.ended, branch.landed")
                self.assertEqual(self.notes(), [])
                wake.take()

    def test_backstop_notes_taken_wakes_and_imported_work_before_wanting_again(self):
        lines = wake.settle("backstop", ["queue landed demo/a"],
                            [imported("branch.landed", "demo/a")])
        text = "lost event: wake queue landed demo/a; branch.landed demo/a"
        self.assertEqual(self.notes(), [text])
        self.assertEqual(lines, ["lost - " + text, "again - tick 1: branch.landed"])
        self.assertWanted("tick 1: branch.landed")

    def test_backstop_notes_a_taken_wake_even_without_new_work(self):
        self.assertEqual(wake.settle("backstop", ["codex 1"], []),
                         ["lost - lost event: wake codex 1"])
        self.assertEqual(self.notes(), ["lost event: wake codex 1"])
        self.assertNoWant()

    def test_quiet_rounds_produce_no_want_note_or_printed_line(self):
        for trigger in wake.TRIGGERS:
            with self.subTest(trigger=trigger):
                self.assertEqual(wake.settle(trigger, None, [started("demo/a-1")]), [])
        self.assertNoWant()
        self.assertEqual(self.notes(), [])

    def test_limit_logs_a_note_instead_of_wanting_again(self):
        lines = wake.settle("event", [f"tick {wake.AGAIN_LIMIT}: run.ended"], [ended("demo/a-1")])
        self.assertEqual(lines, ["again - stopped"])
        self.assertEqual(self.notes(), [f"tick: {wake.AGAIN_LIMIT} rounds in a row wanted another; "
                                        "the next waits for an event or the backstop"])
        self.assertNoWant()

    def test_paths_select_the_want_and_log_for_notes(self):
        path = self.home / "other/tick.want"
        log_path = self.home / "other/events.jsonl"
        wake.settle("backstop", None, [ended("demo/a-1")], path=path, log_path=log_path)
        self.assertEqual(path.read_text(), "tick 1: run.ended\n")
        self.assertEqual([record["text"] for record in log.read(log_path)],
                         ["lost event: run.ended demo/a-1"])
        self.assertNoWant()
        self.assertEqual(self.notes(), [])

    def test_unknown_trigger_raises_before_any_write(self):
        with self.assertRaises(ValueError):
            wake.settle("unknown", ["codex 1"], [ended("demo/a-1")])
        self.assertNoWant()
        self.assertEqual(self.notes(), [])


class UnitsTest(WakeTestCase):
    def test_units_have_paths_triggers_plans_and_service_limits(self):
        home = self.home / "state"
        checkout = self.home / "install with space"
        plans = [Path("relative plan"), self.home / "plan's two"]
        files = wake.units(plans, checkout=checkout, home=home)
        self.assertEqual(list(files), [wake.EVENT_PATH, wake.EVENT_SERVICE,
                                      wake.BACKSTOP_TIMER, wake.BACKSTOP_SERVICE])
        path = self.unit(files, wake.EVENT_PATH)
        self.assertEqual(path, {
            "Unit": {"Description": "fab: start the tick while an event wants one"},
            "Path": {"PathExists": str(home / wake.WANT), "Unit": wake.EVENT_SERVICE},
            "Install": {"WantedBy": "default.target"}})
        timer = self.unit(files, wake.BACKSTOP_TIMER)
        self.assertEqual(timer, {
            "Unit": {"Description": "fab: the tick's backstop, every 10 minutes"},
            "Timer": {"OnCalendar": "*:0/10", "Unit": wake.BACKSTOP_SERVICE},
            "Install": {"WantedBy": "timers.target"}})
        for name, trigger, description in (
                (wake.EVENT_SERVICE, "event", "fab: the tick, started by an event"),
                (wake.BACKSTOP_SERVICE, "backstop", "fab: the tick's backstop")):
            unit = self.unit(files, name)
            self.assertEqual(unit["Unit"], {"Description": description})
            service = unit["Service"]
            self.assertEqual(service["Type"], "oneshot")
            self.assertEqual(service["TimeoutStartSec"], "10min")
            command = shlex.split(service["ExecStart"])
            self.assertEqual(command[:2], ["/usr/bin/bash", "-lc"])
            before, tick = command[2].split("; exec ")
            self.assertEqual(before, "{ git -C " + shlex.quote(str(checkout)) +
                             " fetch -q origin && git -C " + shlex.quote(str(checkout)) +
                             " checkout -q --detach origin/main; } || true")
            self.assertEqual(shlex.split(tick), [str(checkout / "bin/fab"), "tick",
                             "--trigger", trigger, *[str(path.absolute()) for path in plans]])

    def test_defaults_are_absolute_and_preserve_dot_segments(self):
        home = Path("relative/../state")
        files = wake.units([Path("plan/../draft")], home=home)
        self.assertEqual(self.unit(files, wake.EVENT_PATH)["Path"]["PathExists"],
                         str(home.absolute() / wake.WANT))
        command = self.unit(files, wake.EVENT_SERVICE)["Service"]["ExecStart"]
        self.assertIn(str(home.absolute() / "install/bin/fab"), command)
        self.assertIn(str(Path("plan/../draft").absolute()), command)
        defaults = wake.units([])
        self.assertEqual(self.unit(defaults, wake.EVENT_PATH)["Path"]["PathExists"],
                         str(self.want))

    def test_unsafe_path_characters_are_refused_in_every_path(self):
        for character in '\n\r%$"\\':
            for field in ("home", "checkout", "plan"):
                with self.subTest(character=character, field=field):
                    path = self.home / ("bad" + character + "path")
                    kwargs = {field: path} if field != "plan" else {}
                    with self.assertRaises(ValueError):
                        wake.units([path] if field == "plan" else [], **kwargs)


class InstallTest(WakeTestCase):
    def test_install_writes_units_before_reloading_enabling_and_stopping(self):
        for xdg in (None, str(self.home / "xdg")):
            with self.subTest(xdg=xdg), patch.dict(os.environ):
                if xdg is None:
                    os.environ.pop("XDG_CONFIG_HOME", None)
                else:
                    os.environ["XDG_CONFIG_HOME"] = xdg
                directory = (Path(xdg) if xdg else self.home / ".config") / "systemd/user"
                plans = [self.home / "one", self.home / "two"]
                files = wake.units(plans)

                def reload(call):
                    self.assertEqual({path.name: path.read_text() for path in directory.iterdir()}, files)
                    return Result(0)

                fake = FakeRunner().on(["systemctl", "--user", "daemon-reload"], reload)
                paths = wake.install(plans, sh=fake)
                self.assertEqual(paths, [directory / name for name in files])
                self.assertEqual(fake.argvs(), [
                    ["systemctl", "--user", "daemon-reload"],
                    ["systemctl", "--user", "enable", "--now", wake.EVENT_PATH, wake.BACKSTOP_TIMER],
                    ["systemctl", "--user", "stop", wake.OLD_TIMER]])

    def test_explicit_directory_and_checkout_and_failed_old_timer_stop(self):
        directory = self.home / "units"
        checkout = self.home / "code"
        fake = FakeRunner().on(["systemctl", "--user", "stop"], Result(1))
        files = wake.units([], checkout=checkout)
        paths = wake.install([], sh=fake, directory=directory, checkout=checkout)
        self.assertEqual(paths, [directory / name for name in files])
        self.assertEqual({path.name: path.read_text() for path in paths}, files)

    def test_reload_or_enable_failure_raises_and_skips_later_commands(self):
        for command, count in (("daemon-reload", 1), ("enable", 2)):
            with self.subTest(command=command):
                fake = FakeRunner().on(["systemctl", "--user", command], Result(1))
                with self.assertRaises(Failed):
                    wake.install([], sh=fake, directory=self.home / "units")
                self.assertEqual(len(fake.calls), count)

    def test_invalid_path_has_no_writes_or_commands(self):
        fake = FakeRunner()
        directory = self.home / "units"
        with self.assertRaises(ValueError):
            wake.install([Path("bad%path")], sh=fake, directory=directory)
        self.assertFalse(directory.exists())
        self.assertEqual(fake.calls, [])


class MainTest(WakeTestCase):
    def test_delivered_and_undelivered_reasons_have_exit_codes_and_stderr(self):
        for delivered, code, error in ((True, 0, ""), (False, 1, "fab wake: not delivered: codex 1\n")):
            with self.subTest(delivered=delivered), redirect_stderr(io.StringIO()) as err, \
                    patch.object(wake, "wake", return_value=delivered) as deliver:
                self.assertEqual(wake.main(["codex", "1"]), code)
                deliver.assert_called_once_with("codex 1")
                self.assertEqual(err.getvalue(), error)

    def test_no_reason_prints_usage_and_exits_two(self):
        with redirect_stderr(io.StringIO()) as err, patch.object(wake, "wake") as deliver:
            self.assertEqual(wake.main([]), 2)
        self.assertIn("usage: fab wake", err.getvalue())
        deliver.assert_not_called()

    def test_install_prints_paths_and_enabled_units(self):
        files = [self.home / wake.EVENT_PATH, self.home / wake.BACKSTOP_TIMER]
        with patch.object(wake, "install", return_value=files) as install, \
                redirect_stdout(io.StringIO()) as out:
            self.assertEqual(wake.main(["--install", "/plan/a", "/plan/b"]), 0)
        install.assert_called_once_with([Path("/plan/a"), Path("/plan/b")])
        self.assertEqual(out.getvalue().splitlines(), [*map(str, files),
                         f"enabled {wake.EVENT_PATH} {wake.BACKSTOP_TIMER}"])

    def test_errors_print_one_line_and_exit_one(self):
        for failure in (OSError("no file\nnext line"), ValueError("invalid path"),
                        Failed(["systemctl"], Result(1, err="bad unit\nfailed"))):
            with self.subTest(failure=failure), patch.object(wake, "install", side_effect=failure), \
                    redirect_stderr(io.StringIO()) as err:
                self.assertEqual(wake.main(["--install"]), 1)
                self.assertEqual(err.getvalue(), "fab wake: " + " ".join(str(failure).splitlines()) + "\n")


if __name__ == "__main__":
    unittest.main()
