#!/usr/bin/env -S python3 -I -B
"""Offline contract tests. Each case owns a temporary HOME and bare origin."""

from contextlib import contextmanager
import json
import os
from pathlib import Path
import runpy
import shlex
import subprocess
import tempfile
import unittest
from unittest.mock import patch

TOOL = Path(__file__).with_name('record').resolve()
API = runpy.run_path(str(TOOL))
STAMP = '2026-10-29T12:00:00Z'
DRAFT = f'''coordinator = "multi"
mailbox = "s/multi"
state = "active"
priority = 1
source = "drafts/example.md"
updated = {STAMP}
'''.encode()
CLOSING = f'''ended = {STAMP}
lead = "lead/tools"
landed = ["mc/records-1"]
withdrawn = []
open = []
outcome = "done"
'''.encode()
QUESTION = f'''asked = {STAMP}
by = "director"
question = "What next?"
options = ["a", "b"]
recommendation = "a"
deadline = 2026-10-30T12:00:00Z
'''.encode()
DECISION = b'# A choice\n\n## Context\nContext.\n## Options\na, b\n## Decision\na\n## Why\nBecause.\n'
PRIORITIES = f'''[[draft]]
name = "example"
reason = "first"
since = {STAMP}
'''.encode()
VALID = {
    'README.md': b'# Records\n',
    'AGENTS.md': b'# Rules\n',
    'events/queue/hel8/2026-10-29.jsonl': json.dumps(dict(
        id='one', time=STAMP, source='queue', host='hel8', kind='land', branch='mc/a')).encode() + b'\n',
    'drafts/example/draft.toml': DRAFT,
    'drafts/example/parts/tools-records/brief.md': b'# Brief\n',
    'drafts/example/parts/tools-records/closing.toml': CLOSING,
    'drafts/example/parts/tools-records/closing.md': b'# Closing\n',
    'drafts/example/decisions/0001.md': DECISION,
    'director/decisions/0001.md': DECISION,
    'director/priorities.toml': PRIORITIES,
    'director/questions/0001.toml': QUESTION,
    'sessions/coordinator/s+multi/20261029T1200Z-handover.md': b'# Handover\n',
    'sessions/lead/lead+tools/20261029T1200Z-state.md': b'# State\n',
    'sessions/director/director/20261029T1200Z-common.md': b'# Common\n',
    'sessions/ops/ops/20261029T1200Z-handover.md': b'# Ops\n',
    'drafts/example/README.md': b'# Example\n',
}


class RecordTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='record-test-')
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name)
        # Never consult live HOME, git configuration or credentials.
        env = {k: v for k, v in os.environ.items() if not k.startswith(('GIT_', 'RECORDS_'))}
        env.update(HOME=str(self.home), XDG_CONFIG_HOME=str(self.home / '.config'),
                   GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM='1',
                   GIT_AUTHOR_NAME='Test', GIT_AUTHOR_EMAIL='test@example.invalid',
                   GIT_COMMITTER_NAME='Test', GIT_COMMITTER_EMAIL='test@example.invalid')
        self.environment = patch.dict(os.environ, env, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.origin = self.home / 'origin.git'
        self.clone = self.home / 'records'
        self.seed = self.home / 'seed'
        self.git(self.home, 'init', '--bare', '--initial-branch=main', str(self.origin))
        self.git(self.home, 'clone', str(self.origin), str(self.seed))
        (self.seed / 'README.md').write_bytes(b'# Records\n')
        self.seed_commit('initial records')
        self.env = dict(os.environ, RECORDS_REPO=str(self.clone), RECORDS_ORIGIN=str(self.origin))

    def git(self, root, *args):
        result = subprocess.run(['git', '-C', str(root), *args], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        return result.stdout.decode().strip()

    def seed_commit(self, message):
        self.git(self.seed, 'add', '.')
        self.git(self.seed, 'commit', '-m', message)
        self.git(self.seed, 'push', 'origin', 'main')

    def run_record(self, *args, data=b'', code=0, repo=None, **environment):
        env = dict(self.env, **environment)
        if repo is not None:
            env['RECORDS_REPO'] = str(repo)
        result = subprocess.run([str(TOOL), *args], input=data, capture_output=True, env=env)
        self.assertEqual(result.returncode, code, result.stdout.decode(errors='replace') + result.stderr.decode(errors='replace'))
        return result

    def validate(self, name, data):
        return API['validate'](self.seed, name, data)

    def assert_invalid(self, name, data):
        with self.assertRaises(API['Refusal'], msg=name):
            self.validate(name, data)

    def event(self, identity='one', host='hel8', stamp=STAMP, **extra):
        return json.dumps(dict(id=identity, time=stamp, source='queue', host=host, kind='land', **extra)).encode() + b'\n'

    def prepare(self, repo=None):
        self.run_record('pull', repo=repo)

    def assert_clean(self, clone=None):
        clone = clone or self.clone
        self.assertEqual(self.git(clone, 'status', '--porcelain', '--ignored'), '')
        self.assertEqual(self.git(clone, 'rev-parse', 'HEAD'), self.git(self.origin, 'rev-parse', 'main'))
        self.assertFalse((clone / '.git/rebase-merge').exists())
        self.assertFalse((clone / '.git/rebase-apply').exists())

    def test_every_path_class(self):
        (self.seed / 'drafts/example').mkdir(parents=True)
        for name, data in VALID.items():
            with self.subTest(name=name):
                self.validate(name, data)
                self.assert_invalid(name, data + b'\r\n')
                self.assert_invalid(name, data + b'\xff')
        self.assert_invalid('drafts/example/draft.toml', DRAFT.replace(b'priority = 1', b'priority = true'))
        for old, new in ((b'active', b'unknown'), (b's/multi', b'lead/multi'),
                         (b'2026-10-29T12:00:00Z', b'2026-10-29T12:00:00+01:00')):
            self.assert_invalid('drafts/example/draft.toml', DRAFT.replace(old, new))
        self.assert_invalid('drafts/example/draft.toml', b'broken = [')
        self.assert_invalid('drafts/example/parts/tools-records/closing.toml', CLOSING.replace(b'"done"', b'"failed"'))
        self.assert_invalid('drafts/example/parts/tools-records/closing.toml', CLOSING.replace(b'mc/records-1', b'bad..branch'))
        self.assert_invalid('director/questions/0001.toml', QUESTION.replace(b'"director"', b'"nobody"'))
        self.assert_invalid('director/questions/0001.toml', QUESTION.replace(b'["a", "b"]', b'[1]'))
        self.assert_invalid('director/questions/0001.toml', QUESTION + b'answered = "yesterday"\n')
        self.validate('director/questions/0001.toml', QUESTION + f'answer = "a"\nanswered = {STAMP}\napplied = "commit:abc"\n'.encode())
        self.assert_invalid('director/priorities.toml', PRIORITIES.replace(b'example', b'missing'))
        self.assert_invalid('director/priorities.toml', b'draft = "example"')
        for name in ('director/decisions/0001.md', 'drafts/example/decisions/0001.md'):
            self.assert_invalid(name, DECISION.replace(b'## Why', b'## Else'))
            self.assert_invalid(name, DECISION[2:])
        for name in ('old/README.md', 'old/AGENTS.md', 'old/missions/foo.md', 'STATUS.md',
                     'director/decisions/1.md', 'director/questions/0001.md',
                     'sessions/unknown/ops/20261029T1200Z-state.md',
                     'sessions/ops/nobody/20261029T1200Z-state.md',
                     'sessions/ops/ops/20260230T1200Z-state.md',
                     'sessions/ops/ops/20261029T1200Z-unknown.md',
                     '../README.md', '/README.md', 'x/../README.md', '.git/README.md',
                     'drafts//README.md', './README.md', 'drafts/example/parts/tool/brief.md'):
            self.assert_invalid(name, b'# File\n')

    def test_caps_and_secrets(self):
        (self.seed / 'drafts/example').mkdir(parents=True)
        for name, data in VALID.items():
            kind, cap = API['path_class'](name)
            if cap is not None:
                self.assert_invalid(name, b'a' * (cap + 1))
        for secret in (b'ghp_' + b'x' * 30, b'github_pat_' + b'x' * 30,
                       b'sk-' + b'x' * 30, b'sk-ant-small', b'xoxb-token',
                       b'AKIA' + b'A' * 16, b'-----BEGIN RSA PRIVATE KEY-----'):
            self.assert_invalid('README.md', secret)
        self.run_record('write', '--as', 'ops', 'README.md', data=b'sk-ant-secret', code=1)
        self.assert_clean()

    def test_event_validation(self):
        name = 'events/queue/hel8/2026-10-29.jsonl'
        self.validate(name, self.event(task='mc/a', extra=dict(count=1)))
        for data in (b'[]\n', b'{}\n', b'null\n', b'{oops}\n', b'\n',
                     self.event(stamp='2026-10-30T00:00:00Z'), self.event(host='other'),
                     self.event(task=1), self.event() + self.event(),
                     self.event(payload='x' * (16 * 1024)), self.event(count=float('nan'))):
            self.assert_invalid(name, data)
        for name in ('events/Queue/hel8/2026-10-29.jsonl', 'events/queue/-host/2026-10-29.jsonl',
                     'events/queue/hel8/2026-02-30.jsonl'):
            self.assert_invalid(name, self.event())

    def test_whole_fixture_tree_and_explicit_archive_refusal(self):
        for name, data in {**VALID, 'old/legacy.conf': b'archived arbitrary format\r\n'}.items():
            path = self.seed / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        self.seed_commit('fixture')
        checked = self.run_record('check')
        self.assertIn(b'16 files, 0 refused', checked.stdout)
        self.run_record('check', 'old/legacy.conf', code=1)
        self.run_record('write', '--as', 'ops', 'old/README.md', data=b'no', code=1)
        (self.seed / 'STATUS.md').write_bytes(b'legacy')
        self.seed_commit('unsupported path')
        self.assertIn(b'17 files, 1 refused', self.run_record('check', code=1).stdout)

    def test_append_idempotence_and_midnight(self):
        data = self.event(stamp='2026-10-29T23:59:59Z') + self.event('two', stamp='2026-10-30T00:00:00Z')
        self.run_record('append', '--as', 'ops', 'queue', 'hel8', data=data + data)
        head = self.git(self.clone, 'rev-parse', 'HEAD')
        self.run_record('append', '--as', 'ops', 'queue', 'hel8', data=data)
        self.assertEqual(head, self.git(self.clone, 'rev-parse', 'HEAD'))
        for stamp in ('2026-10-29', '2026-10-30'):
            self.assertEqual(len((self.clone / f'events/queue/hel8/{stamp}.jsonl').read_bytes().splitlines()), 1)
        self.assert_clean()
        self.run_record('write', '--as', 'ops', 'events/queue/hel8/2026-10-29.jsonl', data=self.event(), code=1)
        self.run_record('append', '--as', 'ops', 'Queue', 'hel8', data=self.event(), code=1)

    def test_collector_identity_is_append_only(self):
        data = VALID['events/queue/hel8/2026-10-29.jsonl']
        self.run_record('append', '--as', 'collect', 'queue', 'hel8', data=data)
        self.run_record('write', '--as', 'collect', 'README.md', data=b'# No\n', code=1)

    def test_write_show_pull_and_numbering(self):
        self.run_record('write', '--as', 's/multi', 'drafts/example/draft.toml', data=DRAFT)
        self.run_record('write', '--as', 'director', 'director/priorities.toml', data=PRIORITIES)
        for directory, suffix, body in (('director/decisions', 'md', DECISION),
                                        ('drafts/example/decisions', 'md', DECISION),
                                        ('director/questions', 'toml', QUESTION)):
            for number in (1, 2):
                self.run_record('write', '--as', 'director', f'{directory}/next.{suffix}', data=body)
                self.assertTrue((self.clone / f'{directory}/{number:04d}.{suffix}').is_file())
        self.assertEqual(self.git(self.clone, 'log', '-1', '--format=%s'),
                         'director: write director/questions/0002.toml')
        incoming = self.home / 'input.md'
        incoming.write_bytes(b'# Latest\n')
        self.run_record('write', '--as', 'ops', 'README.md', '--from', str(incoming), '--message', 'Explain why')
        self.assertEqual(self.git(self.clone, 'log', '-1', '--format=%s'), 'Explain why')
        self.git(self.seed, 'pull', '--rebase', 'origin', 'main')
        (self.seed / 'README.md').write_bytes(b'# Remote\n')
        self.seed_commit('fresh read')
        self.assertEqual(self.run_record('show', 'README.md').stdout, b'# Remote\n')
        self.assert_clean()

    def test_clone_checks(self):
        self.prepare()
        self.run_record('write', '--as', 'nobody', 'README.md', data=b'a', code=1)
        for ignored in (False, True):
            if ignored:
                (self.clone / '.git/info/exclude').write_text('dirty\n')
            dirty = self.clone / 'dirty'
            dirty.write_text('untracked')
            self.run_record('pull', code=1)
            dirty.unlink()
        (self.clone / 'README.md').write_text('modified')
        self.run_record('check', code=1)
        self.git(self.clone, 'add', 'README.md')
        self.run_record('pull', code=1)
        self.git(self.clone, 'reset', '--hard', 'HEAD')
        link = self.home / 'linked'
        link.symlink_to(self.clone, target_is_directory=True)
        self.run_record('pull', repo=link, code=1)
        self.git(self.clone, 'remote', 'set-url', 'origin', str(self.home / 'foreign.git'))
        self.run_record('pull', code=1)
        self.git(self.clone, 'remote', 'set-url', 'origin', str(self.origin))
        self.git(self.clone, 'remote', 'set-url', '--push', 'origin', str(self.home / 'foreign.git'))
        self.run_record('pull', code=1)
        self.git(self.clone, 'config', '--unset-all', 'remote.origin.pushurl')
        self.git(self.clone, 'checkout', '-b', 'other')
        self.run_record('pull', code=1)
        self.git(self.clone, 'checkout', 'main')
        self.git(self.clone, 'checkout', '--detach')
        self.run_record('pull', code=1)
        self.git(self.clone, 'checkout', 'main')
        self.git(self.clone, 'remote', 'rename', 'origin', 'missing')
        self.run_record('pull', code=1)
        self.git(self.clone, 'remote', 'rename', 'missing', 'origin')
        self.run_record('pull', RECORDS_BRANCH='other', code=1)
        broken = self.home / 'not-a-clone'
        broken.mkdir()
        self.run_record('pull', repo=broken, code=1)
        # A linked git directory is never accepted.
        original_git = self.clone / '.git'
        original_git.rename(self.clone / 'git-storage')
        original_git.symlink_to(self.clone / 'git-storage', target_is_directory=True)
        self.run_record('pull', code=1)

    def test_tracked_symlinks_and_unpublished_commits_refused(self):
        self.prepare()
        self.git(self.clone, 'commit', '--allow-empty', '-m', 'unpublished')
        self.run_record('pull', code=1)
        self.git(self.clone, 'reset', '--hard', 'origin/main')
        (self.seed / 'linked').symlink_to('/etc/passwd')
        self.seed_commit('symlink')
        self.run_record('check', code=1, repo=self.home / 'symlink-clone')

    def test_check_branch_is_read_only(self):
        self.git(self.seed, 'checkout', '-b', 'mc/records-r1')
        self.git(self.seed, 'push', 'origin', 'mc/records-r1')
        branch_clone = self.home / 'branch'
        self.run_record('check', repo=branch_clone, RECORDS_BRANCH='mc/records-r1')
        self.run_record('write', '--as', 'ops', 'README.md', repo=branch_clone,
                        RECORDS_BRANCH='mc/records-r1', data=b'no', code=1)

    def hook(self, clone, body):
        hook = clone / '.git/hooks/pre-push'
        hook.write_text('#!/bin/sh\nset -eu\n' + body)
        hook.chmod(0o755)
        return hook

    def test_push_race_retries_and_rebase_conflict_recovers_input(self):
        self.prepare()
        # A second writer advances origin after the first writer's fetch/commit.
        marker = self.home / 'injected'
        self.hook(self.clone,
                  f'if test ! -e {shlex.quote(str(marker))}; then\n'
                  f'  touch {shlex.quote(str(marker))}\n'
                  f'  git -C {shlex.quote(str(self.seed))} push origin main >&2\nfi\n')
        (self.seed / 'AGENTS.md').write_text('# Remote rules\n')
        self.git(self.seed, 'add', 'AGENTS.md')
        self.git(self.seed, 'commit', '-m', 'other writer')
        self.run_record('write', '--as', 'ops', 'README.md', data=b'# Local\n')
        self.assertEqual((self.clone / 'AGENTS.md').read_text(), '# Remote rules\n')
        self.assert_clean()
        self.git(self.seed, 'pull', '--ff-only', 'origin', 'main')
        (self.seed / 'README.md').write_text('# Conflicting remote\n')
        self.git(self.seed, 'add', 'README.md')
        self.git(self.seed, 'commit', '-m', 'conflicting writer')
        marker.unlink()
        rejected = self.run_record('write', '--as', 'ops', 'README.md', data=b'# Conflicting local\n', code=1)
        self.assertIn(b'rebase conflict', rejected.stderr)
        self.assertIn(b'# Conflicting local', rejected.stderr)
        self.assert_clean()
        self.assertEqual((self.clone / 'README.md').read_text(), '# Conflicting remote\n')

    def test_retry_limit_resets_to_origin(self):
        self.prepare()
        counter = self.home / 'attempts'
        self.hook(self.clone,
                  f'git -C {shlex.quote(str(self.seed))} pull --ff-only origin main >&2\n'
                  f'echo attempt >> {shlex.quote(str(counter))}\n'
                  f'cp {shlex.quote(str(counter))} {shlex.quote(str(self.seed / "AGENTS.md"))}\n'
                  f'git -C {shlex.quote(str(self.seed))} add AGENTS.md\n'
                  f'git -C {shlex.quote(str(self.seed))} commit -m "advance origin" >&2\n'
                  f'git -C {shlex.quote(str(self.seed))} push origin main >&2\n')
        refused = self.run_record('write', '--as', 'ops', 'README.md', data=b'# Local\n', code=1)
        self.assertIn(b'five attempts', refused.stderr)
        self.assertEqual(len(counter.read_text().splitlines()), 5)
        self.assert_clean()

    def test_rebased_content_is_validated(self):
        original = b'# Start\n' + b'a' * 5000 + b'\n# End\n' + b'b' * 5000 + b'\n'
        (self.seed / 'README.md').write_bytes(original)
        self.seed_commit('large base')
        self.prepare()
        (self.seed / 'README.md').write_bytes(b'remote ' + b'r' * 4000 + b'\n' + original)
        self.git(self.seed, 'add', 'README.md')
        self.git(self.seed, 'commit', '-m', 'remote addition')
        self.hook(self.clone, f'git -C {shlex.quote(str(self.seed))} push origin main >&2\n')
        refused = self.run_record('write', '--as', 'ops', 'README.md',
                                  data=original + b'local ' + b'l' * 4000 + b'\n', code=1)
        self.assertIn(b'byte cap', refused.stderr)
        self.assertNotIn(b'rebase conflict', refused.stderr)
        self.assert_clean()

    @contextmanager
    def racing_clones(self):
        other = self.home / 'other'
        self.prepare()
        self.prepare(other)
        first = self.home / 'first-ready'
        second = self.home / 'second-ready'
        hooks = []
        for clone, own, peer in ((self.clone, first, second), (other, second, first)):
            hooks.append(self.hook(clone,
                         f'touch {shlex.quote(str(own))}\n'
                         'i=0\n'
                         f'while test ! -e {shlex.quote(str(peer))}; do\n'
                         '  i=$((i + 1))\n  test "$i" -lt 200 || exit 1\n  sleep 0.02\ndone\n'))
        try:
            yield other
        finally:
            for hook in hooks:
                hook.unlink(missing_ok=True)

    def race(self, other, arguments, inputs):
        processes = []
        try:
            for clone, args, data in zip((self.clone, other), arguments, inputs):
                process = subprocess.Popen([str(TOOL), *args], stdin=subprocess.PIPE,
                                           stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                           env=dict(self.env, RECORDS_REPO=str(clone)))
                processes.append(process)
                process.stdin.write(data)
                process.stdin.close()
                process.stdin = None
            for process in processes:
                stdout, stderr = process.communicate(timeout=20)
                self.assertEqual(process.returncode, 0, stdout.decode() + stderr.decode())
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
                    process.communicate()
        self.run_record('pull')
        self.run_record('pull', repo=other)
        self.assert_clean()
        self.assert_clean(other)

    def test_concurrent_appends_different_hosts(self):
        with self.racing_clones() as other:
            self.race(other, [('append', '--as', 'ops', 'queue', host) for host in ('hel8', 'hetzner8')],
                      [self.event(host=host) for host in ('hel8', 'hetzner8')])
            for host in ('hel8', 'hetzner8'):
                self.assertEqual((self.clone / f'events/queue/{host}/2026-10-29.jsonl').read_bytes(), self.event(host=host))

    def test_concurrent_next_decisions_and_questions(self):
        for directory, suffix, body in (('director/decisions', 'md', DECISION),
                                        ('director/questions', 'toml', QUESTION)):
            with self.subTest(directory=directory), self.racing_clones() as other:
                self.race(other, [('write', '--as', 'director', f'{directory}/next.{suffix}')] * 2,
                          [body, body.replace(b'choice', b'alternative') if suffix == 'md' else body.replace(b'What next?', b'When next?')])
                paths = list((self.clone / directory).glob(f'*.{suffix}'))
                self.assertEqual({p.stem for p in paths}, {'0001', '0002'})
                self.assertEqual(len({p.read_bytes() for p in paths}), 2)

    def test_usage_and_operational_exit_codes(self):
        self.run_record('write', 'README.md', code=2)
        self.run_record('unknown', code=2)
        self.prepare()
        # A server failure without a concurrent update is an error, and is undone.
        hook = self.origin / 'hooks/pre-receive'
        hook.write_text('#!/bin/sh\nexit 1\n')
        hook.chmod(0o755)
        rejected = self.run_record('write', '--as', 'ops', 'README.md', data=b'# Unpublished\n', code=2)
        self.assertIn(b'input not published', rejected.stderr)
        self.assert_clean()


if __name__ == '__main__':
    unittest.main(verbosity=2)
