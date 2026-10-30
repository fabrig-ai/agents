"""Git transport regressions with local origins and a disposable fake SSH master."""

import json
import os
from pathlib import Path
import re
import shlex
import signal
import stat
import subprocess
import time
import unittest
from unittest.mock import patch

import test_fleet_sync as fixture


# Model OpenSSH's ControlPersist detach: setsid, close command pipes, serve a
# control socket. No real SSH keys, trust, services or network are consulted.
SSH = r'''#!/usr/bin/env python3
import os, pathlib, shlex, socket, sys, time
options = dict(arg.split('=', 1) for arg in sys.argv[1:] if '=' in arg)
path = shlex.split(options['ControlPath'])[0].replace('%C', 'a' * 40)
home = pathlib.Path.home()
if not pathlib.Path(path).exists():
    if options['ControlMaster'] != 'auto':
        sys.exit(42)
    server = socket.socket(socket.AF_UNIX)
    server.bind(path)
    server.listen()
    if os.fork() == 0:
        os.setsid()
        fd = os.open(os.devnull, os.O_RDWR)
        for target in (0, 1, 2):
            os.dup2(fd, target)
        os.close(fd)
        while True:
            client, _ = server.accept()
            client.sendall(str(os.getpid()).encode())
            client.close()
    server.close()
client = socket.socket(socket.AF_UNIX)
client.connect(path)
pid = client.recv(64).decode()
client.close()
if sys.argv[-1] == 'hang':
    sibling = home / 'master.pid.new'
    sibling.write_text(pid)
    sibling.replace(home / 'master.pid')
    time.sleep(60)
print(pid)
'''

GIT = '''#!/usr/bin/env python3
import os, shlex, subprocess, sys
ssh = shlex.split(os.environ['GIT_SSH_COMMAND']) if os.environ.get('GIT_SSH_COMMAND') else [os.environ['GIT_SSH']]
result = subprocess.run(ssh + ['git@github.com', sys.argv[-1]])
sys.exit(result.returncode)
'''


