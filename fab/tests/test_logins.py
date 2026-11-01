import io
import json
import os
import secrets
import stat
import unittest
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from fab import cli, log, logins, units
from fab.hosts import Host
from fab.sh import Result, run
from fab.tests.support import FakeRunner, tmp_home

# Runs `ssh [-o X]... TARGET COMMAND` here, with HOME the target's directory under FAKE_SSH_HOMES.
FAKE_SSH = """#!/bin/sh
while [ "$1" = -o ]; do shift 2; done
target=$1; shift
HOME="$FAKE_SSH_HOMES/$target" exec bash -c "$*"
"""
# Answers `codex app-server`'s initialize, account/read and account/rateLimits/read.
FAKE_CODEX = """#!/usr/bin/env -S python3 -I
import json, os, sys
if sys.argv[1:] != ["app-server"]:
    sys.exit(2)
for line in sys.stdin:
    message = json.loads(line)
    if message.get("id") == 2:
        out = {"result": {"account": {"type": "chatgpt", "email": os.environ.get("CODEX_HOME", "default"),
                                      "planType": "pro"}}}
    elif message.get("id") == 3:
        out = {"result": {"rateLimits": {"limitId": "codex",
                "primary": {"usedPercent": 17, "resetsAt": 1793774000, "windowDurationMins": 300},
                "secondary": {"usedPercent": 72, "resetsAt": 1793774975, "windowDurationMins": 10080}}}}
    elif message.get("id") == 1:
        out = {"result": {}}
    else:
        continue
    print(json.dumps({"id": message["id"], **out}), flush=True)
"""
# `claude -p` answers OK unless CLAUDE_CONFIG_DIR holds `expired`; `claude auth status --json` says who.
FAKE_CLAUDE = """#!/bin/sh
dir=${CLAUDE_CONFIG_DIR:-$HOME/.claude}
if [ "$1" = -p ]; then
  if [ -e "$dir/expired" ]; then echo '{"is_error": true, "result": "Failed to authenticate"}'
  else echo '{"is_error": false, "result": "OK"}'; fi
elif [ "$1 $2" = "auth status" ]; then
  if [ -e "$dir/expired" ]; then echo '{"loggedIn": false}'
  else echo '{"loggedIn": true, "email": "someone@example.invalid", "subscriptionType": "max"}'; fi
fi
"""


