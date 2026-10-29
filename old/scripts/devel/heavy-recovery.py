#!/usr/bin/env python3
"""Durable admission and cgroup recovery for heavy; build-infrastructure.md."""
import contextlib
import ctypes
import errno
import fcntl
import functools
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time
import tomllib
import uuid

sys.dont_write_bytecode = True
from recovery_message import RECOVERY_DIAGNOSTIC
from receipt_inputs import capture as capture_inputs

os.umask(0o077)
KIT = Path(__file__).resolve().parent
ROOT = Path(os.environ.get('DEV_ROOT', str(Path.home() / 'src/rust'))).resolve()
TMP = Path(os.environ.get('DEV_TMP', str(ROOT / 'tmp'))).resolve()
BASE = TMP / 'heavy'
LOGS = TMP / 'logs'
BOOT_FILE = Path(os.environ.get('HEAVY_BOOT_ID_FILE', '/proc/sys/kernel/random/boot_id'))
# The state directory is the queue (build-infrastructure.md, 2).
QUEUE = hashlib.sha256(str(BASE).encode()).hexdigest()
PREFIX = 'skein-heavy-' + QUEUE[:12]
LANES = ('build', 'gate')
UNCLAIMED = ('submitted', 'enqueuing', 'queued')
LIVE = ('launching', 'active', 'finishing', 'closing')
ROOM_AFTER = 120  # Reservation after release (build-infrastructure.md 2).
DISK_WAIT_LIMIT = 20 * 60  # Time below a landing's floor (build-infrastructure.md 2).
SNAPSHOT_READ_S = 1.0  # Waiting clients read at most once a second (build-infrastructure.md 3).
FLOOR_REFUSAL = 'disk floor refused before payload start'
CGROOT = Path('/sys/fs/cgroup')
CANCELLED = 130  # A cancelled task's exit, as check.sh and codex-run exit on SIGINT.
USAGE = 'usage: heavy [--gate | --land] [--tail N] [--] command... | heavy --cancel TOKEN'
# Each task's CPU weight in its systemd unit (build-infrastructure.md, 2): a
# landing's work first, an agent's builds next, background work after, and
# idle work only on otherwise idle cores. HEAVY_CLASS names one.
WEIGHTS = {'land': '10000', 'build': '1000', 'background': '100', 'idle': 'idle'}


class Refusal(Exception):
    pass


def subreaper():
    # An orphan's getppid() must name this guard, never systemd --user
    # (build-infrastructure.md 3: the payload adopts its orphans).
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(36, 1, 0, 0, 0) != 0:  # PR_SET_CHILD_SUBREAPER
        raise Refusal('cannot become child subreaper: ' + os.strerror(ctypes.get_errno()))


def run(args, **kw):
    # A session of its own: a terminal's SIGINT reaches heavy, which defers
    # it, and never fails a queue or systemd call midway.
    return subprocess.run([str(x) for x in args], stdin=subprocess.DEVNULL,
                          capture_output=True, text=True, start_new_session=True, **kw)


def boot():
    if BOOT_FILE != Path('/proc/sys/kernel/random/boot_id') and (
            os.environ.get('HEAVY_RECOVERY_FIXTURE') != '1' or not BOOT_FILE.resolve().is_relative_to(TMP)):
        raise Refusal('boot identity override requires an isolated recovery fixture')
    return BOOT_FILE.read_text().strip()


@functools.cache
def setting(key, default) -> int:
    result = run(['bash', '-c', 'set -euo pipefail; root=$1; tmp=$2; '
                  'source "$3"; machine_setting "$4" "$5"',
                  'heavy-setting', ROOT, TMP, KIT / 'kit.sh', key, str(default)], check=True)
    return int(result.stdout.split()[0])


def free_gb() -> int:
    override = os.environ.get('HEAVY_DISK_FREE_FILE')
    if override is not None:
        path = Path(override).resolve()
        if os.environ.get('HEAVY_RECOVERY_FIXTURE') != '1' or not path.is_relative_to(TMP):
            raise Refusal('disk free override requires an isolated recovery fixture')
        return int(path.read_text())
    st = os.statvfs(ROOT)
    return math.ceil(st.f_bavail * st.f_frsize / 2**30)


def landing(task) -> bool:
    return re.fullmatch(r'land \S+( (prebuild|regenerate))?', task['label']) is not None


def floor_of(task):
    return task['floor_gb'] if 'floor_gb' in task else setting('PLAN_MIN_DISK_GB', 40)


def room_of(task):
    return task['room_gb'] if 'room_gb' in task else setting('PLAN_LAND_ROOM_GB', 30)


def reservation(tasks) -> int | None:
    now = time.time()
    return max((room_of(task) for task in tasks.values()
                if (task['state'] != 'released' or
                    ('label' in task and now - task['ended'] < ROOM_AFTER))
                and landing(task)), default=None)


def track_disk_wait(ledger, task, free) -> None:
    if not landing(task) or task['state'] not in ('queued', 'waiting'):
        return
    waiting = free < floor_of(task)
    if waiting == ('disk_wait' in task):
        return
    if waiting:
        task['disk_wait'] = time.time()
    else:
        task.pop('disk_wait')
    ledger.event(task, 'disk_wait:' + uuid.uuid4().hex, waiting=waiting, floor_gb=floor_of(task))
    ledger.save()


def identity(pid=None):
    pid = pid or os.getpid()
    try:
        # The command name may contain spaces and parentheses.
        stat = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
        if stat[0] == 'Z':
            return None
        ticks = stat[19]
        return {'pid': pid, 'ticks': ticks, 'boot': boot()}
    except FileNotFoundError:
        return None


def alive(owner):
    return owner is not None and identity(owner['pid']) == owner


def sync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic(path, value):
    storage_fault('snapshot' if path.name == 'state.json' else 'receipt')
    temporary = path.with_name(path.name + '.new')
    with temporary.open('w', encoding='utf-8') as out:
        os.fchmod(out.fileno(), 0o600)
        json.dump(value, out, separators=(',', ':'), sort_keys=True)
        out.write('\n')
        out.flush()
        os.fsync(out.fileno())
    if value.get('schema') == 'heavy-receipt-v1':
        fault('receipt_fsynced', value['token'])
    if path.name == 'state.json':
        gate = value.get('gate')
        if gate and any(event['event'] == 'drain_begin' for event in value.get('pending', [])):
            fault('intent_fsynced', gate)
        for task in value.get('tasks', {}).values():
            if task['state'] == 'released' and any(event['id'] == task['token'] + ':release_end'
                                                   for event in value.get('pending', [])):
                fault('release_fsynced', task['token'])
    os.replace(temporary, path)
    sync_dir(path.parent)


def complete_lines(path):
    """Discard an interrupted final append, while the host lock is held."""
    if not path.exists():
        return []
    data = path.read_bytes()
    end = data.rfind(b'\n') + 1
    if end != len(data):
        with path.open('r+b') as out:
            out.truncate(end)
            out.flush()
            os.fsync(out.fileno())
    return data[:end].decode().splitlines()


def durable_append(path, lines):
    if not lines:
        return
    storage_fault('journal')
    with path.open('a', encoding='utf-8') as out:
        os.fchmod(out.fileno(), 0o600)
        for line in lines:
            out.write(line + '\n')
        out.flush()
        os.fsync(out.fileno())
    sync_dir(path.parent)


