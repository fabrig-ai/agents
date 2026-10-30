"""Full CLI/lifecycle matrices; isolated periodic coverage."""
from test_session_start import *


class PeriodicCodexLeadTests(CodexLeadTests):
    def test_missing_brief_refuses_without_any_commands(self):
        result = self.command('start', 'lead', 'ab', 'skein')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('missing brief', result.stderr)
        self.assertEqual(self.all_calls(), [])
        self.assertFalse(list(self.home.iterdir()))

    def test_dry_run_command_and_no_writes(self):
        scratch = self.brief('ab')
        result = self.command('start', 'lead', 'ab', 'skein', '--effort', 'xhigh', '--model', 'custom', '--dry-run')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(shlex.split(result.stdout.strip().removeprefix('argv=')),
                         ['codex-run', 'owner', '--effort', 'xhigh', '--model', 'custom', 'lead/ab/skein', str(scratch / 'brief.md')])
        self.assertEqual([c['tool'] for c in self.all_calls()], ['systemctl'])
        self.assertEqual([p.name for p in scratch.iterdir()], ['brief.md'])

    def test_unit_and_launch_errors_are_not_success(self):
        self.brief('ab')
        self.env['FAKE_UNIT_EXIT'] = '1'
        self.assertEqual(self.command('start', 'lead', 'ab', 'skein').returncode, 2)
        self.env.update(FAKE_UNIT_EXIT='3', FAKE_LAUNCH_EXIT='2')
        result = self.command('start', 'lead', 'ab', 'skein')
        self.assertEqual(result.returncode, 2)
        self.assertIn('codex-run launch failed', result.stderr)

    def test_wire_skips_all_codex_leads_including_existing_directories(self):
        values = lib.names('ab', 'skein')
        directory = Path(values['lead_start_dir']) / '.claude'
        directory.mkdir(parents=True)
        settings = directory / 'settings.json'
        settings.write_text('{"keep": true}')
        for options in ((), ('--dry-run',)):
            result = self.command('start', 'wire', 'ab', *options)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.count('Codex owner has no Claude hooks'), 4)
        self.assertEqual(settings.read_text(), '{"keep": true}')
        self.assertTrue(all(c['tool'] == 'session-context' for c in self.all_calls()))



class PeriodicLaunchTests(LaunchTests):
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

    def test_default_flags(self):
        self.brief()
        self.assertEqual(self.command("start", "lead", "dm", "skein").returncode, 0)
        launch = self.calls()[-1]
        self.assertEqual(launch["argv"][:-1], ["--bg", "--name", "lead/skein", "--effort", "high"])
        self.assertIn("written (unknown)", launch["argv"][-1])

    def test_coordinator_reuses_existing_clone_and_brief(self):
        for handle in ("dm", "ab"):
            value = lib.names(handle)
            checkout = Path(value["coordinator_clone"])
            checkout.mkdir(parents=True)
            (checkout / "sentinel").write_text("Keep this checkout.\n")
            brief = Path(value["coordinator_brief"])
            brief.parent.mkdir(parents=True, exist_ok=True)
            brief.write_text("Keep this brief.\n")
            result = self.command("start", "coordinator", handle)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((checkout / "sentinel").read_text(), "Keep this checkout.\n")
            self.assertEqual(brief.read_text(), "Keep this brief.\n")
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



class PeriodicOwnershipTests(OwnershipTests):
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



class PeriodicWiringTests(WiringTests):
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
                        self.assertEqual(set(hooks), {"Stop", "SessionStart", "SessionEnd", "UserPromptSubmit"})
                        self.assertEqual(hooks["Stop"], hooks["UserPromptSubmit"])
                        self.assertEqual(hooks["Stop"], hooks["SessionStart"][:1])
                        self.assertNotIn("matcher", hooks["SessionStart"][0])
                        self.assertEqual([argv[i + 1] for i, token in enumerate(argv) if token == "--watch"],
                                         lib.watched(role, "dm", "jig" if role == "lead" else None))
                        self.assertEqual(stop["timeout"], 30)
                    else:
                        self.assertEqual(set(hooks), {"Stop", "SessionStart", "SessionEnd"})
                        self.assertNotIn("--watch", argv)
                        self.assertEqual(hooks["SessionStart"][0]["matcher"], "compact")

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
                    "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "session-context --hook"}]}],
                              "SessionStart": [{"hooks": [{"type": "command", "command": "session-context --hook"}]}],
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
        self.assertEqual(settings["hooks"]["SessionStart"][:1], [{"matcher": "compact", "hooks": [stop]}])
        self.assertEqual(self.calls(), [])
        self.assertEqual(len(self.all_calls()), 1)
        self.assertEqual(self.all_calls()[0]["argv"], ["--capabilities"])
        self.assertEqual([p.name for p in path.parent.iterdir()], ["settings.json"])
        self.assertFalse(Path(lib.names("dm", "skein")["lead_start_dir"]).exists())

    def test_legacy_capabilities_only_plain_lead_stop_and_no_coordinator_hooks(self):
        self.env["FAKE_GATING"] = "0"
        for role, values in (("lead", lib.names("dm", "skein")), ("coordinator", lib.names("dm"))):
            path, _, _ = lib.hook_settings(values, role, {"hook-gating"})
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"keep": True, "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "session-context --hook"}]}], "SessionStart": [{"hooks": [{"type": "command", "command": "session-context --hook"}]}], "Notification": ["keep"]}}))
        result = self.command("start", "wire", "dm")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("lacks hook-gating", result.stdout)
        self.assertIn("coordinator hooks skipped", result.stdout)
        for role, values in (("lead", lib.names("dm", "skein")), ("coordinator", lib.names("dm"))):
            path, _, _ = lib.hook_settings(values, role, {"hook-gating"})
            settings = json.loads(path.read_text())
            self.assertTrue(settings["keep"])
            self.assertEqual(settings["hooks"]["Notification"], ["keep"])
            self.assertEqual(len(settings["hooks"]["SessionStart"]), 1)
            if role == "lead":
                self.assertEqual(settings["hooks"]["Stop"][0]["hooks"][0]["command"], "session-context --hook")
            else:
                self.assertNotIn("Stop", settings["hooks"])
        self.assertEqual([call["argv"] for call in self.all_calls()], [["--capabilities"]])

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



