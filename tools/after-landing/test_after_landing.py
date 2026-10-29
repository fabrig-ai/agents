#!/usr/bin/env python3
"""Offline contracts: temporary HOME, local Git, fake tiers/heavy/post/record."""

import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
TOOL = HERE / 'after-landing'
loader = importlib.machinery.SourceFileLoader('after_landing_test_subject', str(TOOL))
spec = importlib.util.spec_from_loader(loader.name, loader)
app = importlib.util.module_from_spec(spec)
loader.exec_module(app)


FAKE = r'''#!/usr/bin/env python3
import fcntl
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import tomllib
import xml.etree.ElementTree as ET

home = Path.home()

def write(path, text):
    fd, sibling = tempfile.mkstemp(dir=path.parent)
    with os.fdopen(fd, 'w') as output:
        output.write(text)
    os.replace(sibling, path)

def log(value):
    path = home / 'calls.json'
    with open(home / 'calls.lock', 'a') as gate:
        fcntl.flock(gate, fcntl.LOCK_EX)
        rows = json.loads(path.read_text()) if path.exists() else []
        rows.append(value)
        write(path, json.dumps(rows))

name = Path(sys.argv[0]).name
scenario = json.loads((home / 'scenario.json').read_text())
if name == 'registry':
    log(dict(tool=name, args=sys.argv[1:]))
    if scenario.get('registry_fault'):
        sys.exit(2)
    print(json.dumps(scenario['registry']))
elif name in ('post', 'record'):
    body = Path(sys.argv[-1]).read_text() if name == 'post' else sys.stdin.read()
    accepted = True
    if name == 'record':
        writers = tomllib.loads(Path(os.environ['RECORD_WRITERS']).read_text())
        writer = sys.argv[sys.argv.index('--as') + 1]
        allowed = writers.get(writer, {}).get('sources', [])
        accepted = bool(allowed) and all(json.loads(line)['source'] in allowed and len(line.encode()) + 1 < 16384 for line in body.splitlines())
    log(dict(tool=name, args=sys.argv[1:], body=body, accepted=accepted))
    if not accepted:
        print('record: writer/source refused or event exceeds cap', file=sys.stderr)
        sys.exit(1)
    if scenario.get(name + '_wait'):
        write(home / (name + '-entered'), '')
        while not (home / (name + '-release')).exists():
            time.sleep(.01)
    sys.exit(scenario.get(name + '_code', 0))
elif name == 'heavy' and sys.argv[1] != '--cancel':
    log(dict(tool='heavy-submit', args=sys.argv[1:]))
    print('heavy: queued task 1 in the build lane token ' + 'a'*32, flush=True)
    while not (home / 'allow-end').exists():
        time.sleep(.01)
    print('heavy: receipt /fake/receipt.json token ' + 'a'*32, flush=True)
elif name == 'heavy':
    token = sys.argv[2]
    log(dict(tool=name, args=sys.argv[1:], cwd=str(Path.cwd())))
    if (home / 'allow-end').exists():
        print('heavy: cancelled task 1 (build) token ' + token + ', exit 130')
    else:
        print('heavy: cancelled task 1 (build) token ' + token + '; the reconciler completes its release')
elif name == 'run':
    tree, tier = sys.argv[1:3]
    profile = tier + '-' + tree
    rerun = '-E' in sys.argv
    pair = scenario['pairs'][profile]
    chosen = pair.get('rerun', pair.get('main', [])) if rerun else pair.get('main', [])
    override = {}
    if rerun and pair.get('reruns'):
        expression = sys.argv[sys.argv.index('-E') + 1]
        test = json.loads(expression.partition(' & test(=')[2][:-1])
        override = pair['reruns'][test]
        chosen = override['tests']
    log(dict(tool='tiers', profile=profile, rerun=rerun, args=sys.argv[1:],
             head=__import__('subprocess').check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
             heavy_class=os.environ.get('HEAVY_CLASS'),
             lease_held=bool(os.fstat(int(os.environ['TEST_LEASE_FD']))) if 'TEST_LEASE_FD' in os.environ else None))
    if pair.get('wait'):
        write(home / 'tier-entered', '')
        while not (home / 'tier-release').exists():
            time.sleep(.01)
    if pair.get('hang'):
        print('heavy: queued task 1 in the build lane token ' + 'a'*32, flush=True)
        while True:
            time.sleep(.01)
    config = tomllib.loads(Path(sys.argv[sys.argv.index('--config-file') + 1]).read_text())
    target = Path(config['profile'][profile]['junit']['path'])
    suites = ET.Element('testsuites', tests=str(len(chosen)))
    for binary in sorted(set(row.get('binary', 'pkg::qa') for row in chosen)):
        suite = ET.SubElement(suites, 'testsuite', name=binary)
        for row in chosen:
            if row.get('binary', 'pkg::qa') != binary:
                continue
            case = ET.SubElement(suite, 'testcase', name=row.get('test', 'one'), classname='ignored.classname')
            result = row.get('result', 'pass')
            if result == 'fail':
                ET.SubElement(case, 'failure', message='failed').text = row.get('error', 'first error\nmore details')
            elif result == 'skip':
                ET.SubElement(case, 'skipped')
    write(target, ET.tostring(suites, encoding='unicode'))
    code = override.get('code', pair.get('rerun_code' if rerun else 'code', 100 if any(row.get('result') == 'fail' for row in chosen) else 0))
    sys.exit(code)
'''