def installed():
    # Atomic ledger snapshots need no host lock (build-infrastructure.md 12).
    try:
        snapshot = (BASE / 'state.json').read_text()
    except FileNotFoundError:
        return False
    except (OSError, UnicodeError):
        raise Refusal('cannot tell whether heavy is installed: cannot read host ledger') from None
    try:
        data = json.loads(snapshot)
    except ValueError:
        raise Refusal('cannot tell whether heavy is installed: cannot parse host ledger') from None
    if not isinstance(data, dict):
        raise Refusal('cannot tell whether heavy is installed: cannot parse host ledger')
    if data.get('version') != 1:
        raise Refusal('cannot tell whether heavy is installed: unsupported host ledger version')
    return data.get('installation') is not None


class Ledger:
    def __init__(self):
        self.path = BASE / 'state.json'
        if self.path.exists():
            self.data = json.loads(self.path.read_text())
            if self.data.get('version') != 1:
                raise Refusal('unsupported host ledger version')
        else:
            self.data = {'version': 1, 'queue': QUEUE, 'tasks': {}, 'maintenance': {},
                         'gate': None, 'pending': [], 'installation': None}
        if not older_tasks(self):
            self.seed_number()
        take_over(self)
        self.flush()

    def seed_number(self):
        if 'next_id' not in self.data:
            numbers = [int(task['id']) for task in self.tasks.values()
                       if str(task.get('id', '')).isdigit()]
            rows = LOGS / 'heavy.tsv'
            if rows.exists():
                numbers.extend(int(row.split('\t')[0]) for row in rows.read_text().splitlines()
                               if len(row.split('\t')) == 11 and row.split('\t')[0].isdigit())
            self.data['next_id'] = 1 + max(numbers, default=0)

    @property
    def tasks(self):
        return self.data['tasks']

    def event(self, task, key, **extra):
        token = task['token'] if task else 'host'
        now = time.time_ns()
        fields = {'id': token + ':' + key, 'event': key, 'time_ns': now, 'queue': QUEUE,
                  'boot': boot(), 'token': token,
                  'source': sys.argv[1] if len(sys.argv) > 1 and sys.argv[1].startswith('--') else 'submit',
                  'free_disk_bytes': shutil.disk_usage(ROOT).free,
                  'free_memory_bytes': available_memory()}
        if task:
            fields.update({key: task[key] for key in ('lane', 'label', 'repo', 'tree', 'policy')})
            fields['exclusive'] = task.get('exclusive', task['lane'] == 'gate')
        fields.update(extra)
        self.data['pending'].append(fields)

    def save(self):
        atomic(self.path, self.data)
        self.flush()

    def flush(self):
        # The snapshot's outbox precedes both journals. Event IDs and unique log
        # paths make replay after append/fsync/rename interruptions idempotent.
        pending_rows = [task for task in self.tasks.values() if 'row' in task and not task.get('row_durable')]
        if not self.data['pending'] and not pending_rows:
            return
        events = BASE / 'events.jsonl'
        seen = {json.loads(line)['id'] for line in complete_lines(events)}
        missing = []
        for event in self.data['pending']:
            if event['id'] not in seen:
                missing.append(json.dumps(event, separators=(',', ':'), sort_keys=True))
                seen.add(event['id'])
        durable_append(events, missing)
        if missing:
            fault('events_fsynced', self.data['pending'][-1]['token'])
        rows = complete_lines(LOGS / 'heavy.tsv')
        if pending_rows:
            logs = {line.split('\t')[8] for line in rows if len(line.split('\t')) == 11}
            durable_append(LOGS / 'heavy.tsv', [task['row'] for task in pending_rows if task['log'] not in logs])
            for task in pending_rows:
                task['row_durable'] = True
        self.data['pending'] = []
        atomic(self.path, self.data)


@contextlib.contextmanager
def locked():
    BASE.mkdir(parents=True, exist_ok=True, mode=0o700)
    LOGS.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (BASE / 'host.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield Ledger()


def take_over(ledger):
    if ledger.data['queue'] != QUEUE and all(task['state'] == 'released' for task in ledger.tasks.values()):
        previous = ledger.data['queue']
        ledger.seed_number()
        ledger.data['queue'] = QUEUE
        ledger.event(None, 'migration:' + uuid.uuid4().hex, previous=previous,
                     tasks=len(ledger.tasks), holds=sorted(ledger.data['maintenance']))
        ledger.save()


def older_tasks(ledger) -> list:
    return [task for task in ledger.tasks.values() if task['state'] != 'released' and task.get('queue') != QUEUE]


def available_memory():
    for line in Path('/proc/meminfo').read_text().splitlines():
        if line.startswith('MemAvailable:'):
            return int(line.split()[1]) * 1024
    return 0


def properties(unit):
    result = run(['systemctl', '--user', 'show', unit,
                  '--property=LoadState,ActiveState,ControlGroup,CPUUsageNSec,MemoryPeak'])
    values = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
    if not values:
        raise Refusal('cannot inspect owned systemd unit')
    return values


def own_cgroup(task):
    props = properties(task['unit'])
    group = props.get('ControlGroup', '')
    if group:
        if Path(group).name != task['unit'] or not group.startswith('/user.slice/'):
            raise Refusal('unexpected task cgroup')
        for field in ('CPUUsageNSec', 'MemoryPeak'):
            if props.get(field, '').isdigit() and int(props[field]) < 18446744073709551615:
                task.setdefault('resources', {})[field] = max(
                    int(props[field]), task.get('resources', {}).get(field, 0))
        return CGROOT / group.lstrip('/')
    if props.get('ActiveState') == 'active':
        raise Refusal('active owned unit has no cgroup evidence')
    return None


def populated(path):
    try:
        return 'populated 1' in (path / 'cgroup.events').read_text()
    except FileNotFoundError:
        if path.exists():
            raise Refusal('cgroup v2 population evidence is unavailable')
        return False


def scope_empty(task):
    path = own_cgroup(task)
    recorded = task.get('cgroup')
    if recorded and populated(CGROOT / recorded.lstrip('/')):
        return False
    return path is None or not populated(path)


def kill_scope(task):
    # Unit names are token-derived and never reused. Mark closing durably before
    # this call: a late-created service's guard cannot start a payload.
    own_cgroup(task)
    run(['systemctl', '--user', 'kill', '--kill-whom=all', '--signal=KILL', task['unit']])
    run(['systemctl', '--user', 'stop', '--no-block', task['unit']])
    return scope_empty(task)


def fault(point, token):
    # Fixture-only barriers live in the explicitly isolated DEV_TMP. A kill of
    # this process while blocked models loss at the production entrypoint.
    directory = os.environ.get('HEAVY_FAULT_DIR')
    if directory:
        path = Path(directory).resolve()
        if os.environ.get('HEAVY_RECOVERY_FIXTURE') != '1' or not path.is_relative_to(TMP):
            raise Refusal('fault barriers require an isolated recovery fixture')
        if (path / ('arm-' + point)).exists():
            (path / (token + '-' + point)).write_text(str(os.getpid()))
            while not (path / ('continue-' + point)).exists():
                time.sleep(0.02)


def storage_fault(point):
    directory = os.environ.get('HEAVY_FAULT_DIR')
    if not directory:
        return
    path = Path(directory).resolve()
    if os.environ.get('HEAVY_RECOVERY_FIXTURE') != '1' or not path.is_relative_to(TMP):
        raise Refusal('storage faults require an isolated recovery fixture')
    if (path / ('enospc-' + point)).exists():
        (path / ('hit-enospc-' + point)).touch()
        raise OSError(errno.ENOSPC, 'injected isolated storage write failure')


def waiter_failure():
    # Inspect reported failures, never infer one from task age or tick delays.
    for suffix in ('-reconcile.timer', '-reconcile.service'):
        result = run(['systemctl', '--user', 'show', PREFIX + suffix,
                      '--property=LoadState,ActiveState,Result,ExecMainStatus'])
        values = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
        if result.returncode or values.get('LoadState') != 'loaded':
            return True
        if suffix.endswith('.timer') and values.get('ActiveState') != 'active':
            return True
        if values.get('ActiveState') == 'failed' or values.get('Result', 'success') not in ('', 'success'):
            return True
    return False


def finish(ledger, task):
    now = time.time()
    task['state'] = 'released'
    task.setdefault('code', 137)
    if task.get('outcome') == 'recovered':
        task['code'] = 137
    if not task.get('payload_started') or not task.get('payload_ended'):
        task['code'] = task['code'] or 137
        if task.get('outcome') in (None, 'completed'):
            task['outcome'] = 'refused'
    task['release_complete'], task['cgroup_empty'] = True, True
    task['ended'] = now
    waited = int(task.get('payload_started', now) - task['submitted'])
    ran = int(now - task.get('payload_started', now))
    task['waited'], task['ran'] = waited, ran
    command = ' '.join(task['args'])
    clean = lambda value: str(value).replace('\t', ' ').replace('\r', ' ').replace('\n', ' ')
    task['row'] = '\t'.join(map(clean, [task.get('id', '-'), task['lane'],
        time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(now)), waited, ran, task['code'],
        f'{available_memory() / 1073741824:.1f}', task['repo'], task['log'], command, task['label']]))
    ledger.event(task, 'release_end', outcome=task.get('outcome', 'completed'), code=task['code'],
                 cgroup_empty=True, cgroup=task.get('cgroup'))
    ledger.event(task, 'task_completion', code=task['code'])
    ledger.save()
    fault('release_saved', task['token'])
    cleanup_transport(task)


