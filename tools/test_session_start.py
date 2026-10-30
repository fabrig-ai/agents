#!/usr/bin/env python3
"""Isolated launcher checks: temporary HOME, fake claude and git only."""
import importlib.util
import json
import os
import resource
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
elif pathlib.Path(sys.argv[0]).name == "systemctl":
    if sys.argv[1:] == ["--user", "start", "--no-block", "reap.service"]:
        sys.exit(0)
    assert sys.argv[1:4] == ["--user", "is-active", "--quiet"]
    sys.exit(int(os.environ.get("FAKE_UNIT_EXIT", "3")))
elif pathlib.Path(sys.argv[0]).name == "claim":
    assert sys.argv[1:] == ["list"]
    print(os.environ.get("FAKE_CLAIMS", ""))
    sys.exit(int(os.environ.get("FAKE_CLAIMS_EXIT", "0")))
elif pathlib.Path(sys.argv[0]).name == "lease":
    assert sys.argv[1:] == ["list", "--json"]
    print(os.environ.get("FAKE_LEASES", "[]"))
    sys.exit(int(os.environ.get("FAKE_LEASES_EXIT", "0")))
elif pathlib.Path(sys.argv[0]).name == "reap":
    sys.exit(int(os.environ.get("FAKE_REAP_EXIT", "0")))
elif pathlib.Path(sys.argv[0]).name == "codex-run":
    print("codex-owner-lead-ab-skein")
    sys.exit(int(os.environ.get("FAKE_LAUNCH_EXIT", "0")))
else:
    if os.environ.get("FAKE_GIT_EXIT"):
        sys.exit(int(os.environ["FAKE_GIT_EXIT"]))
    pathlib.Path(sys.argv[-1]).mkdir()
