"""Private, standard-library remote supervisor and read-only gate inspection.

Invoked by tools/land over SSH. Never submits, cancels or edits heavy work.
"""
import ctypes
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time


def atomic(path, value):
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, prefix='.' + path.name,
                                     delete=False) as stream:
        json.dump(value, stream)
        stream.flush()
        os.fsync(stream.fileno())
        sibling = Path(stream.name)
    sibling.replace(path)


def boot():
    return Path('/proc/sys/kernel/random/boot_id').read_text().strip()


def process(pid):
    try:
        path = Path('/proc') / str(pid)
        if path.stat().st_uid != os.getuid():
            return None
        text = (path / 'stat').read_text()
        fields = text.rsplit(')', 1)[1].split()
        return dict(pid=int(pid), pgid=int(fields[2]), state=fields[0],
                    start_ticks=int(fields[19]), name=text.split('(', 1)[1].rsplit(')', 1)[0])
    except (FileNotFoundError, ProcessLookupError):
        return None


def group(pgid):
    if pgid is None:
        return []
    rows = []
    for path in Path('/proc').iterdir():
        if path.name.isdecimal():
            row = process(path.name)
            if row and row['pgid'] == pgid:
                rows.append(row)
    return rows


def directory(record):
    value = record.get('remote_dir')
    if value is None:
        return None
    if not re.fullmatch(r'/tmp/agents-gate\.' + re.escape(record['id']) + r'\.[A-Za-z0-9_]+', value):
        raise ValueError('invalid owned remote directory')
    path = Path(value)
    if path.is_symlink():
        raise ValueError('refusing symlink remote directory')
    return path


def identity(record):
    return {key: record[key] for key in ('id', 'sha', 'owner', 'what')}


def state(record, name='run'):
    path = directory(record)
    if path is None or not path.exists():
        return None
    if json.loads((path / 'identity.json').read_text()) != identity(record):
        raise ValueError('remote identity mismatch')
    status = path / (name + '.json')
    value = json.loads(status.read_text()) if status.exists() else None
    if value is not None and any(value.get(k) != v for k, v in identity(record).items()):
        raise ValueError('remote run identity mismatch')
    return value


def heavy(record):
    # Read the atomic canonical heavy snapshot, never its executable (which
    # reconciles/writes state), command arguments, environment or credentials.
    base = Path(os.environ.get('DEV_TMP', str(Path.home() / 'src/rust/tmp')))
    snapshot = json.loads((base / 'heavy/state.json').read_text())
    if snapshot.get('version') != 1 or not isinstance(snapshot.get('tasks'), dict):
        raise ValueError('heavy observation unavailable')
    root = directory(record)
    found = []
    for token, task in snapshot['tasks'].items():
        if not isinstance(task, dict):
            raise ValueError('invalid heavy task')
        if task.get('label') == record['what']:
            found.append(dict(token=token, state=task.get('state')))
            continue
        cwd = task.get('repo', task.get('cwd'))
        if cwd is None:
            # Released compact history has no directory, and cannot be live.
            if task.get('state') != 'released':
                raise ValueError('heavy task lacks a working directory')
            continue
        if not isinstance(cwd, str) or not Path(cwd).is_absolute():
            raise ValueError('invalid heavy working directory')
        if root and Path(os.path.realpath(cwd)).is_relative_to(root):
            found.append(dict(token=token, state=task.get('state')))
    return found


def inspect(record):
    record = dict(record)
    if record.get('remote_dir') is None and record.get('prepare_uncertain'):
        candidates = [p for p in Path('/tmp').glob('agents-gate.' + record['id'] + '.*')
                      if re.fullmatch(r'agents-gate\.' + record['id'] + r'\.[A-Za-z0-9_]+', p.name)]
        if len(candidates) != 1:
            raise ValueError('remote allocation unknown; retain claim for ops')
        record['remote_dir'] = str(candidates[0])
    value = state(record)
    processes, supervisors = identities(record | (value or {}), record.get('launch_requested'), value)
    upload = state(record, 'upload') or record.get('upload')
    up_processes, up_supervisors = identities(upload or {}, record.get('upload_requested'), upload)
    path = directory(record)
    return dict(remote_dir=record.get('remote_dir'), exists=bool(path and path.exists()),
                run=value, upload=upload, processes=processes + up_processes,
                supervisors=supervisors + up_supervisors, heavy=heavy(record))


