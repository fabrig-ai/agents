#!/usr/bin/env python3
"""Slow process/deployment/Git matrices, run explicitly until gate tiers land."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import runpy
import unittest
from test_qa import Lab
import test_qa as fixtures
from test_qa import (
    CHATGPT,
    CLAUDE,
    HUNG_TOOL_S,
    KIT,
    P,
    Path,
    SCRIPT,
    TIMEOUT_DRIVER,
    ThreadPoolExecutor,
    aged,
    alive,
    datetime,
    dead,
    deployment,
    deployment_pass,
    driven_walk,
    driven_watch,
    end_deployment_pass,
    executable,
    fcntl,
    finished_pair,
    hashlib,
    hold_slot,
    json,
    orphaned_take_keeps_admission,
    os,
    pause_walk,
    queued_entries,
    repeated_claim_lifetimes,
    resource,
    resting,
    select,
    settled_watch,
    shutil,
    signal,
    slot_claims,
    start_stuck_pass,
    stuck_posts,
    subprocess,
    sys,
    time,
    timedelta,
    timezone,
    wait_for,
    walk_with_logins,
    write_walk,
)

def a_detached_pipe_cannot_hold_a_timed_out_command(lab):
    marker = lab.root / 'detached.pid'
    script = lab.root / 'detach.py'
    script.write_text(f'''import os, time
from pathlib import Path
if os.fork() == 0:
    os.setsid()
    marker = Path({str(marker)!r})
    temporary = marker.with_name(marker.name + '.new')
    temporary.write_text(str(os.getpid()))
    temporary.replace(marker)
time.sleep(60)
''')
    driver = f'''import resource, runpy, sys, time
from pathlib import Path
tool = runpy.run_path({str(SCRIPT)!r})
subprocess = tool['subprocess']
original_popen = subprocess.Popen
class ReadyPopen(original_popen):
    def communicate(self, input=None, timeout=None):
        if timeout == 0.3:
            # Start the timeout only once a detached child holds the pipes.
            marker = Path({str(marker)!r})
            deadline = time.monotonic() + 10
            while not marker.exists():
                if self.poll() is not None or time.monotonic() >= deadline:
                    self.kill()
                    super().communicate()
                    raise AssertionError('fixture child never detached')
                time.sleep(0.01)
        return super().communicate(input=input, timeout=timeout)
subprocess.Popen = ReadyPopen
start = resource.getrusage(resource.RUSAGE_CHILDREN)
result = tool['command']([sys.executable, '-I', '-B', {str(script)!r}], timeout=0.3)
assert result.returncode == 124
end = resource.getrusage(resource.RUSAGE_CHILDREN)
# Idle child CPU 19 ms; 4x rounded up to the 500 ms minimum.
assert end.ru_utime + end.ru_stime - start.ru_utime - start.ru_stime < 0.5
'''
    try:
        result = subprocess.run([sys.executable, '-I', '-B', '-c', driver], env=lab.env,
                                capture_output=True, text=True, timeout=10)
        assert result.returncode == 0, result.stderr
        assert marker.exists()
    finally:
        if marker.exists():
            pid = int(marker.read_text())
            if alive(pid):
                os.kill(pid, signal.SIGKILL)
            dead(pid)



def deploy_records_then_starts_its_unit(lab):
    directory = lab.root / P
    directory.mkdir()
    unit, pid = deployment(lab, directory)
    assert unit == f'qa-{P}-box'
    args, = lab.calls('systemd-run')
    for arg in ('--user', '--quiet', '--collect', '--service-type=exec', '--setenv=PATH',
                f'--working-directory={directory}', '--property=KillMode=control-group',
                f'--property=StandardOutput=append:{directory}/box.log',
                f'--property=StandardError=append:{directory}/box.log', '--property=TimeoutStopSec=110',
                f'--property=ExecStop=-"{SCRIPT}" "_give-back" "{directory}" "50"'):
        assert arg in args, (arg, args)
    assert args[-1] == str(directory / 'box/server')
    assert not any('ExecStopPost=' in arg for arg in args)
    assert (directory / 'deployments').read_text() == unit + '\n'
    # Do not replace an active fake unit: refuse the repeated launch.
    lab.configure(deploy_failure=True)
    result = lab.run('deploy', str(directory), 'box', '--', 'true', status=4)
    assert 'fixture deployment refused' in result.stderr
    assert (directory / 'deployments').read_text() == unit + '\n'
    lab.run('deploy', str(directory), 'other', '--', 'true', status=4)
    assert (directory / 'deployments').read_text().splitlines() == [unit, f'qa-{P}-other']
    command = lab.calls('systemd-run')[-1]
    assert Path(command[command.index('--') + 1]).is_absolute()
    link = lab.root / 'linked'
    link.symlink_to(directory, target_is_directory=True)
    unsafe = []
    for name in ('has space', 'has$dollar', 'has%percent', 'has"quote', 'has\\slash', 'has\ttab', 'has\nline'):
        path = lab.root / name
        path.mkdir()
        scratch = path / P
        scratch.mkdir()
        unsafe.append(str(scratch))
    before = len(lab.calls('systemd-run'))
    for path, name, argv in [('relative', 'box', ['true']), (str(link), 'box', ['true']),
                             *[(path, 'box', ['true']) for path in unsafe],
                             (str(directory), 'Box', ['true']), (str(directory), 'a/b', ['true']),
                             (str(directory), 'missing', ['not-a-command-on-path']),
                             (str(directory), 'missing', [])]:
        previous = (directory / 'deployments').read_bytes()
        lab.run('deploy', path, name, '--', *argv, status=2)
        assert (directory / 'deployments').read_bytes() == previous
        assert len(lab.calls('systemd-run')) == before
        if Path(path).is_absolute() and Path(path) != directory:
            assert Path(path).is_symlink() or not (Path(path) / 'deployments').exists()
    # Refuse a linked registry, and an unsafe resolved qa path, before a launch.
    registry = directory / 'deployments'
    original = registry.read_bytes()
    registry.unlink()
    registry.symlink_to(directory / 'box.log')
    lab.run('deploy', str(directory), 'box', '--', 'true', status=2)
    registry.unlink()
    registry.write_bytes(original)
    copied = lab.root / 'unsafe kit'
    copied.mkdir()
    qa = copied / 'qa'
    shutil.copy2(SCRIPT, qa)
    shutil.copy2(KIT / 'evidence.py', copied / 'evidence.py')
    result = subprocess.run([str(qa), 'deploy', str(directory), 'box', '--', 'true'],
                            env=lab.env, capture_output=True, text=True)
    assert result.returncode == 2 and len(lab.calls('systemd-run')) == before
    for value in ('0', '60', 'bad'):
        lab.run('deploy', str(directory), 'box', '--', 'true', status=2, extra={'QA_STOP_SECONDS': value})
    assert registry.read_bytes() == original
    lab.configure(deploy_failure=False)
    binary = lab.root / 'caller-bin'
    binary.mkdir()
    output = directory / 'arguments'
    executable(binary / 'capture', 'import json, os, sys\nfrom pathlib import Path\n'
        + f'Path({str(output)!r}).write_text(json.dumps([sys.argv[1:], os.environ["PATH"]]))\n')
    caller_path = str(binary) + os.pathsep + lab.env['PATH']
    arguments = ['one value', '$literal', '--flag']
    lab.run('deploy', str(directory), 'args', '--', 'capture', *arguments, extra={'PATH': caller_path})
    wait_for(output.exists)
    assert json.loads(output.read_text()) == [arguments, caller_path]
    call = lab.calls('systemd-run')[-1]
    assert call[call.index('--') + 1:] == [str(binary / 'capture'), *arguments]
    os.killpg(pid, signal.SIGKILL)
    dead(pid)



def a_stopped_pass_gives_its_login_back(lab):
    directory, state = deployment_pass(lab, CHATGPT)
    unit, pid = deployment(lab, directory, login=CHATGPT)
    assert not Path(state['logins'][CHATGPT]).exists()
    end_deployment_pass(lab)
    state = lab.watch_state()[1]
    assert state['stage'] in ('ending', 'ended') and state['given'] == [CHATGPT] and 'stopped' not in state
    assert Path(state['logins'][CHATGPT]).is_file()
    assert not (lab.root / 'units' / (unit + '.json')).exists()
    dead(pid)
    lines = (directory / 'give-back.log').read_text().splitlines()
    assert len(lines) == 2 and all(line.endswith(' exit 0') for line in lines), lines
    calls = list(map(json.loads, (lab.root / 'tools.jsonl').read_text().splitlines()))
    stop = next(i for i, call in enumerate(calls) if call['tool'] == 'systemctl' and call['args'] == ['--user', 'stop', '--no-block', '--', unit])
    give = max(i for i, call in enumerate(calls[:stop]) if call['tool'] == 'logins' and call['args'][:2] == ['give', CHATGPT])
    assert give < stop
    assert directory.joinpath('on-stop').stat().st_mode & 0o777 == 0o700



def a_failed_export_leaves_the_unit_up(lab):
    directory, state = deployment_pass(lab, CHATGPT)
    unit, pid = deployment(lab, directory, login=CHATGPT)
    executable(directory / 'give-back', 'raise SystemExit(1)\n')
    end_deployment_pass(lab)
    state = lab.watch_state()[1]
    assert state['stage'] in ('ending', 'ended') and not state['given'] and 'stopped' not in state and alive(pid)
    assert ['--user', 'stop', '--no-block', '--', unit] not in lab.calls('systemctl')
    alert, notice = lab.sent()
    assert alert == stuck_posts(lab)[0]
    for text in (unit, CHATGPT, str(directory), state['logins'][CHATGPT], 'tries again at each check'):
        assert text in notice['body']
    aged(lab, directory)
    lab.watch()
    assert directory.exists() and alive(pid)
    (directory / 'box/login').rename(state['logins'][CHATGPT])
    settled_watch(lab, unit)
    dead(pid)
    assert directory.exists() and lab.walk_state()[1]['stage'] == 'ended' and len(lab.sent()) == 2



def two_stops_take_turns(lab):
    directory = lab.root / P
    directory.mkdir()
    # Keep the first exporter in its critical section until the second
    # wrapper reports an actual failed lock attempt, rather than sleeping.
    for name in ('export-ready', 'lock-busy', 'release-export'):
        os.mkfifo(directory / name)
    ready = os.open(directory / 'export-ready', os.O_RDWR | os.O_NONBLOCK)
    busy = os.open(directory / 'lock-busy', os.O_RDWR | os.O_NONBLOCK)
    release = os.open(directory / 'release-export', os.O_RDWR)
    executable(directory / 'give-back', 'import os\nfrom pathlib import Path\n'
               "with Path('runs').open('a') as out: out.write('start\\n')\n"
               "with open('export-ready', 'wb', buffering=0) as out: out.write(b'r')\n"
               "with open('release-export', 'rb', buffering=0) as source: source.read(1)\n"
               "with Path('runs').open('a') as out: out.write('end\\n')\n")
    driver = f'''import runpy, sys
from pathlib import Path
tool = runpy.run_path({str(SCRIPT)!r})
flock = tool['fcntl'].flock
def observed_flock(*args):
    try:
        return flock(*args)
    except BlockingIOError:
        with open({str(directory / 'lock-busy')!r}, 'wb', buffering=0) as out:
            out.write(b'b')
        raise
tool['fcntl'].flock = observed_flock
sys.exit(tool['main']())
'''
    processes = []
    def receive(fd):
        poll = select.poll()
        poll.register(fd, select.POLLIN)
        assert poll.poll(10_000), 'fixture readiness was not announced'
        assert os.read(fd, 1)
    try:
        processes.append(subprocess.Popen([str(SCRIPT), '_give-back', str(directory), '30'], env=lab.env))
        receive(ready)
        processes.append(subprocess.Popen([sys.executable, '-I', '-B', '-c', driver,
                                          '_give-back', str(directory), '30'], env=lab.env))
        receive(busy)
        assert (directory / 'runs').read_text().splitlines() == ['start']
        os.write(release, b'r')
        receive(ready)
        assert (directory / 'runs').read_text().splitlines() == ['start', 'end', 'start']
        os.write(release, b'r')
        assert [proc.wait(timeout=10) for proc in processes] == [0, 0]
    finally:
        os.write(release, b'rr')
        for proc in processes:
            if proc.poll() is None:
                proc.kill()
            proc.wait()
        for fd in (ready, busy, release):
            os.close(fd)
    assert (directory / 'runs').read_text().splitlines() == ['start', 'end', 'start', 'end']
    assert (directory / 'give-back.log').read_text().count('exit 0') == 2
    with (directory / 'give-back.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        lab.run('_give-back', str(directory), '1')
    assert 'lock busy past 1 s' in (directory / 'give-back.log').read_text()
    (directory / 'give-back').unlink()
    lab.run('_give-back', str(directory), '1')
    (directory / 'give-back').symlink_to('/bin/false')
    lab.run('_give-back', str(directory), '1')
    assert (directory / 'give-back.log').read_text().count('absent') == 2
    lab.run('_give-back')
    lab.run('_give-back', str(directory), 'invalid')
    assert 'error:' in (directory / 'give-back.log').read_text()
    lab.run('_give-back', str(directory / 'missing'), '1')
    (directory / 'give-back.lock').unlink()
    (directory / 'give-back.lock').symlink_to(directory / 'runs')
    lab.run('_give-back', str(directory), '1')
    assert 'error:' in (directory / 'give-back.log').read_text()
    (directory / 'give-back.lock').unlink()
    (directory / 'give-back.log').unlink()
    os.mkfifo(directory / 'give-back.log')
    started = resource.getrusage(resource.RUSAGE_CHILDREN)
    lab.run('_give-back', str(directory), '1')
    ended = resource.getrusage(resource.RUSAGE_CHILDREN)
    # Idle child CPU 56 ms; 4x rounded up to the 500 ms minimum.
    assert ended.ru_utime + ended.ru_stime - started.ru_utime - started.ru_stime < 0.5



def a_wrapper_past_its_bound_is_ended(lab):
    (lab.tmp / 'machine.env').write_text('QA_STOP_SECONDS=3\n')
    lab.env['QA_STOP_SECONDS'] = '2'
    directory, _ = deployment_pass(lab)
    unit, pid = deployment(lab, directory)
    executable(directory / 'give-back', 'import os, subprocess, time\nfrom pathlib import Path\n'
        + f'child = subprocess.Popen([{sys.executable!r}, "-I", "-B", "-c", "import time; time.sleep(60)"])\n'
          "marker = Path('export-pids.new')\n"
          "marker.write_text(f'{os.getpid()} {child.pid}')\n"
          "marker.replace('export-pids')\n"
          'time.sleep(60)\n')
    # Use the same handshake for the direct wrapper and its manager invocation.
    # The wrapper still passes its unchanged two-second wait to Popen.wait().
    driver = f"""import runpy, sys, time
