"""Exhaustive process/compatibility sweeps; run in the periodic tier."""

from test_fleet_sync import *


class PeriodicFleetTest(FleetTest):
    def test_env_value_behavior_matches_main(self):
        # This comparison predates the separately staged quota asset. Keep
        # both candidates on that historical input schema (test_pquota covers it).
        (self.source / "fleet/bootstrap/pquota").unlink(missing_ok=True)
        self.assertGreater(self.prepare_integer_machine_env(), 0)
        baseline = "f7334e8aa68c325076c5c0eda16f6ae6c0c217fa"
        script = self.source / "tools/fleet-sync"
        current = script.read_text()
        old = historical_source(baseline)
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
        # This comparison predates the separately staged quota asset. Keep
        # both candidates on that historical input schema (test_pquota covers it).
        (self.source / "fleet/bootstrap/pquota").unlink(missing_ok=True)
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
        old = historical_source(baseline)
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

    def test_full_sha_pin_rolls_back_current(self):
        self.release_fixture()
        put(self.source / "fleet/env", (self.source / "fleet/env").read_text() + "NEW_VALUE=1\n")
        self.publish()
        self.component_sync("release", "render")
        put(self.home / ".config/fleet-sync/pin", self.sha + "\n")
        state = self.component_sync("release", "render")
        self.assertEqual(self.current().name, "agents-" + self.sha)
        self.assertEqual(state["agents_sha"], self.sha)
        self.assertNotIn("NEW_VALUE", (self.home / ".config/fabrig/env.sh").read_text())


def load_tests(loader, tests, pattern):
    cls = PeriodicFleetTest
    return unittest.TestSuite(cls(name) for name in cls.__dict__ if name.startswith("test_"))
