"""Persistent unit texts and installs use isolated files and fake systemd commands."""

import io
import os
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from fab import atomic, hosts, log, units
from fab.sh import Failed, Result
from fab.tests.support import FakeRunner, tmp_home

STATUS = "fab-status.service"
TIMER = "fab-issues.timer"
SERVICE = "fab-issues.service"
SYSTEMCTL = ["systemctl", "--user"]


def _show(name):
    return [*SYSTEMCTL, "show", "--property=Transient,ActiveState", "--value", name]


class UnitTextTest(unittest.TestCase):
    def test_status_text_and_default_paths(self):
        with tmp_home():
            expected = ("[Unit]\nDescription=fab: the public status page\n\n"
                        "[Service]\nEnvironment=FAB_HOME=/fab home\n"
                        'ExecStart=/usr/bin/bash -lc "exec \'/fab home/install/bin/fab\' '
                        'serve --port 8370 --bind 127.0.0.1"\n'
                        "Restart=on-failure\nRestartSec=5\nSuccessExitStatus=75\n"
                        "RestartForceExitStatus=75\n\n[Install]\nWantedBy=default.target\n")
            self.assertEqual(units.status_service(home=Path("/fab home")), expected)
            self.assertEqual(units.status_units(home=Path("/fab home")), {STATUS: expected})
            self.assertEqual(units.status_service(), units.status_service(home=log.home()))
            self.assertIn('/other/bin/fab serve', units.status_service(checkout=Path('/other')))

    def test_issues_texts_timer_then_service(self):
        with tmp_home():
            expected = {
                TIMER: ("[Unit]\nDescription=fab: the user's questions as forge issues, every 2 minutes\n\n"
                        "[Timer]\nOnCalendar=*:1/2\nUnit=fab-issues.service\n\n"
                        "[Install]\nWantedBy=timers.target\n"),
                SERVICE: ("[Unit]\nDescription=fab: the user's questions as forge issues\n\n"
                          "[Service]\nType=oneshot\nEnvironment=FAB_HOME=/fab\nKillSignal=SIGINT\n"
                          "TimeoutStartSec=infinity\n"
                          'ExecStart=/usr/bin/bash -lc "exec /fab/install/bin/fab issues sync"\n')}
            actual = units.issues_units(home=Path("/fab"))
            self.assertEqual(actual, expected)
            self.assertEqual(list(actual), [TIMER, SERVICE])
            self.assertEqual(units.timer_service("the user's questions as forge issues", "issues sync",
                                                "infinity", home=Path("/fab")), expected[SERVICE])
            self.assertEqual(units.timer("the user's questions as forge issues", "every 2 minutes",
                                        "*:1/2", SERVICE), expected[TIMER])

    def test_quiet_and_persistent_text(self):
        with tmp_home():
            self.assertEqual(units.timer_service("checks", "logins check --all", "1800", quiet=True,
                                                 home=Path('/fab'), checkout=Path('/code')),
                             "[Unit]\nDescription=fab: checks\n\n[Service]\nType=oneshot\n"
                             "Environment=FAB_HOME=/fab\nKillSignal=SIGINT\nTimeoutStartSec=1800\n"
                             "StandardOutput=null\nStandardError=journal\n"
                             'ExecStart=/usr/bin/bash -lc "exec /code/bin/fab logins check --all"\n')
            self.assertEqual(units.timer("reports", "daily", "daily", "report.service", persistent=True),
                             "[Unit]\nDescription=fab: reports, daily\n\n[Timer]\nOnCalendar=daily\n"
                             "Persistent=true\nUnit=report.service\n\n[Install]\nWantedBy=timers.target\n")

    def test_unsafe_paths_and_arguments_are_rejected(self):
        with tmp_home():
            for character in '\n\r%$"\\':
                bad = "bad" + character
                for build in (units.status_units, units.issues_units):
                    for option in ("home", "checkout"):
                        with self.subTest(character=character, build=build, option=option):
                            with self.assertRaises(ValueError):
                                build(**{option: Path(bad)})
                for position in range(3):
                    arguments = ["checks", "issues sync", "1800"]
                    arguments[position] = bad
                    with self.assertRaises(ValueError):
                        units.timer_service(*arguments)
                for position in range(4):
                    arguments = ["checks", "daily", "daily", SERVICE]
                    arguments[position] = bad
                    with self.assertRaises(ValueError):
                        units.timer(*arguments)


    def test_percent_in_fab_home_is_rejected(self):
        with tmp_home() as root, patch.dict(os.environ, {"FAB_HOME": str(root / "bad%home")}):
            for build in (units.status_units, units.issues_units):
                with self.assertRaises(ValueError):
                    build()


