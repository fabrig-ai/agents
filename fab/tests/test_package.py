import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from fab import cli, hosts
from fab.sh import Failed, Result, run, ssh
from fab.tests.support import FakeRunner
from fab.tests.wakes import BUILDER, DISPATCHER, HOSTS, here


class CliTest(unittest.TestCase):
    def test_usage_and_unknown(self):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            self.assertEqual(cli.main(["--help"]), 0)
            self.assertEqual(cli.main(["nonesuch"]), 2)
        self.assertIn("test", out.getvalue())
        self.assertIn("report", out.getvalue())
        self.assertIn("page", out.getvalue())
        self.assertIn("issues", out.getvalue())
        self.assertIn("qa", out.getvalue())
        self.assertIn("unknown command", err.getvalue())


class ImportTest(unittest.TestCase):
    def test_each_module_imports_first(self):
        # A cycle hides when the suite happens to import its modules in a working order.
        script = (
            "import importlib, pathlib, sys\n"
            "failed = []\n"
            "for path in sorted(pathlib.Path('fab').glob('*.py')):\n"
            "    if path.stem == '__main__':\n"
            "        continue\n"
            "    for name in [n for n in sys.modules if n == 'fab' or n.startswith('fab.')]:\n"
            "        del sys.modules[name]\n"
            "    try:\n"
            "        importlib.import_module('fab.' + path.stem)\n"
            "    except Exception as error:\n"
            "        failed.append(f'fab.{path.stem}: {error}')\n"
            "print('\\n'.join(failed))\n")
        root = str(Path(__file__).resolve().parents[2])
        result = run([sys.executable, "-I", "-B", "-c", f"import sys; sys.path.insert(0, {root!r})\n" + script],
                     cwd=root)
        self.assertEqual((result.code, result.out.strip()), (0, ""))


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
        found = hosts.load(local=Path(os.devnull))  # this machine's overrides left out
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

    def test_after_landing_needs_a_builder_and_one_of_its_slots(self):
        base = '[a]\nssh = "x"\ndisk_gb = 300\nplaces = 1\nslots = 7\nslot_bound_gb = 20\nbuilds = 1\n'
        for extra, bad in (('roles = ["builder", "after-landing"]\nafter_landing_slot = 7\n', False),
                           ('roles = ["builder", "after-landing"]\n', True),
                           ('roles = ["builder", "after-landing"]\nafter_landing_slot = 8\n', True),
                           ('roles = ["after-landing"]\nafter_landing_slot = 1\n', True)):
            with self.subTest(extra=extra):
                self.assertEqual(bool(hosts.problems(hosts.parse(base + extra)["a"])), bad)

    def test_a_gate_budgets_one_more_bound_for_the_queue(self):
        text = '[g]\nssh = "x"\nroles = ["gate", "builder"]\nslots = 2\nslot_bound_gb = 20\n'
        self.assertEqual(hosts.parse(text)["g"].budget_gb(), 60)


class OverrideTest(unittest.TestCase):
    TEXT = '[a]\nssh = "x"\nroles = ["gate", "builder"]\nplaces = 4\nbuilds = 4\n[b]\nssh = "y"\nroles = []\n'

    def test_overrides_replace_only_the_keys_they_name(self):
        found = hosts.parse(self.TEXT, '[a]\nplaces = 1\nroles = ["builder"]\n')
        self.assertEqual((found["a"].places, found["a"].builds, found["a"].roles), (1, 4, ("builder",)))
        self.assertEqual(found["a"].ssh, "x")
        self.assertEqual(found["b"], hosts.parse(self.TEXT)["b"])
        self.assertEqual(hosts.tables(self.TEXT, ""), hosts.tables(self.TEXT))

    def test_identity_unknown_hosts_and_bad_toml_are_refused(self):
        for local in ('[a]\nssh = "z"\n', '[a]\nhostname = "z"\n', '[c]\nplaces = 1\n',
                      'places = 1\n', '[a\n'):
            with self.subTest(local=local), self.assertRaisesRegex(ValueError, hosts.LOCAL):
                hosts.tables(self.TEXT, local)

    def test_load_applies_the_overrides_file_when_it_exists(self):
        with tempfile.TemporaryDirectory() as directory:
            path, local = Path(directory) / "hosts.toml", Path(directory) / hosts.LOCAL
            path.write_text(self.TEXT)
            self.assertEqual(hosts.load(path, local)["a"].places, 4)
            local.write_text("[a]\nplaces = 2\n")
            self.assertEqual(hosts.load(path, local)["a"].places, 2)
            with patch.object(hosts, "local_path", return_value=local):
                self.assertEqual(hosts.load(path)["a"].places, 2)

    def test_check_lists_overrides_and_refuses_a_bad_file(self):
        with tempfile.TemporaryDirectory() as directory:
            local = Path(directory) / hosts.LOCAL
            local.write_text("[hetzner8]\nbuilds = 1\n")
            out, err = io.StringIO(), io.StringIO()
            with patch.object(hosts, "local_path", return_value=local), \
                    redirect_stdout(out), redirect_stderr(err):
                self.assertEqual(hosts.main(["check"]), 0)
                local.write_text('[hetzner8]\nssh = "z"\n')
                self.assertEqual(hosts.main(["check"]), 1)
            self.assertIn("hetzner8: overridden in", out.getvalue())
            self.assertIn("cannot change ['ssh']", err.getvalue())


class ThisHostTest(unittest.TestCase):
    def test_given_name_wins_even_empty_or_unknown(self):
        for name in (DISPATCHER, "unknown", ""):
            with self.subTest(name=name), here(BUILDER):
                self.assertEqual(hosts.this_name({DISPATCHER: "hub-machine"}, name), name)

    def test_fab_host_wins_even_empty_or_unknown(self):
        for name in (BUILDER, "unknown", ""):
            with self.subTest(name=name), here(name), patch.object(hosts.socket, "gethostname") as hostname:
                self.assertEqual(hosts.this_name({DISPATCHER: "hub-machine"}), name)
                hostname.assert_not_called()

    def test_hostname_selects_first_matching_entry_or_empty_when_none(self):
        with here(None), patch.object(hosts.socket, "gethostname", return_value="hub-machine"):
            self.assertEqual(hosts.this_name({"first": "hub-machine", "second": "hub-machine"}), "first")
            self.assertEqual(hosts.this_name({"other": "elsewhere"}), "")
            self.assertEqual(hosts.this_name({}), "")

    def test_this_returns_the_host_or_none(self):
        self.assertIs(hosts.this(HOSTS, DISPATCHER), HOSTS[DISPATCHER])
        self.assertIsNone(hosts.this(HOSTS, "unknown"))
        self.assertIsNone(hosts.this(HOSTS, ""))
        with here(BUILDER):
            self.assertIs(hosts.this(HOSTS), HOSTS[BUILDER])
        with here(None), patch.object(hosts.socket, "gethostname", return_value="hub-machine"):
            self.assertIs(hosts.this(HOSTS), HOSTS[DISPATCHER])
