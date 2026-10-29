#!/usr/bin/env python3
"""Isolated launcher checks: temporary HOME, fake claude and git only."""
import importlib.util
import json
import os
import shlex
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import time
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
elif pathlib.Path(sys.argv[0]).name == "session-context":
    assert sys.argv[1:] == ["--capabilities"]
    if os.environ.get("FAKE_GATING", "1") == "1":
        print("hook-gating")
        if os.environ.get("FAKE_DRIFT") == "1":
            print("role-drift")
    else:
        sys.exit(1)
else:
    if os.environ.get("FAKE_GIT_EXIT"):
        sys.exit(int(os.environ["FAKE_GIT_EXIT"]))
    pathlib.Path(sys.argv[-1]).mkdir()
'''
        for command in ("claude", "git", "session-context"):
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
        # Existing launch assertions exclude the separately tested capability probe.
        return [call for call in self.all_calls() if call["tool"] != "session-context"]

    def all_calls(self):
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
                self.assertEqual(value["coordinator_name_prefix"], f"coordinator/{handle}/")
                self.assertRegex(value["coordinator_name"], rf"^coordinator/{handle}/\d{{8}}T\d{{4}}Z$")
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
            for extra, key in (((), "coordinator_name"), (("--next",), "coordinator_name")):
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
        self.assertEqual(result.stdout.splitlines()[-1], "12345678-abcd-4321-8765-123456789abc")
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
        self.assertEqual(launch["argv"][:-1], ["--bg", "--name", "lead/skein", "--effort", "high"])
        self.assertIn("written (unknown)", launch["argv"][-1])

    def test_fresh_coordinator_reads_own_clone_and_brief(self):
        value = lib.names("ab")
        result = self.command("start", "coordinator", "ab")
        self.assertEqual(result.returncode, 0, result.stderr)
        launch = self.calls()[-1]
        self.assertEqual(launch["cwd"], value["coordinator_start_dir"])
        self.assertEqual(launch["argv"][:-1], ["--bg", "--name", value["coordinator_name"], "--effort", "xhigh"])
        for text in (value["coordinator_handover"], value["coordinator_clone"], value["coordinator_brief"], "agents/coordinator.md", "post wait s/another-draft", "plan files it names"):
            self.assertIn(text, launch["argv"][-1])
        self.assertTrue(Path(value["coordinator_clone"]).is_dir())

    def test_warmup_uses_incumbent_handover_and_its_own_name(self):
        for handle in ("dm", "ab"):
            result = self.command("start", "coordinator", handle, "--next", "--model", "custom", "--effort", "high")
            self.assertEqual(result.returncode, 0, result.stderr)
            value = lib.names(handle)
            launch = self.calls()[-1]
            self.assertEqual(launch["argv"][:-1], ["--bg", "--name", value["coordinator_name"], "--model", "custom", "--effort", "high"])
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
                self.assertEqual(result.stdout.splitlines()[-1], expected)

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


class OwnershipTests(Sandbox):
    def draft(self, handle, state, directory="draft"):
        records = Path(self.env.get("RECORDS_REPO", self.home / "src/fabrig/records"))
        path = records / "drafts" / directory / "draft.toml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f'coordinator = "{handle}"\nstate = "{state}"\n')
        return path

    def test_every_owned_name_class_is_silent_and_local(self):
        for name in ["director", "director/", "director/20261029T1200Z"] + [
            name for handle in ("dm", "ab") for name in [
                lib.names(handle)["coordinator_mailbox"], lib.names(handle)["warmup_name"],
                lib.names(handle)["coordinator_name_prefix"], lib.names(handle)["coordinator_name"],
                *(lib.names(handle, area)["lead_name"] for area in lib.AREAS),
            ]
        ]:
            with self.subTest(name=name):
                result = self.command("start", "owns", name)
                self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))
        self.assertEqual(self.all_calls(), [])
        self.assertEqual(list(self.home.iterdir()), [])

    def test_unknown_names_refuse_on_one_stderr_line(self):
        for name in ("o/dm-window-jig", "lead/unknown", "lead/ab/unknown", "coordinator/unknown/time", "coordinator/dm", "directorship", "director-next", "lead/jig@hel8", ""):
            result = self.command("start", "owns", name)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertEqual(result.stdout, "")
            self.assertEqual(len(result.stderr.splitlines()), 1)
            self.assertIn("not ours", result.stderr)
        self.assertEqual(self.all_calls(), [])

    def test_paused_pipeline_including_leads_and_mail_names(self):
        path = self.draft("dm", "paused")
        for name in ("lead/jig", "lead/skein", "s/dynamic-memory", "coord-next", "coordinator/dm/20261029T1200Z"):
            result = self.command("start", "owns", name)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertEqual(result.stdout, "")
            self.assertEqual(len(result.stderr.splitlines()), 1)
            self.assertIn("paused", result.stderr)
        for name in ("lead/ab/jig", "s/another-draft", "director", "director/next"):
            self.assertEqual(self.command("start", "owns", name).returncode, 0)
        path.write_text('coordinator="dm"\nstate="active"\n')
        self.assertEqual(self.command("start", "owns", "lead/jig").returncode, 0)
        self.assertEqual(self.all_calls(), [])

    def test_records_override_absent_drafts_and_any_matching_paused_draft(self):
        self.draft("dm", "paused")
        self.env["RECORDS_REPO"] = str(self.base / "alternate-records")
        self.assertEqual(self.command("start", "owns", "lead/jig").returncode, 0)
        self.draft("dm", "active", "first")
        self.draft("ab", "paused", "second")
        self.assertEqual(self.command("start", "owns", "lead/jig").returncode, 0)
        self.assertEqual(self.command("start", "owns", "lead/ab/jig").returncode, 1)
        self.draft("dm", "paused", "third")
        self.assertEqual(self.command("start", "owns", "lead/jig").returncode, 1)
        self.assertEqual(self.all_calls(), [])

    def test_bad_registry_or_draft_is_error_two_on_one_line(self):
        self.registry.write_text('bad [ toml')
        for name in ("lead/jig", "director", "unknown"):
            result = self.command("start", "owns", name)
            self.assertEqual((result.returncode, result.stdout), (2, ""))
            self.assertEqual(len(result.stderr.splitlines()), 1)
        self.registry.write_text('[dm]\nmailbox="s/dynamic-memory"\ndefault=true\n')
        self.draft("dm", "active").write_text('bad [ toml')
        result = self.command("start", "owns", "lead/jig")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(len(result.stderr.splitlines()), 1)
        self.assertEqual(self.all_calls(), [])

    def test_ownership_latency_below_100ms(self):
        durations = []
        for _ in range(3):
            begin = time.perf_counter()
            result = self.command("start", "owns", "lead/jig")
            durations.append(time.perf_counter() - begin)
            self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))
        self.assertLess(sorted(durations)[1], 0.1, durations)

    def test_stub_contract(self):
        self.assertTrue(os.access(ROOT / "tools/session/fixtures/start-owns-stub", os.X_OK))
        self.env["START_OWNS_ALLOW"] = "lead/jig director"
        self.env["START_OWNS_PAUSED"] = "lead/jig"
        for name, code, reason in (("director", 0, ""), ("lead/jig", 1, "paused"), ("unknown", 1, "not ours")):
            result = self.command("fixtures/start-owns-stub", name)
            self.assertEqual((result.returncode, result.stdout), (code, ""))
            if code:
                self.assertIn(reason, result.stderr)
                self.assertEqual(len(result.stderr.splitlines()), 1)
            else:
                self.assertEqual(result.stderr, "")
        result = self.command("fixtures/start-owns-stub")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(len(result.stderr.splitlines()), 1)


class WiringTests(Sandbox):
    def test_watched_paths_for_both_coordinators_and_roles(self):
        root = self.home / "src/fabrig/main"
        for handle, lead in (("dm", "skein"), ("ab", "ab-skein")):
            self.assertEqual(lib.watched("lead", handle, "skein"), [
                str(root / "AGENTS.md"), str(root / "agents/lead.md"), str(root / "agents/operations.md"),
                str(self.home / "src/fabrig/leads" / lead / "brief.md"),
            ])
            self.assertEqual(lib.watched("coordinator", handle, None), [
                str(root / "AGENTS.md"), str(root / "agents/coordinator.md"), str(root / "agents/operations.md"),
                str(root / "agents/lead.md"),
            ])
        for role, area in (("lead", None), ("unknown", None)):
            with self.assertRaises(ValueError):
                lib.watched(role, "dm", area)

    def test_role_drift_entries_and_gating_only_downgrade(self):
        values = lib.names("dm", "jig")
        Path(values["lead_start_dir"]).mkdir(parents=True)
        for flag in ("1", "0"):
            with self.subTest(drift=flag):
                self.env["FAKE_DRIFT"] = flag
                result = self.command("start", "wire", "dm")
                self.assertEqual(result.returncode, 0, result.stderr)
                for role, value in (("lead", values), ("coordinator", lib.names("dm"))):
                    directory = value["lead_start_dir" if role == "lead" else "coordinator_start_dir"]
                    hooks = json.loads((Path(directory) / ".claude/settings.json").read_text())["hooks"]
                    stop = hooks["Stop"][0]["hooks"][0]
                    argv = shlex.split(stop["command"])
                    if flag == "1":
                        self.assertEqual(set(hooks), {"Stop", "SessionStart", "UserPromptSubmit"})
                        self.assertEqual(hooks["Stop"], hooks["UserPromptSubmit"])
                        self.assertEqual(hooks["Stop"], hooks["SessionStart"])
                        self.assertNotIn("matcher", hooks["SessionStart"][0])
                        self.assertEqual([argv[i + 1] for i, token in enumerate(argv) if token == "--watch"],
                                         lib.watched(role, "dm", "jig" if role == "lead" else None))
                        self.assertEqual(stop["timeout"], 30)
                    else:
                        self.assertEqual(set(hooks), {"Stop", "SessionStart"})
                        self.assertNotIn("--watch", argv)
                        self.assertEqual(hooks["SessionStart"][0]["matcher"], "compact")

    def test_watched_paths_are_shell_quoted(self):
        with patch.dict(os.environ, {"HOME": str(self.home / "space's home;$literal")}):
            values = lib.names("ab", "temper")
            _, settings, _ = lib.hook_settings(values, "lead", {"hook-gating", "role-drift"})
            argv = shlex.split(settings["hooks"]["Stop"][0]["hooks"][0]["command"])
            self.assertEqual([argv[i + 1] for i, token in enumerate(argv) if token == "--watch"],
                             lib.watched("lead", "ab", "temper"))

    def test_drift_wire_dry_run_prints_hooks_and_creates_nothing(self):
        self.env["FAKE_DRIFT"] = "1"
        result = self.command("start", "wire", "dm", "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("UserPromptSubmit", result.stdout)
        self.assertIn("--watch", result.stdout)
        self.assertIn("agents/coordinator.md", result.stdout)
        self.assertNotIn('"matcher"', result.stdout)
        self.assertEqual(list(self.home.iterdir()), [])
        self.assertEqual(self.calls(), [])

    def test_owned_hooks_replaced_other_settings_preserved(self):
        values = lib.names("dm", "jig")
        path = Path(values["lead_start_dir"]) / ".claude/settings.json"
        path.parent.mkdir(parents=True)
        original = {"model": "opus[1m]", "permissions": {"allow": ["Read"]},
                    "hooks": {"Stop": [{"old": True}], "SessionStart": [{"old": True}],
                              "PreToolUse": [{"other": True}]}}
        path.write_text(json.dumps(original))
        result = self.command("start", "wire", "dm")
        self.assertEqual(result.returncode, 0, result.stderr)
        settings = json.loads(path.read_text())
        self.assertEqual(settings["model"], original["model"])
        self.assertEqual(settings["permissions"], original["permissions"])
        self.assertEqual(settings["hooks"]["PreToolUse"], original["hooks"]["PreToolUse"])
        self.assertEqual(len(settings["hooks"]["Stop"]), 1)
        self.assertNotIn("old", str(settings))
        stop = settings["hooks"]["Stop"][0]["hooks"][0]
        self.assertEqual(stop["timeout"], 30)
        self.assertEqual(shlex.split(stop["command"]), [
            "session-context", "--hook", "--role", "lead", "--name", "lead/jig",
            "--coordinator", "s/dynamic-memory@hel8", "--handover", values["coordinator_handover"], "--handle", "dm",
        ])
        self.assertEqual(settings["hooks"]["SessionStart"], [{"matcher": "compact", "hooks": [stop]}])
        self.assertEqual(self.calls(), [])
        self.assertEqual(len(self.all_calls()), 1)
        self.assertEqual(self.all_calls()[0]["argv"], ["--capabilities"])
        self.assertEqual([p.name for p in path.parent.iterdir()], ["settings.json"])
        self.assertFalse(Path(lib.names("dm", "skein")["lead_start_dir"]).exists())

    def test_shell_quoting_and_coordinator_gates(self):
        values = lib.names("dm")
        values["coordinator_handover"] = str(self.home / "a handover's $file; `literal`.md")
        _, settings, _ = lib.hook_settings(values, "coordinator", {"hook-gating"})
        command = settings["hooks"]["Stop"][0]["hooks"][0]["command"]
        argv = shlex.split(command)
        self.assertEqual(argv[argv.index("--handover") + 1], values["coordinator_handover"])
        self.assertEqual(argv[argv.index("--name-prefix") + 1], "coordinator/dm/")
        self.assertEqual(argv[argv.index("--name") + 1], "coord-next")
        _, settings, _ = lib.hook_settings(lib.names("ab"), "coordinator", {"hook-gating"})
        argv = shlex.split(settings["hooks"]["Stop"][0]["hooks"][0]["command"])
        self.assertNotIn("--name", argv)
        self.assertIn("coordinator/ab/", argv)

    def test_legacy_capabilities_only_plain_lead_stop_and_no_coordinator_hooks(self):
        self.env["FAKE_GATING"] = "0"
        for role, values in (("lead", lib.names("dm", "skein")), ("coordinator", lib.names("dm"))):
            path, _, _ = lib.hook_settings(values, role, {"hook-gating"})
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"keep": True, "hooks": {"Stop": ["old"], "SessionStart": ["old"], "Notification": ["keep"]}}))
        result = self.command("start", "wire", "dm")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("lacks hook-gating", result.stdout)
        self.assertIn("coordinator hooks skipped", result.stdout)
        for role, values in (("lead", lib.names("dm", "skein")), ("coordinator", lib.names("dm"))):
            path, _, _ = lib.hook_settings(values, role, {"hook-gating"})
            settings = json.loads(path.read_text())
            self.assertTrue(settings["keep"])
            self.assertEqual(settings["hooks"]["Notification"], ["keep"])
            self.assertNotIn("SessionStart", settings["hooks"])
            if role == "lead":
                self.assertEqual(settings["hooks"]["Stop"][0]["hooks"][0]["command"], "session-context --hook")
            else:
                self.assertNotIn("Stop", settings["hooks"])
        self.assertEqual([call["argv"] for call in self.all_calls()], [["--capabilities"]])

    def test_start_writes_hooks_with_both_capabilities(self):
        scratch = self.brief()
        for gating in ("1", "0"):
            self.env["FAKE_GATING"] = gating
            result = self.command("start", "lead", "dm", "skein")
            self.assertEqual(result.returncode, 0, result.stderr)
            path = Path(lib.names("dm", "skein")["lead_start_dir"]) / ".claude/settings.json"
            hooks = json.loads(path.read_text())["hooks"]
            command = hooks["Stop"][0]["hooks"][0]["command"]
            self.assertEqual("--name lead/skein" in command, gating == "1")
            self.assertEqual("SessionStart" in hooks, gating == "1")
        self.assertEqual((scratch / "brief.md").read_text(), "Work on the named part.\n")

    def test_wire_dry_run_creates_nothing_and_only_visits_existing_leads(self):
        for area in ("jig", "temper"):
            Path(lib.names("dm", area)["lead_start_dir"]).mkdir(parents=True)
        before = sorted(str(path) for path in self.home.rglob("*"))
        result = self.command("start", "wire", "dm", "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("coordinator/dm/", result.stdout)
        self.assertIn("coord-next", result.stdout)
        self.assertIn("lead/jig", result.stdout)
        self.assertIn("lead/temper", result.stdout)
        self.assertNotIn("lead/skein", result.stdout)
        self.assertEqual(before, sorted(str(path) for path in self.home.rglob("*")))
        self.assertEqual(self.calls(), [])
        self.assertEqual(len(self.all_calls()), 1)

    def test_unsupported_probe_or_missing_tool_falls_back(self):
        with patch.object(lib.subprocess, "run", side_effect=FileNotFoundError()):
            self.assertFalse(lib.session_capabilities())
        with patch.object(lib.subprocess, "run", side_effect=subprocess.TimeoutExpired("session-context", 10)):
            self.assertFalse(lib.session_capabilities())
        with patch.object(lib.subprocess, "run", return_value=subprocess.CompletedProcess([], 1, "hook-gating\n", "")):
            self.assertFalse(lib.session_capabilities())

    def test_invalid_existing_settings_fail_without_launching(self):
        self.brief()
        path = Path(lib.names("dm", "skein")["lead_start_dir"]) / ".claude/settings.json"
        path.parent.mkdir(parents=True)
        path.write_text('{"hooks": []}')
        result = self.command("start", "lead", "dm", "skein")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertFalse(any(call["argv"][0] == "--bg" for call in self.calls()))


class WarmupTests(Sandbox):
    def test_recent_live_warmup_refuses_but_old_or_finished_ones_allow(self):
        name = "coordinator/dm/20261028T1200Z"
        path = self.home / ".local/state/session-start/warmups.json"
        path.parent.mkdir(parents=True)
        for age, status, was_next, expected in (
            (60, "busy", True, 1), (7190, "idle", True, 1), (7300, "busy", True, 0),
            (60, "completed", True, 0), (60, "stopped", True, 0), (60, "busy", False, 0),
        ):
            with self.subTest(age=age, status=status, was_next=was_next):
                path.write_text(json.dumps({name: {"next": was_next, "started_at": time.time() - age}}))
                self.env["FAKE_AGENTS"] = json.dumps([{"name": name, "status": status}])
                result = self.command("start", "coordinator", "dm", "--next", "--dry-run")
                self.assertEqual(result.returncode, expected, result.stderr)
                if expected:
                    self.assertIn("recent live warm-up", result.stderr)

    def test_legacy_incumbent_does_not_prevent_start_and_success_is_recorded(self):
        self.env["FAKE_AGENTS"] = '[{"name":"coord-next","status":"busy"}]'
        result = self.command("start", "coordinator", "dm", "--next")
        self.assertEqual(result.returncode, 0, result.stderr)
        launch = self.calls()[-1]
        name = launch["argv"][2]
        self.assertTrue(name.startswith("coordinator/dm/"))
        self.assertIn(name, launch["argv"][-1])
        self.assertIn("warm-up post name is coord-next", launch["argv"][-1])
        state = json.loads((self.home / ".local/state/session-start/warmups.json").read_text())
        self.assertTrue(state[name]["next"])
        self.assertLess(abs(state[name]["started_at"] - time.time()), 30)
        self.assertEqual(state[name]["session_id"], "12345678-abcd-4321-8765-123456789abc")
        self.env["FAKE_AGENTS"] = json.dumps([{"name": name, "status": "busy"}])
        again = self.command("start", "coordinator", "dm", "--next")
        self.assertEqual(again.returncode, 1)
        self.assertIn("live session", again.stderr)

    def test_failed_launch_does_not_record_a_warmup(self):
        self.env["FAKE_LAUNCH_EXIT"] = "1"
        result = self.command("start", "coordinator", "dm", "--next")
        self.assertEqual(result.returncode, 2)
        self.assertFalse((self.home / ".local/state/session-start").exists())


class DirectorTests(Sandbox):
    def test_director_names_and_watched_paths(self):
        values = lib.names("director")
        start = self.home / "src/rust/tmp/supervise/director"
        self.assertEqual(values["director_mailbox"], "director")
        self.assertEqual(values["director_address"], "director@hel8")
        self.assertEqual(values["director_start_dir"], str(start))
        self.assertEqual(values["director_handover"], str(start / "handover.md"))
        self.assertEqual(values["director_state"], str(start / "state.md"))
        self.assertEqual(values["warmup_name"], "director-next")
        self.assertEqual(values["director_name_prefix"], "director/")
        self.assertEqual(values["director_legacy_name"], "director")
        self.assertRegex(values["director_name"], r"^director/\d{8}T\d{4}Z$")
        result = self.command("names", "director")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(dict(line.split("=", 1) for line in result.stdout.splitlines()), values)
        root = self.home / "src/rust/tmp/supervise/monorepo"
        self.assertEqual(lib.watched("director", "director"), [str(root / "director-role.md"), str(root / "director-records.md")])
        with self.assertRaises(ValueError):
            lib.names("director", "jig")

    def test_fresh_director_flags_prompt_and_cwd(self):
        result = self.command("start", "director")
        self.assertEqual(result.returncode, 0, result.stderr)
        launch = self.calls()[-1]
        values = lib.names("director")
        self.assertEqual(launch["argv"][:-1], ["--bg", "--name", values["director_name"], "--effort", "xhigh"])
        self.assertEqual(launch["cwd"], values["director_start_dir"])
        for text in (values["director_name"], "post wait director", "post send --as director", "director-role.md",
                     "director-records.md sections 1, 3 and 3b", "last two sections", "resume-backlog.md",
                     "read only, never write there", "agents/{coordinator,operations,ledger,backlog}.md",
                     "old fleet watch", "s/multi-coord", "session-context", "tools/session/start director --next"):
            self.assertIn(text, launch["argv"][-1])
        self.assertEqual(launch["stdin"], "")
        self.assertNotIn("$", launch["argv"][-1])
        self.assertFalse(any(call["tool"] == "git" for call in self.calls()))

    def test_director_warmup_can_coexist_with_incumbent_and_is_recorded(self):
        self.env["FAKE_AGENTS"] = '[{"name":"director","status":"busy","id":"722f3d5e"}]'
        result = self.command("start", "director", "--next", "--effort", "high")
        self.assertEqual(result.returncode, 0, result.stderr)
        launch = self.calls()[-1]
        name = lib.names("director")["director_name"]
        self.assertEqual(launch["argv"][:-1], ["--bg", "--name", name, "--effort", "high"])
        for text in (name, "warm-up post name is director-next", "post wait director-next", "post send --as director-next director@hel8", '"take over"', '"For my successor"', "director-role.md", "director-records.md", "post wait director"):
            self.assertIn(text, launch["argv"][-1])
        records = json.loads((self.home / ".local/state/session-start/warmups.json").read_text())
        self.assertTrue(records[name]["next"])
        self.assertEqual(records[name]["session_id"], "12345678-abcd-4321-8765-123456789abc")
        self.assertFalse(any(call["tool"] == "git" for call in self.calls()))

    def test_director_refuses_exact_live_name_and_legacy_incumbent(self):
        for name, extra in (("director", ()), (lib.names("director")["director_name"], ()),
                            (lib.names("director")["director_name"], ("--next",))):
            self.env["FAKE_AGENTS"] = json.dumps([{"name": name, "status": "idle", "id": "live-director"}])
            result = self.command("start", "director", *extra, "--dry-run")
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn("live session " + name, result.stderr)
            self.assertIn("prompt:", result.stdout)
        self.assertEqual(list(self.home.iterdir()), [])
        for status in ("stopped", "completed"):
            self.env["FAKE_AGENTS"] = json.dumps([{"name": "director", "status": status}])
            self.assertEqual(self.command("start", "director", "--dry-run").returncode, 0)

    def test_director_recent_warmup_guard_is_scoped_and_expires(self):
        name = "director/20261028T1200Z"
        path = self.home / ".local/state/session-start/warmups.json"
        path.parent.mkdir(parents=True)
        for age, status, expected in ((60, "busy", 1), (7300, "busy", 0), (60, "completed", 0)):
            path.write_text(json.dumps({name: {"next": True, "started_at": time.time() - age}}))
            self.env["FAKE_AGENTS"] = json.dumps([{"name": name, "status": status}])
            result = self.command("start", "director", "--next", "--dry-run")
            self.assertEqual(result.returncode, expected, result.stderr)
            if expected:
                self.assertIn("recent live warm-up " + name, result.stderr)
        other = "coordinator/dm/20261028T1200Z"
        path.write_text(json.dumps({other: {"next": True, "started_at": time.time()}}))
        self.env["FAKE_AGENTS"] = json.dumps([{"name": other, "status": "busy"}])
        self.assertEqual(self.command("start", "director", "--next", "--dry-run").returncode, 0)

    def test_director_wire_and_capability_fallbacks(self):
        values = lib.names("director")
        path = Path(values["director_start_dir"]) / ".claude/settings.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"keep": True, "hooks": {"Notification": ["keep"]}}))
        for gating, drift in (("1", "1"), ("1", "0"), ("0", "0")):
            self.env.update(FAKE_GATING=gating, FAKE_DRIFT=drift)
            result = self.command("start", "wire", "director")
            self.assertEqual(result.returncode, 0, result.stderr)
            settings = json.loads(path.read_text())
            self.assertTrue(settings["keep"])
            self.assertEqual(settings["hooks"]["Notification"], ["keep"])
            if gating == "0":
                self.assertEqual(settings["hooks"], {"Notification": ["keep"]})
                self.assertIn("director hooks skipped", result.stdout)
                continue
            argv = shlex.split(settings["hooks"]["Stop"][0]["hooks"][0]["command"])
            for option, expected in (("--role", "director"), ("--name", "director"), ("--name-prefix", "director/"), ("--handover", values["director_handover"])):
                self.assertEqual(argv[argv.index(option) + 1], expected)
            if drift == "1":
                self.assertEqual(settings["hooks"]["Stop"], settings["hooks"]["SessionStart"])
                self.assertEqual(settings["hooks"]["Stop"], settings["hooks"]["UserPromptSubmit"])
                self.assertEqual([argv[i + 1] for i, token in enumerate(argv) if token == "--watch"], lib.watched("director", "director"))
            else:
                self.assertNotIn("--watch", argv)
                self.assertNotIn("UserPromptSubmit", settings["hooks"])
                self.assertEqual(settings["hooks"]["SessionStart"][0]["matcher"], "compact")
        self.assertEqual(self.calls(), [])
        self.assertFalse(Path(lib.names("dm")["coordinator_start_dir"]).exists())

    def test_director_dry_runs_create_nothing(self):
        self.env["FAKE_DRIFT"] = "1"
        for args in (("director",), ("director", "--next"), ("wire", "director")):
            result = self.command("start", *args, "--dry-run")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("--name-prefix director/ --name director", result.stdout)
            self.assertIn("director-role.md", result.stdout)
            self.assertIn("director-records.md", result.stdout)
            self.assertEqual(list(self.home.iterdir()), [])
        self.assertTrue(all(call["argv"] == ["agents", "--json"] for call in self.calls()))


if __name__ == "__main__":
    unittest.main()
