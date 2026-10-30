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


class FleetFixture(unittest.TestCase):
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

    def prepare_integer_machine_env(self):
        """Retain current host declarations with the historical integer schema."""
        path = self.source / "fleet/hosts.toml"
        hosts = tomllib.loads(path.read_text())["hosts"]
        lines = []
        removed = 0
        for name, host in hosts.items():
            lines.append(f"[hosts.{name}]\n")
            for key, value in host.items():
                if key == "machine_env":
                    integers = {k: v for k, v in value.items() if not isinstance(v, str)}
                    removed += len(value) - len(integers)
                    value = integers
                if isinstance(value, dict):
                    literal = "{ " + ", ".join(f"{json.dumps(k)} = {json.dumps(v)}"
                                               for k, v in value.items()) + " }"
                else:
                    literal = json.dumps(value)
                lines.append(f"{key} = {literal}\n")
        put(path, "".join(lines))
        return removed

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


class FleetTest(FleetFixture):
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


if __name__ == "__main__":
    unittest.main()