class MultiplexTest(fixture.FleetTest):
    def runner(self, check=False, host="hel8"):
        self.ensure_git()
        module, runner = super().runner(check=check, host=host)
        # Transport lifetime checks need real children, not the gate fixture
        # shortcut that executes Python fake commands in this interpreter.
        runner.cmd = module.Runner.cmd.__get__(runner)
        return module, runner

    def test_rendered_wrapper_environment_shares_fleet_master(self):
        self.sync()
        shell = self.home / '.config/fabrig/env.sh'
        manager = self.home / '.config/environment.d/90-fabrig.conf'
        self.assertIn('export GIT_SSH=fleet-git-ssh\n', shell.read_text())
        self.assertIn('GIT_SSH=fleet-git-ssh\n', manager.read_text())
        self.assertTrue((self.home / '.local/bin/fleet-git-ssh').is_symlink())
        self.fake_transport()
        with patch.dict(os.environ, self.env, clear=True):
            module, runner = self.runner()
            with self.assertRaisesRegex(ValueError, 'whitespace'):
                module.env_value('ssh -o ControlMaster=auto', self.home)
            self.assertEqual(module.env_value('a=b', self.home), 'a=b')
            pid = int(runner.cmd('git', 'probe'))
            self.addCleanup(self.stop_master, pid)
            env = {k: v for k, v in self.env.items() if k not in ('GIT_SSH', 'GIT_SSH_COMMAND')}
            # Each tool can inherit this login-shell environment without a private path.
            command = '. "$HOME/.config/fabrig/env.sh"; exec git probe'
            inherited = self.process('bash', '--noprofile', '--norc', '-c', command, env=env)
            self.assertEqual(int(inherited.stdout), pid)
            # Non-login units get the same declaration and PATH from environment.d.
            values = dict(line.split('=', 1) for line in manager.read_text().splitlines())
            values['PATH'] = str(self.bin) + ':' + values['PATH']  # Fake services before system tools.
            inherited = self.process('git', 'probe', env={**env, **values})
            self.assertEqual(int(inherited.stdout), pid)

    def test_wrapper_forwards_ssh_arguments_and_exit_status(self):
        fixture.put(self.bin / 'ssh', '#!/usr/bin/env python3\nimport json,sys\nprint(json.dumps(sys.argv[1:]))\nsys.exit(37)\n', True)
        args = ['-p', '2222', 'git@github.com', "git-upload-pack 'some repo'"]
        result = self.process(self.source / 'tools/fleet-git-ssh', *args, expected=37)
        self.assertEqual(json.loads(result.stdout), [
            '-T', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
            '-o', 'UpdateHostKeys=no', '-o', 'ConnectTimeout=5',
            '-o', 'ControlMaster=auto', '-o', 'ControlPersist=600',
            '-o', f'ControlPath="{self.home}/.local/state/github-ssh/%C"', *args])

    def test_wrapper_and_runner_enforce_one_option_set(self):
        fixture.put(self.bin / 'ssh', '#!/usr/bin/env python3\nimport json,sys\nprint(json.dumps(sys.argv[1:]))\n', True)
        with patch.dict(os.environ, self.env, clear=True):
            _, runner = self.runner()
            commands = (json.loads(self.process(self.source / 'tools/fleet-git-ssh').stdout),
                        shlex.split(runner.git_ssh_command()))
        expected = {'BatchMode=yes', 'StrictHostKeyChecking=yes', 'UpdateHostKeys=no',
                    'ConnectTimeout=5', 'ControlMaster=auto', 'ControlPersist=600',
                    f'ControlPath="{self.home}/.local/state/github-ssh/%C"'}
        options = tuple({argv[index + 1] for index, value in enumerate(argv[:-1]) if value == '-o'}
                        for argv in commands)
        self.assertEqual(options, (expected, expected))

    def fake_transport(self):
        fixture.put(self.bin / "git", GIT, True)
        fixture.put(self.bin / "ssh", SSH, True)

    def stop_master(self, pid):
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass

    def test_options_permissions_and_reuse_across_runners_and_check(self):
        self.fake_transport()
        with patch.dict(os.environ, self.env, clear=True):
            _, runner = self.runner()
            pid = int(runner.cmd("git", "probe"))
            self.addCleanup(self.stop_master, pid)
            self.assertEqual(os.getsid(pid), pid)
            control = self.home / ".local/state/github-ssh"
            self.assertEqual(stat.S_IMODE(control.stat().st_mode), 0o700)
            command = shlex.split(runner.git_ssh_command())
            for option in ("ControlMaster=auto", "ControlPersist=600", f'ControlPath="{control}/%C"'):
                self.assertIn(option, command)
            _, following = self.runner()
            self.assertEqual(int(following.cmd("git", "probe")), pid)
            _, check = self.runner(check=True)
            self.assertEqual(int(check.cmd("git", "probe")), pid)
            self.assertIn("ControlMaster=no", shlex.split(check.git_ssh_command()))
            self.assertLess(len(os.fsencode(str(control / ("a" * 40)))), 100)
            unit = (fixture.ROOT / "fleet/units/fleet-sync.service").read_text()
            self.assertIn("KillMode=process\n", unit)

    def test_inspections_create_no_directory_or_master(self):
        self.fake_transport()
        with patch.dict(os.environ, self.env, clear=True):
            module, runner = self.runner(check=True)
            for preview in (False, True):
                runner.args.check = not preview
                runner.previewing = preview
                with self.assertRaises(module.CommandError) as error:
                    runner.cmd("git", "probe")
                self.assertEqual(error.exception.code, 42)
                self.assertFalse((self.home / ".local/state/github-ssh").exists())

    def test_control_directory_repairs_mode_and_refuses_symlink(self):
        with patch.dict(os.environ, self.env, clear=True):
            _, runner = self.runner()
            runner.git_ssh_command()
            control = self.home / ".local/state/github-ssh"
            control.chmod(0o755)
            _, check = self.runner(check=True)
            with self.assertRaisesRegex(ValueError, "0700"):
                check.git_ssh_command()
            self.assertEqual(stat.S_IMODE(control.stat().st_mode), 0o755)
            runner.git_ssh_command()
            self.assertEqual(stat.S_IMODE(control.stat().st_mode), 0o700)
            control.rmdir()
            control.symlink_to(self.directory, target_is_directory=True)
            with self.assertRaises(ValueError):
                runner.git_ssh_command()

    def test_expanded_path_limit_and_quoted_home(self):
        with patch.dict(os.environ, self.env, clear=True):
            module, runner = self.runner(check=True)
            runner.home = Path("/" + "x" * 40)
            with self.assertRaisesRegex(ValueError, "under 100 bytes"):
                runner.git_ssh_command()
            fixture.put(self.bin / 'ssh', '#!/usr/bin/env python3\nimport json,sys\nprint(json.dumps(sys.argv[1:]))\n', True)
            for name in ('h %', 'home%h', 'h %h"\\%z'):
                with self.subTest(home=name):
                    runner.home = self.directory / name
                    runner.home.mkdir()
                    runner.safe = module.SafeHome(runner.home)
                    wrapper = json.loads(self.process(self.source / 'tools/fleet-git-ssh',
                                         env={**self.env, 'HOME': str(runner.home)}).stdout)
                    commands = (wrapper, shlex.split(runner.git_ssh_command()))
                    # Parse ssh_config quoting, then expand tokens once as SSH does.
                    paths = tuple(shlex.split(next(arg.split('=', 1)[1] for arg in argv
                                                   if arg.startswith('ControlPath=')))[0]
                                  for argv in commands)
                    expected = str(runner.home).replace('%', '%%') + '/.local/state/github-ssh/%C'
                    self.assertEqual(paths, (expected, expected))
                    expanded = tuple(re.sub(r'%(.)', lambda match: {'%': '%', 'C': 'a' * 40,
                                                                   'h': 'github.com'}[match[1]], path)
                                     for path in paths)
                    literal = str(runner.home / '.local/state/github-ssh' / ('a' * 40))
                    self.assertEqual(expanded, (literal, literal))

    def test_timeout_and_interrupt_do_not_wait_for_or_kill_master(self):
        self.fake_transport()
        with patch.dict(os.environ, self.env, clear=True):
            module, runner = self.runner()
            pid = int(runner.cmd("git", "probe"))
            self.addCleanup(self.stop_master, pid)
            for interrupted in (False, True):
                with self.subTest(interrupted=interrupted):
                    marker = self.home / "master.pid"
                    marker.unlink(missing_ok=True)
                    communicate = subprocess.Popen.communicate
                    delivered = False
                    def interrupt(process, *args, **kwargs):
                        nonlocal delivered
                        deadline = time.monotonic() + 5
                        while not marker.exists() and time.monotonic() < deadline:
                            time.sleep(0.01)
                        self.assertTrue(marker.exists(), "fake SSH client did not attach")
                        if not delivered:
                            # Deliver one interruption; cleanup's second communicate must finish.
                            delivered = True
                            raise module.RunInterrupted(signal.SIGINT)
                        return communicate(process, *args, **kwargs)
                    started = time.monotonic()
                    if interrupted:
                        with patch.object(subprocess.Popen, "communicate", interrupt):
                            with self.assertRaises(module.RunInterrupted):
                                runner.cmd("git", "hang", timeout=10)
                    else:
                        with self.assertRaises(subprocess.TimeoutExpired):
                            runner.cmd("git", "hang", timeout=0.5)
                    self.assertLess(time.monotonic() - started, 8)
                    self.assertEqual(int(marker.read_text()), pid)
                    self.assertFalse(module.ACTIVE_CHILDREN)
                    self.assertEqual(int(runner.cmd("git", "probe")), pid)

    def test_mirror_probes_but_fetches_only_changed_sha(self):
        with patch.dict(os.environ, self.env, clear=True):
            _, runner = self.runner()
            mirror = runner.fabrig_mirror()
            for check in (False, True):
                runner.args.check = check
                runner.log.clear()
                runner.fabrig_mirror()
                self.assertTrue(any("ls-remote" in line for line in runner.log))
                self.assertFalse(any(" fetch " in line for line in runner.log))
                fixture.put(self.fabrig / f"change-{check}", "advance main\n")
                self.git(self.fabrig, "add", ".")
                self.git(self.fabrig, "commit", "-qm", "advance")
                self.git(self.fabrig, "push", "origin", "main")
                runner.log.clear()
                runner.fabrig_mirror()
                self.assertEqual(sum(" fetch " in line for line in runner.log), 1)
                self.assertEqual(self.git(mirror, "rev-parse", "origin/main"), self.git(self.fabrig, "rev-parse", "HEAD"))

    def test_publickey_denial_is_failed_timer_run_with_backoff(self):
        with patch.dict(os.environ, self.env, clear=True):
            module, runner = self.runner()
            runner.args.timer = True
            denial = module.CommandError(128, "Permission denied (publickey)")
            with patch.object(runner, "source", return_value=(runner.d.agents_origin, "unknown")), \
                    patch.object(runner, "cmd", side_effect=denial) as command:
                runner.attempt("agents", runner.release)
                self.assertEqual(command.call_count, 1)
            runner.finish()
            saved = self.state()
            self.assertEqual(saved["consecutive_failures"], 1)
            self.assertTrue(saved["last_failure"])
            self.assertIn("backoff until", runner.backoff_reason())
            with patch.object(runner, "cmd", side_effect=denial):
                self.assertTrue(runner.timer_wait())
            self.assertIn("publickey", (self.home / ".local/state/fleet-sync/run.log").read_text())


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(MultiplexTest(name) for name in MultiplexTest.__dict__ if name.startswith("test_"))