LEASE = r"""import fcntl
import json
import os
from pathlib import Path
import tempfile
import uuid

def atomic(path, value):
    fd, sibling = tempfile.mkstemp(dir=path.parent)
    with os.fdopen(fd, 'w') as output:
        json.dump(value, output)
    os.replace(sibling, path)

class Lease:
    def __init__(self, slot):
        self.slot = Path(slot)
        self.clean = False
    def __enter__(self):
        self.directory = Path.home() / 'lease'
        self.directory.mkdir(exist_ok=True, mode=0o700)
        self.fd = os.open(self.directory / 'lock', os.O_CREAT | os.O_RDWR, 0o600)
        fcntl.flock(self.fd, fcntl.LOCK_SH)
        self.token = uuid.uuid4().hex
        self.hold = self.directory / (self.token + '.hold')
        atomic(self.hold, dict(slot=str(self.slot)))
        os.environ['TEST_LEASE_FD'] = str(self.fd)
        return self
    def adopt(self, token):
        path = self.directory / (token + '.hold')
        assert json.loads(path.read_text())['slot'] == str(self.slot)
        path.unlink()
    def __exit__(self, kind, value, trace):
        if self.clean and kind is None:
            self.hold.unlink()
        os.close(self.fd)
"""


class Sandbox(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='after-landing-test-')
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name)
        self.environment = mock.patch.dict(os.environ, dict(
            HOME=str(self.home), GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL='/dev/null',
            GIT_AUTHOR_NAME='test', GIT_AUTHOR_EMAIL='test@example.invalid',
            GIT_COMMITTER_NAME='test', GIT_COMMITTER_EMAIL='test@example.invalid',
            PYTHONDONTWRITEBYTECODE='1', RECORD_WRITERS=str(HERE.parent / 'records/writers.toml')), clear=True)
        self.environment.start()
        # Retain only a safe system PATH, with no personal wrappers/services.
        os.environ['PATH'] = '/usr/local/bin:/usr/bin:/bin'
        self.addCleanup(self.environment.stop)
        self.seed = self.home / 'seed'
        self.origin = self.home / 'origin.git'
        self.slot = self.home / 'slot'
        self.git(self.home, 'init', '-q', '--bare', self.origin)
        self.git(self.home, 'init', '-q', '-b', 'main', self.seed)
        (self.seed / '.config').mkdir()
        app.atomic(self.seed / '.config/nextest.toml',
                   '[profile.default]\nglobal-timeout="1s"\n[profile.qa-skein]\nglobal-timeout="1s"\n'
                   '[profile.qa-jig]\nglobal-timeout="1s"\n')
        (self.seed / 'tools/tiers').mkdir(parents=True)
        (self.seed / 'tools/queue').mkdir()
        app.atomic(self.seed / 'tools/tiers/run', FAKE)
        (self.seed / 'tools/tiers/run').chmod(0o755)
        app.atomic(self.seed / 'tools/queue/leads.txt', 'ops ops@hel8\nmc s/multi-coord@hel8\ncoord s/dynamic-memory@hel8\nq s/qa@hel8\nu s/upgrades@hel8\n')
        self.git(self.seed, 'add', '.')
        self.git(self.seed, 'commit', '-qm', 'baseline')
        self.base = self.git(self.seed, 'rev-parse', 'HEAD')
        self.git(self.seed, 'remote', 'add', 'origin', self.origin)
        self.git(self.seed, 'push', '-q', 'origin', 'main')
        self.git(self.home, 'clone', '-q', '-b', 'main', self.origin, self.slot)
        self.bin = self.home / 'bin'
        self.bin.mkdir()
        for name in ('post', 'record', 'registry', 'heavy'):
            app.atomic(self.bin / name, FAKE)
            (self.bin / name).chmod(0o755)
        self.tiers = self.home / 'tiers.toml'
        app.atomic(self.tiers, 'profiles=["qa-skein"]\n')
        self.scenario = dict(registry=[
            dict(role='lead', branch_key='skein', coordinator_mailbox='s/dynamic-memory'),
            dict(role='lead', branch_key='q-jig', coordinator_mailbox='s/qa'),
            dict(role='coordinator', handle='dm', mailbox='s/dynamic-memory'),
            dict(role='coordinator', handle='q', mailbox='s/qa'),
            dict(role='coordinator', handle='u', mailbox='s/upgrades'),
        ], pairs={profile: dict(main=[dict(test='one')]) for profile in ('qa-skein', 'qa-jig')})
        self.save_scenario()
        self.argv = ['once', '--slot', str(self.slot), '--state-dir', str(self.home / 'state'),
                     '--tiers', str(self.tiers), '--host', 'test-builder']
        for name in ('post', 'record', 'registry', 'heavy'):
            self.argv += ['--' + name, str(self.bin / name)]
        self.args = app.arguments(self.argv)
        app.private_directory(self.args.state_dir)
        self.runner = app.Runner(self.args)

    def git(self, cwd, *args):
        result = subprocess.run(['git', '-C', str(cwd), *map(str, args)],
                                stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def save_scenario(self):
        app.write_json(self.home / 'scenario.json', self.scenario)

    def calls(self, name=None):
        path = self.home / 'calls.json'
        rows = json.loads(path.read_text()) if path.exists() else []
        return [row for row in rows if name is None or row['tool'] == name]

    def events(self, kind=None):
        events = [json.loads(line) for row in self.calls('record') for line in row['body'].splitlines()]
        return [event for event in events if kind is None or event['kind'] == kind]

    def advance(self, key=None, subject=None):
        if key:
            number = self.git(self.seed, 'rev-list', '--count', 'HEAD')
            branch = f'work-{number}'
            self.git(self.seed, 'checkout', '-qb', branch)
            self.git(self.seed, 'commit', '-q', '--allow-empty', '-m', 'branch work')
            branch_tip = self.git(self.seed, 'rev-parse', 'HEAD')
            self.git(self.seed, 'checkout', '-q', 'main')
            self.git(self.seed, 'merge', '-q', '--no-ff', branch, '-m', subject or f'Merge ready/{key}/task-{number}')
        else:
            branch_tip = None
            self.git(self.seed, 'commit', '-q', '--allow-empty', '-m', subject or 'queue baseline')
        self.git(self.seed, 'push', '-q', 'origin', 'main')
        return self.git(self.seed, 'rev-parse', 'HEAD'), branch_tip

    def poll_run(self):
        self.runner.poll()
        self.runner.run()
        return self.runner.state['last_run']

    def single(self):
        app.atomic(self.tiers, 'profiles=["qa-skein"]\n')

    def two(self):
        app.atomic(self.tiers, 'profiles=["qa-skein","qa-jig"]\n')

    def passing_history(self):
        # Routing/replay fixtures start from persisted passing evidence; the
        # complete lifecycle test obtains its predecessor by actually running.
        self.runner.state.update(seen=self.base, cursor=self.base)
        for profile in ('qa-skein', 'qa-jig'):
            key = json.dumps([profile, 'pkg::qa', 'one'], separators=(',', ':'))
            self.runner.state['tests'][key] = dict(result='pass', commit=self.base)
        self.runner.save()

    def states(self):
        return [event['state'] for event in self.events('after-landing-test')]

    def wait_file(self, path, timeout=5):
        end = time.monotonic() + timeout
        while not path.exists():
            if time.monotonic() >= end:
                self.fail('timed out waiting for ' + str(path))
            time.sleep(.01)


class QueueTests(Sandbox):
    def test_suspects_and_routes(self):
        self.runner.poll()
        tip, branch_tip = self.advance('skein')
        other, _ = self.advance('ignored', "Merge commit 'foreign'")
        baseline, _ = self.advance(subject='queue own baseline')
        self.runner.poll()
        suspects = self.runner.state['queue'][1]['suspects']
        self.assertEqual([s['kind'] for s in suspects], ['branch', 'other', 'other'])
        self.assertEqual(suspects[0]['tip'], branch_tip)
        self.assertEqual([s['commit'] for s in suspects], [tip, other, baseline])
        self.assertEqual(self.runner.resolve({'skein', 'q-jig', 'coord', 'q', 'u', 'ops', 'mc'}),
                         dict(skein='s/dynamic-memory@hel8', **{'q-jig': 's/qa@hel8'}, coord='s/dynamic-memory@hel8',
                              q='s/qa@hel8', u='s/upgrades@hel8', ops='ops@hel8', mc='s/multi-coord@hel8'))

    def test_fifo_coalescing_and_hourly_counts(self):
        self.runner.poll()
        second, _ = self.advance('skein')
        self.runner.poll()
        self.runner.run()
        self.assertEqual(self.runner.state['cursor'], self.base)
        self.assertEqual(self.runner.state['queue'][0]['tip'], second)
        third, _ = self.advance('q-jig')
        self.runner.poll()
        fourth, _ = self.advance('mc')
        self.runner.poll()
        self.runner.run()
        event = self.events('after-landing-run')[-1]
        self.assertEqual(event['commit'], fourth)
        self.assertEqual(event['coalesced'], [second, third])
        self.assertEqual(len(event['suspects']), 3)
        self.assertEqual(self.runner.state['hour']['seen'], 4)
        self.assertEqual(self.runner.state['hour']['completed'], 2)
        self.assertEqual(self.runner.state['hour']['coalesced'], 2)
        fifth, _ = self.advance()
        self.runner.poll()
        self.runner.state['hour']['start'] -= 3601
        self.runner.hourly()
        self.runner.deliver()
        bodies = [p['body'] for p in self.calls('post')]
        self.assertEqual(len(bodies), 2)
        self.assertIn('published tips seen: 5; runs completed: 2; tips coalesced: 2', bodies[0])
        self.assertIn('oldest waiting lag seconds:', bodies[0])
        self.assertEqual({p['args'][3] for p in self.calls('post')}, {'ops@hel8', 's/dynamic-memory@hel8'})

    def test_rewritten_history_stops_polling_and_alerts_once(self):
        self.poll_run()
        tip, _ = self.advance()
        self.poll_run()
        self.git(self.seed, 'reset', '--hard', self.base)
        self.git(self.seed, 'push', '-q', '--force', 'origin', 'main')
        self.runner.poll()
        self.runner.deliver()
        self.assertTrue(self.runner.state['stopped'])
        self.assertEqual(self.runner.state['seen'], tip)
        self.advance()
        self.runner.poll()
        self.runner.deliver()
        self.assertEqual(self.runner.state['seen'], tip)
        self.assertEqual(len(self.calls('post')), 1)
        self.assertIn('rewritten history', self.calls('post')[0]['body'])

    def test_dry_run_and_empty_status_have_no_state_or_service_effect(self):
        for _ in range(3):
            self.advance()
        before = self.git(self.slot, 'rev-parse', 'HEAD')
        self.git(self.slot, 'fetch', '-q', 'origin', 'main')
        self.git(self.slot, 'checkout', '-q', '--detach', 'origin/main')
        empty = self.home / 'empty-status'
        status = subprocess.run([sys.executable, '-I', '-B', str(TOOL), 'status', '--state-dir', str(empty)],
                                text=True, capture_output=True, timeout=5)
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertFalse(empty.exists())
        dry = subprocess.run([sys.executable, '-I', '-B', str(TOOL), *self.argv, '--dry-run'],
                             text=True, capture_output=True, timeout=5)
        self.assertEqual(dry.returncode, 0, dry.stderr)
        plan = json.loads(dry.stdout)
        self.assertEqual(plan['previous'], before)
        self.assertEqual(len(plan['suspects']), 3)
        self.assertEqual(self.calls(), [])
        self.assertFalse(self.runner.path.exists())


class VerdictTests(Sandbox):
    def test_new_standing_unattributed_flake_recovered_and_unobserved(self):
        self.single()
        pair = self.scenario['pairs']['qa-skein']
        pair['main'] = [dict(test='first-red', result='fail'), dict(test='later-red')]
        pair['rerun'] = [dict(test='first-red', result='fail')]
        self.save_scenario()
        self.poll_run()
        self.assertEqual(self.states(), ['unattributed'])
        self.assertEqual(self.calls('post'), [])
        self.advance('skein')
        pair['main'] = [dict(test='first-red', result='skip'), dict(test='later-red', result='fail')]
        pair['rerun'] = [dict(test='later-red', result='fail')]
        self.save_scenario()
        self.poll_run()
        self.assertEqual(self.states(), ['unattributed', 'new'])
        self.assertEqual(len(self.calls('post')), 1)
        self.assertLess(len(self.calls('post')[0]['body'].splitlines()), 15)
        self.assertIn('single suspect', self.calls('post')[0]['body'])
        first_key = json.dumps(['qa-skein', 'pkg::qa', 'first-red'], separators=(',', ':'))
        self.assertEqual(self.runner.state['tests'][first_key]['result'], 'red')
        self.advance('skein')
        self.poll_run()
        self.assertEqual(self.states()[-1], 'standing')
        self.assertEqual(len(self.calls('post')), 1)
        self.advance('skein')
        pair['main'] = [dict(test='first-red'), dict(test='later-red'), dict(test='flaky', result='fail')]
        pair['rerun'] = [dict(test='flaky')]
        self.save_scenario()
        self.poll_run()
        self.assertEqual(self.states()[-3:], ['recovered', 'recovered', 'flake'])
        self.assertEqual(self.runner.state['last_run']['verdict'], 'green')
        self.assertTrue(all(c['heavy_class'] == 'background' for c in self.calls('tiers')))
        # No failure excerpt (including first error) is included in records.
        self.assertNotIn('first error', '\n'.join(c['body'] for c in self.calls('record')))

    def test_rerun_requires_exact_single_executed_identity(self):
        self.single()
        self.poll_run()
        for rerun in ([dict(test='different', result='fail')],
                      [dict(test='one', result='fail'), dict(test='two')]):
            with self.subTest(rerun=rerun):
                self.advance('skein')
                self.scenario['pairs']['qa-skein'] = dict(main=[dict(test='one', result='fail')], rerun=rerun)
                self.save_scenario()
                self.poll_run()
                self.assertEqual(self.runner.state['last_run']['verdict'], 'partial')
                self.assertEqual(self.runner.state['last_run']['faulted'], ['qa-skein'])
                self.assertFalse(self.states())

    def test_fault_keeps_cursor_retries_only_faulted_pairs(self):
        self.two()
        self.poll_run()
        tip, _ = self.advance('skein')
        self.scenario['pairs']['qa-jig']['code'] = 2
        self.save_scenario()
        self.poll_run()
        self.assertEqual(self.runner.state['cursor'], self.base)
        self.assertEqual(self.runner.state['queue'][0]['tip'], tip)
        before = len(self.calls('tiers'))
        self.poll_run()
        self.assertEqual([c['profile'] for c in self.calls('tiers')[before:]], ['qa-jig'])
        self.assertEqual(len(self.calls('post')), 1)
        self.scenario['pairs']['qa-jig'].pop('code')
        self.save_scenario()
        self.poll_run()
        self.assertEqual(self.runner.state['cursor'], tip)
        self.assertIsNone(self.runner.state['fault_episode'])
        self.assertEqual(self.events('after-landing-run')[-1]['attempt'], 3)

    def test_red_with_fault_reports_both_and_does_not_lose_red_on_retry(self):
        self.two()
        self.poll_run()
        self.advance('skein')
        self.scenario['pairs']['qa-skein'] = dict(main=[dict(test='one', result='fail')])
        self.scenario['pairs']['qa-jig']['code'] = 4
        self.save_scenario()
        self.poll_run()
        self.assertEqual(self.runner.state['last_run']['verdict'], 'red')
        self.assertEqual(self.runner.state['last_run']['faulted'], ['qa-jig'])
        self.scenario['pairs']['qa-jig'].pop('code')
        self.save_scenario()
        self.poll_run()
        self.assertEqual(self.runner.state['last_run']['verdict'], 'red')
        self.assertEqual(self.runner.state['last_run']['faulted'], [])

    def test_no_route_and_unreadable_registry_fault_to_ops(self):
        self.single()
        self.passing_history()
        for key, registry_fault in [('missing', False), ('skein', True)]:
            self.advance(key)
            self.scenario['registry_fault'] = registry_fault
            self.scenario['pairs']['qa-skein'] = dict(main=[dict(test='one', result='fail')])
            # A passing predecessor is needed for a new red in each iteration.
            test_key = json.dumps(['qa-skein', 'pkg::qa', 'one'], separators=(',', ':'))
            self.runner.state['tests'][test_key] = dict(result='pass', commit=self.base)
            self.save_scenario()
            self.poll_run()
            self.assertIsNotNone(self.events('after-landing-run')[-1]['routing_fault'])
            self.assertEqual(self.calls('post')[-1]['args'][3], 'ops@hel8')
        self.assertTrue(all(call['args'][3] == 'ops@hel8' for call in self.calls('post')))

    def test_records_before_posts_stable_ids_and_accept_post_three(self):
        self.single()
        self.passing_history()
        self.advance('skein')
        self.scenario['pairs']['qa-skein'] = dict(main=[dict(test='one', result='fail')])
        self.scenario.update(record_code=1, post_code=1)
        self.save_scenario()
        self.poll_run()
        self.assertFalse(self.calls('post'))
        first = self.calls('record')[-1]['body']
        self.runner = app.Runner(self.args)
        self.runner.poll()
        self.assertEqual(self.calls('record')[-1]['body'], first)
        self.scenario['record_code'] = 0
        self.save_scenario()
        self.runner.poll()
        self.assertEqual(self.calls('record')[-1]['body'], first)
        first_body = self.calls('post')[-1]['body']
        self.scenario['post_code'] = 3
        self.save_scenario()
        self.runner.poll()
        self.assertEqual(self.calls('post')[-1]['body'], first_body)
        self.assertEqual(self.runner.state['outbox'], [])
        self.runner.poll()
        self.assertEqual(len(self.calls('post')), 2)

    def test_multiple_coordinators_one_post_each_and_other_suspects_in_body(self):
        self.single()
        self.passing_history()
        self.advance('skein')
        self.advance('q-jig')
        self.advance(subject='baseline suspect')
        self.scenario['pairs']['qa-skein'] = dict(main=[dict(test='one', result='fail')])
        self.save_scenario()
        self.poll_run()
        self.assertEqual({c['args'][3] for c in self.calls('post')}, {'s/qa@hel8', 's/dynamic-memory@hel8'})
        for call in self.calls('post'):
            self.assertIn('several suspects', call['body'])
            self.assertIn('baseline suspect', call['body'])
        self.assertTrue(self.events('after-landing-test')[-1]['branch'].startswith('ready/'))


class SupervisionTests(Sandbox):
    def test_restart_mid_run_redoes_same_attempt_and_ids(self):
        self.two()
        numeric = self.home / 'src/fabrig/slots/9'
        numeric.parent.mkdir(parents=True)
        self.slot.rename(numeric)
        self.slot = numeric
        self.args.slot = numeric
        self.argv[self.argv.index('--slot') + 1] = str(numeric)
        lease = self.home / 'lifetime.py'
        app.atomic(lease, LEASE)
        self.argv += ['--lifetime', str(lease)]
        self.runner = app.Runner(self.args)
        self.passing_history()
        self.advance('skein')
        self.scenario['pairs']['qa-skein'] = dict(main=[dict(test='one', result='fail')])
        self.scenario['pairs']['qa-jig']['wait'] = True
        self.save_scenario()
        parent = subprocess.Popen([sys.executable, '-I', '-B', str(TOOL), *self.argv],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: parent.kill() if parent.poll() is None else None)
        self.wait_file(self.home / 'tier-entered')
        parent.kill()
        parent.wait(timeout=5)
        active = json.loads(self.runner.path.read_text())['active']
        self.assertEqual(active['attempt'], 1)
        written = next(iter(active['events'].values()))
        self.assertEqual(len(list((self.home / 'lease').glob('*.hold'))), 1)
        app.atomic(self.home / 'tier-release', '')
        self.scenario['pairs']['qa-jig']['wait'] = False
        self.save_scenario()
        restart = subprocess.run([sys.executable, '-I', '-B', str(TOOL), *self.argv],
                                 text=True, capture_output=True, timeout=10)
        self.assertEqual(restart.returncode, 0, restart.stderr)
        self.runner = app.Runner(self.args)
        self.assertEqual(list((self.home / 'lease').glob('*.hold')), [])
        self.assertTrue(all(c['lease_held'] for c in self.calls('tiers')))
        events = self.events('after-landing-test')
        self.assertEqual(events[-1]['id'], active['tip'] + ':1:qa-skein:pkg::qa:one')
        self.assertEqual(events[-1]['state'], 'new')
        for key in ('id', 'state', 'time', 'logs'):
            self.assertEqual(events[-1][key], written[key])
        self.assertTrue(all(path in self.calls('post')[-1]['body'] for path in written['logs']))
        self.assertEqual(self.events('after-landing-run')[-1]['attempt'], 1)
        # Both pairs are redone, retaining the first pair's already-written ids.
        self.assertEqual(len(self.calls('tiers')), 6)

    def test_wall_bound_waits_for_heavy_end_before_next_pair(self):
        self.two()
        self.runner.poll()
        self.scenario['pairs']['qa-skein'] = dict(hang=True)
        self.save_scenario()
        self.runner.prepare()
        # Exercise the production guardian with a shortened bound, without a
        # test-only environment switch in the installed executable.
        import threading
        failures = []
        def run():
            try:
                with mock.patch.object(app, 'duration', return_value=-1799.3):
                    self.runner.run()
            except BaseException as error:
                failures.append(error)
        thread = threading.Thread(target=run)
        thread.start()
        end = time.monotonic() + 5
        while (not self.calls('heavy') or not self.calls('post')) and time.monotonic() < end:
            time.sleep(.02)
        try:
            self.assertTrue(self.calls('heavy'))
            self.assertEqual({c['profile'] for c in self.calls('tiers')}, {'qa-skein'})
            self.assertTrue(thread.is_alive())
            self.assertIsNone(self.runner.state['cursor'])
            self.assertIn('heavy command to end', self.calls('post')[0]['body'])
        finally:
            app.atomic(self.home / 'allow-end', '')
            thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        self.assertFalse(failures, failures)
        self.assertEqual([c['profile'] for c in self.calls('tiers')], ['qa-skein', 'qa-jig'])
        self.assertEqual(self.runner.state['last_run']['faulted'], ['qa-skein'])
        for call in self.calls('heavy'):
            self.assertEqual(call['args'], ['--cancel', 'a'*32])
            self.assertEqual(call['cwd'], str(self.slot))

    def test_submission_shim_stops_the_next_prerequisite(self):
        self.two()
        custom = self.home / 'custom-run'
        app.atomic(custom, "#!/usr/bin/env python3\nimport os, subprocess, sys\n"
                   "if sys.argv[1] == 'skein':\n"
                   "    subprocess.run(['heavy', 'first'], check=True)\n"
                   "    subprocess.run(['heavy', 'must-not-start'], check=True)\n"
                   "else:\n"
                   "    os.execv(" + repr(str(self.slot / 'tools/tiers/run')) + ", [" + repr(str(self.slot / 'tools/tiers/run')) + ", *sys.argv[1:]])\n")
        custom.chmod(0o755)
        self.args.tiers_run = custom
        self.runner.poll()
        import threading
        failures = []
        def run():
            try:
                with mock.patch.object(app, 'duration', return_value=-1799.3):
                    self.runner.run()
            except BaseException as error:
                failures.append(error)
        thread = threading.Thread(target=run)
        thread.start()
        try:
            deadline = time.monotonic() + 5
            while not self.calls('heavy') and time.monotonic() < deadline:
                time.sleep(.02)
            self.assertTrue(self.calls('heavy'))
            self.assertEqual(len(self.calls('heavy-submit')), 1)
            self.assertTrue(thread.is_alive())
        finally:
            app.atomic(self.home / 'allow-end', '')
            thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        self.assertFalse(failures, failures)
        self.assertEqual([c['args'] for c in self.calls('heavy-submit')], [['first']])
        self.assertEqual(self.runner.state['last_run']['faulted'], ['qa-skein'])

    def test_follow_polls_during_a_long_pair(self):
        self.single()
        self.args.mode = 'follow'
        self.args.poll_interval = .05
        self.runner.next_poll = time.monotonic()
        self.scenario['pairs']['qa-skein']['wait'] = True
        self.save_scenario()
        self.runner.poll()
        import threading
        failures = []
        def publish():
            try:
                self.wait_file(self.home / 'tier-entered')
                self.advance('skein')
                self.advance('q-jig')
                deadline = time.monotonic() + 5
                while self.runner.state['hour']['seen'] < 2 and time.monotonic() < deadline:
                    time.sleep(.02)
            except BaseException as error:
                failures.append(error)
            finally:
                app.atomic(self.home / 'tier-release', '')
        publisher = threading.Thread(target=publish)
        publisher.start()
        self.runner.run()
        publisher.join(timeout=5)
        self.assertFalse(failures, failures)
        self.assertEqual(self.runner.state['cursor'], self.base)
        self.assertGreaterEqual(self.runner.state['hour']['seen'], 2)
        self.assertTrue(self.runner.state['queue'])
        self.assertEqual(self.calls('tiers')[0]['head'], self.base)

    def test_missing_runner_is_a_pair_fault_not_unknown_completion(self):
        self.two()
        self.args.tiers_run = self.home / 'absent'
        self.runner.poll()
        self.runner.run()
        self.assertIsNone(self.runner.state['active'])
        self.assertEqual(self.runner.state['last_run']['faulted'], ['qa-skein', 'qa-jig'])
        self.assertIsNone(self.runner.state['cursor'])

    def test_interrupted_unknown_supervisor_never_switches_slot(self):
        self.runner.poll()
        self.runner.prepare()
        active = self.runner.state['active']
        artifact = self.home / 'orphan'
        artifact.mkdir()
        active['invocation'] = dict(result=str(artifact / 'result.json'), log=str(artifact / 'output.log'),
                                    waiting=str(artifact / 'waiting.json'))
        self.runner.save()
        self.runner.run()
        self.assertIsNotNone(self.runner.state['active'])
        self.assertFalse(self.calls('tiers'))
        self.assertIn('completion unknown', self.runner.state['outbox'][0]['posts'][0]['body'])


class ReviewTests(Sandbox):
    def test_record_fake_enforces_checked_in_writer_allowlist(self):
        real = os.environ['RECORD_WRITERS']
        self.poll_run()
        self.assertTrue(self.calls('record')[-1]['accepted'])
        refused = self.home / 'writers.toml'
        app.atomic(refused, '[collect]\nsources=["queue"]\n')
        os.environ['RECORD_WRITERS'] = str(refused)
        self.advance('skein')
        self.poll_run()
        self.assertFalse(self.calls('record')[-1]['accepted'])
        self.assertTrue(self.runner.state['outbox'])
        batch = self.calls('record')[-1]['body']
        os.environ['RECORD_WRITERS'] = real
        self.runner = app.Runner(self.args)
        self.runner.poll()
        self.assertTrue(self.calls('record')[-1]['accepted'])
        self.assertEqual(self.calls('record')[-1]['body'], batch)
        self.assertFalse(self.runner.state['outbox'])

    def test_large_events_use_detail_files_without_poisoning_poll(self):
        self.runner.poll()
        self.runner.prepare()
        active = self.runner.state['active']
        suspects = [dict(kind='other', commit=str(n), subject='subject ' + 'x'*600) for n in range(100)]
        suspects += [dict(kind='branch', key='skein', branch='ready/skein/bulk', tip=self.base)]
        self.runner.state['queue'][0].update(suspects=suspects, coalesced=[str(n) for n in range(1000)])
        logs = [str(self.home / ('log-' + str(n) + '-' + 'x'*100)) for n in range(1000)]
        alerts = [dict(identity=['qa-skein', 'pkg::qa', 'test-' + str(n) + 'x'*500],
                       error='failure ' + 'x'*400, logs=logs[:2], id='test-' + str(n)) for n in range(100)]
        active['pairs']['qa-skein'] = dict(status='ran', selected=1000, executed=1000, failed=1000,
                                         red=['test-' + str(n) for n in range(1000)], new=alerts, logs=logs, wall=1)
        event = self.runner.event('after-landing-test', 'large-test', commit=active['tip'],
                                  identity=['qa-skein', 'pkg::qa', 'one'], state='new', logs=logs)
        active['events']['large-test'] = event
        self.runner.finish()
        self.assertFalse(self.runner.state['outbox'])
        batch = self.calls('record')[-1]['body']
        self.assertTrue(all(len(line.encode()) + 1 < 16384 for line in batch.splitlines()))
        events = [json.loads(line) for line in batch.splitlines()]
        for event in events:
            detail = json.loads(Path(event['details']).read_text())
            if event['kind'] == 'after-landing-run':
                self.assertEqual(len(detail['suspects']), 101)
                self.assertEqual(len(detail['pairs']['qa-skein']['red']), 1000)
                self.assertEqual(event['confirmed_red_count'], 1000)
            else:
                self.assertEqual(len(detail['logs']), 1000)
        post = self.calls('post')[-1]['body']
        self.assertLess(len(post.encode()), 64000)
        self.assertLess(len(post.splitlines()), 15)
        detail_path = next(line.removeprefix('details: ') for line in post.splitlines() if line.startswith('details: '))
        self.assertEqual(len(json.loads(Path(detail_path).read_text())['new']), 100)
        # Existing oversized outboxes from an earlier version are normalized too.
        legacy = self.runner.event('after-landing-run', 'legacy', commit=self.base, suspects=suspects)
        self.runner.state['outbox'].append(dict(id='legacy', records=[legacy], posts=[], recorded=False))
        self.runner.save()
        tip, _ = self.advance('skein')
        self.runner.poll()
        self.assertEqual(self.runner.state['seen'], tip)
        self.assertFalse(self.runner.state['outbox'])
        huge = self.runner.event('after-landing-test', 'id' + 'x'*20000, commit=self.base,
                                 identity=['qa-skein', 'pkg::qa', 'x'*20000], state='new', logs=logs)
        bounded = self.runner.bounded_event(huge)
        self.assertLess(len(json.dumps(bounded).encode()), 16384)
        self.assertEqual(json.loads(Path(bounded['details']).read_text())['id'], huge['id'])
        self.assertEqual(bounded['id'], self.runner.bounded_event(huge)['id'])

    def test_confirmed_identity_survives_later_confirmation_fault(self):
        self.passing_history()
        for test in ('a', 'b'):
            key = json.dumps(['qa-skein', 'pkg::qa', test], separators=(',', ':'))
            self.runner.state['tests'][key] = dict(result='pass', commit=self.base)
        tip, _ = self.advance('skein')
        self.scenario['pairs']['qa-skein'] = dict(
            main=[dict(test='a', result='fail'), dict(test='b', result='fail')],
            reruns={'a': dict(tests=[dict(test='a', result='fail')]),
                    'b': dict(tests=[dict(test='b', result='fail')], code=2)})
        self.save_scenario()
        self.poll_run()
        self.assertEqual(self.runner.state['last_run']['verdict'], 'red')
        self.assertEqual(self.runner.state['last_run']['faulted'], ['qa-skein'])
        self.assertEqual(self.runner.state['cursor'], self.base)
        a = json.dumps(['qa-skein', 'pkg::qa', 'a'], separators=(',', ':'))
        self.assertEqual(self.runner.state['tests'][a]['result'], 'red')
        self.assertEqual(self.states(), ['new'])
        self.assertEqual({post['args'][3] for post in self.calls('post')}, {'s/dynamic-memory@hel8', 'ops@hel8'})
        event = self.events('after-landing-run')[-1]
        self.assertTrue(event['pairs']['qa-skein']['red'])
        self.scenario['pairs']['qa-skein']['reruns']['b'] = dict(tests=[dict(test='b')])
        self.save_scenario()
        self.poll_run()
        self.assertEqual(self.runner.state['cursor'], tip)
        self.assertEqual(self.runner.state['last_run']['verdict'], 'red')
        self.assertEqual(self.states()[-2:], ['standing', 'flake'])

    def test_unresolved_new_red_is_retried_after_restart(self):
        self.passing_history()
        self.advance('skein')
        self.scenario.update(registry_fault=True)
        self.scenario['pairs']['qa-skein'] = dict(main=[dict(test='one', result='fail')])
        self.save_scenario()
        self.poll_run()
        pending = self.runner.state['outbox'][0]
        identifier = pending['id']
        self.assertFalse(pending['notification']['resolved'])
        self.assertTrue(pending['recorded'])
        self.assertTrue(all(post['args'][3] == 'ops@hel8' for post in self.calls('post')))
        records = len(self.calls('record'))
        self.scenario['registry_fault'] = False
        self.save_scenario()
        self.runner = app.Runner(self.args)
        self.runner.poll()
        self.assertFalse(self.runner.state['outbox'])
        self.assertEqual(len(self.calls('record')), records)
        routed = [post for post in self.calls('post') if post['args'][3] != 'ops@hel8']
        self.assertEqual(len(routed), 1)
        self.assertIn('id: ' + identifier, routed[0]['body'])
        self.advance('skein')
        self.poll_run()
        self.assertEqual(self.states()[-1], 'standing')
        self.assertEqual(len([post for post in self.calls('post') if post['args'][3] != 'ops@hel8']), 1)

    def test_conflicting_and_hostless_routes_are_faults(self):
        original_rows = list(self.scenario['registry'])
        leads = self.slot / 'tools/queue/leads.txt'
        original_leads = leads.read_text()
        cases = [
            (original_rows + [dict(role='lead', branch_key='skein', coordinator_mailbox='s/other')], original_leads, 'skein'),
            (original_rows + [dict(role='lead', branch_key='q', coordinator_mailbox='s/other')], original_leads, 'q'),
            (original_rows, original_leads + 'ops ops@other-host\n', 'ops'),
            (original_rows, 'ops ops\n', 'ops'),
            (original_rows, original_leads + 'extra s/dynamic-memory@other-host\n', 'skein'),
        ]
        for rows, text, key in cases:
            with self.subTest(key=key, rows=rows, text=text):
                self.scenario['registry'] = rows
                self.save_scenario()
                app.atomic(leads, text)
                with self.assertRaises(app.Fault):
                    self.runner.resolve({key})
        self.scenario['registry'] = original_rows
        self.save_scenario()
        # leads.txt can legitimately address the lead while the registry
        # selects that lead's coordinator. Registry ownership takes precedence.
        app.atomic(leads, original_leads + 'skein lead/skein@hel8\n')
        self.assertEqual(self.runner.resolve({'skein'}), {'skein': 's/dynamic-memory@hel8'})

    def test_completion_and_fault_notice_are_one_atomic_save(self):
        class Crash(BaseException):
            pass
        self.runner.poll()
        self.scenario['pairs']['qa-skein']['code'] = 2
        self.save_scenario()
        real_save = self.runner.save
        completed = []
        def crash_after_completion():
            real_save()
            state = json.loads(self.runner.path.read_text())
            if state['active'] is None and state['last_run'] is not None:
                completed.append(state)
                raise Crash()
        with mock.patch.object(self.runner, 'save', side_effect=crash_after_completion):
            with self.assertRaises(Crash):
                self.runner.run()
        self.assertEqual(len(completed), 1)
        snapshot = completed[0]
        self.assertIsNotNone(snapshot['fault_episode'])
        self.assertEqual(snapshot['outbox'][0]['posts'][0]['to'], 'ops@hel8')
        self.assertFalse(snapshot['outbox'][0]['posts'][0]['delivered'])
        self.scenario['pairs']['qa-skein'].pop('code')
        self.save_scenario()
        self.runner = app.Runner(self.args)
        self.poll_run()
        self.assertEqual(self.runner.state['cursor'], self.base)
        self.assertEqual(len(self.calls('post')), 1)
        self.assertIn(snapshot['fault_episode'], self.calls('post')[0]['body'])

    def test_replay_compares_passing_skipped_and_red_outcomes(self):
        class Crash(BaseException):
            pass
        self.passing_history()
        tip, _ = self.advance('skein')
        self.scenario['pairs']['qa-skein'] = dict(main=[dict(test='one', result='fail')])
        self.save_scenario()
        self.runner.poll()
        with mock.patch.object(self.runner, 'finish', side_effect=Crash()):
            with self.assertRaises(Crash):
                self.runner.run()
        saved = json.loads(self.runner.path.read_text())
        event = next(iter(saved['active']['events'].values()))
        self.scenario['pairs']['qa-skein'] = dict(main=[dict(test='one')])
        self.save_scenario()
        self.runner = app.Runner(self.args)
        self.runner.run()
        key = json.dumps(['qa-skein', 'pkg::qa', 'one'], separators=(',', ':'))
        self.assertEqual(self.runner.state['tests'][key]['result'], 'red')
        self.assertEqual(self.runner.state['last_run']['verdict'], 'red')
        self.assertEqual(self.runner.state['last_run']['faulted'], ['qa-skein'])
        self.assertEqual(self.events('after-landing-test')[-1]['id'], event['id'])
        self.assertEqual(self.runner.state['cursor'], self.base)
        self.poll_run()
        self.assertEqual(self.states()[-1], 'recovered')
        self.assertEqual(self.runner.state['cursor'], tip)
        # Passing and skipped observations have no event but must still be
        # checked on replay, including changes in the selected identity set.
        self.advance('skein')
        self.runner.poll()
        self.runner.prepare()
        active = self.runner.state['active']
        active['pairs']['qa-skein'] = dict(red=[], new=[])
        for result, state in [('pass', 'passing'), ('unobserved', 'unobserved')]:
            name = key + state
            observation = dict(result=result, state=state, logs=[], event=None, alert=None)
            self.runner.stage_observation('qa-skein', name, observation)
            changed = dict(observation, result='red', state='new')
            with self.assertRaises(app.Fault):
                self.runner.stage_observation('qa-skein', name, changed)
            self.assertEqual(active['observations']['qa-skein'][name]['result'], result)
        active['selections']['qa-skein'] = [key, 'missing identity']
        with self.assertRaises(app.Fault):
            self.runner.pair('qa-skein')


class ParserTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='after-landing-parser-')
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)

    def test_pinned_nextest_junit_and_exact_filter_escaping(self):
        fixture = self.home / 'fixture.xml'
        app.atomic(fixture, '''<?xml version="1.0" encoding="UTF-8"?>
<testsuites name="nextest-run" tests="3" failures="1">
  <testsuite name="my-package::integration" tests="3" failures="1">
    <testcase name="module::ok" classname="my-package::integration" time="0.001"/>
    <testcase name="module::broken" classname="my-package::integration" time="0.002">
      <failure message="test failed" type="test failure">assertion failed\nsecond line</failure>
    </testcase>
    <testcase name="module::ignored" classname="my-package::integration"><skipped/></testcase>
  </testsuite>
</testsuites>''')
        count, results = app.junit(fixture, 'qa-skein')
        self.assertEqual(count, 3)
        self.assertEqual([r['result'] for r in results.values()], ['pass', 'fail', 'unobserved'])
        self.assertEqual(list(results.values())[1]['identity'], ['qa-skein', 'my-package::integration', 'module::broken'])
        self.assertEqual(list(results.values())[1]['error'], 'assertion failed')
        self.assertEqual(app.exact_filter('a"b\\c', 'x)y,z'),
                         'binary_id(="a\\"b\\\\c") & test(="x)y,z")')
        app.atomic(fixture, '<testsuites tests="2"><testsuite name="x"><testcase name="a"/></testsuite></testsuites>')
        with self.assertRaises(app.Fault):
            app.junit(fixture, 'qa-skein')

    def test_confirmation_selection_requires_one_same_executed_identity(self):
        identity = json.dumps(['qa-skein', 'binary', 'test'])
        passed = {identity: dict(result='pass')}
        self.assertEqual(app.validate_rerun(identity, 1, passed), 'pass')
        for count, results in [(0, {}), (2, passed), (1, {'different': dict(result='fail')}),
                               (1, {identity: dict(result='unobserved')}),
                               (1, {identity: dict(result='fail'), 'other': dict(result='pass')})]:
            with self.subTest(count=count, results=results):
                with self.assertRaises(app.Fault):
                    app.validate_rerun(identity, count, results)

    def test_config_round_trip_and_duration(self):
        import tomllib
        original = dict(profile={'qa-skein': {'default-filter': 'test(="a")',
                                              'overrides': [{'filter': 'all()', 'retries': 2}],
                                              'junit': {'path': '/tmp/not-used.xml'}}}, experimental=['x'])
        encoded = '\n'.join(json.dumps(k) + ' = ' + app.toml_value(v) for k, v in original.items())
        self.assertEqual(tomllib.loads(encoded), original)
        self.assertEqual(app.duration('1h 2m 3s 4ms'), 3723.004)
        for value in ('infinite', '0s', 'x1s', None):
            with self.assertRaises(app.Fault):
                app.duration(value)

class StateTests(Sandbox):
    def test_state_privacy_and_duplicate_runner_lock(self):
        self.poll_run()
        self.assertEqual(self.runner.directory.stat().st_mode & 0o777, 0o700)
        self.assertEqual(self.runner.path.stat().st_mode & 0o777, 0o600)
        with app.lock(self.runner.directory / 'runner.lock'):
            with self.assertRaises(app.Fault):
                with app.lock(self.runner.directory / 'runner.lock'):
                    pass


if __name__ == '__main__':
    unittest.main()