from pathlib import Path
tool = runpy.run_path({str(SCRIPT)!r})
subprocess = tool['subprocess']
original_popen = subprocess.Popen
class ReadyPopen(original_popen):
    def wait(self, timeout=None):
        if timeout is not None:
            marker = Path({str(directory / 'export-pids')!r})
            deadline = time.monotonic() + 10
            while not (marker.exists() and marker.read_text().split()[:1] == [str(self.pid)]):
                if self.poll() is not None or time.monotonic() >= deadline:
                    self.kill()
                    super().wait()
                    raise AssertionError('fixture exporter never reached its hang')
                time.sleep(0.01)
        return super().wait(timeout=timeout)
subprocess.Popen = ReadyPopen
sys.exit(tool['main']())
"""
    ready_qa = executable(lab.root / 'ready-qa', driver)
    started = resource.getrusage(resource.RUSAGE_CHILDREN)
    result = subprocess.run([str(ready_qa), '_give-back', str(directory), '2'],
                            env=lab.env, capture_output=True, text=True, timeout=HUNG_TOOL_S)
    assert result.returncode == 0, result.stderr
    ended = resource.getrusage(resource.RUSAGE_CHILDREN)
    # Idle child CPU 85 ms; 4x rounded up to the 500 ms minimum.
    assert ended.ru_utime + ended.ru_stime - started.ru_utime - started.ru_stime < 0.5
    for process in map(int, (directory / 'export-pids').read_text().split()):
        dead(process)
    assert 'killed past 2 s' in (directory / 'give-back.log').read_text()
    # The bound also applies when the manager invokes the wrapper.
    saved = lab.root / 'units' / (unit + '.json')
    metadata = json.loads(saved.read_text())
    assert metadata['stop'][-1] == '2'
    assert '--property=TimeoutStopSec=62' in lab.calls('systemd-run')[0]
    # The fake manager executes the same wrapper with the readiness driver.
    metadata['stop'][0] = str(ready_qa)
    temporary = saved.with_suffix('.new')
    temporary.write_text(json.dumps(metadata))
    temporary.replace(saved)
    result = subprocess.run([str(lab.root / 'systemctl'), '--user', 'stop', '--', unit],
                            env=lab.env, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    for process in map(int, (directory / 'export-pids').read_text().split()):
        dead(process)
    dead(pid)
    assert not saved.exists() and (directory / 'give-back.log').read_text().count('killed past 2 s') == 2
    # A leader that exits successfully must not leave an exporter child alive.
    executable(directory / 'give-back', 'import subprocess\nfrom pathlib import Path\n'
        + f'child = subprocess.Popen([{sys.executable!r}, "-I", "-B", "-c", "import time; time.sleep(60)"])\n'
          "Path('leftover-pid').write_text(str(child.pid))\n")
    lab.run('_give-back', str(directory), '2')
    dead(int((directory / 'leftover-pid').read_text()))
    assert (directory / 'give-back.log').read_text().splitlines()[-1].endswith('exit 0')



def a_deployment_that_exited_leaves_its_login_out(lab):
    directory, state = deployment_pass(lab, CHATGPT)
    unit, pid = deployment(lab, directory, login=CHATGPT)
    os.killpg(pid, signal.SIGKILL)
    dead(pid)
    end_deployment_pass(lab)
    state = lab.watch_state()[1]
    assert not state['given'] and 'stopped' not in state
    assert 'exit 1' in (directory / 'give-back.log').read_text()
    alert, notice = lab.sent()
    assert alert == stuck_posts(lab)[0]
    assert CHATGPT in notice['body'] and state['logins'][CHATGPT] in notice['body']
    assert f'Unit {unit} is still up' not in notice['body']
    aged(lab, directory)
    lab.watch()
    assert directory.exists() and len(lab.sent()) == 2



def a_failed_stop_is_tried_again(lab):
    lab.env['QA_GIVE_BACK_SECONDS'] = '0'
    directory, _ = deployment_pass(lab)
    unit, pid = deployment(lab, directory)
    lab.configure(stop_failures=[unit])
    lab.end_run()
    result = lab.watch()
    assert f'stop {unit} failed' in result.stdout and alive(pid)
    assert 'stopped' not in lab.watch_state()[1]
    aged(lab, directory)
    lab.configure(unit_states={unit: 'deactivating'})
    result = lab.watch()
    assert 'waiting for unit to stop' in result.stdout
    assert directory.exists() and 'stopped' not in lab.watch_state()[1]
    lab.configure(unit_states={unit: 'unknown'})
    result = lab.watch()
    assert f'{unit}: cannot establish unit state' in result.stdout
    assert directory.exists() and alive(pid)
    lab.configure(stop_failures=[], unit_states={})
    # The asynchronous stop is allowed to complete at the next check.
    lab.watch()
    dead(pid)
    wait_for(lambda: not (lab.root / 'units' / (unit + '.json')).exists())
    lab.watch()
    assert directory.exists() and lab.walk_state()[1]['stage'] == 'ended' and len(lab.sent()) == 1
    assert lab.calls('systemctl').count(['--user', 'stop', '--no-block', '--', unit]) == 3



def a_restarted_service_goes_on(lab):
    directory, state = deployment_pass(lab, CHATGPT, CLAUDE, in_place=(CLAUDE,))
    unit, pid = deployment(lab, directory, login=CHATGPT)
    # Restore the moved login as the session stop would; finish then crashes just
    # after saving its give, before any deployment stop or in-place give.
    lab.run('_give-back', str(directory), '5')
    lab.end_run()
    driver = f'''import os, runpy, sys
tool = runpy.run_path({str(SCRIPT)!r})
watch = tool['Watch']
save = watch.save
def crash(self, directory, state):
    save(self, directory, state)
    if state.get('given') == [{CHATGPT!r}]: os._exit(17)
watch.save = crash
sys.exit(tool['main']())
'''
    result = subprocess.run([sys.executable, '-I', '-B', '-c', driver, 'watch', '--director',
                             'director@fixture', '--once'], env=lab.env, capture_output=True, text=True)
    assert result.returncode == 17, result.stderr
    state = lab.watch_state()[1]
    assert state['stage'] in ('ending', 'ended') and state['given'] == [CHATGPT] and 'stopped' not in state and alive(pid)
    assert not lab.sent()
    settled_watch(lab, unit)
    state = lab.watch_state()[1]
    assert 'stopped' not in state and state['given'] == [CHATGPT, CLAUDE]
    dead(pid)
    # The recovery did not repeat custody's give (the pre-existing stray sweep
    # can still ask the login tool about an already free rung login).
    config = json.loads((lab.root / 'tools.json').read_text())
    assert config['logins_held'] == [] and config['logins_released'] == [CHATGPT, CLAUDE]



def an_in_place_login_waits_for_every_unit(lab):
    lab.env['QA_GIVE_BACK_SECONDS'] = '1'
    directory, state = deployment_pass(lab, CHATGPT, CLAUDE, in_place=(CLAUDE,))
    assert state['kinds'] == {CHATGPT: 'moved', CLAUDE: 'in-place'}
    first, one = deployment(lab, directory, login=CHATGPT)
    second, two = deployment(lab, directory, 'other')
    lab.configure(stop_failures=[second])
    end_deployment_pass(lab)
    state = lab.watch_state()[1]
    assert state['given'] == [CHATGPT] and 'stopped' not in state and alive(two)
    assert json.loads((lab.root / 'tools.json').read_text())['logins_held'] == [CLAUDE]
    dead(one)
    wait_for(lambda: not (lab.root / 'units' / (first + '.json')).exists())
    lab.configure(stop_failures=[])
    lab.watch()
    # A stop can outlast this check's one-second poll budget under load.
    # Process death precedes the fake manager removing its stopping record;
    # wait for both, then let the next check observe completion and give.
    dead(two)
    wait_for(lambda: not (lab.root / 'units' / (second + '.json')).exists())
    lab.watch()
    state = lab.watch_state()[1]
    assert state['given'] == [CHATGPT, CLAUDE] and 'stopped' not in state
    calls = list(map(json.loads, (lab.root / 'tools.jsonl').read_text().splitlines()))
    give = max(i for i, row in enumerate(calls) if row['tool'] == 'logins' and row['args'][:2] == ['give', CLAUDE])
    stop = max(i for i, row in enumerate(calls) if row['tool'] == 'systemctl' and row['args'] == ['--user', 'stop', '--no-block', '--', second])
    assert give > stop and len(lab.sent()) == 1



def deployments_names_only_its_own_units(lab):
    directory, _ = deployment_pass(lab)
    unit, pid = deployment(lab, directory)
    foreign = ['codex-run-x', 'agents-qa-watch', 'qa-otherpass-box', unit + ' bad', unit + '/bad']
    (directory / 'deployments').write_text('\n'.join([*foreign, unit, unit]) + '\n')
    lab.end_run()
    result = lab.watch()
    assert 'stopped' not in lab.watch_state()[1]
    for name in foreign:
        assert name not in result.stdout
        assert not any(name in args for args in lab.calls('systemctl'))
    assert lab.calls('systemctl').count(['--user', 'stop', '--no-block', '--', unit]) == 1
    dead(pid)



def a_unit_of_another_directory_is_not_stopped(lab):
    directory, _ = deployment_pass(lab, CLAUDE, in_place=(CLAUDE,))
    unit, pid = deployment(lab, directory)
    path = lab.root / 'units' / (unit + '.json')
    metadata = json.loads(path.read_text())
    metadata['directory'] = str(lab.root / 'elsewhere')
    path.write_text(json.dumps(metadata))
    lab.end_run()
    result = lab.watch()
    assert 'WorkingDirectory is not the walk directory' in result.stdout
    assert not lab.watch_state()[1]['given'] and alive(pid)
    assert ['--user', 'stop', '--no-block', '--', unit] not in lab.calls('systemctl')
    aged(lab, directory)
    # Failures and malformed observations hold the login without leaking output.
    marker = 'outside-' + 'observation-text'
    for config in ({'list_failures': [directory.name]},
                   {'list_output': {directory.name: marker}},
                   {'show_output': {unit: 'LoadState=loaded\nLoadState=loaded\nActiveState=inactive\nWorkingDirectory=' + str(directory)}},
                   {'show_output': {unit: marker}}):
        lab.configure(list_failures=[], list_output={}, show_output={})
        lab.configure(**config)
        result = lab.watch()
        assert directory.exists() and not lab.watch_state()[1]['given'] and alive(pid)
        assert marker not in result.stdout + result.stderr
    lab.configure(list_failures=[], list_output={}, show_output={})
    metadata['directory'] = str(directory)
    path.write_text(json.dumps(metadata))
    settled_watch(lab, unit)
    dead(pid)
    assert directory.exists() and lab.walk_state()[1]['stage'] == 'ended'



def the_service_ends_a_walk_at_its_cap(lab):
    resting(lab, CHATGPT)
    lab.configure(logins_real=[CHATGPT])
    lab.walk('b0', '--login', CHATGPT, '--cap', '1', now='2026-10-27T10:00:00Z')
    directory, state = lab.walk_state()
    unit, pid = deployment(lab, directory, login=CHATGPT)
    before = lab.head()
    settled_watch(lab, unit, now='2026-10-27T10:01:01Z', extra={'QA_POST_STATUS': '2'})
    state = lab.walk_state()[1]
    assert state['capped'] and state['released'] and state['given'] == [CHATGPT]
    assert state['end_logged'] and not state['posted'] and state['stage'] == 'ending'
    dead(pid)
    lab.watch(extra={'QA_POST_STATUS': '3'})
    lab.watch()
    state = lab.walk_state()[1]
    assert state['stage'] == 'ended' and state['posted'] and lab.head() == before
    rows = (directory.parent / 'b0/loop.tsv').read_text().splitlines()
    assert [row.split('\t')[3] for row in rows[1:]] == ['walk-start', 'walk-end']
    assert 'exit 143' in rows[-1]
    posts = lab.sent()
    assert len(posts) == 2
    assert posts[-1]['args'][1:3] == [state['starter'], 'qa: walk rung-b0-1 ended']
    assert str(directory / 'report.md') in posts[-1]['body'] and 'exit 143' in posts[-1]['body']
    calls = list(map(json.loads, (lab.root / 'tools.jsonl').read_text().splitlines()))
    give = next(i for i, call in enumerate(calls) if call['tool'] == 'logins' and call['args'] == ['give', CHATGPT, '--as', state['holder']])
    stop = next(i for i, call in enumerate(calls) if call['tool'] == 'systemctl' and call['args'] == ['--user', 'stop', '--no-block', '--', unit])
    assert give < stop
    assert ['send', '--as', 'qa-watch', state['starter'], 'qa: walk rung-b0-1 ended', str(directory / 'post-body')] in lab.calls('post')



def a_stuck_walk_login_alerts_the_director_and_the_list(lab):
    address = 'design/upgrades-draft@fixture'
    path = lab.home / '.config/agents-qa/stuck'
    path.parent.mkdir(parents=True)
    path.write_text(address + '\ndirector@fixture\n')
    for refused in (False, True):
        resting(lab, CHATGPT)
        lab.configure(logins_real=[CHATGPT], post_status={address: 1 if refused else 0})
        lab.walk('b0', '--login', CHATGPT, '--cap', '1', now='2026-10-27T10:00:00Z')
        directory, state = lab.walk_states()[-1]
        if refused:
            (directory / 'paused').write_text('blocked before deployment\n')
            lab.end_run(state)
            lab.watch(now='2026-10-27T10:00:01Z')
            previous = lab.walk_states()[-1][1]['attempts'][0]
            lab.run('walk', 'fabrig', 'b0', '--resume', state['walk'], '--build', 'main',
                    now='2026-10-27T10:00:00Z')
            state = lab.walk_states()[-1][1]
            assert state['attempt'] == 2 and state['alerts'] == {}
        unit, pid = deployment(lab, directory, login=CHATGPT)
        executable(directory / 'give-back', 'raise SystemExit(1)\n')
        before = len(lab.sent())
        lab.watch(now='2026-10-27T10:01:01Z')
        posts = lab.sent()[before:]
        assert len(posts) == 3
        alerts = posts[:2]
        assert {post['args'][1] for post in alerts} == {address, 'director@fixture'}
        for post in alerts:
            assert post['args'][2] == f'qa: login {CHATGPT} stuck in walk {state["walk"]}'
            for text in (state['walk'], state['holder'], str(directory), state['logins'][CHATGPT],
                         unit, 'Pool: chatgpt.', "It counts against kind forgejo's cap until it is back"):
                assert text in post['body']
        assert posts[-1]['args'][1:3] == [state['starter'], f'qa: walk {state["walk"]} ended']
        assert CHATGPT in posts[-1]['body'] and unit in posts[-1]['body']
        state = lab.walk_states()[-1][1]
        assert state['alerts'] == {CHATGPT: {address: not refused, 'director@fixture': True}}
        assert state['attempts'][-1]['alerts'] == state['alerts']
        assert alive(pid) and not state['given']
        if not refused:
            lab.watch()
            assert lab.sent()[before:] == posts
        (directory / 'box/login').rename(state['logins'][CHATGPT])
        settled_watch(lab, unit)
        dead(pid)
        state = lab.walk_states()[-1][1]
        if refused:
            assert state['stage'] == 'ending' and state['released'] and state['given'] == [CHATGPT]
            assert state['alerts'][CHATGPT][address] is False
            # A saved delivery retries even while the run's stop cannot be confirmed.
            lab.configure(unit_query_failure=True, post_status={address: 3})
            lab.watch(extra={'QA_GIVE_BACK_SECONDS': '0'})
            state = lab.walk_states()[-1][1]
            assert state['alerts'][CHATGPT][address] is True
            assert state['attempts'][-1]['alerts'] == state['alerts']
            lab.configure(unit_query_failure=False)
            lab.watch()
        state = lab.walk_states()[-1][1]
        assert state['stage'] == 'ended' and state['given'] == [CHATGPT]
        if refused:
            assert state['attempts'][0] == previous and not previous.get('alerts')
        sent = lab.sent()[before:]
        assert sum(post['args'][1] == 'director@fixture' for post in sent) == 1
        assert sum(post['args'][1] == address for post in sent) == (3 if refused else 1)
        assert sum(post['args'][1] == state['starter'] for post in sent) == 1
        lab.watch()
        assert lab.sent()[before:] == sent



def a_stuck_walk_login_stays_held(lab):
    resting(lab, CHATGPT)
    lab.configure(logins_real=[CHATGPT])
    lab.walk('b0', '--login', CHATGPT, '--cap', '1', now='2026-10-27T10:00:00Z')
    directory, state = lab.walk_state()
    unit, pid = deployment(lab, directory, login=CHATGPT)
    executable(directory / 'give-back', 'raise SystemExit(1)\n')
    lab.watch(now='2026-10-27T10:01:01Z')
    state = lab.walk_state()[1]
    assert state['stage'] == 'ending' and not state['released'] and not state['given'] and alive(pid)
    config = json.loads((lab.root / 'tools.json').read_text())
    assert config['login_holders'][CHATGPT] == state['holder']
    alert, post = lab.sent()
    assert alert == stuck_posts(lab)[0]
    assert unit in post['body'] and state['logins'][CHATGPT] in post['body']
    assert post['args'][1] == state['starter']
    lab.walk('b0')
    assert lab.walk_states()[-1][1]['slot'] == 2
    (directory / 'box/login').rename(state['logins'][CHATGPT])
    settled_watch(lab, unit)
    state = lab.walk_states()[0][1]
    assert state['given'] == [CHATGPT] and state['released'] and state['stage'] == 'ended'
    dead(pid)
    assert len(lab.sent()) == 2
    lab.walk('b0')
    assert lab.walk_states()[-1][1]['slot'] == 1



def a_walk_fetch_is_bounded_before_taking_a_login(lab):
    lab.configure(hang={'cargo:fetch': 'before'})
    result = driven_walk(lab, "HUNG = {'cargo:fetch'}\n" + TIMEOUT_DRIVER,
                         '--build', 'main', status=4)
    assert lab.calls('cargo') == [['fetch', '--locked']]
    assert 'cannot fetch build main: command timed out' in result.stderr
    assert not any(args[0] == 'take' for args in lab.calls('logins'))
    assert not lab.calls('codex-run') and lab.walk_state()[1]['released']



def a_walk_in_place_login_waits_for_its_unknown_unit(lab):
    resting(lab, CLAUDE, in_place=True)
    lab.walk('b0', '--kind', 'claude', '--login', CLAUDE)
    directory, state = lab.walk_state()
    unit, pid = deployment(lab, directory)
    lab.configure(inactive=True, unit_states={unit: 'unknown'})
    lab.watch()
    state = lab.walk_state()[1]
    assert state['kinds'] == {CLAUDE: 'in-place'} and not state['given'] and not state['released']
    assert CLAUDE in lab.sent()[0]['body'] and unit in lab.sent()[0]['body']
    lab.configure(unit_states={})
    settled_watch(lab, unit)
    assert lab.walk_state()[1]['given'] == [CLAUDE] and lab.walk_state()[1]['stage'] == 'ended'
    dead(pid)



def a_pause_with_a_login_out_ends_stuck(lab):
    directory, state = walk_with_logins(lab, CHATGPT)
    unit, pid = deployment(lab, directory, login=CHATGPT)
    executable(directory / 'give-back', 'raise SystemExit(1)\n')
    state = pause_walk(lab, directory, state)
    assert state['decision'] == 'walk-end' and state['stage'] == 'ending' and not state['released']
    alert, post = lab.sent()
    assert alert == stuck_posts(lab)[0]
    assert post['args'][2] == 'qa: walk rung-b0-1 ended' and CHATGPT in post['body'] and unit in post['body']
    (directory / 'box/login').rename(state['logins'][CHATGPT])
    settled_watch(lab, unit)
    assert lab.walk_state()[1]['decision'] == 'walk-end' and lab.walk_state()[1]['stage'] == 'ended'
    assert len(lab.sent()) == 2
    dead(pid)



def a_paused_walk_resumes_at_a_branch_with_another_login(lab):
    lab.configure(pools={CHATGPT: [CHATGPT, 'chatgpt-2']})
    resting(lab, 'chatgpt-2')
    directory, state = walk_with_logins(lab, CHATGPT, cap=7)
    unit, pid = deployment(lab, directory, login=CHATGPT)
    kept = directory / 'box/data'
    kept.write_text('kept deployment data\n')
    state = pause_walk(lab, directory, state, settle=(unit,))
    previous = state['attempts'][0]
    assert state['deployments'] == [dict(name='box', unit=unit, argv=[str(directory / 'box/server')])]
    dead(pid)
    lab.env['QA_WALK_SLOTS'] = 'forgejo=2+1'
    lab.walk('other', '--login', CHATGPT)
    fix = lab.commit('fix before landing', branch='fix')
    report = (directory / 'report.md').read_bytes()
    lab.run('walk', 'fabrig', 'b0', '--resume', 'rung-b0-1', '--build', 'origin/fix', now='2026-10-27T09:00:00Z')
    resumed = next(saved for _, saved in lab.walk_states() if saved['walk'] == state['walk'])
    assert resumed['walk'] == state['walk'] and resumed['attempt'] == 2 and len(resumed['attempts']) == 2
    assert resumed['attempts'][0] == previous and resumed['run'] != state['run']
    assert resumed['pools'] == {CHATGPT: 'chatgpt-2'} and resumed['slot'] == 1
    assert resumed['main'] == fix and resumed['cap'] == 7 and resumed['started'] == '2026-10-27T09:00:00Z'
    assert lab.git(lab.slots / '1', 'rev-parse', 'HEAD') == fix
    assert not (directory / 'paused').exists() and not (directory / 'give-back').exists()
    assert (directory / 'report-1.md').read_bytes() == report and kept.read_text() == 'kept deployment data\n'
    task = (directory / 'task.md').read_text()
    assert all(word in task for word in (state['pause_line'], str(directory / 'box/server'),
        str(directory / 'box'), resumed['logins']['chatgpt-2'], 'report-1.md', 'notes.md',
        'configuration', 'stored family', 'fresh deployment', 'main at the landed commit'))
    call = lab.calls('codex-run')[-1]
    assert call[:6] == ['task', '--resume', state['run'], '--to', 'qa-watch', '--on-stop']
    assert call[-3:] == [str(directory / 'task.md'), str(lab.slots / '1'), str(directory / 'report.md')]
    lab.watch(now='2026-10-27T09:06:59Z')
    current = next(saved for _, saved in lab.walk_states() if saved['walk'] == state['walk'])
    assert current['stage'] == 'running' and not current['capped']
    lab.end_run(current, report='Fix confirmed at the branch.\n')
    lab.watch()
    current = next(saved for _, saved in lab.walk_states() if saved['walk'] == state['walk'])
    assert current['stage'] == 'ended' and current['given'] == ['chatgpt-2'] and current['attempts'][0] == previous
    assert lab.calls('logins').count(['give', CHATGPT, '--as', state['holder']]) == 1
    rows = (directory.parent / 'b0/loop.tsv').read_text().splitlines()
    assert [row.split('\t')[3] for row in rows[1:]] == ['walk-start', 'walk-pause', 'walk-resume', 'walk-end']



def a_refused_walk_deployment_preserves_its_saved_command(lab):
    directory, state = walk_with_logins(lab)
    unit, pid = deployment(lab, directory)
    command = [dict(name='box', unit=unit, argv=[str(directory / 'box/server')])]
    lab.configure(deploy_failure=True)
    lab.run('deploy', str(directory), 'box', '--', '/bin/true', status=4)
    assert lab.walk_state()[1]['deployments'] == command and alive(pid)
    lab.run('deploy', str(directory), 'other', '--', '/bin/true', status=4)
    assert lab.walk_state()[1]['deployments'] == command
    os.killpg(pid, signal.SIGKILL)
    dead(pid)
    registry = directory / 'deployments'
    registry.unlink()
    registry.mkdir()
    lab.run('deploy', str(directory), 'box', '--', '/bin/true', status=2)
    assert lab.walk_state()[1]['deployments'] == command
    registry.rmdir()
    registry.write_bytes(b'\xff')
    lab.run('deploy', str(directory), 'box', '--', '/bin/true', status=4)
    assert lab.walk_state()[1]['deployments'] == command
    registry.write_text(unit + '\n')
    lab.run('deploy', str(directory), 'box', '--', '/bin/true', status=4,
            extra={'QA_SYSTEMD_RUN': str(lab.root / 'missing-manager')})
    assert lab.walk_state()[1]['deployments'] == command
    state = pause_walk(lab, directory, lab.walk_state()[1])
    dead(pid)
    lab.configure(deploy_failure=False)
    lab.run('walk', 'fabrig', 'b0', '--resume', 'rung-b0-1', '--build', 'main')
    task = (directory / 'task.md').read_text()
    assert str(directory / 'box/server') in task and '/bin/true' not in task



def a_surviving_launcher_keeps_custody_past_the_grace(lab):
    a_surviving_launcher_keeps_custody_until_its_unit_exists(lab, past_grace=True)



def an_orphan_manual_take_keeps_its_admission_lock(lab):
    orphaned_take_keeps_admission(lab, 'take')



def an_orphan_walk_take_keeps_its_admission_lock(lab):
    orphaned_take_keeps_admission(lab, 'walk')



def an_orphan_resume_take_keeps_its_admission_lock(lab):
    orphaned_take_keeps_admission(lab, 'resume')



def hung_manual_inventory_and_takes_are_bounded(lab):
    for operation in ('list', 'take'):
        lab.configure(hang={'logins:' + operation: 'before'})
        driver = (f'import runpy, sys\ntool = runpy.run_path({str(SCRIPT)!r})\n'
                  + f'HUNG = ("logins:{operation}",)\n' + TIMEOUT_DRIVER
                  + '\nsys.exit(tool["main"]())\n')
        result = subprocess.run([sys.executable, '-I', '-B', '-c', driver, 'take', 'forgejo',
                                 '--as', 'walk/forgejo/manual'], env=lab.env, cwd=lab.root,
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, timeout=HUNG_TOOL_S)
        assert result.returncode == 1, (result.stdout, result.stderr)
        expected = 'cannot read login inventory' if operation == 'list' else 'the caps are broken: command timed out'
        assert expected in result.stderr
        dead(int((lab.root / 'hung-tool').read_text()))
    assert not lab.walk_states() and not lab.watch_states()



def a_surviving_launcher_keeps_custody_until_its_unit_exists(lab, past_grace=False, loaded=False):
    resting(lab, CHATGPT, in_place=True)
    lab.env['QA_WALK_SLOTS'] = 'forgejo=1 claude=3,4'
    lab.env['QA_WALK_KINDS'] = 'forgejo=1:chatgpt'
    focused = lab.tmp / 'qa-focused'
    focused.mkdir()
    (focused / 'rung-b0-brief.md').write_text('Delayed launch fixture.\n')
    lab.configure(delay_before_unit=True, logins_real=[CHATGPT], close_admission=True)
    with (lab.root / 'starter-output').open('w') as output:
        starter = subprocess.Popen([str(SCRIPT), 'walk', 'fabrig', 'b0', '--login', CHATGPT],
                                   env=lab.env, cwd=lab.root, stdin=subprocess.DEVNULL,
                                   stdout=output, stderr=output)
        child = None
        try:
            waiting = lab.root / 'launch-waiting'
            wait_for(waiting.exists)
            child = int(waiting.read_text())
            if past_grace:
                os.kill(child, signal.SIGSTOP)
            directory, state = lab.walk_state()
            assert state['stage'] == 'starting' and not state['run']
            os.kill(starter.pid, signal.SIGKILL)  # Only the starter; codex-run owns another session.
            assert starter.wait(timeout=10) == -signal.SIGKILL and alive(child)
            now = None
            if past_grace:
                meta = lab.tmp / 'codex-run/fixture-1/meta'
                now = (datetime.fromtimestamp(meta.stat().st_mtime, timezone.utc)
                       + timedelta(minutes=11)).strftime('%Y-%m-%dT%H:%M:%SZ')
            if loaded:
                lab.configure(unit_load='loaded', unit_state='inactive')
            result = lab.watch(now=now)
            state = lab.walk_state()[1]
            assert 'launch may still start' in result.stdout
            assert state['run'] == 'fixture-1' and state['stage'] == 'running'
            assert not state['given'] and not state['released']
            lab.walk('b0', '--login', CHATGPT)
            lab.run('queue', 'cancel', queued_entries(lab)[0]['id'])
            assert not any(args[0] == 'give' for args in lab.calls('logins'))
            (lab.root / 'allow-launch').touch()
            if past_grace:
                os.kill(child, signal.SIGCONT)
            wait_for((lab.tmp / 'codex-run/fixture-1/unit').exists)
            dead(child)
            lab.configure(unit_load='loaded', unit_state='active')
            lab.watch()
            saved = json.loads((lab.tmp / 'qa/walks' / (state['walk'] + '.json')).read_text())
            assert saved['stage'] == 'running' and not saved['given'] and not saved['released']
            lab.end_run(saved)
            lab.configure(unit_state='inactive')
            lab.watch()
            saved = json.loads((lab.tmp / 'qa/walks' / (state['walk'] + '.json')).read_text())
            assert saved['stage'] == 'ended' and saved['given'] == [CHATGPT] and saved['released']
            assert len(lab.calls('codex-run')) == 1
        finally:
            (lab.root / 'allow-launch').touch()
            if starter.poll() is None:
                starter.kill()
                starter.wait(timeout=10)
            if child is not None:
                if alive(child):
                    os.kill(child, signal.SIGCONT)
                dead(child)



def a_loaded_inactive_unit_keeps_a_surviving_launcher(lab):
    a_surviving_launcher_keeps_custody_until_its_unit_exists(lab, past_grace=True, loaded=True)



def hex_walk_builds_refuse_ambiguous_and_non_commit_objects(lab):
    seen = {}
    for number in range(10000):
        body = f'collision fixture {number}\n'.encode()
        sha = hashlib.sha1(b'blob ' + str(len(body)).encode() + b'\0' + body).hexdigest()
        if sha[:4] in seen:
            first_sha, first_body = seen[sha[:4]]
            break
        seen[sha[:4]] = sha, body
    else:
        assert False, 'fixture did not find a four-digit object collision'
    origin = lab.origins / 'fabrig.git'
    for tag, expected, data in (('collision-one', first_sha, first_body), ('collision-two', sha, body)):
        result = subprocess.run(['git', '-C', str(origin), 'hash-object', '-w', '--stdin'],
                                input=data, env=lab.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                timeout=HUNG_TOOL_S)
        assert result.returncode == 0 and result.stdout.decode().strip() == expected, result.stderr
        lab.git(origin, 'tag', tag, expected)
    lab.git(origin, 'tag', 'origin/main', sha)
    # A hexadecimal tag must not redirect a commit's prefix either.
    commit = lab.git(origin, 'rev-parse', 'HEAD')
    lab.git(origin, 'tag', commit[:9], sha)
    for ref in (sha[:4], sha, first_sha):
        result = lab.walk('b0', '--build', ref, '--login', CHATGPT, status=2)
        assert 'try origin/<branch> or a commit' in result.stderr
    assert not lab.calls('codex-run') and all(row == ['list'] for row in lab.calls('logins'))
    assert all(s['released'] and s['slot_claim']['released'] for _, s in lab.walk_states())
    lab.walk('b0', '--build', commit[:9].upper())
    state = next(state for _, state in lab.walk_states() if state['run'])
    assert state['main'] == commit



def an_unresolvable_build_takes_nothing(lab):
    for ref in ('nosuch', 'origin/missing', 'HEAD~1', '../main', 'bad..branch', 'abc', '1234'):
        result = lab.walk('bad-ref', '--build', ref, '--login', CHATGPT, status=2)
        assert result.stderr == (f'qa: build {ref}: no branch origin/{ref} and no commit; '
                                 'try origin/<branch> or a commit\n')
    assert all(row == ['list'] for row in lab.calls('logins')) and not lab.calls('codex-run')
    assert all(s['released'] and s['slot_claim']['released'] for _, s in lab.walk_states())
    assert not (lab.tmp / 'qa/repos').exists()
    assert not list((lab.tmp / 'qa/repos').glob('fabrig-walk-*'))
    assert not list((lab.tmp / 'qa-focused').glob('*/loop.tsv'))
    assert all(not s['run'] for _, s in lab.walk_states())
    lab.walk('b0', '--login', CHATGPT)
    directory, state = next((d, s) for d, s in lab.walk_states() if s['run'])
    pause_walk(lab, directory, state)
    saved = lab.tmp / 'qa/walks' / (state['walk'] + '.json')
    paths = [saved, directory / 'paused', directory / 'report.md', directory / 'notes.md',
             directory.parent / 'b0/loop.tsv']
    before = [path.read_bytes() for path in paths]
    takes = [row for row in lab.calls('logins') if row[0] == 'take']
    slots = lab.git(lab.slots / '1', 'worktree', 'list', '--porcelain')
    result = lab.run('walk', 'fabrig', 'b0', '--resume', state['walk'], '--build', 'nosuch', status=2)
    assert 'try origin/<branch> or a commit' in result.stderr
    assert [row for row in lab.calls('logins') if row[0] == 'take'] == takes and len(lab.calls('codex-run')) == 1
    assert [path.read_bytes() for path in paths[1:]] == before[1:]
    current = json.loads(saved.read_text())
    assert current['stage'] == 'paused' and current['attempt'] == 2 and current['slot_claim']['released']
    assert lab.git(lab.slots / '1', 'worktree', 'list', '--porcelain') == slots
    assert len([s for _, s in lab.walk_states() if s['run']]) == 0 and not (directory / 'report-1.md').exists()



def an_ambiguous_build_is_refused(lab):
    commit = lab.marked()
    fix = lab.commit('branch with a hexadecimal name', branch=commit[:9])
    result = lab.walk('b0', '--build', commit[:9], '--login', CHATGPT, status=2)
    assert 'ambiguous branch and commit' in result.stderr
    assert 'origin/' + commit[:9] in result.stderr and 'full commit ' + commit in result.stderr
    assert all(row == ['list'] for row in lab.calls('logins')) and not lab.calls('codex-run')
    assert all(s['released'] and s['slot_claim']['released'] for _, s in lab.walk_states())
    assert not (lab.tmp / 'qa/repos').exists()
    assert not list((lab.tmp / 'qa/repos').glob('fabrig-walk-*'))
    assert not list((lab.tmp / 'qa-focused').glob('*/loop.tsv'))
    lab.walk('b0', '--build', 'origin/' + commit[:9])
    lab.walk('b0', '--build', commit)
    first, second = [(d, s) for d, s in lab.walk_states() if s['run']]
    assert first[1]['main'] == fix and second[1]['main'] == commit



def a_stuck_login_alerts_the_director_and_the_list(lab):
    path = lab.home / '.config/agents-qa/stuck'
    path.parent.mkdir(parents=True)
    path.write_bytes(b'design/upgrades-draft@fixture\n# recovery team\n\ndirector@fixture\nnot an address\n\xff\n')
    directory, state = start_stuck_pass(lab, CHATGPT)
    unit, pid = deployment(lab, directory)
    result = driven_watch(lab, """import json
