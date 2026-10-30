#!/usr/bin/env -S python3 -I -B
"""Offline collectors: scrubbed producer shapes, temporary HOME and bare origin.

Provenance: hel8 runs.tsv/meta, heavy.tsv/events.jsonl, claude agents and
session-context output, and post's header writer. Claims: tools/slots/claim
create_claim (hel8's directory was empty). Queue: tools/queue/mq log_batch,
attempt and run_step (queue.jsonl absent on hel8). Leases: mc/lease-1's
lease.md and tools/lease (not deployed on hel8). All identities, addresses,
subjects and paths below are synthetic. Mail fixtures contain headers only.
"""

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import quote

TOOL = Path(__file__).with_name('record-collect').resolve()
API = runpy.run_path(str(TOOL))
STAMP = '2026-10-29T11:00:00Z'
END = '2026-10-29T11:02:00Z'

class FixedDate(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls.fromisoformat(END.replace('Z', '+00:00'))

RUN = '20261029T110000Z-aaaa'
SESSION = '12345678-1111-2222-3333-123456789abc'
SUBJECT = 'pkg:example-core'
MESSAGE = '20261029T110000Z-12345678'


class CollectTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='collect-test-')
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name)
        clock = patch.dict(API['stage'].__globals__, datetime=FixedDate)
        clock.start()
        self.addCleanup(clock.stop)
        env = {k: v for k, v in os.environ.items() if not k.startswith(('GIT_', 'RECORDS_'))}
        env.update(HOME=str(self.home), XDG_CONFIG_HOME=str(self.home / '.config'),
                   GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM='1',
                   GIT_AUTHOR_NAME='Test', GIT_AUTHOR_EMAIL='test@example.invalid',
                   GIT_COMMITTER_NAME='Test', GIT_COMMITTER_EMAIL='test@example.invalid')
        self.environment = patch.dict(os.environ, env, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.fabrig = self.home / 'src/fabrig'
        self.tmp = self.home / 'src/rust/tmp'
        self.state = self.home / '.local/state/record-collect'
        self.clone = self.home / 'records'
        self.origin = self.home / 'origin.git'
        self.seed = self.home / 'seed'
        self.git(self.home, 'init', '--bare', '--initial-branch=main', str(self.origin))
        self.git(self.home, 'clone', str(self.origin), str(self.seed))
        self.write(self.seed / 'README.md', '# Test records\n')
        self.git(self.seed, 'add', '.')
        self.git(self.seed, 'commit', '-m', 'seed')
        self.git(self.seed, 'push', 'origin', 'main')
        self.env = dict(os.environ, RECORDS_REPO=str(self.clone), RECORDS_ORIGIN=str(self.origin))
        self.bin = self.home / 'bin'
        self.bin.mkdir()
        self.env['PATH'] = str(self.bin) + os.pathsep + os.environ['PATH']
        self.fake('session-start', "import os, pathlib, sys\nassert sys.argv[1:] == ['names', '--json']\nprint((pathlib.Path(os.environ['HOME']) / 'names.json').read_text())\n")
        self.write(self.home / 'names.json', '[]')
        self.fake('claude', """import json, os
from pathlib import Path
assert __import__('sys').argv[1:] == ['agents', '--json']
print((Path(os.environ['HOME']) / 'agents.json').read_text())
""")
        self.fake('session-context', """import sys
if sys.argv[1:] == ['--capabilities']:
 print('fired-markers')
 sys.exit(0)
if sys.argv[1:] == ['--fired', '--json']:
 from pathlib import Path
 import os
 print((Path(os.environ['HOME']) / 'fired.json').read_text())
 sys.exit(0)
assert sys.argv[1] == '--name'
print('12345678: 125,000 of 1,000,000 tokens (12%) at 2026-10-29T11:00:00Z; 42 calls; 0 compaction(s); threshold 75%')
""")
        self.write(self.home / 'agents.json', '[]')
        self.write(self.home / 'fired.json', '[]')
        self.write(self.tmp / 'post/machines', 'hel8 local\nhetzner8 user@host.invalid\n')

    def git(self, root, *args):
        r = subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.strip()

    def write(self, path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(data)
        return path

    def json(self, path, data):
        return self.write(path, json.dumps(data) + '\n')

    def fake(self, name, program):
        path = self.write(self.bin / name, '#!/usr/bin/env python3\n' + program)
        path.chmod(0o700)

    def run_collect(self, *sources, options=(), code=0, **env):
        wrapper = ("import runpy,sys\nfrom datetime import datetime\n"
                   f"class FixedDate(datetime):\n @classmethod\n def now(cls,tz=None): return cls.fromisoformat({END!r}.replace('Z','+00:00'))\n"
                   "sys.argv=sys.argv[1:]\napi=runpy.run_path(sys.argv[0])\n"
                   "api['main'].__globals__['datetime']=FixedDate\nsys.exit(api['main']())")
        r = subprocess.run(['python3', '-I', '-B', '-c', wrapper, str(TOOL), *sources, '--since', STAMP, *options],
                           capture_output=True, text=True, env=dict(self.env, **env))
        self.assertEqual(r.returncode, code, r.stderr + r.stdout)
        return r

    def dry(self, *sources, **kwargs):
        r = self.run_collect(*sources, options=('--dry-run',), **kwargs)
        return [json.loads(line) for line in r.stdout.splitlines() if line.startswith('{')]

    def events(self, source):
        root = self.fabrig / 'events' / source
        return [json.loads(line) for path in sorted(root.glob('*.jsonl')) for line in path.read_text().splitlines()]

    def cursor(self, source):
        return json.loads((self.state / (source + '.json')).read_text())

    def runs_fixture(self, header=True):
        task = self.fabrig / 'tasks/example.md'
        if header:
            self.write(task, '+++\ntask = "example"\nbranch = "mc/example"\ncoordinator = "s/example"\n'
                       'draft = "wave"\narea = "tools"\npart = "collect"\n+++\nSynthetic task.\n')
        else:
            self.write(task, 'Use branch `mc/fallback`.\n')
        self.write(self.tmp / f'codex-run/{RUN}/meta',
                   f'caller=\nto=lead/H/tools@hel8\nmodel=example-model\neffort=high\nread_only=0\n'
                   f'task={task}\ndir={self.fabrig}/slots/1\nreport={self.fabrig}/notes/result.md\n'
                   f'resume_of=20261029T100000Z-bbbb\nstarted={STAMP}\non_stop=\nslot_hold=\n')
        self.run_row = '\t'.join([RUN, 'lead/H/tools@hel8', STAMP, END, '0', '2',
                                  'example-model', 'high', str(task), str(self.fabrig / 'notes/result.md'),
                                  'example-thread', '100/40/20', '0']) + '\n'
        self.write(self.tmp / 'codex-run/runs.tsv', self.run_row)
        return task

    def queue_fixture(self):
        self.write(self.fabrig / 'main/tools/queue/leads.txt', 'tools lead/H/tools@hel8\n')
        row = dict(start=STAMP, end=END, outcome='red', selection=['tools'], dry=False,
                   branches=[dict(name='ready/tools/example', tip='a' * 40, timestamp=1793271600),
                             dict(name='ready/tools/conflict', tip='b' * 40, timestamp=1793271601)],
                   conflicts=[dict(name='ready/tools/conflict', tip='b' * 40, step='merge')],
                   steps=[dict(name='tools', green=False, duration=2.5, suites=[
                       dict(name='collector', green=False, returncode=1, duration=2.4, cwd='/synthetic',
                            command=['example-check'])])],
                   target_cleanup={'count': 2, 'gb': 0.5}, log='/synthetic/queue.log', posts=[])
        self.json(self.fabrig / 'notes/queue.jsonl', row)
        return row

    def claim_fixture(self):
        return self.json(self.fabrig / 'claims/hel8-1',
                         dict(owner='lead/H/tools', what=f'run {RUN}', created=STAMP, lent_by='pool'))

    def heavy_fixture(self):
        cwd = str(self.fabrig / 'slots/1')
        self.write(self.tmp / 'logs/heavy.tsv', '\t'.join([
            '7', 'build', END, '12', '60', '0', '6.7', cwd,
            '/synthetic/heavy.log', 'example-check', 'synthetic build']) + '\n')
        self.json(self.tmp / 'heavy/events.jsonl', dict(
            boot='example-boot', event='release_end', id='example-token:release_end', token='example-token',
            queue='example-queue', source='submit', repo=cwd, tree='example-tree', policy='example-policy',
            lane='build', label='synthetic build', outcome='completed', code=0,
            time_ns=int(API['timestamp'](END).timestamp()) * 1_000_000_000))
        self.claim_fixture()

    def session_fixture(self, name='lead/H/tools'):
        row = dict(pid=123, id=SESSION[:8], sessionId=SESSION, name=name, cwd='/synthetic',
                   kind='background', state='working', status='busy',
                   startedAt=int(API['timestamp'](STAMP).timestamp()) * 1000)
        self.json(self.home / 'agents.json', [row])
        return row

    def lease_fixture(self):
        row = dict(subject=SUBJECT, owner='s/example', what='synthetic wave', since=STAMP,
                   lends=['mc/example'], waiters=[dict(owner='s/next', what='next wave', since=STAMP)])
        path = self.json(self.fabrig / 'leases' / quote(SUBJECT, safe=''), row)
        return path, row

    def post_fixture(self):
        path = self.write(self.tmp / f'post/lead+H+tools/new/{MESSAGE}.md',
                          f'Id: {MESSAGE}\nFrom: s/example@hel8\nTo: lead/H/tools@hel8\n'
                          'Re: 20261029T100000Z-87654321\nSubject: Synthetic status\n\n')
        (path.parent.parent / 'cur').mkdir()
        seconds = API['timestamp'](STAMP).timestamp()
        os.utime(path, (seconds, seconds))
        return path

    def test_runs_header_usage_and_idempotence(self):
        self.runs_fixture()
        self.run_collect('runs')
        events = self.events('runs')
        self.assertEqual([e['kind'] for e in events], ['run-start', 'run-end'])
        end = events[1]
        for key, value in dict(task='example', branch='mc/example', coordinator='s/example',
                               draft='wave', area='tools', part='collect', run=RUN,
                               tokens_in=100, tokens_cached=40, tokens_out=20, minutes=2,
                               exit=0, tries=2, post_status=0).items():
            self.assertEqual(end[key], value)
        self.assertEqual(end['resumed_from'], '20261029T100000Z-bbbb')
        head = self.git(self.origin, 'rev-parse', 'main')
        r = self.run_collect('runs', options=('--since', '2099-01-01T00:00Z'))
        self.assertIn('runs: 0 events', r.stderr)
        self.assertEqual(head, self.git(self.origin, 'rev-parse', 'main'))
        self.assertEqual(self.cursor('runs')['files'][str(self.tmp / 'codex-run/runs.tsv')]['offset'], len(self.run_row.encode()))
        self.assertEqual((self.state / 'runs.json').stat().st_mode & 0o777, 0o600)
        self.assertFalse(self.clone.exists())

    def test_task_fallback_without_header(self):
        task = self.runs_fixture(header=False)
        events = self.dry('runs')
        self.assertTrue(all(e['branch'] == 'mc/fallback' and e['coordinator'] == 'H' and e['area'] == 'tools' for e in events))
        self.write(task, 'Push ready/tools/fallback before finishing.\n')
        self.assertEqual(API['task_keys'](task), {'branch': 'ready/tools/fallback'})
        self.assertFalse(self.state.exists())

    def test_malformed_task_headers_keep_runs_and_other_events(self):
        task = self.runs_fixture()
        healthy_task = self.write(self.fabrig/'tasks/healthy.md',
                    '+++\ntask="healthy"\nbranch="mc/healthy"\n'
                    'coordinator="s/healthy"\ndraft="healthy"\narea="healthy"\npart="runs"\n+++\n')
        healthy_run = '20261029T110000Z-bbbb'
        meta = self.tmp/f'codex-run/{RUN}/meta'
        self.write(self.tmp/f'codex-run/{healthy_run}/meta',
                   meta.read_text().replace(str(task), str(healthy_task)))
        healthy_row = self.run_row.replace(RUN, healthy_run).replace(str(task), str(healthy_task))
        self.write(self.tmp/'codex-run/runs.tsv', self.run_row + healthy_row)
        self.claim_fixture()
        cases = (
            ('unclosed', '+++\nbranch="PRIVATE CONTENT"\n', 'unclosed task header'),
            ('toml', '+++\nbranch: PRIVATE CONTENT\n+++\n', 'invalid TOML task header'),
            ('non-string', '+++\nbranch="mc/partial"\narea=42\n+++\n', 'task join keys must be nonempty strings'),
            ('empty', '+++\nbranch="mc/partial"\narea=""\n+++\n', 'task join keys must be nonempty strings'),
            ('blank', '+++\narea="  "\n+++\n', 'task join keys must be nonempty strings'),
            ('unreadable', None, 'unreadable task file'),
            ('encoding', b'\xffPRIVATE CONTENT', 'unreadable task file'),
        )
        for kind, text, reason in cases:
            with self.subTest(kind=kind):
                if task.is_dir():
                    task.rmdir()
                else:
                    task.unlink(missing_ok=True)
                if text is None:
                    task.mkdir()  # EISDIR is unreadable even when tests run as root.
                elif isinstance(text, bytes):
                    task.write_bytes(text)
                else:
                    task.write_text(text)
                result = self.run_collect('runs', 'claims', options=('--dry-run',))
                rows = [json.loads(line) for line in result.stdout.splitlines() if line.startswith('{')]
                broken = [row for row in rows if row.get('run') == RUN]
                healthy = [row for row in rows if row.get('run') == healthy_run]
                self.assertEqual([row['kind'] for row in broken], ['run-start', 'run-end'])
                self.assertEqual([row['kind'] for row in healthy], ['run-start', 'run-end'])
                for row in broken:
                    self.assertEqual(row['header_error'], reason)
                    self.assertTrue(set(API['JOIN']).isdisjoint(row))
                for row in healthy:
                    self.assertNotIn('header_error', row)
                    self.assertEqual({key:row[key] for key in API['JOIN']},
                        dict(task='healthy', branch='mc/healthy', coordinator='s/healthy',
                             draft='healthy', area='healthy', part='runs'))
                self.assertTrue(any(row['source'] == 'claims' for row in rows))
                self.assertIn('runs: 4 events, 2 header errors', result.stderr)
                self.assertNotIn('PRIVATE CONTENT', result.stdout + result.stderr)
                self.assertFalse(self.state.exists())
                normal = self.run_collect('runs', 'claims')
                self.assertIn('runs: 4 events, 2 header errors', normal.stderr)
                self.assertEqual(self.events('runs'), [row for row in rows if row['source'] == 'runs'])
                if kind != 'encoding':
                    shutil.rmtree(self.state)
                    shutil.rmtree(self.fabrig/'events')
        # The final case also advances the cursor without repeating annotated facts.
        self.assertEqual(len(self.events('runs')), 4)
        self.assertIn('runs: 0 events, 0 header errors', self.run_collect('runs').stderr)

    def test_task_permission_error_is_content_free(self):
        with patch.object(Path, 'read_text', side_effect=PermissionError('PRIVATE CONTENT')):
            self.assertEqual(API['task_keys']('/synthetic/task.md'),
                             {'header_error': 'unreadable task file'})

    def test_active_run_without_completion_and_missing_task(self):
        task = self.runs_fixture()
        task.unlink()
        (self.tmp / 'codex-run/runs.tsv').unlink()
        events = self.dry('runs')
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['kind'], 'run-start')
        self.assertEqual(events[0]['header_error'], 'unreadable task file')
        self.assertTrue(set(API['JOIN']).isdisjoint(events[0]))

    def test_queue_batch_attempts_and_recovery_not_duplicated(self):
        row = self.queue_fixture()
        path = self.fabrig / 'notes/queue.jsonl'
        with path.open('a') as output:
            output.write(json.dumps(dict(row, event='recovery')) + '\n')
        self.run_collect('queue')
        events = self.events('queue')
        batch, attempt, conflict = events
        self.assertEqual(batch['target_cleanup'], {'count': 2, 'gb': 0.5})
        self.assertEqual(batch['steps'][0]['suites'][0]['duration'], 2.4)
        self.assertEqual(batch['selection'], ['tools'])
        self.assertEqual((attempt['area'], attempt['coordinator'], attempt['rejected_step']), ('tools', 'H', 'tools'))
        self.assertEqual((conflict['outcome'], conflict['rejected_step']), ('conflict', 'merge'))
        self.assertNotIn('command', batch['steps'][0]['suites'][0])
        self.assertIn('queue: 0 events', self.run_collect('queue').stderr)

    def test_heavy_completion_and_claim_join(self):
        self.heavy_fixture()
        self.run_collect('heavy')
        event, = self.events('heavy')
        self.assertEqual((event['kind'], event['run'], event['lane']), ('command', RUN, 'build'))
        self.assertEqual((event['wait_s'], event['run_s'], event['exit']), (12, 60, 0))
        self.assertEqual(event['token'], 'example-token')
        self.assertEqual(event['outcome'], 'completed')
        self.assertNotIn('command', event)
        self.assertIn('heavy: 0 events', self.run_collect('heavy').stderr)
        (self.fabrig / 'claims/hel8-1').unlink()
        (self.tmp / 'heavy/events.jsonl').unlink()
        self.assertEqual(self.dry('heavy'), [])

    def test_heavy_multiline_rows_keep_identity_and_replay_after_rotation(self):
        self.heavy_fixture()
        path = self.tmp / 'logs/heavy.tsv'
        normal = path.read_text()
        expected, = self.dry('heavy')
        multiline = normal.replace('example-check', 'for item in 1 2 3; do\nstep one\nstep two\ndone')
        self.write(path, multiline)
        result = self.run_collect('heavy')
        self.assertIn('heavy: skipped 0 malformed rows', result.stderr)
        self.assertEqual(self.events('heavy'), [expected])
        self.assertEqual(self.cursor('heavy')['files'][str(path)]['offset'], len(multiline.encode()))
        replacement = self.write(path.with_suffix('.new'), normal)
        replacement.replace(path)
        self.assertIn('heavy: 0 events', self.run_collect('heavy').stderr)
        self.assertEqual(self.events('heavy'), [expected])

    def test_heavy_skips_orphans_oversized_and_interrupted_rows(self):
        self.heavy_fixture()
        path = self.tmp / 'logs/heavy.tsv'
        normal = path.read_text()
        incomplete = normal.rsplit('\t', 1)[0] + '\n'
        oversized = normal.rstrip('\n') + '\textra\n'
        self.write(path, 'orphan continuation\n' + incomplete + oversized + normal)
        result = self.run_collect('heavy')
        self.assertIn('heavy: skipped 3 malformed rows', result.stderr)
        self.assertEqual(len(self.events('heavy')), 1)
        self.assertEqual(self.cursor('heavy')['files'][str(path)]['offset'], path.stat().st_size)
        result = self.run_collect('heavy')
        self.assertIn('heavy: 0 events', result.stderr)
        self.assertIn('heavy: skipped 0 malformed rows', result.stderr)

    def test_heavy_unfinished_tail_retried_from_row_start(self):
        self.heavy_fixture()
        path = self.tmp / 'logs/heavy.tsv'
        normal = path.read_text()
        # Both newline-terminated command continuations and a partial physical
        # line must retain the entire logical row for a later append.
        for tail in ('unfinished\ncontinuation\n', 'unfinished\ncontinuation'):
            with self.subTest(tail=tail):
                second = normal.replace('7\t', '8\t', 1).replace('example-check', tail + 'done')
                prefix, suffix = second.split('done', 1)
                self.write(path, normal + prefix)
                reader = API['Collector']('heavy', 'hel8', {}, STAMP, datetime.now(timezone.utc))
                reader.heavy()
                self.assertEqual(len(reader.finish()), 1)
                self.assertEqual(reader.state['files'][str(path)]['offset'], len(normal.encode()))
                self.write(path, normal + prefix + 'done' + suffix)
                resumed = API['Collector']('heavy', 'hel8', reader.state, STAMP, datetime.now(timezone.utc))
                resumed.heavy()
                self.assertEqual(len(resumed.finish()), 1)
                self.assertEqual(resumed.state['files'][str(path)]['offset'], path.stat().st_size)
                repeated = API['Collector']('heavy', 'hel8', resumed.state, STAMP, datetime.now(timezone.utc))
                repeated.heavy()
                self.assertEqual(repeated.finish(), [])

    def codex_fixture(self):
        self.json(self.home / 'names.json', [dict(role='lead', kind='codex', name='lead/u/jig',
                  mailbox='lead/u/jig', unit='codex-owner-lead-u-jig', supervisor='s/upgrades')])
        self.fake('systemctl', """import os, sys
from pathlib import Path
assert sys.argv[1:] == ['--user', 'is-active', '--quiet', 'codex-owner-lead-u-jig']
sys.exit(int((Path(os.environ['HOME']) / 'unit-exit').read_text()))
""")
        self.write(self.home / 'unit-exit', '0')
        original = (self.bin / 'session-context').read_text().split('\n', 1)[1]
        self.fake('session-context', """import os, sys
from pathlib import Path
if sys.argv[1:2] == ['--owner']:
 assert sys.argv[1:] == ['--owner', 'lead/u/jig']
 home = Path(os.environ['HOME'])
 code = int((home / 'context-exit').read_text())
 print((home / 'context-line').read_text())
 sys.exit(code)
# Looking up this name via Claude would read a different session.
assert sys.argv[1:] != ['--name', 'lead/u/jig']
""" + original)
        self.owner_reading(50, 0)

    def owner_reading(self, percent, code, thread='abcdef12'):
        self.write(self.home / 'context-exit', str(code))
        self.write(self.home / 'context-line',
                   f'{thread}: {percent * 1000:,} of 100,000 tokens ({percent}%) at {STAMP}; '
                   f'2 compaction(s); threshold 75%' + (' REACHED: hand over now' if code == 3 else ''))

    def test_codex_unit_lifecycle_context_and_threshold_crossings(self):
        self.codex_fixture()
        # A stale Claude row with the same name must never be measured.
        self.session_fixture('lead/u/jig')
        self.run_collect('sessions')
        start, = self.events('sessions')
        self.assertEqual(start['kind'], 'session-start')
        self.assertEqual(start['session_kind'], 'codex-owner')
        self.assertEqual(start['unit'], 'codex-owner-lead-u-jig')
        self.assertEqual(self.dry('sessions'), [])
        self.owner_reading(75, 3)
        first_preview = self.dry('sessions')
        second_preview = self.dry('sessions')
        first_hook = next(e for e in first_preview if e['kind'] == 'handover-needed')
        self.assertEqual(first_hook['id'], next(e for e in second_preview if e['kind'] == 'handover-needed')['id'])
        self.run_collect('sessions')
        hooks = lambda: [e for e in self.events('sessions') if e['kind'] == 'handover-needed']
        self.assertEqual(len(hooks()), 1)
        self.assertEqual(hooks()[0]['id'], first_hook['id'])
        self.assertEqual([e['kind'] for e in self.dry('sessions')], [])
        # The exit status, rather than rounded output, decides crossing.
        self.owner_reading(75, 0)
        self.run_collect('sessions')
        self.owner_reading(75, 3)
        self.run_collect('sessions')
        self.assertEqual(len(hooks()), 2)
        self.assertNotEqual(hooks()[0]['id'], hooks()[1]['id'])
        # A fresh owner thread above threshold begins its own crossing.
        self.owner_reading(80, 3, thread='ffffffff')
        self.run_collect('sessions')
        self.assertEqual(len(hooks()), 3)
        self.write(self.home / 'unit-exit', '3')
        self.run_collect('sessions')
        ends = [e for e in self.events('sessions') if e['kind'] == 'session-end']
        self.assertEqual(len(ends), 1)
        self.assertEqual(ends[0]['session'], start['session'])
        self.assertEqual(ends[0]['session_kind'], 'codex-owner')
        self.run_collect('sessions')
        self.assertEqual(sum(e['kind'] == 'session-end' for e in self.events('sessions')), 1)
        self.write(self.home / 'unit-exit', '0')
        self.run_collect('sessions')
        starts = [e for e in self.events('sessions') if e['kind'] == 'session-start']
        self.assertEqual(len(starts), 2)
        self.assertNotEqual(starts[0]['session'], starts[1]['session'])

    def test_codex_ignores_stale_claude_hook_markers(self):
        self.codex_fixture()
        self.json(self.home / 'fired.json', [dict(session_id=SESSION, name='lead/u/jig', role='lead',
                  reason='old Claude hook', first_fired=STAMP, last_fired=STAMP)])
        events = self.dry('sessions')
        self.assertEqual([e['kind'] for e in events], ['session-start'])

    def test_codex_without_measurement_still_records_unit_transition(self):
        self.codex_fixture()
        self.write(self.home / 'context-exit', '1')
        result = self.run_collect('sessions')
        self.assertIn('skip sessions/context: lead/u/jig:', result.stderr)
        self.assertEqual([e['kind'] for e in self.events('sessions')], ['session-start'])
        self.assertFalse(self.dry('sessions'))

    def test_codex_unknown_unit_is_inactive_and_bus_error_is_unavailable(self):
        self.codex_fixture()
        self.write(self.home / 'unit-exit', '4')
        self.assertEqual([e['kind'] for e in self.dry('sessions')], [])
        self.write(self.home / 'unit-exit', '1')
        result = self.run_collect('sessions', options=('--dry-run',), code=2)
        self.assertIn('systemctl is-active failed', result.stderr)
        self.assertFalse(self.state.exists())

    def test_sessions_lifecycle_names_without_context(self):
        row = self.session_fixture()
        self.run_collect('sessions')
        start, = self.events('sessions')
        self.assertEqual((start['kind'], start['session'], start['coordinator'], start['area']), ('session-start', SESSION, 'H', 'tools'))
        self.assertEqual([e['kind'] for e in self.dry('sessions')], [])
        row['name'] = 'coordinator/H/next'
        self.json(self.home / 'agents.json', [row])
        self.run_collect('sessions')
        name = next(e for e in self.events('sessions') if e['kind'] == 'session-name')
        self.assertEqual(name['previous_name'], 'lead/H/tools')
        self.assertEqual(name['coordinator'], 'H')
        self.json(self.home / 'agents.json', [])
        self.run_collect('sessions')
        self.assertEqual(self.events('sessions')[-1]['kind'], 'session-end')
        self.assertIn('sessions: 0 events', self.run_collect('sessions').stderr)
        self.assertEqual(API['names']('coord-next'), {'coordinator': 'coord-next'})
        self.assertEqual(API['names']('lead/tools'), {'area': 'tools'})

    def test_optional_fired_capability_preserves_session_lifecycle(self):
        original = (self.bin / 'session-context').read_text().split('\n', 1)[1]
        for capability in ("print('hook-gating')", 'sys.exit(2)'):
            with self.subTest(capability=capability):
                self.fake('session-context', original.replace("print('fired-markers')", capability).replace(
                    "if sys.argv[1:] == ['--fired', '--json']:",
                    "if sys.argv[1:] == ['--fired', '--json']:\n raise AssertionError('must not request fired markers')"))
                self.session_fixture()
                result = self.run_collect('sessions', options=('--dry-run',))
                self.assertIn('skip sessions/fired:', result.stderr)
                self.assertEqual([json.loads(line)['kind'] for line in result.stdout.splitlines()],
                                 ['session-start'])
                self.run_collect('sessions')
                self.session_fixture('coordinator/H/next')
                self.run_collect('sessions')
                self.json(self.home / 'agents.json', [])
                self.run_collect('sessions')
                self.assertEqual([e['kind'] for e in self.events('sessions')],
                                 ['session-start', 'session-name', 'session-end'])
                # Reset only the isolated fixture for the next capability case.
                shutil.rmtree(self.fabrig / 'events/sessions')
                for path in self.state.iterdir():
                    path.unlink()

    def test_advertised_fired_failures_return_two(self):
        self.session_fixture()
        original = (self.bin / 'session-context').read_text().split('\n', 1)[1]
        for failed in ("['--fired', '--json']",):
            with self.subTest(failed=failed):
                self.fake('session-context', f'import sys\nif sys.argv[1:] == {failed}: sys.exit(2)\n' + original)
                result = self.run_collect('sessions', options=('--dry-run',), code=2)
                self.assertIn('sessions: error:', result.stderr)
                self.assertFalse(result.stdout)

    def test_capability_command_exceptions_skip_only_fired(self):
        reader = API['Collector']('sessions', 'hel8', {}, STAMP, API['timestamp'](END))
        for error in (FileNotFoundError(), subprocess.TimeoutExpired('session-context', 30)):
            with self.subTest(error=error), patch('subprocess.run', side_effect=error), patch('sys.stderr') as stderr:
                reader.fired()
                self.assertIn('skip sessions/fired:', ''.join(call.args[0] for call in stderr.write.call_args_list))

    def test_exit_policy_success_skips_and_failure(self):
        self.session_fixture()
        self.run_collect('sessions', 'runs', options=('--dry-run',))
        self.run_collect('runs', 'queue', options=('--dry-run',))
        self.json(self.fabrig / 'notes/queue.jsonl', {'invalid': True})
        result = self.run_collect('sessions', 'queue', 'runs', options=('--dry-run',), code=2)
        self.assertIn('skip runs:', result.stdout)
        self.assertIn('queue: error:', result.stderr)
        self.assertEqual([json.loads(line)['kind'] for line in result.stdout.splitlines() if line.startswith('{')],
                         ['session-start'])

    def test_claim_release_and_repeat(self):
        path = self.claim_fixture()
        self.run_collect('claims')
        claim, = self.events('claims')
        self.assertEqual((claim['kind'], claim['area'], claim['slot']), ('claim', 'tools', 'hel8-1'))
        self.assertIn('claims: 0 events', self.run_collect('claims').stderr)
        path.unlink()
        self.run_collect('claims')
        self.assertEqual([e['kind'] for e in self.events('claims')], ['claim', 'release'])
        self.assertIn('claims: 0 events', self.run_collect('claims').stderr)

    def test_leases_take_want_lend_release_and_removed_permissions(self):
        path, row = self.lease_fixture()
        self.run_collect('leases')
        self.assertEqual([e['kind'] for e in self.events('leases')], ['take', 'want', 'lend'])
        self.assertEqual([e['coordinator'] for e in self.events('leases')], ['s/example', 's/next', 's/example'])
        self.assertIn('leases: 0 events', self.run_collect('leases').stderr)
        row['waiters'] = []
        row['lends'] = []
        self.json(path, row)
        self.run_collect('leases')
        self.assertEqual([(e['kind'], e['active']) for e in self.events('leases')[-2:]], [('want', False), ('lend', False)])
        row['lends'] = ['mc/example']
        self.json(path, row)
        self.run_collect('leases')
        lends = [e for e in self.events('leases') if e['kind'] == 'lend']
        self.assertEqual([e['active'] for e in lends], [True, False, True])
        self.assertNotEqual(lends[0]['id'], lends[2]['id'])
        path.unlink()
        self.run_collect('leases')
        self.assertIn('release', [e['kind'] for e in self.events('leases')])
        self.assertIn('leases: 0 events', self.run_collect('leases').stderr)

    def test_post_delivery_read_headers_only_and_mailbox_identity(self):
        path = self.post_fixture()
        self.run_collect('post')
        mail, = self.events('post')
        self.assertEqual((mail['message_id'], mail['area'], mail['coordinator']), (MESSAGE, 'tools', 'H'))
        self.assertEqual(mail['subject'], 'Synthetic status')
        self.assertEqual(mail['delivered'], STAMP)
        self.assertNotIn('body', mail)
        self.assertIn('post: 0 events', self.run_collect('post').stderr)
        path.rename(path.parent.parent / 'cur' / path.name)
        self.run_collect('post')
        mail, read = self.events('post')
        self.assertEqual(read['kind'], 'read')
        self.assertEqual(read['read_time_basis'], 'inode-ctime')
        self.assertNotIn('subject', read)
        self.assertIn('post: 0 events', self.run_collect('post').stderr)
        self.assertFalse(any(e.get('body') for e in self.events('post')))

    def test_dry_run_all_sources_writes_nothing(self):
        self.runs_fixture()
        self.queue_fixture()
        self.heavy_fixture()
        self.session_fixture()
        self.lease_fixture()
        self.post_fixture()
        self.post_sent_fixture()
        events = self.dry(*API['SOURCES'])
        self.assertEqual(set(e['source'] for e in events), set(API['SOURCES']))
        self.assertFalse(self.state.exists())
        self.assertFalse(self.clone.exists())
        before = self.git(self.origin, 'rev-parse', 'main')
        self.run_collect(*API['SOURCES'])
        self.assertFalse(self.clone.exists())
        self.assertEqual(self.git(self.origin, 'rev-parse', 'main'), before)
        for source in API['SOURCES']:
            self.assertTrue(self.events(source))
        cursors = {p: p.read_bytes() for p in self.state.iterdir()}
        self.dry(*API['SOURCES'])
        self.assertEqual(cursors, {p: p.read_bytes() for p in self.state.iterdir()})

    def test_post_reader_stops_at_blank_header_line(self):
        path = self.post_fixture()
        header_length = path.stat().st_size
        original_open = Path.open
        test = self

        class HeaderReader:
            def __init__(self, stream):
                self.stream = stream

            def __enter__(self):
                return self

            def __exit__(self, *unused):
                self.stream.close()

            def fileno(self):
                return self.stream.fileno()

            def readline(self, limit):
                test.assertLess(self.stream.tell(), header_length, 'read past the mail headers')
                return self.stream.readline(limit)

        def audited_open(file, *args, **kwargs):
            stream = original_open(file, *args, **kwargs)
            if file == path:
                self.assertEqual(kwargs.get('buffering'), 0, 'buffering could read past headers')
                return HeaderReader(stream)
            return stream

        reader = API['Collector']('post', 'hel8', {}, STAMP, datetime.now(timezone.utc))
        with patch.object(Path, 'open', audited_open):
            reader.post()
        self.assertEqual(len(reader.finish()), 1)

    def test_absent_source_skips_and_error_does_not_stop_other_sources(self):
        r = self.run_collect('runs')
        self.assertIn('skip runs: no codex-run directory', r.stdout)
        self.assertFalse((self.state / 'runs.json').exists())
        self.write(self.fabrig / 'notes/queue.jsonl', '{invalid}\n')
        self.claim_fixture()
        r = self.run_collect('queue', 'claims', code=2)
        self.assertIn('queue: error:', r.stderr)
        self.assertEqual(len(self.events('claims')), 1)
        self.assertFalse((self.state / 'queue.json').exists())
        self.write(self.fabrig / 'notes/queue.jsonl', '[]\n')
        self.run_collect('queue', 'claims', code=2)

    def test_partial_line_rotation_and_new_input(self):
        self.queue_fixture()
        path = self.fabrig / 'notes/queue.jsonl'
        first = path.read_bytes()
        with path.open('ab') as output:
            output.write(b'{"start":')
        self.run_collect('queue')
        self.assertEqual(self.cursor('queue')['files'][str(path)]['offset'], len(first))
        row = dict(start='2026-10-29T11:03:00Z', end='2026-10-29T11:04:00Z', outcome='green', branches=[], steps=[])
        with path.open('ab') as output:
            output.write((json.dumps(row)[len('{"start":'):] + '\n').encode())
        self.run_collect('queue')
        self.assertEqual(len(self.events('queue')), 4)
        replacement = self.write(path.with_suffix('.rotated'), first.decode())
        replacement.replace(path)
        self.assertIn('queue: 0 events', self.run_collect('queue').stderr)
        self.assertEqual(len(self.events('queue')), 4)

    def test_spool_retention_applies_to_old_inputs_and_empty_polls(self):
        row = self.queue_fixture()
        expired = dict(row, start='2026-10-29T09:00:00Z', end='2026-10-29T09:01:00Z')
        kept = dict(row, start='2026-10-29T09:02:00Z', end='2026-10-29T09:03:00Z')
        self.write(self.fabrig/'notes/queue.jsonl',
                   ''.join(json.dumps(r)+'\n' for r in (expired, kept)))
        self.run_collect('queue', options=('--since', '2026-10-29T00:00:00Z'))
        rows = self.events('queue')
        self.assertTrue(rows)
        self.assertTrue(all(r['time'] == kept['end'] for r in rows))
        source = self.fabrig/'events/queue'
        old = source/'2026-10-28.jsonl'
        self.write(old, json.dumps(dict(rows[0], id='old', time='2026-10-28T12:00:00Z'))+'\n')
        self.run_collect('queue')
        self.assertFalse(old.exists())
        self.assertEqual(self.events('queue'), rows)
        self.assertEqual(len(rows), len({r['id'] for r in rows}))

    def test_multiple_sources_never_touch_records_or_git(self):
        self.claim_fixture()
        self.queue_fixture()
        self.session_fixture()
        head = self.git(self.origin, 'rev-parse', 'main')
        self.fake('git', "raise AssertionError('collector must not invoke git')")
        self.run_collect('queue', 'sessions', 'claims', RECORDS_ORIGIN=str(self.home/'absent.git'))
        for source in ('queue', 'sessions', 'claims'):
            self.assertTrue(self.events(source))
        self.assertFalse(self.clone.exists())
        (self.bin/'git').unlink()
        self.assertEqual(self.git(self.origin, 'rev-parse', 'main'), head)

    def test_multi_source_cursor_failure_replays_without_another_commit(self):
        self.claim_fixture()
        self.queue_fixture()
        namespace = API['argparse'].Namespace(dry_run=False)
        original_atomic = API['atomic']
        def fail_cursor(path, value):
            if path.name == 'queue.json':
                raise OSError('simulated cursor write failure')
            original_atomic(path, value)
        with patch.dict(os.environ, self.env), patch.dict(API['collect'].__globals__, atomic=fail_cursor):
            with API['ExitStack']() as stack:
                transactions = [stack.enter_context(API['stage'](s, namespace, 'hel8', STAMP))
                                for s in ('claims', 'queue')]
                with self.assertRaises(OSError):
                    API['publish'](transactions, 'hel8', False)
        self.assertTrue((self.state/'claims.json').exists())
        self.assertFalse((self.state/'queue.json').exists())
        self.assertTrue((self.state/'queue.pending.json').exists())
        head = self.git(self.origin, 'rev-parse', 'main')
        self.run_collect('queue', 'claims')
        self.assertEqual(self.git(self.origin, 'rev-parse', 'main'), head)
        self.assertFalse(list(self.state.glob('*.pending.json')))

    def test_since_first_cursor_only_and_host_override(self):
        row = self.queue_fixture()
        row['end'] = '2026-10-20T11:00:00Z'
        self.json(self.fabrig / 'notes/queue.jsonl', row)
        self.assertEqual(self.dry('queue'), [])
        # Default seven day bound excludes this old event as well.
        r = subprocess.run([str(TOOL), 'queue', '--dry-run'], env=self.env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, '')
        self.queue_fixture()
        self.assertTrue(all(e['host'] == 'hel8' for e in self.dry('queue')))
        r = self.run_collect('queue', options=('--dry-run', '--host', 'hetzner8'))
        self.assertTrue(all(json.loads(l)['host'] == 'hetzner8' for l in r.stdout.splitlines()))
        self.run_collect('queue')
        self.run_collect('queue', options=('--host', 'hetzner8'), code=2)
        self.run_collect('queue', options=('--since', 'invalid'), code=2)

    def test_spool_failure_retains_outbox_and_cursor_for_replay(self):
        self.claim_fixture()
        namespace = API['argparse'].Namespace(dry_run=False)
        spool = API['publish'].__globals__['event_spool']
        with patch.dict(os.environ, self.env), patch.object(spool, 'append', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                API['collect']('claims', namespace, 'hel8', STAMP)
        pending = self.state / 'claims.pending.json'
        saved = json.loads(pending.read_text())['events']
        self.assertFalse((self.state/'claims.json').exists())
        self.run_collect('claims')
        self.assertEqual(self.events('claims'), saved)
        self.assertFalse(pending.exists())
        self.run_collect('claims')
        self.assertEqual(self.events('claims'), saved)

    def post_sent_fixture(self, code=2, time=STAMP):
        row = dict(time=time, subject_sha256='a' * 64, message_id=MESSAGE, exit=code,
                   **{'from': 'lead/H/tools@hel8', 'to': 's/example@hel8'})
        self.write(self.tmp / 'post/sent.jsonl', json.dumps(row) + '\n')
        return row

    def test_post_sent_missing_partial_retry_rotation_and_hash_only(self):
        self.assertIn('skip post-sent', self.run_collect('post-sent').stdout)
        row = self.post_sent_fixture()
        path = self.tmp / 'post/sent.jsonl'
        success = dict(row, time=END, exit=0)
        encoded = json.dumps(success)
        self.write(path, json.dumps(row) + '\n' + encoded[:20])
        self.run_collect('post-sent')
        failed, = self.events('post-sent')
        self.assertEqual((failed['kind'], failed['exit'], failed['message_id']), ('send', 2, MESSAGE))
        self.assertEqual(failed['subject_sha256'], 'a' * 64)
        self.assertNotIn('subject', failed)
        self.assertNotIn('body', failed)
        self.assertIn('post-sent: 0 events', self.run_collect('post-sent').stderr)
        self.write(path, path.read_text() + encoded[20:] + '\n')
        self.run_collect('post-sent')
        self.assertEqual([e['exit'] for e in self.events('post-sent')], [2, 0])
        replacement = path.with_name('sent.new')
        self.write(replacement, json.dumps(row) + '\n' + encoded + '\n')
        replacement.replace(path)
        self.assertIn('post-sent: 0 events', self.run_collect('post-sent').stderr)

    def test_post_sent_invalid_input_preserves_cursor(self):
        row = self.post_sent_fixture()
        self.run_collect('post-sent')
        before = (self.state / 'post-sent.json').read_bytes()
        row['subject_sha256'] = 'invalid'
        self.write(self.tmp / 'post/sent.jsonl', json.dumps(row) + '\n')
        self.run_collect('post-sent', code=2)
        self.assertEqual((self.state / 'post-sent.json').read_bytes(), before)

    def test_fired_first_updates_replay_and_lead_end_ack_drive_watch(self):
        import tomllib
        watch = runpy.run_path(str(TOOL.with_name('watch')))
        config = tomllib.loads(TOOL.with_name('watch.toml').read_text())['rules']
        self.session_fixture()
        marker = dict(session_id=SESSION, name='lead/H/tools', role='lead', reason='threshold',
                      first_fired=STAMP, last_fired=STAMP)
        self.json(self.home / 'fired.json', [marker])
        self.run_collect('sessions')
        hooks = lambda: [e for e in self.events('sessions') if e['kind'] == 'handover-needed']
        first, = hooks()
        self.assertEqual(first['time'], STAMP)
        self.assertEqual(first['session'], SESSION)
        self.run_collect('sessions')
        self.assertEqual(len(hooks()), 1)
        marker['last_fired'] = END
        self.json(self.home / 'fired.json', [marker])
        self.run_collect('sessions')
        self.assertEqual(len(hooks()), 2)
        self.assertNotEqual(hooks()[0]['id'], hooks()[1]['id'])
        self.assertEqual(hooks()[1]['first_fired'], STAMP)
        data = dict(names={'lead/H/tools': dict(role='lead', supervisor='s/example')},
                    owned={'lead/H/tools': True}, **{'spool/sessions': self.events('sessions')})
        now = API['timestamp'](STAMP).timestamp() + 1300
        late = lambda: [c for c in watch['evaluate'](data, {}, config, now).values()
                        if c['rule'] == 'handover late']
        self.assertEqual(len(late()), 1)
        episodes = {}
        events = watch['reconcile'](episodes, watch['evaluate'](data, {}, config, now),
                                    {'spool/post': 'absent'}, config, now, lambda *args: 0)
        self.assertEqual([e['kind'] for e in events], ['alert-open'])
        # Replaying from a fresh cursor must not duplicate append-only hook facts.
        (self.state / 'sessions.json').unlink()
        self.run_collect('sessions')
        self.assertEqual(len(hooks()), 2)
        mail = self.post_fixture()
        self.write(mail, mail.read_text().replace('From: s/example@hel8', 'From: lead/H/tools@hel8')
                   .replace('Subject: Synthetic status', 'Subject: files current: closing complete'))
        seconds = API['timestamp'](END).timestamp()
        os.utime(mail, (seconds, seconds))
        self.run_collect('sessions')
        ack, = [e for e in self.events('sessions') if e['kind'] == 'files-current']
        self.assertEqual(ack['name'], 'lead/H/tools')
        self.assertEqual(ack['message_id'], MESSAGE)
        data['spool/sessions'] = self.events('sessions')
        self.assertFalse(late())
        self.run_collect('sessions')
        self.assertEqual(sum(e['kind'] == 'files-current' for e in self.events('sessions')), 1)

    def test_files_current_requires_a_lead_sender(self):
        mail = self.post_fixture()
        self.write(mail, mail.read_text().replace('Subject: Synthetic status', 'Subject: files current: done'))
        self.assertFalse(self.dry('sessions'))

    def test_director_sessions_and_markers_without_live_sessions(self):
        self.session_fixture('director/20261029T1100Z')
        self.run_collect('sessions')
        self.assertEqual([e['kind'] for e in self.events('sessions')], ['session-start'])
        self.json(self.home / 'agents.json', [])
        self.json(self.home / 'fired.json', [
            dict(session_id=SESSION, name='director/20261029T1100Z', role='director', reason='compaction',
                 first_fired=STAMP, last_fired=END),
            dict(session_id='unresolved', name=None, role=None, reason='threshold',
                 first_fired=STAMP, last_fired=STAMP)])
        self.run_collect('sessions')
        hooks = [e for e in self.events('sessions') if e['kind'] == 'handover-needed']
        self.assertEqual(len(hooks), 2)
        self.assertTrue(all(e['role'] == 'director' for e in hooks))


if __name__ == '__main__':
    unittest.main(verbosity=2)