def identities(scope, requested, value):
    if scope.get('boot') and scope['boot'] != boot():
        raise ValueError('builder rebooted: saved process identity is unavailable')
    pgid = scope.get('pgid')
    if pgid is not None and (type(pgid) is not int or pgid <= 1):
        raise ValueError('invalid remote process group')
    leader = process(pgid) if pgid else None
    if leader and leader['start_ticks'] != scope.get('start_ticks'):
        raise ValueError('remote process group identity changed')
    supervisor = process(scope['supervisor_pid']) if scope.get('supervisor_pid') else None
    if supervisor and supervisor['state'] != 'Z':
        if supervisor['start_ticks'] != scope.get('supervisor_start_ticks'):
            raise ValueError('remote supervisor identity changed')
        supervisors = [supervisor]
    else:
        supervisors = []
    if requested and pgid is None:
        cancelled_before_launch = value and value.get('phase') == 'finished' and value.get('exit_code') == 125
        if not supervisors and not cancelled_before_launch:
            raise ValueError('remote process identity unavailable; keep claim for ops')
    return group(pgid), supervisors


def upload(record):
    """Publish the uploader's identity before allowing it to consume any bytes."""
    path = directory(record)
    state(record)  # Validate owned directory before writing.
    read_fd, write_fd = os.pipe()
    try:
        with (path / 'run.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if (path / 'cancelled').exists() or (path / 'upload.json').exists():
                raise ValueError('remote upload cancelled or already launched')
            # The barrier survives SSH loss: EOF before permission means no copy.
            worker = ("import os,sys; "
                      "permission=os.read(int(sys.argv[1]),1); "
                      "command=['cat']; "
                      "os.execvp(command[0],command) if permission==b'1' else sys.exit(125)")
            with (path / 'candidate.bundle').open('wb') as stream:
                child = subprocess.Popen([sys.executable, '-I', '-B', '-c', worker, str(read_fd)],
                                         stdin=sys.stdin.buffer, stdout=stream,
                                         stderr=subprocess.DEVNULL, pass_fds=(read_fd,), start_new_session=True)
            value = identity(record) | dict(phase='running', boot=boot(), pgid=child.pid,
                        start_ticks=process(child.pid)['start_ticks'], supervisor_pid=os.getpid(),
                        supervisor_start_ticks=process(os.getpid())['start_ticks'])
            atomic(path / 'upload.json', value)
            os.write(write_fd, b'1')
        code = child.wait()
        with (path / 'run.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            value |= dict(phase='finished', exit_code=code)
            atomic(path / 'upload.json', value)
        return value
    finally:
        os.close(read_fd)
        os.close(write_fd)


def prepare(record):
    path = Path(tempfile.mkdtemp(prefix='agents-gate.' + record['id'] + '.', dir='/tmp'))
    atomic(path / 'identity.json', identity(record))
    return dict(remote_dir=str(path))


def start(record, command, limit, source):
    path = directory(record)
    state(record)  # Validate identity before any write.
    with (path / 'run.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if (path / 'cancelled').exists() or (path / 'run.json').exists():
            raise ValueError('remote run cancelled or already launched')
        helper = path / 'supervisor.py'
        sibling = helper.with_suffix('.new')
        sibling.write_text(source)
        sibling.replace(helper)
        child = subprocess.Popen([sys.executable, '-I', '-B', str(helper), 'supervise',
                                  json.dumps(record), command, str(limit)],
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, start_new_session=True)
        metadata = identity(record) | dict(phase='launching', boot=boot(),
                    supervisor_pid=child.pid, supervisor_start_ticks=process(child.pid)['start_ticks'])
        atomic(path / 'run.json', metadata)
    end = time.monotonic() + 5
    while time.monotonic() < end:
        value = state(record)
        if value.get('pgid'):
            return value
        if value['phase'] == 'finished':
            return value
        time.sleep(.01)
    raise TimeoutError('remote start handshake timed out')


def supervise(record, command, limit):
    path = directory(record)
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(36, 1, 0, 0, 0):
        raise OSError(ctypes.get_errno(), 'subreaper')
    with (path / 'run.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        value = state(record)
        if (path / 'cancelled').exists():
            atomic(path / 'run.json', value | dict(phase='finished', exit_code=125))
            return
        child = subprocess.Popen(['sh', '-c', command], start_new_session=True)
        value |= dict(phase='running', pgid=child.pid, start_ticks=process(child.pid)['start_ticks'])
        atomic(path / 'run.json', value)
        fcntl.flock(lock, fcntl.LOCK_UN)
        try:
            code = child.wait(timeout=float(limit))
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait()
            code = 124
        # Ordinary completion/hard-wall containment drains this run's orphans.
        # An SSH drop or local interrupt never triggers this path early.
        while True:
            for pid in Path(f'/proc/{os.getpid()}/task/{os.getpid()}/children').read_text().split():
                try:
                    os.kill(int(pid), signal.SIGKILL)
                except ProcessLookupError:
                    pass
            try:
                pid, status, usage = os.wait4(-1, os.WNOHANG)
            except ChildProcessError:
                break
            if not pid:
                time.sleep(.005)
        fcntl.flock(lock, fcntl.LOCK_EX)
        atomic(path / 'run.json', value | dict(phase='finished', exit_code=code))


def wait(record, limit):
    end = time.monotonic() + float(limit)
    while time.monotonic() < end:
        value = state(record)
        if value and value['phase'] == 'finished':
            observation = inspect(record)
            if not observation['processes'] and not observation['supervisors']:
                return observation
        time.sleep(.02)
    raise TimeoutError('remote exit status was not received within the wall limit')


def cleanup(record):
    # Inspection precedes mutations, and is repeated under the launch lock.
    observation = inspect(record)
    if observation['processes'] or observation['supervisors'] or observation['heavy']:
        raise ValueError('remote work still exists; claim must remain held')
    path = directory(record)
    if path and path.exists():
        with (path / 'run.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            observation = inspect(record)
            if observation['processes'] or observation['supervisors'] or observation['heavy']:
                raise ValueError('remote work appeared during restoration')
            (path / 'cancelled').touch()  # Prevent a delayed launch after inspection.
            shutil.rmtree(path)
    observation = inspect(record)
    if observation['exists'] or observation['processes'] or observation['supervisors'] or observation['heavy']:
        raise ValueError('builder restoration unproved')
    return observation


def kill(record):
    observation = inspect(record)
    if observation['heavy']:
        raise ValueError('BUG: gate submitted heavy work; resolve it with ops')
    path = directory(record)
    if path is None or not path.exists():
        raise ValueError('cannot cancel an unknown remote directory')
    with (path / 'run.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        observation = inspect(record)  # Verify boot/PID identity immediately before killing.
        (path / 'cancelled').touch()
        for value in (observation['run'] or record, observation.get('upload') or {}):
            pgid = value.get('pgid')
            if pgid and group(pgid):
                os.killpg(pgid, signal.SIGKILL)
    end = time.monotonic() + 5
    while time.monotonic() < end:
        observation = inspect(record)
        if not observation['processes'] and not observation['supervisors']:
            return observation
        time.sleep(.02)
    raise TimeoutError('remote processes have not ended')


def main():
    action = sys.argv[1]
    record = json.loads(sys.argv[2])
    if not re.fullmatch('[0-9a-f]{32}', record['id']):
        raise ValueError('invalid claim identity')
    if action == 'supervise':
        supervise(record, sys.argv[3], sys.argv[4])
        return
    if action == 'start':
        result = start(record, *sys.argv[3:])
    elif action == 'wait':
        result = wait(record, sys.argv[3])
    else:
        result = {'prepare': prepare, 'upload': upload, 'inspect': inspect, 'cleanup': cleanup, 'kill': kill}[action](record)
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