original = tool['Watch'].call
def call(self, name, *args):
    if name == 'post' and args[0] == 'send':
        saved = json.loads((self.directory / 'walks' / (PASS + '.json')).read_text())
        receipts = saved['alerts']['chatgpt']
        if str(args[-2]).startswith('qa: login '):
            assert set(receipts) == {'director@fixture', 'design/upgrades-draft@fixture'}
            assert receipts[args[-3]] is False
        else:
            assert all(receipts.values())
    return original(self, name, *args)
tool['Watch'].call = call
""".replace('PASS', repr(state['walk'])))
    alerts = stuck_posts(lab)
    recipients = {'director@fixture', 'design/upgrades-draft@fixture'}
    assert len(alerts) == 2 and {post['args'][1] for post in alerts} == recipients
    assert result.stdout.count('invalid stuck address; skipped') == 2
    assert lab.sent()[:2] == alerts and lab.sent()[2]['args'][2].startswith('qa: walk ')
    for post in alerts:
        assert post['args'][2] == f'qa: login {CHATGPT} stuck in walk {state["walk"]}'
        for text in (CHATGPT, state['logins'][CHATGPT], str(directory), unit,
                     "It counts against kind forgejo's cap until it is back"):
            assert text in post['body']
    assert lab.watch_state()[1]['alerts'] == {CHATGPT: dict.fromkeys(recipients, True)}
    lab.watch()
    assert len(lab.sent()) == 3 and alive(pid)
    assert all(call[1:3] == ['--as', 'qa-watch'] for call in lab.calls('post') if call[0] == 'send')



def legacy_repository_walks_are_opaque_and_count_for_numbering(lab):
    lab.walk('a')
    directory, state = lab.walk_state()
    lab.end_run(state)
    lab.watch()
    parent = lab.tmp / 'qa/walks'
    for number, repo, stage in ((8, 'temper', 'running'), (9, 'jig', 'paused'), (11, 'temper', 'ended')):
        foreign = dict(state, walk=f'rung-a-{number}', repo=repo, stage=stage, clock_walk=str(number),
                       holder=f'walk/forgejo/rung-a-{number}', logins={'chatgpt-2': str(lab.root / 'foreign-rest')},
                       given=[], attempts=[])
        (parent / (foreign['walk'] + '.json')).write_text(json.dumps(foreign))
    originals = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in parent.glob('*.json')}
    lab.configure(logins_held=['chatgpt-2'], login_holders={'chatgpt-2': 'walk/forgejo/rung-a-11'})
    lab.walk('a')
    current = lab.walk_states()[-1][1] if lab.walk_states()[-1][1]['repo'] == 'fabrig' else next(
        state for _, state in lab.walk_states() if state['walk'] == 'rung-a-12')
    assert current['walk'] == 'rung-a-12' and current['slot'] == 1
    lab.end_run(current)
    lab.watch()
    lab.run('walk', 'fabrig', 'a', '--resume', 'rung-a-9', '--build', 'main', status=2)
    for path, original in originals.items():
        assert (path.read_bytes(), path.stat().st_mtime_ns) == original
    assert not any(call[0] == 'give' and call[1] == 'chatgpt-2' for call in lab.calls('logins'))
    assert json.loads((lab.root / 'tools.json').read_text())['login_holders']['chatgpt-2'] == 'walk/forgejo/rung-a-11'



def watch_wait_outlasts_the_post_cap_and_reads_mail_promptly(lab):
    # Scale only mailbox time: 120 s becomes 1.2 s, the old cap 0.6 s.
    # Keep real subprocess deadlines and an independently delivered mailbox file.
    lab.env['QA_INTERVAL_SECONDS'] = '120'
    lab.configure(wait=[1, 0, 4], wait_scale=0.01)

    def deliver():
        marker = lab.root / 'wait-started-1'
        deadline = time.monotonic() + 10
        while not marker.exists():
            assert time.monotonic() < deadline, 'second mailbox wait never started'
            time.sleep(0.01)
        time.sleep(0.8)
        path = lab.root / 'mail-delivered'
        temporary = path.with_suffix('.new')
        temporary.write_text(str(time.monotonic()))
        temporary.replace(path)

    with ThreadPoolExecutor(max_workers=1) as pool:
        delivery = pool.submit(deliver)
        result = driven_watch(lab, """original = tool['main'].__globals__['command']
