"""Offline custody tests: all source logins and ssh endpoints are disposable."""
import ast
import hashlib
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import secrets
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

TOOL = Path(__file__).with_name('agent-logins')


class AgentLoginsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='agent-logins-test-')
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.home = self.base / 'home'
        self.home.mkdir(mode=0o700)
        self.remote = self.base / 'remote'
        self.remote.mkdir(mode=0o700)
        self.pool = self.home / 'src/fabrig/logins/pool'
        release = self.home / 'src/fabrig/releases/fixture'
        (release / 'fleet').mkdir(parents=True)
        (self.home / 'src/fabrig/current').symlink_to(release)
        (release / 'fleet/hosts.toml').write_text(
            '[hosts.hel8]\nssh="local-must-not-ssh"\n'
            '[hosts.worker]\nssh="fixture@fake-host"\n')
        self.bin = self.base / 'bin'
        self.bin.mkdir()
        self.ssh_log = self.base / 'ssh.jsonl'
        ssh = self.bin / 'ssh'
        ssh.write_text('''#!/usr/bin/env python3
import json, os, shlex, subprocess, sys, time
from pathlib import Path
args = sys.argv[1:]
assert args[:5] == ['-T', '-o', 'BatchMode=yes', '--', 'fixture@fake-host'], args
command = shlex.split(args[5])
assert command[:3] == ['python3', '-I', '-B']
operation, path = command[-2:]
with open(os.environ['SSH_LOG'], 'a') as log:
    log.write(json.dumps([operation, path]) + '\\n')
if os.environ.get('NOISY_SSH'):
    sys.stderr.write(os.environ['NOISY_SSH'])
if os.environ.get('SLOW_SSH'):
    time.sleep(0.15)
if operation == 'sha256sum' and os.environ.get('MISMATCH'):
    print('0' * 64 + '  /proc/self/fd/9')
    sys.exit(0)
env = dict(os.environ, HOME=os.environ['REMOTE_HOME'])
sys.exit(subprocess.run(command, env=env).returncode)
''')
        ssh.chmod(0o700)
        self.env = dict(os.environ, HOME=str(self.home), REMOTE_HOME=str(self.remote),
                        SSH_LOG=str(self.ssh_log), PATH=str(self.bin) + os.pathsep + os.environ['PATH'])
        self.secrets = []

    def source(self, home=None, provider='claude', content=None):
        home = home or self.remote
        directory, filename = ('.claude', '.credentials.json') if provider == 'claude' else ('.codex', 'auth.json')
        parent = home / directory
        parent.mkdir(mode=0o700, exist_ok=True)
        data = content or ('SECRET-' + secrets.token_hex(48) + '\n').encode()
        path = parent / filename
        path.write_bytes(data)
        path.chmod(0o600)
        self.secrets.append(data)
        return path, hashlib.sha256(data).hexdigest()

    def run_tool(self, *args, code=0, extra=None):
        result = subprocess.run([sys.executable, '-I', '-B', str(TOOL), *args],
                                env=dict(self.env, **(extra or {})), capture_output=True, timeout=20)
        self.assertEqual(result.returncode, code, (result.stdout, result.stderr))
        self.private_outputs(result.stdout + result.stderr)
        return result

    def private_outputs(self, output=b''):
        metadata = b''
        for path in (self.pool / 'state.json', self.ssh_log):
            if path.exists() and not path.is_symlink():
                metadata += path.read_bytes()
        for data in self.secrets:
            self.assertNotIn(data.rstrip(b'\n'), output + metadata)

    def entries(self):
        return json.loads(self.run_tool('list', '--json').stdout)

    def assert_private(self, path, mode):
        self.assertEqual(stat.S_IMODE(path.lstat().st_mode), mode)
        self.assertEqual(path.lstat().st_uid, os.geteuid())

    def test_capture_end_to_end_and_private_outputs(self):
        expected = {}
        for provider in ('claude', 'codex'):
            _, expected[provider] = self.source(provider=provider)
        self.run_tool('capture', 'worker', extra={'NOISY_SSH': self.secrets[0].decode()})
        entries = self.entries()
        self.assertEqual(len(entries), 2)
        for row in entries:
            provider = row['provider']
            filename = '.credentials.json' if provider == 'claude' else 'auth.json'
            path = self.pool / provider / row['id']
            self.assertEqual(row['sha256'], expected[provider])
            self.assertEqual(row['kind'], 'snapshot')
            self.assertEqual(row['status'], 'bound:worker')
            self.assertEqual(row['origin']['host'], 'worker')
            self.assertEqual(row['moves'][0]['event'], 'capture')
            self.assertEqual(hashlib.sha256((path / filename).read_bytes()).hexdigest(), expected[provider])
            self.assert_private(path, 0o700)
            self.assert_private(path / filename, 0o600)
        self.assert_private(self.pool, 0o700)
        self.assert_private(self.pool / 'state.json', 0o600)
        self.assert_private(self.pool / 'lock', 0o600)
        self.assertEqual(len(self.ssh_log.read_text().splitlines()), 4)

    def test_hash_mismatch_cleans_partial_file(self):
        self.source()
        result = self.run_tool('capture', 'worker', code=4, extra={'MISMATCH': '1'})
        self.assertIn(b'sha256 mismatch', result.stderr)
        self.assertEqual(list((self.pool / 'claude').iterdir()), [])
        self.assertEqual(self.entries(), [])

    def test_idempotence_and_changed_source_retains_old_snapshot(self):
        self.source()
        self.run_tool('capture', 'worker')
        state = (self.pool / 'state.json').stat()
        first = self.entries()[0]
        result = self.run_tool('capture', 'worker')
        self.assertIn(b'unchanged', result.stdout)
        self.assertEqual((self.pool / 'state.json').stat().st_ino, state.st_ino)
        self.assertEqual(self.entries(), [first])
        self.source()
        self.run_tool('capture', 'worker')
        entries = self.entries()
        self.assertEqual(len(entries), 2)
        self.assertIn(first, entries)
        self.assertTrue(all(row['status'] == 'bound:worker' for row in entries))

    def test_absent_sources(self):
        result = self.run_tool('capture', 'worker')
        self.assertEqual(result.stdout.count(b'absent'), 2)
        self.assertEqual(self.entries(), [])
        self.assertEqual(list(self.pool.glob('*/.capture-*')), [])

    def test_local_hel8_never_uses_ssh(self):
        _, digest = self.source(self.home)
        self.run_tool('capture', 'hel8')
        self.assertFalse(self.ssh_log.exists())
        self.assertEqual(self.entries()[0]['sha256'], digest)
        self.assertEqual(self.entries()[0]['status'], 'bound:hel8')

    def test_dry_run_does_not_contact_or_read_sources(self):
        self.source()
        result = self.run_tool('capture', 'worker', '--dry-run')
        self.assertIn(b'dry-run', result.stdout)
        self.assertFalse(self.ssh_log.exists())
        self.assertFalse((self.pool / 'claude').exists())
        self.assertFalse((self.pool / 'state.json').exists())

    def test_register_prepare_and_list(self):
        for provider in ('claude', 'codex'):
            result = self.run_tool('prepare', provider, 'new-login')
            path = self.pool / provider / 'new-login'
            self.assert_private(path, 0o700)
            self.assertEqual(list(path.iterdir()), [])
            expected = f'CODEX_HOME={path} codex login --device-auth\n' if provider == 'codex' else (
                f'CLAUDE_CONFIG_DIR={path} claude auth login\n')
            self.assertEqual(result.stdout.decode(), expected)
            filename = 'auth.json' if provider == 'codex' else '.credentials.json'
            data = ('SECRET-' + secrets.token_hex(48)).encode()
            self.secrets.append(data)
            (path / filename).write_bytes(data)
            (path / filename).chmod(0o600)
            self.run_tool('register', provider, 'new-login')
            self.run_tool('register', provider, 'new-login')
        entries = self.entries()
        self.assertEqual(len(entries), 2)
        for row in entries:
            self.assertEqual(row['status'], 'free')
            self.assertEqual(row['origin'], 'signed-in')
            self.assertEqual(row['kind'], 'own')
        self.assertIn(b'free', self.run_tool('list').stdout)
        self.run_tool('prepare', 'codex', 'new-login', code=4)
        self.run_tool('register', 'claude', 'missing', code=4)

    def test_snapshot_cannot_be_registered_free(self):
        self.source()
        self.run_tool('capture', 'worker')
        row = self.entries()[0]
        self.run_tool('register', row['provider'], row['id'], code=4)
        self.assertEqual(self.entries(), [row])

    def test_register_refuses_unsafe_and_changed_credentials(self):
        self.run_tool('prepare', 'codex', 'own')
        credential = self.pool / 'codex/own/auth.json'
        credential.write_bytes(b'')
        credential.chmod(0o600)
        self.run_tool('register', 'codex', 'own', code=4)
        data = ('SECRET-' + secrets.token_hex(48)).encode()
        self.secrets.append(data)
        credential.write_bytes(data)
        credential.chmod(0o644)
        self.run_tool('register', 'codex', 'own', code=4)
        credential.chmod(0o600)
        saved = credential.with_name('saved')
        credential.rename(saved)
        credential.symlink_to(saved)
        self.run_tool('register', 'codex', 'own', code=4)
        credential.unlink()
        os.link(saved, credential)
        self.run_tool('register', 'codex', 'own', code=4)
        saved.unlink()
        self.run_tool('register', 'codex', 'own')
        before = self.entries()
        credential.write_bytes(data + b'changed')
        self.run_tool('register', 'codex', 'own', code=4)
        self.assertEqual(self.entries(), before)

    def test_wrong_source_modes_and_links(self):
        source, _ = self.source()
        for mode in (0o644, 0o400, 0o660):
            source.chmod(mode)
            self.run_tool('capture', 'worker', code=4)
            self.assertEqual(list((self.pool / 'claude').iterdir()), [])
        source.chmod(0o600)
        source.parent.chmod(0o755)
        self.run_tool('capture', 'worker', code=4)
        source.parent.chmod(0o700)
        copy = source.with_name('saved')
        source.rename(copy)
        source.symlink_to(copy)
        self.run_tool('capture', 'worker', code=4)
        source.unlink()
        os.link(copy, source)
        self.run_tool('capture', 'worker', code=4)

    def test_symlinked_source_parent(self):
        source, _ = self.source()
        parent = source.parent
        saved = self.remote / 'saved'
        parent.rename(saved)
        parent.symlink_to(saved)
        self.run_tool('capture', 'worker', code=4)

    def test_unsafe_shelf_state_lock_and_registered_entry(self):
        self.source()
        self.run_tool('capture', 'worker')
        row = self.entries()[0]
        credential = self.pool / 'claude' / row['id'] / '.credentials.json'
        for path, valid in ((self.pool, 0o700), (self.pool.parent, 0o700),
                            (self.pool / 'state.json', 0o600), (self.pool / 'lock', 0o600),
                            (credential.parent, 0o700), (credential, 0o600)):
            with self.subTest(path=path):
                path.chmod(0o755 if valid == 0o700 else 0o644)
                self.run_tool('list', code=4)
                path.chmod(valid)
        for path in (self.pool / 'state.json', self.pool / 'lock', credential):
            with self.subTest(link=path):
                saved = path.with_name(path.name + '.saved')
                path.rename(saved)
                path.symlink_to(saved)
                self.run_tool('list', code=4)
                path.unlink()
                saved.rename(path)

    def test_symlinked_shelf_and_ancestor_refused(self):
        self.run_tool('list')
        for path in (self.pool, self.pool.parent):
            saved = path.with_name(path.name + '-saved')
            path.rename(saved)
            path.symlink_to(saved)
            self.run_tool('list', code=4)
            path.unlink()
            saved.rename(path)

    def test_unregistered_provider_and_entry_links_are_refused(self):
        self.run_tool('prepare', 'claude', 'prepared')
        for path in (self.pool / 'claude', self.pool / 'claude/prepared'):
            saved = self.base / 'saved-directory'
            path.rename(saved)
            path.symlink_to(saved)
            self.run_tool('list', code=4)
            path.unlink()
            saved.rename(path)

    def test_concurrent_captures_serialize_without_lost_updates(self):
        self.source(provider='claude')
        self.source(provider='codex')
        env = dict(self.env, SLOW_SSH='1')
        children = [subprocess.Popen([sys.executable, '-I', '-B', str(TOOL), 'capture', 'worker'],
                                     env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(4)]
        for child in children:
            self.addCleanup(lambda child=child: child.poll() is None and child.kill())
        outputs = []
        for child in children:
            out, err = child.communicate(timeout=20)
            self.assertEqual(child.returncode, 0, err)
            outputs.append(out + err)
        self.private_outputs(b''.join(outputs))
        self.assertEqual(len(self.entries()), 2)
        self.assertEqual(sum(output.count(b'unchanged') for output in outputs), 6)
        self.assertEqual(list(self.pool.glob('*/.capture-*')), [])

    def test_invalid_input_and_metadata_diagnostics_never_echo_contents(self):
        self.run_tool('capture', 'unknown', code=4)
        self.run_tool('prepare', 'codex', '../escape', code=4)
        self.run_tool('list')
        payload = ('SECRET-' + secrets.token_hex(48)).encode()
        self.secrets.append(payload)
        state = self.pool / 'state.json'
        # Malformed metadata may contain arbitrary text; error stays generic.
        state.write_bytes(payload)
        state.chmod(0o600)
        result = subprocess.run([sys.executable, '-I', '-B', str(TOOL), 'list', '--json'],
                                env=self.env, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 4)
        self.assertEqual(result.stdout, b'')
        self.assertNotIn(payload, result.stderr)

    def test_helper_opens_credentials_only_as_unreadable_path_descriptors(self):
        loader = importlib.machinery.SourceFileLoader('agent_logins_fixture', str(TOOL))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        source, digest = self.source(self.home)
        audit = '''
import os, sys
def audit(event, args):
    if event == 'open':
        path, mode, flags = args
        if str(path).endswith(('.credentials.json', 'auth.json')):
            if not flags & os.O_PATH:
                raise RuntimeError('Python credential read attempted')
sys.addaudithook(audit)
'''
        result = subprocess.run([sys.executable, '-I', '-B', '-c', audit + module.SOURCE,
                                 'sha256sum', str(source)], capture_output=True, env=self.env, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.startswith(digest.encode()))
        self.private_outputs(result.stdout + result.stderr)
        copied = self.base / 'audit-copy'
        with copied.open('wb') as stream:
            result = subprocess.run([sys.executable, '-I', '-B', '-c', audit + module.SOURCE,
                                     'cat', str(source)], stdout=stream, stderr=subprocess.PIPE,
                                    env=self.env, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(hashlib.sha256(copied.read_bytes()).hexdigest(), digest)
        self.private_outputs(result.stderr)
        # Ownership rejection does not require root or a real foreign file.
        info = source.lstat()
        with mock.patch.object(module.os, 'geteuid', return_value=info.st_uid + 1):
            with self.assertRaises(module.Problem):
                module.check(info, False, source)
        # The helper contains no Python read, open(), capture or file wrapper.
        calls = [node for node in ast.walk(ast.parse(module.SOURCE)) if isinstance(node, ast.Call)]
        for call in calls:
            if isinstance(call.func, ast.Name):
                self.assertNotIn(call.func.id, ('open', 'bytes', 'bytearray'))
            if isinstance(call.func, ast.Attribute):
                self.assertNotIn(call.func.attr, ('read', 'read_bytes', 'read_text', 'fdopen'))


if __name__ == '__main__':
    unittest.main()