class UnitInstallTest(unittest.TestCase):
    def setUp(self):
        home = tmp_home()
        self.root = home.__enter__()
        self.addCleanup(home.__exit__, None, None, None)
        environment = patch.dict(os.environ, {"FAB_HOST": "here"})
        environment.start()
        self.addCleanup(environment.stop)
        self.known = {"here": hosts.Host("here", "fake", ("dispatcher",))}
        self.directory = self.root / "units"
        self.sh = FakeRunner().on(["loginctl"], Result(0, "yes\n"))

    def install(self, files=None, *, primary=TIMER, restartable=False, known=None):
        return units.install_units(units.issues_units() if files is None else files,
                                   primary=primary, restartable=restartable, sh=self.sh,
                                   directory=self.directory, known=self.known if known is None else known)

    def seed(self, files):
        for name, text in files.items():
            atomic.write(self.directory / name, text)

    def test_without_role_no_files_runs_nothing(self):
        for known in ({}, {"here": hosts.Host("here", "fake", ("builder",))}):
            with self.subTest(known=known):
                self.assertEqual(self.install(known=known),
                                 ([f"{TIMER}: no dispatcher role here: nothing to do"], []))
                self.assertEqual(self.sh.argvs(), [])
                self.assertFalse(self.directory.exists())

    def test_without_role_disables_and_stops_primary_only(self):
        self.seed({SERVICE: "existing\n"})
        expected = f"{TIMER}: no dispatcher role here: disabled and stopping"
        self.assertEqual(self.install(known={}), ([expected], []))
        self.assertEqual(self.sh.argvs(), [[*SYSTEMCTL, "disable", TIMER],
                                          [*SYSTEMCTL, "stop", "--no-block", TIMER]])
        self.assertEqual((self.directory / SERVICE).read_text(), "existing\n")
        self.assertFalse((self.directory / TIMER).exists())

    def test_first_install_queries_all_before_stops_then_writes_reload_and_enable(self):
        files = units.issues_units()
        events = []

        def answer(call):
            events.append(call.argv)
            return Result(0, "yes\ninactive\n")

        self.sh.rules.insert(0, (SYSTEMCTL, answer))
        real_write = atomic.write

        def record(path, text):
            events.append(str(path))
            real_write(path, text)

        with patch.object(units.atomic, "write", side_effect=record):
            lines, warnings = self.install(dict(reversed(list(files.items()))))
        paths = [str(self.directory / name) for name in reversed(files)]
        expected = [_show(TIMER), _show(SERVICE)]
        for name in (TIMER, SERVICE):
            expected.extend([[*SYSTEMCTL, "stop", name], [*SYSTEMCTL, "reset-failed", name]])
        expected.extend([*paths, [*SYSTEMCTL, "daemon-reload"], [*SYSTEMCTL, "enable", "--now", TIMER]])
        self.assertEqual(events, expected)
        self.assertEqual(lines, [*paths, f"enabled {TIMER}"])
        self.assertEqual(warnings, [])
        for name, text in files.items():
            self.assertEqual((self.directory / name).read_text(), text)

    def test_active_transient_status_can_be_replaced(self):
        self.sh.on(_show(STATUS), Result(0, "yes\nactive\n"))
        self.install(units.status_units(), primary=STATUS, restartable=True)
        self.assertEqual(self.sh.argvs()[:-1], [_show(STATUS), [*SYSTEMCTL, "stop", STATUS],
                         [*SYSTEMCTL, "reset-failed", STATUS], [*SYSTEMCTL, "daemon-reload"],
                         [*SYSTEMCTL, "enable", "--now", STATUS]])

    def test_nontransient_units_are_never_stopped(self):
        self.sh.on(_show(TIMER), Result(0, "active\nno\n"))
        self.sh.on(_show(SERVICE), Result(0, "active\nno\n"))
        self.install()
        self.assertFalse(any(call.argv[2] in ("stop", "reset-failed", "restart")
                             for call in self.sh.calls if call.argv[:2] == SYSTEMCTL))

    def test_active_transient_service_refuses_before_stops_or_writes(self):
        for state in ("active", "activating", "deactivating", "reloading"):
            with self.subTest(state=state):
                self.sh = FakeRunner().on(_show(TIMER), Result(0, "yes\nactive\n"))
                self.sh.on(_show(SERVICE), Result(0, state + "\nyes\n"))
                out, err = io.StringIO(), io.StringIO()
                with redirect_stdout(out), redirect_stderr(err):
                    code = units.cli_install("issues", units.issues_units(), primary=TIMER,
                                             restartable=False, sh=self.sh,
                                             directory=self.directory, known=self.known)
                self.assertEqual(code, 1)
                self.assertEqual(out.getvalue(), "")
                self.assertEqual(err.getvalue(), f"fab issues: {SERVICE} is running; rerun when it ends\n")
                self.assertEqual(self.sh.argvs(), [_show(TIMER), _show(SERVICE)])
                self.assertFalse(self.directory.exists())

    def test_failed_transient_service_is_removed(self):
        self.sh.on(_show(SERVICE), Result(0, "yes\nfailed\n"))
        self.install()
        self.assertIn([*SYSTEMCTL, "stop", SERVICE], self.sh.argvs())
        self.assertIn([*SYSTEMCTL, "reset-failed", SERVICE], self.sh.argvs())

    def test_reinstall_restarts_only_changed_primary(self):
        for build, primary, restartable, changed in (
                (units.status_units, STATUS, True, None),
                (units.status_units, STATUS, True, STATUS),
                (units.status_units, STATUS, False, STATUS),
                (units.issues_units, TIMER, False, None),
                (units.issues_units, TIMER, False, TIMER),
                (units.issues_units, TIMER, False, SERVICE)):
            with self.subTest(primary=primary, restartable=restartable, changed=changed):
                files = build()
                self.seed({name: text + ("old\n" if name == changed else "")
                           for name, text in files.items()})
                self.sh.calls.clear()
                self.sh.rules = [(["loginctl"], Result(0, "yes\n")),
                                 ([*SYSTEMCTL, "is-enabled"], Result(0, "enabled\n"))]
                self.install(files, primary=primary, restartable=restartable)
                activity = [argv for argv in self.sh.argvs() if argv[2] in ("stop", "restart")]
                expected = [[*SYSTEMCTL, "restart", primary]] if changed == primary and (
                    restartable or primary == TIMER) else []
                self.assertEqual(activity, expected)
                for name, text in files.items():
                    self.assertEqual((self.directory / name).read_text(), text)

    def test_pause_writes_and_reloads_without_enable_or_restart(self):
        files = units.issues_units()
        self.seed({TIMER: "old timer\n"})
        self.sh.on([*SYSTEMCTL, "is-enabled", TIMER], Result(1, "disabled\n"))
        lines, warnings = self.install(files)
        self.assertEqual(self.sh.argvs()[:-1], [_show(TIMER), _show(SERVICE),
                         [*SYSTEMCTL, "is-enabled", TIMER], [*SYSTEMCTL, "daemon-reload"]])
        self.assertEqual(lines, [str(self.directory / name) for name in files] + [f"{TIMER} left disabled"])
        self.assertEqual(warnings, [])
        for name, text in files.items():
            self.assertEqual((self.directory / name).read_text(), text)

    def test_linger_failures_warn_but_succeed_and_use_os_identity(self):
        for answer in (Result(0, "no\n"), Result(1, "yes\n"), OSError("missing loginctl")):
            with self.subTest(answer=answer):
                self.sh = FakeRunner()
                if isinstance(answer, OSError):
                    self.sh.on(["loginctl"], lambda call: (_ for _ in ()).throw(answer))
                else:
                    self.sh.on(["loginctl"], answer)
                out, err = io.StringIO(), io.StringIO()
                with patch.object(units.os, "getuid", return_value=321), \
                        patch.object(units.getpass, "getuser", return_value="tester"), \
                        redirect_stdout(out), redirect_stderr(err):
                    code = units.cli_install("serve", units.status_units(), primary=STATUS,
                                             restartable=True, sh=self.sh,
                                             directory=self.directory, known=self.known)
                self.assertEqual(code, 0)
                self.assertEqual(err.getvalue(), "fab serve: linger is off for tester: the units start "
                                 "at boot only after loginctl enable-linger\n")
                self.assertEqual(self.sh.argvs()[-1], ["loginctl", "show-user", "321",
                                                      "--property=Linger", "--value"])

    def test_cli_maps_errors_to_one_line(self):
        for error in (OSError("cannot\nwrite"), ValueError("bad\nargument"),
                      Failed(["systemctl"], Result(1, err="broken\nservice"))):
            with self.subTest(error=error), patch.object(units, "install_units", side_effect=error), \
                    redirect_stderr(io.StringIO()) as err, redirect_stdout(io.StringIO()) as out:
                self.assertEqual(units.cli_install("issues", {}, primary=TIMER, restartable=False), 1)
                self.assertEqual(err.getvalue(), "fab issues: " + " ".join(str(error).splitlines()) + "\n")
                self.assertEqual(out.getvalue(), "")

    def test_default_directory_and_hosts(self):
        for config in ("", str(self.root / "xdg")):
            with self.subTest(config=config), patch.dict(os.environ, {"XDG_CONFIG_HOME": config}), \
                    patch.object(units.machines, "load", return_value=self.known) as load:
                files = units.status_units()
                lines, _ = units.install_units(files, primary=STATUS, restartable=True, sh=self.sh)
                directory = (Path(config) if config else self.root / ".config") / "systemd/user"
                self.assertEqual(lines, [str(directory / STATUS), f"enabled {STATUS}"])
                load.assert_called_once_with()