def cleanup_transport(task):
    (BASE / (task['token'] + '.env')).unlink(missing_ok=True)
    sync_dir(BASE)


def publish_receipt(ledger, task):
    """Seal a separate log after release, then publish replayable evidence."""
    receipts = BASE / 'receipts'
    path = receipts / (task['token'] + '.json')
    if path.exists() or not task.get('row_durable') or not task.get('release_complete'):
        return
    receipts.mkdir(exist_ok=True, mode=0o700)
    sync_dir(BASE)
    log = Path(task['log'])
    if not task.get('log_complete'):
        # A delayed service can only open the capture file. It can never
        # append to this completed log, including after receipt publication.
        temporary = log.with_suffix('.new')
        storage_fault('seal')
        with temporary.open('wb') as out:
            os.fchmod(out.fileno(), 0o600)
            capture = Path(task['capture'])
            if capture.exists():
                with capture.open('rb') as source:
                    shutil.copyfileobj(source, out)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, log)
        sync_dir(log.parent)
        task['log_complete'] = True
        ledger.save()
    with log.open('rb') as source:
        digest = hashlib.file_digest(source, 'sha256').hexdigest()
    receipt = {'schema': 'heavy-receipt-v1', 'token': task['token'], 'id': task.get('id', ''),
               'queue': task['queue'], 'lane': task['lane'], 'tree': task['tree'],
               'policy': task['policy'], 'args': task['args'], 'outcome': task.get('outcome', 'refused'),
               'code': task['code'], 'payload_started': bool(task.get('payload_started')),
               'payload_ended': bool(task.get('payload_ended')), 'release_complete': True,
               'cgroup_empty': True, 'elapsed_s': max(0.0, task.get('payload_ended', 0) - task.get('payload_started', 0)) if task.get('payload_ended') else 0.0,
               'log': task['log'], 'log_sha256': digest}
    receipt.update({key: task[key] for key in ('head', 'inputs') if key in task})
    fault('receipt_ready', task['token'])
    atomic(path, receipt)
    fault('receipt_published', task['token'])


def request_cancel(ledger, task, reason, **extra):
    """Mark an unfinished task closing, cancelled, under the host lock.

    Release then takes the common path: the reconciler kills the owned scope,
    proves it empty, drops a gate's hold and publishes the receipt. A payload
    that has ended keeps its result: finishing, closing and released tasks
    are left alone. No queue ID is used: a queued entry that starts later
    finds its token released and refuses replay.
    """
    if task['state'] in ('finishing', 'closing', 'released'):
        return False
    task.update(state='closing', outcome='cancelled', code=CANCELLED)
    ledger.event(task, 'release_begin', outcome='cancelled')
    ledger.event(task, 'cancel', reason=reason, **extra)
    ledger.save()
    return True


def defer_interrupts():
    """SIGINT and SIGTERM only mark the returned list; callers act on it
    between host-lock sections, so no ledger write is cut short."""
    received = []
    for number in (signal.SIGINT, signal.SIGTERM):
        signal.signal(number, lambda signum, frame: received.append(signum))
    return received


def say(text, stream=None):
    # A reader that has gone (a pipe closed by its own interrupt) cannot
    # stop a cancellation or its release.
    try:
        print(text, file=stream or sys.stdout, flush=True)
    except OSError:
        pass


def completed_task(token):
    receipt = json.loads((BASE / 'receipts' / (token + '.json')).read_text())
    for line in (BASE / 'events.jsonl').read_text().splitlines(keepends=True):
        if not line.endswith('\n'):
            continue
        event = json.loads(line)
        if event['token'] == token and event['event'] == 'refusal':
            reason = event['reason']
            receipt['refusal'] = 'disk floor refused' if reason == 'disk-floor' else reason
    for line in (LOGS / 'heavy.tsv').read_text().splitlines():
        row = line.split('\t')
        if len(row) == 11 and row[8] == receipt['log']:
            return dict(receipt, state='released', row_durable=True, repo=row[7],
                        waited=int(row[3]), ran=int(row[4]))
    raise Refusal('released task has no durable history row')


def cancel(token):
    received = defer_interrupts()
    if os.environ.get('HEAVY_TASK'):
        raise Refusal('cancel refused: inside a heavy task')
    if not re.fullmatch(r'[0-9a-f]{32}', token):
        raise Refusal('cancel refused: malformed token')
    with locked() as ledger:
        task = ledger.tasks.get(token)
        if task is None:
            raise Refusal('cancel refused: unknown token')
        if task['state'] == 'released' and 'repo' not in task:
            task = completed_task(token)
        # Only the submitting working directory may take a task back.
        if Path(task['repo']).resolve() != Path.cwd().resolve():
            raise Refusal('cancel refused: the task was submitted from another directory')
        cancelled = request_cancel(ledger, task, 'request')
        reconcile(ledger)
    receipt = BASE / 'receipts' / (token + '.json')
    deadline = time.monotonic() + 60
    while True:
        with locked() as ledger:
            task = ledger.tasks.get(token)
            if task is None or (task['state'] == 'released' and 'lane' not in task):
                task = completed_task(token)
            if task['state'] != 'released' or not receipt.is_file():
                reconcile(ledger)
        name = f"task {task.get('id', '-')} ({task['lane']})"
        if task['state'] == 'released' and receipt.is_file():
            break
        if received or time.monotonic() >= deadline:
            say(f'heavy: {"cancelled" if cancelled else "not cancelled, already ended:"} {name} '
                f'token {token}; the reconciler completes its release', sys.stderr)
            return CANCELLED if received else 0 if cancelled else 1
        time.sleep(0.2)
    if cancelled:
        say(f"heavy: cancelled {name} token {token}, exit {task['code']}")
        return 0
    say(f"heavy: not cancelled, already ended: {name} token {token}, exit {task['code']}")
    return 1


