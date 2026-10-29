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
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import quote

TOOL = Path(__file__).with_name('record-collect').resolve()
API = runpy.run_path(str(TOOL))
STAMP = '2026-10-29T11:00:00Z'
END = '2026-10-29T11:02:00Z'
RUN = '20261029T110000Z-aaaa'
SESSION = '12345678-1111-2222-3333-123456789abc'
SUBJECT = 'pkg:example-core'
MESSAGE = '20261029T110000Z-12345678'


class CollectTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='collect-test-')
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name)
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
        self.fake('claude', """import json, os
from pathlib import Path
assert __import__('sys').argv[1:] == ['agents', '--json']
print((Path(os.environ['HOME']) / 'agents.json').read_text())
""")
        self.fake('session-context', """import sys
assert sys.argv[1] == '--name'
print('12345678: 125,000 of 1,000,000 tokens (12%) at 2026-10-29T11:00:00Z; 42 calls; 0 compaction(s); threshold 75%')
""")
        self.write(self.home / 'agents.json', '[]')
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
        r = subprocess.run([str(TOOL), *sources, '--since', STAMP, *options],
                           capture_output=True, text=True, env=dict(self.env, **env))
        self.assertEqual(r.returncode, code, r.stderr + r.stdout)
        return r

    def dry(self, *sources, **kwargs):
        r = self.run_collect(*sources, options=('--dry-run',), **kwargs)
        return [json.loads(line) for line in r.stdout.splitlines() if line.startswith('{')]

    def events(self, source):
        root = self.clone / 'events' / source / 'hel8'
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
        head = self.git(self.clone, 'rev-parse', 'HEAD')
        r = self.run_collect('runs', options=('--since', '2099-01-01T00:00Z'))
        self.assertIn('runs: 0 events', r.stderr)
        self.assertEqual(head, self.git(self.clone, 'rev-parse', 'HEAD'))
        self.assertEqual(self.cursor('runs')['files'][str(self.tmp / 'codex-run/runs.tsv')]['offset'], len(self.run_row.encode()))
        self.assertEqual((self.state / 'runs.json').stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.git(self.clone, 'log', '-1', '--format=%s'), 'collect: append runs/hel8')

    def test_task_fallback_and_invalid_header(self):
        task = self.runs_fixture(header=False)
        events = self.dry('runs')
        self.assertTrue(all(e['branch'] == 'mc/fallback' and e['coordinator'] == 'H' and e['area'] == 'tools' for e in events))
        self.write(task, 'Push ready/tools/fallback before finishing.\n')
        self.assertEqual(API['task_keys'](task), {'branch': 'ready/tools/fallback'})
        self.write(task, '+++\narea = 42\n+++\n')
        self.run_collect('runs', options=('--dry-run',), code=2)
        self.assertFalse(self.state.exists())
        self.write(task, '+++\nbranch = "mc/x"\n')
        self.assertRaises(ValueError, API['task_keys'], task)

    def test_active_run_without_completion_and_missing_task(self):
        task = self.runs_fixture()
        task.unlink()
        (self.tmp / 'codex-run/runs.tsv').unlink()
        events = self.dry('runs')
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['kind'], 'run-start')
        self.assertEqual(events[0]['area'], 'tools')

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

    def test_sessions_lifecycle_names_and_context_each_run(self):
        row = self.session_fixture()
        self.run_collect('sessions')
        start, reading = self.events('sessions')
        self.assertEqual((start['kind'], start['session'], start['coordinator'], start['area']), ('session-start', SESSION, 'H', 'tools'))
        self.assertEqual((reading['kind'], reading['tokens'], reading['window']), ('context', 125000, 1000000))
        self.assertEqual([e['kind'] for e in self.dry('sessions')], ['context'])
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
        events = self.dry(*API['SOURCES'])
        self.assertEqual(set(e['source'] for e in events), set(API['SOURCES']))
        self.assertFalse(self.state.exists())
        self.assertFalse(self.clone.exists())
        # Each source also publishes to a real local bare origin in one run.
        self.run_collect(*API['SOURCES'])
        self.assertEqual(len(self.git(self.clone, 'log', '--format=%s').splitlines()), 8)
        result = subprocess.run([str(TOOL.with_name('record')), 'check'], env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('0 refused', result.stdout)
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

    def test_append_failure_replays_durable_outbox_and_cursor_unchanged(self):
        self.claim_fixture()
        bad_origin = str(self.home / 'absent.git')
        self.run_collect('claims', code=2, RECORDS_ORIGIN=bad_origin)
        self.assertFalse((self.state / 'claims.json').exists())
        pending = self.state / 'claims.pending.json'
        transaction = json.loads(pending.read_text())
        self.assertEqual(pending.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.dry('claims'), transaction['events'])
        self.run_collect('claims')
        self.assertEqual(self.events('claims'), transaction['events'])
        self.assertFalse(pending.exists())
        self.assertIn('claims: 0 events', self.run_collect('claims').stderr)

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

    def test_published_events_survive_cursor_failure_without_duplicate_commit(self):
        self.claim_fixture()
        namespace = API['argparse'].Namespace(dry_run=False)
        original_atomic = API['atomic']

        def fail_cursor(path, value):
            if path.name == 'claims.json':
                raise OSError('simulated cursor write failure')
            original_atomic(path, value)

        with patch.dict(os.environ, self.env), patch.dict(API['collect'].__globals__, atomic=fail_cursor):
            with self.assertRaises(OSError):
                API['collect']('claims', namespace, 'hel8', STAMP)
        self.assertFalse((self.state / 'claims.json').exists())
        head = self.git(self.clone, 'rev-parse', 'HEAD')
        pending = json.loads((self.state / 'claims.pending.json').read_text())
        self.run_collect('claims')
        self.assertEqual(self.events('claims'), pending['events'])
        self.assertEqual(self.git(self.clone, 'rev-parse', 'HEAD'), head)


if __name__ == '__main__':
    unittest.main(verbosity=2)
