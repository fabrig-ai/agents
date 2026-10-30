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
import threading
import time
import unittest
from types import SimpleNamespace
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
import re
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
elif name == 'trim':
    state = json.loads((home / 'state/state.json').read_text())
    slot = Path(sys.argv[-1])
    log(dict(tool=name, args=sys.argv[1:], active=state['active'],
             last_run=state['last_run'], pending=state['trim_pending'],
             records=[event for group in state['outbox'] for event in group['records']],
             head=__import__('subprocess').check_output(['git', '-C', slot, 'rev-parse', 'HEAD'], text=True).strip()))
    if scenario.get('trim_code', 0):
        print('fake trim failed', file=sys.stderr)
        sys.exit(scenario['trim_code'])
    print(f'{slot}: 2 executables, 1.234 GB freed; 100.000 GB free; 0 processes skipped')
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
    head = __import__('subprocess').check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    pair = scenario.get('commits', {}).get(head, {}).get(profile, scenario['pairs'][profile])
    chosen = pair.get('rerun', pair.get('main', [])) if rerun else pair.get('main', [])
    override = {}
    log(dict(tool='tiers', profile=profile, rerun=rerun, args=sys.argv[1:],
             head=__import__('subprocess').check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
             heavy_class=os.environ.get('HEAVY_CLASS'),
             lease_held=bool(os.fstat(int(os.environ['TEST_LEASE_FD']))) if 'TEST_LEASE_FD' in os.environ else None))
    if rerun:
        expression = sys.argv[sys.argv.index('-E') + 1]
        if expression.startswith('('):
            identities = re.findall(r'\(binary_id\(=([^()]+)\) & test\(=([^()]+)\)\)', expression)
            if not identities or expression != ' | '.join(f'(binary_id(={b}) & test(={t}))' for b, t in identities):
                sys.exit(94)
            chosen = [row for row in pair.get('main', [])
                      if (row.get('binary', 'pkg::qa'), row.get('test', 'one')) in identities]
            if len(identities) == 1 and pair.get('reruns'):
                override = pair['reruns'][identities[0][1]]
                chosen = override['tests']
            if 'selection' in pair:
                chosen = pair['selection']
            binary, test = identities[0]
            separator = True
        else:
            binary, separator, test = expression.removeprefix('binary_id(=').partition(') & test(=')
        test = test.removesuffix(')')
        # Nextest 0.9.148 treats quotes literally, so quoted binary IDs miss.
        if binary.startswith('"') or test.startswith('"'):
            print("operator didn't match any binary IDs", file=sys.stderr)
            sys.exit(94)
        if not separator:
            sys.exit(94)
        if not expression.startswith('(') and pair.get('reruns'):
            override = pair['reruns'][test]
            chosen = override['tests']
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
    code_key = 'code' if rerun and expression.startswith('(') else 'rerun_code' if rerun else 'code'
    code = override.get('code', pair.get(code_key, 100 if any(row.get('result') == 'fail' for row in chosen) else 0))
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


# Runner and guardian share frozen absolute and monotonic clocks. Only a test's
# explicit atomic advance changes either clock; real time is a watchdog only.
CLOCK_GUARDIAN = r"""import importlib.machinery
import importlib.util
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace

loader = importlib.machinery.SourceFileLoader('guardian_subject', TOOL_PATH)
spec = importlib.util.spec_from_loader(loader.name, loader)
app = importlib.util.module_from_spec(spec)
loader.exec_module(app)
app.__file__ = __file__
def clock_value(name):
    return json.loads((Path.home() / 'clock.json').read_text())[name]
app.time = SimpleNamespace(time=lambda: clock_value('wall'),
                           monotonic=lambda: clock_value('monotonic'),
                           time_ns=lambda: int(clock_value('wall') * 1_000_000_000), sleep=time.sleep)
if sys.argv[1] != '_supervise':
    sys.exit(app.main())
path = Path(sys.argv[2])
invocation = json.loads(path.read_text())
initialized = False
start_mono = None
def now():
    global initialized, start_mono
    value = clock_value('monotonic')
    if not initialized:
        initialized = True
        start_mono = value
        app.atomic(path.parent / 'clock-started', '')
        return value
    # Older section 2 fixtures advance this invocation's monotonic clock only.
    if invocation['command'][1] == 'skein' and (Path.home() / 'expire-skein').exists():
        return max(value, start_mono + invocation.get('wall_bound', invocation['bound']) + 1)
    return value
app.time.monotonic = now
app.atomic(path.parent / 'started', '')
sys.exit(app.supervise(path, int(sys.argv[3])))
"""


class ControlledClock:
    def __init__(self, home):
        self.path = home / 'clock.json'
        app.write_json(self.path, dict(wall=1_800_000_000, monotonic=0))
        self.sleep = time.sleep

    def time(self):
        return json.loads(self.path.read_text())['wall']

    def monotonic(self):
        return json.loads(self.path.read_text())['monotonic']

    def time_ns(self):
        return int(self.time() * 1_000_000_000)

    def advance(self, *, wall=0, monotonic=0):
        value = json.loads(self.path.read_text())
        value['wall'] += wall
        value['monotonic'] += monotonic
        app.write_json(self.path, value)


class Sandbox(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='after-landing-test-')
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name)
        self.tool = self.home / 'clocked-after-landing.py'
        app.atomic(self.tool, CLOCK_GUARDIAN.replace('TOOL_PATH', repr(str(TOOL))))
        guardian = mock.patch.object(app, '__file__', str(self.tool))
        guardian.start()
        self.addCleanup(guardian.stop)
        self.environment = mock.patch.dict(os.environ, dict(
            HOME=str(self.home), GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL='/dev/null',
            GIT_AUTHOR_NAME='test', GIT_AUTHOR_EMAIL='test@example.invalid',
            GIT_COMMITTER_NAME='test', GIT_COMMITTER_EMAIL='test@example.invalid',
            PYTHONDONTWRITEBYTECODE='1', RECORD_WRITERS=str(HERE.parent / 'records/writers.toml')), clear=True)
        self.environment.start()
        # Retain only a safe system PATH, with no personal wrappers/services.
        os.environ['PATH'] = '/usr/local/bin:/usr/bin:/bin'
        self.addCleanup(self.environment.stop)
        self.clock = ControlledClock(self.home)
        clock_patch = mock.patch.object(app, 'time', self.clock)
        clock_patch.start()
        self.addCleanup(clock_patch.stop)
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
        (self.seed / 'tools/slots').mkdir()
        app.atomic(self.seed / 'tools/tiers/run', FAKE)
        app.atomic(self.seed / 'tools/slots/trim', FAKE)
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
        for name in ('post', 'record', 'registry', 'heavy', 'trim'):
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
        for name in ('post', 'record', 'registry', 'heavy', 'trim'):
            self.argv += ['--' + name, str(self.bin / name)]
        self.args = app.arguments(self.argv)
        app.private_directory(self.args.state_dir)
        self.runner = app.Runner(self.args)

    def git(self, cwd, *args):
        result = subprocess.run(['git', '-C', str(cwd), *map(str, args)],
                                stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120)
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

    def wait_for(self, condition, description, worker=None):
        # Conditions determine progress. This generous watchdog only diagnoses a
        # broken handshake; it never drives a tier timeout or a test transition.
        end = time.monotonic() + 120
        while not condition():
            if worker is not None:
                alive = worker.poll() is None if isinstance(worker, subprocess.Popen) else worker.is_alive()
                self.assertTrue(alive, 'worker exited while waiting for ' + description)
            if time.monotonic() >= end:
                self.fail('timed out waiting for ' + description)
            time.sleep(.01)

    def wait_file(self, path, worker=None):
        self.wait_for(path.exists, str(path), worker)


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
        hourly_time = self.runner.state['hour']['start'] + 3601
        clock = SimpleNamespace(time=lambda: hourly_time)
        with mock.patch.object(app, 'time', clock):
            self.runner.hourly()
        self.runner.deliver()
        bodies = [p['body'] for p in self.calls('post')]
        self.assertEqual(len(bodies), 2)
        self.assertIn('published tips seen: 5; runs completed: 2; tips coalesced: 2', bodies[0])
        self.assertIn('oldest waiting lag seconds:', bodies[0])
        self.assertIn('trim bytes freed: 2468000000', bodies[0])
        self.assertEqual(self.runner.state['hour']['trim_bytes'], 0)
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
        status = subprocess.run([sys.executable, '-I', '-B', str(self.tool), 'status', '--state-dir', str(empty)],
                                text=True, capture_output=True, timeout=120)
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertFalse(empty.exists())
        dry = subprocess.run([sys.executable, '-I', '-B', str(self.tool), *self.argv, '--dry-run'],
                             text=True, capture_output=True, timeout=120)
        self.assertEqual(dry.returncode, 0, dry.stderr)
        plan = json.loads(dry.stdout)
        self.assertEqual(plan['previous'], before)
        self.assertEqual(len(plan['suspects']), 3)
        self.assertEqual(self.calls(), [])
        self.assertFalse(self.runner.path.exists())


