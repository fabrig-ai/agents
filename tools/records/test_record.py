#!/usr/bin/env -S python3 -I -B
"""Offline contract tests. Each case owns a temporary HOME and bare origin."""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import fcntl
import json
import os
from pathlib import Path
import runpy
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from offline_test_support import RecordsSeed, call_main

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
    'events/after-landing/hel8/2026-10-29.jsonl': json.dumps(dict(
        id='one', time=STAMP, source='after-landing', host='hel8', kind='land', branch='mc/a')).encode() + b'\n',
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


class RecordTests(RecordsSeed, unittest.TestCase):
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
        self.copy_records_seed()
        self.env = dict(os.environ, RECORDS_REPO=str(self.clone), RECORDS_ORIGIN=str(self.origin))

    def git(self, root, *args):
        result = subprocess.run(['git', '-C', str(root), *args], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        return result.stdout.decode().strip()

    def seed_commit(self, message):
        self.git(self.seed, 'add', '.')
        self.git(self.seed, 'commit', '-m', message)
        self.git(self.seed, 'push', 'origin', 'main')

    def run_record(self, *args, data=b'', code=0, repo=None, wait=True, cli=False, **environment):
        env = dict(self.env, **environment)
        if repo is not None:
            env['RECORDS_REPO'] = str(repo)
        argv = [str(TOOL), *args]
        if not wait:
            program = ("import runpy, sys\nfrom unittest.mock import patch\n"
                       "with patch('time.sleep') as sleep:\n"
                       " status = runpy.run_path(sys.argv.pop(1))['main']()\n"
                       " assert all(1 <= call.args[0] <= 5 for call in sleep.call_args_list)\n"
                       " sys.exit(status)\n")
            argv = [sys.executable, '-I', '-B', '-c', program, *argv]
        if cli or not wait:
            result = subprocess.run(argv, input=data, capture_output=True, env=env)
        else:
            api = API if TOOL == Path(API['__file__']) else runpy.run_path(str(TOOL))
            result = call_main(api['main'], argv, env, data)
        self.assertEqual(result.returncode, code, result.stdout.decode(errors='replace') + result.stderr.decode(errors='replace'))
        return result

    def validate(self, name, data):
        return API['validate'](self.seed, name, data)

    def assert_invalid(self, name, data):
        with self.assertRaises(API['Refusal'], msg=name):
            self.validate(name, data)

    def event(self, identity='one', host='hel8', stamp=STAMP, **extra):
        return json.dumps(dict(id=identity, time=stamp, source='after-landing', host=host, kind='land', **extra)).encode() + b'\n'

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
        name = 'events/after-landing/hel8/2026-10-29.jsonl'
        self.validate(name, self.event(task='mc/a', extra=dict(count=1)))
        for data in (b'[]\n', b'{}\n', b'null\n', b'{oops}\n', b'\n',
                     self.event(stamp='2026-10-30T00:00:00Z'), self.event(host='other'),
                     self.event(task=1), self.event() + self.event(),
                     self.event(payload='x' * (16 * 1024)), self.event(count=float('nan'))):
            self.assert_invalid(name, data)
        for name in ('events/Queue/hel8/2026-10-29.jsonl', 'events/after-landing/-host/2026-10-29.jsonl',
                     'events/after-landing/hel8/2026-02-30.jsonl'):
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
        self.run_record('append', '--as', 'ops', 'after-landing', 'hel8', data=data + data)
        head = self.git(self.clone, 'rev-parse', 'HEAD')
        self.run_record('append', '--as', 'ops', 'after-landing', 'hel8', data=data)
        self.assertEqual(head, self.git(self.clone, 'rev-parse', 'HEAD'))
        for stamp in ('2026-10-29', '2026-10-30'):
            self.assertEqual(len((self.clone / f'events/after-landing/hel8/{stamp}.jsonl').read_bytes().splitlines()), 1)
        self.assert_clean()
        self.run_record('write', '--as', 'ops', 'events/after-landing/hel8/2026-10-29.jsonl', data=self.event(), code=1)
        self.run_record('append', '--as', 'ops', 'Queue', 'hel8', data=self.event(), code=1)

    def test_batch_append_is_atomic_and_idempotent(self):
        data = self.event() + self.event('two')
        self.run_record('append', '--as', 'after-landing', '--batch', 'hel8', data=data + data)
        head = self.git(self.origin, 'rev-parse', 'main')
        self.run_record('append', '--as', 'after-landing', '--batch', 'hel8', data=data)
        self.assertEqual(self.git(self.origin, 'rev-parse', 'main'), head)
        self.assertEqual((self.clone/'events/after-landing/hel8/2026-10-29.jsonl').read_bytes(), data)
        self.assert_clean()

    def test_batch_refuses_all_lines_if_any_source_is_missing_or_invalid(self):
        self.prepare()
        head = self.git(self.origin, 'rev-parse', 'main')
        good = self.event()
        for row in (dict(id='bad', time=STAMP, host='hel8', kind='command'),
                    dict(id='bad', time=STAMP, source='../bad', host='hel8', kind='command'),
                    dict(id='bad', time=STAMP, source='heavy', host='wrong', kind='command'), []):
            with self.subTest(row=row):
                self.run_record('append', '--as', 'after-landing', '--batch', 'hel8',
                                data=good + json.dumps(row).encode() + b'\n', code=1)
                self.assertFalse((self.clone/'events').exists())
                self.assertEqual(self.git(self.origin, 'rev-parse', 'main'), head)
                self.assert_clean()


    @contextmanager
    def push_transport(self, mode):
        directory = self.home / 'transport'
        directory.mkdir(exist_ok=True)
        tool = directory / 'git'
        real_git = shutil.which('git')
        tool.write_text('#!/usr/bin/env -S python3 -I -B\n'
            'import subprocess, sys\nfrom pathlib import Path\n'
            'args = sys.argv[1:]\n'
            f'push = len(args) > 2 and args[2] == "push" and args[1] == {str(self.clone)!r}\n'
            f'mode = {mode!r}\n'
            'if push and mode == "false-success": sys.exit(0)\n'
            f'result = subprocess.run([{real_git!r}, *args])\n'
            'if push and result.returncode == 0 and mode == "lost-ack":\n'
            ' print("synthetic acknowledgement lost", file=sys.stderr)\n'
            ' sys.exit(1)\n'
            'sys.exit(result.returncode)\n')
        tool.chmod(0o700)
        with patch.dict(self.env, PATH=str(directory) + os.pathsep + os.environ['PATH']):
            yield


    def test_success_exit_without_origin_commit_is_not_confirmation(self):
        self.prepare()
        with self.push_transport('false-success'):
            result = self.run_record('append', '--as', 'after-landing', '--batch', 'hel8', data=self.event(), code=2)
        self.assertIn(b'not confirmed by origin', result.stderr)
        self.assertFalse((self.clone / 'events').exists())
        self.assert_clean()


    def test_collector_identity_is_append_only(self):
        data = VALID['events/after-landing/hel8/2026-10-29.jsonl']
        self.run_record('append', '--as', 'after-landing', 'after-landing', 'hel8', data=data)
        self.run_record('write', '--as', 'after-landing', 'README.md', data=b'# No\n', code=1)

    def test_raw_events_refused_for_every_writer(self):
        for writer in ('ops', 'director', 'collect', 'watch', 'after-landing'):
            for source in ('runs', 'queue', 'heavy', 'sessions', 'watch', 'post-sent'):
                with self.subTest(writer=writer, source=source):
                    data = self.event().replace(b'after-landing', source.encode())
                    self.run_record('append', '--as', writer, source, 'hel8', data=data, code=1)
                    self.run_record('write', '--as', writer,
                                    f'events/{source}/hel8/2026-10-29.jsonl', data=data, code=1)
        self.assertFalse((self.clone/'events').exists())

    @contextmanager
    def writer_declaration(self, declaration):
        # Exercise the adjacent declaration without changing the real tool files.
        tool = self.home / 'tool' / 'record'
        API['atomic_write'](tool, TOOL.read_bytes())
        tool.chmod(0o755)
        if declaration is not None:
            API['atomic_write'](tool.with_name('writers.toml'), declaration)
        with patch(__name__ + '.TOOL', tool):
            yield

    def test_writer_declaration_parsed(self):
        self.assertEqual(API['append_writers'](), {'after-landing': ['after-landing']})

    def test_after_landing_source_and_atomic_batch_restrictions(self):
        own = self.event()
        self.run_record('append', '--as', 'after-landing', 'after-landing', 'hel8', data=own)
        head = self.git(self.origin, 'rev-parse', 'main')
        for writer in ('collect', 'watch', 'after-landing'):
            with self.subTest(writer=writer):
                other = 'watch' if writer != 'watch' else 'queue'
                self.run_record('append', '--as', writer, other, 'hel8',
                                data=self.event().replace(b'after-landing', other.encode()), code=1)
        self.run_record('append', '--as', 'after-landing', '--batch', 'hel8',
                        data=own.replace(b'one', b'two') + self.event().replace(b'after-landing', b'runs'), code=1)
        self.assertEqual(head, self.git(self.origin, 'rev-parse', 'main'))
        self.assertEqual((self.clone / 'events/after-landing/hel8/2026-10-29.jsonl').read_bytes(), own)
        self.assertFalse((self.clone / 'events/runs').exists())
        self.assert_clean()

    def test_new_declaration_controls_sources_and_overrides_post_permissions(self):
        with self.writer_declaration(b'[new-producer]\nsources = ["after-landing"]\n[ops]\nsources = ["watch"]\n'):
            self.run_record('append', '--as', 'new-producer', 'after-landing', 'hel8', data=self.event())
            self.run_record('append', '--as', 'ops', 'after-landing', 'hel8', data=self.event(), code=1)
            for writer in ('new-producer', 'ops'):
                self.run_record('write', '--as', writer, 'README.md', data=b'# No\n', code=1)
        self.assert_clean()

    def test_declared_writer_cannot_run_judgement_commands(self):
        commands = [
            ('write', 'README.md'),
            ('draft', 'example', '--coordinator', 'multi', '--mailbox', 's/multi', '--source', 'draft.md'),
            ('priority', 'set', 'example', '--reason', 'no'),
            ('priority', 'show'),
            ('ask', '--question', 'Q', '--option', 'a', '--recommendation', 'a', '--deadline', '+1'),
            ('answer', '1', '--answer', 'a'),
            ('questions',), ('status',),
            ('decide', '--director', '--title', 'T', '--context', 'C', '--options', 'O',
             '--decision', 'D', '--why', 'W'),
        ]
        for command in commands:
            with self.subTest(command=command):
                result = self.run_record(*command, '--as', 'after-landing', code=1)
                self.assertIn(b'declared writer may only append', result.stderr)
        self.assertFalse(self.clone.exists())


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


    def test_automatic_conflict_defers_without_unfinished_rebase(self):
        self.prepare()
        name = 'events/after-landing/hel8/2026-10-29.jsonl'
        path = self.seed / name
        path.parent.mkdir(parents=True)
        path.write_bytes(self.event('remote'))
        self.git(self.seed, 'add', name)
        self.git(self.seed, 'commit', '-m', 'conflicting event file')
        self.hook(self.clone, f'git -C {shlex.quote(str(self.seed))} push origin main >&2\n')
        result = self.run_record('append', '--as', 'after-landing', 'after-landing', 'hel8',
                                 data=self.event('local'), code=3, wait=False)
        self.assertIn(b'rebase conflict', result.stderr)
        self.assertEqual((self.clone / name).read_bytes(), self.event('remote'))
        self.assert_clean()
        self.assertFalse((self.clone / '.git/rebase-merge').exists())

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
        outputs = []
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
                outputs.append(stdout)
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
                    process.communicate()
        self.run_record('pull')
        self.run_record('pull', repo=other)
        self.assert_clean()
        self.assert_clean(other)
        return outputs


    def draft(self, name='example', **options):
        args = ['draft', name, '--as', 'director', '--coordinator', 'multi',
                '--mailbox', 's/multi', '--source', 'skein/docs/design/draft/example.md']
        for key, value in options.items():
            args.extend(['--' + key, str(value)])
        return self.run_record(*args)

    def fields(self, name):
        data = (self.clone / name).read_bytes()
        API['validate'](self.clone, name, data)
        return tomllib.loads(data.decode())

    def ask(self, text='What next?', deadline='+2'):
        return self.run_record('ask', '--as', 'director', '--question', text,
                               '--option', 'a', '--option', 'b',
                               '--recommendation', 'a', '--deadline', deadline)

    def decide_args(self, target='--director', name=None, **texts):
        args = ['decide', '--as', 'director', target]
        if name:
            args.append(name)
        for field in ('title', 'context', 'options', 'decision', 'why'):
            args.extend(['--' + field, texts.get(field, 'choice')])
        return args


    def test_director_commands_publish_and_read_back(self):
        # One short path for every command; full state/argument tables are periodic.
        self.draft(state='active')
        self.run_record('draft', 'example', '--as', 'director', '--coordinator', 'multi',
                        '--mailbox', 's/multi', '--source', 'draft.md', '--state', 'queued', code=1)
        self.assertEqual(self.fields('drafts/example/draft.toml')['state'], 'active')
        self.run_record('priority', 'set', '--as', 'director', 'example', '--reason', 'first')
        priorities = self.run_record('priority', 'show', '--as', 'director').stdout
        self.assertEqual(tomllib.loads(priorities.decode())['draft'][0]['name'], 'example')
        self.assertEqual(self.ask().stdout.splitlines()[-1], b'0001')
        self.assertIn(b'0001', self.run_record('questions', '--as', 'director', '--open').stdout)
        self.run_record('answer', '1', '--as', 'director', '--answer', 'a', '--applied', 'commit:a')
        self.assertEqual(self.run_record('questions', '--as', 'director', '--open').stdout, b'')
        self.run_record(*self.decide_args())
        self.assertEqual(self.fields('director/questions/0001.toml')['applied'], 'commit:a')
        self.assertIn(b'## Decision', (self.clone/'director/decisions/0001.md').read_bytes())
        status = json.loads(self.run_record('status', '--as', 'director', '--json', cli=True).stdout)
        self.assertEqual(status['drafts'][0]['name'], 'example')
        self.assertIn(b'example active', self.run_record('status', '--as', 'director').stdout)
        self.assert_clean()

    def test_malformed_declaration_refuses_before_clone(self):
        with self.writer_declaration(b'broken = ['):
            self.run_record('append', '--as', 'after-landing', 'after-landing', 'hel8',
                            data=self.event(), code=2)
        self.assertFalse(self.clone.exists())

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

    def test_nested_launcher_leads_can_write_close_and_ask(self):
        self.prepare()
        self.run_record('write', '--as', 'lead/q/jig', 'README.md', data=b'# Lead update\n')
        self.run_record('write', '--as', 'lead/q/jig',
                        'drafts/example/parts/tools-records/closing.toml',
                        data=CLOSING.replace(b'lead/tools', b'lead/q/jig'))
        self.run_record('write', '--as', 'lead/q/jig', 'director/questions/next.toml',
                        data=QUESTION.replace(b'by = "director"', b'by = "lead/q/jig"'))
        self.run_record('check')
        for writer in ('after-landing',):
            self.run_record('ask', '--as', writer, '--question', 'Scope?', '--option', 'a',
                            '--recommendation', 'a', '--deadline', '+1', code=1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