def command(argv, cwd=None, timeout=None, pass_fds=(), **kwargs):
    if str(argv[0]).endswith('/post'):
        if argv[1] == 'wait':
            interval = int(argv[argv.index('--timeout') + 1])
            # Preserve command grace for process startup under suite load.
            timeout = min(timeout, interval) * 0.01 + max(0, timeout - interval)
        else:
            assert timeout == 60, (argv, timeout)
    return original(argv, cwd=cwd, timeout=timeout, pass_fds=pass_fds, **kwargs)
tool['main'].__globals__['command'] = command
# Also scale the failure backoff, so the broken implementation fails promptly.
sleep = tool['time'].sleep
tool['time'].sleep = lambda seconds: sleep(seconds * 0.01 if seconds == 120 else seconds)
""", once=False, status=2)
        delivery.result()
    assert 'post wait failed' not in result.stdout, result.stdout
    assert 'fixture end mail' in result.stdout
    assert float((lab.root / 'wait-elapsed').read_text()) >= 1.2
    assert float((lab.root / 'mail-read-delay').read_text()) < 0.4
    assert [call[0] for call in lab.calls('post')] == ['wait', 'wait', 'read', 'wait']



def a_hung_systemctl_bounds_the_check(lab):
    first, unit, pid, second, other_unit, other_pid = finished_pair(lab)
    bounded = """import time
