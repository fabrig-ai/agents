#!/usr/bin/env python3
"""Shared isolated fixtures for the gate and periodic after-landing contracts."""

import atexit
import shutil
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
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


FAKE = r'''#!/usr/bin/env -S python3 -I -S -B
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


_GIT_TEMPLATE = None


def git_template(git):
    """Build the baseline once; each test owns independent copied repositories."""
    global _GIT_TEMPLATE
    if _GIT_TEMPLATE is None:
        temporary = tempfile.TemporaryDirectory(prefix='after-landing-template-')
        atexit.register(temporary.cleanup)
        root = Path(temporary.name)
        seed, origin, slot = (root / name for name in ('seed', 'origin.git', 'slot'))
        git(root, 'init', '-q', '--bare', origin)
        git(root, 'init', '-q', '-b', 'main', seed)
        (seed / '.config').mkdir()
        app.atomic(seed / '.config/nextest.toml',
                   '[profile.default]\nglobal-timeout="1s"\n[profile.qa-skein]\nglobal-timeout="1s"\n'
                   '[profile.qa-jig]\nglobal-timeout="1s"\n')
        (seed / 'tools/tiers').mkdir(parents=True)
        (seed / 'tools/queue').mkdir()
        (seed / 'tools/slots').mkdir()
        app.atomic(seed / 'tools/tiers/run', FAKE)
        app.atomic(seed / 'tools/slots/trim', FAKE)
        (seed / 'tools/tiers/run').chmod(0o755)
        app.atomic(seed / 'tools/queue/leads.txt', 'ops ops@hel8\nmc s/multi-coord@hel8\ncoord s/dynamic-memory@hel8\nq s/qa@hel8\nu s/upgrades@hel8\n')
        git(seed, 'add', '.')
        git(seed, 'commit', '-qm', 'baseline')
        base = git(seed, 'rev-parse', 'HEAD')
        git(seed, 'remote', 'add', 'origin', origin)
        git(seed, 'push', '-q', 'origin', 'main')
        git(root, 'clone', '-q', '-b', 'main', origin, slot)
        _GIT_TEMPLATE = root, base
    return _GIT_TEMPLATE


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
        self.make_repositories()
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

    def make_repositories(self):
        template, self.base = git_template(self.git)
        for name in ('seed', 'origin.git', 'slot'):
            shutil.copytree(template / name, self.home / name)
        for repository in (self.seed, self.slot):
            config = repository / '.git/config'
            app.atomic(config, config.read_text().replace(str(template), str(self.home)))


class BisectionSandbox(Sandbox):
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


class CoreSandbox(Sandbox):
    """Core decisions use private paths and in-process services, without Git."""
    def make_repositories(self):
        self.base = 'a' * 40
        leads = self.slot / 'tools/queue/leads.txt'
        leads.parent.mkdir(parents=True)
        app.atomic(leads, 'ops ops@hel8\nmc s/multi-coord@hel8\ncoord s/dynamic-memory@hel8\nq s/qa@hel8\nu s/upgrades@hel8\n')

    def setUp(self):
        super().setUp()
        def registry(argv, **kwargs):
            self.assertEqual(argv, [self.args.registry, 'names', '--json'])
            return SimpleNamespace(returncode=int(self.scenario.get('registry_fault', False)),
                                   stdout=json.dumps(self.scenario['registry']))
        patch = mock.patch.object(app, 'command', side_effect=registry)
        patch.start()
        self.addCleanup(patch.stop)


class CoreBisectionSandbox(CoreSandbox, BisectionSandbox):
    pass
