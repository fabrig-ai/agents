"""Integration tests: all processes use a disposable HOME and local git origins."""

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

ROOT = Path(__file__).resolve().parent.parent
FABRIG_TOOLS = Path("/home/free/src/fabrig/main/tools")
HOST_COUNT = len(tomllib.loads((ROOT / "fleet/hosts.toml").read_text())["hosts"])


def put(path, content, executable=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    sibling = path.with_name(path.name + ".test-new")
    sibling.write_text(content)
    sibling.chmod(0o755 if executable else 0o600)
    sibling.replace(path)


SYSTEMCTL = '''#!/usr/bin/env python3
import json, os, pathlib, subprocess, sys
home = pathlib.Path.home()
with (home / "systemctl.log").open("a") as f:
    f.write(json.dumps(sys.argv[1:]) + "\\n")
if os.environ.get("FAKE_NO_BUS"):
    sys.exit(1)
args = sys.argv[2:]
directory = home / ".config/systemd/user"
def enablement(name):
    if name.endswith(".timer"):
        return [directory / "timers.target.wants" / name]
    links, section = [], ""
    for line in (directory / name).read_text().splitlines():
        line = line.strip()
        if line.startswith("["):
            section = line
        key, sep, value = line.partition("=")
        if section == "[Install]" and sep:
            for target in value.split():
                if key in ("WantedBy", "RequiredBy"):
                    suffix = "wants" if key == "WantedBy" else "requires"
                    links.append(directory / (target + "." + suffix) / name)
                elif key == "Alias":
                    links.append(directory / target)
    return links
if args[0] == "daemon-reload":
    record = home / "unit-reloads.json"
    reloads = json.loads(record.read_text()) if record.exists() else []
    reloads.append({p.name: p.stat().st_mtime_ns for p in directory.iterdir() if p.is_file()})
    sibling = record.with_suffix(".new")
    sibling.write_text(json.dumps(reloads))
    sibling.replace(record)
    (home / "manager-needs-reload").unlink(missing_ok=True)
elif args[0] == "enable":
    name = args[-1]
    for link in enablement(name):
        link.parent.mkdir(parents=True, exist_ok=True)
        if link.is_symlink() and link.resolve() != directory / name:
            print("conflicting enablement symlink", file=sys.stderr)
            sys.exit(1)
        if not link.is_symlink():
            link.symlink_to(directory / name)
    if name.endswith(".service") and "--now" in args:
        active = home / (name + ".active")
        sibling = active.with_suffix(".new")
        sibling.write_text("active")
        sibling.replace(active)
    if os.environ.get("FAKE_ENABLE_TIMER_RUN"):
        result = subprocess.run([sys.executable, "-I", "-B",
            str(home / "src/fabrig/current/tools/fleet-sync"), "--host", "hel8", "--timer"],
            capture_output=True, text=True, timeout=10)
        record = home / "timer-race.json"
        sibling = record.with_suffix(".new")
        sibling.write_text(json.dumps([result.returncode, result.stdout, result.stderr]))
        sibling.replace(record)
elif args[0] == "disable":
    for link in enablement(args[-1]):
        link.unlink(missing_ok=True)
elif args[0] == "show":
    if "NeedDaemonReload" in args:
        for name in args[3:]:
            needed = (home / "manager-needs-reload").read_text().splitlines() if (home / "manager-needs-reload").exists() else []
            print("NeedDaemonReload=" + ("yes" if name in needed else "no"))
    else:
        print("Version=fake")
elif args[0] == "is-active":
    if args[-1].endswith(".service"):
        state = os.environ.get("FAKE_SERVICE_STATE", "active" if (home / (args[-1] + ".active")).exists() else "inactive")
        sys.exit(0 if state == "active" else 1 if state == "failed" else 3)
    sys.exit(3 if os.environ.get("FAKE_INACTIVE") or not (directory / "timers.target.wants" / args[-1]).is_symlink() else 0)
'''

SSH = '''#!/usr/bin/env python3
import json, os, pathlib, sys
with (pathlib.Path.home() / "ssh.log").open("a") as f:
    f.write(json.dumps(sys.argv[1:]) + "\\n")
hosts = json.loads(os.environ["FAKE_SSH_HOSTS"])
host = hosts[sys.argv[-2]]
if host == "hetzner3":
    print("fixture unreachable", file=sys.stderr)
    sys.exit(255)
print(json.dumps({"host": host, "agents_sha": "a" * 40, "fabrig_sha": "b" * 40,
                  "last_timer_end": "2026-01-01T00:00:00+00:00", "items": []}))
'''


class FleetTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="fleet-test-")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.home = self.directory / "home"
        self.home.mkdir()
        self.bin = self.directory / "bin"
        self.bin.mkdir()
        self.env = {**os.environ, "HOME": str(self.home), "PATH": f"{self.bin}:/usr/bin:/bin",
                    "PYTHONDONTWRITEBYTECODE": "1", "GIT_CONFIG_NOSYSTEM": "1",
                    "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_AUTHOR_NAME": "Fixture",
                    "GIT_AUTHOR_EMAIL": "fixture@example.invalid", "GIT_COMMITTER_NAME": "Fixture",
                    "GIT_COMMITTER_EMAIL": "fixture@example.invalid", "DBUS_SESSION_BUS_ADDRESS": "fake:bus"}
        for key in ("FLEET_HOST", "FLEET_SYNC_HANDOFF", "FLEET_SYNC_LOG", "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
            self.env.pop(key, None)
        put(self.bin / "systemctl", SYSTEMCTL, True)
        put(self.bin / "systemd-analyze", "#!/bin/bash\nexit 0\n", True)
        put(self.bin / "ssh", SSH, True)
        for command, output in {"claude": "2.1.312 (Claude Code)", "codex": "codex-cli 0.162.1",
                                "cargo-nextest": "cargo-nextest 0.9.148", "kache": "kache 1.2.2-gitrev.2", "rustc": "rustc 1.95.0 (fixture)"}.items():
            put(self.bin / command, f"#!/bin/bash\nprintf '%s\\n' '{output}'\n", True)
        self.fabrig = self.directory / "fabrig-source"
        self.fabrig.mkdir()
        # Copy the real installer and manifest, never any credentials or live state.
        for name in ("install", "installed"):
            put(self.fabrig / "tools" / name, (FABRIG_TOOLS / name).read_text(), name == "install")
        for line in (self.fabrig / "tools/installed").read_text().splitlines():
            if line.strip() and not line.startswith("#"):
                tool, directory = line.split()
                put(self.fabrig / "tools" / directory / tool, "#!/bin/bash\nexit 0\n", True)
        fabrig_origin = self.repository(self.fabrig, "fabrig-origin.git")
        self.git(fabrig_origin, "config", "uploadpack.allowFilter", "true")
        # Transport semantics avoid local-clone object hardlinks changing main's
        # mtimes when the fixture origin receives unrelated commits.
        self.fabrig_origin = fabrig_origin.as_uri()
        self.system_bins = (self.directory / "system/usr/bin", self.directory / "system/bin")
        for directory in self.system_bins:
            directory.mkdir(parents=True)
        put(self.system_bins[0] / "watch", "#!/bin/sh\nexit 0\n", True)
        self.source = self.directory / "agents-source"
        self.source.mkdir()
        shutil.copytree(ROOT / "fleet", self.source / "fleet")
        for line in (ROOT / "tools/installed").read_text().splitlines():
            if line.strip() and not line.lstrip().startswith("#"):
                path = line.split()[-1]
                put(self.source / "tools" / path, (ROOT / "tools" / path).read_text(), True)
        # Isolate manifest system-command checks from the machine running tests.
        script = self.source / "tools/fleet-sync"
        put(script, script.read_text().replace(
            'SYSTEM_TOOL_DIRS = (Path("/usr/bin"), Path("/bin"))',
            f'SYSTEM_TOOL_DIRS = tuple(map(Path, {json.dumps([str(p) for p in self.system_bins])}))'), True)
        put(self.source / "tools/installed", (ROOT / "tools/installed").read_text())
        put(self.source / "fleet/repositories.toml",
            f"agents = {json.dumps(str(self.directory / 'agents-origin.git'))}\n"
            f"fabrig = {json.dumps(str(self.fabrig_origin))}\n")
        put(self.source / "old/forbidden", "must not be deployed\n")
        self.origin = self.repository(self.source, "agents-origin.git")
        self.sha = self.git(self.source, "rev-parse", "HEAD").strip()
        hosts = tomllib.loads((ROOT / "fleet/hosts.toml").read_text())["hosts"]
        self.env["FAKE_SSH_HOSTS"] = json.dumps({h["ssh"]: name for name, h in hosts.items()})

    def process(self, *args, cwd=None, expected=0, env=None):
        result = subprocess.run([str(a) for a in args], cwd=cwd, env=env or self.env,
                                capture_output=True, text=True, timeout=60)
        if expected is not None:
            self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result

    def git(self, directory, *args):
        return self.process("git", "-C", directory, *args).stdout

    def repository(self, source, name):
        self.git(source, "init", "-b", "main")
        self.git(source, "add", ".")
        self.git(source, "commit", "-qm", "fixture")
        origin = self.directory / name
        self.process("git", "clone", "--bare", source, origin)
        self.git(source, "remote", "add", "origin", origin)
        return origin

    def publish(self):
        self.git(self.source, "add", ".")
        self.git(self.source, "commit", "-qm", "new fleet declaration")
        self.git(self.source, "push", "origin", "main")
        return self.git(self.source, "rev-parse", "HEAD").strip()

    def sync(self, *args, expected=0, env=None, script=None):
        result = self.process("python3", "-I", "-B", script or self.source / "tools/fleet-sync",
                              "--host", "hel8", "--json", *args, expected=expected, env=env)
        return json.loads(result.stdout) if result.stdout else None

    def state(self):
        return json.loads((self.home / ".local/state/fleet-sync/state.json").read_text())

    def current(self):
        return (self.home / "src/fabrig/current").resolve()

    def calls(self):
        return [json.loads(line) for line in (self.home / "systemctl.log").read_text().splitlines()]

    def fabrig_item(self, state):
        return next(i for i in state["items"] if i["item"] == "fabrig")

    def runner(self, check=False):
        loader = importlib.machinery.SourceFileLoader("fleet_sync_test", str(self.source / "tools/fleet-sync"))
        module = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
        loader.exec_module(module)
        args = argparse.Namespace(check=check, timer=False, resume_fd=None)
        return module, module.Runner(args, module.Declarations(self.source, self.home), "hel8")

    def snapshot(self, exclude_mirror=False, root=None):
        root = root or self.home
        rows = {}
        for path in [root, *root.rglob("*")]:
            if exclude_mirror and path.is_relative_to(self.home / "src/fabrig/.fleet-sync/fabrig.git"):
                continue
            info = path.lstat()
            rows[str(path.relative_to(root))] = (info.st_mode, info.st_size, info.st_mtime_ns,
                os.readlink(path) if path.is_symlink() else path.read_bytes() if path.is_file() else None)
        return rows

    def test_empty_home_and_idempotence(self):
        first = self.sync()
        self.assertTrue(any(i["result"] == "changed" for i in first["items"]))
        self.assertEqual(self.current().name, "agents-" + self.sha)
        self.assertFalse((self.current() / "old").exists())
        self.assertEqual(os.readlink(self.home / ".local/bin/fleet-sync"), str(self.home / "src/fabrig/current/tools/fleet-sync"))
        self.assertEqual(self.git(self.home / "src/fabrig/agents", "branch", "--show-current"), "")
        self.assertFalse(any(i["result"] not in ("ok", "warn") for i in self.sync()["items"]))
        cargo = tomllib.loads((self.home / ".cargo/config.toml").read_text())
        self.assertEqual(cargo["build"]["jobs"], 4)
        self.assertFalse((self.home / "src/rust/tmp/post/machines").exists())
        for path in (".profile", ".bashrc", ".config/fabrig/env.sh"):
            self.process("bash", "-n", self.home / path)

    def test_new_main_executes_new_implementation(self):
        self.sync()
        put(self.source / "fleet/env", (self.source / "fleet/env").read_text() + "DEPLOYED=yes\n")
        script = self.source / "tools/fleet-sync"
        put(script, script.read_text().replace('"wrote file"', '"new implementation wrote file"'), True)
        sha = self.publish()
        # Invoke the old immutable release, as a timer would.
        state = self.sync(script=self.current() / "tools/fleet-sync")
        self.assertEqual(self.current().name, "agents-" + sha)
        self.assertIn("DEPLOYED=yes", (self.home / ".config/fabrig/env.sh").read_text())
        self.assertTrue(any(i["reason"] == "new implementation wrote file" for i in state["items"]))
        self.assertEqual(state["agents_sha"], sha)
        self.assertIn("--self-check", (self.home / ".local/state/fleet-sync/run.log").read_text())

    def test_failed_self_check_keeps_current(self):
        self.sync()
        current = self.current()
        settings = self.home / ".claude/settings.json"
        before = settings.read_bytes()
        put(self.source / "fleet/env", "BAD=$USER\n")
        self.publish()
        state = self.sync(script=current / "tools/fleet-sync", expected=1)
        self.assertEqual(self.current(), current)
        self.assertEqual(settings.read_bytes(), before)
        self.assertTrue(any(i["item"] == "agents" and i["result"] == "failed" for i in state["items"]))

    def test_pin_and_hold(self):
        self.sync()
        original = self.current()
        put(self.source / "fleet/env", (self.source / "fleet/env").read_text() + "NEW=1\n")
        self.publish()
        put(self.home / ".config/fleet-sync/pin", self.sha + "\n")
        self.sync()
        self.assertEqual(self.current(), original)
        put(self.home / ".config/fleet-sync/hold", "maintenance\nmore detail\n")
        before = self.snapshot()
        state = self.sync()
        self.assertEqual(state["items"][0]["reason"], "maintenance")
        self.assertEqual(state["items"][0]["result"], "held")
        self.assertEqual(before, self.snapshot())

    def test_dirty_clone_refused(self):
        self.sync()
        put(self.home / "src/fabrig/agents/untracked", "dirt\n")
        state = self.sync(expected=1)
        self.assertIn("dirty clone", state["items"][0]["reason"])

    def test_foreign_and_symlink_clones_refused(self):
        self.sync()
        clone = self.home / "src/fabrig/agents"
        self.git(clone, "remote", "set-url", "origin", self.fabrig_origin)
        self.assertIn("foreign origin", self.sync(expected=1)["items"][0]["reason"])
        moved = clone.with_name("moved")
        clone.rename(moved)
        clone.symlink_to(moved)
        self.assertIn("symlink clone", self.sync(expected=1)["items"][0]["reason"])

    def test_non_symlink_tool_refused(self):
        put(self.home / ".local/bin/fleet-sync", "mine\n")
        state = self.sync(expected=1)
        self.assertEqual((self.home / ".local/bin/fleet-sync").read_text(), "mine\n")
        self.assertTrue(any(i["item"] == "link:fleet-sync" and i["result"] == "failed" for i in state["items"]))

    def test_backups_once_and_modes(self):
        put(self.home / ".cargo/config.toml", "# personal\n")
        put(self.home / ".profile", "# original profile\n")
        self.sync()
        backup = self.home / ".cargo/config.toml.pre-fleet-sync"
        self.assertEqual(backup.read_text(), "# personal\n")
        self.assertFalse((self.home / ".claude/settings.json.pre-fleet-sync").exists())
        put(self.home / ".cargo/config.toml", "# later edit\n")
        self.sync()
        self.assertEqual(backup.read_text(), "# personal\n")
        for path, mode in ((".cargo/config.toml", 0o600), (".profile", 0o644), (".config/fabrig/env.sh", 0o644)):
            self.assertEqual(stat.S_IMODE((self.home / path).stat().st_mode), mode)

    def test_blocks_and_conflicts(self):
        outside = '# personal\nexport DISABLE_AUTOUPDATER=0\ncase $- in *i*) ;; *) return;; esac\n'
        put(self.home / ".bashrc", outside)
        put(self.home / ".profile", "# profile\n")
        put(self.home / ".config/plan/environment.sh", "export TEMPER_FORGEJO=/wrong\n")
        state = self.sync()
        self.assertTrue(any(i["item"].startswith("conflict:") for i in state["items"]))
        bashrc = self.home / ".bashrc"
        self.assertTrue(bashrc.read_text().endswith(outside))
        self.assertTrue(bashrc.read_text().startswith("# >>> fleet-sync >>>\n"))
        before = bashrc.read_text()
        self.sync()
        self.assertEqual(bashrc.read_text(), before)
        # Update an obsolete block, retaining every byte outside it.
        put(bashrc, before.replace('[ ! -f "$HOME/.config/fabrig/env.sh" ] || . "$HOME/.config/fabrig/env.sh"', "# obsolete source"))
        self.sync()
        self.assertEqual(bashrc.read_text(), before)

    def test_codex_preserves_project_bytes(self):
        suffix = '[projects."/tmp/a"]\ntrust_level = "trusted" # keep\n\n[projects."/tmp/b"]\ntrust_level = "untrusted"\n'
        put(self.home / ".codex/config.toml", '# keep comment\nmodel = "old"\npersonality = "friendly"\n' + suffix)
        self.sync()
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
        self.sync()
        result = path.read_bytes().decode()
        self.assertTrue(result.startswith(prefix))
        self.assertTrue(result.endswith(suffix))
        self.assertEqual(tomllib.loads(result)["model"], "gpt-6.1-sol")

    def test_json_semantics_and_file_mtime(self):
        self.sync()
        path = self.home / ".claude/settings.json"
        put(path, json.dumps(json.loads(path.read_text()), sort_keys=True))
        before = path.stat().st_mtime_ns
        state = self.sync()
        self.assertEqual(before, path.stat().st_mtime_ns)
        self.assertEqual(next(i["result"] for i in state["items"] if i["item"] == ".claude/settings.json"), "ok")

    def test_check_writes_nothing_empty_and_configured(self):
        before = self.snapshot(exclude_mirror=True)
        self.sync("--check", expected=1)
        self.assertEqual(before, self.snapshot(exclude_mirror=True))
        self.sync()
        put(self.home / ".cargo/config.toml", "# drift\n")
        before = self.snapshot(exclude_mirror=True)
        self.sync("--check", expected=1)
        self.assertEqual(before, self.snapshot(exclude_mirror=True))

    def test_unknown_host_no_writes(self):
        before = self.snapshot()
        result = self.process("python3", "-I", "-B", self.source / "tools/fleet-sync", "--host", "unknown", expected=2)
        self.assertIn("unknown host", result.stderr)
        self.assertEqual(before, self.snapshot())

    def test_timer_lock_is_quiet(self):
        path = self.home / ".local/state/fleet-sync/lock"
        put(path, "")
        with path.open("r") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            before = self.snapshot()
            self.assertIsNone(self.sync("--timer"))
            self.assertEqual(before, self.snapshot())
            self.assertEqual(self.sync("--check")["items"], [
                {"item": "lock", "result": "busy", "reason": "a run is in progress; check again"}])

    def test_units_reload_only_on_change(self):
        self.sync()
        calls = self.calls()
        self.assertEqual(calls.count(["--user", "daemon-reload"]), 1)
        self.sync()
        self.assertEqual(self.calls().count(["--user", "daemon-reload"]), 1)
        self.assertFalse(any("restart" in a or "stop" in a for a in self.calls()))
        self.assertEqual(next(i["result"] for i in self.sync("--check")["items"] if i["item"] == "enabled:fleet-sync.timer"), "ok")

    def test_role_change_removes_only_owned_units(self):
        roles = self.source / "fleet/units/roles.toml"
        put(roles, roles.read_text() + '"role.service" = ["session"]\n"role.timer" = ["session"]\n')
        put(self.source / "fleet/units/role.service", "[Unit]\nDescription=Role\n[Service]\nType=simple\nExecStart=/bin/true\n")
        put(self.source / "fleet/units/role.timer", "[Unit]\nDescription=Role timer\n[Timer]\nOnCalendar=minutely\n[Install]\nWantedBy=timers.target\n")
        self.publish()
        state = self.sync()
        self.assertTrue(any(i["reason"].startswith("restart pending") for i in state["items"]))
        units = self.home / ".config/systemd/user"
        put(units / "personal.service", "keep\n")
        hosts = self.source / "fleet/hosts.toml"
        put(hosts, hosts.read_text().replace('roles = ["session"]', 'roles = ["builder"]'))
        self.publish()
        self.sync()
        self.assertFalse((units / "role.service").exists())
        self.assertFalse((units / "role.timer").exists())
        self.assertEqual((units / "personal.service").read_text(), "keep\n")
        self.assertIn(["--user", "disable", "--no-reload", "role.service"], self.calls())

    def test_no_bus_fails(self):
        state = self.sync(expected=1, env={**self.env, "FAKE_NO_BUS": "1"})
        self.assertTrue(any(i["item"] == "units" and i["result"] == "failed" for i in state["items"]))
        self.assertTrue(self.state()["unit_reload_pending"])
        self.sync()
        self.assertEqual(self.calls().count(["--user", "daemon-reload"]), 1)
        self.assertFalse(self.state()["unit_reload_pending"])

    def test_status_from_outside_fleet(self):
        script = self.source / "tools/fleet-sync"
        put(script, script.read_text().replace("import socket\n", "import socket\nsocket.gethostname = lambda: 'outside-fleet'\n"), True)
        result = self.process("python3", "-I", "-B", self.source / "tools/fleet-sync", "status", "--json", expected=1)
        self.assertEqual(len(json.loads(result.stdout)["hosts"]), HOST_COUNT)
        calls = [json.loads(line) for line in (self.home / "ssh.log").read_text().splitlines()]
        self.assertEqual(len(calls), HOST_COUNT)

    def test_fabrig_failure_does_not_skip_files(self):
        self.sync()
        self.git(self.home / "src/fabrig/main", "remote", "set-url", "origin", self.origin)
        (self.home / ".cargo/config.toml").unlink()
        state = self.sync(expected=1)
        self.assertTrue(any(i["item"] == "fabrig" and i["result"] == "failed" for i in state["items"]))
        self.assertTrue((self.home / ".cargo/config.toml").exists())

    def test_fabrig_new_head_and_link_repair(self):
        self.sync()
        put(self.fabrig / "tools/new-file", "new\n")
        self.git(self.fabrig, "add", ".")
        self.git(self.fabrig, "commit", "-qm", "fabrig update")
        self.git(self.fabrig, "push", "origin", "main")
        state = self.sync()
        self.assertEqual(state["fabrig_sha"], self.git(self.fabrig, "rev-parse", "HEAD").strip())
        link = self.home / ".local/bin/claim"
        link.unlink()
        state = self.sync()
        self.assertTrue(link.is_symlink())
        self.assertIn("tools/install", (self.home / ".local/state/fleet-sync/run.log").read_text())

    def test_fabrig_non_tools_landing_leaves_main_untouched(self):
        self.sync()
        clone = self.home / "src/fabrig/main"
        installed = self.git(clone, "rev-parse", "HEAD").strip()
        before = self.snapshot(root=clone)
        put(self.fabrig / "docs/new", "docs only\n")
        self.git(self.fabrig, "add", ".")
        self.git(self.fabrig, "commit", "-qm", "non-tool landing")
        self.git(self.fabrig, "push", "origin", "main")
        remote = self.git(self.fabrig, "rev-parse", "HEAD").strip()
        state = self.sync()
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
        self.sync()
        put(self.fabrig / "tools/new", "tool change\n")
        self.git(self.fabrig, "add", ".")
        self.git(self.fabrig, "commit", "-qm", "tool landing")
        self.git(self.fabrig, "push", "origin", "main")
        mirror = self.home / "src/fabrig/.fleet-sync/fabrig.git"
        old = self.git(mirror, "rev-parse", "origin/main")
        before = self.snapshot(exclude_mirror=True)
        state = self.sync("--check", expected=1)
        self.assertEqual(before, self.snapshot(exclude_mirror=True))
        self.assertNotEqual(old, self.git(mirror, "rev-parse", "origin/main"))
        self.assertEqual(self.fabrig_item(state)["result"], "drift")

    def test_check_missing_mirror_and_lock_creates_neither(self):
        self.sync()
        mirror = self.home / "src/fabrig/.fleet-sync/fabrig.git"
        lock = self.home / ".local/state/fabrig/install.lock"
        shutil.rmtree(mirror)
        lock.unlink()  # Fixture cleanup only; fleet-sync must never unlink this inode.
        before = self.snapshot()
        self.assertEqual(self.fabrig_item(self.sync("--check"))["result"], "ok")
        self.assertEqual(before, self.snapshot())
        put(self.fabrig / "docs-only", "ahead\n")
        self.git(self.fabrig, "add", ".")
        self.git(self.fabrig, "commit", "-qm", "non-tool landing")
        self.git(self.fabrig, "push", "origin", "main")
        state = self.sync("--check", expected=1)
        self.assertEqual(self.fabrig_item(state)["result"], "drift")
        self.assertEqual(before, self.snapshot())
        self.assertFalse(mirror.exists())
        self.assertFalse(lock.exists())

    def test_installed_head_missing_from_mirror_counts_changed(self):
        self.sync()
        clone = self.home / "src/fabrig/main"
        put(clone / "local-only", "unpublished commit\n")
        self.git(clone, "add", ".")
        self.git(clone, "commit", "-qm", "installed local commit")
        self.assertEqual(self.fabrig_item(self.sync("--check", expected=1))["result"], "drift")

    def test_install_lock_busy_skips_fabrig_and_continues(self):
        self.sync()
        path = self.home / ".local/state/fabrig/install.lock"
        inode = path.stat().st_ino
        link = self.home / ".local/bin/claim"
        link.unlink()
        link.symlink_to("wrong")
        with path.open("r") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            before = self.snapshot()
            self.assertEqual(self.fabrig_item(self.sync("--check")),
                {"item": "fabrig", "result": "held", "reason": "install lock busy"})
            self.assertEqual(before, self.snapshot())
            (self.home / ".cargo/config.toml").unlink()
            state = self.sync()
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
        self.assertEqual(self.fabrig_item(self.sync(expected=1))["result"], "failed")
        self.assertTrue(lock.is_symlink())
        self.assertEqual(target.read_text(), "never replace or follow\n")
        lock.unlink()
        os.mkfifo(lock, 0o600)
        self.assertIn("not a regular file", self.fabrig_item(self.sync(expected=1))["reason"])
        self.assertTrue(stat.S_ISFIFO(lock.lstat().st_mode))
        lock.unlink()
        lock.mkdir()
        self.assertEqual(self.fabrig_item(self.sync(expected=1))["result"], "failed")
        self.assertTrue(lock.is_dir())

    def test_install_lock_modes_check_read_only_normal_repairs_inode(self):
        self.sync()
        lock = self.home / ".local/state/fabrig/install.lock"
        inode = lock.stat().st_ino
        lock.chmod(0o644)
        lock.parent.chmod(0o755)
        before = self.snapshot()
        self.assertIn("0600", self.fabrig_item(self.sync("--check", expected=1))["reason"])
        self.assertEqual(before, self.snapshot())
        self.sync()
        self.assertEqual(lock.stat().st_ino, inode)
        self.assertEqual(stat.S_IMODE(lock.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(lock.parent.stat().st_mode), 0o700)

    def test_defer_before_lock_keeps_controls_unchanged(self):
        defer = self.home / ".config/fleet-sync/defer-fabrig"
        put(defer, "ops upgrading\nsecond line\n")
        state = self.sync()
        self.assertEqual(self.fabrig_item(state), {"item": "fabrig", "result": "deferred", "reason": "ops upgrading"})
        self.assertFalse((self.home / ".local/state/fabrig/install.lock").exists())
        self.assertFalse((self.home / "src/fabrig/main").exists())
        self.assertEqual(defer.read_text(), "ops upgrading\nsecond line\n")
        self.assertFalse((defer.parent / "pin").exists())
        self.assertFalse((defer.parent / "hold").exists())
        result = self.process("python3", "-I", "-B", self.source / "tools/fleet-sync", "--host", "hel8")
        self.assertIn("1 deferred", result.stdout)

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
        self.sync()
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
        self.sync()
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
        state = self.sync()
        self.assertEqual(next(i["result"] for i in state["items"] if i["item"] == "version:codex"), "warn")

    def test_builder_rendering_and_env_host_override(self):
        self.sync("--host", "hetzner6", env={**self.env, "FLEET_HOST": "hel8"})
        self.assertEqual(self.state()["host"], "hetzner6")
        self.assertNotIn("jobs", tomllib.loads((self.home / ".cargo/config.toml").read_text())["build"])
        self.assertEqual((self.home / "src/rust/tmp/machine.env").read_text(),
                         "PLAN_MIN_DISK_GB=40\nKACHE_MAX_GB=50\nKACHE_LOCAL_ONLY=1\nQA_SLOTS=2\nHEAVY_BUILD_SLOTS=3\n")
        settings = json.loads((self.home / ".claude/settings.json").read_text())
        self.assertNotIn("HEAVY_BUILD_JOBS", settings["env"])
        self.assertNotIn("PATH", settings["env"])
        self.assertTrue(settings["env"]["SKEIN_TEST_CHROMIUM"].startswith(str(self.home)))

    def test_post_machines_check_only_never_written_or_backed_up(self):
        path = self.home / "src/rust/tmp/post/machines"
        put(path, "ops routing\n")
        before = path.stat().st_mtime_ns
        for flags in ((), ("--check",)):
            state = self.sync(*flags)
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
        self.publish()
        self.sync()
        path = self.home / "src/rust/tmp/post/machines"
        self.assertEqual(path.read_text().splitlines()[0], "hel8 local")
        put(policy, '[files]\n"src/rust/tmp/post/machines" = "check"\n')
        self.publish()
        before = path.stat().st_mtime_ns
        state = self.sync()
        self.assertEqual(next(i["result"] for i in state["items"] if i["item"] == "src/rust/tmp/post/machines"), "ok")
        self.assertEqual(path.stat().st_mtime_ns, before)

    def test_invalid_file_policy_no_writes(self):
        put(self.source / "fleet/policy.toml", '[files]\n"src/rust/tmp/post/machines" = "ignore"\n')
        before = self.snapshot()
        self.process("python3", "-I", "-B", self.source / "tools/fleet-sync", "--host", "hel8", expected=2)
        self.assertEqual(before, self.snapshot())

    def test_environment_d_plain_values(self):
        self.sync()
        content = (self.home / ".config/environment.d/90-fabrig.conf").read_text()
        self.assertIn(f"SKEIN_TEST_CHROMIUM={self.home}/.local/opt/chromium-147.0.7727.101/bin/chromium\n", content)
        self.assertNotIn('"', content)
        self.assertNotIn("'", content)
        self.assertNotIn("$", content)

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
        self.sync()
        self.sync("--check")
        self.assertEqual(snapshots, {p: self.snapshot(root=self.home / p) for p in protected + units})
        self.assertFalse(any(any("heavy" in arg for arg in argv) for argv in self.calls()))

    def test_shell_outside_bytes_preserved(self):
        outside = "# keep CRLF\r\n# outside\r\n"
        put(self.home / ".profile", outside)
        put(self.home / ".bashrc", outside)
        self.sync()
        self.assertTrue((self.home / ".profile").read_bytes().decode().startswith(outside))
        self.assertTrue((self.home / ".bashrc").read_bytes().decode().endswith(outside))

    def test_full_sha_pin_rolls_back_current(self):
        self.sync()
        put(self.source / "fleet/env", (self.source / "fleet/env").read_text() + "NEW_VALUE=1\n")
        self.publish()
        self.sync()
        put(self.home / ".config/fleet-sync/pin", self.sha + "\n")
        state = self.sync(script=self.current() / "tools/fleet-sync")
        self.assertEqual(self.current().name, "agents-" + self.sha)
        self.assertEqual(state["agents_sha"], self.sha)
        self.assertNotIn("NEW_VALUE", (self.home / ".config/fabrig/env.sh").read_text())

    def test_timer_age_and_history_pruning(self):
        self.sync("--timer")
        stamp = self.state()["last_timer_end"]
        history = self.home / ".local/state/fleet-sync/runs.jsonl"
        stale = {"end": (dt.datetime.now(dt.UTC) - dt.timedelta(days=8)).isoformat()}
        put(history, json.dumps(stale) + "\n" + history.read_text())
        self.sync()
        self.assertEqual(self.state()["last_timer_end"], stamp)
        self.assertEqual(len(history.read_text().splitlines()), 1)
        self.assertEqual(self.sync("--check")["last_timer_end"], stamp)

    def test_status_unreachable(self):
        self.sync("--timer")
        state = self.sync("status", expected=1)
        self.assertEqual(len(state["hosts"]), HOST_COUNT)
        self.assertIn("unreachable", next(h for h in state["hosts"] if h["host"] == "hetzner3"))
        self.assertTrue(next(h for h in state["hosts"] if h["host"] == "hel8")["last_timer_end"])
        calls = [json.loads(line) for line in (self.home / "ssh.log").read_text().splitlines()]
        self.assertEqual(len(calls), HOST_COUNT - 1)
        self.assertTrue(all("StrictHostKeyChecking=yes" in c and "BatchMode=yes" in c for c in calls))

    def test_release_retention(self):
        self.sync()
        directory = self.home / "src/fabrig/releases"
        for n in range(12):
            path = directory / f"agents-{n:040x}"
            path.mkdir()
            os.utime(path, (n + 1, n + 1))
        self.sync()
        self.assertEqual(len(list(directory.glob("agents-*"))), 10)
        self.assertTrue(self.current().is_dir())

    def test_invalid_declaration_changes_nothing(self):
        put(self.source / "fleet/unparsed.txt", "surprise\n")
        before = self.snapshot()
        self.process("python3", "-I", "-B", self.source / "tools/fleet-sync", "--host", "hel8", expected=2)
        self.assertEqual(before, self.snapshot())


class LandTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="land-test-")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.home = self.directory / "home"
        self.home.mkdir()
        self.env = {**os.environ, "HOME": str(self.home), "GIT_CONFIG_GLOBAL": "/dev/null",
                    "GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_NAME": "Fixture", "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
                    "GIT_COMMITTER_NAME": "Fixture", "GIT_COMMITTER_EMAIL": "fixture@example.invalid"}
        self.source = self.directory / "source"
        self.source.mkdir()
        put(self.source / "tools/land", (ROOT / "tools/land").read_text(), True)
        put(self.source / "tools/check.sh", '#!/bin/bash\necho gate >> "$HOME/gates"\n[[ ! -f "$HOME/fail-gate" ]]\n', True)
        self.git("init", "-b", "main")
        self.git("add", ".")
        self.git("commit", "-qm", "fixture")
        self.origin = self.directory / "origin.git"
        self.run_command("git", "clone", "--bare", self.source, self.origin)
        self.git("remote", "add", "origin", self.origin)
        self.git("switch", "-c", "feature")
        put(self.source / "feature", "feature\n")
        self.git("add", ".")
        self.git("commit", "-qm", "feature")

    def run_command(self, *args, expected=0):
        result = subprocess.run([str(a) for a in args], cwd=self.source, env=self.env,
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result.stdout.strip()

    def git(self, *args):
        return self.run_command("git", *args)

    def land(self, expected=0):
        return self.run_command("python3", "-I", "-B", "tools/land", expected=expected)

    def test_fast_forward(self):
        self.land()
        self.assertEqual(self.git("rev-parse", "HEAD"), self.run_command("git", "--git-dir", self.origin, "rev-parse", "main"))
        self.assertEqual((self.home / "gates").read_text(), "gate\n")

    def test_dirty_refused(self):
        put(self.source / "dirt", "dirt\n")
        self.land(expected=1)
        self.assertFalse((self.home / "gates").exists())

    def test_rebase_checks_twice(self):
        other = self.directory / "other"
        self.run_command("git", "clone", self.origin, other)
        put(other / "upstream", "upstream\n")
        self.run_command("git", "-C", other, "add", ".")
        self.run_command("git", "-C", other, "commit", "-qm", "upstream")
        self.run_command("git", "-C", other, "push", "origin", "main")
        self.land()
        self.assertEqual((self.home / "gates").read_text(), "gate\ngate\n")
        self.assertTrue((self.source / "upstream").exists())

    def test_gate_failure_prevents_push(self):
        before = self.run_command("git", "--git-dir", self.origin, "rev-parse", "main")
        put(self.home / "fail-gate", "fail\n")
        self.land(expected=1)
        self.assertEqual(before, self.run_command("git", "--git-dir", self.origin, "rev-parse", "main"))


if __name__ == "__main__":
    unittest.main()