def wrapper_unit(token) -> str:
    return PREFIX + '-' + token + '-wrapper.service'


def start_wrapper(task) -> bool:
    try:
        result = run(['systemd-run', '--user', '--quiet', '--collect',
                      '--unit=' + task['wrapper_unit'], '--service-type=exec',
                      '--property=EnvironmentFile=' + str(BASE / (task['token'] + '.env')),
                      '--property=UMask=0077', '--property=StandardInput=null',
                      '--property=StandardOutput=null', '--property=StandardError=journal',
                      '--working-directory=' + task['repo'],
                      KIT / 'heavy', '--task', task['token']])
        return result.returncode == 0
    except OSError:
        return False


def wrapper_running(task) -> bool:
    return bool(task.get('wrapper_unit')) and properties(task['wrapper_unit']).get('ActiveState') in (
        'active', 'activating', 'deactivating', 'reloading')


def room(ledger, task):
    lane, token = task['lane'], task['token']
    if lane in ledger.data['maintenance']:
        return 0
    if lane == 'build':
        if ledger.data['gate']:
            return 0
        slots = int(os.environ.get('HEAVY_BUILD_SLOTS_EFFECTIVE', '0'))
        return max(0, slots - sum(other['state'] in LIVE and other['lane'] == 'build'
                                 for other in ledger.tasks.values())) if slots else math.inf
    return int(ledger.data['gate'] in (None, token) and not any(
        other['state'] in LIVE and other['token'] != token and other['lane'] == 'gate'
        for other in ledger.tasks.values()))


def admissible(ledger, task) -> bool:
    is_landing = landing(task)
    older = sum(other['state'] in ('queued', 'waiting') and other['lane'] == task['lane']
                and int(other['id']) < int(task['id']) and (not is_landing or landing(other))
                for other in ledger.tasks.values())
    if older >= room(ledger, task):
        return False
    if is_landing:
        return free_gb() >= floor_of(task)
    if task['lane'] == 'build' and (reserved := reservation(ledger.tasks)) is not None:
        free = free_gb()
        # Even unlimited slots keep younger builds behind one waiting for room.
        floors = [floor_of(other) for other in ledger.tasks.values()
                  if other['state'] in ('queued', 'waiting') and other['lane'] == 'build'
                  and int(other['id']) < int(task['id']) and not landing(other)]
        return free >= max([floor_of(task), *floors]) + reserved
    return True


def reconcile(ledger):
    free = None
    for task in ledger.tasks.values():
        if task['state'] in UNCLAIMED and not wrapper_running(task):
            task.update(state='closing', outcome='cancelled', code=137)
            ledger.event(task, 'release_begin', outcome='cancelled')
            ledger.event(task, 'unclaimed', reason='no running wrapper unit before its claim')
            ledger.save()
        orphan = task['state'] not in (*UNCLAIMED, 'released') and (
            task['boot'] != boot() or not alive(task.get('wrapper')))
        if task['state'] in ('queued', 'waiting') and landing(task) and not orphan:
            if free is None:
                free = free_gb()
            track_disk_wait(ledger, task, free)
            if 'disk_wait' in task and time.time() - task['disk_wait'] >= DISK_WAIT_LIMIT:
                task.update(state='closing', outcome='refused', code=2, refusal=FLOOR_REFUSAL)
                ledger.event(task, 'release_begin', outcome='refused')
                ledger.event(task, 'refusal', reason='disk-floor')
                ledger.save()
        if task['state'] == 'released':
            cleanup_transport(task)
            publish_receipt(ledger, task)
        if task['state'] in (*UNCLAIMED, 'released'):
            continue
        if task['state'] != 'closing' and (orphan or task['state'] == 'finishing'):
            task['state'] = 'closing'
            task['outcome'] = 'recovered' if orphan else 'completed'
            ledger.event(task, 'release_begin', outcome=task['outcome'])
            if orphan:
                ledger.event(task, 'recovery', reason='wrapper identity ended or boot changed')
            ledger.save()
        if task['state'] != 'closing':
            continue
        if not kill_scope(task):
            continue
        fault('release_empty', task['token'])
        if ledger.data['gate'] == task['token']:
            ledger.data['gate'] = None
        finish(ledger, task)
        publish_receipt(ledger, task)
    take_over(ledger)


def probe_containment():
    # Real kernel probe: a session change must remain in the same task cgroup.
    probe = PREFIX + '-probe-' + uuid.uuid4().hex
    result = run(['systemd-run', '--user', '--quiet', '--wait', '--pipe', '--collect',
                  '--unit=' + probe, '--property=ExitType=cgroup', '--property=KillMode=control-group',
                  '--property=Delegate=no', '/bin/sh', '-c',
                  'group=$(cut -d: -f3 /proc/self/cgroup); '
                  'grep -qx "populated 1" "/sys/fs/cgroup$group/cgroup.events" || exit 1; '
                  'cat /proc/self/cgroup; setsid sh -c "cat /proc/self/cgroup"'])
    groups = result.stdout.strip().splitlines()
    if result.returncode or len(groups) != 2 or groups[0] != groups[1] or probe not in groups[0]:
        raise Refusal('systemd cgroup containment with setsid is unsupported')
    return groups


def refresh_probe(ledger):
    installed = ledger.data['installation']
    if installed and installed['boot'] != boot():
        groups = probe_containment()
        installed.update(boot=boot(), probe=groups)
        ledger.event(None, 'containment_probe:' + uuid.uuid4().hex, cgroups=groups, reason='boot changed')
        ledger.save()


def ensure_reconciler(ledger):
    installed = ledger.data['installation']
    if not installed:
        raise Refusal('containment/reconciler not installed; run heavy --install-reconciler')
    refresh_probe(ledger)
    if run(['systemctl', '--user', 'is-active', '--quiet', PREFIX + '-reconcile.timer']).returncode:
        raise Refusal('independent reconciler timer is not active')


def safe_environment():
    banned = re.compile(r'^CLAUDE_CODE_|TOKEN|SECRET|PASSWORD|PASSWD|API_KEY|CREDENTIAL', re.I)
    return {key: value for key, value in os.environ.items() if not banned.search(key)}


