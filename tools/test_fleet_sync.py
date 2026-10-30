"""Integration tests: all processes use a disposable HOME and local git origins."""

import argparse
import atexit
import contextlib
import io
import datetime as dt
import fcntl
from functools import lru_cache
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import sys
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


# Every file runs cases serially in its own interpreter. Keep an immutable
# baseline outside the case directory, and restore private repositories/files
# at the same paths (the committed fixture declarations contain absolute URLs).
# Copies never use hardlinks: commits, refs, modes and mtimes remain case-local.
_BASELINE = None
_DEPLOYED = {}


@lru_cache(maxsize=16)
def runner_code(source, filename):
    return compile(source, filename, "exec")


@lru_cache(maxsize=16)
def historical_source(revision, asset="tools/fleet-sync"):
    return subprocess.check_output(["git", "-C", str(ROOT), "show", f"{revision}:{asset}"], text=True)


@lru_cache(maxsize=4)
def historical_archive(revision, subtree):
    return subprocess.check_output(["git", "-C", str(ROOT), "archive", revision, subtree])


class FleetTest(unittest.TestCase):
    def setUp(self):
        global _BASELINE
        if _BASELINE is None:
            self.build_fixture()
            template = tempfile.TemporaryDirectory(prefix="fleet-baseline-")
            atexit.register(template.cleanup)
            shutil.copytree(self.directory, Path(template.name) / "tree", symlinks=True)
            values = {key: getattr(self, key) for key in (
                "directory", "home", "bin", "env", "fabrig", "fabrig_origin",
                "system_bins", "source", "origin", "sha")}
            values["env"] = dict(values["env"])
            _BASELINE = template, values
        else:
            template, values = _BASELINE
            shutil.copytree(Path(template.name) / "tree", values["directory"], symlinks=True,
                            ignore=shutil.ignore_patterns(".git", "*-origin.git"))
            self.__dict__.update(values)
            self.env = dict(values["env"])
            self.addCleanup(shutil.rmtree, self.directory)

    def build_fixture(self):
        # Keep HOME short enough for the real OpenSSH %C socket limit, even inside the gate.
        self.temp = tempfile.TemporaryDirectory(prefix="fs-", dir="/tmp")
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
                                "cargo-nextest": "cargo-nextest 0.9.148", "kache": "kache 1.2.2-gitrev.2", "rustc": "rustc 1.95.0 (fixture)", "chromium": "Chromium 147.0.7727.101",
                                "forgejo": "Forgejo version 17.0.0", "forgejo-runner": "forgejo-runner 13.2.0"}.items():
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

    def ensure_git(self):
        """Materialize private refs/origins only for cases that actually use git."""
        if _BASELINE is None:
            return
        template, _ = _BASELINE
        for relative in ("fabrig-source/.git", "agents-source/.git", "fabrig-origin.git", "agents-origin.git"):
            destination = self.directory / relative
            if not destination.exists():
                shutil.copytree(Path(template.name) / "tree" / relative, destination)

    def process(self, *args, cwd=None, expected=0, env=None):
        if str(args[0]) == "git" or (str(args[0]) == "python3" and "--self-check" not in args):
            self.ensure_git()
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

    def inspect_sync(self, *args, expected=0, env=None, script=None):
        """Real parser/check/status/control paths, without interpreter startup."""
        result = self.cli("python3", "-I", "-B", script or self.source / "tools/fleet-sync",
                          "--host", "hel8", "--json", *args, expected=expected, env=env)
        return json.loads(result.stdout) if result.stdout else None

    def deployed(self, *components):
        """Restore the immutable result of one real deployment, for setup only."""
        global _DEPLOYED
        if components not in _DEPLOYED:
            if components:
                self.component_sync(*components)
            else:
                self.sync()
            template = tempfile.TemporaryDirectory(prefix="fleet-deployed-")
            atexit.register(template.cleanup)
            shutil.copytree(self.home, Path(template.name) / "home", symlinks=True)
            _DEPLOYED[components] = template
        else:
            shutil.rmtree(self.home)
            shutil.copytree(Path(_DEPLOYED[components].name) / "home", self.home, symlinks=True)
        return self.state()

    def release_fixture(self, clone=True):
        """Build the previous-release inputs without running another deployment.

        Candidate checks still run the real release stage/CLI. This fixture only
        supplies its already-existing tree, detached checkout and state.
        """
        release = self.home / "src/fabrig/releases" / ("agents-" + self.sha)
        shutil.copytree(self.source, release, symlinks=True,
                        ignore=shutil.ignore_patterns(".git", "old"))
        put(release / ".fleet-release.json", json.dumps({"origin": str(self.origin), "sha": self.sha}))
        with patch.dict(os.environ, self.env, clear=True):
            module, _ = self.runner()
            module.atomic_link(self.home / "src/fabrig/current", release)
            put(release / ".fleet-promoted", module.now())
        if clone:
            self.process("git", "clone", self.origin, self.home / "src/fabrig/agents")
            self.git(self.home / "src/fabrig/agents", "switch", "--detach", self.sha)
        state = self.component_sync("render", "links", "units")
        state["agents_sha"] = self.sha
        put(self.home / ".local/state/fleet-sync/state.json", json.dumps(state))
        put(self.home / ".local/state/fleet-sync/lock", "")
        return state

    def component_sync(self, *components, check=False, env=None, expected=0, host="hel8", timer=False):
        """Exercise selected production stages; full CLI handoffs have own tests."""
        with patch.dict(os.environ, env or self.env, clear=True):
            module, runner = self.runner(check=check, host=host)
            runner.args.timer = timer
            # Release-stage tests keep real git, self-check and smoke children,
            # then return instead of replacing this test interpreter. The new
            # implementation/lock-fd handoff is exercised through sync().
            if "release" in components:
                self.assertTrue(runner.acquire())
            try:
                with patch.object(os, "execve"):
                    for component in components:
                        runner.attempt(component, getattr(runner, component))
                        if component == "release" and not any(i["result"] == "failed" for i in runner.state["items"]):
                            runner.d = module.Declarations(self.current(), self.home)
                code = runner.finish()
            finally:
                if runner.lock_fd is not None:
                    os.close(runner.lock_fd)
            self.assertEqual(code, expected, runner.state["items"])
            return runner.state

    def state(self):
        return json.loads((self.home / ".local/state/fleet-sync/state.json").read_text())

    def current(self):
        return (self.home / "src/fabrig/current").resolve()

    def calls(self):
        return [json.loads(line) for line in (self.home / "systemctl.log").read_text().splitlines()]

    def fabrig_item(self, state):
        return next(i for i in state["items"] if i["item"] == "fabrig")

    def load_runner(self, script=None):
        script = script or self.source / "tools/fleet-sync"
        loader = importlib.machinery.SourceFileLoader("fleet_sync_test", str(script))
        module = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
        exec(runner_code(Path(loader.path).read_text(), loader.path), module.__dict__)
        return module

    def cli(self, *argv, expected=0, env=None, cwd=None):
        """Run parser/read-only CLI tables in-process; process smoke tests use process()."""
        output, error = io.StringIO(), io.StringIO()
        previous_umask = os.umask(0o077)
        try:
            with (
                contextlib.chdir(cwd or Path.cwd()),
                patch.dict(os.environ, env or self.env, clear=True),
                patch.object(sys, "argv", list(map(str, argv[3:]))),
                patch.object(os, "execve", side_effect=AssertionError("read-only CLI attempted exec")),
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(error),
            ):
                module = self.load_runner(argv[3])
                try:
                    code = module.main()
                except SystemExit as exit:
                    code = exit.code or 0
                except (OSError, ValueError, subprocess.SubprocessError) as failure:
                    print(f"fleet-sync: {failure}", file=error)
                    code = 1
        finally:
            os.umask(previous_umask)
        result = subprocess.CompletedProcess(argv, code, output.getvalue(), error.getvalue())
        self.assertEqual(code, expected, result.stdout + result.stderr)
        return result

    def runner(self, check=False, host="hel8"):
        module = self.load_runner()
        args = argparse.Namespace(check=check, timer=False, resume_fd=None)
        declarations = module.Declarations(self.source, self.home)
        runner = module.Runner(args, declarations, declarations.host(host))
        command = runner.cmd
        def cmd(*argv, **kwargs):
            if argv[0] == "git":
                self.ensure_git()
            search = f"{self.home}/.local/bin:{self.home}/.cargo/bin:" + os.environ["PATH"]
            executable = shutil.which(str(argv[0]), path=search)
            path = Path(executable) if executable else None
            # Stage tests execute their existing Python fake programs directly.
            # SSH keeps its real transport child; installed artifacts keep their
            # real version probes. Full sync() always uses actual children.
            if (path is None or path.parent != self.bin or path.name == "ssh"
                    or not path.read_bytes().startswith(b"#!/usr/bin/env python3\n")):
                return command(*argv, **kwargs)
            output, error = io.StringIO(), io.StringIO()
            code = 0
            with (
                patch.object(sys, "argv", [str(path), *map(str, argv[1:])]),
                patch.dict(os.environ, {**runner.environment(), "PATH": search, **kwargs.get("extra_env", {})}),
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(error),
            ):
                try:
                    exec(runner_code(path.read_text(), str(path)), {"__name__": "__main__", "__file__": str(path)})
                except SystemExit as exit:
                    code = exit.code or 0
            out, err = output.getvalue(), error.getvalue()
            runner.log.append(f"$ {module.shlex.join(map(str, argv))}\n{out}{err}")
            if code not in kwargs.get("allowed", (0,)):
                raise module.CommandError(code, f"{path.name} exited {code}: {(err or out).strip()[-600:]}")
            return out.encode() if kwargs.get("binary") else out.strip()
        runner.cmd = cmd
        return module, runner

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

    def test_empty_home_and_idempotence(self):
        protected = ("src/fabrig/claims", "src/fabrig/leases", "src/fabrig/queue", "src/fabrig/slots",
                     ".local/state/heavy", ".local/state/agents-heavy", ".local/state/fabrig/heavy",
                     "src/rust/tmp/heavy", "src/rust/tmp/codex-run", "src/rust/tmp/owners", "src/rust/tmp/logins",
                     "src/rust/tmp/post/inbox", "src/rust/tmp/post/outbox", "src/rust/tmp/post/sent")
        for relative in protected:
            put(self.home / relative / "sentinel", "opaque state\n")
        before = {relative: self.snapshot(root=self.home / relative) for relative in protected}
        unit = "gate-worker.service"
        put(self.source / "fleet/units" / unit,
            "# fleet-sync: start-once\n[Unit]\nDescription=Gate worker\n[Service]\nType=simple\nExecStart=/bin/true\n[Install]\nWantedBy=default.target\n")
        roles = self.source / "fleet/units/roles.toml"
        put(roles, roles.read_text() + f'"{unit}" = ["session"]\n')
        self.sha = self.publish()
        first = self.sync()
        enable = ["--user", "enable", "--now", "--no-reload", unit]
        self.assertEqual(self.calls().count(enable), 1)
        self.assertLess(self.calls().index(["--user", "daemon-reload"]), self.calls().index(enable))
        self.assertTrue((self.home / (unit + ".active")).exists())
        self.assertTrue(any(i["result"] == "changed" for i in first["items"]))
        self.assertEqual(self.current().name, "agents-" + self.sha)
        self.assertFalse((self.current() / "old").exists())
        self.assertEqual(os.readlink(self.home / ".local/bin/fleet-sync"), str(self.home / "src/fabrig/current/tools/fleet-sync"))
        self.assertEqual(self.git(self.home / "src/fabrig/agents", "branch", "--show-current"), "")
        self.assertFalse(any(i["result"] not in ("ok", "warn") for i in self.component_sync("release", "fabrig", "links", "render", "units", "versions")["items"]))
        self.assertEqual(self.calls().count(enable), 1)
        cargo = tomllib.loads((self.home / ".cargo/config.toml").read_text())
        self.assertEqual(cargo["build"]["jobs"], 4)
        self.assertFalse((self.home / "src/rust/tmp/post/machines").exists())
        for path in (".profile", ".bashrc", ".config/fabrig/env.sh"):
            self.process("bash", "-n", self.home / path)

        self.assertEqual(before, {relative: self.snapshot(root=self.home / relative) for relative in protected})

    def test_new_main_executes_new_implementation(self):
        self.release_fixture()
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
        self.release_fixture()
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
        self.release_fixture()
        original = self.current()
        put(self.source / "fleet/env", (self.source / "fleet/env").read_text() + "NEW=1\n")
        self.publish()
        put(self.home / ".config/fleet-sync/pin", self.sha + "\n")
        self.component_sync("release")
        self.assertEqual(self.current(), original)
        put(self.home / ".config/fleet-sync/hold", "maintenance\nmore detail\n")
        before = self.snapshot()
        state = self.sync()
        self.assertEqual(state["items"][0]["reason"], "maintenance")
        self.assertEqual(state["items"][0]["result"], "held")
        self.assertEqual(before, self.snapshot())

    def test_dirty_clone_refused(self):
        self.release_fixture()
        put(self.home / "src/fabrig/agents/untracked", "dirt\n")
        state = self.component_sync("release", expected=1)
        self.assertIn("dirty clone", state["items"][0]["reason"])

    def test_foreign_and_symlink_clones_refused(self):
        self.release_fixture()
        clone = self.home / "src/fabrig/agents"
        self.git(clone, "remote", "set-url", "origin", self.fabrig_origin)
        self.assertIn("foreign origin", self.component_sync("release", expected=1)["items"][0]["reason"])
        moved = clone.with_name("moved")
        clone.rename(moved)
        clone.symlink_to(moved)
        self.assertIn("symlink clone", self.component_sync("release", expected=1)["items"][0]["reason"])


    def test_check_writes_nothing_empty_and_configured(self):
        before = self.snapshot(exclude_mirror=True)
        self.inspect_sync("--check", expected=1)
        self.assertEqual(before, self.snapshot(exclude_mirror=True))
        self.release_fixture()
        put(self.home / ".cargo/config.toml", "# drift\n")
        before = self.snapshot(exclude_mirror=True)
        self.inspect_sync("--check", expected=1)
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
            self.assertIsNone(self.inspect_sync("--timer"))
            self.assertEqual(before, self.snapshot())
            self.assertEqual(self.inspect_sync("--check")["items"], [
                {"item": "lock", "result": "busy", "reason": "a run is in progress; check again"}])


    def test_status_from_outside_fleet(self):
        script = self.source / "tools/fleet-sync"
        put(script, script.read_text().replace("import socket\n", "import socket\nsocket.gethostname = lambda: 'outside-fleet'\n"), True)
        result = self.process("python3", "-I", "-B", self.source / "tools/fleet-sync", "status", "--json", expected=1)
        self.assertEqual(len(json.loads(result.stdout)["hosts"]), HOST_COUNT)
        calls = [json.loads(line) for line in (self.home / "ssh.log").read_text().splitlines()]
        self.assertEqual(len(calls), HOST_COUNT)


    def test_status_unreachable(self):
        self.release_fixture()
        self.component_sync("versions", timer=True)
        state = self.sync("status", expected=1)
        self.assertEqual(len(state["hosts"]), HOST_COUNT)
        self.assertIn("unreachable", next(h for h in state["hosts"] if h["host"] == "hetzner3"))
        self.assertTrue(next(h for h in state["hosts"] if h["host"] == "hel8")["last_timer_end"])
        calls = [json.loads(line) for line in (self.home / "ssh.log").read_text().splitlines()]
        self.assertEqual(len(calls), HOST_COUNT - 1)
        self.assertTrue(all("StrictHostKeyChecking=yes" in c and "BatchMode=yes" in c for c in calls))

    def test_release_retention(self):
        self.release_fixture()
        directory = self.home / "src/fabrig/releases"
        for n in range(12):
            path = directory / f"agents-{n:040x}"
            path.mkdir()
            os.utime(path, (n + 1, n + 1))
        self.component_sync("release")
        self.assertEqual(len(list(directory.glob("agents-*"))), 10)
        self.assertTrue(self.current().is_dir())

    def test_invalid_declaration_changes_nothing(self):
        put(self.source / "fleet/unparsed.txt", "surprise\n")
        before = self.snapshot()
        self.process("python3", "-I", "-B", self.source / "tools/fleet-sync", "--host", "hel8", expected=2)
        self.assertEqual(before, self.snapshot())


if __name__ == "__main__":
    unittest.main()
