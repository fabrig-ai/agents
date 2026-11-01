import io
import json
import os
import secrets
import stat
import unittest
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from fab import cli, log, logins
from fab.hosts import Host
from fab.sh import Result, run
from fab.tests.support import tmp_home

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
        out = {"result": {"rateLimits": {"primary": {"usedPercent": 72, "resetsAt": 1793774975}}}}
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
            return Result(0, json.dumps({"email": "a@example.invalid", "plan": "pro", "used": 40}) + "\n")
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
        self.assertEqual(codex, {"email": "/codex/home", "plan": "pro", "used": 72, "resets": 1793774975})
        directory = self.home / "claude-dir"
        directory.mkdir()
        self.assertEqual(logins.account("claude", home=str(directory), validate=True),
                         {"email": "someone@example.invalid", "plan": "max"})
        (directory / "expired").write_text("")
        self.assertEqual(logins.account("claude", home=str(directory), validate=True),
                         {"error": "Failed to authenticate"})
        self.assertEqual(logins.account("claude", home=str(directory)), {"error": "not logged in"})

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
