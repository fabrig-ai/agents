"""Fleet regressions, using the shared disposable fixture without inherited cases."""
import argparse
import datetime as dt
import fcntl
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import tomllib
import unittest
from unittest.mock import patch
import test_fleet_sync as fixture
from test_fleet_sync import put, ROOT, FABRIG_TOOLS, HOST_COUNT


class FleetCases(fixture.FleetFixture):
    def test_invalid_global_host_and_expanded_env_no_writes(self):
        before = self.snapshot()
        original = (self.source / "fleet/env").read_text()
        for value in ("two words", "a\tb", "a\u2003b", "a'b", 'a"b', "a\\b", "$USER", "$HOME/$OTHER"):
            with self.subTest(value=value):
                put(self.source / "fleet/env", original + f"INVALID={value}\n")
                self.process("python3", "-I", "-B", self.source / "tools/fleet-sync", "--host", "hel8", expected=2)
                self.assertEqual(before, self.snapshot())
        put(self.source / "fleet/env", original)
        hosts = self.source / "fleet/hosts.toml"
        original_hosts = hosts.read_text()
        put(hosts, original_hosts.replace('HEAVY_BUILD_JOBS = "2"', 'HEAVY_BUILD_JOBS = "two words"'))
        self.process("python3", "-I", "-B", self.source / "tools/fleet-sync", "--host", "hel8", expected=2)
        put(hosts, original_hosts)
        self.assertEqual(before, self.snapshot())
        # Values safe before expansion can become unsafe through HOME.
        self.process("python3", "-I", "-B", self.source / "tools/fleet-sync", "--host", "hel8", expected=2,
                     env={**self.env, "HOME": str(self.home / "with space")})
        self.assertEqual(before, self.snapshot())

    def test_machine_env_strings_render_for_every_host(self):
        hosts = self.source / "fleet/hosts.toml"
        original = hosts.read_text()
        # An arbitrary key and an existing numeric key both accept strings.
        put(hosts, original.replace('machine_env = { ',
            'machine_env = { GENERIC_LITERAL = "Az09@._:/+-", ZERO = 0, ').replace(
                'KACHE_MAX_GB = 50', 'KACHE_MAX_GB = "50"'))
        with patch.dict(os.environ, self.env, clear=True):
            module, _ = self.runner()
            declarations = module.Declarations(self.source, self.home)
            for name, host in declarations.hosts.items():
                with self.subTest(host=name):
                    runner = module.Runner(argparse.Namespace(check=False, timer=False, resume_fd=None),
                                           declarations, name)
                    runner.render()
                    self.assertFalse([i for i in runner.state["items"] if i["result"] == "failed"])
                    content = (self.home / "src/rust/tmp/machine.env").read_text()
                    self.assertIn("GENERIC_LITERAL=Az09@._:/+-\nZERO=0\n", content)
                    self.assertIn(f"KACHE_MAX_GB={host['machine_env']['KACHE_MAX_GB']}\n", content)

    def test_hetzner6_qa_machine_env_strings_render_byte_for_byte(self):
        hosts = self.source / "fleet/hosts.toml"
        original = hosts.read_text()
        values = {
            "QA_WALK_KINDS": "forgejo=2:chatgpt,claude=2:claude",
            "QA_WALK_SLOTS": "forgejo=8+1,claude=4+3",
            "QA_SLOT_HOST": "hetzner6",
            "QA_CLAIM_OWNER": "s/qa",
            "QA_CLAIM_SSH": "free@204.168.210.29",
            "QA_STUCK_TO": "s/qa@hel8",
        }
        existing = tomllib.loads(original)["hosts"]["hetzner6"]["machine_env"]
        self.assertEqual({key: existing[key] for key in values}, values)
        with patch.dict(os.environ, self.env, clear=True):
            module, _ = self.runner()
            declarations = module.Declarations(self.source, self.home)
            runner = module.Runner(argparse.Namespace(check=False, timer=False, resume_fd=None),
                                   declarations, "hetzner6")
            runner.render()
        self.assertFalse([i for i in runner.state["items"] if i["result"] == "failed"])
        expected = "".join(f"{key}={value}\n" for key, value in existing.items())
        self.assertEqual((self.home / "src/rust/tmp/machine.env").read_bytes(), expected.encode())

    def test_env_value_behavior_matches_main(self):
        self.assertGreater(self.prepare_integer_machine_env(), 0)
        baseline = "f7334e8aa68c325076c5c0eda16f6ae6c0c217fa"
        script = self.source / "tools/fleet-sync"
        current = script.read_text()
        old = self.process("git", "-C", ROOT, "show", f"{baseline}:tools/fleet-sync").stdout
        results = []
        values = ("", "a=b,c;é\x7f", "$HOME/file", "two words", "a\tb", "a\nb", "a\rb",
                  'a"b', "a'b", "a\\b", "$USER", "$HOME/$OTHER", "a\x00b", 1, True)
        try:
            for source in (old, current):
                put(script, source, True)
                with patch.dict(os.environ, self.env, clear=True):
                    module, _ = self.runner()
                result = []
                for value in values:
                    try:
                        result.append(("ok", module.env_value(value, self.home)))
                    except ValueError as error:
                        result.append(("error", str(error)))
                results.append(result)
        finally:
            put(script, current, True)
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[1][0], ("ok", ""))
        self.assertEqual(results[1][1], ("ok", "a=b,c;é\x7f"))
        self.assertEqual(results[1][2], ("ok", str(self.home / "file")))

    def test_invalid_machine_env_no_writes(self):
        hosts = self.source / "fleet/hosts.toml"
        original = hosts.read_text()
        before = self.snapshot()
        strings = ("", "two words", "a\tb", "a\u2003b", "a'b", 'a"b', "a\\b",
                   "a\nb", "a\rb", "$HOME", "$USER")
        invalid = tuple(map(json.dumps, strings)) + ('true', 'false', '-1', '1.5',
                                                    '[]', '[1]', '{}', '{ x = 1 }')
        for name in tomllib.loads(original)["hosts"]:
            for value in invalid:
                with self.subTest(host=name, value=value):
                    section = f"[hosts.{name}]"
                    prefix, rest = original.split(section, 1)
                    rest = rest.replace('machine_env = { ',
                                        f'machine_env = {{ ARBITRARY_KEY = {value}, ', 1)
                    put(hosts, prefix + section + rest)
                    # Selecting hel8 still validates every other host first.
                    result = self.process("python3", "-I", "-B", self.source / "tools/fleet-sync",
                                          "--host", "hel8", expected=2)
                    self.assertIn(f"invalid machine_env for {name}: ARBITRARY_KEY", result.stderr)
                    self.assertEqual(before, self.snapshot())
        put(hosts, original.replace('PLAN_MIN_MEM_GB = 4', 'BAD-KEY = 4', 1))
        result = self.process("python3", "-I", "-B", self.source / "tools/fleet-sync",
                              "--host", "hel8", expected=2)
        self.assertIn("invalid machine_env for hel8: BAD-KEY", result.stderr)
        self.assertEqual(before, self.snapshot())

    def test_integer_machine_env_matches_main_runner_for_every_host(self):
        # Pin the main runner used when this schema expansion was branched.
        baseline = "f7334e8aa68c325076c5c0eda16f6ae6c0c217fa"
        hosts = tomllib.loads((ROOT / "fleet/hosts.toml").read_text())["hosts"]
        # Use today's declarations, including roles, while keeping the old
        # runner's integer-only schema. Future string settings are excluded
        # from both candidates rather than pinning the declaration bytes.
        lines = []
        for name, host in hosts.items():
            lines.append(f"[hosts.{name}]\n")
            for key, value in host.items():
                if key == "machine_env":
                    value = {k: v for k, v in value.items() if not isinstance(v, str)}
                if isinstance(value, dict):
                    literal = "{ " + ", ".join(f"{json.dumps(k)} = {json.dumps(v)}"
                                               for k, v in value.items()) + " }"
                else:
                    literal = json.dumps(value)
                lines.append(f"{key} = {literal}\n")
        put(self.source / "fleet/hosts.toml", "".join(lines))
        script = self.source / "tools/fleet-sync"
        current = script.read_text()
        old = self.process("git", "-C", ROOT, "show", f"{baseline}:tools/fleet-sync").stdout
        rendered = []
        try:
            for index, source in enumerate((old, current)):
                put(script, source, True)
                with patch.dict(os.environ, self.env, clear=True):
                    module, _ = self.runner()
                    declarations = module.Declarations(self.source, self.home)
                    result = {}
                    for name, host in declarations.hosts.items():
                        self.assertTrue(all(type(v) is int for v in host["machine_env"].values()))
                        home = self.directory / f"render-{index}-{name}"
                        home.mkdir()
                        with patch.dict(os.environ, {"HOME": str(home)}):
                            runner = module.Runner(argparse.Namespace(check=False, timer=False, resume_fd=None),
                                                   declarations, name)
                            runner.render()
                        self.assertFalse([i for i in runner.state["items"] if i["result"] == "failed"])
                        result[name] = (home / "src/rust/tmp/machine.env").read_bytes()
                    rendered.append(result)
        finally:
            put(script, current, True)
        self.assertEqual(set(rendered[0]), set(hosts))
        self.assertEqual(set(rendered[1]), set(hosts))
        self.assertEqual(rendered[0], rendered[1])

    def test_posix_path_idempotence_in_nested_shells(self):
        self.sync()
        path = self.home / ".config/fabrig/env.sh"
        self.process("sh", "-n", path)
        local, cargo = f"{self.home}/.local/bin", f"{self.home}/.cargo/bin"
        script = '. "$1"; . "$1"; exec /bin/sh -c \' . "$1"; printf "%s\\n" "$PATH"\' sh "$1"'
        for initial, expected in (("/usr/bin:/bin", f"{local}:{cargo}:/usr/bin:/bin"),
                                  (f"{local}:{cargo}:/bin", f"{local}:{cargo}:/bin"),
                                  (f"/bin:{cargo}", f"{local}:/bin:{cargo}"),
                                  (f"/bin:{local}", f"{cargo}:/bin:{local}")):
            with self.subTest(initial=initial):
                result = self.process("/bin/sh", "-c", script, "sh", path, env={**self.env, "PATH": initial})
                self.assertEqual(result.stdout.strip(), expected)

    def test_conflicts_ignore_path_but_warn_other_owned_keys(self):
        put(self.home / ".profile", 'export PATH="$HOME/extra:$PATH"\nexport DISABLE_AUTOUPDATER=0\n')
        put(self.home / ".config/plan/environment.sh", 'PATH=/wrong\n')
        put(self.home / ".config/environment.d/10-older.conf", 'PATH=/also-wrong\nDISABLE_AUTOUPDATER=0\n')
        state = self.sync()
        warnings = [i for i in state["items"] if i["item"].startswith("conflict:")]
        self.assertEqual(len(warnings), 2)
        self.assertTrue(all("DISABLE_AUTOUPDATER" in i["reason"] for i in warnings))


if __name__ == "__main__":
    unittest.main()