from pathlib import Path
subprocess = tool['subprocess']
original_popen = subprocess.Popen
class ReadyPopen(original_popen):
    def communicate(self, input=None, timeout=None):
        if timeout == 0.3:
            marker = Path(tool['os'].environ['QA_FIXTURE']) / ('hung-' + OWNER)
            deadline = time.monotonic() + 10
            while not (marker.exists() and marker.read_text().split()[:1] == [str(self.pid)]):
                if self.poll() is not None or time.monotonic() >= deadline:
                    self.kill()
                    super().communicate()
                    raise AssertionError('fixture manager never reached its hang')
                time.sleep(0.01)
        return super().communicate(input=input, timeout=timeout)
subprocess.Popen = ReadyPopen
original = tool['command']
def command(argv, cwd=None, timeout=None, pass_fds=(), **kwargs):
    if str(argv[0]).endswith('/systemctl'):
        assert timeout == 30
        config = tool['json'].loads((Path(tool['os'].environ['QA_FIXTURE']) / 'tools.json').read_text())
        if any(argv[2] == operation and str(argv[-1]).startswith('qa-' + owner + '-')
               for owner, operation in config.get('hung_systemctl', {}).items()):
            timeout = 0.3
    return original(argv, cwd=cwd, timeout=timeout, pass_fds=pass_fds, **kwargs)
