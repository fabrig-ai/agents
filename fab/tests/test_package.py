import io
import unittest
from contextlib import redirect_stderr, redirect_stdout

from fab import cli, hosts
from fab.sh import Failed, Result, run, ssh
from fab.tests.support import FakeRunner


class CliTest(unittest.TestCase):
    def test_usage_and_unknown(self):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            self.assertEqual(cli.main(["--help"]), 0)
            self.assertEqual(cli.main(["nonesuch"]), 2)
        self.assertIn("test", out.getvalue())
        self.assertIn("report", out.getvalue())
        self.assertIn("unknown command", err.getvalue())


class RunnerTest(unittest.TestCase):
    def test_real_runner_captures_and_checks(self):
        self.assertEqual(run(["printf", "hi"]).out, "hi")
        self.assertEqual(run(["false"]).code, 1)
        with self.assertRaises(Failed):
            run(["false"], check=True)
        self.assertEqual(run(["sleep", "5"], timeout=0.05).code, 124)

    def test_fake_runner_first_matching_rule(self):
        fake = FakeRunner().on(["git", "push"], Result(1, err="rejected")).on(["git"], Result(0, out="ok"))
        self.assertEqual(fake(["git", "push", "origin"]).code, 1)
        self.assertEqual(fake(["git", "status"]).out, "ok")
        self.assertEqual(fake(["ls"]).code, 0)
        with self.assertRaises(Failed):
            fake(["git", "push"], check=True)
        self.assertEqual(fake.argvs()[0], ["git", "push", "origin"])

    def test_ssh_runs_a_login_shell(self):
        argv = ssh("free@h", ["codex-run", "task", "a b"])
        self.assertEqual(argv[:3], ["ssh", "-o", "BatchMode=yes"])
        self.assertEqual(argv[-1], "bash -lc 'codex-run task '\"'\"'a b'\"'\"''")


class HostsTest(unittest.TestCase):
    def test_the_repository_hosts_fit_their_disks(self):
        found = hosts.load()
        self.assertIn("builder", found["hetzner6"].roles)
        self.assertEqual([p for h in found.values() for p in hosts.problems(h)], [])

    def test_an_overfull_builder_is_a_problem(self):
        text = """[b]
ssh = "x"
roles = ["builder"]
disk_gb = 100
places = 1
slots = 8
slot_bound_gb = 20
kache_gb = 50
headroom_gb = 10
builds = 1
"""
        (host,) = hosts.parse(text).values()
        self.assertEqual(host.budget_gb(), 220)
        self.assertIn("exceeds", hosts.problems(host)[0])
        with self.assertRaises(ValueError):
            hosts.parse('[b]\nssh = "x"\nroles = ["chef"]\n')