class PeriodicWarmupTests(WarmupTests):
    def test_legacy_incumbent_does_not_prevent_start_and_success_is_recorded(self):
        self.env["FAKE_AGENTS"] = '[{"name":"coord-next","status":"busy"}]'
        before = time.time()
        result = self.command("start", "coordinator", "dm", "--next")
        after = time.time()
        self.assertEqual(result.returncode, 0, result.stderr)
        launch = self.calls()[-1]
        name = launch["argv"][2]
        self.assertTrue(name.startswith("coordinator/dm/"))
        self.assertIn(name, launch["argv"][-1])
        self.assertIn("warm-up post name is coord-next", launch["argv"][-1])
        state = json.loads((self.home / ".local/state/session-start/warmups.json").read_text())
        self.assertTrue(state[name]["next"])
        self.assertGreaterEqual(state[name]["started_at"], before)
        self.assertLessEqual(state[name]["started_at"], after)
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



class PeriodicDirectorTests(DirectorTests):
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
                self.assertEqual(set(settings["hooks"]), {"Notification", "SessionStart", "SessionEnd"})
                self.assertIn("director hooks skipped", result.stdout)
                continue
            argv = shlex.split(settings["hooks"]["Stop"][0]["hooks"][0]["command"])
            for option, expected in (("--role", "director"), ("--name", "director"), ("--name-prefix", "director/"), ("--handover", values["director_handover"])):
                self.assertEqual(argv[argv.index(option) + 1], expected)
            if drift == "1":
                self.assertEqual(settings["hooks"]["Stop"], settings["hooks"]["SessionStart"][:1])
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



class PeriodicRetireTests(RetireTests):
    def test_coordinator_paths_and_warmup_cleanup(self):
        values = lib.names("ab")
        lib.record_warmup("coordinator/ab/old", "id", 123)
        lib.record_warmup("ab-next", "id", 123)
        lib.record_warmup("coordinator/dm/old", "id", 123)
        result = self.retire("coordinator", yes=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("refused:", result.stdout)
        for key in ("coordinator_clone", "coordinator_brief", "coordinator_start_dir"):
            self.assertIn("path=" + values[key], result.stdout)
        self.assertEqual(set(lib.warmup_records()), {"coordinator/dm/old"})
        self.assertEqual([c["argv"] for c in self.calls() if c["tool"] == "lease"], [["list", "--json"]])

    def test_live_names_and_prefixes_refuse_but_completed_does_not(self):
        for role, name in (("lead", "lead/ab/jig"), ("lead", "lead/ab/jig/next"),
                           ("coordinator", "coordinator/ab/old"), ("coordinator", "ab-next"),
                           ("coordinator", "s/another-draft")):
            for status in (None, "busy", "stopped", "completed"):
                with self.subTest(role=role, name=name, status=status):
                    session = {"name": name, "id": "deadbeef"}
                    if status is not None:
                        session["state"] = status
                    self.env["FAKE_AGENTS"] = json.dumps([session])
                    result = self.retire(role)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual("live session " + name in result.stdout, status not in ("stopped", "completed"))
                    if status not in ("stopped", "completed"):
                        self.assertEqual(self.retire(role, yes=True).returncode, 1)
        self.assertFalse(any(call["tool"] == "reap" for call in self.calls()))

    def test_missing_reap_and_unavailable_inputs_refuse(self):
        for key, value, expected in (("FAKE_CLAIMS", "malformed", "claim list unavailable"),
                                     ("FAKE_CLAIMS_EXIT", "1", "claim list unavailable"),
                                     ("FAKE_AGENTS_EXIT", "1", "session observation unavailable"),
                                     ("FAKE_LEASES", "{}", "lease list unavailable")):
            self.env[key] = value
            result = self.retire("coordinator", yes=True)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn(expected, result.stdout)
            del self.env[key]
        (self.bin / "reap").unlink()
        self.assertEqual(self.retire().returncode, 0)
        result = self.retire(yes=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("reap absent", result.stdout)



def load_tests(loader, tests, pattern):
    classes = (PeriodicCodexLeadTests, PeriodicLaunchTests, PeriodicOwnershipTests, PeriodicWiringTests, PeriodicWarmupTests, PeriodicDirectorTests, PeriodicRetireTests,)
    return unittest.TestSuite(cls(name) for cls in classes
                              for name in cls.__dict__ if name.startswith("test_"))