def selects_kache():
    # Resolve the two independent Cargo wrapper slots in increasing config
    # precedence, then apply [env] and dedicated/generic environment overrides.
    names = ('PATH', 'RUSTC_WRAPPER', 'RUSTC_WORKSPACE_WRAPPER', 'CARGO_BUILD_RUSTC_WRAPPER',
             'CARGO_BUILD_RUSTC_WORKSPACE_WRAPPER')
    cargo_home = Path(os.environ.get('CARGO_HOME', str(Path.home() / '.cargo'))).resolve()
    directories = [cargo_home, *(parent / '.cargo' for parent in reversed((Path.cwd(), *Path.cwd().parents)))]
    build, settings, origins, seen = {}, {}, {}, set()
    for directory in directories:
        path = directory / 'config'
        if not path.is_file():
            path = directory / 'config.toml'
        if not path.is_file() or path.resolve() in seen:
            continue
        seen.add(path.resolve())
        try:
            with path.open('rb') as source:
                config = tomllib.load(source)
        except (OSError, ValueError):
            raise Refusal('cannot resolve Cargo wrapper configuration') from None
        if not isinstance(config.get('build', {}), dict) or not isinstance(config.get('env', {}), dict):
            raise Refusal('cannot resolve Cargo wrapper configuration')
        if 'include' in config:
            raise Refusal('Cargo configuration includes are outside the declared policy')
        for field in ('rustc-wrapper', 'rustc-workspace-wrapper'):
            if field in config.get('build', {}):
                build[field] = config['build'][field]
                origins[field] = directory.parent
        for name in names:
            if name in config.get('env', {}):
                value = config['env'][name]
                if isinstance(value, dict) and isinstance(settings.get(name), dict):
                    settings[name].update(value)
                else:
                    settings[name] = value
                origins[name] = directory.parent
    environment = dict(os.environ)
    for name, value in settings.items():
        value = {'value': value} if isinstance(value, str) else value
        if not isinstance(value, dict) or not isinstance(value.get('value'), str):
            raise Refusal('cannot resolve Cargo wrapper configuration')
        if name not in environment or value.get('force', False):
            setting = value['value']
            if value.get('relative', False):
                setting = str((origins[name] / setting).resolve())
            environment[name] = setting
    for field, dedicated in (('rustc-wrapper', 'RUSTC_WRAPPER'),
                             ('rustc-workspace-wrapper', 'RUSTC_WORKSPACE_WRAPPER')):
        generic = 'CARGO_BUILD_' + field.upper().replace('-', '_')
        value = environment.get(dedicated, environment.get(generic, build.get(field, '')))
        if not isinstance(value, str):
            raise Refusal('cannot resolve Cargo wrapper configuration')
        if not value:
            continue
        base = Path.cwd() if dedicated in environment or generic in environment else origins[field]
        command = str(base / value) if '/' in value and not Path(value).is_absolute() else value
        resolved = shutil.which(command, path=environment.get('PATH'))
        if Path(value).name == 'kache' or (resolved and Path(resolved).resolve().name == 'kache'):
            return True
    return False


def environment_file(path, env):
    # systemd EnvironmentFile syntax: double quotes, escaped slash/quote/dollar/
    # backtick; literal newlines are supported inside the quoted value.
    with path.open('w') as out:
        for key, value in env.items():
            if not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*', key):
                continue
            value = value.replace('\\', '\\\\').replace('"', '\\"').replace('$', '\\$').replace('`', '\\`')
            out.write(key + '="' + value + '"\n')
        out.flush()
        os.fsync(out.fileno())
    sync_dir(path.parent)


def install(interval):
    if not re.fullmatch(r'[0-9]+(?:\.[0-9]+)?s?', interval) or float(interval.rstrip('s')) <= 0:
        raise Refusal('invalid reconciler interval')
    groups = probe_containment()
    with locked() as ledger:
        env = {key: os.environ[key] for key in ('PATH', 'DEV_ROOT', 'DEV_TMP', 'HEAVY_BOOT_ID_FILE', 'HEAVY_RECOVERY_FIXTURE', 'XDG_RUNTIME_DIR', 'DBUS_SESSION_BUS_ADDRESS') if key in os.environ}
        env['DEV_ROOT'], env['DEV_TMP'] = str(ROOT), str(TMP)
        if os.environ.get('HEAVY_RECOVERY_FIXTURE') == '1':
            for key in ('HEAVY_FAULT_DIR', 'HEAVY_DISK_FREE_FILE'):
                if key in os.environ:
                    env[key] = os.environ[key]
        environment_file(BASE / 'reconcile.env', env)
        units = Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home() / '.config'))) / 'systemd/user'
        if any(char in str(path) for path in (BASE, units, KIT) for char in '\r\n'):
            raise Refusal('systemd integration paths must be single-line paths')
        # Record first: a partial install must refuse, never run plain
        # (build-infrastructure.md 4 and 12). Reinstallation rewrites the units.
        ledger.data['installation'] = {'boot': boot(), 'interval': interval, 'probe': groups,
                                        'units': str(units)}
        ledger.save()
        units.mkdir(parents=True, exist_ok=True)
        # Quote systemd specifiers and ExecStart words independently of a shell.
        quote = lambda value: '"' + str(value).replace('%', '%%').replace('\\', '\\\\').replace('"', '\\"') + '"'
        service = PREFIX + '-reconcile.service'
        timer = PREFIX + '-reconcile.timer'
        (units / service).write_text('[Unit]\nDescription=heavy owned cgroup recovery\nStartLimitIntervalSec=0\n'
            '[Service]\nType=oneshot\nUMask=0077\nEnvironmentFile=' + str(BASE / 'reconcile.env').replace('%', '%%') + '\n'
            'ExecStart=' + quote(sys.executable) + ' ' + quote(Path(__file__).resolve()) + ' --reconcile\n')
        (units / timer).write_text('[Unit]\nDescription=heavy recovery polling\n[Timer]\n'
            'OnBootSec=' + interval + '\nOnUnitInactiveSec=' + interval + '\nAccuracySec=100ms\n'
            'Unit=' + service + '\n[Install]\nWantedBy=timers.target\n')
        run(['systemctl', '--user', 'daemon-reload'], check=True)
        run(['systemctl', '--user', 'enable', '--now', timer], check=True)
        ledger.event(None, 'containment_probe:' + uuid.uuid4().hex, cgroups=groups, interval=interval)
        ledger.save()
    print('heavy: independent reconciler ' + timer + '; interval ' + interval)


def maintenance(lane, pause):
    with locked() as ledger:
        if lane not in LANES and (pause or lane not in ledger.data['maintenance']):
            raise Refusal('maintenance requires a lane: build or gate')
        if pause:
            ledger.data['maintenance'][lane] = True
        else:
            ledger.data['maintenance'].pop(lane, None)
        ledger.event(None, 'maintenance:' + uuid.uuid4().hex, group=lane, held=pause)
        ledger.save()
        reconcile(ledger)


def gate_candidate():
    head = run(['git', 'rev-parse', 'HEAD'])
    tree = run(['git', 'rev-parse', 'HEAD^{tree}'])
    status = run(['git', 'status', '--porcelain', '--untracked-files=normal', '--ignore-submodules=none'])
    states = [run(['git', 'rev-parse', '--git-path', name])
              for name in ('rebase-merge', 'rebase-apply', 'MERGE_HEAD')]
    if head.returncode or tree.returncode or status.returncode or status.stdout.strip() or any(
            state.returncode or Path(state.stdout.strip()).exists() for state in states):
        raise Refusal('gate candidate HEAD/index/worktree or rebase state is not clean; rerun land')
    if run(['git', 'rev-parse', 'HEAD']).stdout.strip() != head.stdout.strip():
        raise Refusal('gate candidate commit changed during validation; rerun land')
    return head.stdout.strip(), tree.stdout.strip()


def check_gate_candidate(ledger, task):
    if task['lane'] != 'gate' or task['tree'] == 'unversioned':
        return True
    try:
        commit, tree = gate_candidate()
        valid = commit == task['commit'] and tree == task['tree']
    except Refusal:
        valid = False
    if not valid:
        task.update(state='finishing', code=2, outcome='refused',
                    refusal='gate candidate HEAD/index/worktree or rebase changed; rerun land')
        ledger.event(task, 'refusal', reason=task['refusal'])
        ledger.save()
    return valid