tool['main'].__globals__['command'] = command
"""
    bounded = 'OWNER = ' + repr(first.name) + '\n' + bounded
    for operation in ('list-units', 'show'):
        lab.configure(hung_systemctl={first.name: operation})
        result = driven_watch(lab, bounded)
        saved = next(state for _, state in lab.walk_states() if state['walk'] == first.name)
        assert saved['given'] == [CHATGPT] and alive(pid)
        assert CLAUDE in json.loads((lab.root / 'tools.json').read_text())['logins_held']
        for process in map(int, (lab.root / ('hung-' + first.name)).read_text().split()):
            dead(process)
        expected = 'units unknown' if operation == 'list-units' else 'cannot establish unit state'
        assert expected in result.stdout
    dead(other_pid)
    wait_for(lambda: not (lab.root / 'units' / (other_unit + '.json')).exists())
    lab.configure(hung_systemctl={})
    settled_watch(lab, unit)
    dead(pid)
    assert all(state['stage'] == 'ended' for _, state in lab.walk_states())



def one_walk_failing_its_end_lets_the_check_go_on(lab):
    first, unit, pid, second, other_unit, other_pid = finished_pair(lab)
    marker = 'outside-' + 'exception-contents'
    patch = f"""original = tool['Watch'].end
def end(self, directory, state):
    if state['walk'] == {first.name!r}:
        raise OSError({marker!r})
    return original(self, directory, state)
