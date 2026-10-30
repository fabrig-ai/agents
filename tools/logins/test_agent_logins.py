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
        self.remote2 = self.base / 'remote2'
        self.remote2.mkdir(mode=0o700)
        self.pool = self.home / 'src/fabrig/logins/pool'
        release = self.home / 'src/fabrig/releases/fixture'
        (release / 'fleet').mkdir(parents=True)
        (self.home / 'src/fabrig/current').symlink_to(release)
        (release / 'fleet/hosts.toml').write_text(
            '[hosts.hel8]\nssh="local-must-not-ssh"\n'
            '[hosts.worker]\nssh="fixture@fake-host"\n'
            '[hosts.worker2]\nssh="fixture@fake-host-2"\n')
        self.bin = self.base / 'bin'
        self.bin.mkdir()
        self.ssh_log = self.base / 'ssh.jsonl'
        ssh = self.bin / 'ssh'
        ssh.write_text('''#!/usr/bin/env python3
import json, os, shlex, subprocess, sys, time
from pathlib import Path
args = sys.argv[1:]
assert args[:4] == ['-T', '-o', 'BatchMode=yes', '--'], args
remote_home = {'fixture@fake-host': os.environ['REMOTE_HOME'],
               'fixture@fake-host-2': os.environ['REMOTE_HOME_2']}[args[4]]
command = shlex.split(args[5])
assert command[:3] == ['python3', '-I', '-B']
operation, path = command[5:7]
with open(os.environ['SSH_LOG'], 'a') as log:
    log.write(json.dumps([operation, path]) + '\\n')
if os.environ.get('NOISY_SSH'):
    sys.stderr.write(os.environ['NOISY_SSH'])
if os.environ.get('SLOW_SSH'):
    time.sleep(0.15)
if operation == os.environ.get('FAIL_OPERATION'):
    sys.exit(int(os.environ.get('FAIL_CODE', '4')))
if operation == 'remove' and os.environ.get('CHANGE_BEFORE_REMOVE'):
    changed = Path(remote_home) / path.removeprefix('~/')
    changed.write_bytes(os.environ['CHANGE_BEFORE_REMOVE'].encode())
if operation == 'sha256sum' and (os.environ.get('MISMATCH')
        or (os.environ.get('MISMATCH_AT') == 'stage' and '.agent-logins-' in path)
        or (os.environ.get('MISMATCH_AT') == 'credential' and '.agent-logins-' not in path)):
    print('0' * 64 + '  /proc/self/fd/9')
    sys.exit(0)
env = dict(os.environ, HOME=remote_home)
if operation == 'remove' and os.environ.get('MISSING_HASH_PATH'):
    env['PATH'] = os.environ['MISSING_HASH_PATH']
code = subprocess.run(command, env=env).returncode
if operation == 'install' and code == 0 and os.environ.get('DROP_AFTER_INSTALL'):
    code = 255
sys.exit(code)
''')
        ssh.chmod(0o700)
        sha = self.bin / 'sha256sum'
        sha.write_text('''#!/usr/bin/env python3
import os, subprocess, sys
descriptor = int(sys.argv[-1].rsplit('/', 1)[1])
fragment = os.environ.get('BAD_HASH_PATH')
if fragment and fragment in os.readlink('/proc/self/fd/' + str(descriptor)):
    print('0' * 64 + '  ' + sys.argv[-1])
    sys.exit(0)
sys.exit(subprocess.run(['/usr/bin/sha256sum', *sys.argv[1:]], pass_fds=(descriptor,)).returncode)
''')
        sha.chmod(0o700)
        self.env = dict(os.environ, HOME=str(self.home), REMOTE_HOME=str(self.remote),
                        REMOTE_HOME_2=str(self.remote2),
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
        calls = [node for helper in (module.SOURCE, module.MUTATE)
                 for node in ast.walk(ast.parse(helper)) if isinstance(node, ast.Call)]
        for call in calls:
            if isinstance(call.func, ast.Name):
                self.assertNotIn(call.func.id, ('open', 'bytes', 'bytearray'))
            if isinstance(call.func, ast.Attribute):
                self.assertNotIn(call.func.attr, ('read', 'read_bytes', 'read_text', 'fdopen'))

    def own(self, provider='claude', identity='spare'):
        self.run_tool('prepare', provider, identity)
        data = ('SECRET-' + secrets.token_hex(48)).encode()
        self.secrets.append(data)
        path = self.pool / provider / identity / ('.credentials.json' if provider == 'claude' else 'auth.json')
        path.write_bytes(data)
        path.chmod(0o600)
        self.run_tool('register', provider, identity)
        return path, hashlib.sha256(data).hexdigest()

    def captured(self, provider='claude'):
        source, digest = self.source(provider=provider)
        self.run_tool('capture', 'worker')
        row = next(row for row in self.entries() if row['provider'] == provider)
        path = self.pool / provider / row['id'] / ('.credentials.json' if provider == 'claude' else 'auth.json')
        return source, path, row

    def test_release_lend_round_trips_with_refreshed_credentials(self):
        for provider in ('claude', 'codex'):
            with self.subTest(provider=provider):
                source, path, row = self.captured(provider)
                _, refreshed = self.source(provider=provider)
                self.assertNotEqual(refreshed, row['sha256'])
                noisy = {'NOISY_SSH': self.secrets[-1].decode()}
                self.run_tool('release', 'worker', provider, extra=noisy)
                self.assertFalse(source.exists())
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), refreshed)
                free = next(entry for entry in self.entries() if entry['id'] == row['id'])
                self.assertEqual(free['status'], 'free')
                self.assertEqual(free['sha256'], refreshed)
                self.assertEqual(free['moves'][-1]['event'], 'release')
                self.run_tool('lend', row['id'], 'worker', extra=noisy)
                self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), refreshed)
                self.assertTrue(path.exists())
                self.assert_private(source, 0o600)
                self.assert_private(source.parent, 0o700)
                self.assertEqual(next(entry for entry in self.entries() if entry['id'] == row['id'])['status'], 'lent:worker')
                self.run_tool('release', 'worker', provider)
                self.assertFalse(source.exists())
                self.assertEqual(next(entry for entry in self.entries() if entry['id'] == row['id'])['status'], 'free')

    def test_release_mismatches_restore_stale_shelf_and_preserve_host(self):
        source, path, row = self.captured()
        original_shelf = path.read_bytes()
        _, refreshed = self.source()
        original_host = source.read_bytes()
        for extra in ({'BAD_HASH_PATH': '.release-new-'}, {'MISMATCH': '1'},
                      {'BAD_HASH_PATH': str(path)}, {'FAIL_OPERATION': 'remove', 'FAIL_CODE': '7'}):
            with self.subTest(extra=extra):
                self.run_tool('release', 'worker', 'claude', code=4, extra=extra)
                self.assertEqual(path.read_bytes(), original_shelf)
                self.assertEqual(source.read_bytes(), original_host)
                self.assertEqual(self.entries(), [row])
                self.assertEqual(list(path.parent.glob('.release-*')), [])

    def test_release_checks_for_source_refresh_before_unlink(self):
        source, path, row = self.captured()
        original = path.read_bytes()
        changed = 'SECRET-' + secrets.token_hex(48)
        self.secrets.append(changed.encode())
        result = self.run_tool('release', 'worker', 'claude', code=4,
                               extra={'CHANGE_BEFORE_REMOVE': changed})
        self.assertIn(b'source changed', result.stderr)
        self.assertEqual(source.read_bytes(), changed.encode())
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(self.entries(), [row])

    def test_lend_mismatches_keep_shelf_and_destination_absent(self):
        path, digest = self.own()
        before = self.entries()
        for extra in ({'BAD_HASH_PATH': str(path)}, {'MISMATCH_AT': 'stage'},
                      {'FAIL_OPERATION': 'install', 'FAIL_CODE': '7'}, {'MISMATCH_AT': 'credential'}):
            with self.subTest(extra=extra):
                self.run_tool('lend', 'spare', 'worker', code=4, extra=extra)
                self.assertFalse((self.remote / '.claude/.credentials.json').exists())
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)
                self.assertEqual(self.entries(), before)
                self.assertEqual(list(self.remote.glob('.claude/.agent-logins-*')), [])

    def test_lend_refuses_existing_credentials_links_and_held_entries(self):
        path, digest = self.own()
        source, _ = self.source()
        before = source.read_bytes()
        result = self.run_tool('lend', 'spare', 'worker', code=4)
        self.assertIn(b'release first', result.stderr)
        self.assertEqual(source.read_bytes(), before)
        source.unlink()
        source.symlink_to(path)
        self.assertIn(b'release first', self.run_tool('lend', 'spare', 'worker', code=4).stderr)
        source.unlink()
        self.run_tool('lend', 'spare', 'worker')
        self.run_tool('lend', 'spare', 'worker2', code=4)
        self.assertFalse((self.remote2 / '.claude/.credentials.json').exists())
        self.run_tool('register', 'claude', 'spare', code=4)
        self.run_tool('capture', 'worker', code=4)

    def test_release_requires_entry_and_present_source(self):
        source, _ = self.source()
        result = self.run_tool('release', 'worker', 'claude', code=4)
        self.assertIn(b'no bound or lent entry', result.stderr)
        self.assertTrue(source.exists())
        self.run_tool('capture', 'worker')
        source.unlink()
        self.run_tool('release', 'worker', 'claude', code=4)
        self.assertTrue(all(row['status'].startswith('bound:') for row in self.entries()))

    def test_release_selects_lent_then_latest_bound_placeholder(self):
        source, path, old = self.captured()
        self.source()
        self.run_tool('capture', 'worker')
        newest = next(row for row in self.entries() if row['id'] != old['id'])
        self.run_tool('release', 'worker', 'claude')
        self.assertEqual(next(row for row in self.entries() if row['id'] == old['id'])['status'], 'bound:worker')
        self.assertEqual(next(row for row in self.entries() if row['id'] == newest['id'])['status'], 'free')
        self.run_tool('lend', newest['id'], 'worker')
        self.run_tool('release', 'worker', 'claude')
        self.assertEqual(next(row for row in self.entries() if row['id'] == newest['id'])['status'], 'free')

    def test_swap_success_and_lend_failure_after_release(self):
        source, old_path, old = self.captured()
        path, digest = self.own()
        self.run_tool('swap', 'worker', 'claude', 'spare')
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), digest)
        states = {row['id']: row['status'] for row in self.entries()}
        self.assertEqual(states[old['id']], 'free')
        self.assertEqual(states['spare'], 'lent:worker')
        result = self.run_tool('swap', 'worker', 'claude', old['id'], code=4,
                               extra={'FAIL_OPERATION': 'stage'})
        self.assertIn(b'SWAP FAILED AFTER RELEASE', result.stderr)
        self.assertIn(b'has no claude credential', result.stderr)
        self.assertFalse(source.exists())
        self.assertTrue(all(row['status'] == 'free' for row in self.entries()))
        self.assertTrue(path.exists())
        self.assertTrue(old_path.exists())

    def test_swap_provider_and_id_errors_leave_released_login_free(self):
        source, path, row = self.captured()
        self.own('codex')
        result = self.run_tool('swap', 'worker', 'claude', 'spare', code=4)
        self.assertIn(b'SWAP FAILED AFTER RELEASE', result.stderr)
        self.assertFalse(source.exists())
        self.assertTrue(all(entry['status'] == 'free' for entry in self.entries()))

    def test_dry_transfers_have_no_source_access_or_metadata_changes(self):
        source, path, row = self.captured()
        self.own()
        state = (self.pool / 'state.json').read_bytes()
        log = self.ssh_log.read_bytes()
        self.run_tool('release', 'worker', 'claude', '--dry-run')
        self.run_tool('lend', 'spare', 'worker', '--dry-run')
        self.assertEqual((self.pool / 'state.json').read_bytes(), state)
        self.assertEqual(self.ssh_log.read_bytes(), log)
        self.assertTrue(source.exists())

    def test_lend_creates_private_parent_and_supports_local_hel8(self):
        path, digest = self.own('codex')
        self.run_tool('lend', 'spare', 'hel8')
        credential = self.home / '.codex/auth.json'
        self.assertEqual(hashlib.sha256(credential.read_bytes()).hexdigest(), digest)
        self.assert_private(credential.parent, 0o700)
        self.assert_private(credential, 0o600)
        self.run_tool('release', 'hel8', 'codex')
        self.assertFalse(credential.exists())
        self.assertFalse(self.ssh_log.exists())

    def test_ambiguous_ids_and_unsafe_destination_are_refused(self):
        self.own('claude')
        self.own('codex')
        self.run_tool('lend', 'spare', 'worker', code=4)
        self.run_tool('prepare', 'claude', 'unique')
        path = self.pool / 'claude/unique/.credentials.json'
        path.write_bytes(b'dummy-private-fixture')
        path.chmod(0o600)
        self.run_tool('register', 'claude', 'unique')
        parent = self.remote / '.claude'
        parent.mkdir(mode=0o755)
        parent.chmod(0o755)
        self.run_tool('lend', 'unique', 'worker', code=4)
        parent.rmdir()
        parent.symlink_to(self.remote2)
        self.run_tool('lend', 'unique', 'worker', code=4)

    def test_concurrent_lends_have_only_one_holder(self):
        self.own()
        children = [subprocess.Popen([sys.executable, '-I', '-B', str(TOOL), 'lend', 'spare', host],
                                     env=dict(self.env, SLOW_SSH='1'), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    for host in ('worker', 'worker2')]
        for child in children:
            self.addCleanup(lambda child=child: child.poll() is None and child.kill())
        outputs = []
        for child in children:
            out, err = child.communicate(timeout=30)
            outputs.append(out + err)
        self.assertEqual(sorted(child.returncode for child in children), [0, 4])
        self.private_outputs(b''.join(outputs))
        self.assertEqual(sum((home / '.claude/.credentials.json').exists() for home in (self.remote, self.remote2)), 1)
        self.assertTrue(self.entries()[0]['status'].startswith('lent:'))

    def test_uncertain_transfers_block_reuse_and_preserve_copies(self):
        source, path, row = self.captured()
        _, digest = self.source()
        self.run_tool('release', 'worker', 'claude', code=4, extra={'FAIL_OPERATION': 'remove', 'FAIL_CODE': '255'})
        self.assertTrue(source.exists())
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)
        state = json.loads((self.pool / 'state.json').read_text())
        self.assertEqual(state['pending']['event'], 'release')
        self.assertEqual(state['entries'][0]['status'], 'bound:worker')
        self.assertEqual(len(list(path.parent.glob('.release-old-*'))), 1)
        self.assertIn(b'operator recovery required', self.run_tool('list', code=4).stderr)
        self.run_tool('release', 'worker', 'claude', code=4)

    def test_concurrent_swaps_hold_one_lock_across_release_and_lend(self):
        source, path, row = self.captured()
        self.own(identity='spare-one')
        self.own(identity='spare-two')
        children = [subprocess.Popen([sys.executable, '-I', '-B', str(TOOL), 'swap', 'worker', 'claude', identity],
                                     env=dict(self.env, SLOW_SSH='1'), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    for identity in ('spare-one', 'spare-two')]
        for child in children:
            self.addCleanup(lambda child=child: child.poll() is None and child.kill())
        for child in children:
            out, err = child.communicate(timeout=30)
            self.assertEqual(child.returncode, 0, err)
            self.private_outputs(out + err)
        entries = self.entries()
        lent = [entry for entry in entries if entry['status'] == 'lent:worker']
        self.assertEqual(len(lent), 1)
        self.assertEqual(sum(entry['status'] == 'free' for entry in entries), 2)
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), lent[0]['sha256'])

    def test_uncertain_lend_install_never_leaves_reusable_free_state(self):
        path, digest = self.own()
        self.run_tool('lend', 'spare', 'worker', code=4, extra={'FAIL_OPERATION': 'install', 'FAIL_CODE': '255'})
        state = json.loads((self.pool / 'state.json').read_text())
        self.assertEqual(state['pending']['event'], 'lend')
        self.assertTrue(path.exists())
        self.run_tool('lend', 'spare', 'worker2', code=4)
        self.run_tool('list', '--json', code=4)

    def test_lost_install_reply_preserves_host_copy_and_blocks_another_loan(self):
        path, digest = self.own()
        self.run_tool('lend', 'spare', 'worker', code=4, extra={'DROP_AFTER_INSTALL': '1'})
        credential = self.remote / '.claude/.credentials.json'
        self.assertEqual(hashlib.sha256(credential.read_bytes()).hexdigest(), digest)
        self.assertTrue(path.exists())
        self.run_tool('lend', 'spare', 'worker2', code=4)
        self.assertIn(b'operator recovery required', self.run_tool('list', code=4).stderr)

    def test_missing_hash_executable_is_not_treated_as_absent_credential(self):
        path, digest = self.own()
        missing = self.base / 'no-sha'
        missing.mkdir()
        (missing / 'python3').symlink_to(sys.executable)
        self.run_tool('lend', 'spare', 'worker', code=4,
                      extra={'MISMATCH_AT': 'credential', 'MISSING_HASH_PATH': str(missing)})
        self.assertTrue((self.remote / '.claude/.credentials.json').exists())
        state = json.loads((self.pool / 'state.json').read_text())
        self.assertEqual(state['pending']['event'], 'lend')
        self.run_tool('lend', 'spare', 'worker2', code=4)


if __name__ == '__main__':
    unittest.main()