def weight(lane):
    chosen = os.environ.get('HEAVY_CLASS', '')
    if chosen in WEIGHTS:
        return WEIGHTS[chosen]
    # Labels never raise a weight: a landing's prebuild beside a gate is
    # still a build (decision 1210).
    if lane == 'gate':
        return WEIGHTS['land']
    return WEIGHTS['build']


def submit(args, lane, tail_lines, exclusive):
    if os.environ.get('HEAVY_TASK'):
        raise Refusal('already inside a heavy task; run the command directly')
    # An interrupt of the waiting client cancels its task (request_cancel).
    received = defer_interrupts()
    commit = run(['git', 'rev-parse', 'HEAD']).stdout.strip() or 'unversioned'
    tree = run(['git', 'rev-parse', 'HEAD^{tree}']).stdout.strip() or 'unversioned'
    if lane == 'gate' and run(['git', 'rev-parse', '--is-inside-work-tree']).returncode == 0:
        commit, tree = gate_candidate()
    if received:
        say('heavy: interrupted; nothing was queued', sys.stderr)
        return CANCELLED
    token = uuid.uuid4().hex
    with locked() as ledger:
        ensure_reconciler(ledger)
        reconcile(ledger)
        if older := older_tasks(ledger):
            n = len(older)
            raise Refusal(f'drain first: {n} task{"" if n == 1 else "s"} from the pueue generation')
        jobs = os.environ.get('HEAVY_BUILD_JOBS_EFFECTIVE', str(len(os.sched_getaffinity(0))))
        label = os.environ.get('HEAVY_LABEL', Path.cwd().name)
        number = ledger.data['next_id']
        ledger.data['next_id'] = number + 1
        task = {'token': token, 'id': str(number), 'wrapper_unit': wrapper_unit(token), 'lane': lane,
                'exclusive': exclusive, 'weight': weight(lane),
                'args': args, 'label': label,
                'floor_gb': setting('PLAN_MIN_DISK_GB', 40),
                'room_gb': setting('PLAN_LAND_ROOM_GB', 30),
                'repo': str(Path.cwd()), 'tree': tree, 'commit': commit, 'policy': os.environ.get('SKEIN_GATE_POLICY_ID', 'gate-policy-unavailable') if lane == 'gate' else 'build-' + jobs,
                'boot': boot(), 'queue': QUEUE, 'unit': PREFIX + '-' + token + '.service',
                'submitted': time.time(), 'state': 'queued', 'log': str(LOGS / (token + '.log')),
                'capture': str(LOGS / (token + '.capture'))}
        ledger.tasks[token] = task
        Path(task['capture']).touch(mode=0o600)
        ledger.event(task, 'submit')
        ledger.save()
        env = safe_environment()
        env['HEAVY_TASK'] = '1'
        env['NEXTEST_DOUBLE_SPAWN'] = os.environ.get('NEXTEST_DOUBLE_SPAWN', '0')
        env.pop('NEXTEST_TEST_THREADS', None)
        env['CARGO_BUILD_JOBS'] = jobs
        env['HEAVY_LANE'] = lane
        environment_file(BASE / (token + '.env'), env)
        fault('wrapper_intent', token)
        if not start_wrapper(task):
            task.update(state='closing', outcome='refused', code=2)
            ledger.event(task, 'refusal', reason='cannot start the task wrapper unit')
            ledger.save()
            reconcile(ledger)
            raise Refusal('cannot start the task wrapper unit')
    say(f"heavy: queued task {task['id']} in the {lane} lane token {token}", sys.stderr)
    warned, next_health, handled = False, 0.0, 0
    disk_spell, room_spell = None, False
    while True:
        if received and not handled:
            # The cancel is durable before anything is printed.
            with locked() as ledger:
                current = ledger.tasks.get(token)
                cancelled = current is not None and request_cancel(ledger, current, 'interrupt', signal=received[0])
                reconcile(ledger)
            handled = len(received)
            say(f"heavy: interrupted; {'cancelled' if cancelled else 'not cancelled, already ended:'} "
                f"task {task['id']} ({lane}) token {token}", sys.stderr)
        elif handled and len(received) > handled:
            say(f"heavy: interrupted again; leaving task {task['id']} token {token} "
                'to the reconciler', sys.stderr)
            return CANCELLED
        check_health = time.monotonic() >= next_health
        if check_health:
            failed = waiter_failure()
            if failed and not warned:
                print(RECOVERY_DIAGNOSTIC, file=sys.stderr, flush=True)
            warned = failed
            next_health = time.monotonic() + 1
        # Atomic snapshots let clients observe completion without contending
        # with admission. The row marker follows the durable event/TSV flush.
        try:
            snapshot = json.loads((BASE / 'state.json').read_text())
            task = snapshot['tasks'].get(token)
            if task is None or (task['state'] == 'released' and 'log' not in task):
                task = completed_task(token)
        except (OSError, ValueError):
            print(RECOVERY_DIAGNOSTIC, file=sys.stderr, flush=True)
            return 2
        if check_health:
            spell = task.get('disk_wait') if task['state'] in ('queued', 'waiting') else None
            free = None
            if spell is not None and spell != disk_spell:
                free = free_gb()
                say(f"heavy: task {task['id']} waits for the disk floor: {free} GB free, below its floor "
                    f"of {floor_of(task)} GB; refused after 20 minutes below it", sys.stderr)
            disk_spell = spell
            held = False
            if task['state'] in ('queued', 'waiting') and lane == 'build' and not landing(task):
                reserved = reservation(snapshot['tasks'])
                if reserved is not None:
                    free = free_gb() if free is None else free
                    held = free < floor_of(task) + reserved
                    if held and not room_spell:
                        say(f"heavy: task {task['id']} waits for a landing's room: {free} GB free, "
                            f"starting at {floor_of(task) + reserved} GB", sys.stderr)
            room_spell = held
        if task['state'] == 'released' and (BASE / 'receipts' / (token + '.json')).is_file():
            break
        time.sleep(SNAPSHOT_READ_S)
    if task.get('refusal') == FLOOR_REFUSAL and not task.get('payload_started'):
        fault('client_refusal', token)
        result = run(['bash', '-c', 'set -euo pipefail; root=$1; tmp=$2; '
                      'source "$3"; disk_floor heavy "$4"',
                      'heavy-disk-floor', ROOT, TMP, KIT / 'kit.sh', str(floor_of(task))])
        if result.stderr:
            say(result.stderr.rstrip(), sys.stderr)
        else:
            say(f"heavy: task {task['id']} stayed below its floor of {floor_of(task)} GB for 20 minutes; "
                f"{free_gb()} GB free now", sys.stderr)
    if task.get('refusal'):
        print('heavy: ' + task['refusal'], file=sys.stderr, flush=True)
    if task.get('outcome') == 'cancelled' and not handled:
        print(f"heavy: cancelled task {task['id']} ({lane}) token {token}", file=sys.stderr, flush=True)
    lines = Path(task['log']).read_text(errors='replace').splitlines()
    if len(lines) > tail_lines:
        print(f"heavy: … {len(lines) - tail_lines} earlier lines in {task['log']}")
    if tail_lines:
        print('\n'.join(lines[-tail_lines:]))
    print(f"heavy: task {task['id']} ({lane}) exit {task['code']}, waited {task['waited']}s, "
          f"ran {task['ran']}s, log {task['log']}")
    print(f"heavy: receipt {BASE / 'receipts' / (token + '.json')} token {token}")
    return task['code']