class LoginsTest(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.home = self.stack.enter_context(tmp_home())
        tools = self.home / "tools"
        tools.mkdir()
        for name, text in (("ssh", FAKE_SSH), ("codex", FAKE_CODEX), ("claude", FAKE_CLAUDE)):
            (tools / name).write_text(text)
            (tools / name).chmod(0o755)
        self.homes = self.home / "hosts"
        for name in ("b1", "b2", "gate"):
            (self.homes / f"free@{name}").mkdir(parents=True)
        self.stack.enter_context(patch.dict(os.environ, {
            "PATH": f"{tools}:{os.environ['PATH']}", "FAKE_SSH_HOMES": str(self.homes),
            "FAB_LOGINS": str(self.home / "shelf")}))
        self.hosts = {
            "hel8": Host("hel8", "free@hel8", ("dispatcher",)),
            "b1": Host("b1", "free@b1", ("builder",)),
            "b2": Host("b2", "free@b2", ("builder",)),
            "gate": Host("gate", "free@gate", ("gate",)),
        }
        self.outputs = []
        self.accounts = []
        self.shelf = logins.Shelf(hosts=self.hosts, local="hel8", sh=self.runner)

    def runner(self, argv, **kwargs):
        """The real runner, but `fab logins account` answers from self.accounts; every output kept."""
        if "logins account" in " ".join(argv):
            self.accounts.append(list(argv))
            return Result(0, json.dumps({"email": "a@example.invalid", "plan": "pro", "used": 40,
                                         "limits": [{"name": "week", "used": 40, "resets": 1793774975}]}) + "\n")
        result = run(argv, **kwargs)
        self.outputs.append(result.out + result.err)
        return result

    def at(self, host, path):
        return (self.home if host == "hel8" else self.homes / f"free@{host}") / path

    def secret(self, host, path, *, directory=False):
        """Fresh random bytes at host's path (a directory of two files when directory); return them."""
        place = self.at(host, path)
        value = secrets.token_hex(32).encode()
        if directory:
            (place / "nested").mkdir(parents=True, exist_ok=True)
            (place / ".credentials.json").write_bytes(value)
            (place / "nested" / "state").write_bytes(value[::-1])
        else:
            place.parent.mkdir(parents=True, exist_ok=True)
            place.write_bytes(value)
            place.chmod(0o600)
        return value

    def smith_root(self):
        """A dummy SMITH_LIVE root on b1, including the files named by smith's live tests."""
        source = "qa/smith-live"
        root = self.at("b1", source)
        for name, contents in {
            "config/smith/config.toml": 'credentials = "/home/free/.local/state/smith-live"',
            "host-id": "dummy host",
            "tokens/chatgpt": "dummy smith ChatGPT record",
            "programs/claude/.credentials.json": "dummy Claude record",
        }.items():
            destination = root / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            sibling = destination.with_name(destination.name + ".new")
            sibling.write_text(contents)
            sibling.replace(destination)
        root.chmod(0o755)
        return source

    def events(self):
        return [entry["ev"] for entry in log.read() if entry["ev"].startswith("login.")]

    def assertNeverPrinted(self, *values):
        for value in values:
            for output in self.outputs:
                self.assertNotIn(value.decode(), output)

    def test_capture_copies_a_machine_login_which_stays_lent_to_it(self):
        value = self.secret("b1", ".codex/auth.json")
        login = self.shelf.capture("b1", "codex")
        self.assertEqual((login.id, login.holder, login.host, login.path), ("codex-1", "b1", "b1", ".codex/auth.json"))
        self.assertEqual((self.home / "shelf/codex-1/auth.json").read_bytes(), value)
        self.assertEqual(self.at("b1", ".codex/auth.json").read_bytes(), value)
        self.assertEqual(stat.S_IMODE((self.home / "shelf/codex-1").stat().st_mode), 0o700)
        self.assertEqual(self.events(), ["login.added", "login.lent"])
        self.assertNeverPrinted(value)
        with self.assertRaisesRegex(logins.Refused, "already a lent login's"):
            self.shelf.capture("b1", "codex")
        self.assertEqual(self.shelf.capture("b1", "codex", path=".codex/auth.json", free=True).id, "codex-2")

    def test_return_copies_the_refreshed_login_back_and_lend_carries_it(self):
        self.secret("b1", ".codex/auth.json")
        self.shelf.capture("b1", "codex")
        refreshed = self.secret("b1", ".codex/auth.json")
        login = self.shelf.give_back("codex-1")
        self.assertTrue(login.free)
        self.assertFalse(self.at("b1", ".codex/auth.json").exists())
        self.assertEqual((self.home / "shelf/codex-1/auth.json").read_bytes(), refreshed)
        login = self.shelf.lend("codex-1", "b2")
        self.assertEqual((login.holder, login.path), ("b2", ".codex/auth.json"))
        lent = self.at("b2", ".codex/auth.json")
        self.assertEqual(lent.read_bytes(), refreshed)
        self.assertEqual(stat.S_IMODE(lent.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(lent.parent.stat().st_mode), 0o700)
        self.assertEqual([p.name for p in lent.parent.iterdir()], ["auth.json"])
        self.assertNeverPrinted(refreshed)

    def test_lend_refuses_what_would_break_custody(self):
        self.secret("b1", ".claude/.credentials.json")
        self.shelf.capture("b1", "claude")
        with self.assertRaisesRegex(logins.Refused, "not free: lent to b1"):
            self.shelf.lend("claude-1", "b2")
        self.shelf.give_back("claude-1")
        existing = self.secret("b2", ".claude/.credentials.json")
        with self.assertRaisesRegex(logins.Refused, "exists; return its login first"):
            self.shelf.lend("claude-1", "b2")
        self.assertEqual(self.at("b2", ".claude/.credentials.json").read_bytes(), existing)
        (self.home / "shelf/claude-1/.credentials.json").write_bytes(b"changed on the shelf")
        with self.assertRaisesRegex(logins.Refused, "not the one returned"):
            self.shelf.lend("claude-1", "b1")
        self.assertFalse(self.at("b1", ".claude/.credentials.json").exists())
        with self.assertRaisesRegex(logins.Refused, "no login claude-9"):
            self.shelf.lend("claude-9", "b1")
        with self.assertRaisesRegex(logins.Refused, "lent to a run; name its --path"):
            self.secret("b1", "qa/record")
            self.shelf.capture("b1", "chatgpt", path="qa/record", free=True)
            self.shelf.lend("chatgpt-1", "b2")
        self.assertEqual(self.events().count("login.lent"), 1)

    def test_return_refuses_a_link_and_a_missing_login(self):
        self.secret("b1", ".codex/auth.json")
        self.shelf.capture("b1", "codex")
        lent = self.at("b1", ".codex/auth.json")
        lent.unlink()
        with self.assertRaisesRegex(logins.Refused, "is missing"):
            self.shelf.give_back("codex-1")
        lent.symlink_to(self.at("b1", "elsewhere"))
        with self.assertRaisesRegex(logins.Refused, "is a link"):
            self.shelf.give_back("codex-1")
        self.assertEqual(self.shelf.login("codex-1").holder, "b1")
        self.shelf.retire("codex-1", "lost with b1")
        login = self.shelf.login("codex-1")
        self.assertEqual((login.free, login.retired, login.holder), (False, "lost with b1", None))
        with self.assertRaisesRegex(logins.Refused, r"retired \(lost with b1\)"):
            self.shelf.lend("codex-1", "b2")

    def test_swap_gives_back_the_machines_login_and_lends_the_other(self):
        first = self.secret("b1", ".codex/auth.json")
        self.shelf.capture("b1", "codex")
        self.secret("b2", ".codex/auth.json")
        self.shelf.capture("b2", "codex")
        self.shelf.give_back("codex-2")
        second = (self.home / "shelf/codex-2/auth.json").read_bytes()
        login = self.shelf.swap("b1", "codex-2")
        self.assertEqual((login.id, login.holder), ("codex-2", "b1"))
        self.assertEqual(self.at("b1", ".codex/auth.json").read_bytes(), second)
        self.assertTrue(self.shelf.login("codex-1").free)
        self.assertEqual((self.home / "shelf/codex-1/auth.json").read_bytes(), first)
        with self.assertRaisesRegex(logins.Refused, "not free"):
            self.shelf.swap("b2", "codex-2")

    def test_borrow_lends_the_lowest_free_login_of_a_kind_to_a_run(self):
        for number in range(1, 4):
            self.secret("b1", f"qa/record-{number}")
            self.shelf.capture("b1", "chatgpt", path=f"qa/record-{number}", free=True)
        self.shelf.lend("chatgpt-1", "b2", path="runs/r0/login", holder="r0")
        login = self.shelf.borrow("chatgpt", "b2", path="runs/r1/login", holder="r1")
        self.assertEqual((login.id, login.holder, login.path), ("chatgpt-2", "r1", "runs/r1/login"))
        self.assertTrue(self.at("b2", "runs/r1/login").is_file())
        for number in range(3, 4):
            self.shelf.retire(f"chatgpt-{number}", "test")
        with self.assertRaisesRegex(logins.Refused, "no free chatgpt login"):
            self.shelf.borrow("chatgpt", "b2", path="runs/r2/login", holder="r2")
        self.shelf.give_back("chatgpt-1")
        self.assertEqual(self.shelf.borrow("chatgpt", "b2", path="runs/r2/login", holder="r2").id, "chatgpt-1")

    def test_lending_a_claude_machine_login_forgets_the_account_its_predecessor_cached(self):
        settings = self.at("b2", ".claude.json")
        settings.write_text(json.dumps({"oauthAccount": {"emailAddress": "before@example.invalid"}, "theme": "dark"}))
        self.secret("b1", ".claude/.credentials.json")
        self.shelf.capture("b1", "claude")
        self.shelf.give_back("claude-1")
        self.shelf.lend("claude-1", "b2")
        self.assertEqual(json.loads(settings.read_text()), {"theme": "dark"})
        self.assertEqual(stat.S_IMODE(settings.stat().st_mode), 0o600)
        self.shelf.give_back("claude-1")
        settings.write_text(json.dumps({"oauthAccount": {"emailAddress": "kept@example.invalid"}}))
        self.shelf.lend("claude-1", "b2", path="runs/r1/.credentials.json", holder="r1")
        self.assertEqual(json.loads(settings.read_text()), {"oauthAccount": {"emailAddress": "kept@example.invalid"}})

    def test_github_fixtures_are_a_directory_lent_private_to_a_run(self):
        self.secret("b1", "src/rust/tmp/github-conformance", directory=True)
        self.shelf.capture("b1", "github", path="src/rust/tmp/github-conformance", free=True)
        login = self.shelf.borrow("github", "b2", path="walks/r1/github", holder="walk/github/rung-a-1")
        self.assertEqual(login.id, "github-1")
        # temper's proof-live-github.sh refuses fixtures whose directory is not 0700.
        self.assertEqual(stat.S_IMODE(self.at("b2", "walks/r1/github").stat().st_mode), 0o700)
        with self.assertRaisesRegex(logins.Refused, "has no check"):
            self.shelf.check("github-1")
        self.shelf.give_back("github-1")
        self.assertFalse(self.at("b2", "walks/r1/github").exists())

    def test_smith_live_capture_free_and_borrow_default_path_returns_the_root(self):
        source = self.smith_root()
        out = io.StringIO()
        with patch.object(logins, "Shelf", return_value=self.shelf), redirect_stdout(out):
            self.assertEqual(logins.main(["capture", "b1", "smith-live", "--path", source, "--free"]), 0)
        self.assertTrue(self.shelf.login("smith-live-1").free)
        self.assertTrue(self.at("b1", source).is_dir())
        self.assertEqual(self.events(), ["login.added"])
        login = self.shelf.borrow("smith-live", "b2", path="", holder="run-1")
        self.assertEqual((login.id, login.holder, login.path),
                         ("smith-live-1", "run-1", ".local/state/smith-live"))
        lent = self.at("b2", login.path)
        self.assertEqual(stat.S_IMODE(lent.stat().st_mode), 0o700)
        for original in self.at("b1", source).rglob("*"):
            if original.is_file():
                self.assertEqual((lent / original.relative_to(self.at("b1", source))).read_bytes(),
                                 original.read_bytes())
        self.assertTrue(self.shelf.give_back(login.id).free)
        self.assertFalse(lent.exists())
        self.assertEqual(self.events(), ["login.added", "login.lent", "login.returned"])

    def test_smith_live_lend_accepts_relative_tilde_and_host_absolute_fixed_paths(self):
        self.shelf.capture("b1", "smith-live", path=self.smith_root(), free=True)
        fixed = ".local/state/smith-live"
        destination = self.at("b2", fixed)
        for path in (fixed, "~/" + fixed, str(destination)):
            with self.subTest(path=path):
                login = self.shelf.lend("smith-live-1", "b2", path=path, holder="run-1")
                self.assertEqual(login.path, fixed if path.startswith("~/") else path)
                self.assertTrue(destination.is_dir())
                self.shelf.give_back(login.id)
                self.assertFalse(destination.exists())

    def test_smith_live_lend_and_borrow_refuse_other_paths_before_copying(self):
        self.shelf.capture("b1", "smith-live", path=self.smith_root(), free=True)
        paths = ("runs/r1/smith", str(self.at("b2", "elsewhere")),
                 str(self.home / ".local/state/smith-live"))
        for operation, name in ((self.shelf.lend, "smith-live-1"), (self.shelf.borrow, "smith-live")):
            for path in paths:
                with self.subTest(operation=operation.__name__, path=path), \
                        patch.object(self.shelf, "_push") as copy:
                    with self.assertRaisesRegex(logins.Refused,
                                                r"a smith-live login is lent only at ~/\.local/state/smith-live"):
                        operation(name, "b2", path=path, holder="run-1")
                    copy.assert_not_called()
                    self.assertFalse(self.at("b2", path).exists())
        self.assertFalse(self.at("b2", ".local").exists())
        self.assertTrue(self.shelf.login("smith-live-1").free)
        self.assertEqual(self.events(), ["login.added"])

    def test_smith_live_check_refuses_without_probing_or_lending(self):
        self.shelf.capture("b1", "smith-live", path=self.smith_root(), free=True)
        with patch.object(self.shelf, "_account") as probe:
            with self.assertRaisesRegex(logins.Refused,
                                        "a smith-live login has no check; its runs show whether it works"):
                self.shelf.check("smith-live-1")
        probe.assert_not_called()
        self.assertEqual(self.events(), ["login.added"])

    def test_borrow_cli_omits_path_only_for_a_fixed_kind(self):
        self.shelf.capture("b1", "smith-live", path=self.smith_root(), free=True)
        self.secret("b1", "qa/chatgpt")
        self.shelf.capture("b1", "chatgpt", path="qa/chatgpt", free=True)
        out, err = io.StringIO(), io.StringIO()
        with patch.object(logins, "Shelf", return_value=self.shelf), \
                redirect_stdout(out), redirect_stderr(err):
            self.assertEqual(logins.main(["borrow", "smith-live", "b2", "--holder", "run-1"]), 0)
            self.assertEqual(logins.main(["borrow", "chatgpt", "b2", "--holder", "run-2"]), 1)
            self.assertEqual(logins.main(["borrow", "codex", "b2", "--holder", "run-3"]), 1)
        self.assertEqual(out.getvalue(), "smith-live-1\n")
        self.assertEqual(err.getvalue(),
                         "fab logins: a chatgpt login is lent to a run; name its --path\n"
                         "fab logins: a codex login is lent to a run; name its --path\n")
        self.assertEqual(self.shelf.login("smith-live-1").path, ".local/state/smith-live")
        self.assertTrue(self.shelf.login("chatgpt-1").free)
        self.shelf.give_back("smith-live-1")

    def test_smith_live_capture_still_requires_a_source_path(self):
        with self.assertRaisesRegex(logins.Refused, "has no machine path; name its --path"):
            self.shelf.capture("b1", "smith-live", free=True)
        self.assertEqual(self.events(), [])

    def test_a_directory_login_is_lent_to_a_run_and_returned_whole(self):
        self.secret("b1", "qa/claude", directory=True)
        login = self.shelf.capture("b1", "claude-box", path="qa/claude", free=True)
        self.assertTrue(login.free)
        self.shelf.lend("claude-box-1", "b2", path="runs/r1/claude", holder="r1")
        lent = self.at("b2", "runs/r1/claude")
        self.assertEqual(stat.S_IMODE(lent.stat().st_mode), 0o700)
        self.assertEqual(self.shelf.login("claude-box-1").holder, "r1")
        (lent / ".credentials.json").write_bytes(b"refreshed by the run")
        (lent / "nested" / "more").write_bytes(b"the run's cache")
        self.shelf.give_back("claude-box-1")
        self.assertFalse(lent.exists())
        entry = self.home / "shelf/claude-box-1/login"
        self.assertEqual((entry / ".credentials.json").read_bytes(), b"refreshed by the run")
        self.assertEqual(sorted(p.name for p in (entry / "nested").iterdir()), ["more", "state"])
        self.assertEqual(sorted(p.name for p in entry.parent.iterdir()), ["login"])

    def test_check_asks_the_machine_or_lends_a_free_login_here_for_a_moment(self):
        self.secret("b1", ".codex/auth.json")
        self.shelf.capture("b1", "codex")
        self.assertEqual(self.shelf.check("codex-1")["used"], 40)
        self.assertEqual(self.accounts[-1][-1], "bash -lc 'fab logins account codex --validate'")
        login = self.shelf.login("codex-1")
        self.assertEqual((login.email, login.plan, login.used), ("a@example.invalid", "pro", 40))
        checked = log.read()[-1]
        self.assertEqual(checked["limit_names"], ["week"])
        self.assertEqual(checked["limit_used"], [40])
        self.assertEqual(checked["limit_resets"], [1793774975])
        self.assertNotIn("limits", checked)
        self.shelf.give_back("codex-1")
        self.shelf.check("codex-1")
        self.assertEqual(self.accounts[-1][-4:], ["codex", "--home", str(log.home() / "logins-check/codex-1"),
                                                  "--validate"])
        self.assertTrue(self.shelf.login("codex-1").free)
        self.assertFalse((log.home() / "logins-check/codex-1").exists())
        self.assertEqual(self.events()[-3:], ["login.lent", "login.returned", "login.checked"])
        self.secret("b1", "record")
        self.shelf.capture("b1", "chatgpt", path="record", free=True)
        with self.assertRaisesRegex(logins.Refused, "has no check"):
            self.shelf.check("chatgpt-1")

    def test_missing_names_the_machine_logins_each_role_needs(self):
        self.secret("b1", ".codex/auth.json")
        self.shelf.capture("b1", "codex")
        self.assertEqual(self.shelf.missing(), ["hel8: no claude login", "hel8: no codex login", "b1: no claude login",
                                                "b2: no claude login", "b2: no codex login"])

    def test_account_reads_the_products_own_answers(self):
        codex = logins.account("codex", home="/codex/home")
        self.assertEqual(codex, {"email": "/codex/home", "plan": "pro", "used": 72, "resets": 1793774975,
                                 "limits": [{"name": "5 h", "used": 17, "resets": 1793774000},
                                            {"name": "week", "used": 72, "resets": 1793774975}]})
        directory = self.home / "claude-dir"
        directory.mkdir()
        self.assertEqual(logins.account("claude", home=str(directory), validate=True),
                         {"email": "someone@example.invalid", "plan": "max", "limits": []})
        (directory / "expired").write_text("")
        self.assertEqual(logins.account("claude", home=str(directory), validate=True),
                         {"error": "Failed to authenticate"})
        self.assertEqual(logins.account("claude", home=str(directory)), {"error": "not logged in"})

    def test_codex_limits_all_buckets_and_duration_names(self):
        def window(minutes):
            return {"windowDurationMins": minutes, "usedPercent": 81, "resetsAt": 1793774975}

        buckets = {"z": {"limitId": "private model name", "primary": window(1440),
                          "secondary": window(90)},
                   "a": {"limitId": "codex", "primary": window(300), "secondary": window(10080)}}
        limits = logins._codex_limits({"rateLimitsByLimitId": buckets, "rateLimits": buckets["z"]})
        self.assertEqual([limit["name"] for limit in limits], ["5 h", "week", "other 1 d", "other 90 min"])
        self.assertTrue(all(limit["used"] == 81 and limit["resets"] == 1793774975 for limit in limits))
        for minutes, name in ((120, "2 h"), (2880, "2 d"), (1, "1 min"), (None, "?"), (0, "?")):
            with self.subTest(minutes=minutes):
                self.assertEqual(logins._codex_limits({"rateLimits": {"primary": window(minutes)}})[0]["name"],
                                 "other " + name)
        self.assertEqual(logins._codex_limits({}), [])

    def test_claude_usage_lines_names_and_utc_resets(self):
        now = datetime(2026, 11, 1, 12, tzinfo=timezone.utc).timestamp()
        limits = logins._claude_limits("""Current session: 85% used · resets 3:09pm (UTC)
Current week (all models): 12.5% used · resets Nov 4, 2am (UTC)
Current week (Sonnet): 3% used · resets Nov 5, 1:30pm
Current week (Fable): 99% used · resets Nov 4, 2am (UTC)
Current week (fable): 99% used
Other text with private@example.invalid
Current week [extra]: 0% used""", now)
        self.assertEqual([limit["name"] for limit in limits], ["5 h", "week", "week (Sonnet)", "week [extra]"])
        self.assertEqual([limit["used"] for limit in limits], [85, 12.5, 3, 0])
        self.assertEqual(limits[0]["resets"], datetime(2026, 11, 1, 15, 9, tzinfo=timezone.utc).timestamp())
        self.assertEqual(limits[1]["resets"], datetime(2026, 11, 4, 2, tzinfo=timezone.utc).timestamp())
        self.assertIsNone(limits[-1]["resets"])
        for value in ("bad", "0am", "13pm", "1:60pm", "Nov 31, 2am"):
            self.assertIsNone(logins._claude_reset(value, now))
        self.assertEqual(logins._claude_reset("10am", now),
                         datetime(2026, 11, 2, 10, tzinfo=timezone.utc).timestamp())
        self.assertEqual(logins._claude_reset("11am", now), now - 3600)
        self.assertEqual(logins._claude_reset("Jan 1, 12am", now),
                         datetime(2027, 1, 1, tzinfo=timezone.utc).timestamp())

    def test_claude_usage_requires_a_free_local_command_and_keeps_account_on_failure(self):
        answer = {"local_command": "usage", "num_turns": 0, "total_cost_usd": 0,
                  "result": "Current week (all models): 25% used"}
        runner = FakeRunner().on(["claude", "-p", "/usage"], Result(0, json.dumps(answer)))
        with patch.object(logins, "run", side_effect=runner) as command:
            found = logins.account("claude")
        self.assertEqual(found["limits"], [{"name": "week", "used": 25, "resets": None}])
        self.assertEqual(runner.argvs(), [["claude", "-p", "/usage", "--output-format", "json",
                                         "--no-session-persistence", "--strict-mcp-config", "--tools", "",
                                         "--model", "claude-haiku-5-5", "--settings", '{"disableAllHooks": true}']])
        self.assertEqual(command.call_args.kwargs["env"]["TZ"], "UTC")
        for replacement in ({"local_command": "model"}, {"num_turns": 1}, {"total_cost_usd": .01},
                            {"num_turns": None}, {"total_cost_usd": None}, {"num_turns": False}, {"is_error": True}):
            with self.subTest(replacement=replacement):
                runner = FakeRunner().on(["claude"], Result(0, json.dumps({**answer, **replacement})))
                with patch.object(logins, "run", side_effect=runner):
                    self.assertEqual(logins.account("claude"),
                                     {"email": "someone@example.invalid", "plan": "max", "limits": []})
        for result in (Result(1, json.dumps(answer)), Result(0, "invalid"), Result(0, "[]")):
            with patch.object(logins, "run", return_value=result):
                self.assertEqual(logins.account("claude")["limits"], [])
        with patch.object(logins, "run", side_effect=OSError("absent")):
            self.assertEqual(logins.account("claude")["limits"], [])

    def test_check_install_without_opening_shelf(self):
        runner = FakeRunner().on(["loginctl"], Result(0, "yes\n"))
        directory = self.home / "units"
        install = units.cli_install

        def isolated(command, files, **options):
            return install(command, files, sh=runner, directory=directory,
                           known=self.hosts, **options)

        with patch.dict(os.environ, {"FAB_HOST": "hel8"}), \
                patch.object(units, "cli_install", side_effect=isolated) as installing, \
                patch.object(logins, "Shelf") as shelf, \
                redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()) as err:
            self.assertEqual(logins.main(["check", "--install"]), 0)
        shelf.assert_not_called()
        installing.assert_called_once_with("logins check", units.logins_check_units(),
                                            primary="fab-logins-check.timer", restartable=False)
        files = units.logins_check_units()
        for name, text in files.items():
            self.assertEqual((directory / name).read_text(), text)
        self.assertEqual(out.getvalue().splitlines(),
                         [*(str(directory / name) for name in files), "enabled fab-logins-check.timer"])
        self.assertEqual(err.getvalue(), "")
        self.assertIn(["systemctl", "--user", "enable", "--now", "fab-logins-check.timer"], runner.argvs())
        self.assertFalse((self.home / "shelf").exists())

    def test_check_install_rejects_ids_and_all_and_normal_check_requires_one(self):
        for options in (["--install", "codex-1"], ["--install", "--all"],
                        [], ["--all", "codex-1"]):
            with self.subTest(options=options), redirect_stderr(io.StringIO()), \
                    patch.object(logins, "Shelf") as shelf, \
                    patch.object(units, "cli_install") as installing:
                with self.assertRaises(SystemExit) as error:
                    logins.main(["check", *options])
                self.assertEqual(error.exception.code, 2)
                shelf.assert_not_called()
                installing.assert_not_called()

    def test_check_ids_still_returns_failure_for_a_failed_account(self):
        with patch.object(logins, "Shelf", return_value=self.shelf), \
                patch.object(self.shelf, "check", side_effect=[{"limits": []}, {"error": "expired"}]) as check, \
                redirect_stdout(io.StringIO()) as out:
            self.assertEqual(logins.main(["check", "codex-1", "claude-1"]), 1)
        self.assertEqual([call.args[0] for call in check.call_args_list], ["codex-1", "claude-1"])
        self.assertEqual([json.loads(line) for line in out.getvalue().splitlines()],
                         [{"id": "codex-1", "limits": []}, {"id": "claude-1", "error": "expired"}])

    def test_check_install_rejects_invalid_home_before_opening_shelf(self):
        with patch.dict(os.environ, {"FAB_HOME": str(self.home / "bad%home")}), \
                patch.object(logins, "Shelf") as shelf, \
                patch.object(units, "cli_install") as installing, redirect_stderr(io.StringIO()) as err:
            self.assertEqual(logins.main(["check", "--install"]), 1)
        self.assertTrue(err.getvalue().startswith("fab logins check: invalid unit argument "))
        self.assertEqual(len(err.getvalue().splitlines()), 1)
        shelf.assert_not_called()
        installing.assert_not_called()

    def test_check_all_skips_refused_logins_and_continues_after_failed_checks(self):
        entries = [logins.Login(name, kind, "", "") for name, kind in
                   (("codex-1", "codex"), ("claude-1", "claude"), ("claude-box-1", "claude-box"),
                    ("github-1", "github"), ("chatgpt-1", "chatgpt"))]
        out = io.StringIO()
        with patch.object(logins, "Shelf", return_value=self.shelf), \
                patch.object(self.shelf, "logins", return_value={login.id: login for login in entries}), \
                patch.object(self.shelf, "check", side_effect=[logins.Refused("lent to a run"),
                                                              {"error": "expired"}, {"limits": []}]) as check, \
                redirect_stdout(out):
            self.assertEqual(logins.main(["check", "--all"]), 0)
        self.assertEqual([call.args[0] for call in check.call_args_list], ["codex-1", "claude-1", "claude-box-1"])
        self.assertEqual([json.loads(line) for line in out.getvalue().splitlines()],
                         [{"id": "codex-1", "skipped": True}, {"id": "claude-1", "error": "expired"},
                          {"id": "claude-box-1", "limits": []}])

    def test_check_refuses_a_runs_login_without_checking_the_account(self):
        login = logins.Login("codex-1", "codex", "", "", holder="run-1", host="b1", path="runs/run-1/auth.json")
        with patch.object(self.shelf, "login", return_value=login), \
                patch.object(self.shelf, "_account") as probe:
            with self.assertRaisesRegex(logins.Refused, "lent to run-1"):
                self.shelf.check(login.id)
        probe.assert_not_called()
        self.assertEqual(log.read(), [])

    def test_check_records_a_failed_account_with_empty_limit_columns(self):
        login = logins.Login("codex-1", "codex", "", "", holder="b1", host="b1", path=".codex/auth.json")
        with patch.object(self.shelf, "login", return_value=login), \
                patch.object(self.shelf, "_account", return_value={"error": "expired"}):
            self.assertEqual(self.shelf.check(login.id), {"error": "expired"})
        self.assertEqual(log.read()[-1]["error"], "expired")
        for key in ("limit_names", "limit_used", "limit_resets"):
            self.assertEqual(log.read()[-1][key], [])

    def test_fold_ignores_other_records_and_unknown_logins(self):
        folded = logins.fold([
            {"ts": "t0", "ev": "run.started", "id": "codex-1"},
            {"ts": "t1", "ev": "login.lent", "id": "codex-1", "holder": "b1", "host": "b1", "at": "p", "sha": "x"},
            {"ts": "t2", "ev": "login.added", "id": "codex-1", "kind": "codex", "origin": "b1:p", "sha": "x"},
            {"ts": "t3", "ev": "login.checked", "id": "codex-1", "email": "e", "plan": "pro", "used": 3},
        ])
        self.assertEqual(list(folded), ["codex-1"])
        self.assertTrue(folded["codex-1"].free)
        self.assertEqual((folded["codex-1"].used, folded["codex-1"].checked, folded["codex-1"].error), (3, "t3", None))
        folded = logins.fold([*map(dict, [
            {"ts": "t1", "ev": "login.added", "id": "claude-1", "kind": "claude", "origin": "b1:p", "sha": "x"},
            {"ts": "t2", "ev": "login.checked", "id": "claude-1", "error": "expired"}])])
        self.assertIn("error: expired", logins.table(folded.values())[1])

    def test_the_command_lists_and_refuses(self):
        self.secret("b1", ".codex/auth.json")
        out, err = io.StringIO(), io.StringIO()
        with patch.object(logins.fab_hosts, "load", return_value=self.hosts), \
                patch.object(logins.fab_hosts, "this_name", return_value="hel8"), redirect_stdout(out), \
                redirect_stderr(err):
            self.assertEqual(cli.main(["logins", "capture", "b1", "codex"]), 0)
            self.assertEqual(cli.main(["logins", "list"]), 0)
            self.assertEqual(cli.main(["logins", "return", "codex-7"]), 1)
            self.assertEqual(cli.main(["logins", "list", "--json"]), 0)
        lines = out.getvalue().splitlines()
        self.assertEqual(lines[0].split(), ["codex-1", "b1", "b1:.codex/auth.json"])
        self.assertEqual(lines[1].split()[:3], ["id", "holder", "where"])
        self.assertIn("hel8: no codex login", lines)
        self.assertEqual(json.loads(lines[-1])["holder"], "b1")
        self.assertEqual(err.getvalue(), "fab logins: no login codex-7\n")


if __name__ == "__main__":
    unittest.main()