'''
        for command in ("claude", "git", "session-context", "systemctl", "codex-run", "claim", "lease", "reap", "session-reap-hook"):
            path = self.bin / command
            path.write_text(fake)
            path.chmod(0o755)
        self.env = {
            "HOME": str(self.home), "PATH": str(self.bin), "FAKE_LOG": str(self.log),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        self.addCleanup(patch.stopall)
        patch.dict(os.environ, {"HOME": str(self.home), "PATH": str(self.bin)}).start()
        patch.object(lib, "REGISTRY", self.registry).start()
        # Parent expectations and child launches must share a minute even when
        # scheduling crosses a real clock boundary.
        self.now = lib.datetime.now(lib.UTC)
        now = self.now
        class Clock(lib.datetime):
            @classmethod
            def now(cls, tz=None):
                return now.astimezone(tz) if tz is not None else now.replace(tzinfo=None)
        patch.object(lib, "datetime", Clock).start()

    def command(self, tool, *args):
        command = [sys.executable, "-I", "-B", str(self.checkout / "tools/session" / tool), *args]
        driver = f"""import runpy, sys
from datetime import datetime
from pathlib import Path
script = sys.argv.pop(1)
sys.argv[0] = script
sys.path.insert(0, {str(self.checkout / "tools/session")!r})
import session_lib
now = datetime.fromisoformat({self.now.isoformat()!r})
class Clock(datetime):
    @classmethod
    def now(cls, tz=None):
        return now.astimezone(tz) if tz is not None else now.replace(tzinfo=None)
session_lib.datetime = Clock
import session_retire
session_retire.datetime = Clock
"""
        if tool == "start" and args[:1] in (("owns",), ("names",)):
            # Enforce locality inside the child, including calls outside fake PATH.
            driver += """def local_only(event, args):
    if (event.startswith(('subprocess.', 'socket.', 'os.exec', 'os.spawn'))
            or event in ('os.system', 'os.posix_spawn', 'os.fork', 'os.forkpty')):
        raise AssertionError('local command attempted ' + event)
sys.addaudithook(local_only)
"""
        driver += "runpy.run_path(script, run_name='__main__')\n"
        command = command[:3] + ["-c", driver] + command[3:]
        return subprocess.run(
            command,
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
                scratch = self.home / "src/fabrig/coord" / handle
                clone = self.home / "src/fabrig/coord/next2" if handle == "dm" else scratch / "repo"
                self.assertEqual(value["coordinator_clone"], str(clone))
                self.assertEqual(value["coordinator_brief"], str(scratch / "brief.md"))
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
            '[dm]\nmailbox="s/a"\ndefault=true\nlead_kind="other"',
            '[dm]\nmailbox="s/a"\ndefault=true\nlead_kind=true',
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


class CodexLeadTests(Sandbox):
    def setUp(self):
        super().setUp()
        self.registry.write_text(self.registry.read_text() + 'lead_kind = "codex"\n')

    def test_registry_kind_defaults_and_owner_paths(self):
        self.assertEqual(lib.names('dm', 'jig')['lead_kind'], 'claude')
        values = lib.names('ab', 'jig')
        self.assertEqual(values['lead_kind'], 'codex')
        self.assertEqual(values['lead_unit'], 'codex-owner-lead-ab-jig')
        with patch.dict(os.environ, DEV_ROOT=str(self.base / 'dev')):
            self.assertEqual(lib.names('ab', 'jig')['lead_owner_state'], str(self.base / 'dev/tmp/owners/jig/codex'))

    def test_systemd_string_escaping(self):
        for name, escaped in (('lead/u/jig', 'lead-u-jig'), ('a-b/c_d:e.f', r'a\x2db-c_d:e.f'),
                              ('.hello', r'\x2ehello'), ('a b/é', r'a\x20b-\xc3\xa9'),
                              (r'a\b', r'a\x5cb')):
            self.assertEqual(lib.systemd_escape(name), escaped)


    def test_owner_launch_preserves_state_and_prepares_clones_without_hooks(self):
        scratch = self.brief('ab')
        (scratch / 'state.md').write_text('inherited\n')
        result = self.command('start', 'lead', 'ab', 'skein')
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.all_calls()
        self.assertEqual([c['tool'] for c in calls], ['systemctl', 'git', 'git', 'codex-run'])
        self.assertEqual(calls[0]['argv'], ['--user', 'is-active', '--quiet', 'codex-owner-lead-ab-skein'])
        self.assertEqual(calls[-1]['argv'], ['owner', '--effort', 'high', 'lead/ab/skein', str(scratch / 'brief.md')])
        self.assertEqual((scratch / 'state.md').read_text(), 'inherited\n')
        self.assertEqual((scratch / 'common.md').read_text(), '(empty)\n')
        self.assertTrue((scratch / 'repo').is_dir())
        self.assertTrue((scratch / 'survey').is_dir())
        self.assertFalse(Path(lib.names('ab', 'skein')['lead_start_dir']).exists())


    def test_active_unit_refuses_even_dry_run(self):
        scratch = self.brief('ab')
        self.env['FAKE_UNIT_EXIT'] = '0'
        for options in ((), ('--dry-run',)):
            result = self.command('start', 'lead', 'ab', 'skein', *options)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn('active unit codex-owner-lead-ab-skein', result.stderr)
        self.assertTrue(all(c['tool'] == 'systemctl' for c in self.all_calls()))
        self.assertEqual([p.name for p in scratch.iterdir()], ['brief.md'])


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


    def test_fresh_coordinator_reads_own_clone_and_brief(self):
        for handle in ("dm", "ab"):
            with self.subTest(handle=handle):
                value = lib.names(handle)
                result = self.command("start", "coordinator", handle)
                self.assertEqual(result.returncode, 0, result.stderr)
                launch = self.calls()[-1]
                self.assertEqual(launch["cwd"], value["coordinator_start_dir"])
                self.assertEqual(launch["argv"][:-1], ["--bg", "--name", value["coordinator_name"], "--effort", "xhigh"])
                for text in (value["coordinator_handover"], value["coordinator_clone"], value["coordinator_brief"], "agents/coordinator.md", "post wait " + value["coordinator_mailbox"], "plan files it names"):
                    self.assertIn(text, launch["argv"][-1])
                self.assertTrue(Path(value["coordinator_clone"]).is_dir())
                self.assertTrue(Path(value["coordinator_brief"]).parent.is_dir())
                self.assertFalse((Path(value["coordinator_start_dir"]) / "repo").exists())


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
            self.assertIn(value["coordinator_clone"], launch["argv"][-1])
            self.assertIn(value["coordinator_brief"], launch["argv"][-1])
            self.assertIn("post wait " + value["warmup_name"], launch["argv"][-1])
        self.assertFalse(any(call["tool"] == "git" for call in self.calls()))


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

    def test_owned_name_classes_in_process(self):
        for name in ["director", "director/", "director/20261029T1200Z"] + [
            name for handle in ("dm", "ab") for name in [
                lib.names(handle)["coordinator_mailbox"], lib.names(handle)["warmup_name"],
                lib.names(handle)["coordinator_name_prefix"], lib.names(handle)["coordinator_name"],
                *(lib.names(handle, area)["lead_name"] for area in lib.AREAS),
            ]
        ]:
            with self.subTest(name=name):
                self.assertEqual(lib.owns(name), (True, ""))
        self.assertEqual(self.all_calls(), [])
        self.assertEqual(list(self.home.iterdir()), [])


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

    def test_ownership_local_cpu_budget(self):
        durations = []
        for _ in range(3):
            begin = resource.getrusage(resource.RUSAGE_CHILDREN)
            result = self.command("start", "owns", "lead/jig")
            end = resource.getrusage(resource.RUSAGE_CHILDREN)
            durations.append(end.ru_utime + end.ru_stime - begin.ru_utime - begin.ru_stime)
            self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))
        # Idle child CPU <= 59 ms; 4x rounded up to the 500 ms minimum.
        self.assertLess(max(durations), 0.5, durations)
        self.assertEqual(self.all_calls(), [])


class InventoryTests(Sandbox):
    def setUp(self):
        super().setUp()
        self.registry.write_text((ROOT / "pipeline/coordinators.toml").read_text())

    def test_inventory_registry_identities_and_supervisors(self):
        result = self.command("start", "names", "--json")
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        rows = json.loads(result.stdout)
        self.assertEqual(len(rows), 23)
        by_mailbox = {row["mailbox"]: row for row in rows}
        self.assertEqual(len(by_mailbox), len(rows))
        for handle, mailbox, default in (("dm", "s/dynamic-memory", True), ("q", "s/qa", False), ("u", "s/upgrades", False), ("lf", "s/ladder", False)):
            coordinator = by_mailbox[mailbox]
            self.assertEqual(coordinator["role"], "coordinator")
            self.assertEqual(coordinator["handle"], handle)
            self.assertEqual(coordinator["supervisor"], "director")
            self.assertEqual(coordinator["name_prefix"], f"coordinator/{handle}/")
            self.assertEqual(coordinator["warmup_name"], "coord-next" if default else f"{handle}-next")
            self.assertEqual(coordinator["legacy_names"], ["coord-next"] if default else [])
            self.assertEqual(coordinator["aliases"], [coordinator["warmup_name"]])
            self.assertFalse(coordinator["paused"])
            start = "coordinator" if default else f"coordinators/{handle}"
            self.assertEqual(coordinator["start_dir"], str(self.home / "src/rust/tmp/supervise" / start))
            for area in lib.AREAS:
                name = f"lead/{area}" if default else f"lead/{handle}/{area}"
                lead = by_mailbox[name]
                key = area if default else f"{handle}-{area}"
                self.assertEqual(lead["name"], name)
                self.assertEqual(lead["role"], "lead")
                self.assertEqual(lead["handle"], handle)
                self.assertEqual(lead["area"], area)
                self.assertEqual(lead["branch_key"], key)
                self.assertEqual(lead["supervisor"], mailbox)
                self.assertEqual(lead["coordinator_mailbox"], mailbox)
                self.assertEqual(lead["scratch"], str(self.home / "src/fabrig/leads" / key))
                self.assertEqual(lead["kind"], "claude")
                self.assertEqual(lead["start_dir"], str(self.home / "src/rust/tmp/supervise/leads" / key))
                self.assertNotIn("unit", lead)
                self.assertNotIn("owner_state", lead)
                self.assertFalse(lead["paused"])
        director = by_mailbox["director"]
        self.assertEqual(director["name_prefix"], "director/")
        self.assertEqual(director["legacy_names"], ["director"])
        self.assertIsNone(director["supervisor"])
        self.assertFalse(director["paused"])
        for name in ("ops", "s/deploy"):
            self.assertEqual(by_mailbox[name]["supervisor"], "director")
            self.assertTrue(by_mailbox[name]["always_watched"])
            self.assertIn("always watched", by_mailbox[name]["note"])
        self.assertEqual(self.all_calls(), [])
        self.assertEqual(list(self.home.iterdir()), [])

    def test_inventory_matches_unflagged_watch_invocation(self):
        flagged = self.command("start", "names", "--json")
        unflagged = self.command("start", "names")
        self.assertEqual(unflagged.returncode, 0, unflagged.stderr)
        self.assertEqual(json.loads(flagged.stdout), json.loads(unflagged.stdout))

    def test_inventory_pause_state_uses_ownership_records(self):
        records = self.base / "records"
        self.env["RECORDS_REPO"] = str(records)
        for name, handle, state in (("qa", "q", "paused"), ("old-qa", "q", "active"), ("upgrades", "u", "active")):
            path = records / "drafts" / name / "draft.toml"
            path.parent.mkdir(parents=True)
            path.write_text(f'coordinator="{handle}"\nstate="{state}"\n')
        result = self.command("start", "names", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        for row in json.loads(result.stdout):
            if "handle" in row:
                self.assertEqual(row["paused"], row["handle"] == "q")
        self.assertEqual(self.command("start", "owns", "lead/q/jig").returncode, 1)
        self.assertEqual(self.command("start", "owns", "s/upgrades").returncode, 0)
        # Missing overridden records means unpaused, even if the default has paused data.
        default = self.home / "src/fabrig/records/drafts/green/draft.toml"
        default.parent.mkdir(parents=True)
        default.write_text('coordinator="dm"\nstate="paused"\n')
        self.env["RECORDS_REPO"] = str(self.base / "missing")
        rows = json.loads(self.command("start", "names", "--json").stdout)
        self.assertFalse(any(row.get("paused", False) for row in rows))
        self.assertEqual(self.all_calls(), [])

    def test_inventory_local_cpu_budget(self):
        durations = []
        for _ in range(3):
            begin = resource.getrusage(resource.RUSAGE_CHILDREN)
            result = self.command("start", "names", "--json")
            end = resource.getrusage(resource.RUSAGE_CHILDREN)
            durations.append(end.ru_utime + end.ru_stime - begin.ru_utime - begin.ru_stime)
            self.assertEqual(result.returncode, 0, result.stderr)
        # Idle child CPU <= 74 ms; 4x rounded up to the 500 ms minimum.
        self.assertLess(max(durations), 0.5, durations)
        self.assertEqual(self.all_calls(), [])

    def test_inventory_bad_registry_fails_without_partial_json(self):
        self.registry.write_text("invalid [ toml")
        result = self.command("start", "names", "--json")
        self.assertEqual((result.returncode, result.stdout), (2, ""))
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


    def test_watched_paths_are_shell_quoted(self):
        with patch.dict(os.environ, {"HOME": str(self.home / "space's home;$literal")}):
            values = lib.names("ab", "temper")
            _, settings, _ = lib.hook_settings(values, "lead", {"hook-gating", "role-drift"})
            argv = shlex.split(settings["hooks"]["Stop"][0]["hooks"][0]["command"])
            self.assertEqual([argv[i + 1] for i, token in enumerate(argv) if token == "--watch"],
                             lib.watched("lead", "ab", "temper"))


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
            self.assertIn("SessionStart", hooks)
        self.assertEqual((scratch / "brief.md").read_text(), "Work on the named part.\n")


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


class ReapSettingsTests(Sandbox):
    def test_all_roles_capabilities_foreign_groups_and_repeat_wire(self):
        foreign = {"type": "command", "command": "foreign-command"}
        for role, values in (("lead", lib.names("dm", "jig")),
                             ("coordinator", lib.names("ab")), ("director", lib.names("director"))):
            for capabilities in (set(), {"hook-gating"}, {"hook-gating", "role-drift"}):
                with self.subTest(role=role, capabilities=capabilities):
                    path = Path(values[f"{role}_start_dir"]) / ".claude/settings.json"
                    path.parent.mkdir(parents=True, exist_ok=True)
                    original = [{"matcher": "resume", "hooks": [foreign, {"type": "command", "command": "session-context --hook"}]},
                                {"hooks": [foreign.copy()]}]
                    path.write_text(json.dumps({"hooks": {event: original for event in (
                        "Stop", "SessionStart", "SessionEnd", "UserPromptSubmit")}}))
                    path, settings, _ = lib.hook_settings(values, role, capabilities)
                    for event, groups in settings["hooks"].items():
                        self.assertEqual(groups[:2], [{"matcher": "resume", "hooks": [foreign]}, {"hooks": [foreign]}])
                        reapers = [group for group in groups if any("reap-hook" in hook["command"] for hook in group["hooks"])]
                        self.assertEqual(len(reapers), int(event in ("SessionStart", "SessionEnd")))
                        if reapers:
                            self.assertNotIn("matcher", reapers[0])
                            self.assertEqual(shlex.split(reapers[0]["hooks"][0]["command"]), ["session-reap-hook", values[f"{role}_name"]])
                    lib.atomic_json(path, settings)
                    self.assertEqual(lib.hook_settings(values, role, capabilities)[1], settings)

    def test_missing_or_nonexecutable_hook_omits_both_and_migrates_owned_entries(self):
        executable = self.bin / "session-reap-hook"
        foreign = {"type": "command", "command": "foreign-hook"}
        for available in (False, True):
            executable.chmod(0o755 if available else 0o644)
            for role, values in (("lead", lib.names("dm", "jig")),
                                 ("coordinator", lib.names("ab")), ("director", lib.names("director"))):
                for capabilities in (set(), {"hook-gating"}, {"hook-gating", "role-drift"}):
                    with self.subTest(available=available, role=role, capabilities=capabilities):
                        path = Path(values[f"{role}_start_dir"]) / ".claude/settings.json"
                        path.parent.mkdir(parents=True, exist_ok=True)
                        old = [{"hooks": [foreign,
                            {"type": "command", "command": "/obsolete/release/tools/session/reap-hook old"},
                            {"type": "command", "command": "session-reap-hook old"}]}]
                        path.write_text(json.dumps({"hooks": {event: old for event in ("SessionStart", "SessionEnd")}}))
                        _, settings, reason = lib.hook_settings(values, role, capabilities)
                        for event in ("SessionStart", "SessionEnd"):
                            groups = settings["hooks"][event]
                            self.assertEqual(groups[0], {"hooks": [foreign]})
                            commands = [hook["command"] for group in groups for hook in group["hooks"]]
                            self.assertNotIn("/obsolete/release/tools/session/reap-hook old", commands)
                            self.assertNotIn("session-reap-hook old", commands)
                            self.assertEqual(sum(command.startswith("session-reap-hook ") for command in commands), int(available))
                        self.assertEqual("session-reap-hook absent from PATH" in reason, not available)
        executable.unlink()
        for role, values in (("lead", lib.names("dm", "jig")),
                             ("coordinator", lib.names("ab")), ("director", lib.names("director"))):
            path = Path(values[f"{role}_start_dir"]) / ".claude/settings.json"
            path.unlink()
            _, settings, _ = lib.hook_settings(values, role, set())
            self.assertNotIn("SessionStart", settings.get("hooks", {}))
            self.assertNotIn("SessionEnd", settings.get("hooks", {}))

    def test_wire_omits_missing_hook_until_installed_and_shows_path_name(self):
        executable = self.bin / "session-reap-hook"
        executable.unlink()
        result = self.command("start", "wire", "director", "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("session-reap-hook absent from PATH", result.stdout)
        self.assertNotIn('"SessionEnd"', result.stdout)
        executable.symlink_to(self.checkout / "tools/session/reap-hook")
        result = self.command("start", "wire", "director", "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('"command": "session-reap-hook director/', result.stdout)
        self.assertIn('"SessionEnd"', result.stdout)
        self.assertNotIn(str(self.checkout / "tools/session/reap-hook"), result.stdout)


class RetireTests(Sandbox):
    def retire(self, role="lead", handle="ab", area="jig", yes=False):
        args = ["retire", role, handle]
        if role == "lead":
            args.append(area)
        if yes:
            args.append("--yes")
        return self.command("start", *args)

    def test_lead_dry_run_and_yes_keep_paths_and_drop_only_role_warmups(self):
        values = lib.names("ab", "jig")
        scratch = self.brief("ab", "jig")
        Path(values["lead_start_dir"]).mkdir(parents=True)
        lib.record_warmup(values["lead_name"], "id", 123)
        lib.record_warmup("coordinator/ab/old", "other", 124)
        before = sorted(str(path) for path in self.home.rglob("*"))
        result = self.retire()
        self.assertEqual(result.returncode, 0, result.stderr)
        for key in ("lead_scratch", "lead_start_dir"):
            self.assertIn("path=" + values[key], result.stdout)
        self.assertNotIn("refused:", result.stdout)
        self.assertFalse(any(call["tool"] in ("reap", "systemctl") for call in self.calls()))
        self.assertEqual(before, sorted(str(path) for path in self.home.rglob("*")))
        result = self.retire(yes=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        calls = [call for call in self.calls() if call["tool"] in ("reap", "systemctl")]
        identifier = f"retire-lead+ab+jig-{self.now:%Y%m%dT%H%M%S%fZ}"
        self.assertEqual(calls[0]["argv"], ["record", "start", "--kind", "retired-scratch", "--owner", "lead/ab/jig",
            "--id", identifier, "--path", values["lead_scratch"], "--path", values["lead_start_dir"]])
        self.assertEqual(calls[1]["argv"], ["record", "end", "--kind", "retired-scratch", "--id", identifier])
        self.assertEqual(calls[2]["argv"], ["--user", "start", "--no-block", "reap.service"])
        self.assertEqual(set(lib.warmup_records()), {"coordinator/ab/old"})
        self.assertTrue((scratch / "brief.md").exists())
        self.assertTrue(Path(values["lead_start_dir"]).exists())


    def test_claim_owner_and_successor_refusals(self):
        for role, owner in (("lead", "lead/ab/jig"), ("coordinator", "s/another-draft")):
            self.env["FAKE_CLAIMS"] = f"hel8 1 [s/reserved]: {owner}: build (since now); held 1d"
            result = self.retire(role, yes=True)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn("claimed slot: hel8 1", result.stdout)
        self.env["FAKE_CLAIMS"] = "hel8 1 [lead/ab/jig]: other/owner: lead/ab/jig (since now); held 1d"
        for name in ("lead/jig", "lead/unknown/jig"):
            self.env["FAKE_AGENTS"] = json.dumps([{"name": name, "status": "busy"}])
            result = self.retire(yes=True)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn("live successor for area jig: " + name, result.stdout)
            self.assertNotIn("claimed slot:", result.stdout)
        self.assertFalse(any(call["tool"] == "reap" for call in self.calls()))

    def test_lease_default_shared_and_symlink_shared_refusals(self):
        self.env["FAKE_LEASES"] = json.dumps([{"owner": "s/another-draft", "subject": "crates/compiler"}])
        result = self.retire("coordinator", yes=True)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("lease held by s/another-draft: crates/compiler", result.stdout)
        result = self.retire("coordinator", "dm", yes=True)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("default coordinator has a shared start directory", result.stdout)
        scratch = Path(lib.names("ab", "jig")["lead_scratch"])
        scratch.parent.mkdir(parents=True)
        scratch.symlink_to(lib.names("dm", "jig")["lead_scratch"], target_is_directory=True)
        result = self.retire(yes=True)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("path shared with another role", result.stdout)
        self.assertFalse(any(call["tool"] == "reap" for call in self.calls()))


    def test_record_failure_preserves_warmups_and_does_not_wake(self):
        lib.record_warmup("coordinator/ab/old", "id", 123)
        self.env["FAKE_REAP_EXIT"] = "1"
        result = self.retire("coordinator", yes=True)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("coordinator/ab/old", lib.warmup_records())
        self.assertFalse(any(call["tool"] == "systemctl" for call in self.calls()))

    def test_codex_active_owner_refuses(self):
        self.registry.write_text(self.registry.read_text() + 'lead_kind = "codex"\n')
        self.env["FAKE_UNIT_EXIT"] = "0"
        result = self.retire(yes=True)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("active unit codex-owner-lead-ab-jig", result.stdout)

    def test_live_retirement_smoke(self):
        self.env['FAKE_AGENTS'] = json.dumps([{'name': 'lead/ab/jig/next', 'state': 'busy'}])
        result = self.retire(yes=True)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('live session lead/ab/jig/next', result.stdout)
        self.assertFalse(any(call['tool'] == 'reap' for call in self.calls()))

    def test_arity_refuses(self):
        for args in (("lead", "ab"), ("coordinator", "ab", "jig")):
            self.assertEqual(self.command("start", "retire", *args).returncode, 2)


if __name__ == "__main__":
    unittest.main()