def wrapper(token):
    room_warned = False
    fault('claim', token)
    with locked() as ledger:
        reconcile(ledger)
        task = ledger.tasks.get(token)
        if task is None or not task.get('wrapper_unit') or task['state'] != 'queued':
            raise Refusal('token is not queued; refusing replay')
        task['wrapper'] = identity()
        task['boot'] = boot()
        task['state'] = 'waiting'
        ledger.event(task, 'wrapper_start')
        ledger.save()
    while True:
        with locked() as ledger:
            reconcile(ledger)
            task = ledger.tasks.get(token) or completed_task(token)
            if task['state'] == 'released':
                return task['code']
            # A cancelled task still closing must never be admitted.
            if task['state'] != 'waiting':
                time.sleep(SNAPSHOT_READ_S)
                continue
            if landing(task):
                track_disk_wait(ledger, task, free_gb())
            elif task['lane'] == 'build' and not room_warned:
                reserved = reservation(ledger.tasks)
                if reserved is not None and free_gb() < floor_of(task) + reserved:
                    ledger.event(task, 'room_wait', floor_gb=floor_of(task), room_gb=reserved)
                    ledger.save()
                    room_warned = True
            ready = admissible(ledger, task)
            # An exclusive gate records its hold before draining live scopes.
            if ready and task['lane'] == 'gate' and task.get('exclusive', True):
                if ledger.data['gate'] is None:
                    ledger.data['gate'] = token
                    ledger.event(task, 'drain_begin')
                    ledger.save()
                    fault('intent', token)
                ready = not any(other['token'] != token and other['state'] in LIVE
                                for other in ledger.tasks.values())
                if ready:
                    ledger.event(task, 'drain_end')
            if ready:
                # Lazy-starting kache here would place the shared daemon inside
                # this task. Its separate user service must already own it.
                if selects_kache() and run(
                        ['systemctl', '--user', 'is-active', '--quiet', 'kache.service']).returncode:
                    task['state'], task['code'] = 'finishing', 2
                    task['refusal'] = 'selected Cargo wrapper requires the shared kache.service; start that service or deliberately disable the selected wrapper'
                    ledger.event(task, 'refusal', reason=task['refusal'])
                    ledger.save()
                    continue
                task['state'] = 'launching'
                ledger.event(task, 'admit', build_slots=int(os.environ.get('HEAVY_BUILD_SLOTS_EFFECTIVE', '0')),
                             jobs=os.environ.get('CARGO_BUILD_JOBS'), weight=task.get('weight', WEIGHTS['build']))
                ledger.save()
                # The in-cgroup guard takes the same lock and checks the durable
                # token. A delayed StartTransientUnit after orphan recovery can
                # create no payload, even if this wrapper dies during launch.
                launcher = subprocess.Popen(['systemd-run', '--user', '--quiet', '--wait', '--collect',
                    '--unit=' + task['unit'], '--service-type=exec', '--property=ExitType=cgroup',
                    '--property=KillMode=control-group', '--property=Delegate=no',
                    '--property=CPUAccounting=yes', '--property=MemoryAccounting=yes',
                    '--property=CPUWeight=' + task.get('weight', WEIGHTS['build']),
                    # Out of memory, the kernel kills an agent's build, which
                    # reruns, before a landing's work.
                    '--property=OOMScoreAdjust=' + ('0' if task.get('weight') == WEIGHTS['land'] else '500'),
                    '--property=EnvironmentFile=' + str(BASE / (token + '.env')),
                    '--property=StandardOutput=append:' + task['capture'], '--property=StandardError=inherit',
                    '--working-directory=' + task['repo'], str(KIT / 'heavy'), '--payload', token],
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                break
        time.sleep(SNAPSHOT_READ_S)
    while True:
        try:
            launcher.wait(timeout=SNAPSHOT_READ_S)
            ended = True
        except subprocess.TimeoutExpired:
            ended = False
        current = json.loads((BASE / 'state.json').read_text())['tasks'].get(token) or completed_task(token)
        if current['state'] == 'released' and current.get('row_durable'):
            launcher.wait()
            return current['code']
        if current['state'] not in ('finishing', 'closing') and not ended:
            continue
        with locked() as ledger:
            task = ledger.tasks.get(token) or completed_task(token)
            if ended and task['state'] in ('launching', 'active'):
                task['state'], task['code'] = 'finishing', 2 if task['state'] == 'launching' else 137
                ledger.event(task, 'refusal', reason='contained service failed before payload entry')
                ledger.save()
            reconcile(ledger)
            if task['state'] == 'released':
                return task['code']
        time.sleep(SNAPSHOT_READ_S)


def phase(token, name, **values):
    with locked() as ledger:
        task = ledger.tasks[token]
        if name == 'payload_end':
            task['payload_ended'] = time.time()
        ledger.event(task, name, **values)
        ledger.save()


def gc(token, serial):
    deadline = time.monotonic() + 60
    phase(token, 'gc_begin:' + str(serial))
    # Only connect to an existing shared service; never create a lazy daemon.
    outcome, reason = 'skipped', 'client-missing'
    try:
        if shutil.which('kache'):
            for reason, args in (
                    ('readiness', ['systemctl', '--user', 'is-active', '--quiet', 'kache.service']),
                    ('rpc', ['kache', 'gc'])):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(args, 0)
                result = subprocess.run(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL, timeout=remaining)
                if result.returncode:
                    outcome = 'unavailable' if reason == 'readiness' else 'error'
                    break
            else:
                outcome = 'completed'
    except subprocess.TimeoutExpired:
        # run() kills and reaps only its own client; no captured pipe can linger.
        outcome = 'timeout'
    except OSError:
        outcome = 'error'
    phase(token, 'gc_end:' + str(serial), outcome=outcome, reason=reason)


def prepare_payload_policy(token):
    # Called only after the durable ownership guard marks this cgroup active.
    # All runtime version launchers and their descendants belong to its scope.
    names = ('SKEIN_GATE_POLICY_ID', 'SKEIN_TEST_CHROMIUM', 'SKEIN_TEST_FONTS', 'SKEIN_GATE_POLICY_HELPER')
    result = run(['bash', '-c', 'source "$1"; gate_policy_prepare || exit 2; '
                  'printf "%s\\0" "$SKEIN_GATE_POLICY_ID" "$SKEIN_TEST_CHROMIUM" '
                  '"$SKEIN_TEST_FONTS" "$SKEIN_GATE_POLICY_HELPER"',
                  'heavy-policy', KIT / 'gate-policy.sh'])
    values = result.stdout.split('\0')
    with locked() as ledger:
        task = ledger.tasks[token]
        if task['state'] != 'active':
            return False
        expected = os.environ.get('SKEIN_GATE_POLICY_ID')
        if result.returncode or len(values) != 5 or values[0] != task['policy'] or (
                expected and values[0] != expected):
            task.update(state='finishing', code=2, outcome='refused',
                        refusal='submitted gate policy no longer validates at contained entry')
            ledger.event(task, 'refusal', reason=task['refusal'])
            ledger.save()
            return False
        os.environ.update(zip(names, values[:4]))
    return True


def payload_disk_floor(token):
    # Submission may have waited for room in its lane. Check again inside
    # the owned cgroup, outside the host lock, just before command start.
    with locked() as ledger:
        floor = floor_of(ledger.tasks[token])
    result = run(['bash', '-c', 'set -euo pipefail; root=$1; tmp=$2; '
                  'source "$3"; disk_floor heavy "$4"',
                  'heavy-disk-floor', ROOT, TMP, KIT / 'kit.sh', str(floor)])
    if not result.returncode:
        return True
    print(result.stderr, end='', flush=True)
    with locked() as ledger:
        task = ledger.tasks[token]
        if task['state'] == 'active':
            task.update(state='finishing', code=2, outcome='refused',
                        refusal=FLOOR_REFUSAL)
            ledger.event(task, 'refusal', reason='disk-floor')
            ledger.save()
    return False


def payload(token):
    with locked() as ledger:
        task = ledger.tasks.get(token)
        if task is None or task['state'] != 'launching' or not alive(task['wrapper']) or task['boot'] != boot():
            return 137
        group = Path('/proc/self/cgroup').read_text().strip().split('::', 1)[1]
        if Path(group).name != task['unit']:
            raise Refusal('payload did not enter its owned cgroup')
        if not populated(CGROOT / group.lstrip('/')):
            raise Refusal('payload cgroup population cannot be proved')
        task['cgroup'] = group
        task['state'] = 'active'
        if not check_gate_candidate(ledger, task):
            return 2
        ledger.event(task, 'scope_enter', cgroup=group)
        ledger.save()
        args, lane = task['args'], task['lane']
        alone = lane == 'gate' and task.get('exclusive', True)
    if lane == 'gate':
        if not prepare_payload_policy(token):
            return 2
    if alone:
        phase(token, 'settle_begin')
        settle = int(os.environ.get('HEAVY_SETTLE', '120'))
        start = time.monotonic()
        while time.monotonic() - start < settle and os.getloadavg()[0] >= len(os.sched_getaffinity(0)):
            time.sleep(min(5, max(0, settle - (time.monotonic() - start))))
        phase(token, 'settle_end')
        fault('settled', token)
    fault('payload_floor', token)
    if not payload_disk_floor(token):
        return 2
    with locked() as ledger:
        task = ledger.tasks[token]
        if task['state'] != 'active':
            return 137
        if not check_gate_candidate(ledger, task):
            return 2
        task.update(capture_inputs(task['repo']))
        task['payload_started'] = time.time()
        ledger.event(task, 'payload_begin')
        ledger.save()
    subreaper()
    child = subprocess.Popen(args, stdin=subprocess.DEVNULL)
    next_gc = time.monotonic() + 120
    serial = 0
    while child.returncode is None:
        # One waiter owns both the command's status and adopted orphans.
        while True:
            try:
                pid, status = os.waitpid(-1, os.WNOHANG)
            except ChildProcessError:
                break
            if not pid:
                break
            if pid == child.pid:
                child.returncode = os.waitstatus_to_exitcode(status)
        if child.returncode is not None:
            break
        if lane == 'gate' and time.monotonic() >= next_gc:
            gc(token, serial)
            serial += 1
            next_gc = time.monotonic() + 120
        time.sleep(0.05)
    code = child.returncode if child.returncode >= 0 else 128 - child.returncode
    if alone:
        with locked() as ledger:
            elapsed = int(time.time() - ledger.tasks[token]['payload_started'])
        print(f'heavy: ran alone for {elapsed}s', flush=True)
    with locked() as ledger:
        if not check_gate_candidate(ledger, ledger.tasks[token]):
            return 2
    phase(token, 'payload_end', code=code)
    gc(token, serial)
    with locked() as ledger:
        task = ledger.tasks[token]
        own_cgroup(task)  # Sample accounting while the completed payload's unit still exists.
        task['code'], task['state'] = code, 'finishing'
        ledger.save()
    fault('payload_finished', token)
    # Keep the adopting parent until all its children are reaped. A child
    # that stays alive dies with this unit at the reconciler's release.
    while True:
        try:
            os.waitpid(-1, 0)
        except ChildProcessError:
            break
    return code


def main(args):
    if args == ['--installed']:
        return 0 if installed() else 1
    if len(args) == 2 and args[0] == '--group-held':
        with locked() as ledger:
            return 0 if args[1] in ledger.data['maintenance'] or (
                ledger.data['gate'] and args[1] != 'gate') else 1
    if len(args) in (2, 3) and args[0] == '--record-refusal':
        if args[1] not in ('policy', 'disk-floor'):
            raise Refusal('unknown refusal category')
        with locked() as ledger:
            task = ledger.tasks.get(args[2]) if len(args) == 3 else None
            if task is not None and 'lane' not in task:
                task = None
            ledger.event(task, 'refusal:' + uuid.uuid4().hex, reason=args[1])
            ledger.save()
        return 0
    if args == ['--check-recovery']:
        with locked() as ledger:
            ensure_reconciler(ledger)
        return 0
    if args and args[0] == '--install-reconciler':
        install(args[1] if len(args) > 1 else '5s')
        return 0
    if args == ['--remove-reconciler']:
        with locked() as ledger:
            reconcile(ledger)
            if any(task['state'] != 'released' for task in ledger.tasks.values()):
                raise Refusal('cannot remove reconciler with unfinished tasks')
            installation = ledger.data['installation']
            run(['systemctl', '--user', 'disable', '--now', PREFIX + '-reconcile.timer'], check=True)
            run(['systemctl', '--user', 'stop', PREFIX + '-reconcile.service'])
            for suffix in ('.service', '.timer'):
                (Path(installation['units']) / (PREFIX + '-reconcile' + suffix)).unlink(missing_ok=True)
            run(['systemctl', '--user', 'daemon-reload'], check=True)
            ledger.data['installation'] = None
            ledger.save()
        return 0
    if args == ['--reconcile']:
        with locked() as ledger:
            reconcile(ledger)
            refresh_probe(ledger)
        return 0
    if len(args) == 2 and args[0] in ('--maintenance-pause', '--maintenance-resume'):
        maintenance(args[1], args[0] == '--maintenance-pause')
        return 0
    if len(args) == 2 and args[0] == '--cancel':
        return cancel(args[1])
    if len(args) == 2 and args[0] in ('--task', '--payload'):
        return {'--task': wrapper, '--payload': payload}[args[0]](args[1])
    lane, exclusive, tail_lines = 'build', False, int(os.environ.get('HEAVY_TAIL', '200'))
    while args:
        if args[0] == '--gate':
            lane, exclusive, args = 'gate', True, args[1:]
        elif args[0] == '--land':
            lane, exclusive, args = 'gate', False, args[1:]
        elif args[0] == '--tail' and len(args) > 1:
            tail_lines, args = int(args[1]), args[2:]
        elif args[0] == '--':
            args = args[1:]
            break
        elif args[0].startswith('-'):
            raise Refusal(USAGE)
        else:
            break
    if not args or tail_lines < 0:
        raise Refusal(USAGE)
    return submit(args, lane, tail_lines, exclusive)


if __name__ == '__main__':
    try:
        sys.exit(main(sys.argv[1:]))
    except (Refusal, subprocess.CalledProcessError, ValueError, OSError) as error:
        # Record fixed categories, never arbitrary subprocess text or caller
        # arguments. Wrong-queue/corrupt-state refusals cannot use that ledger.
        try:
            if sys.argv[1:] != ['--installed']:
                with locked() as refused:
                    refused.event(None, 'refusal:' + uuid.uuid4().hex, reason=type(error).__name__)
                    refused.save()
        except (Refusal, ValueError, OSError):
            pass
        print('heavy: ' + str(error), file=sys.stderr)
        sys.exit(2)