class TrimTests(Sandbox):
    def assert_trim_after_saved_verdict(self, verdict):
        # A failed publisher leaves the saved event/outbox available for the
        # fake trim to inspect, independently of remote record durability.
        self.scenario['record_code'] = 1
        self.save_scenario()
        self.poll_run()
        calls = self.calls('trim')
        self.assertEqual(len(calls), 1)
        call = calls[0]
        self.assertEqual(call['args'], ['--older', '0', str(self.slot)])
        self.assertIsNone(call['active'])
        self.assertEqual(call['last_run']['verdict'], verdict)
        self.assertEqual(call['pending'], dict(id=call['last_run']['id'], started=True))
        event = next(event for event in call['records'] if event['kind'] == 'after-landing-run')
        self.assertEqual(event['verdict'], verdict)
        self.assertEqual(event['id'], call['last_run']['id'])
        self.assertEqual(self.runner.state['last_trim']['id'], event['id'])
        self.assertEqual(self.runner.state['last_trim']['bytes_freed'], 1_234_000_000)
        self.runner.run()
        # Partial attempts retain their tip; a second attempt is a new run.
        expected = 2 if verdict == 'partial' else 1
        self.assertEqual(len(self.calls('trim')), expected)

    def test_trim_once_after_saved_green(self):
        self.assert_trim_after_saved_verdict('green')

    def test_trim_once_after_saved_red(self):
        self.scenario['pairs']['qa-skein']['main'] = [dict(test='one', result='fail')]
        self.assert_trim_after_saved_verdict('red')

    def test_trim_once_after_saved_partial(self):
        self.scenario['pairs']['qa-skein']['code'] = 2
        self.assert_trim_after_saved_verdict('partial')

    def test_trim_precedes_next_checkout(self):
        self.poll_run()
        next_tip, _ = self.advance()
        self.runner.poll()
        real_git = app.git
        checkouts = []
        def git(slot, *argv):
            if argv[0] == 'checkout':
                checkouts.append(argv[-1])
                self.assertEqual(len(self.calls('trim')), 1)
                self.assertEqual(self.calls('trim')[0]['head'], self.base)
                self.assertEqual(self.runner.state['last_trim']['id'], self.base + ':1')
            return real_git(slot, *argv)
        with mock.patch.object(app, 'git', side_effect=git):
            self.runner.run()
        self.assertEqual(checkouts, [next_tip])
        self.assertEqual(len(self.calls('trim')), 2)

    def test_trim_failure_episode_survives_restart_and_runs_proceed(self):
        self.scenario['trim_code'] = 1
        self.save_scenario()
        for attempt in range(2):
            if attempt:
                self.runner = app.Runner(self.args)
                self.advance()
            self.poll_run()
            self.assertEqual(self.runner.state['last_run']['verdict'], 'green')
            self.assertEqual(self.runner.state['last_run']['faulted'], [])
            self.assertIsNone(self.runner.state['fault_episode'])
            self.assertEqual(self.runner.state['last_trim']['code'], 1)
            self.assertIn('fake trim failed', self.runner.state['last_trim']['error'])
            self.assertEqual(len(self.calls('post')), 1)
        self.scenario['trim_code'] = 0
        self.save_scenario()
        self.advance()
        self.poll_run()
        self.assertIsNone(self.runner.state['trim_fault_episode'])
        self.scenario['trim_code'] = 1
        self.save_scenario()
        self.advance()
        self.poll_run()
        self.assertEqual(len(self.calls('tiers')), 4)
        self.assertEqual(len(self.calls('trim')), 4)
        self.assertEqual(len(self.calls('post')), 2)
        self.assertTrue(all(call['args'][3] == 'ops@hel8' for call in self.calls('post')))
        self.assertTrue(all('trim exit 1' in call['body'] for call in self.calls('post')))

    def test_saved_pending_trim_resumes_before_checkout(self):
        class Crash(BaseException):
            pass
        real_trim = self.runner.trim
        def trim():
            if self.runner.state['trim_pending']:
                raise Crash()
            real_trim()
        with mock.patch.object(self.runner, 'trim', side_effect=trim):
            with self.assertRaises(Crash):
                self.poll_run()
        self.assertEqual(self.calls('trim'), [])
        self.runner = app.Runner(self.args)
        tip, _ = self.advance()
        real_git = app.git
        def git(slot, *argv):
            if argv[0] == 'checkout':
                self.assertEqual(len(self.calls('trim')), 1)
                self.assertEqual(self.calls('trim')[0]['head'], self.base)
            return real_git(slot, *argv)
        with mock.patch.object(app, 'git', side_effect=git):
            self.poll_run()
        self.assertEqual(self.runner.state['cursor'], tip)
        self.assertEqual(len(self.calls('trim')), 2)

    def test_interrupted_trim_is_not_repeated_or_blocking(self):
        class Crash(BaseException):
            pass
        real_save = self.runner.save
        def save():
            if self.runner.state['last_trim'] is not None:
                raise Crash()
            real_save()
        with mock.patch.object(self.runner, 'save', side_effect=save):
            with self.assertRaises(Crash):
                self.poll_run()
        self.assertEqual(len(self.calls('trim')), 1)
        self.runner = app.Runner(self.args)
        self.runner.run()
        self.assertEqual(len(self.calls('trim')), 1)
        self.assertIn('completion unknown', self.runner.state['last_trim']['error'])
        self.runner.deliver()
        self.assertEqual(len(self.calls('post')), 1)
        tip, _ = self.advance()
        self.poll_run()
        self.assertEqual(self.runner.state['cursor'], tip)
        self.assertEqual(len(self.calls('trim')), 2)

    def test_existing_state_loads_without_migration(self):
        self.passing_history()
        old = json.loads(self.runner.path.read_text())
        for key in ('last_trim', 'trim_pending', 'trim_fault_episode', 'bisect'):
            old.pop(key)
        old['hour'].pop('trim_bytes')
        old['hour'].pop('bisect_seconds')
        app.write_json(self.runner.path, old)
        before = self.runner.path.read_bytes()
        self.runner = app.Runner(self.args)
        self.assertEqual(self.runner.path.read_bytes(), before)
        self.assertEqual(self.runner.state['tests'], old['tests'])
        self.assertEqual(self.runner.state['hour']['trim_bytes'], 0)
        self.assertIsNone(self.runner.state['trim_pending'])
        tip, _ = self.advance()
        self.poll_run()
        self.assertEqual(self.runner.state['cursor'], tip)
        self.assertEqual(len(self.calls('trim')), 1)

    def test_default_trim_path_is_in_the_slot(self):
        self.args.trim = None
        self.poll_run()
        self.assertEqual(len(self.calls('trim')), 1)
        self.assertIsNone(self.runner.state['last_trim']['error'])


