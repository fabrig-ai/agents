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
            [sys.executable, "-I", str(self.checkout / "tools/session" / tool), *args],
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


class LaunchTests(Sandbox):
    def test_no_brief_refuses_without_commands_or_writes(self):
        result = self.command("start", "lead", "dm", "skein")
        self.assertEqual(result.returncode, 1)
        self.assertIn("missing brief", result.stderr)
        self.assertEqual(self.calls(), [])
        self.assertEqual(list(self.home.iterdir()), [])

    def test_live_refuses_before_setup_and_prints_dry_run_first(self):
        scratch = self.brief()
        self.env["FAKE_AGENTS"] = json.dumps([{"name": "lead/skein", "status": "busy", "id": "live-id"}])
        for extra in ((), ("--dry-run",)):
            with self.subTest(extra=extra):
                result = self.command("start", "lead", "dm", "skein", *extra)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("live session lead/skein (live-id)", result.stderr)
                if extra:
                    self.assertIn("cwd=", result.stdout)
                    self.assertIn("argv=", result.stdout)
                    self.assertIn("prompt:", result.stdout)
                self.assertEqual(sorted(path.name for path in scratch.iterdir()), ["brief.md"])
        self.assertTrue(all(call["argv"] == ["agents", "--json"] for call in self.calls()))

    def test_live_coordinator_and_warmup_refuse(self):
        for handle in ("dm", "ab"):
            for extra, key in (((), "coordinator_name"), (("--next",), "warmup_name")):
                name = lib.names(handle)[key]
                self.env["FAKE_AGENTS"] = json.dumps([{"name": name, "status": "idle"}])
                result = self.command("start", "coordinator", handle, *extra)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn(name, result.stderr)
        self.assertEqual(list(self.home.iterdir()), [])

    def test_only_stopped_and_completed_allow_reuse(self):
        self.brief()
        for status in ("stopped", "completed", "idle", "busy", "unknown"):
            self.env["FAKE_AGENTS"] = json.dumps([{"name": "lead/skein", "status": status}])
            result = self.command("start", "lead", "dm", "skein", "--dry-run")
            self.assertEqual(result.returncode, 0 if status in ("stopped", "completed") else 1, result.stderr)
        self.env["FAKE_AGENTS"] = '[{"name":"lead/skein","state":"working"}]'
        self.assertEqual(self.command("start", "lead", "dm", "skein", "--dry-run").returncode, 1)

    def test_scratch_created_once_and_clones_reused(self):
        scratch = self.brief()
        result = self.command("start", "lead", "dm", "skein")
        self.assertEqual(result.returncode, 0, result.stderr)
        for filename in ("common.md", "state.md"):
            self.assertEqual((scratch / filename).read_text(), "(empty)\n")
            (scratch / filename).write_text("Inherited content, keep it.\n")
        self.assertEqual(sorted(path.name for path in scratch.iterdir()), ["brief.md", "common.md", "repo", "state.md", "survey"])
        self.assertTrue(Path(lib.names("dm", "skein")["lead_start_dir"]).is_dir())
        result = self.command("start", "lead", "dm", "skein")
        self.assertEqual(result.returncode, 0, result.stderr)
        for filename in ("common.md", "state.md"):
            self.assertEqual((scratch / filename).read_text(), "Inherited content, keep it.\n")
        clones = [call for call in self.calls() if call["tool"] == "git"]
        self.assertEqual([call["argv"] for call in clones], [
            ["clone", "--reference", str(self.home / "src/fabrig/main"), "git@github.com:fabrig-ai/fabrig.git", str(scratch / directory)]
            for directory in ("repo", "survey")
        ])

    def test_dry_run_leaves_everything_unchanged(self):
        scratch = self.brief("ab", "jig")
        (scratch / "state.md").write_text("Updated 06:12Z\n")
        before = {str(path.relative_to(self.home)): path.read_bytes() if path.is_file() else None for path in self.home.rglob("*")}
        for args in (("lead", "ab", "jig"), ("coordinator", "dm"), ("coordinator", "ab", "--next")):
            result = self.command("start", *args, "--dry-run")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("argv=claude --bg --name", result.stdout)
            self.assertIn("prompt:", result.stdout)
        after = {str(path.relative_to(self.home)): path.read_bytes() if path.is_file() else None for path in self.home.rglob("*")}
        self.assertEqual(before, after)
        self.assertEqual([call["argv"] for call in self.calls()], [["agents", "--json"]] * 3)
        self.assertEqual(list(self.checkout.rglob("__pycache__")), [])

    def test_lead_argv_cwd_and_prompt(self):
        scratch = self.brief("ab", "smith")
        (scratch / "state.md").write_text("Updated 2026-10-29T06:12Z\n")
        result = self.command("start", "lead", "ab", "smith", "--model", "a model", "--effort", "medium")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "12345678-abcd-4321-8765-123456789abc")
        calls = self.calls()
        self.assertEqual(calls[0]["argv"], ["agents", "--json"])
        launch = calls[-1]
        self.assertEqual(launch["tool"], "claude")
        self.assertEqual(launch["argv"][:-1], ["--bg", "--name", "lead/ab/smith", "--model", "a model", "--effort", "medium"])
        self.assertEqual(launch["cwd"], lib.names("ab", "smith")["lead_start_dir"])
        self.assertEqual(launch["stdin"], "")
        prompt = launch["argv"][-1]
        for text in ("s/another-draft@hel8", "ready/ab-smith/<task>", "2026-10-29T06:12Z", "post wait lead/ab/smith", "session-context", "at exit 3", str(scratch)):
            self.assertIn(text, prompt)
        self.assertNotIn("$", prompt)

    def test_default_flags(self):
        self.brief()
        self.assertEqual(self.command("start", "lead", "dm", "skein").returncode, 0)
        launch = self.calls()[-1]
        self.assertEqual(launch["argv"][:-1], ["--bg", "--name", "lead/skein", "--model", "opus", "--effort", "high"])
        self.assertIn("written (unknown)", launch["argv"][-1])

    def test_fresh_coordinator_reads_own_clone_and_brief(self):
        value = lib.names("ab")
        result = self.command("start", "coordinator", "ab")
        self.assertEqual(result.returncode, 0, result.stderr)
        launch = self.calls()[-1]
        self.assertEqual(launch["cwd"], value["coordinator_start_dir"])
        self.assertEqual(launch["argv"][:-1], ["--bg", "--name", "s/another-draft", "--model", "opus", "--effort", "xhigh"])
        for text in (value["coordinator_handover"], value["coordinator_clone"], value["coordinator_brief"], "agents/coordinator.md", "post wait s/another-draft", "plan files it names"):
            self.assertIn(text, launch["argv"][-1])
        self.assertTrue(Path(value["coordinator_clone"]).is_dir())

    def test_warmup_uses_incumbent_handover_and_its_own_name(self):
        for handle in ("dm", "ab"):
            result = self.command("start", "coordinator", handle, "--next", "--model", "custom", "--effort", "high")
            self.assertEqual(result.returncode, 0, result.stderr)
            value = lib.names(handle)
            launch = self.calls()[-1]
            self.assertEqual(launch["argv"][:-1], ["--bg", "--name", value["warmup_name"], "--model", "custom", "--effort", "high"])
            self.assertEqual(launch["cwd"], value["coordinator_start_dir"])
            self.assertIn(value["coordinator_address"], launch["argv"][-1])
            self.assertIn(value["coordinator_handover"], launch["argv"][-1])
            self.assertIn("post wait " + value["warmup_name"], launch["argv"][-1])
        self.assertFalse(any(call["tool"] == "git" for call in self.calls()))

    def test_unknown_placeholder_fails_before_commands(self):
        self.brief()
        (self.checkout / "prompts/lead.md").write_text("Unexpected $missing")
        result = self.command("start", "lead", "dm", "skein")
        self.assertEqual(result.returncode, 2)
        self.assertIn("missing", result.stderr)
        self.assertEqual(self.calls(), [])

    def test_launch_report_formats_and_unparsed_output(self):
        self.brief()
        for output, expected in (
            ('{"session_id":"json-id"}', "json-id"),
            ('{"sessionId":"camel-id"}', "camel-id"),
            ("Agent ID: short-id", "short-id"),
            ("Started 12345678-abcd-4321-8765-123456789abc in background", "12345678-abcd-4321-8765-123456789abc"),
            ("An unfamiliar launch report", "An unfamiliar launch report"),
        ):
            with self.subTest(output=output):
                self.env["FAKE_LAUNCH"] = output
                result = self.command("start", "lead", "dm", "skein")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), expected)

    def test_bad_agents_output_or_failure_never_launches(self):
        self.brief()
        for output in ("invalid json", '{}', '["invalid session"]'):
            self.env["FAKE_AGENTS"] = output
            result = self.command("start", "lead", "dm", "skein")
            self.assertEqual(result.returncode, 2, result.stderr)
        self.env["FAKE_AGENTS"] = "[]"
        self.env["FAKE_AGENTS_EXIT"] = "1"
        result = self.command("start", "lead", "dm", "skein")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertTrue(all(call["argv"] == ["agents", "--json"] for call in self.calls()))

    def test_clone_and_launch_failures_are_errors(self):
        self.brief()
        self.env["FAKE_GIT_EXIT"] = "1"
        result = self.command("start", "lead", "dm", "skein")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertFalse(any(call["argv"][0] == "--bg" for call in self.calls()))
        del self.env["FAKE_GIT_EXIT"]
        self.env["FAKE_LAUNCH_EXIT"] = "1"
        self.env["FAKE_LAUNCH"] = "Launch failed"
        result = self.command("start", "lead", "dm", "skein")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("Launch failed", result.stderr)

    def test_usage_and_registry_errors(self):
        for args in ((), ("side",), ("lead", "dm"), ("lead", "dm", "../unsafe"), ("coordinator", "missing")):
            result = self.command("start", *args)
            self.assertEqual(result.returncode, 2, result.stderr)
        self.registry.write_text("not valid toml")
        self.assertEqual(self.command("start", "coordinator", "dm").returncode, 2)
        self.assertEqual(self.command("names", "dm").returncode, 2)
        self.assertEqual(self.calls(), [])


if __name__ == "__main__":
    unittest.main()
