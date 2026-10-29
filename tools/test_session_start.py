#!/usr/bin/env python3
"""Isolated launcher checks: temporary HOME, fake claude and git only."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("session_lib", ROOT / "tools/session/session_lib.py")
lib = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lib)


class Sandbox(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.home = self.base / "home"
        self.home.mkdir()
        self.checkout = self.base / "checkout"
        for directory in ("tools/session", "prompts", "pipeline"):
            shutil.copytree(ROOT / directory, self.checkout / directory, ignore=shutil.ignore_patterns("__pycache__"))
        self.registry = self.checkout / "pipeline/coordinators.toml"
        self.registry.write_text('[dm]\nmailbox = "s/dynamic-memory"\ndefault = true\n\n[ab]\nmailbox = "s/another-draft"\n')
        self.log = self.base / "calls.jsonl"
        self.bin = self.base / "bin"
        self.bin.mkdir()
        fake = f"#!{sys.executable}\n" + '''import json, os, pathlib, sys
with open(os.environ["FAKE_LOG"], "a") as stream:
    stream.write(json.dumps({"tool": pathlib.Path(sys.argv[0]).name,
                             "argv": sys.argv[1:], "cwd": os.getcwd(),
                             "stdin": sys.stdin.read()}) + "\\n")
if pathlib.Path(sys.argv[0]).name == "claude":
    if sys.argv[1:] == ["agents", "--json"]:
        print(os.environ.get("FAKE_AGENTS", "[]"))
        sys.exit(int(os.environ.get("FAKE_AGENTS_EXIT", "0")))
    print(os.environ.get("FAKE_LAUNCH", "Started background agent. Session ID: 12345678-abcd-4321-8765-123456789abc"))
    sys.exit(int(os.environ.get("FAKE_LAUNCH_EXIT", "0")))
else:
    if os.environ.get("FAKE_GIT_EXIT"):
        sys.exit(int(os.environ["FAKE_GIT_EXIT"]))
    pathlib.Path(sys.argv[-1]).mkdir()
'''
        for command in ("claude", "git"):
            path = self.bin / command
            path.write_text(fake)
            path.chmod(0o755)
        self.env = {
            "HOME": str(self.home), "PATH": str(self.bin), "FAKE_LOG": str(self.log),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        self.addCleanup(patch.stopall)
        patch.dict(os.environ, {"HOME": str(self.home)}).start()
        patch.object(lib, "REGISTRY", self.registry).start()

    def command(self, tool, *args):
        return subprocess.run(
            [sys.executable, "-I", "-B", str(self.checkout / "tools/session" / tool), *args],
            env=self.env, cwd=self.checkout, input="", text=True, capture_output=True,
        )

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def brief(self, handle="dm", area="skein"):
        scratch = Path(lib.names(handle, area)["lead_scratch"])
        scratch.mkdir(parents=True)
        (scratch / "brief.md").write_text("Work on the named part.\n")
        return scratch


class NamesTests(Sandbox):
    def test_names_table(self):
        for handle, mailbox, key, lead, coord, handover, branch, warmup in (
            ("dm", "s/dynamic-memory", "skein", "lead/skein", "coordinator", "handover.md", "coord", "coord-next"),
            ("ab", "s/another-draft", "ab-skein", "lead/ab/skein", "coordinators/ab", "coordinators/ab/handover.md", "ab", "ab-next"),
        ):
            with self.subTest(handle=handle):
                value = lib.names(handle, "skein")
                supervise = self.home / "src/rust/tmp/supervise"
                self.assertEqual(value["lead_name"], lead)
                self.assertEqual(value["lead_mailbox"], lead)
                self.assertEqual(value["branch_key"], key)
                self.assertEqual(value["lead_scratch"], str(self.home / "src/fabrig/leads" / key))
                self.assertEqual(value["lead_start_dir"], str(supervise / "leads" / key))
                self.assertEqual(value["coordinator_start_dir"], str(supervise / coord))
                self.assertEqual(value["coordinator_handover"], str(supervise / handover))
                self.assertEqual(value["coordinator_branch_prefix"], branch)
                self.assertEqual(value["coordinator_mailbox"], mailbox)
                self.assertEqual(value["coordinator_address"], mailbox + "@hel8")
                self.assertEqual(value["warmup_name"], warmup)
                self.assertEqual(value["lead_mail_dir"], str(self.home / "src/rust/tmp/post" / lead.replace("/", "+") / "cur"))
        for area in lib.AREAS:
            self.assertEqual(lib.names("ab", area)["branch_key"], f"ab-{area}")

    def test_names_cli(self):
        for args in (("dm",), ("ab", "jig")):
            result = self.command("names", *args)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(dict(line.split("=", 1) for line in result.stdout.splitlines()), lib.names(*args))
        self.assertEqual(self.calls(), [])

    def test_registry_rejects_invalid_entries(self):
        cases = (
            '[dm]\nmailbox="s/a"\ndefault=true\n[ab]\nmailbox="s/b"\ndefault=true',
            '[Bad]\nmailbox="s/a"\ndefault=true',
            '[toolong99]\nmailbox="s/a"\ndefault=true',
            '[dm]\nmailbox="s/a"\ndefault=true\n[ab]\nmailbox="s/a"',
            '[dm]\nmailbox="s/a"\ndefault=true\n[dm]\nmailbox="s/b"',
            '[dm]\nmailbox="s/Bad"\ndefault=true',
            '[dm]\nmailbox="s/a"',
            '[dm]\nmailbox="s/a"\ndefault="yes"',
            '[dm]\nmailbox="s/a"\ndefault=true\nextra=1',
            '',
        )
        for contents in cases:
            with self.subTest(contents=contents):
                self.registry.write_text(contents)
                with self.assertRaises(ValueError):
                    lib.registry()

    def test_unknown_handle_and_area(self):
        for handle, area in (("missing", None), ("dm", "../unsafe")):
            with self.assertRaises(ValueError):
                lib.names(handle, area)

    def test_render_is_strict(self):
        template = self.base / "template.md"
        template.write_text("Hello $name; $$literal")
        self.assertEqual(lib.render(template, {"name": "lead/skein"}), "Hello lead/skein; $literal")
        with self.assertRaises(KeyError):
            lib.render(template, {})
        template.write_text("Broken $ placeholder")
        with self.assertRaises(ValueError):
            lib.render(template, {})

    def test_first_z_timestamp_or_unknown(self):
        state = self.base / "state.md"
        self.assertEqual(lib.state_time(state), "unknown")
        state.write_text("No time\nUpdated 2026-10-29T02:48:07Z\nLater 03:00Z\n")
        self.assertEqual(lib.state_time(state), "2026-10-29T02:48:07Z")
        state.write_text("Update 02:48Z\nLater 03:00Z")
        self.assertEqual(lib.state_time(state), "02:48Z")
        state.write_text("(empty)\n")
        self.assertEqual(lib.state_time(state), "unknown")


if __name__ == "__main__":
    unittest.main()