class VerdictTests(Sandbox):
    def test_live_identity_confirmation_uses_unquoted_exact_filter(self):
        binary = 'temper-client-browser-world::qa_all'
        test = 'qa_task_pages::typed_agent_address_survives_reload_and_a_lineage_round_trip'
        self.scenario['pairs']['qa-skein'] = dict(main=[dict(binary=binary, test=test, result='fail')])
        self.save_scenario()
        self.poll_run()
        self.assertEqual(self.runner.state['last_run']['verdict'], 'red')
        rerun, = [row for row in self.calls('tiers') if row['rerun']]
        self.assertEqual(rerun['args'][-2:], ['-E', f'binary_id(={binary}) & test(={test})'])

    def test_quoted_matchers_are_rejected_by_fake_nextest(self):
        self.scenario['pairs']['qa-skein'] = dict(main=[dict(test='one', result='fail')])
        self.save_scenario()
        with mock.patch.object(app, 'exact_filter', return_value='binary_id(="pkg::qa") & test(="one")'):
            self.poll_run()
        self.assertEqual(self.runner.state['last_run']['verdict'], 'partial')
        self.assertEqual(self.runner.state['last_run']['faulted'], ['qa-skein'])
        self.assertEqual(self.events('after-landing-run')[-1]['pairs']['qa-skein']['error'],
                         'tiers/run exit 94')
        self.assertFalse(self.states())

    def test_unsafe_identity_faults_without_confirmation(self):
        self.scenario['pairs']['qa-skein'] = dict(main=[dict(test='unsafe)test', result='fail')])
        self.save_scenario()
        self.poll_run()
        self.assertEqual(self.runner.state['last_run']['verdict'], 'partial')
        self.assertEqual(self.events('after-landing-run')[-1]['pairs']['qa-skein']['error'],
                         'identity not expressible as an exact filter')
        self.assertFalse(any(row['rerun'] for row in self.calls('tiers')))
        self.assertFalse(self.states())

    def test_confirmation_non_test_exits_stay_faults(self):
        for code in (94, 2, 101):
            with self.subTest(code=code):
                self.scenario['pairs']['qa-skein'] = dict(
                    main=[dict(test='one', result='fail')], rerun_code=code)
                self.save_scenario()
                self.poll_run()
                self.assertEqual(self.runner.state['last_run']['verdict'], 'partial')
                self.assertEqual(self.runner.state['last_run']['faulted'], ['qa-skein'])
                self.assertFalse(self.states())

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
            if 'bisection' in call['body']:
                continue
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
        parent = subprocess.Popen([sys.executable, '-I', '-B', str(self.tool), *self.argv],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        def finish_parent():
            app.atomic(self.home / 'tier-release', '')
            if parent.poll() is None:
                parent.kill()
            parent.wait(timeout=120)
        self.addCleanup(finish_parent)
        self.wait_file(self.home / 'tier-entered', parent)
        parent.kill()
        parent.wait(timeout=120)
        active = json.loads(self.runner.path.read_text())['active']
        self.assertEqual(active['attempt'], 1)
        written = next(iter(active['events'].values()))
        self.assertEqual(len(list((self.home / 'lease').glob('*.hold'))), 1)
        app.atomic(self.home / 'tier-release', '')
        self.scenario['pairs']['qa-jig']['wait'] = False
        self.save_scenario()
        restart = subprocess.run([sys.executable, '-I', '-B', str(self.tool), *self.argv],
                                 text=True, capture_output=True, timeout=120)
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

    def start_clocked_run(self):
        self.failures = []
        def run():
            try:
                self.runner.run()
            except BaseException as error:
                self.failures.append(error)
        thread = threading.Thread(target=run)
        thread.start()
        def finish():
            app.atomic(self.home / 'allow-end', '')
            thread.join(timeout=120)
            self.assertFalse(thread.is_alive(), 'runner did not finish after fake release')
        self.addCleanup(finish)
        return thread

    def expire_skein(self, thread):
        # Wait for both clock initialization and the fake's queued token before
        # advancing time, even if the child runs before the guardian does.
        def queued():
            active = self.runner.state['active']
            invocation = active and active['invocation']
            return (invocation and
                    (Path(invocation['log']).parent / 'clock-started').exists() and
                    bool(app.heavy_tokens(invocation['log'])[0]))
        self.wait_for(queued, 'skein heavy queued token', thread)
        app.atomic(self.home / 'expire-skein', '')
        self.wait_for(lambda: self.calls('heavy'), 'heavy cancellation acknowledgement', thread)

    def test_wall_bound_waits_for_heavy_end_before_next_pair(self):
        self.two()
        self.runner.poll()
        self.scenario['pairs']['qa-skein'] = dict(hang=True)
        self.save_scenario()
        self.runner.prepare()
        thread = self.start_clocked_run()
        self.expire_skein(thread)
        self.wait_for(lambda: self.calls('post'), 'waiting-for-heavy notice', thread)
        try:
            self.assertTrue(self.calls('heavy'))
            self.assertEqual({c['profile'] for c in self.calls('tiers')}, {'qa-skein'})
            self.assertTrue(thread.is_alive())
            self.assertIsNone(self.runner.state['cursor'])
            self.assertEqual(self.calls('trim'), [])
            self.assertIn('heavy command to end', self.calls('post')[0]['body'])
        finally:
            app.atomic(self.home / 'allow-end', '')
            thread.join(timeout=120)
        self.assertFalse(thread.is_alive())
        self.assertFalse(self.failures, self.failures)
        self.assertEqual([c['profile'] for c in self.calls('tiers')], ['qa-skein', 'qa-jig'])
        self.assertEqual(self.runner.state['last_run']['faulted'], ['qa-skein'])
        self.assertEqual(len(self.calls('trim')), 1)
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
        thread = self.start_clocked_run()
        try:
            self.expire_skein(thread)
            self.assertEqual(len(self.calls('heavy-submit')), 1)
            self.assertTrue(thread.is_alive())
        finally:
            app.atomic(self.home / 'allow-end', '')
            thread.join(timeout=120)
        self.assertFalse(thread.is_alive())
        self.assertFalse(self.failures, self.failures)
        self.assertEqual([c['args'] for c in self.calls('heavy-submit')], [['first']])
        self.assertEqual(self.runner.state['last_run']['faulted'], ['qa-skein'])
        event = self.events('after-landing-run')[-1]
        self.assertEqual(event['pairs']['qa-skein']['error'], 'pair wall bound passed')
        self.assertEqual(event['pairs']['qa-jig']['status'], 'ran')
        self.assertEqual(event['pairs']['qa-jig']['wall'], 0)
        self.assertEqual([c['profile'] for c in self.calls('tiers')], ['qa-jig'])

    def test_follow_polls_during_a_long_pair(self):
        self.single()
        self.args.mode = 'follow'
        self.args.poll_interval = 10
        published = threading.Event()
        clock = SimpleNamespace(monotonic=lambda: 11 if published.is_set() else 0,
                                time=self.clock.time, time_ns=self.clock.time_ns, sleep=time.sleep)
        self.scenario['pairs']['qa-skein']['wait'] = True
        self.save_scenario()
        self.runner.poll()
        failures = []
        def publish():
            try:
                self.wait_file(self.home / 'tier-entered')
                self.advance('skein')
                self.advance('q-jig')
                published.set()
                self.wait_for(lambda: self.runner.state['hour']['seen'] >= 2, 'follow poll of new tips')
            except BaseException as error:
                failures.append(error)
            finally:
                app.atomic(self.home / 'tier-release', '')
        publisher = threading.Thread(target=publish)
        with mock.patch.object(app, 'time', clock):
            self.runner.next_poll = self.args.poll_interval
            publisher.start()
            self.runner.run()
            publisher.join(timeout=120)
        self.assertFalse(publisher.is_alive(), 'publisher did not finish after tier release')
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
        self.assertEqual(self.calls('trim'), [])
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
        for alert in alerts:
            key = json.dumps(alert['identity'], separators=(',', ':'))
            active['baseline'][key] = dict(result='pass', commit=self.base)
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


class BisectionTests(Sandbox):
    def key(self, name='one', profile='qa-skein'):
        return json.dumps([profile, 'pkg::qa', name], separators=(',', ':'))

    def setup_interval(self, count=4, names=('one',)):
        self.passing_history()
        for name in names:
            self.runner.state['tests'][self.key(name)] = dict(result='pass', commit=self.base)
        self.runner.save()
        commits = [self.advance('skein' if i % 2 == 0 else 'q-jig')[0] for i in range(count)]
        self.scenario['pairs']['qa-skein'] = dict(
            main=[dict(test=name, result='fail') for name in names],
            reruns={name: dict(tests=[dict(test=name, result='fail')]) for name in names})
        self.scenario['commits'] = {self.base: {'qa-skein': dict(main=[dict(test=name) for name in names])}}
        self.save_scenario()
        return commits

    def at(self, commit, rows=None, **values):
        self.scenario.setdefault('commits', {}).setdefault(commit, {})['qa-skein'] = dict(
            main=rows if rows is not None else [dict(test='one')], **values)
        self.save_scenario()

    def pending(self):
        with mock.patch.object(self.runner, 'bisect'):
            self.poll_run()
        self.assertIsNotNone(self.runner.state['bisect'])
        return self.runner.state['bisect']

    def bisect_events(self):
        return self.events('after-landing-bisect')

    def probe_commits(self, event):
        return [probe['commit'] for probe in json.loads(Path(event['details']).read_text())['probes']]

    def test_interval_uses_identity_good_older_than_cursor(self):
        commits = self.setup_interval(4)
        self.runner.state['cursor'] = commits[2]
        self.runner.state['seen'] = commits[2]
        self.runner.save()
        phase = self.pending()
        self.assertEqual(phase['groups'][0]['GOOD'], self.base)
        self.assertEqual(phase['groups'][0]['candidates'], commits)
        self.assertEqual(phase['deadline'] - phase['started'], 2700)
        saved = json.loads(self.runner.path.read_text())
        self.assertEqual(saved['version'], 2)
        # The pre-change Runner rejects this before any polling or checkout.
        self.assertNotEqual(saved['version'], 1)
        tests, cursor, verdict = saved['tests'], saved['cursor'], saved['last_run']
        self.runner.run()
        self.assertEqual(self.runner.state['tests'], tests)
        self.assertEqual(self.runner.state['cursor'], cursor)
        self.assertEqual(self.runner.state['last_run'], verdict)
        self.runner.deliver()
        self.assertEqual(self.bisect_events()[0]['candidate_count'], 4)

    def test_single_commit_interval_has_no_bisection(self):
        self.setup_interval(1)
        self.poll_run()
        self.assertIsNone(self.runner.state['bisect'])
        self.assertFalse(self.bisect_events())
        self.assertEqual(len(self.calls('tiers')), 2)
        self.assertEqual(self.runner.state['version'], 1)

    def test_branch_merge_culprit_is_proven_with_passing_parent(self):
        commits = self.setup_interval(4)
        self.at(commits[0])
        self.poll_run()
        event, = self.bisect_events()
        self.assertEqual(event['result'], 'culprit proven')
        self.assertEqual(event['culprit_commit'], commits[1])
        self.assertEqual(event['commit'], commits[1])
        self.assertTrue(event['branch'].startswith('ready/q-jig/'))
        self.assertEqual(self.probe_commits(event), [self.base, commits[1], commits[0]])
        self.assertEqual(event['id'], commits[-1] + ':1:bisect:1')
        for row in self.calls('tiers')[2:]:
            self.assertTrue(row['args'][-1].startswith('(binary_id(=pkg::qa)'))
            self.assertEqual(row['heavy_class'], 'background')
        self.assertEqual(len(self.calls('trim')), 2)
        self.assertTrue(all(post['body'].count('\n') < 14 for post in self.calls('post')))
        records_at = [i for i, row in enumerate(self.calls()) if row['tool'] == 'record' and 'after-landing-bisect' in row['body']]
        posts_at = [i for i, row in enumerate(self.calls()) if row['tool'] == 'post' and 'bisection results' in row['body']]
        self.assertLess(max(records_at), min(posts_at))

    def test_tip_culprit_is_proven_without_reprobe(self):
        commits = self.setup_interval(2)
        self.at(commits[0])
        self.poll_run()
        event, = self.bisect_events()
        self.assertEqual(event['culprit_commit'], commits[-1])
        self.assertEqual(self.probe_commits(event), [self.base, commits[0]])
        self.assertEqual([call['head'] for call in self.calls('tiers')].count(commits[-1]), 2)

    def test_other_culprit_tells_ops(self):
        self.passing_history()
        culprit, _ = self.advance(subject='direct regression')
        self.advance('skein')
        self.scenario['pairs']['qa-skein'] = dict(main=[dict(test='one', result='fail')])
        self.at(self.base)
        self.poll_run()
        event, = self.bisect_events()
        self.assertEqual(event['result'], 'culprit proven')
        self.assertEqual(event['culprit_commit'], culprit)
        self.assertEqual(event['culprit']['subject'], 'direct regression')
        self.assertNotIn('branch', event)
        posts = [row for row in self.calls('post') if 'bisection results' in row['body']]
        self.assertEqual({row['args'][3] for row in posts}, {'ops@hel8', 's/dynamic-memory@hel8'})

    def test_older_culprit_adds_missing_coordinator(self):
        commits = self.setup_interval(3)
        self.runner.state.update(cursor=commits[1], seen=commits[1])
        self.runner.save()
        self.at(commits[0])
        self.poll_run()
        self.assertEqual(self.bisect_events()[0]['culprit_commit'], commits[1])
        posts = [row for row in self.calls('post') if 'bisection results' in row['body']]
        self.assertEqual({row['args'][3] for row in posts}, {'s/dynamic-memory@hel8', 's/qa@hel8'})

    def test_good_failing_now_is_inconclusive(self):
        self.setup_interval()
        self.at(self.base, [dict(test='one', result='fail')])
        self.poll_run()
        event, = self.bisect_events()
        self.assertEqual(event['result'], 'inconclusive')
        self.assertIsNone(event['culprit_commit'])
        self.assertEqual(self.probe_commits(event), [self.base])

    def test_unbuildable_middle_alternates_older_then_newer(self):
        commits = self.setup_interval(6)
        self.at(commits[2], code=101)
        self.at(commits[1], code=101)
        self.at(commits[3], code=101)
        self.at(commits[0])
        self.poll_run()
        event, = self.bisect_events()
        self.assertEqual(self.probe_commits(event)[:5], [self.base, commits[2], commits[1], commits[3], commits[0]])
        self.assertEqual(event['result'], 'range')
        probes = json.loads(Path(event['details']).read_text())['probes']
        self.assertEqual(probes[1]['outcome'], 'unbuildable')

    def test_nextest_build_failed_101_all_unbuildable_gives_range(self):
        # Pinned to nextest_metadata::NextestExitCode::BUILD_FAILED:
        # https://nexte.st/rustdoc/src/nextest_metadata/exit_codes.rs
        self.assertEqual(app.BUILD_FAILED, 101)
        commits = self.setup_interval(4, ('one', 'two'))
        for commit in commits[:-1]:
            self.at(commit, code=101)
        self.poll_run()
        event, = self.bisect_events()
        self.assertEqual(event['result'], 'range')
        self.assertEqual(event['good'], self.base)
        self.assertEqual(event['bad'], commits[-1])
        self.assertEqual(event['interval'], dict(good=self.base, bad=commits[-1], between=commits[:-1]))
        self.assertEqual(event['number'], '1')
        self.assertEqual(len(event['identities']), 2)
        self.assertIsNone(event['culprit_commit'])
        self.assertFalse([post for post in self.calls('post') if post['args'][3] == 'ops@hel8'])

    def test_flake_and_skipped_confirmation_are_unknown(self):
        commits = self.setup_interval(3, ('one', 'two'))
        # Both fail the group probe and are rerun alone. One passes, the other
        # is selected but skipped; neither is a confirmed bad.
        rows = [dict(test=name, result='fail') for name in ('one', 'two')]
        reruns = {'one': dict(tests=[dict(test='one')]),
                  'two': dict(tests=[dict(test='two', result='skip')])}
        self.at(commits[0], rows, reruns=reruns)
        self.at(commits[1], [dict(test=name, result='skip') for name in ('one', 'two')])
        self.poll_run()
        event, = self.bisect_events()
        self.assertEqual(event['result'], 'range')
        probes = json.loads(Path(event['details']).read_text())['probes']
        self.assertEqual([probe['outcome'] for probe in probes], ['good', 'unknown', 'unknown'])
        group_call = self.calls('tiers')[3]
        self.assertIn(') | (binary_id', group_call['args'][-1])
        # Each failed group member is confirmed with its own exact filter.
        expressions = [row['args'][-1] for row in self.calls('tiers') if '-E' in row['args']]
        self.assertIn('(binary_id(=pkg::qa) & test(=two))', expressions)

    def test_group_splits_good_bad_unknown_with_stable_order(self):
        commits = self.setup_interval(4, ('one', 'two', 'three'))
        self.at(commits[1], [dict(test='one', result='fail'), dict(test='two'), dict(test='three', result='skip')])
        self.at(commits[0], [dict(test=name) for name in ('one', 'two', 'three')])
        self.at(commits[2], [dict(test='one', result='fail'), dict(test='two', result='fail'), dict(test='three', result='skip')])
        self.poll_run()
        events = self.bisect_events()
        self.assertEqual([event['identities'][0][2] for event in events], ['one', 'two', 'three'])
        self.assertEqual([event['result'] for event in events], ['culprit proven', 'culprit proven', 'range'])
        self.assertEqual([event['id'] for event in events], [commits[-1] + f':1:bisect:{n}' for n in ('1.1', '1.2', '1.3')])
        self.assertEqual([event['culprit_commit'] for event in events[:2]], [commits[1], commits[2]])

    def test_selection_fault_ends_all_groups_and_posts_ops_once(self):
        commits = self.setup_interval(4, ('one', 'two'))
        self.at(commits[1], selection=[dict(test='unexpected')])
        phase = self.pending()
        self.runner.run()
        self.runner.deliver()
        self.assertEqual({event['result'] for event in self.bisect_events()}, {'inconclusive'})
        self.assertEqual(phase['count'], 2)
        self.assertEqual(len([post for post in self.calls('post') if post['args'][3] == 'ops@hel8']), 1)
        self.runner = app.Runner(self.args)
        self.runner.poll()
        self.assertEqual(len([post for post in self.calls('post') if post['args'][3] == 'ops@hel8']), 1)

    def test_tiers_fault_keeps_completed_group_and_stops_unresolved(self):
        commits = self.setup_interval(4, ('one', 'two'))
        self.at(commits[1], [dict(test='one', result='fail'), dict(test='two')])
        self.at(commits[0], [dict(test='one')])
        self.at(commits[2], code=2)
        self.poll_run()
        self.assertEqual([event['result'] for event in self.bisect_events()], ['culprit proven', 'inconclusive'])
        self.assertEqual(len([post for post in self.calls('post') if post['args'][3] == 'ops@hel8']), 1)

    def test_invocation_budget_includes_confirmations_across_groups(self):
        self.setup_interval(4, ('one', 'two'))
        phase = self.pending()
        phase['count'] = 14
        # GOOD group launch is #15; then the first failure's confirmation is
        # #17 and must never launch after the middle group invocation #16.
        self.runner.save()
        before = len(self.calls('tiers'))
        self.runner.run()
        self.runner.deliver()
        self.assertEqual(phase['count'], 16)
        self.assertEqual(len(self.calls('tiers')) - before, 2)
        event, = self.bisect_events()
        self.assertEqual(event['result'], 'range')
        self.assertEqual(self.probe_commits(event), [self.base])
        self.assertFalse([post for post in self.calls('post') if post['args'][3] == 'ops@hel8'])

    def test_deadline_preserves_narrowed_range_and_bounds_invocation(self):
        commits = self.setup_interval(6)
        self.at(commits[2])
        phase = self.pending()
        real_save = self.runner.save_bisect_probe
        def expire_after_middle(index, commit, outcomes, logs):
            real_save(index, commit, outcomes, logs)
            if commit == commits[2]:
                self.clock.advance(wall=121, monotonic=121)
        phase['deadline'] = self.clock.time() + 120
        with mock.patch.object(self.runner, 'save_bisect_probe', side_effect=expire_after_middle):
            self.runner.run()
        self.runner.deliver()
        event, = self.bisect_events()
        self.assertEqual(event['result'], 'range')
        self.assertEqual(event['good'], commits[2])
        self.assertEqual(event['bad'], commits[-1])
        for path in self.runner.directory.glob('run-*/spec.json'):
            invocation = json.loads(path.read_text())
            if invocation['command'][-1].startswith('('):
                self.assertGreater(invocation['bound'], 0)
                self.assertLessEqual(invocation['bound'], 120)
        self.assertFalse([post for post in self.calls('post') if post['args'][3] == 'ops@hel8'])

    def test_restart_unknown_heavy_drains_then_redoes_whole_probe(self):
        self.setup_interval(4)
        phase = self.pending()
        artifact = self.home / 'orphan-bisect'
        artifact.mkdir()
        app.atomic(artifact / 'output.log', 'heavy: queued task 1 in build token ' + 'a' * 32 + '\n')
        phase['invocation'] = dict(result=str(artifact / 'result.json'), log=str(artifact / 'output.log'),
                                   waiting=str(artifact / 'waiting.json'))
        phase['probe'] = dict(index=0, commit=self.base)
        phase['count'] = 1
        self.runner.save()
        before = len(self.calls('tiers'))
        self.runner = app.Runner(self.args)
        with mock.patch.object(app, 'git', wraps=app.git) as git:
            self.runner.run()
            self.assertFalse(git.called)
        self.assertEqual(len(self.calls('tiers')), before)
        saved = json.loads(self.runner.path.read_text())['bisect']
        self.assertEqual(saved['invocation']['heavy_tokens'], ['a' * 32])
        self.assertEqual(saved['deadline'], phase['deadline'])
        app.atomic(self.home / 'allow-end', '')
        self.runner = app.Runner(self.args)
        self.runner.run()
        self.runner.deliver()
        self.assertEqual(self.calls('tiers')[before]['head'], self.base)
        self.assertTrue(self.calls('heavy'))
        self.assertEqual(self.bisect_events()[0]['result'], 'culprit proven')

    def test_restart_after_saved_probe_keeps_outcome_and_absolute_deadline(self):
        class Crash(BaseException):
            pass
        self.setup_interval(4)
        phase = self.pending()
        deadline = phase['deadline']
        real_save = self.runner.save_bisect_probe
        def crash_after_saved(*args):
            real_save(*args)
            raise Crash()
        with mock.patch.object(self.runner, 'save_bisect_probe', side_effect=crash_after_saved):
            with self.assertRaises(Crash):
                self.runner.run()
        self.runner = app.Runner(self.args)
        self.assertEqual(self.runner.state['bisect']['deadline'], deadline)
        self.assertEqual(self.runner.state['bisect']['count'], 1)
        self.assertEqual(self.runner.state['bisect']['groups'][0]['probes'][0]['outcome'], 'good')
        self.runner.run()
        self.runner.deliver()
        probes = self.probe_commits(self.bisect_events()[0])
        self.assertEqual(probes.count(self.base), 1)
        self.assertEqual(len([call for call in self.calls('tiers') if call['head'] == self.base]), 1)

    def test_final_events_posts_trim_atomic_and_replay_stable(self):
        class Crash(BaseException):
            pass
        self.setup_interval(4)
        self.scenario.update(record_code=1, post_code=1)
        self.save_scenario()
        self.pending()
        real_save = self.runner.save
        def crash_after_completed():
            real_save()
            state = self.runner.state
            if state['bisect'] is None and any(item['id'].endswith(':bisect') for item in state['outbox']):
                raise Crash()
        with mock.patch.object(self.runner, 'save', side_effect=crash_after_completed):
            with self.assertRaises(Crash):
                self.runner.run()
        snapshot = json.loads(self.runner.path.read_text())
        event = snapshot['outbox'][-1]['records'][0]
        self.assertTrue(snapshot['trim_pending']['id'].endswith(':bisect'))
        self.assertEqual(len(self.calls('trim')), 1)
        self.runner = app.Runner(self.args)
        self.runner.run()
        self.runner.deliver()
        self.assertEqual(len(self.calls('trim')), 2)
        self.assertEqual(self.runner.state['outbox'][-1]['records'][0], event)
        self.scenario['record_code'] = 0
        self.save_scenario()
        self.runner = app.Runner(self.args)
        self.runner.poll()
        bodies = [post['body'] for post in self.runner.state['outbox'][-1]['posts']]
        self.assertTrue(all(record == event for record in self.bisect_events()))
        self.scenario['post_code'] = 3
        self.save_scenario()
        self.runner = app.Runner(self.args)
        self.runner.poll()
        self.assertEqual(self.runner.state['outbox'], [])
        self.assertEqual([row['body'] for row in self.calls('post') if 'bisection results' in row['body']], [body + '\n' for body in bodies])

    def test_bisect_post_waits_for_run_without_holding_slot(self):
        self.setup_interval(4)
        self.scenario['post_code'] = 1
        self.save_scenario()
        self.poll_run()
        self.assertIsNone(self.runner.state['bisect'])
        self.assertIsNone(self.runner.state['active'])
        self.assertIsNone(self.runner.state['trim_pending'])
        self.assertFalse([row for row in self.calls('post') if 'bisection results' in row['body']])
        self.assertTrue(self.bisect_events())  # Records may proceed independently.
        result_group = self.runner.state['outbox'][-1]
        self.assertEqual(result_group['after'], self.runner.state['outbox'][0]['id'])
        self.assertTrue(all('run event id: ' + result_group['after'] in post['body']
                            for post in result_group['posts']))
        self.advance('skein')
        self.poll_run()
        self.assertEqual(self.runner.state['last_run']['verdict'], 'red')
        self.scenario['post_code'] = 0
        self.save_scenario()
        self.runner = app.Runner(self.args)
        self.runner.poll()
        calls = self.calls('post')
        first_bisect = next(i for i, row in enumerate(calls) if 'bisection results' in row['body'])
        self.assertTrue(all('bisection results' not in row['body'] for row in calls[:first_bisect]))
        self.assertEqual(self.runner.state['outbox'], [])

    def test_unresolved_run_routes_follow_bisect_after_registry_recovers(self):
        self.setup_interval(4)
        self.scenario['registry_fault'] = True
        self.save_scenario()
        self.poll_run()
        self.assertIsNone(self.runner.state['bisect'])
        self.assertTrue(self.runner.state['outbox'][-1]['notification']['bisect'])
        self.scenario['registry_fault'] = False
        self.save_scenario()
        self.runner = app.Runner(self.args)
        self.runner.poll()
        self.assertFalse(self.runner.state['outbox'])
        self.assertEqual(len([row for row in self.calls('post') if 'bisection results' in row['body']]), 2)

    def test_hourly_counts_bisection_minutes_and_arriving_tips(self):
        self.setup_interval(4)
        phase = self.pending()
        self.clock.advance(wall=30, monotonic=30)
        new, _ = self.advance('skein')
        self.runner.poll()
        self.assertEqual(phase['arrived'], [new])
        self.clock.advance(wall=90, monotonic=90)
        self.runner.state['hour']['start'] = self.clock.time() - 3600
        self.runner.hourly()
        self.runner.deliver()
        coverage = [post['body'] for post in self.calls('post') if 'bisection minutes:' in post['body']]
        self.assertEqual(len(coverage), 2)
        self.assertTrue(all(body.rstrip().endswith('bisection minutes: 2.0') for body in coverage))
        self.assertEqual(self.runner.state['hour']['bisect_seconds'], 0)
        self.assertEqual(self.runner.state['bisect']['accounted_at'], phase['started'] + 120)
        self.runner = app.Runner(self.args)
        self.clock.advance(wall=60, monotonic=60)
        self.runner.run()
        self.runner.deliver()
        event, = self.bisect_events()
        self.assertEqual(event['arrived'], [new])
        self.assertEqual(event['wall'], 180)
        self.assertEqual(self.runner.state['hour']['bisect_seconds'], 60)
        self.clock.advance(wall=3600, monotonic=3600)
        self.runner.hourly()
        self.runner.deliver()
        coverage = [post['body'] for post in self.calls('post') if 'bisection minutes:' in post['body']]
        self.assertEqual(len(coverage), 4)
        self.assertTrue(all(body.rstrip().endswith('bisection minutes: 1.0') for body in coverage[2:]))
        self.assertEqual(self.runner.state['hour']['bisect_seconds'], 0)

    def test_deadline_cancels_and_drains_before_final_trim(self):
        self.assert_bisect_wall_termination(deadline_capped=True)

    def test_section_two_wall_bound_stays_fault_when_deadline_passes_during_drain(self):
        self.assert_bisect_wall_termination(deadline_capped=False)

    def assert_bisect_wall_termination(self, *, deadline_capped):
        self.setup_interval(4)
        phase = self.pending()
        phase['deadline'] = self.clock.time() + (60 if deadline_capped else 3600)
        self.runner.save()
        self.at(self.base, hang=True)
        before = len(self.calls('tiers'))
        failures = []
        def run():
            try:
                self.runner.run()
            except BaseException as error:
                failures.append(error)
        worker = threading.Thread(target=run)
        worker.start()
        try:
            def queued():
                invocation = phase['invocation']
                return (invocation and (Path(invocation['log']).parent / 'clock-started').exists()
                        and app.heavy_tokens(invocation['log'])[0])
            self.wait_for(queued, 'bisection heavy submission', worker)
            invocation = phase['invocation']
            self.assertLessEqual(invocation['bound'], 60 if deadline_capped else 1801)
            self.assertEqual(invocation['deadline_bound'], deadline_capped)
            advance = 60 if deadline_capped else 1802
            self.clock.advance(wall=advance, monotonic=advance)
            self.wait_for(lambda: self.calls('heavy'), 'bisection cancellation', worker)
            self.wait_for(lambda: Path(invocation['waiting']).exists(), 'guardian waiting for heavy', worker)
            self.assertTrue(worker.is_alive())
            self.assertEqual(len(self.calls('trim')), 1)
            self.assertEqual(len(self.calls('tiers')) - before, 1)
            self.assertIsNotNone(self.runner.state['bisect'])
            if not deadline_capped:
                self.clock.advance(wall=2000, monotonic=2000)
        finally:
            app.atomic(self.home / 'allow-end', '')
            worker.join(timeout=120)
        self.assertFalse(worker.is_alive())
        self.assertFalse(failures, failures)
        result = json.loads(Path(invocation['result']).read_text())
        self.assertEqual(result['timeout_cause'], 'deadline' if deadline_capped else 'wall')
        self.runner.deliver()
        self.assertEqual(self.bisect_events()[0]['result'], 'range' if deadline_capped else 'inconclusive')
        self.assertEqual(len(self.calls('trim')), 2)
        self.assertIsNone(self.runner.state['bisect'])

    def test_distinct_good_commits_and_pairs_form_ordered_groups(self):
        commits = self.setup_interval(3, ('one', 'two'))
        self.two()
        self.runner.state['tests'][self.key('two')] = dict(result='pass', commit=commits[0])
        self.scenario['pairs']['qa-jig'] = dict(main=[dict(test='one', result='fail')])
        self.runner.save()
        self.save_scenario()
        phase = self.pending()
        self.assertEqual([group['profile'] for group in phase['groups']], ['qa-skein', 'qa-skein', 'qa-jig'])
        self.assertEqual([group['GOOD'] for group in phase['groups']], [self.base, commits[0], self.base])
        self.assertEqual([group['number'] for group in phase['groups']], ['1', '2', '3'])
        self.assertTrue(all(len(group['identities']) == 1 for group in phase['groups']))

    def test_large_bisect_event_keeps_result_and_private_probe_details(self):
        event = self.runner.event('after-landing-bisect', self.base + ':1:bisect:1',
                                  commit=self.base, tip=self.base, attempt=1, GOOD=self.base,
                                  candidate_count=4, result='range', culprit_commit=None,
                                  identities=[['qa-skein', 'binary', 'x' * 20000]],
                                  probes=[dict(commit=self.base, outcome='unknown')])
        bounded = self.runner.bounded_event(event)
        self.assertLess(len(json.dumps(bounded).encode()) + 1, 16384)
        self.assertEqual(bounded['identities_count'], 1)
        self.assertEqual(bounded['result'], 'range')
        detail = Path(bounded['details'])
        self.assertEqual(detail.stat().st_mode & 0o777, 0o600)
        self.assertEqual(json.loads(detail.read_text()), event)


    def test_good_bad_and_unknown_parts_end_only_those_parts(self):
        commits = self.setup_interval(4, ('one', 'two', 'three'))
        self.at(self.base, [dict(test='one', result='fail'), dict(test='two'),
                            dict(test='three', result='skip')])
        self.poll_run()
        events = self.bisect_events()
        self.assertEqual([event['number'] for event in events], ['1.1', '1.2', '1.3'])
        self.assertEqual([event['result'] for event in events],
                         ['inconclusive', 'culprit proven', 'inconclusive'])
        self.assertEqual([event['identities'][0][2] for event in events], ['one', 'two', 'three'])
        self.assertEqual(events[1]['culprit_commit'], commits[0])
        for event in (events[0], events[2]):
            self.assertEqual(self.probe_commits(event), [self.base])
        self.assertEqual(len([row for row in self.calls('tiers') if row['head'] == commits[-1]]), 4)

    def test_good_flake_and_skipped_confirmation_are_inconclusive(self):
        self.setup_interval(4, ('one', 'two'))
        self.at(self.base, [dict(test='one', result='fail'), dict(test='two', result='fail')],
                reruns={'one': dict(tests=[dict(test='one')]),
                        'two': dict(tests=[dict(test='two', result='skip')])})
        self.poll_run()
        event, = self.bisect_events()
        self.assertEqual(event['number'], '1')
        self.assertEqual(event['result'], 'inconclusive')
        self.assertEqual(self.probe_commits(event), [self.base])
        self.assertEqual(json.loads(Path(event['details']).read_text())['probes'][0]['outcome'], 'unknown')

    def test_good_unbuildable_is_whole_group_inconclusive(self):
        self.setup_interval(4, ('one', 'two'))
        self.at(self.base, code=101)
        self.poll_run()
        event, = self.bisect_events()
        self.assertEqual(event['number'], '1')
        self.assertEqual(event['result'], 'inconclusive')
        self.assertEqual(len(event['identities']), 2)
        self.assertEqual(self.probe_commits(event), [self.base])
        self.assertEqual(json.loads(Path(event['details']).read_text())['probes'][0]['outcome'], 'unbuildable')

    def test_confirmation_build_failure_is_whole_group_unbuildable(self):
        commits = self.setup_interval(4, ('one', 'two'))
        self.at(commits[1], [dict(test='one', result='fail'), dict(test='two')],
                reruns={'one': dict(tests=[dict(test='one')], code=101)})
        self.at(commits[0], code=101)
        self.at(commits[2], code=101)
        self.poll_run()
        event, = self.bisect_events()
        self.assertEqual(event['number'], '1')
        self.assertEqual(event['result'], 'range')
        self.assertEqual(len(event['identities']), 2)
        probes = json.loads(Path(event['details']).read_text())['probes']
        self.assertEqual([probe['outcome'] for probe in probes], ['good', 'unbuildable', 'unbuildable', 'unbuildable'])
        self.assertEqual(len(probes[1]['logs']), 2)

    def test_initial_numbers_use_first_parent_age_not_lexical_hash(self):
        old, newer, middle, tip = ('f' * 40, 'a' * 40, 'b' * 40, 'c' * 40)
        active = dict(tip=tip, attempt=1, profiles=['qa-jig', 'qa-skein'], baseline={})
        alerts = []
        for profile in active['profiles']:
            # Deliberately insert the newer GOOD first as well.
            for name, good in [('two', newer), ('one', old)]:
                key = self.key(name, profile)
                active['baseline'][key] = dict(result='pass', commit=good)
                alerts.append(dict(identity=json.loads(key)))
        def git(slot, *argv):
            if argv[0] == 'rev-list':
                return '\n'.join([newer, middle, tip] if argv[-1] == old + '..' + tip else [middle, tip])
            self.assertEqual(argv[0], 'rev-parse')
            return old if argv[-1] == newer + '^1' else newer
        run = dict(id=tip + ':1', notification=dict(destinations=[]))
        with mock.patch.object(app, 'git', side_effect=git):
            phase = self.runner.pending_bisection(active, alerts, run)
        self.assertEqual([group['GOOD'] for group in phase['groups']], [old, newer, old, newer])
        self.assertEqual([group['profile'] for group in phase['groups']], ['qa-jig', 'qa-jig', 'qa-skein', 'qa-skein'])
        self.assertEqual([group['number'] for group in phase['groups']], ['1', '2', '3', '4'])

    def test_sparse_nested_split_numbers_survive_restart_and_replay(self):
        class Crash(BaseException):
            pass
        commits = self.setup_interval(6, ('one', 'two', 'three'))
        self.at(commits[2], [dict(test='one', result='fail'), dict(test='two', result='skip'),
                            dict(test='three', result='skip')])
        self.at(commits[0], [dict(test=name) for name in ('one', 'two', 'three')])
        self.at(commits[1], [dict(test='one'), dict(test='two'), dict(test='three', result='skip')])
        self.at(commits[3], [dict(test='one', result='fail'), dict(test='two', result='fail'),
                            dict(test='three', result='skip')])
        self.at(commits[4], [dict(test='one', result='fail'), dict(test='two', result='fail'),
                            dict(test='three', result='skip')])
        self.pending()
        real_save = self.runner.save_bisect_probe
        def crash_after_split(*args):
            real_save(*args)
            if args[1] == commits[2]:
                raise Crash()
        with mock.patch.object(self.runner, 'save_bisect_probe', side_effect=crash_after_split):
            with self.assertRaises(Crash):
                self.runner.run()
        saved = json.loads(self.runner.path.read_text())['bisect']
        self.assertEqual([group['number'] for group in saved['groups']], ['1.1', '1.3'])
        self.scenario.update(record_code=1, post_code=1)
        self.save_scenario()
        self.runner = app.Runner(self.args)
        self.runner.run()
        self.runner.deliver()
        outbox = self.runner.state['outbox'][-1]
        ids = [commits[-1] + ':1:bisect:' + number for number in ('1.1', '1.3.2', '1.3.3')]
        self.assertEqual([event['id'] for event in outbox['records']], ids)
        self.assertEqual([event['number'] for event in outbox['records']], ['1.1', '1.3.2', '1.3.3'])
        self.assertTrue(outbox['notification']['resolved'])  # Resolved at creation, before publication.
        self.assertEqual(outbox['after'], commits[-1] + ':1')
        self.scenario.update(record_code=0, post_code=3)
        self.save_scenario()
        self.runner = app.Runner(self.args)
        self.runner.poll()
        self.assertFalse(self.runner.state['outbox'])
        self.assertEqual({event['id'] for event in self.bisect_events()}, set(ids))
        for event in self.bisect_events():
            self.assertNotIn(commits[-1], self.probe_commits(event))

    def test_restart_mid_confirmation_discards_entire_partial_probe(self):
        class Crash(BaseException):
            pass
        commits = self.setup_interval(4, ('one', 'two'))
        self.at(commits[0], [dict(test='one'), dict(test='two')])
        self.pending()
        real_launch, real_popen = self.runner.launch, app.subprocess.Popen
        launched_counts = []
        def popen(argv, *args, **kwargs):
            if '_supervise' in argv:
                state = json.loads(self.runner.path.read_text())
                phase = state['bisect']
                self.assertIsNotNone(phase['invocation'])
                self.assertEqual(phase['invocation']['result'], json.loads(Path(argv[-2]).read_text())['result'])
                launched_counts.append(phase['count'])
            return real_popen(argv, *args, **kwargs)
        def crash_after_first_confirmation(profile, *args, **kwargs):
            result = real_launch(profile, *args, **kwargs)
            phase = self.runner.state['bisect']
            if phase['count'] == 3:
                raise Crash()
            return result
        with mock.patch.object(app.subprocess, 'Popen', side_effect=popen), \
                mock.patch.object(self.runner, 'launch', side_effect=crash_after_first_confirmation):
            with self.assertRaises(Crash):
                self.runner.run()
        self.assertEqual(launched_counts, [1, 2, 3])
        saved = json.loads(self.runner.path.read_text())['bisect']
        group, = saved['groups']
        self.assertEqual(group['number'], '1')
        self.assertEqual([probe['commit'] for probe in group['probes']], [self.base])
        self.assertEqual((group['lo'], group['hi']), (0, 4))
        self.assertEqual(saved['probe']['commit'], commits[1])
        self.assertEqual(saved['count'], 3)
        before = len(self.calls('tiers'))
        self.runner = app.Runner(self.args)
        self.assertEqual(self.runner.state['bisect']['deadline'], saved['deadline'])
        self.runner.run()
        self.runner.deliver()
        redone = self.calls('tiers')[before:before + 3]
        self.assertEqual([call['head'] for call in redone], [commits[1]] * 3)
        self.assertIn(' | ', redone[0]['args'][-1])
        self.assertNotIn(' | ', redone[1]['args'][-1])
        self.assertNotIn(' | ', redone[2]['args'][-1])
        event, = self.bisect_events()
        self.assertEqual(event['id'], commits[-1] + ':1:bisect:1')
        self.assertEqual(event['culprit_commit'], commits[1])
        self.assertEqual(self.probe_commits(event), [self.base, commits[1], commits[0]])


    def test_finish_preparation_failure_preserves_state_and_never_duplicates_posts(self):
        self.setup_interval(3)
        self.runner.poll()
        with mock.patch.object(self.runner, 'finish'):
            self.runner.run()
        before = json.loads(json.dumps(self.runner.state))
        saved_before = self.runner.path.read_bytes()
        real_git = app.git
        def fail_parent_read(slot, *argv):
            if argv[0] == 'rev-parse' and argv[-1].endswith('^1'):
                raise app.Fault('injected bisection preparation failure')
            return real_git(slot, *argv)
        with mock.patch.object(app, 'git', side_effect=fail_parent_read):
            with self.assertRaisesRegex(app.Fault, 'injected bisection preparation failure'):
                self.runner.finish()
        self.assertEqual(self.runner.state, before)
        self.assertEqual(self.runner.path.read_bytes(), saved_before)
        # The same outer error path as follow/once may safely save and deliver
        # the ops fault. No unfinished run notification may have escaped.
        self.runner.fault('injected bisection preparation failure')
        self.runner.deliver()
        self.assertEqual([post['args'][3] for post in self.calls('post')], ['ops@hel8'])
        self.runner = app.Runner(self.args)
        self.runner.run()
        self.runner.deliver()
        run_posts = [post for post in self.calls('post') if 'new reds: ' in post['body']]
        self.assertEqual(len(run_posts), 2)
        self.assertEqual({post['args'][3] for post in run_posts}, {'s/dynamic-memory@hel8', 's/qa@hel8'})
        self.assertEqual(self.runner.state['last_run']['verdict'], 'red')
        self.assertIsNone(self.runner.state['active'])

    def test_bisect_routes_and_retries_use_tip_snapshot_after_historical_probe(self):
        self.passing_history()
        culprit, _ = self.advance('mc')
        leads = self.seed / 'tools/queue/leads.txt'
        app.atomic(leads, leads.read_text().replace('mc s/multi-coord@hel8', 'mc s/current-multi@hel8'))
        self.git(self.seed, 'add', 'tools/queue/leads.txt')
        tip, _ = self.advance('skein')
        self.scenario['pairs']['qa-skein'] = dict(main=[dict(test='one', result='fail')])
        self.at(self.base)
        self.pending()
        self.assertEqual({post['args'][3] for post in self.calls('post')},
                         {'s/current-multi@hel8', 's/dynamic-memory@hel8'})
        self.scenario['registry_fault'] = True
        self.save_scenario()
        self.runner = app.Runner(self.args)
        self.runner.run()
        self.runner.deliver()
        self.assertEqual(self.bisect_events()[0]['culprit_commit'], culprit)
        self.assertEqual(self.git(self.slot, 'rev-parse', 'HEAD'), culprit)
        self.assertNotEqual(culprit, tip)
        self.scenario['registry_fault'] = False
        self.save_scenario()
        self.runner = app.Runner(self.args)
        self.runner.poll()
        result_posts = [post for post in self.calls('post') if 'bisection results' in post['body']]
        self.assertEqual({post['args'][3] for post in result_posts},
                         {'s/current-multi@hel8', 's/dynamic-memory@hel8'})
        self.assertFalse(self.runner.state['outbox'])

    def test_saved_guardian_deadline_cause_overrides_prestart_wall_cap(self):
        self.setup_interval(4)
        phase = self.pending()
        phase['deadline'] = app.time.time() + 3600
        self.runner.save()
        real_popen = app.subprocess.Popen
        results = []
        class FinishedGuardian:
            def poll(self):
                return 0
            def wait(self):
                return 0
        def popen(argv, *args, **kwargs):
            if '_supervise' not in argv:
                return real_popen(argv, *args, **kwargs)
            spec_path = Path(argv[-2])
            invocation = json.loads(spec_path.read_text())
            self.assertFalse(invocation['deadline_bound'])
            # A guardian delayed past the absolute deadline publishes its
            # actual cause even though the pre-start shorter cap was the wall.
            app.write_json(Path(invocation['result']), dict(
                code=2, timeout=True, timeout_cause='deadline', elapsed=0))
            app.atomic(spec_path.parent / 'started', '')
            results.append(invocation)
            return FinishedGuardian()
        with mock.patch.object(app.subprocess, 'Popen', side_effect=popen):
            self.runner.run()
        self.runner.deliver()
        self.assertEqual(len(results), 1)
        self.assertEqual(self.bisect_events()[0]['result'], 'range')
        self.assertFalse([post for post in self.calls('post') if post['args'][3] == 'ops@hel8'])

    def test_guardian_obeys_both_frozen_clocks_and_explicit_advances(self):
        subject = self.home / 'clock-probe-subject.py'
        app.atomic(subject, '''import json
import os
from pathlib import Path
import tempfile
import time

def atomic(path, text):
    fd, sibling = tempfile.mkstemp(dir=path.parent)
    with os.fdopen(fd, 'w') as output:
        output.write(text)
    os.replace(sibling, path)

def supervise(path, fd):
    for number in (0, 1):
        atomic(Path.home() / ('clock-snapshot-' + str(number)),
               json.dumps([time.time(), time.monotonic()]))
        while not (Path.home() / ('clock-release-' + str(number))).exists():
            time.sleep(.01)
    return 0
''')
        probe_tool = self.home / 'clock-probe.py'
        app.atomic(probe_tool, CLOCK_GUARDIAN.replace('TOOL_PATH', repr(str(subject))))
        invocation = self.home / 'clock-probe-spec.json'
        app.write_json(invocation, dict(command=['run', 'skein'], bound=100))
        clock_path = self.home / 'clock.json'
        app.write_json(clock_path, dict(wall=10000, monotonic=10))
        worker = subprocess.Popen([sys.executable, '-I', '-B', str(probe_tool),
                                   '_supervise', str(invocation), '-1'])
        try:
            self.wait_file(self.home / 'clock-snapshot-0', worker)
            self.assertEqual(json.loads((self.home / 'clock-snapshot-0').read_text()), [10000, 10])
            app.write_json(clock_path, dict(wall=10037, monotonic=15))
            app.atomic(self.home / 'clock-release-0', '')
            self.wait_file(self.home / 'clock-snapshot-1', worker)
            self.assertEqual(json.loads((self.home / 'clock-snapshot-1').read_text()), [10037, 15])
        finally:
            app.atomic(self.home / 'clock-release-0', '')
            app.atomic(self.home / 'clock-release-1', '')
            worker.wait(timeout=120)
        self.assertEqual(worker.returncode, 0)


    def test_guardian_records_deadline_expiry_during_startup(self):
        self.setup_interval(4)
        phase = self.pending()
        phase['deadline'] = self.clock.time() + 3600
        self.runner.save()
        real_popen = app.subprocess.Popen
        invocations = []
        def delayed_start(argv, *args, **kwargs):
            if '_supervise' in argv:
                invocation = json.loads(Path(argv[-2]).read_text())
                self.assertFalse(invocation['deadline_bound'])
                self.assertEqual(invocation['wall_bound'], 1801)
                # Startup is the explicit handshake: expire absolute time only
                # after the runner has persisted its invocation and count.
                self.assertEqual(json.loads(self.runner.path.read_text())['bisect']['count'], 1)
                self.clock.advance(wall=3600, monotonic=3600)
                invocations.append(invocation)
            return real_popen(argv, *args, **kwargs)
        before = len(self.calls('tiers'))
        with mock.patch.object(app.subprocess, 'Popen', side_effect=delayed_start):
            self.runner.run()
        self.runner.deliver()
        self.assertEqual(len(invocations), 1)
        result = json.loads(Path(invocations[0]['result']).read_text())
        self.assertTrue(result['timeout'])
        self.assertEqual(result['timeout_cause'], 'deadline')
        self.assertEqual(result['elapsed'], 0)
        self.assertEqual(len(self.calls('tiers')), before)
        self.assertEqual(self.bisect_events()[0]['result'], 'range')
        self.assertFalse([post for post in self.calls('post') if post['args'][3] == 'ops@hel8'])


class ParserTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='after-landing-parser-')
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)

    def test_pinned_nextest_junit(self):
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
        app.atomic(fixture, '<testsuites tests="2"><testsuite name="x"><testcase name="a"/></testsuite></testsuites>')
        with self.assertRaises(app.Fault):
            app.junit(fixture, 'qa-skein')

    def test_exact_filter_unquoted_safe_identities(self):
        for binary, test in [
            ('temper-client-browser-world::qa_all',
             'qa_task_pages::typed_agent_address_survives_reload_and_a_lineage_round_trip'),
            ('package-123::qa_all_4', 'module_5::test-678'),
        ]:
            with self.subTest(binary=binary, test=test):
                self.assertEqual(app.exact_filter(binary, test),
                                 f'binary_id(={binary}) & test(={test})')

    def test_exact_filter_refuses_unsafe_identities(self):
        unsafe = ['', 'a)b', 'a(b', 'a,b', 'a&b', 'a|b', 'a b', 'a\tb',
                  'a\nb', 'a\u00a0b', 'a\\b', '/a', '#a', '~a', '=a', 'a"b']
        for identity in unsafe:
            for binary, test in [(identity, 'safe'), ('safe', identity)]:
                with self.subTest(binary=binary, test=test):
                    with self.assertRaisesRegex(app.Fault, 'identity not expressible as an exact filter'):
                        app.exact_filter(binary, test)

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
