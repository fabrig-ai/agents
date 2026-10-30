"""Focused file, declaration, service and installer policies in private fixtures."""
from test_fleet_sync import *


class FleetPolicyTest(FleetTest):
    def deployed(self):
        return super().deployed("fabrig", "links", "render", "units")

    def test_non_symlink_tool_refused(self):
        put(self.home / ".local/bin/fleet-sync", "mine\n")
        state = self.component_sync("links", expected=1)
        self.assertEqual((self.home / ".local/bin/fleet-sync").read_text(), "mine\n")
        self.assertTrue(any(i["item"] == "link:fleet-sync" and i["result"] == "failed" for i in state["items"]))

    def test_backups_once_and_modes(self):
        put(self.home / ".cargo/config.toml", "# personal\n")
        put(self.home / ".profile", "# original profile\n")
        self.component_sync("render")
        backup = self.home / ".cargo/config.toml.pre-fleet-sync"
        self.assertEqual(backup.read_text(), "# personal\n")
        self.assertFalse((self.home / ".claude/settings.json.pre-fleet-sync").exists())
        put(self.home / ".cargo/config.toml", "# later edit\n")
        self.component_sync("render")
        self.assertEqual(backup.read_text(), "# personal\n")
        for path, mode in ((".cargo/config.toml", 0o600), (".profile", 0o644), (".config/fabrig/env.sh", 0o644)):
            self.assertEqual(stat.S_IMODE((self.home / path).stat().st_mode), mode)

    def test_blocks_and_conflicts(self):
        outside = '# personal\nexport DISABLE_AUTOUPDATER=0\ncase $- in *i*) ;; *) return;; esac\n'
        put(self.home / ".bashrc", outside)
        put(self.home / ".profile", "# profile\n")
        put(self.home / ".config/plan/environment.sh", "export TEMPER_FORGEJO=/wrong\n")
        state = self.component_sync("render")
        self.assertTrue(any(i["item"].startswith("conflict:") for i in state["items"]))
        bashrc = self.home / ".bashrc"
        self.assertTrue(bashrc.read_text().endswith(outside))
        self.assertTrue(bashrc.read_text().startswith("# >>> fleet-sync >>>\n"))
        before = bashrc.read_text()
        self.component_sync("render")
        self.assertEqual(bashrc.read_text(), before)
        # Update an obsolete block, retaining every byte outside it.
        put(bashrc, before.replace('[ ! -f "$HOME/.config/fabrig/env.sh" ] || . "$HOME/.config/fabrig/env.sh"', "# obsolete source"))
        self.component_sync("render")
        self.assertEqual(bashrc.read_text(), before)

    def test_codex_preserves_project_bytes(self):
        suffix = '[projects."/tmp/a"]\ntrust_level = "trusted" # keep\n\n[projects."/tmp/b"]\ntrust_level = "untrusted"\n'
        put(self.home / ".codex/config.toml", '# keep comment\nmodel = "old"\npersonality = "friendly"\n' + suffix)
        self.component_sync("render")
        content = (self.home / ".codex/config.toml").read_text()
        self.assertTrue(content.endswith(suffix))
        self.assertIn('# keep comment\n', content)
        self.assertIn('personality = "friendly"\n', content)
        self.assertEqual(tomllib.loads(content)["model_reasoning_effort"], "high")

    def test_codex_multiline_and_crlf_preserved(self):
        prefix = '# keep\r\nnotes = """\r\nmodel = "inside a string"\r\n[apparent.header]\r\n"""\r\n'
        suffix = '[projects."/tmp/a"]\r\ntrust_level = "trusted"\r\n'
        path = self.home / ".codex/config.toml"
        put(path, prefix + '"model" = "old"\r\n' + suffix)
        self.component_sync("render")
        result = path.read_bytes().decode()
        self.assertTrue(result.startswith(prefix))
        self.assertTrue(result.endswith(suffix))
        self.assertEqual(tomllib.loads(result)["model"], "gpt-6.1-sol")

    def test_json_semantics_and_file_mtime(self):
        self.component_sync("render")
        path = self.home / ".claude/settings.json"
        put(path, json.dumps(json.loads(path.read_text()), sort_keys=True))
        before = path.stat().st_mtime_ns
        state = self.component_sync("render")
        self.assertEqual(before, path.stat().st_mtime_ns)
        self.assertEqual(next(i["result"] for i in state["items"] if i["item"] == ".claude/settings.json"), "ok")

    def test_units_reload_only_on_change(self):
        self.deployed()
        calls = self.calls()
        self.assertEqual(calls.count(["--user", "daemon-reload"]), 1)
        self.component_sync("units")
        self.assertEqual(self.calls().count(["--user", "daemon-reload"]), 1)
        self.assertFalse(any("restart" in a or "stop" in a for a in self.calls()))
        self.assertEqual(next(i["result"] for i in self.component_sync("units", check=True)["items"] if i["item"] == "enabled:fleet-sync.timer"), "ok")

    def test_role_change_removes_only_owned_units(self):
        roles = self.source / "fleet/units/roles.toml"
        put(roles, roles.read_text() + '"role.service" = ["session"]\n"role.timer" = ["session"]\n')
        put(self.source / "fleet/units/role.service", "[Unit]\nDescription=Role\n[Service]\nType=simple\nExecStart=/bin/true\n")
        put(self.source / "fleet/units/role.timer", "[Unit]\nDescription=Role timer\n[Timer]\nOnCalendar=minutely\n[Install]\nWantedBy=timers.target\n")
        state = self.component_sync("units")
        self.assertTrue(any(i["reason"].startswith("restart pending") for i in state["items"]))
        units = self.home / ".config/systemd/user"
        put(units / "personal.service", "keep\n")
        hosts = self.source / "fleet/hosts.toml"
        put(hosts, hosts.read_text().replace('roles = ["session"]', 'roles = ["builder"]'))
        self.component_sync("units")
        self.assertFalse((units / "role.service").exists())
        self.assertFalse((units / "role.timer").exists())
        self.assertEqual((units / "personal.service").read_text(), "keep\n")
        self.assertIn(["--user", "disable", "--no-reload", "role.service"], self.calls())

    def test_no_bus_fails(self):
        state = self.component_sync("units", expected=1, env={**self.env, "FAKE_NO_BUS": "1"})
        self.assertTrue(any(i["item"] == "units" and i["result"] == "failed" for i in state["items"]))
        self.assertTrue(self.state()["unit_reload_pending"])
        self.component_sync("units")
        self.assertEqual(self.calls().count(["--user", "daemon-reload"]), 1)
        self.assertFalse(self.state()["unit_reload_pending"])

    def test_fabrig_failure_does_not_skip_files(self):
        self.deployed()
        self.git(self.home / "src/fabrig/main", "remote", "set-url", "origin", self.origin)
        (self.home / ".cargo/config.toml").unlink()
        state = self.component_sync("fabrig", "links", "render", expected=1)
        self.assertTrue(any(i["item"] == "fabrig" and i["result"] == "failed" for i in state["items"]))
        self.assertTrue((self.home / ".cargo/config.toml").exists())

    def test_fabrig_new_head_and_link_repair(self):
        self.deployed()
        put(self.fabrig / "tools/new-file", "new\n")
        self.git(self.fabrig, "add", ".")
        self.git(self.fabrig, "commit", "-qm", "fabrig update")
        self.git(self.fabrig, "push", "origin", "main")
        state = self.component_sync("fabrig", "links", "render")
        self.assertEqual(state["fabrig_sha"], self.git(self.fabrig, "rev-parse", "HEAD").strip())
        link = self.home / ".local/bin/claim"
        link.unlink()
        state = self.component_sync("fabrig", "links", "render")
        self.assertTrue(link.is_symlink())
        self.assertIn("tools/install", (self.home / ".local/state/fleet-sync/run.log").read_text())

    def test_fabrig_non_tools_landing_leaves_main_untouched(self):
        self.deployed()
        clone = self.home / "src/fabrig/main"
        installed = self.git(clone, "rev-parse", "HEAD").strip()
        before = self.snapshot(root=clone)
        put(self.fabrig / "docs/new", "docs only\n")
        self.git(self.fabrig, "add", ".")
        self.git(self.fabrig, "commit", "-qm", "non-tool landing")
        self.git(self.fabrig, "push", "origin", "main")
        remote = self.git(self.fabrig, "rev-parse", "HEAD").strip()
        state = self.component_sync("fabrig", "links", "render")
        self.assertEqual(before, self.snapshot(root=clone))
        self.assertEqual(state["fabrig_sha"], installed)
        self.assertEqual(self.fabrig_item(state), {"item": "fabrig", "result": "ok",
            "reason": f"main ahead, tools unchanged ({installed[:7]} -> {remote[:7]})"})
        self.assertNotIn("tools/install", (self.home / ".local/state/fleet-sync/run.log").read_text())
        mirror = self.home / "src/fabrig/.fleet-sync/fabrig.git"
        self.assertEqual(self.git(mirror, "rev-parse", "origin/main").strip(), remote)
        self.assertEqual(self.git(mirror, "rev-parse", "--is-bare-repository").strip(), "true")
        self.assertEqual(self.git(mirror, "config", "--get", "remote.origin.partialclonefilter").strip(), "blob:none")
        self.assertEqual(stat.S_IMODE(mirror.stat().st_mode), 0o700)

    def test_check_fetches_only_existing_mirror(self):
        self.deployed()
        put(self.fabrig / "tools/new", "tool change\n")
        self.git(self.fabrig, "add", ".")
        self.git(self.fabrig, "commit", "-qm", "tool landing")
        self.git(self.fabrig, "push", "origin", "main")
        mirror = self.home / "src/fabrig/.fleet-sync/fabrig.git"
        old = self.git(mirror, "rev-parse", "origin/main")
        before = self.snapshot(exclude_mirror=True)
        state = self.component_sync("fabrig", "links", "render", check=True, expected=1)
        self.assertEqual(before, self.snapshot(exclude_mirror=True))
        self.assertNotEqual(old, self.git(mirror, "rev-parse", "origin/main"))
        self.assertEqual(self.fabrig_item(state)["result"], "drift")

    def test_check_missing_mirror_and_lock_creates_neither(self):
        self.deployed()
        mirror = self.home / "src/fabrig/.fleet-sync/fabrig.git"
        lock = self.home / ".local/state/fabrig/install.lock"
        shutil.rmtree(mirror)
        lock.unlink()  # Fixture cleanup only; fleet-sync must never unlink this inode.
        before = self.snapshot()
        self.assertEqual(self.fabrig_item(self.component_sync("fabrig", "links", "render", check=True))["result"], "ok")
        self.assertEqual(before, self.snapshot())
        put(self.fabrig / "docs-only", "ahead\n")
        self.git(self.fabrig, "add", ".")
        self.git(self.fabrig, "commit", "-qm", "non-tool landing")
        self.git(self.fabrig, "push", "origin", "main")
        state = self.component_sync("fabrig", "links", "render", check=True, expected=1)
        self.assertEqual(self.fabrig_item(state)["result"], "drift")
        self.assertEqual(before, self.snapshot())
        self.assertFalse(mirror.exists())
        self.assertFalse(lock.exists())

    def test_installed_head_missing_from_mirror_counts_changed(self):
        self.deployed()
        clone = self.home / "src/fabrig/main"
        put(clone / "local-only", "unpublished commit\n")
        self.git(clone, "add", ".")
        self.git(clone, "commit", "-qm", "installed local commit")
        self.assertEqual(self.fabrig_item(self.component_sync("fabrig", "links", "render", check=True, expected=1))["result"], "drift")

    def test_install_lock_busy_skips_fabrig_and_continues(self):
        self.deployed()
        path = self.home / ".local/state/fabrig/install.lock"
        inode = path.stat().st_ino
        link = self.home / ".local/bin/claim"
        link.unlink()
        link.symlink_to("wrong")
        with path.open("r") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            before = self.snapshot()
            self.assertEqual(self.fabrig_item(self.component_sync("fabrig", "links", "render", check=True)),
                {"item": "fabrig", "result": "held", "reason": "install lock busy"})
            self.assertEqual(before, self.snapshot())
            (self.home / ".cargo/config.toml").unlink()
            state = self.component_sync("fabrig", "links", "render")
            self.assertEqual(self.fabrig_item(state)["result"], "held")
            self.assertTrue((self.home / ".cargo/config.toml").exists())
            self.assertEqual(os.readlink(link), "wrong")
        self.assertEqual(path.stat().st_ino, inode)

    def test_install_lock_inode_modes_scope_and_installer_exclusion(self):
        with patch.dict(os.environ, self.env, clear=True):
            module, runner = self.runner()
            command = runner.cmd
            path = self.home / ".local/state/fabrig/install.lock"
            observed = []
            def assert_locked(*args, **kwargs):
                if str(args[-1]).endswith("tools/install"):
                    self.assertEqual(kwargs.get("timeout"), 300)
                    with path.open("r") as stream:
                        with self.assertRaises(BlockingIOError):
                            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    observed.append("installer")
                return command(*args, **kwargs)
            with patch.object(runner, "cmd", side_effect=assert_locked):
                runner.fabrig()
            self.assertEqual(observed, ["installer"])
            inode = path.stat().st_ino
            real_readlink = os.readlink
            def readlink_checked(link, *args, **kwargs):
                if Path(link).parent == self.home / ".local/bin" or "dir_fd" in kwargs:
                    with path.open("r") as stream:
                        with self.assertRaises(BlockingIOError):
                            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    observed.append("link")
                return real_readlink(link, *args, **kwargs)
            with patch.object(module.os, "readlink", side_effect=readlink_checked):
                runner.fabrig()
            self.assertIn("link", observed)
            self.assertEqual(path.stat().st_ino, inode)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)
            with path.open("r") as stream:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)  # Released at step return.

    def test_install_lock_refuses_symlink_fifo_and_directory(self):
        lock = self.home / ".local/state/fabrig/install.lock"
        lock.parent.mkdir(parents=True)
        target = self.home / "untouched"
        put(target, "never replace or follow\n")
        lock.symlink_to(target)
        self.assertEqual(self.fabrig_item(self.component_sync("fabrig", expected=1))["result"], "failed")
        self.assertTrue(lock.is_symlink())
        self.assertEqual(target.read_text(), "never replace or follow\n")
        lock.unlink()
        os.mkfifo(lock, 0o600)
        self.assertIn("not a regular file", self.fabrig_item(self.component_sync("fabrig", expected=1))["reason"])
        self.assertTrue(stat.S_ISFIFO(lock.lstat().st_mode))
        lock.unlink()
        lock.mkdir()
        self.assertEqual(self.fabrig_item(self.component_sync("fabrig", expected=1))["result"], "failed")
        self.assertTrue(lock.is_dir())

    def test_install_lock_modes_check_read_only_normal_repairs_inode(self):
        self.deployed()
        lock = self.home / ".local/state/fabrig/install.lock"
        inode = lock.stat().st_ino
        lock.chmod(0o644)
        lock.parent.chmod(0o755)
        before = self.snapshot()
        self.assertIn("0600", self.fabrig_item(self.component_sync("fabrig", check=True, expected=1))["reason"])
        self.assertEqual(before, self.snapshot())
        self.component_sync("fabrig")
        self.assertEqual(lock.stat().st_ino, inode)
        self.assertEqual(stat.S_IMODE(lock.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(lock.parent.stat().st_mode), 0o700)

    def test_defer_before_lock_keeps_controls_unchanged(self):
        defer = self.home / ".config/fleet-sync/defer-fabrig"
        put(defer, "ops upgrading\nsecond line\n")
        state = self.component_sync("fabrig", "links", "render")
        self.assertEqual(self.fabrig_item(state), {"item": "fabrig", "result": "deferred", "reason": "ops upgrading"})
        self.assertFalse((self.home / ".local/state/fabrig/install.lock").exists())
        self.assertFalse((self.home / "src/fabrig/main").exists())
        self.assertEqual(defer.read_text(), "ops upgrading\nsecond line\n")
        self.assertFalse((defer.parent / "pin").exists())
        self.assertFalse((defer.parent / "hold").exists())
        with patch.dict(os.environ, self.env, clear=True):
            module, _ = self.runner()
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                module.print_state(state, False)
        self.assertIn("1 deferred", output.getvalue())

    def test_defer_created_during_lock_acquisition(self):
        with patch.dict(os.environ, self.env, clear=True):
            module, runner = self.runner()
            real_flock = fcntl.flock
            lock = self.home / ".local/state/fabrig/install.lock"
            def acquire_then_defer(fd, operation):
                real_flock(fd, operation)
                with lock.open("r") as other:
                    with self.assertRaises(BlockingIOError):
                        real_flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
                put(self.home / ".config/fleet-sync/defer-fabrig", "raced with ops\n")
            with patch.object(module.fcntl, "flock", side_effect=acquire_then_defer):
                runner.fabrig()
            self.assertEqual(self.fabrig_item(runner.state)["result"], "deferred")
            self.assertFalse(runner.log)  # No git calls or link checks before the second defer check.

    def test_defer_created_during_fetch_precedes_link_check(self):
        self.deployed()
        put(self.home / "src/fabrig/main/tools/installed", "malformed manifest to detect a read\n")
        with patch.dict(os.environ, self.env, clear=True):
            _, runner = self.runner()
            command = runner.cmd
            def fetch_then_defer(*args, **kwargs):
                result = command(*args, **kwargs)
                if args[0] == "git" and "fetch" in args and str(args[2]).endswith("fabrig.git"):
                    put(self.home / ".config/fleet-sync/defer-fabrig", "deferred during fetch\n")
                return result
            with patch.object(runner, "cmd", side_effect=fetch_then_defer):
                runner.fabrig()
            self.assertEqual(self.fabrig_item(runner.state)["result"], "deferred")

    def test_defer_created_during_bootstrap_precedes_installer(self):
        with patch.dict(os.environ, self.env, clear=True):
            _, runner = self.runner()
            command = runner.cmd
            def clone_then_defer(*args, **kwargs):
                result = command(*args, **kwargs)
                if args[0] == "git" and "clone" in args and ".fabrig-install-" in str(args[-1]):
                    put(self.home / ".config/fleet-sync/defer-fabrig", "ops deferred bootstrap\n")
                return result
            with patch.object(runner, "cmd", side_effect=clone_then_defer):
                runner.fabrig()
            self.assertEqual(self.fabrig_item(runner.state)["result"], "deferred")
            self.assertFalse((self.home / "src/fabrig/main").exists())
            self.assertFalse(any("tools/install" in entry for entry in runner.log))

    def test_defer_created_during_links_stops_remaining_checks(self):
        self.deployed()
        with patch.dict(os.environ, self.env, clear=True):
            module, runner = self.runner()
            readlink = os.readlink
            seen = []
            def readlink_then_defer(path, *args, **kwargs):
                result = readlink(path, *args, **kwargs)
                if Path(path).parent == self.home / ".local/bin" or "dir_fd" in kwargs:
                    seen.append(str(path))
                    put(self.home / ".config/fleet-sync/defer-fabrig", "ops deferred link checks\n")
                return result
            with patch.object(module.os, "readlink", side_effect=readlink_then_defer):
                runner.fabrig()
            self.assertEqual(len(seen), 1)
            self.assertEqual(self.fabrig_item(runner.state)["result"], "deferred")

    def test_versions_warn_only(self):
        put(self.bin / "codex", "#!/bin/bash\necho codex-cli 0.0.1\n", True)
        state = self.component_sync("versions")
        self.assertEqual(next(i["result"] for i in state["items"] if i["item"] == "version:codex"), "warn")

    def test_builder_rendering_and_env_host_override(self):
        self.component_sync("render", host="hetzner6", env={**self.env, "FLEET_HOST": "hel8"})
        self.assertEqual(self.state()["host"], "hetzner6")
        self.assertNotIn("jobs", tomllib.loads((self.home / ".cargo/config.toml").read_text())["build"])
        self.assertEqual((self.home / "src/rust/tmp/machine.env").read_text(),
                         "PLAN_MIN_DISK_GB=40\nKACHE_MAX_GB=50\nKACHE_LOCAL_ONLY=1\nQA_SLOTS=2\nHEAVY_BUILD_SLOTS=3\n"
                         "QA_WALK_KINDS=forgejo=2:chatgpt,claude=2:claude\nQA_WALK_SLOTS=forgejo=8+1,claude=4+3\n"
                         "QA_SLOT_HOST=hetzner6\nQA_CLAIM_OWNER=s/qa\nQA_CLAIM_SSH=free@204.168.210.29\n"
                         "QA_STUCK_TO=s/qa@hel8\nSESSION_SLOTS=2\n")
        settings = json.loads((self.home / ".claude/settings.json").read_text())
        self.assertNotIn("HEAVY_BUILD_JOBS", settings["env"])
        self.assertNotIn("PATH", settings["env"])
        self.assertTrue(settings["env"]["SKEIN_TEST_CHROMIUM"].startswith(str(self.home)))

    def test_post_machines_check_only_never_written_or_backed_up(self):
        path = self.home / "src/rust/tmp/post/machines"
        put(path, "ops routing\n")
        before = path.stat().st_mtime_ns
        for flags in ((), ("--check",)):
            state = self.component_sync("render", check=bool(flags))
            item = next(i for i in state["items"] if i["item"] == "src/rust/tmp/post/machines")
            self.assertEqual(item["result"], "warn")
            self.assertIn("names differ:", item["reason"])
            self.assertIn("ops", item["reason"])
            self.assertEqual(path.read_text(), "ops routing\n")
            self.assertEqual(path.stat().st_mtime_ns, before)
            self.assertFalse(path.with_name("machines.pre-fleet-sync").exists())

    def test_policy_write_opt_in_and_matching_check_only(self):
        policy = self.source / "fleet/policy.toml"
        put(policy, '[files]\n"src/rust/tmp/post/machines" = "write"\n')
        self.component_sync("render")
        path = self.home / "src/rust/tmp/post/machines"
        self.assertEqual(path.read_text().splitlines()[0], "hel8 local")
        put(policy, '[files]\n"src/rust/tmp/post/machines" = "check"\n')
        before = path.stat().st_mtime_ns
        state = self.component_sync("render")
        self.assertEqual(next(i["result"] for i in state["items"] if i["item"] == "src/rust/tmp/post/machines"), "ok")
        self.assertEqual(path.stat().st_mtime_ns, before)

    def test_invalid_file_policy_no_writes(self):
        put(self.source / "fleet/policy.toml", '[files]\n"src/rust/tmp/post/machines" = "ignore"\n')
        before = self.snapshot()
        self.process("python3", "-I", "-B", self.source / "tools/fleet-sync", "--host", "hel8", expected=2)
        self.assertEqual(before, self.snapshot())

    def test_environment_d_plain_values(self):
        self.component_sync("render")
        content = (self.home / ".config/environment.d/90-fabrig.conf").read_text()
        self.assertIn(f"SKEIN_TEST_CHROMIUM={self.home}/.local/opt/chromium-147.0.7727.101/bin/chromium\n", content)
        self.assertNotIn('"', content)
        self.assertNotIn("'", content)
        self.assertNotIn("$", content)

    def test_invalid_global_host_and_expanded_env_no_writes(self):
        before = self.snapshot()
        module, _ = self.runner()
        original = (self.source / "fleet/env").read_text()
        for value in ("two words", "a\tb", "a\u2003b", "a'b", 'a"b', "a\\b", "$USER", "$HOME/$OTHER"):
            with self.subTest(value=value):
                put(self.source / "fleet/env", original + f"INVALID={value}\n")
                with self.assertRaises(ValueError):
                    module.Declarations(self.source, self.home)
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

    def test_invalid_machine_env_table_no_writes(self):
        hosts = self.source / "fleet/hosts.toml"
        original = hosts.read_text()
        before = self.snapshot()
        strings = ("", "two words", "a\tb", "a\u2003b", "a'b", 'a"b', "a\\b",
                   "a\nb", "a\rb", "$HOME", "$USER")
        invalid = tuple(map(json.dumps, strings)) + ('true', 'false', '-1', '1.5',
                                                    '[]', '[1]', '{}', '{ x = 1 }')
        with patch.dict(os.environ, self.env, clear=True):
            module, _ = self.runner()
            for name in tomllib.loads(original)["hosts"]:
                for value in invalid:
                    with self.subTest(host=name, value=value):
                        prefix, rest = original.split(f"[hosts.{name}]", 1)
                        rest = rest.replace('machine_env = { ',
                                            f'machine_env = {{ ARBITRARY_KEY = {value}, ', 1)
                        put(hosts, prefix + f"[hosts.{name}]" + rest)
                        with self.assertRaisesRegex(ValueError, f"invalid machine_env for {name}: ARBITRARY_KEY"):
                            module.Declarations(self.source, self.home)
                        self.assertEqual(before, self.snapshot())
            put(hosts, original.replace('PLAN_MIN_MEM_GB = 4', 'BAD-KEY = 4', 1))
            with self.assertRaisesRegex(ValueError, "invalid machine_env for hel8: BAD-KEY"):
                module.Declarations(self.source, self.home)
        result = self.process("python3", "-I", "-B", self.source / "tools/fleet-sync",
                              "--host", "hel8", expected=2)
        self.assertIn("invalid machine_env for hel8: BAD-KEY", result.stderr)
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

    def test_posix_path_idempotence_in_nested_shells(self):
        self.component_sync("render")
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
        state = self.component_sync("render")
        warnings = [i for i in state["items"] if i["item"].startswith("conflict:")]
        self.assertEqual(len(warnings), 2)
        self.assertTrue(all("DISABLE_AUTOUPDATER" in i["reason"] for i in warnings))

    def test_never_touches_coordination_heavy_or_spools(self):
        protected = ["src/fabrig/claims", "src/fabrig/leases", "src/fabrig/queue", "src/fabrig/slots",
                     ".local/state/heavy", ".local/state/agents-heavy", ".local/state/fabrig/heavy",
                     "src/rust/tmp/heavy", "src/rust/tmp/codex-run", "src/rust/tmp/owners",
                     "src/rust/tmp/logins",
                     "src/rust/tmp/post/inbox", "src/rust/tmp/post/outbox", "src/rust/tmp/post/sent",
                     "src/rust/tmp/post/arbitrary-spool"]
        units = [".config/systemd/user/agents-heavy-reconcile.service",
                 ".config/systemd/user/agents-heavy-reconcile.timer",
                 ".config/systemd/user/heavy.service"]
        for directory in protected:
            put(self.home / directory / "sentinel", "opaque state\n")
        for unit in units:
            put(self.home / unit, "[Unit]\nDescription=Never touch\n")
        snapshots = {p: self.snapshot(root=self.home / p) for p in protected + units}
        self.component_sync("render", "units")
        self.component_sync("render", "units", check=True)
        self.assertEqual(snapshots, {p: self.snapshot(root=self.home / p) for p in protected + units})
        self.assertFalse(any(any("heavy" in arg for arg in argv) for argv in self.calls()))

    def test_shell_outside_bytes_preserved(self):
        outside = "# keep CRLF\r\n# outside\r\n"
        put(self.home / ".profile", outside)
        put(self.home / ".bashrc", outside)
        self.component_sync("render")
        self.assertTrue((self.home / ".profile").read_bytes().decode().startswith(outside))
        self.assertTrue((self.home / ".bashrc").read_bytes().decode().endswith(outside))

    def test_timer_age_and_history_pruning(self):
        with patch.dict(os.environ, self.env, clear=True):
            module, runner = self.runner()
            instant = dt.datetime(2026, 10, 30, tzinfo=dt.UTC)
            class Clock(dt.datetime):
                @classmethod
                def now(cls, tz=None):
                    return instant
            with patch.object(module.dt, "datetime", Clock):
                runner.args.timer = True
                runner.item("fixture", "changed", "timer work")
                self.assertEqual(runner.finish(), 0)
                stamp = self.state()["last_timer_end"]
                history = self.home / ".local/state/fleet-sync/runs.jsonl"
                stale = {"end": (instant - dt.timedelta(days=8)).isoformat()}
                put(history, json.dumps(stale) + "\n" + history.read_text())
                runner.args.timer = False
                runner.state["items"] = []
                self.assertEqual(runner.finish(), 0)
                self.assertEqual(self.state()["last_timer_end"], stamp)
                self.assertEqual(len(history.read_text().splitlines()), 1)
                _, check = self.runner(check=True)
                self.assertEqual(check.state["last_timer_end"], stamp)
                self.assertEqual(check.finish(), 0)


def load_tests(loader, tests, pattern):
    cls = FleetPolicyTest
    return unittest.TestSuite(cls(name) for name in cls.__dict__ if name.startswith("test_"))