tool['Watch'].end = end
"""
    result = driven_watch(lab, patch)
    assert first.name in result.stdout and 'OSError' in result.stdout and marker not in result.stdout + result.stderr
    assert first.exists() and alive(pid) and not lab.walk_states()[0][1]['given']
    dead(other_pid)
    wait_for(lambda: not (lab.root / 'units' / (other_unit + '.json')).exists())
    assert not (lab.root / 'units' / (other_unit + '.json')).exists()



def a_walk_never_stops_its_successors_unit(lab):
    first, state = deployment_pass(lab)
    unit, pid = deployment(lab, first)
    lab.walk('b1')
    second, _ = lab.walk_states()[1]
    successor, other_pid = deployment(lab, second)
    lab.end_run(state)
    lab.watch()
    dead(pid)
    assert alive(other_pid)
    assert ['--user', 'stop', '--no-block', '--', unit] in lab.calls('systemctl')
    assert not any(successor in call for call in lab.calls('systemctl'))
    before = (first / 'deployments').read_bytes()
    lab.run('deploy', str(first), '2-box', '--', 'true', status=2)
    assert (first / 'deployments').read_bytes() == before



def an_edited_deployments_trace_never_controls_custody(lab):
    variants = ('deleted', 'empty', 'foreign', 'link', 'directory', 'fifo', 'hardlink')
    for variant in variants:
        lab.env['QA_WALK_KINDS'] = 'forgejo=2:claude'
        if not (lab.root / 'login-store' / CLAUDE / 'login').exists():
            resting(lab, CLAUDE, in_place=True)
        lab.configure(logins_real=[CLAUDE])
        lab.walk(variant)
        directory, state = next((directory, state) for directory, state in lab.walk_states()
                                if state['rung'] == variant)
        unit, pid = deployment(lab, directory)
        outside = lab.root / ('outside-' + variant)
        outside.write_text('outside trace')
        registry = directory / 'deployments'
        registry.unlink()
        if variant == 'empty': registry.touch()
        elif variant == 'foreign': registry.write_text('codex-run-foreign\nqa-other-box\n')
        elif variant == 'link': registry.symlink_to(outside)
        elif variant == 'directory': registry.mkdir()
        elif variant == 'fifo': os.mkfifo(registry)
        elif variant == 'hardlink': os.link(outside, registry)
        lab.end_run(state)
        lab.watch()
        dead(pid)
        wait_for(lambda: not (lab.root / 'units' / (unit + '.json')).exists())
        lab.watch()
        current = next(state for _, state in lab.walk_states() if state['walk'] == directory.name)
        assert current['given'] == [CLAUDE] and current['released']
        assert outside.read_text() == 'outside trace'
        calls = list(map(json.loads, (lab.root / 'tools.jsonl').read_text().splitlines()))
        give = max(i for i, row in enumerate(calls) if row['tool'] == 'logins' and row['args'][:2] == ['give', CLAUDE])
        stop = max(i for i, row in enumerate(calls) if row['tool'] == 'systemctl' and row['args'] == ['--user', 'stop', '--no-block', '--', unit])
        show = max(i for i, row in enumerate(calls[:give]) if row['tool'] == 'systemctl' and row['args'][1] == 'show' and row['args'][-1] == unit)
        assert stop < show < give



def a_walk_with_no_login_stops_its_units(lab):
    directory, state = deployment_pass(lab)
    result = subprocess.run([str(lab.root / 'logins'), 'give', CHATGPT, '--as', state['holder']],
                            env=lab.env, capture_output=True, text=True, timeout=HUNG_TOOL_S)
    assert result.returncode == 0, result.stderr
    state.update(logins={}, kinds={}, pools={}, given=[], run_recorded=[])
    write_walk(lab, state)
    unit, pid = deployment(lab, directory)
    lab.end_run(state)
    settled_watch(lab, unit)
    dead(pid)
    assert lab.walk_state()[1]['stage'] == 'ended'



def claim_release_waits_for_session_and_deployment_stop(lab):
    lab.walk()
    directory, state = lab.walk_state()
    unit, pid = deployment(lab, directory)
    lab.end_run(state)
    lab.configure(unit_job='77')
    lab.watch()
    assert not [c for c in lab.calls('claim') if c[0] == 'release']
    lab.configure(unit_job='0', inactive=True, unit_states={unit: 'unknown'})
    lab.watch()
    assert not [c for c in lab.calls('claim') if c[0] == 'release']
    assert slot_claims(lab) and lab.walk_state()[1]['given'] == [CHATGPT]
    lab.configure(unit_states={})
    settled_watch(lab, unit)
    assert lab.walk_state()[1]['slot_claim']['released'] and not slot_claims(lab)
    dead(pid)



def local_and_remote_claims_are_bounded_and_unknown_acceptance_is_alerted(lab):
    for remote, when in (('', 'before'), ('claims@hel8', 'after')):
        lab.env['QA_CLAIM_SSH'] = remote
        lab.configure(hang={'claim:claim': when})
        result = driven_walk(lab, "HUNG = {'claim:claim', 'ssh:-o'}\n" + TIMEOUT_DRIVER.replace("if operation in HUNG:", "if operation in HUNG and not (name == 'ssh' and \"'list'\" in str(argv[-1])):"),
                             status=1)
        assert 'exit 124' in result.stderr
        assert not lab.calls('cargo') and not lab.calls('codex-run')
        assert all(state['slot'] is None for _, state in lab.walk_states())
        lab.configure(hang={})
        lab.watch()
        assert bool(slot_claims(lab)) == (when == 'after')
        assert not [c for c in lab.calls('claim') if c[0] == 'release']



def remote_release_timeout_keeps_successors_on_retry(lab):
    lab.env['QA_CLAIM_SSH'] = 'claims@hel8'
    lab.walk()
    lab.configure(inactive=True, hang={'claim:release': 'after'})
    # Only remote release is shortened; other SSH operations retain the real 60-second bound.
    patch = TIMEOUT_DRIVER.replace("if operation in HUNG:", "if operation in HUNG and 'release' in str(argv[-1]):")
    driven_watch(lab, "HUNG = {'ssh:-o'}\n" + patch)
    assert not slot_claims(lab)
    current = lab.walk_state()[1]
    assert current['slot_claim']['release_status'] == 'release unconfirmed'
    assert 'exit 124' in current['slot_claim']['release_result']
    hold_slot(lab, 1, what='a newer claim')
    lab.configure(hang={})
    lab.watch()
    lab.watch()
    assert slot_claims(lab)['1']['what'] == 'a newer claim'
    assert len([c for c in lab.calls('claim') if c[0] == 'release']) == 1
    assert len([m for m in lab.sent() if 'slot release unconfirmed' in m['args'][2]]) == 1



def a_launcher_without_metadata_keeps_custody_and_admission(lab):
    lab.configure(delay_before_meta=True)
    brief = lab.tmp / 'qa-focused/rung-b0-brief.md'
    brief.parent.mkdir(parents=True)
    brief.write_text('Early launcher fixture.\n')
    with (lab.root / 'starter-output').open('w') as output:
        starter = subprocess.Popen([str(SCRIPT), 'walk', 'fabrig', 'b0'], env=lab.env,
                                   stdin=subprocess.DEVNULL, stdout=output, stderr=output)
        child = None
        try:
            wait_for((lab.root / 'meta-waiting').exists)
            child = int((lab.root / 'meta-waiting').read_text())
            directory, state = lab.walk_state()
            assert state['stage'] == 'starting' and not state['run']
            assert not list((lab.tmp / 'codex-run').glob('*/meta'))
            starter.kill()
            assert starter.wait(timeout=10) == -signal.SIGKILL and alive(child)
            future = (datetime.fromisoformat(state['started'].replace('Z', '+00:00'))
                      + timedelta(minutes=11)).strftime('%Y-%m-%dT%H:%M:%SZ')
            before = (datetime.fromisoformat(state['started'].replace('Z', '+00:00'))
                      + timedelta(seconds=599)).strftime('%Y-%m-%dT%H:%M:%SZ')
            lab.watch(now=before)
            assert not lab.sent()
            custody = (lab.tmp / 'qa/walks' / (state['walk'] + '.json')).read_bytes()
            calls = {name: lab.calls(name) for name in ('claim', 'logins', 'systemctl', 'codex-run')}
            lab.watch(now=future, extra={'QA_POST_STATUS': '2'})
            notice, = lab.sent()
            assert notice['args'][1:3] == ['director@fixture', f'qa: overdue launch for {state["walk"]}']
            assert f'Walk {state["walk"]}, attempt 1' in notice['body']
            assert '660 seconds' in notice['body'] and 'descriptor held' in notice['body']
            receipt, = (lab.tmp / 'qa/attention').glob('*.json')
            saved_receipt = json.loads(receipt.read_text())
            assert saved_receipt['attempted'] and saved_receipt['result'] == 'exit 2'
            assert saved_receipt['body'] == notice['body']
            lab.watch(now=future)  # A failed post retries despite the busy admission lock.
            assert lab.sent() == [notice, notice]
            lab.watch(now=future)
            assert lab.sent() == [notice, notice]
            assert (lab.tmp / 'qa/walks' / (state['walk'] + '.json')).read_bytes() == custody
            assert {name: lab.calls(name) for name in calls} == calls
            saved = lab.walk_state()[1]
            assert saved['stage'] == 'starting' and not saved['given'] and not saved['released']
            assert slot_claims(lab) and not [c for c in lab.calls('claim') if c[0] == 'release']
            with (lab.tmp / 'qa/walks.lock').open('a') as probe:
                try:
                    fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    pass
                else:
                    raise AssertionError('launcher did not inherit admission exclusion')
            (lab.root / 'allow-meta').touch()
            wait_for((lab.tmp / 'codex-run/fixture-1/unit').exists)
            dead(child)
            lab.watch()
            saved = lab.walk_state()[1]
            assert saved['run'] == 'fixture-1' and not saved['given']
            lab.end_run(saved)
            lab.watch()
            assert lab.walk_state()[1]['slot_claim']['released']
        finally:
            (lab.root / 'allow-meta').touch()
            if starter.poll() is None:
                starter.kill()
                starter.wait(timeout=10)
            if child is not None:
                dead(child)



def claim_lifetimes_remain_unique_when_names_attempts_and_times_repeat(lab):
    repeated_claim_lifetimes(lab)



def new_claim_lifetimes_get_distinct_release_alerts(lab):
    repeated_claim_lifetimes(lab, refused=True)



def clean_unpublished_slot_heads_are_preserved_and_named(lab):
    checkout = lab.slots / '1'
    for rung, branch in (('detached', None), ('branch', 'private-work')):
        if branch:
            lab.git(checkout, 'switch', '-c', branch)
        else:
            lab.git(checkout, 'switch', '--detach')
        lab.git(checkout, 'commit', '--allow-empty', '-m', 'unpublished fixture work ' + rung)
        head = lab.git(checkout, 'rev-parse', 'HEAD')
        result = lab.walk(rung, status=4)
        assert head in result.stderr and 'unpublished' in result.stderr
        assert lab.git(checkout, 'rev-parse', 'HEAD') == head
        assert not lab.calls('cargo') and not lab.calls('trim') and not lab.calls('codex-run')
        assert not [c for c in lab.calls('logins') if c[0] == 'take']
        assert not slot_claims(lab)
    assert all(state['slot_claim']['released'] for _, state in lab.walk_states())



def only_the_last_saved_walk_checkout_can_authorize_an_unpublished_head(lab):
    old = lab.commit('first temporary branch', branch='temporary-one')
    lab.walk('one', '--build', 'temporary-one')
    first = lab.walk_state()[1]
    lab.end_run(first)
    lab.watch()
    lab.git(lab.products['fabrig'], 'push', 'origin', ':temporary-one')
    # The previous walk's detached commit is now unpublished but still ours.
    lab.walk('two', '--build', 'main')
    second = lab.walk_states()[1][1]
    lab.end_run(second)
    lab.watch()
    checkout = lab.slots / '1'
    lab.git(checkout, 'switch', '--detach', old)
    # That earlier commit is not the slot's last saved checkout any more.
    result = lab.walk('three', status=4)
    assert old in result.stderr and lab.git(checkout, 'rev-parse', 'HEAD') == old
    assert len(lab.calls('codex-run')) == 2 and not slot_claims(lab)



def an_after_resume_builds_main_only_after_every_commit_lands(lab):
    directory, state = walk_with_logins(lab, CHATGPT)
    state = pause_walk(lab, directory, state)
    first = lab.commit('first fix', branch='fix')
    second = lab.commit('second fix', branch='fix')
    result = lab.run('walk', 'fabrig', 'b0', '--resume', state['walk'], '--after', first, '--after', second)
    assert 'queued ' + state['walk'] in result.stdout
    assert lab.walk_state()[1]['attempt'] == 1
    lab.watch()
    assert len(lab.calls('codex-run')) == 1
    checkout = lab.products['fabrig']
    lab.git(checkout, 'switch', 'main')
    lab.git(checkout, 'merge', '--ff-only', first)
    lab.git(checkout, 'push', 'origin', 'main')
    lab.watch()
    assert len(lab.calls('codex-run')) == 1
    lab.git(checkout, 'merge', '--ff-only', second)
    tip = lab.commit('main advanced after fixes', branch='main')
    lab.watch()
    resumed = lab.walk_state()[1]
    assert resumed['main'] == tip and resumed['ref'] == 'main' and resumed['attempt'] == 2
    assert not queued_entries(lab) and len(lab.calls('codex-run')) == 2
    lab.watch()
    assert len(lab.calls('codex-run')) == 2



def evidence_remote_is_append_only_and_retryable(lab):
    origin = lab.origins / 'qa.git'
    lab.git(lab.root, 'init', '--bare', str(origin))
    lab.env.update(QA_EVIDENCE_REMOTE=str(origin), QA_EVIDENCE_BRANCH='evidence')
    lab.walk()
    directory, state = lab.walk_state()
    lab.end_run()
    lab.watch()
    branch = lab.git(origin, 'rev-parse', 'evidence')
    path = 'walks/' + state['started'][:10] + '-' + state['walk']
    assert lab.git(origin, 'show', f'evidence:{path}/report.md') == '## Findings\nNone.'
    assert branch in lab.run('keep', state['walk']).stdout
    assert lab.git(origin, 'rev-parse', 'evidence') == branch
    lab.walk('b1')
    other_dir, other = lab.walk_states()[1]
    lab.end_run(other)
    # Receive refuses the push; the same scanned snapshot survives repair/retry.
    unavailable = origin.with_name('qa-offline.git')
    origin.rename(unavailable)
    lab.watch()
    assert lab.walk_states()[1][1]['slot_claim']['released']
    (other_dir / 'report.md').write_text('edited after waiting snapshot\n')
    unavailable.rename(origin)
    lab.watch()
    lab.git(origin, 'merge-base', '--is-ancestor', branch, 'evidence')
    path = 'walks/' + other['started'][:10] + '-' + other['walk']
    assert lab.git(origin, 'show', f'evidence:{path}/report.md') == '## Findings\nNone.'



def evidence_lost_push_ack_and_collision_preserve_saved_identity(lab):
    origin = lab.origins / 'qa.git'
    lab.git(lab.root, 'init', '--bare', str(origin))
    lab.env.update(QA_EVIDENCE_REMOTE=str(origin), QA_EVIDENCE_BRANCH='evidence')
    real_git = shutil.which('git')
    wrapper = lab.root / 'git'
    executable(wrapper, f'''import os, subprocess, sys
from pathlib import Path
result = subprocess.run([{real_git!r}, *sys.argv[1:]])
marker = Path({str(lab.root / 'interrupted-evidence-init')!r})
if 'remote' in sys.argv and 'add' in sys.argv and not marker.exists():
    marker.write_text('ready')
    os.kill(os.getppid(), 9)
sys.exit(1 if 'push' in sys.argv else result.returncode)
''')
    lab.walk()
    directory, state = lab.walk_state()
    lab.end_run()
    lab.watch(status=-9)
    assert not (lab.tmp / 'qa/evidence.git').exists()
    assert lab.walk_state()[1]['slot_claim']['released']
    lab.watch()
    preservation = lab.tmp / 'qa/preservation' / (state['walk'] + '.json')
    kept = json.loads(preservation.read_text())
    assert kept['status'] == 'kept' and kept['candidate'] == kept['commit']
    head = lab.git(origin, 'rev-parse', 'evidence')
    assert head == kept['commit']
    # The publication lane confirms exact saved trees, never a foreign occupied path.
    checkout = lab.root / 'evidence-edit'
    lab.git(lab.root, 'clone', '--branch', 'evidence', str(origin), str(checkout))
    (checkout / kept['destination'] / 'report.md').write_text('foreign bytes\n')
    lab.git(checkout, 'add', '.')
    lab.git(checkout, 'commit', '-m', 'fixture collision')
    wrapper.unlink()
    lab.git(checkout, 'push', 'origin', 'evidence')
    conflicting = lab.git(origin, 'rev-parse', 'evidence')
    kept.update(status='waiting')
    preservation.write_text(json.dumps(kept))
    result = lab.run('keep', state['walk'], status=1)
    assert 'occupied' in result.stderr
    assert lab.git(origin, 'rev-parse', 'evidence') == conflicting and directory.exists()



CASES = (
    a_deployment_that_exited_leaves_its_login_out,
    a_detached_pipe_cannot_hold_a_timed_out_command,
    a_failed_export_leaves_the_unit_up,
    a_failed_stop_is_tried_again,
    a_hung_systemctl_bounds_the_check,
    a_launcher_without_metadata_keeps_custody_and_admission,
    a_loaded_inactive_unit_keeps_a_surviving_launcher,
    a_pause_with_a_login_out_ends_stuck,
    a_paused_walk_resumes_at_a_branch_with_another_login,
    a_refused_walk_deployment_preserves_its_saved_command,
    a_restarted_service_goes_on,
    a_stopped_pass_gives_its_login_back,
    a_stuck_login_alerts_the_director_and_the_list,
    a_stuck_walk_login_alerts_the_director_and_the_list,
    a_stuck_walk_login_stays_held,
    a_surviving_launcher_keeps_custody_past_the_grace,
    a_surviving_launcher_keeps_custody_until_its_unit_exists,
    a_unit_of_another_directory_is_not_stopped,
    a_walk_fetch_is_bounded_before_taking_a_login,
    a_walk_in_place_login_waits_for_its_unknown_unit,
    a_walk_never_stops_its_successors_unit,
    a_walk_with_no_login_stops_its_units,
    a_wrapper_past_its_bound_is_ended,
    an_after_resume_builds_main_only_after_every_commit_lands,
    an_ambiguous_build_is_refused,
    an_edited_deployments_trace_never_controls_custody,
    an_in_place_login_waits_for_every_unit,
    an_orphan_manual_take_keeps_its_admission_lock,
    an_orphan_resume_take_keeps_its_admission_lock,
    an_orphan_walk_take_keeps_its_admission_lock,
    an_unresolvable_build_takes_nothing,
    claim_lifetimes_remain_unique_when_names_attempts_and_times_repeat,
    claim_release_waits_for_session_and_deployment_stop,
    clean_unpublished_slot_heads_are_preserved_and_named,
    deploy_records_then_starts_its_unit,
    deployments_names_only_its_own_units,
    evidence_lost_push_ack_and_collision_preserve_saved_identity,
    evidence_remote_is_append_only_and_retryable,
    hex_walk_builds_refuse_ambiguous_and_non_commit_objects,
    hung_manual_inventory_and_takes_are_bounded,
    legacy_repository_walks_are_opaque_and_count_for_numbering,
    local_and_remote_claims_are_bounded_and_unknown_acceptance_is_alerted,
    new_claim_lifetimes_get_distinct_release_alerts,
    one_walk_failing_its_end_lets_the_check_go_on,
    only_the_last_saved_walk_checkout_can_authorize_an_unpublished_head,
    remote_release_timeout_keeps_successors_on_retry,
    the_service_ends_a_walk_at_its_cap,
    two_stops_take_turns,
    watch_wait_outlasts_the_post_cap_and_reads_mail_promptly,
)


class PeriodicWalkTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.WalkTests.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.WalkTests.tearDownClass.__func__)
    child = classmethod(fixtures.WalkTests.child.__func__)
    cases = CASES
    script = Path(__file__).resolve()


for case in CASES:
    setattr(PeriodicWalkTests, "test_" + case.__name__, fixtures.test_method(case.__name__))


if __name__ == "__main__":
    if sys.argv[1:2] == ["--one"]:
        isolation = runpy.run_path(str(fixtures.KIT / "isolation.py"))
        isolation["run_one"](globals()[sys.argv[2]],
            lambda case, root, baseline: case(Lab(root, baseline)), Path(sys.argv[3]), "qa-periodic-")
    else:
        unittest.main(verbosity=2)
