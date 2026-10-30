#!/usr/bin/env python3
"""Offline QA gate: fresh state and scoped calls; process matrices are periodic."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import secrets
import select
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import runpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
import qa_test_support as support

KIT = Path(__file__).resolve().parent
SCRIPT = KIT / 'qa'
HUNG_TOOL_S = 60
P = '20261026-0915-fabrig'
CHATGPT = 'chatgpt'
CLAUDE = 'claude'
REAL = 'real-model'

# Exercise real stop deadlines but poll the fake manager at fixture speed.
# Only unit_stopped uses the shorter interval; CLI settings and timeout
# assertions still see production values and the real monotonic clock.
FAST_POLL = """import time
unit_stopped = tool['Watch'].unit_stopped
sleep = time.sleep
def fast_unit_stopped(self, *args, **kwargs):
    try:
        time.sleep = lambda seconds: sleep(min(seconds, 0.01))
        return unit_stopped(self, *args, **kwargs)
    finally:
        time.sleep = sleep
tool['Watch'].unit_stopped = fast_unit_stopped
"""

WATCH_TOOLS = r'''import json, os, sys, signal, time
from pathlib import Path
from datetime import datetime, timezone
root = Path(os.environ['QA_FIXTURE'])
args = sys.argv[1:]
name = Path(sys.argv[0]).name
with (root / 'tools.jsonl').open('a') as log:
    log.write(json.dumps(dict(tool=name, args=args, **({'cwd': os.getcwd()} if name == 'cargo' else {}))) + '\n')
config = json.loads((root / 'tools.json').read_text())
runs = root / 'tmp/codex-run'
units = root / 'units'

def publish_marker(name, value):
    path = root / name
    temporary = path.with_name(path.name + '.' + str(os.getpid()) + '.new')
    temporary.write_text(value)
    temporary.replace(path)

def hang(when):
    operation = name + ':' + (args[0] if args else '')
    if config.get('hang', {}).get(operation) == when:
        publish_marker('hung-tool', str(os.getpid()))
        time.sleep(600)

hang('before')

def alive(pid):
    try:
        return Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[0] != 'Z'
    except FileNotFoundError:
        return False

def stop_group(pid):
    try:
        os.killpg(pid, signal.SIGTERM)
        deadline = time.monotonic() + 0.5
        while alive(pid) and time.monotonic() < deadline:
            time.sleep(0.01)
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass

def end(run, report, code=0):
    state = runs / run
    meta = dict(line.split('=', 1) for line in (state / 'meta').read_text().splitlines())
    Path(meta['report']).write_text(report)
    ended = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    row = [run, 'qa-watch', meta['started'], ended, str(code), '1', meta['model'], meta['effort'], meta['task'], meta['report'], 'thread', '100/20/30', '0']
    with (runs / 'runs.tsv').open('a') as out:
        out.write('\t'.join(row) + '\n')
    (state / 'ended').touch()

if name == 'ssh':
    import shlex
    assert args[:2] == ['-o', 'BatchMode=yes'] and len(args) == 4, args
    if config.get('ssh_refusal'):
        sys.exit('fixture ssh unavailable')
    remote = shlex.split(args[3])
    assert remote[:2] == ['bash', '-lc'] and len(remote) == 3, remote
    words = shlex.split(remote[2])
    assert Path(words[0]).name == 'claim', words
    os.execv(words[0], words)
elif name == 'claim':
    path = root / 'claims.json'
    claims = json.loads(path.read_text()) if path.exists() else {}
    if args[0] == 'list':
        if config.get('claim_list_refusal'):
            sys.exit(1)
        if 'claim_list_lines' in config:
            print('\n'.join(config['claim_list_lines']))
            sys.exit(0)
        for number in range(1, 10):
            record = claims.get(str(number))
            prefix = f'hetzner6 {number} [s/qa]: '
            print(prefix + (f"{record['owner']}: {record['what']} (since 2026-10-29T00:00:00+00:00); held 0d 00:00:00" if record else 'free'))
    else:
        action, host, number, owner, *what = args
        assert host == 'hetzner6', args
        if action == 'claim':
            if number in claims:
                sys.exit(1)
            claims[number] = dict(owner=owner, what=what[0])
        else:
            assert action == 'release' and (not what or len(what) == 2 and what[0] == '--what'), args
            if config.get('claim_release_refusal') or number not in claims or claims[number]['owner'] != owner:
                sys.exit(1)
            if what and claims[number]['what'] != what[1]:
                sys.exit('fixture release requires matching WHAT')
            del claims[number]
        temporary = path.with_suffix('.new')
        temporary.write_text(json.dumps(claims))
        temporary.replace(path)
        if action == 'claim':
            if not config.get('claim_empty_reply'):
                print(f'{host}-{number} claimed by {owner}: {what[0]}', flush=True)
        elif not config.get('release_empty_reply'):
            print(f'{host}-{number} released by {owner}', flush=True)
        hang('after')
        if config.get('claim_unknown_exit') and action == 'claim':
            sys.exit(config['claim_unknown_exit'])
        if config.get('release_unknown_exit') and action == 'release':
            sys.exit(config['release_unknown_exit'])
elif name == 'df':
    assert args == ['-B1', '--output=avail', '/'], args
    print('Avail')
    print(config.get('disk_available', 90000000000))
elif name == 'cargo':
    assert args == ['fetch', '--locked'], args
    if 'cargo_lock' in config:
        assert Path('Cargo.lock').read_text() == config['cargo_lock']
    if config.get('cargo_refusal'):
        sys.exit(config['cargo_refusal'])
elif name == 'codex-run':
    import atexit, shutil
    if args[1:2] == ['--resume']:
        previous = runs / args[2]
        if config.get('resume_refusal'):
            sys.exit(config['resume_refusal'])
        if not (previous / 'thread').is_file() and not (previous / 'events.jsonl').is_file():
            sys.exit('resume run has no thread')
        if not (previous / 'meta').is_file():
            sys.exit('resume run has no meta')
        args = [args[0], *args[3:]]
    if config.get('refuse_launch'):
        sys.exit('fixture launch refused')
    assert args[:4] == ['task', '--to', 'qa-watch', '--on-stop'], args
    assert Path(args[4]).is_absolute()
    task, checkout, report = args[5:]
    assert not Path(report).exists(), 'REPORT already exists'
    process = root / 'proc' / str(os.getpid())
    process.mkdir(parents=True)
    (process / 'cmdline').write_bytes(b'\0'.join(os.fsencode(word) for word in sys.argv) + b'\0')
    atexit.register(shutil.rmtree, process)
    if config.get('delay_before_meta'):
        publish_marker('meta-waiting', str(os.getpid()))
        while not (root / 'allow-meta').exists():
            time.sleep(0.01)
    runs.mkdir(parents=True, exist_ok=True)
    run = 'fixture-' + str(len(list(runs.glob('fixture-*'))) + 1)
    state = runs / run
    state.mkdir()
    started = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    (state / 'thread').write_text('fixture thread')
    (state / 'meta').write_text(f'model=gpt-6.1-sol\neffort=high\nstarted={started}\ntask={task}\nreport={report}\non_stop={args[4]}\n')
    Path(report).write_text(f'codex-run: run {run} is writing this report.\n')
    hang('after')
    if config.get('close_admission'):
        os.closerange(3, 256)  # Deliberately lose kernel exclusion to exercise observation fallback.
    if config.get('delay_before_unit'):
        publish_marker('launch-waiting', str(os.getpid()))
        while not (root / 'allow-launch').exists():
            time.sleep(0.01)
    (state / 'unit').touch()
    if config.get('interrupt_launch'):
        os.kill(os.getppid(), 9)
    print(run, state)
elif name == 'systemd-run':
    import shlex, subprocess
    unit = args[args.index('--unit') + 1]
    directory = Path(next(arg.split('=', 1)[1] for arg in args if arg.startswith('--working-directory=')))
    # Recording must precede the manager call, including a refused start.
    assert unit in (directory / 'deployments').read_text().splitlines()
    if config.get('deploy_failure'):
        sys.exit('fixture deployment refused')
    properties = dict(arg.removeprefix('--property=').split('=', 1) for arg in args if arg.startswith('--property='))
    assert '--setenv=PATH' in args
    assert '--expand-environment=no' in args
    with Path(properties['StandardOutput'].removeprefix('append:')).open('a') as output:
        child = subprocess.Popen(args[args.index('--') + 1:], cwd=directory, stdin=subprocess.DEVNULL,
                                 stdout=output, stderr=output, start_new_session=True,
                                 env=dict(PATH=os.environ['PATH']))
    units.mkdir(exist_ok=True)
    (units / (unit + '.json')).write_text(json.dumps(dict(pid=child.pid,
        stop=shlex.split(properties['ExecStop'].removeprefix('-')), directory=str(directory))))
elif name == 'systemctl':
    import fnmatch
    unit = args[-1].removesuffix('.service')
    run = unit.removeprefix('codex-run-')
    deployment = unit.startswith('qa-')
    path = units / (unit + '.json')
    saved = json.loads(path.read_text()) if deployment and path.exists() else None
    pass_name = unit.removeprefix('qa-').removesuffix('-*') if args[1] == 'list-units' else ''
    for owner, operation in config.get('hung_systemctl', {}).items():
        if args[1] == operation and (pass_name == owner or fnmatch.fnmatchcase(unit, 'qa-' + owner + '-[a-z]*')):
            import subprocess
            child = subprocess.Popen([sys.executable, '-I', '-B', '-c', 'import time; time.sleep(600)'])
            publish_marker('hung-' + owner, f'{os.getpid()} {child.pid}')
            time.sleep(600)
    if args[1] == 'list-units':
        assert args[:7] == ['--user', 'list-units', '--all', '--plain', '--no-legend', '--full', args[-1]]
        if config.get('unit_query_failure') or pass_name in config.get('list_failures', []):
            sys.exit('fixture manager unavailable')
        if pass_name in config.get('list_output', {}):
            print(config['list_output'][pass_name])
        else:
            for file in sorted(units.glob('*.json')):
                if fnmatch.fnmatchcase(file.stem, args[-1]):
                    metadata = json.loads(file.read_text())
                    active = 'active' if alive(metadata['pid']) else 'inactive'
                    print(f'{file.stem}.service loaded {active} running Fixture deployment')
        sys.exit(0)
    if args[1] == 'show':
        properties = ['--property=LoadState', '--property=ActiveState']
        if '--property=Job' in args:
            properties.append('--property=Job')
        if deployment:
            properties.append('--property=WorkingDirectory')
        assert args[2:-1] == [*properties, '--'], args
        if config.get('unit_query_failure'):
            sys.exit('fixture manager unavailable')
        if deployment:
            override = config.get('unit_states', {}).get(unit)
            if override == 'unknown':
                sys.exit('fixture unit state unknown')
            if unit in config.get('show_output', {}):
                print(config['show_output'][unit])
                sys.exit(0)
            print('LoadState=' + ('loaded' if saved else 'not-found'))
            print('ActiveState=' + (override or ('deactivating' if saved and saved.get('stopping') else
                                                'active' if saved and alive(saved['pid']) else 'inactive')))
            if '--property=Job' in args:
                print('Job=' + config.get('unit_jobs', {}).get(unit, ''))
            print('WorkingDirectory=' + (saved['directory'] if saved else ''))
            sys.exit(0)
        present = (runs / run / 'unit').exists()
        active = config.get('unit_state', 'active' if config.get('unit_active') else
                            'inactive' if not present or config.get('inactive') or (runs / run / 'ended').exists() else 'active')
        if config.get('unit_malformed'):
            print('LoadState=loaded')
        else:
            print('LoadState=' + config.get('unit_load', 'loaded' if present else 'not-found'))
            print('ActiveState=' + active)
            if '--property=Job' in args:
                print('Job=' + config.get('unit_job', ''))
        sys.exit(0)
    import subprocess
    if args[1] == '_finish-stop':
        assert deployment and saved
        subprocess.run(saved['stop'], stdin=subprocess.DEVNULL, check=True)
        stop_group(saved['pid'])
        path.unlink(missing_ok=True)
        sys.exit(0)
    assert args[1] == 'stop', args
    if config.get('stop_failure') or unit in config.get('stop_failures', []):
        sys.exit('fixture stop refused')
    if deployment:
        assert args[:4] in (['--user', 'stop', '--no-block', '--'], ['--user', 'stop', '--', unit])
        if not saved:
            sys.exit('fixture unit not loaded')
        if '--no-block' in args:
            saved['stopping'] = True
            path.write_text(json.dumps(saved))
            subprocess.Popen([sys.executable, '-I', '-B', sys.argv[0], '--user', '_finish-stop', unit],
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
        else:
            subprocess.run(saved['stop'], stdin=subprocess.DEVNULL, check=True)
            stop_group(saved['pid'])
            path.unlink()
    else:
        meta = dict(line.split('=', 1) for line in (runs / run / 'meta').read_text().splitlines())
        on_stop = Path(meta['on_stop'])
        if on_stop.is_file() and not on_stop.is_symlink() and os.access(on_stop, os.X_OK):
            subprocess.run([str(on_stop)], cwd=on_stop.parent, stdin=subprocess.DEVNULL, timeout=60)
        end(run, 'codex-run: the run wrote no report and no last message; exit 143.\n', 143)
elif name == 'logins':
    if args[0] == 'take' and config.get('delay_take'):
        publish_marker('take-waiting', str(os.getpid()))
        while not (root / 'allow-take').exists():
            time.sleep(0.01)
        config = json.loads((root / 'tools.json').read_text())
    held = set(config.get('logins_held', []))
    holders = {login: config.get('login_holders', {}).get(login, 'qa-watch') for login in held}
    if args == ['list']:
        if config.get('login_list_failure'):
            sys.exit('fixture login list failed')
        members = set(holders) | set(config.get('logins_out', []))
        for pool in config.get('pools', {}).values():
            members.update(pool)
        for login in sorted(members):
            if login not in holders and login not in config.get('logins_out', []):
                print(f'{login}: at rest')
                continue
            holder = holders.get(login, 'qa-watch')
            note = ' (fabrig)' if login != 'chatgpt-2' else ''
            state = 'not at rest' if login in config.get('logins_out', []) else 'at rest'
            print(f'{login}: held by {holder}{note} since 2026-10-26T09:15:23Z, 0:01, {state}')
            print('  waiting: other since 2026-10-26T09:15:23Z (any of chatgpt)')
            print('  last 24 hours: 0:01 held')
        for line in config.get('list_lines', []):
            print(line)
        sys.exit(0)
    if args[0] == 'drop':
        entry = dict(holder=args[args.index('--as') + 1], request=args[1], pool='--any' in args)
        config['login_queue'] = [row for row in config.get('login_queue', []) if row != entry]
        (root / 'tools.json').write_text(json.dumps(config))
        sys.exit(0)
    assert args[0] in ('take', 'give', 'set-run'), args
    login = args[1]
    position = args.index('--as')
    holder = args[position + 1]
    if args[0] == 'set-run':
        if config.get('set_run_refusal') or login not in held or holders.get(login) != holder:
            sys.exit(2)
        config.setdefault('login_runs', {})[login] = args[args.index('--run') + 1]
        publish_marker('tools.json', json.dumps(config))
        print('run set: ' + login)
        sys.exit(0)
    if login in config.get('logins_refused', []):
        print('fixture login refused', file=sys.stderr)
        sys.exit(4)
    if args[0] == 'take':
        pool = '--any' in args
        now = '--now' in args
        if holder.startswith('qa-watch'):
            assert pool and now and args[position + 2] == '--note' and args[position + 3] in ('fabrig', 'jig'), args
        if holder.startswith('walk/'):
            assert pool and now and '--wait' not in args, args
            if (root / 'tmp/qa/walks' / (holder.rsplit('/', 1)[-1] + '.json')).exists():
                assert Path(args[args.index('--note') + 1]).is_dir(), args
        members = config.get('pools', {}).get(login, [login]) if pool else [login]
        queue = config.setdefault('login_queue', [])
        entry = dict(holder=holder, request=login, pool=pool)
        if not now:
            entry = next((row for row in queue if row == entry), entry)
            if entry not in queue:
                queue.append(entry)
        reserved = set()
        free = {member for group in config.get('pools', {}).values() for member in group
                if member not in holders and member not in config.get('logins_busy', [])
                and member not in config.get('logins_out', [])}
        available = None
        for row in [*queue, entry] if now else queue:
            choices = config.get('pools', {}).get(row['request'], [row['request']]) if row['pool'] else [row['request']]
            choice = next((member for member in choices if member in free and member not in reserved), None)
            if row is entry:
                available = choice
                break
            if choice:
                reserved.add(choice)
        if login in config.get('logins_busy', []) or available is None:
            if '--wait' in args:
                queue.remove(entry)
            (root / 'tools.json').write_text(json.dumps(config))
            print('fixture login busy', file=sys.stderr)
            sys.exit(1)
        login = available
        if not now:
            queue.remove(entry)
        held.add(login)
        holders[login] = holder
        config.update(logins_held=sorted(held), login_holders=holders)
        (root / 'tools.json').write_text(json.dumps(config))
        hang('after')
        print(login, root / 'login-store' / login / 'login')
    elif login in holders and holders[login] != holder:
        print('fixture held by another', file=sys.stderr)
        sys.exit(2)
    elif (login in config.get('logins_out', []) or login in config.get('logins_real', [])
          and not (root / 'login-store' / login / 'login').exists()):
        print('fixture login out', file=sys.stderr)
        sys.exit(1)
    elif login in held:
        config.setdefault('logins_released', []).append(login)
        held.remove(login)
        holders.pop(login)
        config.update(logins_held=sorted(held), login_holders=holders)
        (root / 'tools.json').write_text(json.dumps(config))
    else:
        print('already free: ' + login)
elif name == 'post':
    if args[0] == 'send':
        rest = args[3:] if args[1] == '--as' else args[1:]
        if len(rest[1]) > 200 or any(ord(c) < 32 or 127 <= ord(c) <= 159 or c in '\u2028\u2029' for c in rest[1]):
            sys.exit('fixture subject refused')
        with Path(os.environ['QA_POST_LOG']).open('a') as log:
            log.write(json.dumps(dict(args=['send', *rest], body=Path(rest[2]).read_text())) + '\n')
        sys.exit(int(config.get('post_status', {}).get(rest[0], os.environ['QA_POST_STATUS'])))
    if args[0] == 'wait':
        waits = root / 'waits'
        index = int(waits.read_text()) if waits.exists() else 0
        waits.write_text(str(index + 1))
        if index == 0 and config.get('wait_settings'):
            (root / 'tmp/machine.env').write_text(config['wait_settings'])
        if 'wait_scale' in config and index < 2:
            started = time.monotonic()
            publish_marker('wait-started-' + str(index), str(started))
            deadline = started + int(args[args.index('--timeout') + 1]) * config['wait_scale']
            while time.monotonic() < deadline:
                if (root / 'mail-delivered').exists():
                    sys.exit(0)
                time.sleep(0.01)
            publish_marker('wait-elapsed', str(time.monotonic() - started))
            sys.exit(1)
        sys.exit(config.get('wait', [4])[index])
    assert args == ['read', 'qa-watch']
    if config.get('wait_scale'):
        delivered = float((root / 'mail-delivered').read_text())
        publish_marker('mail-read-delay', str(time.monotonic() - delivered))
        (root / 'mail-delivered').unlink()
    print('fixture end mail')
'''

# Only standard, nonblocking fake observations can avoid process startup.
# Mutations, modified fake programs and deliberate hangs retain real argv,
# timeout, process-group and inherited-descriptor behavior.
FAST_READ_DRIVER = '_fixture_program = ' + repr(f'#!/usr/bin/env -S {sys.executable} -I -B\n' + WATCH_TOOLS) + '\n' + r'''
import contextlib, io, traceback
from pathlib import Path
_fixture_original = tool['command']
_fixture_compiled = compile(_fixture_program, '<qa fake observation>', 'exec')
def _fixture_command(argv, cwd=None, timeout=None, pass_fds=(), **kwargs):
    argv = [str(word) for word in argv]
    name = Path(argv[0]).name
    quick = (name in ('logins', 'claim') and argv[1:] == ['list']
             or name == 'df' and argv[1:] == ['-B1', '--output=avail', '/']
             or name == 'systemctl' and argv[1:3] in (['--user', 'show'], ['--user', 'list-units']))
    try:
        root = Path(tool['os'].environ['QA_FIXTURE'])
        config = tool['json'].loads((root / 'tools.json').read_text())
        quick = (quick and not cwd and not pass_fds and not kwargs
                 and Path(argv[0]).parent == root and not config.get('hang')
                 and not config.get('hung_systemctl')
                 and Path(argv[0]).read_text() == _fixture_program)
    except (OSError, KeyError, ValueError):
        quick = False
    if not quick:
        return _fixture_original(argv, cwd=cwd, timeout=timeout, pass_fds=pass_fds, **kwargs)
    out, err, status = io.StringIO(), io.StringIO(), 0
    previous = tool['sys'].argv
    tool['sys'].argv = argv
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                exec(_fixture_compiled, {'__name__': '__main__', '__file__': argv[0]})
            except SystemExit as exit_status:
                if isinstance(exit_status.code, str):
                    print(exit_status.code, file=tool['sys'].stderr)
                    status = 1
                else:
                    status = exit_status.code or 0
            except Exception:
                traceback.print_exc()
                status = 1
    finally:
        tool['sys'].argv = previous
    return tool['subprocess'].CompletedProcess(argv, status, out.getvalue(), err.getvalue())
tool['main'].__globals__['command'] = _fixture_command
'''


FIXTURE_PROGRAM = f'#!/usr/bin/env -S {sys.executable} -I -B\n' + WATCH_TOOLS
FIXTURE_CODE = compile(FIXTURE_PROGRAM, '<qa fake service>', 'exec')


class Lab:
    def __init__(self, root, built=None, lightweight=False, slot_numbers=range(1, 5)):
        self.lightweight = lightweight
        self.built = built
        self.root = root
        self.home, self.tmp = root / 'home', root / 'tmp'
        self.origins = root / 'origins'
        self.post_log = root / 'post.jsonl'
        self.post = root / 'post'
        for path in (self.home, self.tmp, self.origins, root / 'proc', root / 'git-template', root / 'git-template/info'):
            path.mkdir(exist_ok=True)
        self.env = dict(PATH=str(root) + os.pathsep + os.environ['PATH'], HOME=str(self.home), DEV_ROOT=str(root),
                        DEV_TMP=str(self.tmp), QA_FIXTURE=str(root), QA_POST_LOG=str(self.post_log), QA_POST_STATUS='0',
                        QA_WALK_SLOTS='forgejo=1,2 claude=3,4 github=5 both=6,7',
                        QA_CLAIM_SSH='', USER='fixture', POST_NAME='o/fixture', GIT_CONFIG_GLOBAL='/dev/null',
                        GIT_TEMPLATE_DIR=str(root / 'git-template'), GIT_CONFIG_NOSYSTEM='1',
                        GIT_AUTHOR_NAME='Fixture', GIT_AUTHOR_EMAIL='fixture@invalid',
                        GIT_COMMITTER_NAME='Fixture', GIT_COMMITTER_EMAIL='fixture@invalid',
                        GIT_ALLOW_PROTOCOL='file', LC_ALL='C.UTF-8', PYTHONDONTWRITEBYTECODE='1')
        for index, (key, value) in enumerate((('maintenance.auto', 'false'), ('gc.auto', '0'),
                                             ('fetch.autoMaintenance', 'false'), ('receive.autogc', 'false'))):
            self.env[f'GIT_CONFIG_KEY_{index}'] = key
            self.env[f'GIT_CONFIG_VALUE_{index}'] = value
        self.env['GIT_CONFIG_COUNT'] = '4'
        self.configure(pools={CHATGPT: [CHATGPT, 'chatgpt-2', 'chatgpt-3'], CLAUDE: [CLAUDE, 'claude-2', 'claude-3']})
        for name in ('post', 'codex-run', 'systemctl', 'systemd-run', 'logins', 'cargo', 'claim', 'ssh', 'df'):
            tool = root / name
            executable(tool, WATCH_TOOLS)
            self.env['QA_' + name.upper().replace('-', '_')] = str(tool)
        self.products = {'fabrig': root / 'fabrig'}
        self.serial = 0
        checkout = self.products['fabrig']
        if lightweight:
            checkout.mkdir()
            self.template_head = (built / 'fabrig/.git/refs/heads/main').read_text().strip()
        elif built is not None:
            shutil.copytree(built / 'fabrig', checkout)
            shutil.copytree(built / 'origins/fabrig.git', self.origins / 'fabrig.git')
            self.git(checkout, 'remote', 'set-url', 'origin', str(self.origins / 'fabrig.git'))
        else:
            self.git(root, 'init', '-b', 'main', str(checkout))
            trim = checkout / 'tools/slots/trim'
            trim.parent.mkdir(parents=True)
            trim.write_text("import json, os, sys\nfrom pathlib import Path\nroot = Path(os.environ['QA_FIXTURE'])\nwith (root / 'tools.jsonl').open('a') as out:\n    out.write(json.dumps(dict(tool='trim', args=sys.argv[1:])) + '\\n')\nprint('fixture trim')\nsys.exit(json.loads((root / 'tools.json').read_text()).get('trim_status', 0))\n")
            self.git(checkout, 'add', 'tools')
            self.git(checkout, 'commit', '-m', 'baseline')
            self.git(root, 'clone', '--bare', str(checkout), str(self.origins / 'fabrig.git'))
            self.git(checkout, 'remote', 'add', 'origin', str(self.origins / 'fabrig.git'))
        self.slots = self.home / 'src/fabrig/slots'
        self.slots.mkdir(parents=True)
        if not lightweight:
            for number in slot_numbers:
                shutil.copytree(checkout, self.slots / str(number))



    def git(self, root, *args):
        result = subprocess.run(['git', '-C', str(root), *args], env=self.env, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=HUNG_TOOL_S)
        assert result.returncode == 0, (args, result.stderr)
        return result.stdout.strip()

    def scratch(self, files, directory=None):
        root = directory if directory is not None else self.root / 'scratch'
        root.mkdir(exist_ok=True)
        for name, data in files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data if isinstance(data, bytes) else data.encode())
        return root

    def commit(self, subject, trailer=None, repo='fabrig', branch='main'):
        checkout = self.products[repo]
        self.serial += 1
        stamp = (datetime(2026, 10, 26, tzinfo=timezone.utc) + timedelta(minutes=self.serial)).isoformat()
        self.env['GIT_AUTHOR_DATE'] = self.env['GIT_COMMITTER_DATE'] = stamp
        self.git(checkout, 'checkout', '-B', branch)
        args = ['commit', '--allow-empty', '-m', subject]
        if trailer is not None:
            args += ['-m', 'QA: ' + trailer]
        self.git(checkout, *args)
        sha = self.git(checkout, 'rev-parse', 'HEAD')
        self.git(checkout, 'push', 'origin', branch)
        return sha

    def marked(self):
        return self.commit('B: refuses a frame', 'a task past the page is refused by name')

    def run(self, *args, status=0, extra=None, now=None):
        driver = f'import runpy, sys\ntool = runpy.run_path({str(SCRIPT)!r})\n' + FAST_POLL
        if now is not None:
            # Own the clock only in the fixture interpreter, never in qa's CLI.
            driver += f'tool["main"].__globals__["timestamp"] = lambda: {now!r}\n'
        if args[:1] in (('watch',), ('walk',), ('take',)):
            driver += FAST_READ_DRIVER + '\n'
        driver += 'sys.exit(tool["main"]())'
        if getattr(self, 'in_process', False):
            return self.invoke(driver, args, status=status, extra=extra)
        command = [sys.executable, '-I', '-B', '-c', driver, *args]
        result = subprocess.run(command, env=dict(self.env, **(extra or {})), cwd=self.root,
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, timeout=HUNG_TOOL_S)
        assert result.returncode == status, (args, result.returncode, result.stdout, result.stderr)
        return result

    def invoke(self, driver, args, status=0, extra=None):
        env = dict(self.env, **(extra or {}))
        inline_driver = driver.replace(FAST_READ_DRIVER, '')
        if '._exit(' in inline_driver or 'os.kill(' in inline_driver or 'addaudithook' in inline_driver:
            result = support.child_execute(support.load(SCRIPT), inline_driver,
                [str(SCRIPT), *args], env, self.root, self.setup_inline, HUNG_TOOL_S)
        else:
            # The in-process dispatcher handles both observations and mutations.
            result = support.execute(support.load(SCRIPT), inline_driver, [str(SCRIPT), *args],
                                     env, self.root, self.setup_inline)
        assert result.returncode == status, (args, result.returncode, result.stdout, result.stderr)
        return result

    def setup_inline(self, tool):
        if self.lightweight:
            lab = self
            def fetch(repositories, repo, slot):
                checkout = lab.slots / str(slot)
                trim = checkout / 'tools/slots/trim'
                trim.parent.mkdir(parents=True, exist_ok=True)
                if not trim.exists():
                    shutil.copyfile(lab.built / 'fabrig/tools/slots/trim', trim)
                return checkout
            tool['Repositories'].fetch = fetch
            tool['Repositories'].protect_head = lambda *a: None
            tool['Repositories'].build = lambda repositories, root, ref: lab.template_head
            tool['Repositories'].checkout = lambda *a: None
        original = tool['command']
        def command(argv, cwd=None, timeout=None, pass_fds=(), **kwargs):
            import atexit
            import contextlib
            import io
            import traceback
            from unittest.mock import patch
            words = list(map(str, argv))
            if self.lightweight and words[0] == 'git':
                # Q-state dependency fixtures contain only this absent object;
                # real Git graph/resolution contracts have full repositories.
                assert words[1] == '-C' and Path(words[2]).parent == self.slots
                assert words[3:] == ['rev-parse', '--disambiguate=' + 'a' * 40], words
                return subprocess.CompletedProcess(argv, 0, '', '')
            resolved = shutil.which(words[0])
            program = Path(resolved) if resolved else Path(words[0])
            is_trim = len(words) > 3 and words[:3] == ['python3', '-I', '-B'] and words[3].endswith('/tools/slots/trim')
            if is_trim:
                program = Path(words[3])
                words = words[3:]
            config = json.loads((self.root / 'tools.json').read_text())
            quick = (program.is_relative_to(self.root) and program.name in
                     ('logins', 'claim', 'ssh', 'df', 'cargo', 'post', 'codex-run', 'systemctl')
                     and program.read_text() == FIXTURE_PROGRAM or is_trim)
            if (not quick or kwargs or config.get('hang') or config.get('hung_systemctl')
                    or program.name == 'codex-run' and any(config.get(k) for k in
                        ('delay_before_meta', 'delay_before_unit', 'interrupt_launch', 'close_admission'))
                    or program.name == 'systemctl' and words[2:3] not in (['show'], ['list-units'])):
                return original(argv, cwd=cwd, timeout=timeout, pass_fds=pass_fds, **kwargs)
            output, error = io.StringIO(), io.StringIO()
            previous_argv, previous_cwd = sys.argv, Path.cwd()
            callbacks = []
            code = compile(program.read_text(), str(program), 'exec') if is_trim else FIXTURE_CODE
            def exec_fixture(path, argv):
                # Run the fake ssh's exact parsed argv through the same fixture,
                # preserving its output/status without replacing this interpreter.
                nested = command(argv)
                sys.stdout.write(nested.stdout)
                sys.stderr.write(nested.stderr)
                raise SystemExit(nested.returncode)
            status = 0
            try:
                sys.argv = words
                if cwd is not None:
                    os.chdir(cwd)
                with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error), \
                        patch.object(atexit, 'register', lambda fn, *a, **kw: callbacks.append((fn, a, kw))), \
                        patch.object(os, 'execv', exec_fixture):
                    try:
                        exec(code, {'__name__': '__main__', '__file__': str(program)})
                    except SystemExit as exit_status:
                        if isinstance(exit_status.code, str):
                            print(exit_status.code, file=sys.stderr)
                            status = 1
                        else:
                            status = exit_status.code or 0
                    except Exception:
                        traceback.print_exc()
                        status = 1
            finally:
                for fn, a, kw in reversed(callbacks):
                    fn(*a, **kw)
                sys.argv = previous_argv
                os.chdir(previous_cwd)
            return subprocess.CompletedProcess(argv, status, output.getvalue(), error.getvalue())
        tool['command'] = command

    def probe(self, driver):
        return support.execute(support.load(SCRIPT), driver, [str(SCRIPT)], self.env, self.root)

    def head(self):
        if self.lightweight:
            return self.template_head
        return self.git(self.products['fabrig'], 'rev-parse', 'HEAD')


    def sent(self):
        return [json.loads(line) for line in self.post_log.read_text().splitlines()] if self.post_log.exists() else []

    def configure(self, **values):
        path = self.root / 'tools.json'
        config = json.loads(path.read_text()) if path.exists() else {}
        config.update(values)
        path.write_text(json.dumps(config))

    def calls(self, tool):
        path = self.root / 'tools.jsonl'
        return [row['args'] for row in map(json.loads, path.read_text().splitlines()) if row['tool'] == tool] if path.exists() else []

    def prune_dead_launchers(self):
        # Only fixture children have entries; SIGKILL cannot run their atexit.
        for path in (self.root / 'proc').iterdir():
            if not alive(int(path.name)):
                shutil.rmtree(path)

    def watch(self, status=0, extra=None, now=None):
        self.prune_dead_launchers()
        return self.run('watch', '--director', 'director@fixture', '--once', status=status, extra=extra, now=now)

    def walk(self, rung='b0', *args, status=0, now=None):
        path = self.tmp / 'qa-focused' / ('rung-' + rung + '-brief.md')
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(b'Rung fixture brief.\r\nPreserve these bytes.\n')
        return self.run('walk', 'fabrig', rung, *args, status=status, now=now)

    def walk_states(self):
        return [(self.tmp / 'qa-focused' / path.stem, json.loads(path.read_text()))
                for path in sorted((self.tmp / 'qa/walks').glob('*.json'))]

    def walk_state(self):
        state, = self.walk_states()
        return state

    def watch_states(self):
        return []  # Pass scheduling is outside this tool.

    def watch_state(self):
        return self.walk_state()


    def end_run(self, state=None, report='## Findings\nNone.\n', code=0):
        state = state or self.walk_state()[1]
        directory = (self.tmp / 'qa-focused' / state['walk'] if 'walk' in state
                     else self.tmp / 'qa' / state['pass'])
        (directory / 'report.md').write_text(report)
        run = self.tmp / 'codex-run' / state['run']
        meta = dict(line.split('=', 1) for line in (run / 'meta').read_text().splitlines())
        ended = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        row = [state['run'], 'qa-watch', state['started'], ended, str(code), '1', meta['model'], meta['effort'],
               str(directory / 'brief.md'), str(directory / 'report.md'), 'thread', '100/20/30', '0']
        with (self.tmp / 'codex-run/runs.tsv').open('a') as out:
            out.write('\t'.join(row) + '\n')
        (run / 'ended').touch()
        return ended

def stuck_posts(lab):
    return [post for post in lab.sent() if post['args'][2].startswith('qa: login ')]




def executable(path, text):
    temporary = path.with_name(path.name + '.new')
    temporary.write_text(f'#!/usr/bin/env -S {sys.executable} -I -B\n' + text)
    temporary.replace(path)
    path.chmod(0o700)
    return path


def alive(pid):
    try:
        return Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[0] != 'Z'
    except FileNotFoundError:
        return False


def wait_for(check):
    deadline = time.monotonic() + 10
    while not check():
        assert time.monotonic() < deadline, 'fixture process did not settle'
        time.sleep(0.01)


def dead(pid):
    wait_for(lambda: not alive(pid))
    try:
        os.waitpid(pid, 0)
    except ChildProcessError:
        pass


def resting(lab, name, in_place=False):
    path = lab.root / 'login-store' / name / 'login'
    path.parent.mkdir(parents=True, exist_ok=True)
    if in_place:
        path.mkdir(mode=0o700)
        (path / 'fixture').touch()
    else:
        path.write_text('fixture login\n')
        path.chmod(0o600)
    return path


def deployment_pass(lab, *logins, in_place=()):
    pools = list(logins) or [CHATGPT]
    lab.env['QA_WALK_KINDS'] = 'forgejo=2:' + ','.join(pools)
    for name in pools:
        resting(lab, name, name in in_place)
    lab.configure(logins_real=list(pools))
    lab.walk('b0', '--cap', '1', now='2026-10-27T10:00:00Z')
    return lab.walk_state()



def deployment(lab, directory, name='box', login=None):
    box = directory / name
    box.mkdir(exist_ok=True)
    (box / 'pid').unlink(missing_ok=True)
    path = lab.root / 'login-store' / login / 'login' if login else None
    program = executable(box / 'server', 'import os, time\nfrom pathlib import Path\n'
        + (f'Path({str(path)!r}).rename({str(box / "login")!r})\n' if login else '')
        + f'pid = Path({str(box / "pid-new")!r})\n'
          'pid.write_text(str(os.getpid()))\n'
        + f'pid.replace({str(box / "pid")!r})\n'
          'while True: time.sleep(1)\n')
    unit = lab.run('deploy', str(directory), name, '--', str(program)).stdout.strip()
    wait_for(lambda: (box / 'pid').exists())
    pid = int((box / 'pid').read_text())
    if login:
        executable(directory / 'give-back', 'import os, sys\nfrom pathlib import Path\n'
            + f'path = Path({str(path)!r})\n'
              'if path.exists(): sys.exit(0)\n'
            + f'pid = int(Path({str(box / "pid")!r}).read_text())\n'
              'try:\n'
              "    live = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[0] != 'Z'\n"
              'except FileNotFoundError: live = False\n'
              'if not live: sys.exit(1)\n'
            + f'Path({str(box / "login")!r}).rename(path)\n')
    return unit, pid


def aged(lab, directory):
    # Walk directories are retained after completion, including past seven days.
    pass



def end_deployment_pass(lab):
    lab.watch(now='2026-10-27T10:01:01Z')
    lab.watch()



def deploy_runs_the_real_systemd_run(lab):
    directory, state = deployment_pass(lab)
    lab.end_run(state)
    lab.watch()
    assert lab.walk_state()[1]['stage'] == 'ended' and 'kinds' in state
    directory = lab.root / P
    directory.mkdir()
    binary = lab.root / 'system-bin'
    binary.mkdir()
    log = lab.root / 'system-programs.jsonl'
    for name in ('systemd-run', 'systemctl'):
        executable(binary / name, 'import json, sys\nfrom pathlib import Path\n'
            + f'with Path({str(log)!r}).open("a") as log:\n'
              '    log.write(json.dumps([Path(sys.argv[0]).name, sys.argv[1:]]) + "\\n")\n')
    lab.env.pop('QA_SYSTEMD_RUN')
    lab.env.pop('QA_SYSTEMCTL')
    lab.env['PATH'] = str(binary) + os.pathsep + lab.env['PATH']
    program = str(Path(shutil.which('true', path=lab.env['PATH'])).absolute())
    unit = f'qa-{directory.name}-box'
    assert lab.run('deploy', str(directory), 'box', '--', 'true').stdout == unit + '\n'
    assert list(map(json.loads, log.read_text().splitlines())) == [['systemd-run', [
        '--user', '--collect', '--quiet', '--unit', unit,
        '--service-type=exec', '--expand-environment=no', f'--working-directory={directory}', '--setenv=PATH',
        '--property=KillMode=control-group',
        f'--property=StandardOutput=append:{directory}/box.log',
        f'--property=StandardError=append:{directory}/box.log',
        f'--property=ExecStop=-"{SCRIPT}" "_give-back" "{directory}" "50"',
        '--property=TimeoutStopSec=110', '--', program]]]
    log.write_text('')
    # Observe the service's dependency lookup with no executable overrides.
    driver = (f'import runpy; tool = runpy.run_path({str(SCRIPT)!r}); '
              f'workspace = tool["Workspace"](); service = tool["Watch"](workspace, "director@fixture"); '
              f'service.deployments(tool["Path"]({str(directory)!r}), '
              f'{{"walk": {directory.name!r}, "kinds": {{}}}})')
    result = lab.probe(driver)
    assert result.returncode == 0, result.stderr
    assert list(map(json.loads, log.read_text().splitlines())) == [['systemctl', [
        '--user', 'list-units', '--all', '--plain', '--no-legend', '--full', f'qa-{directory.name}-*']]]
























def driven_watch(lab, patch, once=True, status=0, extra=None, now=None):
    lab.prune_dead_launchers()
    driver = f'''import runpy, sys
tool = runpy.run_path({str(SCRIPT)!r})
{FAST_POLL}
{FAST_READ_DRIVER}
{patch}
sys.exit(tool['main']())
'''
    if now is not None:
        driver = driver.replace("sys.exit(tool['main']())", f'tool["main"].__globals__["timestamp"] = lambda: {now!r}\nsys.exit(tool["main"]())')
    if getattr(lab, 'in_process', False):
        return lab.invoke(driver, ['watch', '--director', 'director@fixture', *(['--once'] if once else [])],
                          status=status, extra=extra)
    result = subprocess.run([sys.executable, '-I', '-B', '-c', driver, 'watch', '--director',
                             'director@fixture', *(['--once'] if once else [])], env=dict(lab.env, **(extra or {})), capture_output=True,
                            text=True, timeout=HUNG_TOOL_S)
    assert result.returncode == status, (result.stdout, result.stderr)
    return result


def settled_watch(lab, *units, **kwargs):
    # A successful stop can race show() reading the disappearing fake record.
    # Retry only these known-to-stop deployments, after their manager records
    # disappear. Keep one check's notification/clock assertions intact; tests
    # of unknown/refused stops still use the unmodified bounded observation.
    patch = f"""import time
from pathlib import Path
original = tool['Watch'].unit_stopped
def settled(self, unit, seconds, directory=None):
    stopped = original(self, unit, seconds, directory)
    if not stopped and unit in {units!r}:
        record = Path(tool['os'].environ['QA_FIXTURE']) / 'units' / (unit + '.json')
        deadline = time.monotonic() + 10
        while record.exists():
            assert time.monotonic() < deadline, 'fixture stop did not settle'
            time.sleep(0.01)
        return original(self, unit, seconds, directory)
    return stopped
tool['Watch'].unit_stopped = settled
"""
    return driven_watch(lab, patch, **kwargs)




def deploy_passes_a_literal_dollar(lab):
    directory = lab.root / P
    directory.mkdir()
    output = directory / 'arguments'
    program = executable(directory / 'capture', 'import json, os, sys\nfrom pathlib import Path\n'
                         "output = Path('arguments')\n"
                         "temporary = output.with_name(output.name + '.new')\n"
                         "temporary.write_text(json.dumps(sys.argv[1:]))\n"
                         "os.replace(temporary, output)\n")
    args = ['$HOME', '${PATH}']
    lab.run('deploy', str(directory), 'literal', '--', str(program), *args)
    wait_for(output.exists)
    assert json.loads(output.read_text()) == args
    call, = lab.calls('systemd-run')
    assert '--expand-environment=no' in call and call[-2:] == args


def a_linked_log_or_registry_writes_nowhere_else(lab):
    directory = lab.root / P
    directory.mkdir()
    outside = lab.root / 'outside-notes'
    marker = 'outside-' + 'write-contents'
    outside.write_text(marker)
    executable(directory / 'give-back', "from pathlib import Path\nPath('returned').touch()\nprint('export output')\n")
    log = directory / 'give-back.log'
    # A bad log must never prevent the login's give-back from running.
    for kind in ('hardlink', 'symlink', 'fifo', 'directory'):
        if kind == 'hardlink':
            os.link(outside, log)
        elif kind == 'symlink':
            log.symlink_to(outside)
        elif kind == 'fifo':
            os.mkfifo(log)
        else:
            log.mkdir()
        result = lab.run('_give-back', str(directory), '2')
        assert (directory / 'returned').exists() and outside.read_text() == marker
        assert not result.stdout + result.stderr
        (directory / 'returned').unlink()
        log.rmdir() if log.is_dir() else log.unlink()
    registry = directory / 'deployments'
    for kind in ('hardlink', 'fifo', 'directory'):
        if kind == 'hardlink':
            os.link(outside, registry)
        elif kind == 'fifo':
            os.mkfifo(registry)
        else:
            registry.mkdir()
        result = lab.run('deploy', str(directory), 'box', '--', 'true', status=2)
        assert not lab.calls('systemd-run') and outside.read_text() == marker
        assert marker not in result.stdout + result.stderr
        registry.rmdir() if registry.is_dir() else registry.unlink()


def a_walk_takes_a_login_and_a_slot_and_starts(lab):
    main = lab.git(lab.products['fabrig'], 'rev-parse', 'HEAD')
    path = resting(lab, CHATGPT)
    result = lab.walk('b0', '--login', CHATGPT)
    directory, state = lab.walk_state()
    checkout = lab.slots / '1'
    assert state['slot'] == 1 and state['holder'] == 'walk/forgejo/rung-b0-1'
    assert state['starter'] == 'o/fixture@' + socket.gethostname()
    assert state['ref'] == 'main' and state['main'] == main and state['cap'] == 180
    assert lab.git(checkout, 'rev-parse', 'HEAD') == main
    assert lab.git(checkout, 'rev-parse', '--abbrev-ref', 'HEAD') == 'HEAD'
    assert state['pools'] == {CHATGPT: CHATGPT} and state['logins'] == {CHATGPT: str(path)}
    assert directory.stat().st_mode & 0o777 == 0o700
    assert (directory / 'brief.md').read_bytes() == (directory.parent / 'rung-b0-brief.md').read_bytes()
    task = (directory / 'task.md').read_text()
    assert all(word in task for word in (str(path), CHATGPT, str(checkout), main,
                                        str(directory / 'give-back'), str(directory / 'report.md'), 'qa deploy'))
    rows = (directory.parent / 'b0/loop.tsv').read_text().splitlines()
    assert rows[0] == 'time\trung\twalk\tevent\tnote'
    assert len(rows) == 2 and rows[1].split('\t')[1:4] == ['b0', '1', 'walk-start']
    assert main[:9] in rows[1] and CHATGPT in rows[1]
    assert 'Never take give-back.lock' in task and 'use a different lock name' in task
    assert [c for c in lab.calls('logins') if c[0] != 'set-run'] == [['list'], ['list'], ['take', CHATGPT, '--any', '--now', '--as', state['holder'],
                                  '--note', str(directory)]]
    assert lab.calls('codex-run') == [['task', '--to', 'qa-watch', '--on-stop', str(directory / 'on-stop'),
                                      str(directory / 'task.md'), str(checkout), str(directory / 'report.md')]]
    assert result.stdout.splitlines() == ['walk rung-b0-1', f'{CHATGPT} {path}', 'run ' + state['run']]
    before = lab.head()
    lab.watch()
    assert lab.walk_state()[1]['stage'] == 'running' and lab.head() == before and not lab.sent()


def a_refused_login_starts_nothing(lab):
    lab.env['QA_WALK_KINDS'] = 'forgejo=2:chatgpt,claude'
    lab.configure(logins_busy=[CLAUDE])
    lab.walk('b0', '--login', CLAUDE, '--login', CHATGPT, status=0)
    directory, state = lab.walk_state()
    assert state['stage'] == 'ended' and state['released'] and state['given'] == [CHATGPT]
    assert ['give', CHATGPT, '--as', state['holder']] in lab.calls('logins')
    assert len(queued_entries(lab)) == 1
    assert not lab.calls('codex-run') and not (directory.parent / 'b0/loop.tsv').exists()
    config = json.loads((lab.root / 'tools.json').read_text())
    assert not config['logins_held'] and not config['login_queue']


def a_third_walk_is_queued_at_once(lab):
    lab.walk('b0')
    lab.walk('b0')
    before = lab.calls('logins')
    result = lab.walk('b0', '--login', CHATGPT, status=0)
    assert 'queued ' in result.stdout and 'kind forgejo holds 2' in queued_entries(lab)[0]['reason']
    states = [state for _, state in lab.walk_states()]
    assert [state['slot'] for state in states] == [1, 2]
    assert lab.calls('logins') == before + [['list']] and len(lab.calls('codex-run')) == 2


def driven_walk(lab, patch, *args, status=0):
    brief = lab.tmp / 'qa-focused/rung-b0-brief.md'
    brief.parent.mkdir(parents=True, exist_ok=True)
    brief.write_text('fixture rung\n')
    driver = f'import os, runpy, sys\ntool = runpy.run_path({str(SCRIPT)!r})\n' + FAST_READ_DRIVER + '\n' + patch + '\nsys.exit(tool["main"]())\n'
    if getattr(lab, 'in_process', False):
        return lab.invoke(driver, ['walk', 'fabrig', 'b0', *args], status=status)
    result = subprocess.run([sys.executable, '-I', '-B', '-c', driver, 'walk', 'fabrig', 'b0', *args],
                            env=lab.env, capture_output=True, text=True, timeout=HUNG_TOOL_S)
    assert result.returncode == status, (result.returncode, result.stdout, result.stderr)
    return result


def a_walk_grant_lost_in_a_crash_is_given_back(lab):
    driven_walk(lab, '''Watch = tool['Watch']
original = Watch.call
def call(self, name, *args):
    result = original(self, name, *args)
    if name == 'logins' and args[0] == 'take' and result.returncode == 0:
        os._exit(77)
    return result
Watch.call = call
''', '--login', CHATGPT, status=77)
    directory, state = lab.walk_state()
    assert state['stage'] == 'reserving' and not state['logins'] and state['slot'] == 1
    lab.watch()
    state = lab.walk_state()[1]
    assert state['stage'] == 'ended' and state['released']
    assert ['give', CHATGPT, '--as', state['holder']] in lab.calls('logins')
    assert not lab.calls('codex-run') and not lab.sent()
    lab.walk('b0', '--login', CHATGPT)
    assert lab.walk_states()[-1][1]['slot'] == 1








def a_walk_refuses_invalid_inputs_before_taking_anything(lab):
    cases = [([], {'POST_NAME': ''}), ([], {'POST_NAME': 'bad@host'}),
             (['--cap', '0'], {}), (['--login', 'chatgpt-2'], {}),
             (['--login', CHATGPT, '--login', CHATGPT], {})]
    for args, extra in cases:
        lab.run('walk', 'fabrig', 'b0', *args, status=2, extra=extra)
    lab.run('walk', 'fabrig', 'Bad', status=2)
    assert not (lab.tmp / 'qa').exists() and not lab.calls('logins') and not lab.calls('codex-run')


def a_walk_resolves_origin_branches_and_commit_prefixes(lab):
    main = lab.marked()
    branch = lab.commit('fix for confirmation', branch='confirm')
    # An existing scratch number is part of the rung's namespace too.
    focused = lab.tmp / 'qa-focused'
    focused.mkdir()
    (focused / 'rung-b0-4').mkdir()
    lab.walk('b0', '--build', 'origin/confirm')
    lab.walk('b0', '--build', main[:9])
    first, second = lab.walk_states()
    assert first[1]['walk'] == 'rung-b0-5' and first[1]['main'] == branch
    assert second[1]['walk'] == 'rung-b0-6' and second[1]['main'] == main
    assert lab.git(lab.slots / '1', 'rev-parse', 'HEAD') == branch
    assert lab.git(lab.slots / '2', 'rev-parse', 'HEAD') == main


def walk_fetch_build(lab):
    checkout = lab.products['fabrig']
    lab.git(checkout, 'checkout', '-b', 'needs-fetch')
    lock = '# fixture branch needs upstream sources absent from the cache\n'
    (checkout / 'Cargo.lock').write_text(lock)
    lab.git(checkout, 'add', 'Cargo.lock')
    commit = lab.commit('branch with uncached sources', branch='needs-fetch')
    lab.configure(cargo_lock=lock)
    return commit


def a_walk_fetches_its_build_before_taking_a_login(lab):
    commit = walk_fetch_build(lab)
    lab.walk('b0', '--build', 'origin/needs-fetch')
    directory, state = lab.walk_state()
    checkout = lab.slots / '1'
    calls = list(map(json.loads, (lab.root / 'tools.jsonl').read_text().splitlines()))
    fetch, = [row for row in calls if row['tool'] == 'cargo']
    take, = [row for row in calls if row['tool'] == 'logins' and row['args'][0] == 'take']
    assert fetch['args'] == ['fetch', '--locked'] and fetch['cwd'] == str(checkout)
    assert calls.index(fetch) < calls.index(take)
    assert state['main'] == lab.git(checkout, 'rev-parse', 'HEAD') == commit
    assert state['stage'] == 'running' and state['logins']


def a_failed_walk_fetch_takes_no_login(lab):
    walk_fetch_build(lab)
    lab.configure(cargo_refusal='fixture locked sources unavailable')
    result = lab.walk('b0', '--build', 'origin/needs-fetch', status=4)
    assert 'cannot fetch build origin/needs-fetch: fixture locked sources unavailable' in result.stderr
    assert lab.calls('cargo') == [['fetch', '--locked']]
    assert not any(args[0] == 'take' for args in lab.calls('logins'))
    assert not lab.calls('codex-run')
    state = lab.walk_state()[1]
    assert state['released'] and state['stage'] == 'ended' and not state['logins']




def a_resumed_walk_fetches_before_taking_a_login(lab):
    directory, state = walk_with_logins(lab, CHATGPT)
    state = pause_walk(lab, directory, state)
    commit = walk_fetch_build(lab)
    before = lab.calls('logins')
    report = (directory / 'report.md').read_bytes()
    lab.configure(cargo_refusal='fixture resumed sources unavailable')
    args = ('walk', 'fabrig', 'b0', '--resume', state['walk'], '--build', 'needs-fetch')
    result = lab.run(*args, status=4)
    assert 'cannot fetch build needs-fetch: fixture resumed sources unavailable' in result.stderr
    assert not any(row[0] == 'take' for row in lab.calls('logins')[len(before):])
    failed = lab.walk_state()[1]
    assert failed['stage'] == 'paused' and failed['released'] and not failed['logins']
    assert (directory / 'report.md').read_bytes() == report
    assert (directory / 'paused').read_text().strip() == state['pause_line']
    lab.configure(cargo_refusal='')
    lab.run(*args)
    resumed = lab.walk_state()[1]
    assert resumed['stage'] == 'running' and resumed['main'] == commit
    calls = list(map(json.loads, (lab.root / 'tools.jsonl').read_text().splitlines()))
    fetches = [index for index, row in enumerate(calls) if row['tool'] == 'cargo']
    takes = [index for index, row in enumerate(calls) if row['tool'] == 'logins' and row['args'][0] == 'take']
    assert len(fetches) == 3 and len(takes) == 2 and fetches[-1] < takes[-1]
    assert calls[fetches[-1]]['cwd'] == str(lab.slots / '1')


def a_walk_preparation_refusal_returns_its_grants(lab):
    # Read the absent brief without Lab.walk creating one for this request.
    lab.run('walk', 'fabrig', 'missing', '--login', CHATGPT, status=1)
    assert all(state['stage'] == 'ended' and state['released'] and state['given'] == [CHATGPT]
               for _, state in lab.walk_states())
    assert not lab.calls('codex-run') and not lab.sent()
    assert not list((lab.tmp / 'qa-focused').glob('*/loop.tsv'))
    lab.configure(refuse_launch=True)
    lab.walk('b0', '--login', CHATGPT, status=1)
    state = next(state for _, state in lab.walk_states() if state['walk'] == 'rung-b0-1')
    assert state['released'] and state['stage'] == 'ended' and state['given'] == [CHATGPT]


def a_walk_launch_lost_in_a_crash_is_recovered(lab):
    driven_walk(lab, '''Watch = tool['Watch']
original = Watch.call
def call(self, name, *args):
    result = original(self, name, *args)
    if name == 'codex-run' and result.returncode == 0:
        os._exit(77)
    return result
Watch.call = call
''', '--login', CHATGPT, status=77)
    directory, state = lab.walk_state()
    assert not state['run'] and state['stage'] == 'starting'
    lab.watch()
    state = lab.walk_state()[1]
    assert state['run'] == 'fixture-1' and state['stage'] == 'running' and not state['given']
    lab.configure(inactive=True)
    lab.watch()
    assert lab.walk_state()[1]['stage'] == 'ended' and len(lab.sent()) == 1
    assert len(lab.calls('codex-run')) == 1


def a_timed_out_walk_launch_keeps_custody_for_recovery(lab):
    driven_walk(lab, '''Watch = tool['Watch']
original = Watch.call
def call(self, name, *args):
    result = original(self, name, *args)
    if name == 'codex-run':
        result.returncode = 124
    return result
Watch.call = call
''', '--login', CHATGPT, status=1)
    assert lab.walk_state()[1]['stage'] == 'starting'
    lab.watch()
    state = lab.walk_state()[1]
    assert state['run'] == 'fixture-1' and state['stage'] == 'running' and not state['given']
    assert not [call for call in lab.calls('logins') if call[0] == 'give']


def a_walk_end_append_survives_an_interrupted_save(lab):
    lab.walk('b0')
    directory, state = lab.walk_state()
    lab.configure(inactive=True)
    driven_watch(lab, '''import os
Watch = tool['Watch']
original = Watch.save
def save(self, directory, state):
    if 'walk' in state and state.get('end_logged'):
        os._exit(0)
    return original(self, directory, state)
Watch.save = save
''')
    assert not lab.walk_state()[1]['end_logged'] and not lab.sent()
    lab.watch()
    assert lab.walk_state()[1]['stage'] == 'ended'
    rows = (directory.parent / 'b0/loop.tsv').read_text().splitlines()
    assert len([row for row in rows if row.split('\t')[3] == 'walk-end']) == 1
    assert len(lab.sent()) == 1




def a_damaged_walk_state_does_not_block_others_cleanup(lab):
    lab.walk('b0', '--login', CHATGPT)
    lab.walk('b1', '--kind', 'claude', '--login', CLAUDE)
    directory, state = lab.walk_states()[0]
    saved = lab.tmp / 'qa/walks' / (state['walk'] + '.json')
    original = saved.read_bytes()
    lab.configure(inactive=True)
    corruptions = ['{broken json', json.dumps(dict(state, logins=[])), json.dumps(dict(state, given=None)),
                   json.dumps({key: value for key, value in state.items() if key != 'logins'})]
    for corrupt in corruptions:
        saved.write_text(corrupt)
        result = lab.watch()
        assert 'invalid walk state; keeping custody' in result.stdout
        assert ['give', CHATGPT, '--as', state['holder']] not in lab.calls('logins')
    good = json.loads((lab.tmp / 'qa/walks/rung-b1-claude-1.json').read_text())
    assert good['stage'] == 'ended' and good['given'] == [CLAUDE]
    assert good['run']
    assert ['give', CHATGPT, '--as', state['holder']] not in lab.calls('logins')
    saved.write_bytes(original)
    lab.watch()
    state = json.loads(saved.read_text())
    assert state['stage'] == 'ended' and state['given'] == [CHATGPT]


def a_linked_walk_state_keeps_its_grant_held(lab):
    lab.walk('b0', '--login', CHATGPT)
    directory, state = lab.walk_state()
    saved = lab.tmp / 'qa/walks' / (state['walk'] + '.json')
    outside = lab.root / 'outside-state'
    original = saved.read_bytes()
    saved.rename(outside)
    saved.symlink_to(outside)
    lab.configure(inactive=True)
    result = lab.watch()
    assert 'invalid walk state; keeping custody' in result.stdout
    assert outside.read_bytes() == original and not lab.sent()
    assert ['give', CHATGPT, '--as', state['holder']] not in lab.calls('logins')
    saved.unlink()
    outside.rename(saved)
    lab.watch()
    assert lab.walk_state()[1]['stage'] == 'ended'


def walk_with_logins(lab, *pools, cap=180):
    for pool in pools:
        resting(lab, pool)
    lab.configure(logins_real=list(pools))
    flags = [word for pool in pools for word in ('--login', pool)]
    lab.walk('b0', *flags, '--cap', str(cap), now='2026-10-27T08:00:00Z')
    return lab.walk_state()


def pause_walk(lab, directory, state, line='step 4: blocked by a finding', post_status='0', settle=()):
    (directory / 'paused').write_text(line + '\n')
    (directory / 'notes.md').write_text('Finding: keep the deployment data and continue step 4.\n')
    lab.run('_give-back', str(directory), '5')
    lab.end_run(state, report='Blocking finding at step 4.\n')
    if settle:
        settled_watch(lab, *settle, extra={'QA_POST_STATUS': post_status})
    else:
        lab.watch(extra={'QA_POST_STATUS': post_status})
    return next(saved for _, saved in lab.walk_states() if saved['walk'] == state['walk'])





def a_paused_walk_frees_its_slot_and_logins(lab):
    directory, state = walk_with_logins(lab, CHATGPT)
    state = pause_walk(lab, directory, state, post_status='2')
    assert state['decision'] == 'walk-pause' and state['released'] and state['given'] == [CHATGPT]
    assert state['end_logged'] and not state['posted'] and state['stage'] == 'ending'
    lab.watch(extra={'QA_POST_STATUS': '3'})
    lab.watch()
    state = lab.walk_state()[1]
    assert state['stage'] == 'paused' and state['posted'] and directory.is_dir()
    posts = lab.sent()
    assert len(posts) == 2 and posts[-1]['args'][1:3] == [state['starter'], 'qa: walk rung-b0-1 paused']
    assert state['pause_line'] in posts[-1]['body'] and str(directory / 'report.md') in posts[-1]['body']
    rows = (directory.parent / 'b0/loop.tsv').read_text().splitlines()
    assert [row.split('\t')[3] for row in rows[1:]] == ['walk-start', 'walk-pause']
    assert state['pause_line'] in rows[-1]
    lab.walk('other', '--login', CHATGPT)
    other = lab.walk_states()[-1][1]
    assert other['slot'] == 1 and other['logins'][CHATGPT] == state['logins'][CHATGPT]
    assert state['attempts'][0]['decision'] == 'walk-pause'









def a_failed_resume_launch_gives_back_and_stays_paused(lab):
    directory, state = walk_with_logins(lab, CHATGPT)
    state = pause_walk(lab, directory, state)
    lab.configure(resume_refusal='resume run has no thread', refuse_launch=True)
    lab.run('walk', 'fabrig', 'b0', '--resume', 'rung-b0-1', '--build', 'main', status=1)
    failed = lab.walk_state()[1]
    assert failed['stage'] == 'paused' and failed['released'] and failed['given'] == [CHATGPT]
    assert failed['attempt'] == 2 and len(failed['attempts']) == 2 and not failed['run']
    assert failed['attempts'][0]['run'] == state['run'] and len(lab.calls('codex-run')) == 3
    assert (directory / 'paused').read_text().strip() == state['pause_line']
    assert (directory / 'report-1.md').read_text() == 'Blocking finding at step 4.\n'
    lab.configure(refuse_launch=False, resume_refusal='')
    lab.run('walk', 'fabrig', 'b0', '--resume', 'rung-b0-1', '--build', 'main')
    current = lab.walk_state()[1]
    assert current['attempt'] == 3 and len(current['attempts']) == 3 and current['stage'] == 'running'
    assert lab.calls('codex-run')[-1][1:3] == ['--resume', state['run']]


def a_resume_before_the_pause_is_complete_is_refused(lab):
    directory, state = walk_with_logins(lab, CHATGPT)
    pause_walk(lab, directory, state, post_status='2')
    before = lab.calls('logins')
    lab.run('walk', 'fabrig', 'b0', '--resume', 'rung-b0-1', '--build', 'main', status=2)
    assert lab.calls('logins') == before and len(lab.calls('codex-run')) == 1
    assert lab.walk_state()[1]['attempt'] == 1


def a_resume_whose_thread_is_gone_starts_fresh(lab):
    directory, state = walk_with_logins(lab, CHATGPT)
    state = pause_walk(lab, directory, state)
    (lab.tmp / 'codex-run' / state['run'] / 'thread').unlink()
    lab.run('walk', 'fabrig', 'b0', '--resume', 'rung-b0-1', '--build', 'main')
    current = lab.walk_state()[1]
    calls = lab.calls('codex-run')
    assert len(calls) == 3 and calls[1][1:3] == ['--resume', state['run']]
    assert calls[2][:4] == ['task', '--to', 'qa-watch', '--on-stop']
    assert current['stage'] == 'running' and current['run'] != state['run']
    task = (directory / 'task.md').read_text()
    assert 'notes.md' in task and 'report-1.md' in task and 'Carry their findings' in task


def resume_refuses_a_walk_not_paused(lab):
    directory, state = walk_with_logins(lab, CHATGPT)
    before = lab.calls('logins')
    for args in [('--resume', 'rung-b0-1', '--build', 'main'), ('--resume', 'rung-b0-1'),
                 ('--resume', '0', '--build', 'main')]:
        lab.run('walk', 'fabrig', 'b0', *args, status=2)
    assert lab.calls('logins') == before
    lab.end_run(state)
    lab.watch()
    before = lab.calls('logins')
    lab.run('walk', 'fabrig', 'b0', '--resume', 'rung-b0-1', '--build', 'main', status=2)
    assert lab.calls('logins') == before and lab.walk_state()[1]['stage'] == 'ended'


def invalid_pause_lines_end_the_walk(lab):
    for line in ('x' * 201, 'a\tb', 'a\x85b', 'a\u2028b', ''):
        lab.walk('b0')
        directory, state = lab.walk_states()[-1]
        (directory / 'paused').write_text(line + '\n')
        lab.end_run(state)
        lab.watch()
        state = lab.walk_states()[-1][1]
        assert state['decision'] == 'walk-end' and state['stage'] == 'ended'
    assert all(post['args'][2].endswith(' ended') for post in lab.sent())


def a_linked_pause_marker_is_not_read(lab):
    lab.walk('b0')
    directory, state = lab.walk_state()
    outside = lab.root / 'outside-pause'
    outside.write_text('linked pause line\n')
    (directory / 'paused').symlink_to(outside)
    lab.end_run(state)
    lab.watch()
    assert lab.walk_state()[1]['decision'] == 'walk-end'
    assert 'linked pause line' not in lab.sent()[0]['body'] and outside.read_text() == 'linked pause line\n'


def a_second_pause_has_its_own_clock_event(lab):
    directory, state = walk_with_logins(lab)
    state = pause_walk(lab, directory, state, line='attempt 2: this is user text')
    lab.run('walk', 'fabrig', 'b0', '--resume', 'rung-b0-1', '--build', 'main')
    state = lab.walk_state()[1]
    # The bound is characters, with the terminating newline outside it.
    state = pause_walk(lab, directory, state, line='x' * 200)
    assert state['stage'] == 'paused' and state['attempt'] == 2
    rows = [row.split('\t') for row in (directory.parent / 'b0/loop.tsv').read_text().splitlines()[1:]]
    assert [row[3] for row in rows] == ['walk-start', 'walk-pause', 'walk-resume', 'walk-pause']
    assert rows[-1][4] == 'kind forgejo attempt 2: ' + 'x' * 200
    lab.run('walk', 'fabrig', 'b0', '--resume', 'rung-b0-1', '--build', 'main')
    lab.end_run(lab.walk_state()[1])
    lab.watch()
    rows = [row.split('\t') for row in (directory.parent / 'b0/loop.tsv').read_text().splitlines()[1:]]
    assert rows[-2][3] == 'walk-resume' and rows[-2][4].startswith('kind forgejo attempt 3: ')
    assert rows[-1][3] == 'walk-end' and (directory / 'report-2.md').is_file()


def an_interrupted_resume_releases_only_its_new_grant(lab):
    directory, state = walk_with_logins(lab, CHATGPT)
    state = pause_walk(lab, directory, state)
    previous = state['attempts'][0]
    driven_walk(lab, '''Watch = tool['Watch']
original = Watch.call
def call(self, name, *args):
    result = original(self, name, *args)
    if name == 'logins' and args[0] == 'take' and result.returncode == 0:
        os._exit(77)
    return result
Watch.call = call
''', '--resume', 'rung-b0-1', '--build', 'main', status=77)
    assert not lab.walk_state()[1]['logins'] and lab.walk_state()[1]['attempt'] == 2
    lab.watch()
    current = lab.walk_state()[1]
    assert current['stage'] == 'paused' and current['released'] and current['attempts'][0] == previous
    assert not current['run'] and len(lab.calls('codex-run')) == 1
    assert lab.calls('logins').count(['give', CHATGPT, '--as', state['holder']]) == 2


def an_accepted_resume_recovers_only_its_new_run(lab):
    directory, state = walk_with_logins(lab, CHATGPT)
    state = pause_walk(lab, directory, state)
    previous = state['attempts'][0]
    driven_walk(lab, '''Watch = tool['Watch']
original = Watch.call
def call(self, name, *args):
    result = original(self, name, *args)
    if name == 'codex-run':
        result.returncode = 124
    return result
Watch.call = call
''', '--resume', 'rung-b0-1', '--build', 'main', status=1)
    assert lab.walk_state()[1]['stage'] == 'starting'
    lab.watch()
    current = lab.walk_state()[1]
    assert current['stage'] == 'running' and current['run'] == 'fixture-2'
    assert current['attempts'][0] == previous and not current['given']
    assert lab.calls('logins').count(['give', CHATGPT, '--as', state['holder']]) == 1


def a_resume_without_its_meta_starts_fresh(lab):
    directory, state = walk_with_logins(lab)
    state = pause_walk(lab, directory, state)
    (lab.tmp / 'codex-run' / state['run'] / 'meta').unlink()
    lab.run('walk', 'fabrig', 'b0', '--resume', 'rung-b0-1', '--build', 'main')
    assert lab.walk_state()[1]['stage'] == 'running' and lab.walk_state()[1]['run'] == 'fixture-2'
    assert len(lab.calls('codex-run')) == 3




def damaged_attempt_history_keeps_walk_custody(lab):
    directory, state = walk_with_logins(lab, CHATGPT)
    saved = lab.tmp / 'qa/walks/rung-b0-1.json'
    original = saved.read_bytes()
    for corruption in (dict(state, attempts=[None]), dict(state, deployments=[None]),
                       dict(state, alerts={CHATGPT: {'director@fixture': 'false'}}),
                       dict(state, attempts=[dict(state['attempts'][0], alerts={CHATGPT: []})]),
                       dict(state, kind='', holder='walk/' + state['walk']),
                       dict(state, report_attempt='../outside'), dict(state, attempts=[{}])):
        saved.write_text(json.dumps(corruption))
        result = lab.watch()
        assert 'invalid walk state; keeping custody' in result.stdout
        assert ['give', CHATGPT, '--as', state['holder']] not in lab.calls('logins')
    saved.write_bytes(original)
    assert not lab.sent()


def a_saved_pause_decision_survives_its_marker_removal(lab):
    directory, state = walk_with_logins(lab)
    (directory / 'paused').write_text('original paused step\n')
    lab.end_run(state)
    driven_watch(lab, '''import os
Watch = tool['Watch']
original = Watch.save
def save(self, directory, state):
    original(self, directory, state)
    if state.get('decision') == 'walk-pause':
        os._exit(0)
Watch.save = save
''')
    assert lab.walk_state()[1]['decision'] == 'walk-pause' and not lab.walk_state()[1]['end_logged']
    (directory / 'paused').unlink()
    lab.watch()
    state = lab.walk_state()[1]
    assert state['stage'] == 'paused' and state['pause_line'] == 'original paused step'
    assert 'original paused step' in lab.sent()[0]['body']


def a_resume_refuses_pool_changes_but_accepts_its_cap(lab):
    directory, state = walk_with_logins(lab, CHATGPT)
    state = pause_walk(lab, directory, state)
    before = lab.calls('logins')
    lab.run('walk', 'fabrig', 'b0', '--resume', state['walk'], '--build', 'main', '--login', CLAUDE, status=2)
    assert lab.calls('logins') == before
    lab.run('walk', 'fabrig', 'b0', '--resume', state['walk'], '--build', 'main', '--cap', '1')
    current = lab.walk_state()[1]
    assert current['cap'] == 1 and current['requests'] == [CHATGPT] and current['pools'] == {CHATGPT: CHATGPT}
    assert current['attempts'][0] == state['attempts'][0]
    lab.end_run(current)
    lab.watch()
    assert lab.walk_state()[1]['given'] == [CHATGPT]


def an_old_pending_end_does_not_turn_into_a_pause(lab):
    directory, state = walk_with_logins(lab)
    lab.end_run(state)
    lab.watch(extra={'QA_POST_STATUS': '2'})
    state = lab.walk_state()[1]
    for key in ('decision', 'attempt', 'attempts', 'report_attempt'):
        state.pop(key, None)
    (lab.tmp / 'qa/walks/rung-b0-1.json').write_text(json.dumps(state))
    (directory / 'paused').write_text('a marker added after the old end\n')
    lab.watch()
    current = lab.walk_state()[1]
    assert current['stage'] == 'ended' and current['decision'] == 'walk-end'
    assert current['attempt'] == 1 and len(current['attempts']) == 1
    assert all(post['args'][2] == 'qa: walk rung-b0-1 ended' for post in lab.sent())


def walks_of_two_kinds_take_their_own_slots_and_pools(lab):
    focused = lab.tmp / 'qa-focused'
    focused.mkdir()
    (focused / 'rung-b0-claude-brief.md').write_bytes(b'Claude-specific rung brief.\n')
    lab.walk('b0')
    lab.walk('b0', '--kind', 'claude')
    first, second = lab.walk_states()
    assert first[1]['walk'] == 'rung-b0-1' and first[1]['kind'] == 'forgejo'
    assert first[1]['holder'] == 'walk/forgejo/rung-b0-1' and first[1]['pools'] == {CHATGPT: CHATGPT}
    assert second[1]['walk'] == 'rung-b0-claude-1' and second[1]['kind'] == 'claude'
    assert second[1]['holder'] == 'walk/claude/rung-b0-claude-1' and second[1]['pools'] == {CLAUDE: CLAUDE}
    assert [call[-2] for call in lab.calls('codex-run')] == [
        str(lab.slots / '1'), str(lab.slots / '3')]
    assert (second[0] / 'brief.md').read_bytes() == (focused / 'rung-b0-claude-brief.md').read_bytes()
    rows = [row.split('\t') for row in (focused / 'b0/loop.tsv').read_text().splitlines()[1:]]
    assert [row[2] for row in rows] == ['1', 'claude-1']
    assert all('--now' in call and '--wait' not in call for call in lab.calls('logins') if call[0] == 'take')


def a_kind_at_its_cap_queues_at_once(lab):
    lab.walk('b0')
    lab.walk('b0')
    before = [call for call in lab.calls('logins') if call[0] == 'take']
    result = lab.walk('another', status=0)
    assert 'queued ' in result.stdout and all('kind forgejo holds 2' in e['reason'] for e in queued_entries(lab))
    assert [call for call in lab.calls('logins') if call[0] == 'take'] == before
    directory, state = lab.walk_states()[0]
    lab.end_run(state)
    lab.configure(logins_out=[CHATGPT])
    lab.watch()
    current = lab.walk_states()[0][1]
    assert current['released'] and current['decision'] == 'walk-end' and not current['given']
    result = lab.walk('another', status=0)
    assert 'queued ' in result.stdout and all('kind forgejo holds 2' in e['reason'] for e in queued_entries(lab))
    assert [call for call in lab.calls('logins') if call[0] == 'take'] == before


def login_refuses_another_kinds_pool(lab):
    lab.walk('b0', '--kind', 'claude', '--login', CHATGPT, status=2)
    lab.walk('b0', '--kind', '', status=2)
    lab.walk('b0', '--kind', 'unknown', status=2)
    assert all(row == ['list'] for row in lab.calls('logins')) and not lab.calls('codex-run')
    assert all(s['released'] and s['slot_claim']['released'] for _, s in lab.walk_states())


def a_resume_by_name_keeps_its_kind(lab):
    resting(lab, CLAUDE)
    lab.walk('b0', '--kind', 'claude')
    directory, state = lab.walk_state()
    state = pause_walk(lab, directory, state)
    lab.walk('b1', '--kind', 'claude')
    lab.walk('b2', '--kind', 'claude')
    before = [call for call in lab.calls('logins') if call[0] == 'take']
    result = lab.run('walk', 'fabrig', 'b0', '--resume', state['walk'], '--build', 'main', status=0)
    assert 'queued ' + state['walk'] in result.stdout
    assert [call for call in lab.calls('logins') if call[0] == 'take'] == before
    lab.end_run(lab.walk_states()[1][1])
    lab.watch()
    assert not queued_entries(lab)
    current = lab.walk_states()[0][1]
    assert current['kind'] == 'claude' and current['pools'] == {CLAUDE: CLAUDE}
    assert current['slot'] == 3 and current['holder'] == state['holder'] and current['attempt'] == 2
    assert lab.calls('codex-run')[-1][-2] == str(lab.slots / '3')


def manual_kind_holders_stay_held_when_watcher_checks(lab):
    resting(lab, CHATGPT, in_place=True)
    lab.configure(logins_held=[CHATGPT], login_holders={CHATGPT: 'walk/forgejo/manual'})
    lab.watch()
    assert not [call for call in lab.calls('logins') if call[0] == 'give']
    lab.walk('b0')
    directory, state = lab.walk_state()
    assert state['pools'] == {CHATGPT: 'chatgpt-2'}
    result = lab.walk('b1', status=0)
    assert 'queued ' in result.stdout
    lab.run('queue', 'cancel', queued_entries(lab)[0]['id'])
    lab.end_run(state)
    lab.watch()
    config = json.loads((lab.root / 'tools.json').read_text())
    assert config['logins_held'] == [CHATGPT] and config['login_holders'][CHATGPT] == 'walk/forgejo/manual'
    assert [row['args'][1] for row in lab.sent()] == ['director@fixture', state['starter']]


def a_busy_now_take_queues_and_undoes_the_attempt(lab):
    lab.configure(logins_busy=[CHATGPT])
    result = lab.walk('b0', status=0)
    assert 'queued ' in result.stdout and 'login pool chatgpt is busy' in queued_entries(lab)[0]['reason']
    state = lab.walk_state()[1]
    assert state['released'] and state['stage'] == 'ended' and not state['run']
    takes = [call for call in lab.calls('logins') if call[0] == 'take']
    assert len(takes) == 1 and '--now' in takes[0] and '--wait' not in takes[0]
    assert not json.loads((lab.root / 'tools.json').read_text())['login_queue']


def pre_kind_walks_drain_before_kind_admission(lab):
    lab.walk('b0')
    directory, state = lab.walk_state()
    for key in ('kind', 'clock_walk'):
        state.pop(key)
    state['holder'] = 'walk/' + state['walk']
    saved = lab.tmp / 'qa/walks' / (state['walk'] + '.json')
    saved.write_text(json.dumps(state))
    lab.configure(login_holders={CHATGPT: state['holder']})
    before = lab.calls('logins')
    assert 'pre-kind walks still hold slots' in lab.walk('b1', status=1).stderr
    assert lab.calls('logins') == before
    lab.end_run(state)
    lab.watch()
    assert ['give', CHATGPT, '--as', state['holder']] in lab.calls('logins')
    lab.walk('b1')
    assert lab.walk_states()[-1][1]['kind'] == 'forgejo'


def numbering_survives_a_change_of_default_kind(lab):
    lab.walk('b0')
    lab.end_run(lab.walk_state()[1])
    lab.watch()
    lab.env['QA_WALK_KINDS'] = 'claude=2:claude forgejo=2:chatgpt'
    lab.walk('b0', '--kind', 'forgejo')
    state = next(state for _, state in lab.walk_states() if state['walk'] == 'rung-b0-forgejo-2')
    lab.end_run(state)
    lab.watch()
    lab.walk('b0')
    state = next(state for _, state in lab.walk_states() if state['kind'] == 'claude')
    assert state['walk'] == 'rung-b0-2'  # The first filename is occupied by the earlier default.
    lab.end_run(state)
    lab.watch()
    rows = [row.split('\t') for row in (lab.tmp / 'qa-focused/b0/loop.tsv').read_text().splitlines()[1:]]
    assert [row[3] for row in rows] == ['walk-start', 'walk-end'] * 3
    assert [row[2] for row in rows[::2]] == ['1', 'forgejo-2', '2']
    (lab.tmp / 'qa-focused/rung-b0-claude-7').mkdir()
    lab.walk('b0')
    current = next(state for _, state in lab.walk_states() if state['walk'] == 'rung-b0-8')
    assert current['kind'] == 'claude'


def a_walk_reads_its_inventory_strictly(lab):
    lab.configure(list_lines=[f'{CHATGPT}: at rest'])
    result = lab.walk('b0', status=1)
    assert 'cannot read login inventory for walk admission' in result.stderr
    assert lab.calls('logins') == [['list']] and not lab.walk_states() and not lab.calls('codex-run')




def a_unit_created_during_launcher_scan_keeps_its_custody(lab):
    lab.walk('b0', now='2026-10-27T08:00:00Z')
    walk_directory, walk = lab.walk_state()
    run = lab.tmp / 'codex-run' / walk['run']
    (run / 'unit').unlink()
    clock = datetime(2026, 10, 27, 8, tzinfo=timezone.utc).timestamp()
    os.utime(run / 'meta', (clock, clock))
    patch = '''original = tool['Watch'].launcher_alive
def launcher_alive(self, meta):
    result = original(self, meta)
    assert result is False
    (meta.parent / 'unit').touch()
    return result
tool['Watch'].launcher_alive = launcher_alive
tool['main'].__globals__['timestamp'] = lambda: '2026-10-27T08:11:00Z'
'''
    driven_watch(lab, patch)
    current_walk = lab.walk_state()[1]
    assert current_walk['stage'] == 'running' and not current_walk['released'] and not current_walk['given']
    assert not any(args[0] == 'give' for args in lab.calls('logins'))



def orphaned_take_keeps_admission(lab, mode):
    lab.env['QA_WALK_SLOTS'] = 'forgejo=1 claude=3,4'
    lab.env['QA_WALK_KINDS'] = 'forgejo=1:chatgpt'
    if mode == 'take':
        args = ['take', 'forgejo', '--as', 'walk/forgejo/manual']
    else:
        brief = lab.tmp / 'qa-focused/rung-b0-brief.md'
        brief.parent.mkdir(parents=True)
        brief.write_text('Admission fixture.\n')
        args = ['walk', 'fabrig', 'b0']
        if mode == 'resume':
            lab.walk('b0')
            directory, state = lab.walk_state()
            state = pause_walk(lab, directory, state)
            args += ['--resume', state['walk'], '--build', 'main']
    lab.configure(delay_take=True)
    with (lab.root / 'first-output').open('w') as output, (lab.root / 'second-output').open('w') as second_output:
        starter = subprocess.Popen([str(SCRIPT), *args], env=lab.env, cwd=lab.root,
                                   stdin=subprocess.DEVNULL, stdout=output, stderr=output)
        child = second = None
        try:
            waiting = lab.root / 'take-waiting'
            wait_for(waiting.exists)
            child = int(waiting.read_text())
            os.kill(child, signal.SIGSTOP)
            starter.kill()
            assert starter.wait(timeout=10) == -signal.SIGKILL and alive(child)
            lock = lab.tmp / 'qa' / ('watch.lock' if mode == 'watch' else 'walks.lock')
            with lock.open('a') as probe:
                try:
                    fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    pass
                else:
                    raise AssertionError('orphan take lost its admission lock')
            calls = lab.calls('logins')
            if mode == 'watch':
                result = lab.watch(status=2)
                assert 'another service runs' in result.stderr
            else:
                marker = lab.root / 'second-waiting'
                driver = f'''import runpy, sys
from pathlib import Path
tool = runpy.run_path({str(SCRIPT)!r})
original = tool['fcntl'].flock
def flock(fd, operation):
    if operation == tool['fcntl'].LOCK_EX:
        Path({str(marker)!r}).touch()
    return original(fd, operation)
tool['fcntl'].flock = flock
sys.exit(tool['main']())
'''
                second = subprocess.Popen([sys.executable, '-I', '-B', '-c', driver, 'take', 'forgejo',
                                           '--as', 'walk/forgejo/second'], env=lab.env, cwd=lab.root,
                                          stdin=subprocess.DEVNULL, stdout=second_output, stderr=second_output)
                wait_for(marker.exists)
                try:
                    second.wait(timeout=0.2)
                except subprocess.TimeoutExpired:
                    pass
                else:
                    raise AssertionError('second admission did not wait for the orphan take')
            assert lab.calls('logins') == calls
            (lab.root / 'allow-take').touch()
            os.kill(child, signal.SIGCONT)
            dead(child)
            if second is not None:
                assert second.wait(timeout=10) == 1
                assert 'kind forgejo holds 1 of its 1 logins of pool chatgpt' in (lab.root / 'second-output').read_text()
                assert len(lab.calls('logins')) == len(calls) + 1  # Only its listing; no second take.
            lab.configure(delay_take=False)
            if mode == 'take':
                lab.watch()
                config = json.loads((lab.root / 'tools.json').read_text())
                assert config['login_holders'][CHATGPT] == 'walk/forgejo/manual'
                lab.run('give', CHATGPT, '--as', 'walk/forgejo/manual')
            else:
                lab.watch()
                if mode == 'watch':
                    assert lab.watch_state()[1]['run']
                else:
                    assert lab.walk_state()[1]['released']
        finally:
            (lab.root / 'allow-take').touch()
            if starter.poll() is None:
                starter.kill()
                starter.wait(timeout=10)
            if second is not None and second.poll() is None:
                second.kill()
                second.wait(timeout=10)
            if child is not None:
                if alive(child):
                    os.kill(child, signal.SIGCONT)
                dead(child)








def a_take_by_hand_is_refused_past_its_kinds_cap(lab):
    lab.env['QA_WALK_SLOTS'] = 'forgejo=1 github=5'
    lab.env['QA_WALK_KINDS'] = 'forgejo=1:chatgpt github=1:chatgpt'
    lab.configure(pools={CHATGPT: [CHATGPT, 'chatgpt-2', 'chatgpt-3', 'chatgpt-4']})
    head = lab.head()
    result = lab.run('take', 'github', '--as', 'walk/github/manual')
    assert result.stdout == f'{CHATGPT} {lab.root}/login-store/{CHATGPT}/login\n'
    assert lab.calls('logins') == [['list'], ['take', CHATGPT, '--any', '--now', '--as', 'walk/github/manual']]
    assert not lab.walk_states() and lab.head() == head
    result = lab.run('take', 'github', '--as', 'walk/github/manual-2', status=1)
    assert result.stderr == 'qa: kind github holds 1 of its 1 logins of pool chatgpt\n'
    calls = lab.calls('logins')
    lab.run('take', 'github', '--as', 'walk/forgejo/x', status=2)
    assert lab.calls('logins') == calls
    lab.walk('b0')
    walk = lab.walk_state()[1]
    assert walk['kind'] == 'forgejo' and walk['pools'] == {CHATGPT: 'chatgpt-2'}
    lab.watch()
    config = json.loads((lab.root / 'tools.json').read_text())
    assert config['login_holders'][CHATGPT] == 'walk/github/manual'
    lab.run('give', CHATGPT, '--as', 'walk/github/manual')
    assert lab.run('give', CHATGPT, '--as', 'walk/github/manual').stdout == 'already free: chatgpt\n'
    result = lab.run('take', 'github', '--as', 'walk/github/manual-2')
    assert result.stdout == f'{CHATGPT} {lab.root}/login-store/{CHATGPT}/login\n'
    assert len(lab.walk_states()) == 1 and not lab.watch_states()
    assert not json.loads((lab.root / 'tools.json').read_text())['login_queue']


def manual_login_commands_refuse_invalid_inputs_before_tools(lab):
    for args in (('take', 'missing', '--as', 'walk/missing/x'),
                 ('take', 'forgejo', '--as', 'walk/claude/x'),
                 ('take', 'forgejo', '--login', CLAUDE, '--as', 'walk/forgejo/x'),
                 ('take', 'forgejo', '--login', 'chatgpt-2', '--as', 'walk/forgejo/x')):
        lab.run(*args, status=2)
    for holder in ('qa-watch/x', 'walk/forgejo', 'walk/forgejo/-x', 'walk/forgejo/x_y',
                   'walk/forgejo/x/y', 'walk/Forgejo/x'):
        lab.run('take', 'forgejo', '--as', holder, status=2)
        lab.run('give', CHATGPT, '--as', holder, status=2)
    lab.run('give', 'Bad', '--as', 'walk/forgejo/x', status=2)
    lab.run('take', 'forgejo', status=2)
    lab.run('give', CHATGPT, status=2)
    assert not lab.calls('logins') and not (lab.tmp / 'qa').exists()


def manual_and_generated_walk_holders_never_share_custody(lab):
    holder = 'walk/forgejo/rung-b0-1'
    lab.run('take', 'forgejo', '--as', holder)
    lab.walk('b0')
    directory, walk = lab.walk_state()
    assert walk['walk'] == 'rung-b0-2' and walk['holder'] != holder
    assert walk['pools'] == {CHATGPT: 'chatgpt-2'}
    lab.watch()
    assert not any(args[0] == 'give' for args in lab.calls('logins'))
    lab.run('give', CHATGPT, '--as', holder)
    before = lab.calls('logins')
    result = lab.run('take', 'forgejo', '--as', walk['holder'], status=1)
    assert 'holder name already belongs to a saved walk' in result.stderr
    assert lab.calls('logins') == before
    lab.end_run(walk)
    lab.watch()
    assert lab.walk_state()[1]['stage'] == 'ended'
    before = lab.calls('logins')
    lab.run('take', 'forgejo', '--as', walk['holder'], status=1)
    assert lab.calls('logins') == before
    # The earlier generated-looking manual name stays usable once given back.
    lab.run('take', 'forgejo', '--as', holder)
    lab.watch()
    config = json.loads((lab.root / 'tools.json').read_text())
    assert config['login_holders'][CHATGPT] == holder
    assert lab.calls('logins').count(['give', CHATGPT, '--as', holder]) == 1


def a_manual_take_selects_its_pool_and_give_passes_through(lab):
    lab.env['QA_WALK_KINDS'] = 'both=2:claude,chatgpt'
    note = 'recovery $(literal); `literal` $HOME'
    result = lab.run('take', 'both', '--as', 'walk/both/first', '--note', note)
    assert result.stdout == f'{CLAUDE} {lab.root}/login-store/{CLAUDE}/login\n'
    assert lab.calls('logins')[-1] == ['take', CLAUDE, '--any', '--now', '--as', 'walk/both/first', '--note', note]
    lab.run('take', 'both', '--login', CHATGPT, '--as', 'walk/both/second', '--note', '')
    assert lab.calls('logins')[-1] == ['take', CHATGPT, '--any', '--now', '--as', 'walk/both/second', '--note', '']
    result = lab.run('give', CHATGPT, '--as', 'walk/both/first', status=2)
    assert result.stdout == '' and result.stderr == 'fixture held by another\n'
    lab.configure(logins_out=[CHATGPT])
    result = lab.run('give', CHATGPT, '--as', 'walk/both/second', status=1)
    assert result.stdout == '' and result.stderr == 'fixture login out\n'
    # Recovery must work after a kind is retired, even with broken current settings.
    lab.env['QA_WALK_KINDS'] = 'broken'
    lab.configure(logins_out=[], logins_refused=[CHATGPT])
    result = lab.run('give', CHATGPT, '--as', 'walk/both/second', status=4)
    assert result.stderr == 'fixture login refused\n'
    lab.configure(logins_refused=[])
    lab.run('give', CHATGPT, '--as', 'walk/both/second')
    assert lab.run('give', CHATGPT, '--as', 'walk/both/second').stdout == 'already free: chatgpt\n'
    assert not lab.walk_states() and not lab.watch_states() and not lab.calls('codex-run')


def a_manual_take_refuses_unknown_inventory_and_a_broken_cap(lab):
    for config in ({'list_lines': ['unexpected listing']}, {'list_lines': ['chatgpt: at rest']},
                   {'login_list_failure': True}):
        lab.configure(list_lines=[], login_list_failure=False)
        lab.configure(**config)
        result = lab.run('take', 'forgejo', '--as', 'walk/forgejo/manual', status=1)
        assert 'cannot read login inventory for walk admission' in result.stderr
    assert all(args == ['list'] for args in lab.calls('logins'))
    lab.configure(list_lines=[], login_list_failure=False, logins_busy=[CHATGPT])
    result = lab.run('take', 'forgejo', '--as', 'walk/forgejo/manual', status=1)
    assert result.stderr == 'qa: the caps are broken: fixture login busy\n'
    assert lab.calls('logins')[-1] == ['take', CHATGPT, '--any', '--now', '--as', 'walk/forgejo/manual']
    assert not json.loads((lab.root / 'tools.json').read_text())['login_queue']
    assert not lab.walk_states() and not lab.watch_states()








def queued_and_running_start_jobs_keep_custody(lab):
    directory, state = walk_with_logins(lab, CHATGPT)
    lab.env['QA_WALK_SLOTS'] = 'forgejo=1 claude=3,4'
    lab.env['QA_WALK_KINDS'] = 'forgejo=1:chatgpt'
    for job in ('42', '43', 'unknown', '-1', '0 waiting'):
        lab.configure(unit_load='loaded', unit_state='inactive', unit_job=job)
        lab.watch()
        saved = lab.walk_state()[1]
        assert saved['stage'] == 'running' and not saved['given'] and not saved['released']
        assert not any(args[0] == 'give' for args in lab.calls('logins'))
        lab.walk('other', '--login', CHATGPT)
        lab.run('queue', 'cancel', queued_entries(lab)[0]['id'])
    # Even a worker completion marker cannot overrule a pending start.
    lab.end_run(state)
    lab.configure(unit_job='44')
    lab.watch()
    assert not lab.walk_state()[1]['given'] and not lab.walk_state()[1]['released']
    lab.configure(unit_job='0')
    lab.watch()
    assert lab.walk_state()[1]['given'] == [CHATGPT] and lab.walk_state()[1]['released']


def a_job_created_during_launcher_scan_keeps_custody(lab):
    directory, state = walk_with_logins(lab, CHATGPT)
    lab.configure(unit_load='loaded', unit_state='inactive')
    patch = """def launcher_alive(self, meta):
    path = self.workspace.root / 'tools.json'
    config = json.loads(path.read_text())
    config['unit_job'] = '42'
    temporary = path.with_name(path.name + '.new')
    temporary.write_text(json.dumps(config))
    temporary.replace(path)
    return False
import json
tool['Watch'].launcher_alive = launcher_alive
"""
    driven_watch(lab, patch)
    saved = lab.walk_state()[1]
    assert saved['stage'] == 'running' and not saved['given'] and not saved['released']
    assert not any(args[0] == 'give' for args in lab.calls('logins'))


def a_non_dumpable_process_does_not_block_walk_cleanup(lab):
    directory, state = walk_with_logins(lab, CHATGPT)
    lab.end_run(state)
    (lab.tmp / 'codex-run' / state['run'] / 'unit').unlink()
    # Fixture entries use live fixture PIDs so prune_dead_launchers retains them.
    foreign = lab.root / 'proc' / str(os.getpid()) / 'cmdline'
    launcher = lab.root / 'proc' / str(os.getppid()) / 'cmdline'
    for path in (foreign, launcher):
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(b'\0'.join(os.fsencode(word) for word in
                         (lab.root / 'codex-run', 'task', directory / 'task.md')) + b'\0')
    # Reuse the descriptor-ownership simulation from the unsafe-metadata cases;
    # only this fixture inode looks unowned, with no chown or real /proc access.
    patch = f'''import os
from pathlib import Path
from types import SimpleNamespace
original_fstat = os.fstat
info = Path({str(foreign)!r}).stat()
def fstat(fd):
    actual = original_fstat(fd)
    if (actual.st_dev, actual.st_ino) == (info.st_dev, info.st_ino):
        return SimpleNamespace(st_mode=actual.st_mode, st_nlink=actual.st_nlink,
                               st_uid=os.getuid() + 1)
    return actual
os.fstat = fstat
'''
    driven_watch(lab, patch)
    saved = lab.walk_state()[1]
    assert not saved['given'] and not saved['released'] and not saved['posted']
    assert not any(args[0] == 'give' for args in lab.calls('logins'))
    launcher.unlink()
    launcher.parent.rmdir()
    result = driven_watch(lab, patch)
    saved = lab.walk_state()[1]
    assert saved['stage'] == 'ended' and saved['given'] == [CHATGPT]
    assert saved['released'] and saved['posted'] and saved['end_logged']
    assert 'cleanup failed' not in result.stdout + result.stderr
    assert lab.sent()[-1]['args'][1:3] == [saved['starter'], 'qa: walk rung-b0-1 ended']


def an_ended_not_found_session_with_an_empty_job_releases_custody(lab):
    directory, state = walk_with_logins(lab, CHATGPT)
    lab.end_run(state)
    (lab.tmp / 'codex-run' / state['run'] / 'unit').unlink()
    # Real systemd reports LoadState=not-found, ActiveState=inactive, Job=.
    lab.watch()
    saved = lab.walk_state()[1]
    assert saved['stage'] == 'ended' and saved['given'] == [CHATGPT]
    assert saved['released'] and saved['posted'] and saved['end_logged']
    assert lab.sent()[-1]['args'][1:3] == [saved['starter'], 'qa: walk rung-b0-1 ended']
    assert not [args for args in lab.calls('systemctl') if args[1] == 'stop']


def a_missing_walk_unit_is_ended_after_the_launch_grace(lab):
    lab.walk('b0', '--login', CHATGPT, now='2026-10-27T08:00:00Z')
    directory, state = lab.walk_state()
    run = lab.tmp / 'codex-run' / state['run']
    (run / 'unit').unlink()
    clock = datetime(2026, 10, 27, 8, tzinfo=timezone.utc).timestamp()
    os.utime(run / 'meta', (clock, clock))
    lab.watch(now='2026-10-27T08:09:59Z')
    saved = lab.walk_state()[1]
    assert saved['stage'] == 'running' and not saved['given'] and not saved['released']
    lab.watch(now='2026-10-27T08:11:00Z')
    saved = lab.walk_state()[1]
    assert saved['stage'] == 'ended' and saved['given'] == [CHATGPT] and saved['released']
    assert not [args for args in lab.calls('systemctl') if args[1] == 'stop']


def a_resumed_launch_without_a_unit_keeps_its_new_grant(lab):
    directory, state = walk_with_logins(lab, CHATGPT)
    state = pause_walk(lab, directory, state)
    previous = state['attempts'][0]
    lab.configure(logins_held=[CHATGPT], login_holders={CHATGPT: 'director/manual'})
    driven_walk(lab, '''Watch = tool['Watch']
original = Watch.call
def call(self, name, *args):
    result = original(self, name, *args)
    if name == 'codex-run':
        os._exit(77)
    return result
Watch.call = call
''', '--resume', state['walk'], '--build', 'main', status=77)
    (lab.tmp / 'codex-run/fixture-2/unit').unlink()
    lab.watch()
    current = lab.walk_state()[1]
    assert current['run'] == 'fixture-2' and current['stage'] == 'running' and not current['released']
    assert current['pools'] == {CHATGPT: 'chatgpt-2'} and not current['given']
    assert current['attempts'][0] == previous
    assert not any(args[0] == 'give' and args[1] == 'chatgpt-2' for args in lab.calls('logins'))
    (lab.tmp / 'codex-run/fixture-2/unit').touch()
    lab.end_run(current)
    lab.watch()
    assert lab.walk_state()[1]['given'] == ['chatgpt-2'] and lab.walk_state()[1]['released']
    assert lab.calls('logins').count(['give', CHATGPT, '--as', state['holder']]) == 1


def a_walk_resolves_remote_branches_despite_colliding_tags(lab):
    old = lab.git(lab.products['fabrig'], 'rev-parse', 'HEAD')
    main = lab.marked()
    fix = lab.commit('remote fix', branch='fix')
    origin = lab.origins / 'fabrig.git'
    lab.git(origin, 'tag', 'origin/fix', old)
    lab.git(origin, 'tag', 'origin/main', old)
    lab.walk('b0', '--build', 'origin/fix')
    lab.walk('b0')
    first, second = lab.walk_states()
    assert first[1]['main'] == fix and second[1]['main'] == main
    assert lab.git(lab.slots / '1', 'rev-parse', 'HEAD') == fix
    assert lab.git(lab.slots / '2', 'rev-parse', 'HEAD') == main




def a_bare_branch_resolves_to_origins(lab):
    main = lab.marked()
    fix = lab.commit('bare branch fix', branch='fix')
    # A branch moving after resolution must not change the saved build.
    driver = f'''original = tool['Repositories'].checkout
def checkout(self, root, main):
    tool['git'](root, 'update-ref', 'refs/remotes/origin/fix', {main!r})
    return original(self, root, main)
tool['Repositories'].checkout = checkout
'''
    lab.walk('b0', '--build', 'fix')
    driven_walk(lab, driver, '--build', 'origin/fix')
    first, second = lab.walk_states()
    assert first[1]['ref'] == 'fix' and second[1]['ref'] == 'origin/fix'
    assert first[1]['main'] == second[1]['main'] == fix
    for slot in (1, 2):
        assert lab.git(lab.slots / str(slot), 'rev-parse', 'HEAD') == fix
    assert lab.git(lab.slots / '2', 'rev-parse', 'refs/remotes/origin/fix') == main




def a_build_never_resolves_through_a_tag_or_a_stale_ref(lab):
    old = lab.marked()
    checkout = lab.products['fabrig']
    # A tag spelled as the tracking ref, with no branch of that name on origin.
    lab.git(checkout, 'tag', 'refs/remotes/origin/fix', old)
    lab.git(checkout, 'push', 'origin', 'refs/tags/refs/remotes/origin/fix')
    result = lab.walk('b0', '--build', 'fix', '--login', CHATGPT, status=2)
    assert 'no branch origin/fix and no commit' in result.stderr
    # A branch fetched once, then deleted on origin.
    gone = lab.commit('a fix branch later deleted', branch='gone')
    lab.walk('unused', '--build', 'missing', status=2)
    assert lab.git(lab.slots / '1', 'rev-parse', 'refs/remotes/origin/gone') == gone
    lab.git(checkout, 'push', 'origin', ':gone')
    result = lab.walk('b0', '--build', 'gone', '--login', CHATGPT, status=2)
    assert 'no branch origin/gone and no commit' in result.stderr
    assert all(row == ['list'] for row in lab.calls('logins')) and not lab.calls('codex-run')
    assert all(s['released'] and s['slot_claim']['released'] for _, s in lab.walk_states())






TIMEOUT_DRIVER = """import os, time
from pathlib import Path
subprocess = tool['subprocess']
original_popen = subprocess.Popen
class ReadyPopen(original_popen):
    def communicate(self, input=None, timeout=None):
        if timeout == 0.3:
            # Start the short deadline only after the intended side effect.
            marker = Path(os.environ['QA_FIXTURE']) / 'hung-tool'
            deadline = time.monotonic() + 300
            while not (marker.exists() and marker.read_text() == str(self.pid)):
                if self.poll() is not None or time.monotonic() >= deadline:
                    self.kill()
                    super().communicate()
                    raise AssertionError('fixture tool never reached its hang')
                time.sleep(0.01)
        return super().communicate(input=input, timeout=timeout)
subprocess.Popen = ReadyPopen
original = tool['command']
def command(argv, cwd=None, timeout=None, pass_fds=(), **kwargs):
    name = str(argv[0]).rsplit('/', 1)[-1]
    expected = {'claim': 60, 'ssh': 60, 'df': 30, 'python3': 300, 'cargo': 300, 'git': 300, 'systemctl': 30, 'logins': 60, 'post': 60, 'codex-run': 120}
    if kwargs.get('env', {}).get('GIT_NO_LAZY_FETCH') == '1':
        assert name == 'git' and 0 < timeout <= 120
    else:
        assert timeout == expected[name], (argv, timeout)
    operation = name + ':' + str(argv[1] if len(argv) > 1 else '')
    if operation in HUNG:
        timeout = 0.3
    return original(argv, cwd=cwd, timeout=timeout, pass_fds=pass_fds, **kwargs)
tool['main'].__globals__['command'] = command
"""


def a_fifo_stuck_list_does_not_block_cleanup(lab):
    unsafe_stuck_list(lab, 'fifo')
    path = lab.home / '.config/agents-qa/stuck'
    path.unlink()
    target = lab.root / 'stuck-target'
    target.write_text('design/linked@fixture\n')
    path.symlink_to(target)
    before = lab.sent()
    result = lab.watch()
    assert str(path) in result.stdout and 'cannot open safely' in result.stdout
    assert 'using director alone' in result.stdout
    assert lab.sent() == before and target.read_text() == 'design/linked@fixture\n'


def an_oversized_stuck_list_does_not_block_cleanup(lab):
    unsafe_stuck_list(lab, 'oversized')


def stuck_recipients_are_bounded_in_file_order(lab):
    path = lab.home / '.config/agents-qa/stuck'
    path.parent.mkdir(parents=True)
    limit = 'a' * (120 - len('@fixture')) + '@fixture'
    too_long = 'a' + limit
    long_line = 'design/long-line@fixture'.ljust(201)
    addresses = [f'design/team-{number}@fixture' for number in reversed(range(20))]
    text = '\n'.join([limit, too_long, long_line, limit, *addresses]) + '\n'
    path.write_text(text + '\n' * (16 * 1024 - len(text)))
    assert path.stat().st_size == 16 * 1024
    _, state = start_stuck_pass(lab, CHATGPT)
    result = lab.watch()
    expected = [limit, *addresses[:15], 'director@fixture']
    alerts = stuck_posts(lab)
    assert [post['args'][1] for post in alerts] == expected
    assert lab.watch_state()[1]['alerts'] == {CHATGPT: dict.fromkeys(expected, True)}
    for number in (2, 3):
        assert f'{path}:{number}: invalid stuck address; skipped' in result.stdout
    for invalid in (too_long, 'design/long-line@fixture'):
        assert invalid not in result.stdout + result.stderr
        assert all(invalid not in post['body'] for post in lab.sent())
    assert all(len(post['args'][1]) <= 120 for post in alerts)
    assert all(post['args'][2] == f'qa: login {CHATGPT} stuck in walk {state["walk"]}' for post in alerts)
    lab.watch()
    assert stuck_posts(lab) == alerts


def a_recipient_launch_error_does_not_block_the_other_alerts(lab):
    path = lab.home / '.config/agents-qa/stuck'
    path.parent.mkdir(parents=True)
    refused = ['design/oserror@fixture', 'design/problem@fixture']
    accepted = ['director@fixture', 'design/accepted@fixture']
    path.write_text('\n'.join(refused + accepted) + '\n')
    _, state = start_stuck_pass(lab, CHATGPT)
    result = driven_watch(lab, """original = tool['Watch'].call
def call(self, name, *args):
    if name == 'post' and args[0] == 'send':
        if args[-3] == 'design/oserror@fixture':
            raise OSError('fixture private launch failure')
        if args[-3] == 'design/problem@fixture':
            raise tool['Problem']('fixture private post problem', 4)
    return original(self, name, *args)
tool['Watch'].call = call
""")
    saved = lab.watch_state()[1]
    assert saved['stage'] == 'ending' and saved['released'] and not saved.get('notice')
    assert saved['alerts'] == {CHATGPT: dict(zip(refused + accepted, [False, False, True, True]))}
    assert [post['args'][1] for post in stuck_posts(lab)] == accepted
    assert lab.sent()[-1]['args'][2].startswith('qa: walk ') and CHATGPT in lab.sent()[-1]['body']
    for name in ('OSError', 'Problem'):
        assert f'alert for {CHATGPT} failed ({name}); trying next check' in result.stdout
    assert 'fixture private' not in result.stdout + result.stderr
    lab.watch()
    assert [post['args'][1] for post in stuck_posts(lab)] == accepted + refused
    assert all(lab.watch_state()[1]['alerts'][CHATGPT].values())
    before = lab.sent()
    lab.watch()
    assert lab.sent() == before and lab.watch_state()[1]['walk'] == state['walk']




def a_refused_alert_is_sent_again(lab):
    path = lab.home / '.config/agents-qa/stuck'
    path.parent.mkdir(parents=True)
    address = 'design/upgrades-draft@fixture'
    path.write_text(address + '\n')
    directory, _ = start_stuck_pass(lab, CHATGPT)
    lab.configure(post_status={address: 1})
    lab.watch()
    assert lab.watch_state()[1]['alerts'] == {CHATGPT: {address: False, 'director@fixture': True}}
    assert len(stuck_posts(lab)) == 2
    # Returning the login and changing the list cannot discard a saved delivery.
    lab.configure(logins_out=[])
    path.unlink()
    path.mkdir()
    aged(lab, directory)
    result = lab.watch()
    assert 'cannot read stuck addresses (IsADirectoryError)' in result.stdout
    assert directory.exists() and lab.watch_state()[1]['given'] == [CHATGPT]
    lab.configure(post_status={address: 3})
    lab.watch()
    assert directory.exists() and lab.walk_state()[1]['stage'] == 'ended'
    alerts = stuck_posts(lab)
    assert [post['args'][1] for post in alerts].count('director@fixture') == 1
    assert [post['args'][1] for post in alerts].count(address) == 3
    assert f'Login {CHATGPT} was stuck in walk ' in alerts[-1]['body']
    lab.watch()
    assert stuck_posts(lab) == alerts


def an_alert_goes_once_per_stuck_login(lab):
    path = lab.home / '.config/agents-qa/stuck'
    path.parent.mkdir(parents=True)
    address = 'design/upgrades-draft@fixture'
    path.write_text(address + '\n')
    _, state = start_stuck_pass(lab, CHATGPT, CLAUDE)
    lab.watch()
    alerts = stuck_posts(lab)
    assert len(alerts) == 4
    for login in (CHATGPT, CLAUDE):
        selected = [post for post in alerts if post['args'][2] == f'qa: login {login} stuck in walk {state["walk"]}']
        assert {post['args'][1] for post in selected} == {address, 'director@fixture'}
    lab.configure(logins_out=[CLAUDE])
    lab.watch()
    assert lab.watch_state()[1]['given'] == [CHATGPT]
    assert stuck_posts(lab) == alerts


def no_list_alerts_the_director_alone(lab):
    _, state = start_stuck_pass(lab, CHATGPT)
    lab.watch()
    alert, = stuck_posts(lab)
    assert alert['args'][1:3] == ['director@fixture', f'qa: login {CHATGPT} stuck in walk {state["walk"]}']
    assert lab.watch_state()[1]['alerts'] == {CHATGPT: {'director@fixture': True}}
    lab.watch()
    assert stuck_posts(lab) == [alert]


def the_stuck_list_is_read_at_each_check(lab):
    _, state = start_stuck_pass(lab, CHATGPT, CLAUDE)
    lab.configure(logins_out=[CHATGPT], logins_refused=[CLAUDE], wait=[0, 4])
    patch = """import json
from pathlib import Path
original = tool['Watch'].check
def check(self, options):
    original(self, options)
    path = Path.home() / '.config/agents-qa/stuck'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('design/upgrades-draft@fixture\\n')
    config = json.loads((self.workspace.root / 'tools.json').read_text())
    config.update(logins_out=['chatgpt', 'claude'], logins_refused=[])
    (self.workspace.root / 'tools.json').write_text(json.dumps(config))
tool['Watch'].check = check
"""
    driven_watch(lab, patch, once=False, status=2)
    alerts = stuck_posts(lab)
    assert len(alerts) == 3
    assert {(post['args'][2], post['args'][1]) for post in alerts} == {
        (f'qa: login {login} stuck in walk {state["walk"]}', address)
        for login, addresses in ((CHATGPT, ['director@fixture']),
                                 (CLAUDE, ['director@fixture', 'design/upgrades-draft@fixture']))
        for address in addresses}


def saved_alerts_retry_when_the_run_state_is_unknown(lab):
    directory, state = start_stuck_pass(lab, CHATGPT)
    (lab.tmp / 'codex-run' / state['run'] / 'ended').unlink()
    lab.configure(inactive=True)
    lab.watch(extra={'QA_POST_STATUS': '1'})
    assert lab.watch_state()[1]['stage'] == 'ending'
    assert lab.watch_state()[1]['alerts'] == {CHATGPT: {'director@fixture': False}}
    before = len(lab.calls('logins'))
    lab.configure(unit_query_failure=True)
    lab.watch()
    assert lab.watch_state()[1]['alerts'] == {CHATGPT: {'director@fixture': True}}
    assert not lab.watch_state()[1]['given'] and directory.exists()
    assert not any(args[0] == 'give' for args in lab.calls('logins')[before:])
    assert len(stuck_posts(lab)) == 2 and 'Deployment units are unknown.' in stuck_posts(lab)[-1]['body']
    lab.watch()
    assert len(stuck_posts(lab)) == 2


def start_stuck_pass(lab, *logins):
    directory, state = deployment_pass(lab, *logins)
    lab.end_run(state)
    lab.configure(logins_out=list(logins))
    return directory, state



def unsafe_stuck_list(lab, shape):
    _, first = start_stuck_pass(lab, CHATGPT)
    lab.env['QA_WALK_KINDS'] += ' claude=2:claude'
    lab.walk('b1', '--kind', 'claude')
    second = lab.walk_states()[1][1]
    lab.end_run(second)
    path = lab.home / '.config/agents-qa/stuck'
    path.parent.mkdir(parents=True)
    if shape == 'fifo':
        os.mkfifo(path)
    else:
        path.write_bytes(b'design/overflow@fixture\n' * 1000)
    result = lab.watch()
    reason = 'not a regular file' if shape == 'fifo' else 'exceeds 16 KiB'
    assert 'cannot read stuck addresses (' in result.stdout and reason in result.stdout
    assert str(path) in result.stdout and 'using director alone' in result.stdout
    states = dict((state['walk'], state) for _, state in lab.walk_states())
    assert states[first['walk']]['alerts'] == {CHATGPT: {'director@fixture': True}}
    assert states[second['walk']]['stage'] == 'ended'
    assert all('design/overflow@fixture' not in post['body'] for post in lab.sent())



def legacy_login_claims(lab):
    originals = {}
    for number in (7, 8, 9):
        state = dict(walk=f'rung-a-{number}', repo='temper', rung='a',
                     holder=f'walk/forgejo/rung-a-{number}',
                     logins={CHATGPT: str(lab.root / 'foreign-rest')} if number == 7 else {},
                     attempts=[dict(logins={CHATGPT: str(lab.root / 'old-foreign-rest')})])
        write_walk(lab, state)
        path = lab.tmp / 'qa/walks' / (state['walk'] + '.json')
        originals[path] = (path.read_bytes(), path.stat().st_mtime_ns)
    return originals


def assert_legacy_unchanged(originals):
    for path, original in originals.items():
        assert (path.read_bytes(), path.stat().st_mtime_ns) == original


def stale_legacy_claims_allow_a_fabrig_walk_to_end(lab):
    lab.walk()
    _, state = lab.walk_state()
    originals = legacy_login_claims(lab)
    lab.end_run(state)
    lab.watch()
    current = next(saved for _, saved in lab.walk_states() if saved['walk'] == state['walk'])
    assert current['stage'] == 'ended' and current['given'] == [CHATGPT]
    assert current['released'] and current['posted'] and current['slot_claim']['released']
    assert lab.calls('logins').count(['give', CHATGPT, '--as', state['holder']]) == 1
    assert_legacy_unchanged(originals)


def a_current_legacy_holder_keeps_its_login(lab):
    lab.walk()
    _, state = lab.walk_state()
    originals = legacy_login_claims(lab)
    holder = 'walk/forgejo/rung-a-8'  # Only a historical attempt names this login.
    lab.configure(login_holders={CHATGPT: holder})
    lab.end_run(state)
    result = lab.watch()
    assert f'{CHATGPT}: conflicting custody claims' in result.stdout and holder in result.stdout
    assert not any(call[0] == 'give' and call[1] == CHATGPT for call in lab.calls('logins'))
    assert json.loads((lab.root / 'tools.json').read_text())['login_holders'][CHATGPT] == holder
    assert_legacy_unchanged(originals)


def a_legacy_holder_is_protected_even_without_a_named_claim(lab):
    lab.walk()
    _, state = lab.walk_state()
    foreign = dict(walk='rung-a-7', repo='temper', rung='a',
                   holder='walk/forgejo/rung-a-7', logins={}, attempts=[])
    write_walk(lab, foreign)
    path = lab.tmp / 'qa/walks/rung-a-7.json'
    originals = {path: (path.read_bytes(), path.stat().st_mtime_ns)}
    lab.configure(login_holders={CHATGPT: foreign['holder']})
    lab.end_run(state)
    lab.watch()
    assert not any(call[0] == 'give' and call[1] == CHATGPT for call in lab.calls('logins'))
    assert json.loads((lab.root / 'tools.json').read_text())['login_holders'][CHATGPT] == foreign['holder']
    assert_legacy_unchanged(originals)


def unavailable_inventory_preserves_legacy_claims(lab):
    lab.walk()
    _, state = lab.walk_state()
    originals = legacy_login_claims(lab)
    lab.end_run(state)
    for config in ({'login_list_failure': True},
                   {'login_list_failure': False, 'list_lines': ['unreadable inventory']}):
        lab.configure(**config)
        result = lab.watch()
        assert 'cannot list stray logins:' in result.stdout
        assert f'{CHATGPT}: conflicting custody claims' in result.stdout
        assert not any(call[0] == 'give' for call in lab.calls('logins'))
        assert_legacy_unchanged(originals)
    lab.configure(list_lines=[])
    lab.watch()
    current = next(saved for _, saved in lab.walk_states() if saved['walk'] == state['walk'])
    assert current['stage'] == 'ended' and current['given'] == [CHATGPT]
    assert_legacy_unchanged(originals)


def an_unknown_login_holder_preserves_legacy_claims(lab):
    lab.walk()
    _, state = lab.walk_state()
    originals = legacy_login_claims(lab)
    lab.configure(logins_held=[], login_holders={}, pools={})
    lab.end_run(state)
    result = lab.watch()
    assert f'{CHATGPT}: conflicting custody claims' in result.stdout
    assert not any(call[0] == 'give' and call[1] == CHATGPT for call in lab.calls('logins'))
    assert_legacy_unchanged(originals)





def a_resume_recovers_its_thread_from_events(lab):
    directory, state = walk_with_logins(lab, CHATGPT)
    state = pause_walk(lab, directory, state)
    run = lab.tmp / 'codex-run' / state['run']
    (run / 'thread').unlink()
    (run / 'events.jsonl').write_text('{"type":"thread.started","thread_id":"fixture-thread"}\n')
    lab.run('walk', 'fabrig', 'b0', '--resume', state['walk'], '--build', 'main')
    assert len(lab.calls('codex-run')) == 2 and lab.walk_state()[1]['stage'] == 'running'



def walk_kind_settings_are_validated_and_follow_precedence(lab):
    shutil.copytree(lab.products['fabrig'], lab.slots / '5')
    invalid = ('', 'Forgejo=2:chatgpt', 'forge-jo=2:chatgpt', 'forgejo=0:chatgpt',
               'forgejo=2:chatgpt-2', 'forgejo=2:chatgpt,chatgpt',
               'forgejo=1:chatgpt forgejo=1:claude', 'forgejo=1:', 'forgejo=1:chatgpt\nclaude=1:claude')
    for value in invalid:
        lab.run('take', 'forgejo', '--as', 'walk/forgejo/manual', status=2, extra={'QA_WALK_KINDS': value})
    assert not lab.calls('logins')
    (lab.tmp / 'machine.env').write_text('QA_WALK_KINDS=github=1:chatgpt\nQA_STOP_SECONDS=2\n')
    lab.walk('a')
    assert lab.walk_state()[1]['kind'] == 'github'
    lab.env['QA_WALK_KINDS'] = 'forgejo=1:claude'
    lab.walk('b')
    assert lab.walk_states()[1][1]['kind'] == 'forgejo'
    for key in ('QA_STOP_SECONDS', 'QA_GIVE_BACK_SECONDS', 'QA_INTERVAL_SECONDS'):
        lab.run('take', 'forgejo', '--as', 'walk/forgejo/manual', status=2, extra={key: '-1'})



def deeply_nested_and_oversized_states_keep_custody_without_stopping_checks(lab):
    lab.walk('b0')
    _, state = lab.walk_state()
    lab.walk('b1', '--kind', 'claude')
    good = lab.walk_states()[1][1]
    lab.end_run(good)
    path = lab.tmp / 'qa/walks' / (state['walk'] + '.json')
    for data in ('[' * 40001 + '0' + ']' * 40001, ' ' * (1024 * 1024) + '{}',
                 '{"n":' + '9' * 5000 + '}', '{broken json'):
        path.write_text(data)
        result = lab.watch()
        assert 'invalid walk state; keeping custody' in result.stdout
        assert path.read_text() == data
        assert not any(call[0] == 'give' and call[1] == CHATGPT for call in lab.calls('logins'))
    saved = json.loads((lab.tmp / 'qa/walks' / (good['walk'] + '.json')).read_text())
    assert saved['stage'] == 'ended' and saved['given'] == [CLAUDE]



def watch_runs_once_per_machine_and_loops_on_its_mailbox(lab):
    parent = lab.tmp / 'qa'
    parent.mkdir()
    with (parent / 'watch.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        assert 'another service runs' in lab.watch(status=2).stderr
    lab.configure(wait=[0, 1, 4], wait_settings='QA_INTERVAL_SECONDS=0\n')
    result = lab.run('watch', '--director', 'director@fixture', status=2)
    assert 'fixture end mail' in result.stdout
    assert sum(call[0] == 'wait' for call in lab.calls('post')) == 3
    assert lab.calls('post')[-1][lab.calls('post')[-1].index('--timeout') + 1] == '0'





def unsupported_commands_are_refused_without_state(lab):
    for name in ('candidates', 'decide', 'default', 'backlog', 'passes', 'findings', 'rung', 'triage'):
        lab.run(name, status=2)
    assert not (lab.tmp / 'qa').exists() and not lab.calls('logins')



def write_walk(lab, state):
    path = lab.tmp / 'qa/walks' / (state['walk'] + '.json')
    temporary = path.with_suffix('.new')
    temporary.write_text(json.dumps(state))
    temporary.replace(path)


def finished_pair(lab):
    first, state = deployment_pass(lab, CHATGPT, CLAUDE, in_place=(CLAUDE,))
    first_unit, first_pid = deployment(lab, first)
    lab.walk('b1')
    second, other = lab.walk_states()[1]
    second_unit, second_pid = deployment(lab, second)
    lab.end_run(state)
    lab.end_run(other)
    return first, first_unit, first_pid, second, second_unit, second_pid












def a_hard_linked_rung_brief_is_never_read_or_copied(lab):
    focused = lab.tmp / 'qa-focused'
    focused.mkdir()
    alias = lab.root / 'ordinary-fixture-data'
    alias.write_bytes(b'Fixture alias bytes, never a login.\n')
    for rung, suffix in (('default', ''), ('specific', '-forgejo')):
        brief = focused / f'rung-{rung}{suffix}-brief.md'
        os.link(alias, brief)
        result = lab.run('walk', 'fabrig', rung, status=4)
        assert str(brief) in result.stderr
        state = next(state for _, state in lab.walk_states() if state['rung'] == rung)
        assert not (focused / state['walk'] / 'brief.md').exists()
        assert state['released'] and not lab.calls('codex-run')


def unsafe_metadata_is_rejected_without_reading(lab, shape):
    from contextlib import redirect_stdout
    import io
    from types import SimpleNamespace
    from unittest.mock import patch
    tool = support.load(SCRIPT).__dict__
    with patch.dict(os.environ, lab.env, clear=True):
        lab.setup_inline(tool)
        workspace = tool['Workspace']()
        watch = tool['Watch'](workspace, 'director@fixture')
        directory = lab.tmp / 'qa-focused/rung-a-1'
        state = dict(walk='rung-a-1', rung='a', kind='forgejo', attempts=[])
        safe_meta = lab.root / 'safe-meta'
        safe_meta.write_text(f'task={lab.root}/task.md\n')
        readers = (
            ('machine', lab.root / 'tmp/post/machines', workspace.machine),
            ('settings', lab.tmp / 'machine.env', lambda: tool['settings'](workspace)),
            ('state', lab.tmp / 'qa/walks/rung-a-1.json', lambda: watch.read_state(target)),
            ('stuck', lab.home / '.config/agents-qa/stuck', watch.stuck_addresses),
            ('launcher', watch.runs / 'fixture/meta', lambda: watch.launcher_alive(target)),
            ('cmdline', lab.root / 'proc/123/cmdline', lambda: watch.launcher_alive(safe_meta)),
            ('facts', watch.runs / 'runs.tsv', lambda: watch.facts('fixture')),
            ('recovery', watch.runs / 'fixture/meta', lambda: watch.recover_run(directory, state)),
            ('pause', lab.root / 'marker/paused', lambda: tool['pause_line'](target.parent)),
            ('deployments', lab.root / 'scratch/deployments', lambda: tool['deploy'](
                SimpleNamespace(directory=str(target.parent), name='box', argv=['/bin/true']), workspace)),
            ('clock', directory.parent / 'a/loop.tsv', lambda: watch.walk_event(directory, state, 'walk-end', 'fixture')),
            ('brief', lab.tmp / 'qa-focused/rung-brief-brief.md', lambda: tool['walk'](
                SimpleNamespace(repo='fabrig', rung='brief', cap=None, login=[], resume=None, kind=None, build=None),
                workspace)),
        )
        for label, target, read in readers:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.unlink(missing_ok=True)
            target.write_text('Ordinary fixture data, never a login.\n')
            alias = target.with_name(target.name + '.alias')
            alias.unlink(missing_ok=True)
            if shape == 'hardlink':
                os.link(target, alias)
            elif shape == 'symlink':
                target.rename(alias)
                target.symlink_to(alias)
            info = target.stat()
            real_fstat, real_fdopen, real_open = os.fstat, os.fdopen, io.open

            def fstat(fd):
                actual = real_fstat(fd)
                if shape == 'unowned' and (actual.st_dev, actual.st_ino) == (info.st_dev, info.st_ino):
                    return SimpleNamespace(st_mode=actual.st_mode, st_nlink=actual.st_nlink,
                                           st_uid=os.getuid() + 1, st_dev=actual.st_dev, st_ino=actual.st_ino)
                return actual

            class Unreadable:
                def __init__(self, source): self.source = source
                def __enter__(self): return self
                def __exit__(self, *args): return self.source.__exit__(*args)
                def __getattr__(self, name): return getattr(self.source, name)
                def read(self, *args, **kwargs):
                    raise AssertionError(f'{label}: unsafe file bytes read')
                readline = read
                readlines = read
                __iter__ = read

            def guarded(source):
                actual = real_fstat(source.fileno())
                if (actual.st_dev, actual.st_ino) == (info.st_dev, info.st_ino):
                    return Unreadable(source)
                return source

            output = io.StringIO()
            with patch('os.fstat', fstat), patch('os.fdopen', lambda *a, **kw: guarded(real_fdopen(*a, **kw))), \
                    patch('io.open', lambda *a, **kw: guarded(real_open(*a, **kw))), redirect_stdout(output):
                try:
                    result = read()
                except tool['Problem'] as error:
                    assert str(target) in str(error), (label, error)
                else:
                    if label == 'cmdline' and shape == 'unowned':
                        assert result is False
                    else:
                        assert str(target) in output.getvalue(), (label, output.getvalue())
            target.unlink()
            alias.unlink(missing_ok=True)


def hard_linked_metadata_is_never_read(lab):
    unsafe_metadata_is_rejected_without_reading(lab, 'hardlink')


def unowned_metadata_is_never_read(lab):
    unsafe_metadata_is_rejected_without_reading(lab, 'unowned')


def symlinked_metadata_is_never_read(lab):
    unsafe_metadata_is_rejected_without_reading(lab, 'symlink')


def brief_copy_validates_and_reads_the_same_descriptor(lab):
    focused = lab.tmp / 'qa-focused'
    focused.mkdir()
    brief = focused / 'rung-b0-brief.md'
    patch = f"""import os
from pathlib import Path
original = os.open
opens = []
def opened(path, flags, *args, **kwargs):
    fd = original(path, flags, *args, **kwargs)
    if Path(path) == Path({str(brief)!r}):
        assert flags & os.O_NOFOLLOW
        assert not opens, 'brief opened more than once'
        opens.append(fd)
        Path(path).rename(Path(path).with_name('opened-brief'))
        replacement = Path(path).with_name('replacement')
        replacement.write_bytes(b'A different pathname.\\n')
        replacement.replace(path)
    return fd
os.open = opened
"""
    driven_walk(lab, patch)
    directory, _ = lab.walk_state()
    assert (directory / 'brief.md').read_bytes() == b'fixture rung\n'
    assert brief.read_bytes() == b'A different pathname.\n'


def hand_give_cannot_release_a_saved_walk_holder_or_claim(lab):
    directory, state = walk_with_logins(lab, CHATGPT)
    before = lab.calls('logins')
    for name, holder in ((CHATGPT, state['holder']),
                         ('claude', state['holder']),
                         (CHATGPT, 'walk/forgejo/manual')):
        result = lab.run('give', name, '--as', holder, status=2,
                         extra={'QA_WALK_KINDS': 'invalid'})
        assert 'service cleanup' in result.stderr
        assert lab.calls('logins') == before
    lab.end_run(state)
    lab.watch()
    assert lab.walk_state()[1]['given'] == [CHATGPT]
    # Historical grants also remain reserved for cleanup.
    lab.run('give', CHATGPT, '--as', 'walk/forgejo/manual', status=2)
    assert lab.calls('logins').count(['give', CHATGPT, '--as', state['holder']]) == 1


def hand_give_protects_foreign_walks_and_saved_attempts(lab):
    parent = lab.tmp / 'qa/walks'
    parent.mkdir(parents=True)
    state = dict(walk='rung-a-12', repo='temper', rung='a', kind='retired',
                 holder='walk/retired/rung-a-12', logins={},
                 attempts=[dict(logins={'chatgpt': str(lab.root / 'unused-rest')},
                                holder='walk/earlier/rung-a-12')])
    write_walk(lab, state)
    original = (parent / 'rung-a-12.json').read_bytes()
    for holder in (state['holder'], 'walk/earlier/rung-a-12', 'walk/forgejo/manual'):
        result = lab.run('give', CHATGPT, '--as', holder, status=2)
        assert 'service cleanup' in result.stderr
        assert not lab.calls('logins')
    lab.run('give', CLAUDE, '--as', state['holder'], status=2)
    assert not lab.calls('logins')
    assert (parent / 'rung-a-12.json').read_bytes() == original
    # An unrelated hand holder still uses logins give's output and status.
    assert lab.run('give', CLAUDE, '--as', 'walk/retired/manual').stdout == 'already free: claude\n'


def hand_give_refuses_unreadable_saved_custody(lab):
    parent = lab.tmp / 'qa/walks'
    parent.mkdir(parents=True)
    (parent / 'rung-a-1.json').write_text('{broken')
    result = lab.run('give', CHATGPT, '--as', 'walk/forgejo/manual', status=2)
    assert 'keeping custody' in result.stderr and not lab.calls('logins')


def conflicting_walk_claims_give_for_neither(lab):
    lab.walk('b0')
    first, original = lab.walk_state()
    lab.walk('b1')
    second, other = lab.walk_states()[1]
    forged = dict(other, run_recorded=[], logins=original['logins'], kinds=original['kinds'], pools=original['pools'])
    write_walk(lab, forged)
    lab.end_run(original)
    lab.end_run(other)
    result = lab.watch()
    assert f'{CHATGPT}: conflicting custody claims' in result.stdout
    assert not any(call[0] == 'give' and call[1] == CHATGPT for call in lab.calls('logins'))
    write_walk(lab, other)
    lab.watch()
    assert all(state['stage'] == 'ended' for _, state in lab.walk_states())


def a_new_walk_grant_checks_existing_claims_before_giving(lab):
    lab.walk('b0')
    _, original = lab.walk_state()
    claimed = 'chatgpt-2'
    forged = dict(original, run_recorded=[], logins={claimed: str(lab.root / 'resting' / claimed)},
                  kinds={claimed: 'moved'}, pools={CHATGPT: claimed})
    write_walk(lab, forged)
    result = lab.run('walk', 'fabrig', 'b1', status=1)
    assert 'rung brief missing:' in result.stderr
    assert f'{claimed}: conflicting custody claims' in result.stdout
    walk = lab.walk_states()[1][1]
    assert walk['stage'] == 'cancelled' and not walk['given']
    lab.watch()
    assert not any(call[0] == 'give' and call[1] == claimed for call in lab.calls('logins'))
    write_walk(lab, original)
    lab.watch()
    assert lab.walk_states()[1][1]['stage'] == 'ended'


def workspace_defaults_and_fixture_overrides_are_gated(lab):
    driver = f"""import os, runpy
from pathlib import Path
tool = runpy.run_path({str(SCRIPT)!r})
os.environ.pop('DEV_ROOT')
os.environ.pop('DEV_TMP')
os.environ.pop('QA_FIXTURE')
workspace = tool['Workspace']()
assert workspace.root == Path.home() / 'src/rust'
assert workspace.tmp == workspace.root / 'tmp'
assert workspace.tool('post') == Path('post')
assert workspace.tool('systemd-run') == Path('systemd-run')
assert workspace.origin('fabrig') == 'git@github.com:fabrig-ai/fabrig.git'
assert not hasattr(workspace, 'records')
"""
    result = lab.probe(driver)
    assert result.returncode == 0, result.stderr


def the_first_kind_is_never_blocked(lab):
    lab.configure(pools={CHATGPT: [CHATGPT, 'chatgpt-2', 'chatgpt-3', 'chatgpt-4'],
                         CLAUDE: [CLAUDE, 'claude-2']},
                  logins_held=[CHATGPT, 'chatgpt-2'],
                  login_holders={CHATGPT: 'qa-watch/foreign-pass', 'chatgpt-2': 'qa-watch'})
    lab.walk('b0', '--kind', 'claude')
    lab.walk('b0')
    lab.walk('b0')
    states = [state for _, state in lab.walk_states()]
    forgejo = [state for state in states if state['kind'] == 'forgejo']
    assert [state['pools'][CHATGPT] for state in forgejo] == ['chatgpt-3', 'chatgpt-4']
    assert [state['slot'] for state in forgejo] == [1, 2]
    lab.watch()
    assert not any(call[0] == 'give' for call in lab.calls('logins'))
    assert not json.loads((lab.root / 'tools.json').read_text())['login_queue']


def pass_states_are_left_untouched(lab):
    lab.walk('b0')
    _, walk = lab.walk_state()
    directory = lab.tmp / 'qa/foreign-pass'
    directory.mkdir()
    state = directory / 'pass.json'
    state.write_text(json.dumps(dict(walk, holder=walk['holder'], finished=True)))
    original = (state.read_bytes(), state.stat().st_mtime_ns)
    lab.end_run(walk)
    lab.watch()
    assert (state.read_bytes(), state.stat().st_mtime_ns) == original
    assert lab.walk_state()[1]['stage'] == 'ended'

def slot_claims(lab):
    path = lab.root / 'claims.json'
    return json.loads(path.read_text()) if path.exists() else {}


def hold_slot(lab, number, owner='s/qa', what='another task'):
    claims = slot_claims(lab)
    claims[str(number)] = dict(owner=owner, what=what)
    path = lab.root / 'claims.json'
    temporary = path.with_suffix('.new')
    temporary.write_text(json.dumps(claims))
    temporary.replace(path)


def no_walk_resources_taken(lab):
    assert not any(args[0] == 'take' for args in lab.calls('logins'))
    assert not lab.calls('codex-run') and not lab.calls('cargo')
    assert not (lab.tmp / 'qa/repos').exists()
    assert all(not state['logins'] and state['released'] for _, state in lab.walk_states())


def a_held_named_slot_allows_the_next_free_slot(lab):
    lab.env['QA_WALK_SLOTS'] = 'forgejo=2+1'
    hold_slot(lab, 2, owner='ops')
    before = slot_claims(lab)['2']
    lab.walk()
    _, state = lab.walk_state()
    assert state['slot'] == 1 and slot_claims(lab)['2'] == before
    assert not queued_entries(lab)
    calls = [c for c in lab.calls('claim') if c[0] == 'claim']
    assert len(calls) == 1 and calls[0][:4] == ['claim', 'hetzner6', '1', 's/qa']


def all_named_slots_held_queues_without_taking_anything(lab):
    hold_slot(lab, 1, owner='ops')
    hold_slot(lab, 2)
    before = slot_claims(lab)
    result = lab.walk(status=0)
    assert 'queued ' in result.stdout
    no_walk_resources_taken(lab)
    assert slot_claims(lab) == before
    assert not [call for call in lab.calls('claim') if call[0] == 'release']


def dirty_slots_are_preserved_refused_and_released(lab):
    checkout = lab.slots / '1'
    tracked = checkout / 'tools/slots/trim'
    original = tracked.read_bytes()
    tracked.write_bytes(original + b'# changed\n')
    result = lab.walk('tracked', status=4)
    assert 'dirty slot' in result.stderr and tracked.read_bytes() == original + b'# changed\n'
    tracked.write_bytes(original)
    untracked = checkout / 'private-work'
    untracked.write_text('preserve me')
    result = lab.walk('untracked', status=4)
    assert 'dirty slot' in result.stderr and untracked.read_text() == 'preserve me'
    untracked.unlink()
    # Ignored files outside target must not be silently erased or used either.
    (checkout / '.git/info/exclude').write_text('private-work\n')
    untracked.write_text('ignored work')
    result = lab.walk('ignored', status=4)
    assert 'dirty slot' in result.stderr and untracked.read_text() == 'ignored work'
    no_walk_resources_taken(lab)
    assert not slot_claims(lab)
    assert len([c for c in lab.calls('claim') if c[0] == 'release']) == 3


def a_slot_is_never_created_replaced_or_used_with_the_wrong_origin(lab):
    checkout = lab.slots / '1'
    lab.git(checkout, 'remote', 'set-url', 'origin', str(lab.root / 'wrong-origin'))
    result = lab.walk('wrong', status=4)
    assert 'unexpected origin' in result.stderr
    moved = lab.slots / 'kept'
    checkout.rename(moved)
    lab.walk('missing', status=4)
    assert not checkout.exists() and moved.is_dir()
    checkout.symlink_to(moved)
    result = lab.walk('linked', status=4)
    assert 'symlink refused' in result.stderr and checkout.is_symlink()
    no_walk_resources_taken(lab)
    assert not slot_claims(lab)


def low_disk_refuses_and_releases_before_taking_a_login(lab):
    lab.configure(disk_available=79999999999)
    result = lab.walk(status=4)
    assert '80000000000' in result.stderr
    no_walk_resources_taken(lab)
    assert not slot_claims(lab)
    assert lab.calls('trim') == [[str(lab.slots / '1')]]
    assert lab.walk_state()[1]['slot_claim']['released']


def target_stays_warm_and_trim_failure_is_logged_before_fetch(lab):
    target = lab.slots / '1/target/debug/keep'
    target.parent.mkdir(parents=True)
    target.write_text('warm build')
    lab.configure(trim_status=7, disk_available=80000000000)
    lab.walk()
    directory, _ = lab.walk_state()
    assert target.read_text() == 'warm build'
    assert 'fixture trim\ntrim exit 7\n' == (directory / 'prepare-1.log').read_text()
    calls = list(map(json.loads, (lab.root / 'tools.jsonl').read_text().splitlines()))
    index = lambda name: next(i for i, row in enumerate(calls) if row['tool'] == name)
    take = next(i for i, row in enumerate(calls) if row['tool'] == 'logins' and row['args'][0] == 'take')
    assert index('claim') < index('trim') < index('df') < index('cargo') < take
    task = (directory / 'task.md').read_text()
    for text in ('HEAVY_CLASS=background heavy cargo build --locked --offline -p temper',
                 'Never use --release or --target-dir', 'never clean the target',
                 'touch nothing else in the checkout', 'df -B1 --output=avail /',
                 '80000000000', 'wait 5 minutes', 'own binary'):
        assert text in task, text
    assert not (lab.tmp / 'qa/repos').exists()


def claims_over_ssh_quote_both_shell_levels_and_use_saved_endpoint(lab):
    import shlex
    # Make accidental interpolation observable without invoking a real shell or ssh.
    directory = lab.root / "literal ' $() ; directory"
    directory.mkdir()
    shutil.copyfile(lab.root / 'claim', directory / 'claim')
    (directory / 'claim').chmod(0o700)
    lab.env['QA_CLAIM'] = str(directory / 'claim')
    lab.env['QA_CLAIM_SSH'] = 'claims@hel8'
    lab.walk()
    _, state = lab.walk_state()
    call = next(c for c in lab.calls('ssh') if shlex.split(shlex.split(c[-1])[2])[1] == 'claim')
    assert call[:3] == ['-o', 'BatchMode=yes', 'claims@hel8'] and len(call) == 4
    outer = shlex.split(call[3])
    assert outer[:2] == ['bash', '-lc'] and len(outer) == 3
    assert shlex.split(outer[2]) == [str(directory / 'claim'), 'claim', 'hetzner6', '1', 's/qa',
                                   state['slot_claim']['what']]
    assert re.fullmatch(r'qa walk rung-b0-1 attempt 1 claim [0-9a-f]{32}', state['slot_claim']['what'])
    lab.env['QA_CLAIM_SSH'] = 'new-claims@hel8'
    lab.env['QA_CLAIM_OWNER'] = 'new/owner'
    lab.configure(inactive=True)
    lab.watch()
    assert lab.walk_state()[1]['slot_claim']['released'] and not slot_claims(lab)
    assert any(call[2] == 'claims@hel8' and 'release' in call[3] for call in lab.calls('ssh'))
    assert state['slot_claim']['ssh'] == 'claims@hel8'




def claim_release_failure_is_retried_and_alerted_once(lab):
    lab.walk()
    lab.configure(inactive=True, claim_release_refusal=True)
    lab.watch()
    _, state = lab.walk_state()
    assert state['stage'] == 'ended' and state['released'] and state['given'] == [CHATGPT]
    assert state['slot_claim']['release_status'] == 'release unconfirmed'
    assert not state['slot_claim']['released'] and slot_claims(lab)
    releases = lambda: [c for c in lab.calls('claim') if c[0] == 'release']
    assert len(releases()) == 1
    lab.configure(claim_release_refusal=False)
    lab.watch()
    lab.watch()
    assert len(releases()) == 2 and lab.walk_state()[1]['slot_claim']['released']
    notices = [row for row in lab.sent() if 'slot release unconfirmed' in row['args'][2]]
    assert len(notices) == 1 and notices[0]['args'][1] == 'director@fixture'


def a_claim_lost_between_acceptance_and_save_gets_orphan_grace(lab):
    driven_walk(lab, '''Watch = tool['Watch']
original = Watch.slot_call
def slot_call(self, claim, *args):
    result = original(self, claim, *args)
    if args[0] == 'claim' and result.returncode == 0:
        os._exit(77)
    return result
Watch.slot_call = slot_call
''', status=77)
    _, state = lab.walk_state()
    assert state['slot'] is None and not state.get('slot_claim') and slot_claims(lab)
    # Same owner, unrelated WHAT and an out-of-kind slot remain protected.
    hold_slot(lab, 2, what='manual work')
    hold_slot(lab, 7, what='qa walk rung-unrelated-1 attempt 1')
    lab.watch()
    assert set(slot_claims(lab)) == {'1', '2', '7'}
    assert lab.walk_state()[1]['released']
    lab.watch()
    assert not lab.sent()  # No release or notice before the orphan grace.
    assert not [c for c in lab.calls('claim') if c[0] == 'release']


def an_orphan_claim_without_any_state_waits_for_grace(lab):
    hold_slot(lab, 1, what='qa walk rung-crashed-1 attempt 1')
    hold_slot(lab, 2, owner='ops', what='qa walk rung-other-1 attempt 1')
    lab.watch()
    lab.watch()
    assert set(slot_claims(lab)) == {'1', '2'}
    assert not lab.sent()  # Grace has not elapsed.
    assert not [c for c in lab.calls('claim') if c[0] == 'release']


def a_saved_claim_precedes_any_checkout_preparation(lab):
    result = driven_walk(lab, '''Repositories = tool['Repositories']
def fetch(self, repo, slot):
    state, = (self.workspace.tmp / 'qa/walks').glob('*.json')
    import json
    saved = json.loads(state.read_text())
    assert saved['slot'] == saved['slot_claim']['slot'] == slot
    assert saved['slot_claim']['host'] == 'hetzner6' and saved['slot_claim']['owner'] == 's/qa'
    assert tool['re'].fullmatch(r'qa walk rung-b0-1 attempt 1 claim [0-9a-f]{32}', saved['slot_claim']['what'])
    os._exit(77)
Repositories.fetch = fetch
''', status=77)
    assert not result.stderr
    assert lab.walk_state()[1]['slot_claim'] and slot_claims(lab)
    lab.watch()
    assert not slot_claims(lab) and lab.walk_state()[1]['slot_claim']['released']


def a_release_saved_after_a_crash_never_releases_a_successor(lab):
    lab.walk()
    lab.configure(inactive=True)
    driven_watch(lab, '''import os
Watch = tool['Watch']
original = Watch.slot_call
def slot_call(self, claim, *args):
    result = original(self, claim, *args)
    if args[0] == 'release' and result.returncode == 0:
        os._exit(77)
    return result
Watch.slot_call = slot_call
''', status=77)
    assert not slot_claims(lab) and not lab.walk_state()[1]['slot_claim']['released']
    hold_slot(lab, 1, what='qa walk rung-successor-1 attempt 1')
    before = len([c for c in lab.calls('claim') if c[0] == 'release'])
    # Retries observe the successor but never release its different WHAT.
    lab.env['QA_WALK_SLOTS'] = 'forgejo=2'
    lab.watch()
    assert lab.walk_state()[1]['slot_claim']['release_status'] == 'release unconfirmed'
    assert slot_claims(lab)['1']['what'] == 'qa walk rung-successor-1 attempt 1'
    assert len([c for c in lab.calls('claim') if c[0] == 'release']) == before


def a_pause_releases_and_resume_waits_for_its_own_slot(lab):
    directory, state = walk_with_logins(lab, CHATGPT)
    paused = pause_walk(lab, directory, state)
    assert paused['slot_claim']['released'] and not slot_claims(lab)
    hold_slot(lab, 1, owner='ops')
    lab.run('walk', 'fabrig', 'b0', '--resume', state['walk'], '--build', 'main')
    assert lab.walk_state()[1]['stage'] == 'paused' and lab.walk_state()[1]['attempt'] == 1
    lab.env['QA_WALK_SLOTS'] = 'forgejo=2+1'
    lab.watch()
    assert queued_entries(lab) and len(lab.calls('codex-run')) == 1
    # A free slot 2 cannot replace this walk's saved slot 1.
    path = lab.root / 'claims.json'
    temporary = path.with_suffix('.new')
    temporary.write_text('{}')
    temporary.replace(path)
    lab.watch()
    resumed = lab.walk_state()[1]
    assert not queued_entries(lab) and resumed['attempt'] == 2 and resumed['slot'] == 1
    assert re.fullmatch(r'qa walk rung-b0-1 attempt 2 claim [0-9a-f]{32}', resumed['slot_claim']['what'])
    assert resumed['slot_claim']['what'] != paused['slot_claim']['what']
    assert resumed['attempts'][0]['slot_claim']['released']
    assert (directory / 'prepare-2.log').is_file()
    assert lab.calls('codex-run')[-1][-2] == str(lab.slots / '1')


def a_pause_with_unconfirmed_release_queues_resume_until_retry(lab):
    directory, state = walk_with_logins(lab, CHATGPT)
    lab.configure(claim_release_refusal=True)
    state = pause_walk(lab, directory, state)
    assert state['stage'] == 'paused' and state['given'] == [CHATGPT]
    assert state['slot_claim']['release_status'] == 'release unconfirmed'
    result = lab.run('walk', 'fabrig', 'b0', '--resume', state['walk'], '--build', 'main', status=0)
    assert 'queued ' + state['walk'] in result.stdout
    lab.configure(claim_release_refusal=False)
    lab.watch()
    assert lab.walk_state()[1]['attempts'][0]['slot_claim']['released']
    assert lab.walk_state()[1]['stage'] == 'running' and not queued_entries(lab)
    assert len([c for c in lab.calls('claim') if c[0] == 'release']) == 2
    assert len(lab.calls('codex-run')) == 2




def named_slot_settings_validate_and_override_the_old_counts(lab):
    for value in ('forgejo=0', 'forgejo=1,1', 'forgejo=1 claude=1', 'forgejo=1 forgejo=2',
                  'forgejo=../1', 'forgejo=1\nclaude=3', 'forgejo=', 'Forgejo=1'):
        lab.run('walk', 'fabrig', 'b0', status=2, extra={'QA_WALK_SLOTS': value})
    for key, value in (('QA_SLOT_HOST', '-host'), ('QA_CLAIM_OWNER', 'bad\nowner'),
                       ('QA_CLAIM_SSH', '-oProxyCommand=bad')):
        lab.run('walk', 'fabrig', 'b0', status=2, extra={key: value})
    assert not lab.calls('claim') and not lab.calls('logins')
    lab.env.pop('QA_WALK_SLOTS')
    (lab.tmp / 'machine.env').write_text('QA_WALK_SLOTS=forgejo=2\nQA_SLOT_HOST=hetzner6\nQA_CLAIM_OWNER=s/qa\nQA_CLAIM_SSH=claims@hel8\n')
    # Two in the old setting, one named slot: the kind now has cap one.
    lab.env['QA_WALK_KINDS'] = 'forgejo=2:chatgpt claude=9:claude'
    lab.env.pop('QA_CLAIM_SSH')
    lab.walk('one')
    result = lab.walk('two', status=0)
    assert 'holds 1 of its 1' in queued_entries(lab)[0]['reason']
    result = lab.walk('no-slot', '--kind', 'claude', status=1)
    assert 'no walk slots configured for kind claude' in result.stderr
    assert lab.walk_state()[1]['slot'] == 2 and lab.calls('ssh')
    # Environment takes priority over the file, including an empty local target.
    lab.env['QA_WALK_SLOTS'] = 'forgejo=1 claude=3'
    lab.env['QA_CLAIM_SSH'] = ''
    lab.walk('local', '--kind', 'claude')
    assert lab.walk_states()[0][1]['slot_claim']['ssh'] == ''


def fleet_settings_accept_commas_and_plus_without_whitespace(lab):
    import tomllib
    values = dict(QA_WALK_KINDS='forgejo=2:chatgpt+claude,claude=2:claude',
                  QA_WALK_SLOTS='forgejo=1,2,claude=3,4')
    # The exact fleet representation parses as data and contains only allowed value characters.
    literal = 'machine_env = { ' + ', '.join(f'{key} = "{value}"' for key, value in values.items()) + ' }'
    assert tomllib.loads(literal)['machine_env'] == values
    assert all(not any(c.isspace() or c in "'\"\\$" for c in value) for value in values.values())
    for key in values:
        lab.env.pop(key, None)
    (lab.tmp / 'machine.env').write_text(''.join(f'{key}={value}\n' for key, value in values.items()))
    lab.walk()
    directory, state = lab.walk_state()
    assert set(state['requests']) == {CHATGPT, CLAUDE} and state['slot'] == 1
    lab.walk('other', '--kind', 'claude')
    assert lab.walk_states()[1][1]['slot'] == 3
    assert state['slot_claim']['slot'] == 1
    assert re.fullmatch(r'qa walk rung-b0-1 attempt 1 claim [0-9a-f]{32}', state['slot_claim']['what'])
    # Legacy whitespace kinds and comma pools still work under the same parser.
    lab.env['QA_WALK_KINDS'] = 'forgejo=2:chatgpt,claude claude=2:claude'
    lab.walk('legacy')
    assert set(lab.walk_states()[1][1]['requests']) == {CHATGPT, CLAUDE}


def failed_remote_or_unreadable_claim_never_prepares_or_falls_back(lab):
    lab.env['QA_CLAIM_SSH'] = 'claims@hel8'
    lab.configure(ssh_refusal=True)
    before = [lab.git(lab.slots / str(n), 'rev-parse', 'HEAD') for n in (1, 2)]
    result = lab.walk(status=1)
    assert 'fixture ssh unavailable' in result.stderr
    assert len(lab.calls('ssh')) == 1 and not lab.calls('claim')
    no_walk_resources_taken(lab)
    lab.configure(ssh_refusal=False)
    result = driven_walk(lab, '''def slot_call(self, claim, *args):
    raise UnicodeError('fixture undecodable result')
tool['Watch'].slot_call = slot_call
''', status=4)
    assert 'UnicodeError' in result.stderr
    no_walk_resources_taken(lab)
    assert [lab.git(lab.slots / str(n), 'rev-parse', 'HEAD') for n in (1, 2)] == before
    assert not lab.calls('trim')


def empty_and_unknown_claim_results_refuse_even_if_record_was_created(lab):
    lab.configure(claim_empty_reply=True)
    result = lab.walk('empty', status=1)
    assert 'unreadable or empty result' in result.stderr
    no_walk_resources_taken(lab)
    assert set(slot_claims(lab)) == {'1'}
    # A reply lost after recording is not permission to use another candidate.
    lab.env['QA_WALK_SLOTS'] = 'forgejo=2,1'
    lab.configure(claim_empty_reply=False, claim_unknown_exit=255)
    result = lab.walk('unknown', status=1)
    assert 'exit 255' in result.stderr
    no_walk_resources_taken(lab)
    assert set(slot_claims(lab)) == {'1', '2'}
    assert [c[2] for c in lab.calls('claim') if c[0] == 'claim'] == ['1', '2']


def release_preflight_mismatch_updates_one_notice_and_keeps_successors(lab):
    lab.walk()
    lab.configure(inactive=True, claim_list_lines=['hetzner6 1 [s/qa]: free'])
    lab.watch()
    assert lab.walk_state()[1]['slot_claim']['release_status'] == 'release unconfirmed'
    assert not [c for c in lab.calls('claim') if c[0] == 'release']
    lab.configure(claim_list_lines=[])
    lab.watch()
    lab.configure(claim_list_lines=['hetzner6 1 [s/qa]: s/qa: different WHAT (since 2026-10-29T00:00:00+00:00); held 0d 00:00:00'])
    lab.watch()
    assert not [c for c in lab.calls('claim') if c[0] == 'release']
    assert len([m for m in lab.sent() if 'slot release unconfirmed' in m['args'][2]]) == 1
    lab.configure(claim_list_lines=['hetzner6 1 [s/qa]: s/qa: different WHAT (since 2026-10-29T00:00:00+00:00); held 1d 00:00:00'])
    lab.watch()
    assert len([m for m in lab.sent() if 'slot release unconfirmed' in m['args'][2]]) == 1
    assert slot_claims(lab)


def release_waits_for_give_back_even_when_all_units_are_stopped(lab):
    directory, state = walk_with_logins(lab, CHATGPT)
    lab.configure(inactive=True, logins_out=[CHATGPT])
    lab.watch()
    current = lab.walk_state()[1]
    assert current['released'] and not current['given']
    assert not [c for c in lab.calls('claim') if c[0] == 'release']
    assert current['slot_claim']['release_status'] == 'held'
    lab.configure(logins_out=[])
    lab.watch()
    assert lab.walk_state()[1]['slot_claim']['released']
    assert len([c for c in lab.calls('claim') if c[0] == 'release']) == 1




def a_release_crash_before_call_retries_the_durable_intent(lab):
    lab.walk()
    lab.configure(inactive=True)
    driven_watch(lab, '''import os
original = tool['Watch'].slot_call
def slot_call(self, claim, *args):
    if args[0] == 'release':
        os._exit(77)
    return original(self, claim, *args)
tool['Watch'].slot_call = slot_call
''', status=77)
    assert lab.walk_state()[1]['slot_claim']['release_status'] == 'release unconfirmed'
    lab.watch()
    lab.watch()
    assert not slot_claims(lab) and lab.walk_state()[1]['slot_claim']['released']
    assert len([c for c in lab.calls('claim') if c[0] == 'release']) == 1
    assert not [m for m in lab.sent() if 'slot release unconfirmed' in m['args'][2]]


def unknown_walk_holders_alert_once_and_hand_holders_are_untouched(lab):
    holder = 'walk/forgejo/no-state'
    hand = 'q/manual'
    lab.configure(logins_held=[CHATGPT, 'chatgpt-2', CLAUDE],
                  login_holders={CHATGPT: holder, 'chatgpt-2': holder, CLAUDE: hand})
    lab.watch()
    lab.watch()
    assert not [c for c in lab.calls('logins') if c[0] == 'give']
    assert len(lab.sent()) == 1 and lab.sent()[0]['args'][1] == 'director@fixture'
    assert holder in lab.sent()[0]['body'] and hand not in lab.sent()[0]['body']
    assert 'chatgpt-2' in lab.sent()[0]['body']
    config = json.loads((lab.root / 'tools.json').read_text())
    assert set(config['logins_held']) == {CHATGPT, 'chatgpt-2', CLAUDE}
    # A different holder receives one distinct notice; a new login for the old holder does not.
    lab.configure(login_holders={CHATGPT: holder, 'chatgpt-2': 'walk/forgejo/another', CLAUDE: hand})
    lab.watch()
    lab.watch()
    assert len(lab.sent()) == 2


def a_saved_attempt_holder_authorizes_only_its_exact_stray(lab):
    lab.walk()
    directory, state = lab.walk_state()
    lab.configure(inactive=True)
    lab.watch()
    state = lab.walk_state()[1]
    state['attempts'][0]['holder'] = 'walk/forgejo/earlier'
    write_walk(lab, state)
    lab.configure(logins_held=[CHATGPT, 'chatgpt-2', CLAUDE],
                  login_holders={CHATGPT: state['holder'], 'chatgpt-2': 'walk/forgejo/earlier',
                                 CLAUDE: 'walk/forgejo/unclaimed'})
    lab.watch()
    gives = [c for c in lab.calls('logins') if c[0] == 'give']
    assert ['give', CHATGPT, '--as', state['holder']] in gives
    assert ['give', 'chatgpt-2', '--as', 'walk/forgejo/earlier'] in gives
    assert not any(c[1] == CLAUDE for c in gives)
    assert len([m for m in lab.sent() if 'unsaved walk login holder' in m['args'][2]]) == 1


def an_unreadable_grant_keeps_the_claim_until_inventory_confirms_give_back(lab):
    result = driven_walk(lab, """original = tool['Watch'].call
def call(self, name, *args):
    result = original(self, name, *args)
    if name == 'logins' and args[0] == 'take' and result.returncode == 0:
        path = self.workspace.fixture / 'tools.json'
        config = tool['json'].loads(path.read_text())
        config['logins_out'] = [result.stdout.split()[0]]
        temporary = path.with_suffix('.new')
        temporary.write_text(tool['json'].dumps(config))
        temporary.replace(path)
        result.stdout = 'unreadable grant'
    return result
tool['Watch'].call = call
""", status=4)
    assert 'invalid login grant' in result.stderr
    assert lab.walk_state()[1]['stage'] == 'ended'
    lab.watch()
    assert not lab.walk_state()[1]['slot_claim']['released']
    assert not [c for c in lab.calls('claim') if c[0] == 'release']
    lab.configure(logins_out=[])
    lab.watch()
    assert lab.walk_state()[1]['slot_claim']['released']
    assert len([c for c in lab.calls('claim') if c[0] == 'release']) == 1




def a_missing_launch_keeps_grace_and_unknown_custody(lab):
    driven_walk(lab, '''def call(self, name, *args):
    if name == 'codex-run':
        os._exit(77)
    return original(self, name, *args)
original = tool['Watch'].call
tool['Watch'].call = call
''', status=77)
    directory, state = lab.walk_state()
    started = datetime.fromisoformat(state['started'].replace('Z', '+00:00'))
    before = (started + timedelta(seconds=599)).strftime('%Y-%m-%dT%H:%M:%SZ')
    after = (started + timedelta(seconds=601)).strftime('%Y-%m-%dT%H:%M:%SZ')
    lab.watch(now=before)
    assert not lab.sent()
    assert lab.walk_state()[1]['stage'] == 'starting'
    assert not lab.walk_state()[1]['given'] and slot_claims(lab)
    result = lab.run('take', 'forgejo', '--as', 'walk/forgejo/manual', status=1)
    assert 'launch' in result.stderr
    result = lab.walk('other', status=1)
    assert 'launch' in result.stderr
    unknown = lab.root / 'proc' / str(os.getpid()) / 'cmdline'
    unknown.parent.mkdir()
    unknown.mkdir()  # Same descriptor reader refuses this observation.
    lab.watch(now=after)
    notice, = lab.sent()
    assert notice['args'][1:3] == ['director@fixture', f'qa: overdue launch for {state["walk"]}']
    assert f'Walk {state["walk"]}, attempt 1' in notice['body']
    assert '601 seconds' in notice['body'] and 'unknown' in notice['body']
    assert lab.walk_state()[1]['stage'] == 'starting' and not lab.walk_state()[1]['given']
    unknown.rmdir()
    unknown.write_bytes(b'\0'.join(os.fsencode(word) for word in
                        (lab.root / 'codex-run', 'task', directory / 'task.md')) + b'\0')
    lab.watch(now=after)
    assert lab.walk_state()[1]['stage'] == 'starting' and not lab.walk_state()[1]['given']
    assert lab.sent() == [notice]  # Changing observation cannot resend this launch.
    unknown.unlink()
    unknown.parent.rmdir()
    lab.watch(now=after)
    saved = lab.walk_state()[1]
    assert saved['stage'] == 'ended' and saved['given'] == [CHATGPT] and saved['slot_claim']['released']


def an_overdue_live_launcher_does_not_block_other_walks(lab):
    lab.walk('other', '--kind', 'claude')
    other_directory, other = lab.walk_state()
    driven_walk(lab, """original = tool['Watch'].call
def call(self, name, *args):
    if name == 'codex-run':
        os._exit(77)
    return original(self, name, *args)
tool['Watch'].call = call
""", status=77)
    directory, state = next((d, s) for d, s in lab.walk_states() if s['walk'] != other['walk'])
    after = (datetime.fromisoformat(state['started'].replace('Z', '+00:00'))
             + timedelta(seconds=601)).strftime('%Y-%m-%dT%H:%M:%SZ')
    process = lab.root / 'proc' / str(os.getpid())
    process.mkdir()
    (process / 'cmdline').write_bytes(b'\0'.join(os.fsencode(word) for word in
                                    (lab.root / 'codex-run', 'task', directory / 'task.md')) + b'\0')
    lab.end_run(other)
    lab.watch(now=after)
    states = {s['walk']: s for _, s in lab.walk_states()}
    assert states[state['walk']] == state
    assert states[other['walk']]['stage'] == 'ended' and states[other['walk']]['slot_claim']['released']
    notices = [post for post in lab.sent() if 'overdue launch' in post['args'][2]]
    notice, = notices
    assert notice['args'][1] == 'director@fixture'
    assert f'Walk {state["walk"]}, attempt 1' in notice['body']
    assert '601 seconds' in notice['body'] and 'launcher live' in notice['body']
    lab.watch(now=after)
    assert [post for post in lab.sent() if 'overdue launch' in post['args'][2]] == notices


def successor_claim_survives_release(lab, remote):
    lab.env['QA_CLAIM_SSH'] = remote
    lab.walk()
    _, started = lab.walk_state()
    claim = started['slot_claim']
    lab.configure(inactive=True)
    driven_watch(lab, """original = tool['Watch'].slot_call
def slot_call(self, claim, *args):
    if args[0] == 'release':
        assert self.walk_lock is not None
        # An external owner replaces the claim after the successful list guard.
        path = self.workspace.fixture / 'claims.json'
        claims = tool['json'].loads(path.read_text())
        assert claims[str(claim['slot'])]['what'] == claim['what']
        claims[str(claim['slot'])] = dict(owner=claim['owner'], what=claim['what'] + ' successor')
        temporary = path.with_suffix('.new')
        temporary.write_text(tool['json'].dumps(claims))
        temporary.replace(path)
    return original(self, claim, *args)
tool['Watch'].slot_call = slot_call
""")
    assert slot_claims(lab)[str(started['slot'])] == dict(owner=claim['owner'], what=claim['what'] + ' successor')
    saved = lab.walk_state()[1]['slot_claim']
    assert saved['release_status'] == 'release unconfirmed' and not saved['released']
    assert 'matching WHAT' in saved['release_result']
    release = ['release', claim['host'], str(started['slot']), claim['owner'], '--what', claim['what']]
    assert [c for c in lab.calls('claim') if c[0] == 'release'] == [release]
    if remote:
        import shlex
        calls = [c for c in lab.calls('ssh') if 'release' in c[-1]]
        assert len(calls) == 1 and calls[0][2] == remote
        assert shlex.split(shlex.split(calls[0][-1])[2]) == [str(lab.root / 'claim'), *release]
    lab.watch()
    lab.watch()
    assert slot_claims(lab)[str(started['slot'])]['what'] == claim['what'] + ' successor'
    assert [c for c in lab.calls('claim') if c[0] == 'release'] == [release]
    notices = [m for m in lab.sent() if 'slot release unconfirmed' in m['args'][2]]
    assert len(notices) == 1
    assert claim['what'] in notices[0]['body'] and 'matching WHAT' in notices[0]['body']


def a_local_successor_claim_survives_atomic_release(lab):
    successor_claim_survives_release(lab, '')


def a_remote_successor_claim_survives_atomic_release(lab):
    successor_claim_survives_release(lab, 'claims@hel8')


def repeated_claim_lifetimes(lab, refused=False):
    stamp = '2026-10-29T17:41:00Z'
    claims = []
    for repeat in range(2):
        lab.walk(now=stamp)
        directory, state = lab.walk_state()
        assert state['walk'] == 'rung-b0-1' and state['attempt'] == 1 and state['started'] == stamp
        claims.append(state['slot_claim']['what'])
        lab.configure(inactive=True, claim_release_refusal=refused)
        lab.watch(now=stamp)
        saved = lab.walk_state()[1]
        assert saved['released'] and saved['given'] == [CHATGPT]
        if refused:
            assert saved['slot_claim']['release_status'] == 'release unconfirmed'
            lab.watch(now=stamp)  # A refused claim still alerts only once.
        else:
            assert not slot_claims(lab) and saved['slot_claim']['released']
        if repeat == 0:
            # Simulate reconciled claims and fresh history with the same name/clock.
            path = lab.root / 'claims.json'
            temporary = path.with_suffix('.new')
            temporary.write_text('{}')
            temporary.replace(path)
            (lab.tmp / 'qa/walks' / (state['walk'] + '.json')).unlink()
            shutil.rmtree(directory)
    assert claims[0] != claims[1], claims
    assert all(re.fullmatch(r'qa walk rung-b0-1 attempt 1 claim [0-9a-f]{32}', what) for what in claims)
    if refused:
        notices = [m for m in lab.sent() if 'slot release unconfirmed' in m['args'][2]]
        assert len(notices) == 2
        assert all(sum(what in m['body'] for m in notices) == 1 for what in claims)






def legacy_saved_claims_release_with_their_exact_what(lab):
    lab.walk()
    _, state = lab.walk_state()
    old = 'qa walk rung-b0-1 attempt 1'
    state['slot_claim']['what'] = old
    state['attempts'][-1]['slot_claim']['what'] = old
    path = lab.tmp / 'qa/walks' / (state['walk'] + '.json')
    temporary = path.with_suffix('.new')
    temporary.write_text(json.dumps(state))
    temporary.replace(path)
    hold_slot(lab, state['slot'], what=old)
    lab.configure(inactive=True)
    lab.watch()
    assert not slot_claims(lab) and lab.walk_state()[1]['slot_claim']['released']
    assert [c for c in lab.calls('claim') if c[0] == 'release'] == [
        ['release', 'hetzner6', str(state['slot']), 's/qa', '--what', old]]


def slot_release_refuses_without_the_walks_lock(lab):
    lab.walk()
    lab.configure(logins_held=[], inactive=True)
    driver = f'''import runpy
from pathlib import Path
tool = runpy.run_path({str(SCRIPT)!r})
service = tool['Watch'](tool['Workspace'](), 'director@fixture')
service.options = tool['settings'](service.workspace)
with service.walks_locked():
    (directory, state), = service.local_walks()
    state['given'] = list(state['logins'])
    state['released'] = True
try:
    service.release_slot(directory, state)
except tool['Problem'] as error:
    assert 'walks lock' in str(error)
else:
    raise AssertionError('unlocked claim verification/release was allowed')
'''
    result = lab.probe(driver)
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert slot_claims(lab) and not [c for c in lab.calls('claim') if c[0] == 'release']


def release_preflight_and_delete_exclude_other_walks(lab):
    lab.walk()
    lab.configure(inactive=True)
    driven_watch(lab, '''import subprocess
original = tool['Watch'].slot_call
def slot_call(self, claim, *args):
    result = original(self, claim, *args)
    if args[0] == 'list' and 'release unconfirmed' in str(self.states):
        assert self.walk_lock is not None
        path = str(self.directory / 'walks.lock')
        code = "import fcntl,sys; f=open(sys.argv[1], 'a'); "
        code += "\\ntry: fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)"
        code += "\\nexcept BlockingIOError: sys.exit(0)"
        code += "\\nraise AssertionError('a successor could enter during release')"
        checked = subprocess.run([tool['sys'].executable, '-I', '-B', '-c', code, path], capture_output=True)
        assert checked.returncode == 0, checked.stderr
    return result
tool['Watch'].slot_call = slot_call
''')
    assert lab.walk_state()[1]['slot_claim']['released']
    assert len([c for c in lab.calls('claim') if c[0] == 'release']) == 1






def detached_heads_contained_in_origin_history_are_accepted(lab):
    old = lab.head()
    new = lab.marked()
    lab.git(lab.slots / '1', 'switch', '--detach', old)
    lab.walk()
    assert lab.git(lab.slots / '1', 'rev-parse', 'HEAD') == new
    assert lab.walk_state()[1]['main'] == new


def fast_readonly_fixture_results_match_external_services(lab):
    driver = f"import runpy, sys\ntool = runpy.run_path({str(SCRIPT)!r})\n" + FAST_READ_DRIVER + r"""
workspace = tool['Workspace']()
for broken in (False, True):
    root = workspace.fixture
    config = tool['json'].loads((root / 'tools.json').read_text())
    config['unit_query_failure'] = broken
    config['login_list_failure'] = broken
    config['claim_list_refusal'] = broken
    (root / 'tools.json').write_text(tool['json'].dumps(config))
    for argv, bound in (([workspace.tool('logins'), 'list'], 60),
                        ([workspace.tool('claim'), 'list'], 60),
                        ([workspace.tool('df'), '-B1', '--output=avail', '/'], 30),
                        ([workspace.tool('systemctl'), '--user', 'show', '--property=LoadState',
                          '--property=ActiveState', '--property=Job', '--', 'codex-run-fixture'], 30),
                        ([workspace.tool('systemctl'), '--user', 'list-units', '--all', '--plain',
                          '--no-legend', '--full', 'qa-rung-b0-1-*'], 30)):
        native = _fixture_original(argv, timeout=bound)
        quick = _fixture_command(argv, timeout=bound)
        assert (quick.returncode, quick.stdout, quick.stderr) == (native.returncode, native.stdout, native.stderr)
# A changed executable must go through the external command path too.
script = root / 'logins'
text = script.read_text()
temporary = script.with_name(script.name + '.new')
temporary.write_text(text + '\nprint("custom fixture footer")\n')
temporary.chmod(0o700)
temporary.replace(script)
config['login_list_failure'] = False
(root / 'tools.json').write_text(tool['json'].dumps(config))
called = []
original = _fixture_original
def external(*args, **kwargs):
    called.append(args)
    return original(*args, **kwargs)
_fixture_original = external
_fixture_command([workspace.tool('logins'), 'list'], timeout=60)
assert called
"""
    result = lab.probe(driver)
    assert result.returncode == 0, (result.stdout, result.stderr)


def queued_entries(lab):
    return [json.loads(p.read_text()) for p in (lab.tmp / 'qa/queue').glob('*.json')]


def a_busy_slot_start_is_queued_then_started(lab):
    lab.env['QA_WALK_SLOTS'] = 'forgejo=1'
    lab.walk()
    _, first = lab.walk_state()
    result = lab.walk()
    assert re.search(r'queued [0-9a-f]{32}\n', result.stdout)
    entry, = queued_entries(lab)
    assert entry['kind'] == 'forgejo' and entry['rung'] == 'b0'
    assert len(lab.calls('codex-run')) == 1
    lab.watch()
    assert len(lab.calls('codex-run')) == 1
    lab.end_run(first)
    lab.watch()
    assert not queued_entries(lab) and len(lab.calls('codex-run')) == 2
    second = lab.walk_states()[-1][1]
    assert second['stage'] == 'running' and second['slot'] == 1
    assert second['starter'] == first['starter'] and second['queue_id'] == entry['id']
    lab.watch()
    assert len(lab.calls('codex-run')) == 2




def a_watcher_refusal_keeps_the_queue_and_updates_one_notice(lab):
    lab.env['QA_WALK_SLOTS'] = 'forgejo=1'
    lab.walk()
    _, state = lab.walk_state()
    lab.walk()
    lab.end_run(state)
    lab.configure(cargo_refusal=2)
    lab.watch()
    entry, = queued_entries(lab)
    assert 'cannot fetch build main' in entry['reason']
    notices = lambda: [m for m in lab.sent() if m['args'][2] == 'qa: queued walk refused']
    assert len(notices()) == 1
    lab.watch()
    assert len(notices()) == 1 and len(queued_entries(lab)) == 1
    lab.configure(cargo_refusal=3)
    lab.watch()
    assert len(notices()) == 1
    receipt, = (lab.tmp / 'qa/attention').glob('*.json')
    latest = json.loads(receipt.read_text())
    assert queued_entries(lab)[0]['reason'] in latest['body']
    lab.configure(cargo_refusal=0)
    lab.watch()
    assert not queued_entries(lab) and len(lab.calls('codex-run')) == 2


def the_queue_lists_and_cancels_without_taking_resources(lab):
    missing = 'a' * 40
    lab.walk('b0', '--after', missing)
    entry, = queued_entries(lab)
    listed = lab.run('queue').stdout
    assert all(value in listed for value in (entry['id'], 'forgejo', 'b0', missing, entry['since'], entry['reason']))
    assert not lab.calls('codex-run') and not lab.calls('cargo')
    assert not [c for c in lab.calls('claim') if c[0] == 'claim']
    lab.run('queue', 'cancel', entry['id'])
    assert not queued_entries(lab)
    lab.run('queue', 'cancel', entry['id'], status=2)
    lab.watch()
    assert not lab.calls('codex-run')


def a_queued_resume_no_longer_paused_is_dropped_with_notice(lab):
    directory, state = walk_with_logins(lab, CHATGPT)
    state = pause_walk(lab, directory, state)
    lab.run('walk', 'fabrig', 'b0', '--resume', state['walk'], '--after', 'a' * 40)
    lab.run('walk', 'fabrig', 'b0', '--resume', state['walk'], '--build', 'main')
    lab.watch()
    lab.watch()
    assert not queued_entries(lab) and len(lab.calls('codex-run')) == 2
    assert len([m for m in lab.sent() if m['args'][2] == 'qa: queued resume dropped']) == 1


def pending_attention_notices_retry_until_post_accepts(lab):
    lab.walk()
    lab.configure(inactive=True, claim_release_refusal=True)
    lab.watch(extra={'QA_POST_STATUS': '2'})
    notices = lambda: [m for m in lab.sent() if 'slot release unconfirmed' in m['args'][2]]
    assert len(notices()) == 1
    lab.watch(extra={'QA_POST_STATUS': '3'})
    assert len(notices()) == 2
    lab.watch()
    assert len(notices()) == 2
    receipts = [json.loads(p.read_text()) for p in (lab.tmp / 'qa/attention').glob('*.json')]
    assert receipts and all(r['delivered'] for r in receipts)


def orphan_claims_release_after_ten_minutes_with_exact_what(lab):
    lab.walk()
    _, live = lab.walk_state()
    orphan = 'qa walk rung-orphan-1 attempt 1 claim ' + 'a' * 32
    hold_slot(lab, 2, what=orphan)
    hold_slot(lab, 3, owner='ops', what='qa walk rung-other-1 attempt 1')
    lab.watch(now='2026-10-30T00:00:00Z')
    lab.watch(now='2026-10-30T00:09:59Z')
    assert set(slot_claims(lab)) == {'1', '2', '3'}
    lab.watch(now='2026-10-30T00:10:00Z')
    assert set(slot_claims(lab)) == {'1', '3'}
    assert ['release', 'hetzner6', '2', 's/qa', '--what', orphan] in lab.calls('claim')
    assert slot_claims(lab)['1']['what'] == live['slot_claim']['what']
    lab.watch(now='2026-10-30T00:20:00Z')
    assert len([m for m in lab.sent() if 'orphan slot released' in m['args'][2]]) == 1


def orphan_claims_keep_live_or_uncertain_runs_and_reset_grace(lab):
    lab.walk()
    directory, state = lab.walk_state()
    (lab.tmp / 'qa/walks' / (state['walk'] + '.json')).unlink()
    # The login was returned separately; the missing state's run is still live.
    lab.configure(logins_held=[], login_holders={})
    lab.watch(now='2026-10-30T00:00:00Z')
    lab.watch(now='2026-10-30T00:20:00Z')
    assert slot_claims(lab) and not [c for c in lab.calls('claim') if c[0] == 'release']
    lab.configure(inactive=True)
    lab.watch(now='2026-10-30T00:21:00Z')
    lab.configure(unit_query_failure=True)
    result = lab.watch(now='2026-10-30T00:30:00Z')
    assert 'orphan claim kept' in result.stdout
    lab.configure(unit_query_failure=False)
    lab.watch(now='2026-10-30T00:31:00Z')
    assert slot_claims(lab)
    lab.watch(now='2026-10-30T00:41:00Z')
    assert not slot_claims(lab)


def stale_legacy_holders_are_silent_at_a_start(lab):
    (lab.tmp / 'qa/walks').mkdir(parents=True)
    originals = legacy_login_claims(lab)
    result = lab.walk()
    assert 'conflicting custody claims' not in result.stdout
    assert_legacy_unchanged(originals)
    result = lab.walk('b1')
    assert 'conflicting custody claims' not in result.stdout
    assert_legacy_unchanged(originals)


def a_queue_admission_survives_a_crash_after_launch(lab):
    lab.env['QA_WALK_SLOTS'] = 'forgejo=1'
    lab.walk()
    _, state = lab.walk_state()
    lab.walk()
    lab.end_run(state)
    driven_watch(lab, '''import os
original = tool['Watch'].call
def call(self, name, *args):
    result = original(self, name, *args)
    if name == 'codex-run':
        os._exit(77)
    return result
tool['Watch'].call = call
''', status=77)
    assert queued_entries(lab) and len(lab.calls('codex-run')) == 2
    lab.watch()
    lab.watch()
    assert not queued_entries(lab) and len(lab.calls('codex-run')) == 2
    assert lab.walk_states()[-1][1]['stage'] == 'running'


def the_watcher_selects_the_oldest_ready_entry_once_per_kind(lab):
    stamp = '2026-10-30T00:00:00Z'
    lab.walk('first', now=stamp)
    lab.walk('second', now=stamp)
    originals = lab.walk_states()
    lab.walk('blocked', '--after', 'a' * 40, now=stamp)
    lab.walk('ready-one', now=stamp)
    lab.walk('ready-two', now=stamp)
    entries = sorted(queued_entries(lab), key=lambda e: e['order'])
    assert [e['rung'] for e in entries] == ['blocked', 'ready-one', 'ready-two']
    for _, state in originals:
        lab.end_run(state)
    lab.watch(now='2026-10-30T00:00:01Z')
    assert {e['rung'] for e in queued_entries(lab)} == {'blocked', 'ready-two'}
    assert len(lab.calls('codex-run')) == 3
    assert any(s['rung'] == 'ready-one' and s['stage'] == 'running' for _, s in lab.walk_states())
    # There is still a free slot, but each check starts only one per kind.
    lab.watch(now='2026-10-30T00:00:02Z')
    assert [e['rung'] for e in queued_entries(lab)] == ['blocked']
    assert len(lab.calls('codex-run')) == 4


def a_busy_inventory_slot_is_queued_and_runs_when_freed(lab):
    lab.env['QA_WALK_SLOTS'] = 'forgejo=1'
    hold_slot(lab, 1, owner='ops')
    lab.walk()
    entry, = queued_entries(lab)
    assert 'slots for kind forgejo are busy' in entry['reason']
    assert not lab.calls('codex-run') and not lab.calls('cargo')
    lab.watch()
    assert queued_entries(lab) and slot_claims(lab)['1']['owner'] == 'ops'
    # Fake the external owner's release, without invoking a real service.
    path = lab.root / 'claims.json'
    temporary = path.with_suffix('.new')
    temporary.write_text('{}')
    temporary.replace(path)
    lab.watch()
    assert not queued_entries(lab) and len(lab.calls('codex-run')) == 1
    assert lab.walk_states()[-1][1]['slot_claim']['owner'] == 's/qa'


def orphan_release_and_its_notice_survive_an_interrupted_save(lab):
    what = 'qa walk rung-orphan-1 attempt 1 claim ' + 'b' * 32
    hold_slot(lab, 1, what=what)
    lab.watch(now='2026-10-30T00:00:00Z')
    driven_watch(lab, '''import os
original = tool['Watch'].slot_call
def slot_call(self, claim, *args):
    result = original(self, claim, *args)
    if args[0] == 'release':
        os._exit(77)
    return result
tool['Watch'].slot_call = slot_call
''', status=77, now='2026-10-30T00:10:00Z')
    assert not slot_claims(lab) and not lab.sent()
    lab.watch(now='2026-10-30T00:10:01Z', extra={'QA_POST_STATUS': '2'})
    lab.watch(now='2026-10-30T00:10:02Z', extra={'QA_POST_STATUS': '3'})
    lab.watch(now='2026-10-30T00:10:03Z')
    notices = [m for m in lab.sent() if 'orphan slot released' in m['args'][2]]
    assert len(notices) == 2 and all(what in m['body'] for m in notices)
    assert len([c for c in lab.calls('claim') if c[0] == 'release']) == 1


def a_damaged_queue_keeps_custody_cleanup_running(lab):
    lab.walk()
    _, state = lab.walk_state()
    lab.walk('waiting', '--after', 'a' * 40)
    entry, = queued_entries(lab)
    path = lab.tmp / 'qa/queue' / (entry['id'] + '.json')
    outside = lab.root / 'queue-target'
    path.rename(outside)
    path.symlink_to(outside)
    original = outside.read_bytes()
    lab.run('queue', status=4)
    attention = lab.tmp / 'qa/attention' / ('a' * 64 + '.json')
    attention.parent.mkdir(parents=True, exist_ok=True)
    attention.write_text('[]')
    lab.end_run(state)
    result = lab.watch()
    assert 'cannot read walk queue' in result.stdout
    assert 'cannot retry notice' in result.stdout
    assert outside.read_bytes() == original
    assert lab.walk_state()[1]['stage'] == 'ended' and not slot_claims(lab)
    assert len(lab.calls('codex-run')) == 1


def a_queued_walk_uses_the_first_free_inventory_slot(lab):
    lab.env['QA_WALK_SLOTS'] = 'forgejo=1+2,claude=3+4'
    hold_slot(lab, 1, owner='ops')
    hold_slot(lab, 2, owner='ops')
    lab.walk()
    assert len(queued_entries(lab)) == 1 and not lab.walk_states()
    claims = slot_claims(lab)
    del claims['2']
    path = lab.root / 'claims.json'
    temporary = path.with_suffix('.new')
    temporary.write_text(json.dumps(claims))
    temporary.replace(path)
    lab.watch()
    assert not queued_entries(lab) and lab.walk_state()[1]['slot'] == 2
    assert slot_claims(lab)['1']['owner'] == 'ops'


def plus_slot_lists_validate_and_keep_legacy_forms(lab):
    driver = '''for spelling in ('forgejo=1+2,claude=3+4', 'forgejo=1,2 claude=3,4', 'forgejo=1+2 claude=3+4'):
    tool['os'].environ['QA_WALK_SLOTS'] = spelling
    options = tool['settings'](tool['Workspace']())
    assert options['QA_WALK_KINDS']['forgejo']['numbers'] == [1, 2]
    assert options['QA_WALK_KINDS']['claude']['numbers'] == [3, 4]
for spelling in ('forgejo=1+1', 'forgejo=1+2,claude=2+3', 'forgejo=1+', 'forgejo=+1', 'forgejo=1++2', 'forgejo=0+1'):
    tool['os'].environ['QA_WALK_SLOTS'] = spelling
    try:
        tool['settings'](tool['Workspace']())
    except tool['Problem']:
        pass
    else:
        raise AssertionError(spelling)
'''
    result = subprocess.run([sys.executable, '-I', '-B', '-c',
                             f'import runpy; tool=runpy.run_path({str(SCRIPT)!r})\n' + driver],
                            env=lab.env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert not lab.calls('claim') and not lab.calls('logins')


def unknown_slot_inventory_refuses_without_claiming(lab):
    for rows in ([], ['hetzner6 1 [s/qa]: free', 'hetzner6 1 [s/qa]: free'],
                 ['hetzner6 1 [s/qa]: malformed']):
        lab.configure(claim_list_lines=rows)
        result = lab.walk(status=4)
        assert 'cannot read slot inventory' in result.stderr
    assert not [c for c in lab.calls('claim') if c[0] == 'claim']
    assert not lab.calls('cargo') and not lab.calls('codex-run') and not lab.walk_states()


def a_machine_stuck_recipient_replaces_the_fallback_file(lab):
    address = 'design/machine@fixture'
    (lab.tmp / 'machine.env').write_text('QA_STUCK_TO=' + address + '\n')
    path = lab.home / '.config/agents-qa/stuck'
    path.parent.mkdir(parents=True)
    path.write_text('design/fallback@fixture\n')
    start_stuck_pass(lab, CHATGPT)
    lab.watch()
    assert [m['args'][1] for m in stuck_posts(lab)] == [address, 'director@fixture']


def stuck_recipient_settings_validate_and_follow_precedence(lab):
    path = lab.home / '.config/agents-qa/stuck'
    path.parent.mkdir(parents=True)
    path.write_text('design/fallback@fixture\n')
    (lab.tmp / 'machine.env').write_text('QA_STUCK_TO=design/machine@fixture\n')
    for value, expected in ((None, ['design/machine@fixture', 'director@fixture']),
                            ('design/env@fixture', ['design/env@fixture', 'director@fixture']),
                            ('director@fixture', ['director@fixture']),
                            ('', ['design/fallback@fixture', 'director@fixture'])):
        if value is None:
            lab.env.pop('QA_STUCK_TO', None)
        else:
            lab.env['QA_STUCK_TO'] = value
        driven_watch(lab, f"""original = tool['Watch'].stuck_addresses
def stuck_addresses(self):
    addresses = original(self)
    assert addresses == {expected!r}, addresses
    return addresses
tool['Watch'].stuck_addresses = stuck_addresses
""")
    for value in ('not an address', 'design/team@fixture\n', 'a' * 121 + '@fixture'):
        result = lab.run('take', 'forgejo', '--as', 'walk/forgejo/manual', status=2,
                         extra={'QA_STUCK_TO': value})
        assert 'invalid QA_STUCK_TO' in result.stderr
    assert not [c for c in lab.calls('logins') if c[0] == 'take']


def a_walk_records_its_launched_run_on_every_hold(lab):
    lab.env['QA_WALK_KINDS'] = 'forgejo=2:chatgpt+claude'
    directory, state = walk_with_logins(lab, CHATGPT, CLAUDE)
    assert set(state['run_recorded']) == {CHATGPT, CLAUDE}
    config = json.loads((lab.root / 'tools.json').read_text())
    assert all(config['login_runs'][login] == state['run'] for login in state['logins'])
    calls = [json.loads(line) for line in (lab.root / 'tools.jsonl').read_text().splitlines()]
    launch = next(i for i, c in enumerate(calls) if c['tool'] == 'codex-run')
    assert all(i > launch for i, c in enumerate(calls) if c['tool'] == 'logins' and c['args'][0] == 'set-run')
    state = pause_walk(lab, directory, state)
    old_run = state['run']
    lab.run('walk', 'fabrig', 'b0', '--resume', state['walk'], '--build', 'main')
    resumed = lab.walk_state()[1]
    assert resumed['run'] != old_run and set(resumed['run_recorded']) == {CHATGPT, CLAUDE}
    config = json.loads((lab.root / 'tools.json').read_text())
    assert all(config['login_runs'][login] == resumed['run'] for login in resumed['logins'])


def a_failed_run_binding_retries_without_cancelling_the_walk(lab):
    lab.configure(set_run_refusal=True)
    lab.walk()
    _, state = lab.walk_state()
    assert state['stage'] == 'running' and state['run_recorded'] == []
    lab.configure(set_run_refusal=False)
    lab.watch()
    assert lab.walk_state()[1]['run_recorded'] == [CHATGPT]
    assert json.loads((lab.root / 'tools.json').read_text())['login_runs'][CHATGPT] == state['run']
    before = [c for c in lab.calls('logins') if c[0] == 'set-run']
    lab.watch()
    assert [c for c in lab.calls('logins') if c[0] == 'set-run'] == before
    assert len(lab.calls('codex-run')) == 1


def a_recovered_launch_binds_its_run_to_the_hold(lab):
    driven_walk(lab, '''original = tool['Watch'].call
def call(self, name, *args):
    result = original(self, name, *args)
    if name == 'codex-run':
        result.returncode = 124
    return result
tool['Watch'].call = call
''', status=1)
    assert not lab.walk_state()[1]['run']
    lab.watch()
    state = lab.walk_state()[1]
    assert state['stage'] == 'running' and state['run_recorded'] == [CHATGPT]
    assert json.loads((lab.root / 'tools.json').read_text())['login_runs'][CHATGPT] == state['run']
    assert len(lab.calls('codex-run')) == 1


def the_queue_json_fixture_matches_real_output(lab):
    fixture = json.loads((KIT / 'fixtures/qa-queue.json').read_text())
    missing = 'a' * 40
    assert lab.run('queue', '--json').stdout == '[]\n'
    patch = "tool['secrets'].token_hex = lambda count: '1' * 32\ntool['main'].__globals__['timestamp'] = lambda: '2026-10-30T10:00:00Z'\n"
    driven_walk(lab, patch, '--after', missing)
    directory, state = walk_with_logins(lab, CHATGPT)
    pause_walk(lab, directory, state)
    patch = "tool['secrets'].token_hex = lambda count: '2' * 32\ntool['main'].__globals__['timestamp'] = lambda: '2026-10-30T10:01:00Z'\n"
    driven_walk(lab, patch, '--resume', state['walk'], '--after', missing)
    output = json.loads(lab.run('queue', '--json').stdout)
    assert output == fixture, output
    for row in output:
        assert {'id', 'kind', 'rung', 'resume', 'after', 'since', 'reason'} <= row.keys()
        assert re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ', row['since'])
        assert row['resume'] is None or isinstance(row['resume'], str)
    for row in output:
        lab.run('queue', 'cancel', row['id'])
    assert lab.run('queue', '--json').stdout == '[]\n'



def evidence_scan_rules_and_placeholders(lab):
    module = support.load(SCRIPT).evidence
    scan = module['scan']
    unsafe = {
        'key/jwt': ['ghp_' + 'x' * 30, 'sk-ant-example', 'eyJabc.def.ghi',
                    '-----BEGIN RSA PRIVATE KEY-----'],
        'header/cookie-jar': ['Authorization: Bearer literal', 'Proxy-Authorization: Basic literal',
                              'Cookie: session=literal', '{"Authorization": "Bearer literal"}',
                              '{"Cookie": "session=literal"}', '# Netscape HTTP Cookie File',
                              '.example.test\tTRUE\t/\tFALSE\t0\tsession\tvalue'],
        'link': ['https://user:literal@example.test', 'https://example.test?code=literal',
                 'https://example.test#access_token=literal'],
        'assigned/user': ['password=literal', '{"api_key": "literal"}', "secret: 'literal'",
                          'curl -u user:literal https://example.test', 'token=$TOKEN-literal',
                          r'password=some\ value'],
    }
    for rule, samples in unsafe.items():
        for value in samples:
            assert scan(value) == rule, (value, scan(value))
    for value in ('password=""', 'token=null', 'secret=true', 'password=false', 'token=TOKEN',
                  'token=<token>', 'token=...', 'token=***', 'token=@FILE', 'token=$token',
                  'token=${token}', 'token=${{ secrets.TOKEN }}', 'token="${{ secrets.TOKEN }}"',
                  'password=$PASSWORD # comment', 'token="[masked]"',
                  'Authorization: Bearer <TOKEN>', 'Cookie: session=[masked]',
                  '{"Authorization": "Bearer <TOKEN>"}', '{"Cookie": "session=[masked]"}',
                  'Set-Cookie: session=[masked]; Path=/; SameSite=Lax; HttpOnly',
                  'https://example.test?code=$code', 'curl --user user:$PASSWORD'):
        assert scan(value) is None, (value, scan(value))


def evidence_snapshot_checks_names_types_and_limits(lab):
    module = support.load(SCRIPT).evidence
    snapshot, refused = module['snapshot'], module['Refusal']
    root = lab.scratch({'report.md': 'report\n', 'notes.md': 'notes\n', 'store/data': b'\x00'})
    files, index = snapshot(root, {'kind': 'walk', 'name': 'fixture'}, 1024)
    assert set(files) == {'report.md', 'notes.md', 'index.json'}
    for name in ('cookies.txt', 'auth.json', 'id_rsa', 'login.txt', 'nested/password.log', 'x.env'):
        target = root / 'evidence' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b'never opened')
        try:
            snapshot(root, {}, 1024)
            assert False, name
        except refused as error:
            assert 'name' in str(error) and 'never opened' not in str(error)
        target.unlink()
    for name in ('tokens.txt', 'session-status.txt'):
        (root / 'evidence' / name).write_text('safe\n')
    snapshot(root, {}, 1024)
    target = root / 'evidence/linked.txt'
    target.symlink_to(root / 'report.md')
    try:
        snapshot(root, {}, 1024)
        assert False
    except refused as error:
        assert 'kind/binary' in str(error)
    target.unlink()
    os.link(root / 'report.md', target)
    try:
        snapshot(root, {}, 1024)
        assert False
    except refused:
        pass
    target.unlink()
    (root / 'evidence/large.txt').write_bytes(b'x' * 2000)
    (root / 'scripts').mkdir()
    (root / 'scripts/run.sh').write_text('echo safe\n')
    files, index = snapshot(root, {}, 1024)
    assert not any(name.startswith('evidence/') for name in files)
    assert 'scripts/run.sh' in files and index['omissions']
    (root / 'report.md').write_bytes(b'x' * 2000)
    try:
        snapshot(root, {}, 1024)
        assert False
    except refused as error:
        assert 'size' in str(error)


def evidence_keep_is_local_and_immutable_by_default(lab):
    lab.walk()
    directory, state = lab.walk_state()
    lab.end_run()
    lab.watch()
    kept = lab.tmp / 'qa/evidence' / state['walk']
    assert (kept / 'report.md').read_bytes() == (directory / 'report.md').read_bytes()
    assert not (lab.tmp / 'qa/evidence.git').exists()
    first = lab.run('keep', state['walk']).stdout
    (directory / 'report.md').write_text('changed after preservation\n')
    assert lab.run('keep', state['walk']).stdout == first
    assert (kept / 'report.md').read_text() == '## Findings\nNone.\n'
    assert not list(kept.glob('give-back*'))


def evidence_refusals_retry_notice_without_holding_custody(lab):
    lab.walk()
    directory, state = lab.walk_state()
    lab.end_run(report='Authorization: Bearer literal-fixture\n')
    lab.env['QA_POST_STATUS'] = '1'
    lab.watch()
    assert directory.exists() and lab.walk_state()[1]['slot_claim']['released']
    assert ['give', CHATGPT, '--as', state['holder']] in lab.calls('logins')
    inventory = json.loads((lab.root / 'tools.json').read_text())
    assert inventory['logins_held'] == [] and CHATGPT not in inventory['login_holders']
    assert not (lab.tmp / 'qa/evidence' / state['walk']).exists()
    lab.env['QA_POST_STATUS'] = '0'
    lab.watch()
    notices = [m for m in lab.sent() if m['args'][2] == 'qa: evidence refused']
    assert len(notices) == 2 and 'report.md' in notices[-1]['body'] and 'header/cookie-jar' in notices[-1]['body']
    assert 'literal-fixture' not in str(notices)
    lab.watch()
    assert len([m for m in lab.sent() if m['args'][2] == 'qa: evidence refused']) == 2
    (directory / 'report.md').write_text('safe repaired report\n')
    lab.watch()
    assert (lab.tmp / 'qa/evidence' / state['walk'] / 'report.md').read_text() == 'safe repaired report\n'




def evidence_prune_requires_seven_days_and_pin_guards(lab):
    lab.walk(now='2026-10-01T00:00:00Z')
    directory, state = lab.walk_state()
    lab.end_run()
    lab.watch(now='2026-10-01T00:00:00Z')
    lab.watch(now='2026-10-07T23:59:59Z')
    assert directory.exists()
    lab.run('pin', state['walk'])
    lab.watch(now='2026-10-08T00:00:00Z')
    assert directory.exists()
    lab.run('unpin', state['walk'])
    lab.watch(now='2026-10-08T00:00:00Z')
    assert not directory.exists()
    assert (lab.tmp / 'qa/evidence' / state['walk'] / 'report.md').exists()
    lab.watch(now='2026-10-09T00:00:00Z')
    assert len([m for m in lab.sent() if m['args'][2] == 'qa: walk scratch pruned']) == 1


def evidence_prune_preserves_pauses_and_pending_publication(lab):
    lab.walk(now='2026-10-01T00:00:00Z')
    directory, state = lab.walk_state()
    (directory / 'paused').write_text('waiting for fix\n')
    lab.end_run()
    lab.watch(now='2026-10-01T00:00:00Z')
    lab.watch(now='2026-11-01T00:00:00Z')
    assert directory.exists() and lab.walk_state()[1]['stage'] == 'paused'
    assert not (lab.tmp / 'qa/evidence' / state['walk']).exists()
    lab.run('keep', state['walk'], status=2)
    # A valid but unavailable fixture remote must leave scratch after expiry.
    lab.env.update(QA_EVIDENCE_REMOTE=str(lab.origins / 'unavailable.git'), QA_EVIDENCE_BRANCH='evidence')
    lab.walk('b1', now='2026-10-01T00:00:00Z')
    other_dir, other = lab.walk_states()[1]
    lab.end_run(other)
    lab.watch(now='2026-10-01T00:00:00Z')
    lab.watch(now='2026-11-01T00:00:00Z')
    assert other_dir.exists() and lab.walk_states()[1][1]['slot_claim']['released']


def scratch_bytes_queue_counts_reservations_and_retained_data(lab):
    lab.env.update(QA_WALK_SCRATCH_BYTES='1000', QA_SCRATCH_BUDGET_BYTES='2500')
    lab.walk()
    first, state = lab.walk_state()
    lab.walk('b1')
    assert len(lab.walk_states()) == 2
    # A different kind has slots/logins available but the byte budget is exhausted.
    lab.walk('b2', '--kind', 'claude')
    entries = json.loads(lab.run('queue', '--json').stdout)
    assert len(entries) == 1 and 'scratch budget' in entries[0]['reason']
    assert len(lab.walk_states()) == 2
    # Active walks reserve bytes; ended/paused/pinned scratch is measured instead.
    lab.end_run(state)
    lab.watch()
    assert len(lab.walk_states()) == 2  # retained generated files exceed tiny budget
    shutil.rmtree(first)
    # This fixture simulates a confirmed prune. An unexplained missing scratch
    # directory instead keeps its reservation under conservative measurement.
    path = lab.tmp / 'qa/preservation' / (state['walk'] + '.json')
    kept = json.loads(path.read_text())
    kept['pruned'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    sibling = path.with_suffix('.new')
    sibling.write_text(json.dumps(kept))
    sibling.replace(path)
    lab.watch()
    assert len(lab.walk_states()) == 3 and json.loads(lab.run('queue', '--json').stdout) == []


def evidence_snapshot_never_opens_credentials_or_unsafe_entries(lab):
    from unittest.mock import patch
    module = support.load(SCRIPT).evidence
    root = lab.scratch({'report.md': 'safe\n', 'evidence/auth.json': 'fixture do not open\n'})
    opened = os.open
    def guard(path, *args, **kwargs):
        assert str(path) != 'auth.json', 'credential name was opened'
        return opened(path, *args, **kwargs)
    with patch.object(os, 'open', guard):
        try:
            module['snapshot'](root, {})
            assert False
        except module['Refusal'] as error:
            assert error.rule == 'name'
    (root / 'evidence/auth.json').unlink()
    for content in (b'\x00', b'\xff'):
        (root / 'report.md').write_bytes(content)
        try:
            module['snapshot'](root, {})
            assert False
        except module['Refusal'] as error:
            assert error.rule == 'kind/binary'
    (root / 'report.md').write_text('safe\n')
    fifo = root / 'evidence/wait.txt'
    os.mkfifo(fifo)
    try:
        module['snapshot'](root, {})
        assert False
    except module['Refusal'] as error:
        assert error.rule == 'kind/binary'
    fifo.unlink()
    (root / 'evidence/token=literal.txt').write_text('safe\n')
    try:
        module['snapshot'](root, {})
        assert False
    except module['Refusal'] as error:
        assert 'literal' not in str(error) and 'entry' in str(error)


def evidence_snapshot_detects_replacement_before_read(lab):
    from unittest.mock import patch
    module = support.load(SCRIPT).evidence
    root = lab.scratch({'report.md': 'original\n'})
    opened = os.open
    def replace_before_open(path, *args, **kwargs):
        if path == 'report.md':
            target = root / 'report.md'
            sibling = root / 'changed.md'
            sibling.write_text('changed\n')
            sibling.replace(target)
        return opened(path, *args, **kwargs)
    with patch.object(os, 'open', replace_before_open):
        try:
            module['snapshot'](root, {})
            assert False
        except module['Refusal'] as error:
            assert error.rule == 'changed during snapshot'
    (root / 'report.md').write_text('x' * 1000)
    try:
        module['snapshot'](root, {}, 1024)
        assert False, 'index must count against the cap'
    except module['Refusal'] as error:
        assert error.rule == 'size'


def evidence_check_is_network_free_and_does_not_adopt_scratch(lab):
    root = lab.scratch({'report.md': 'safe\n'})
    lab.env['QA_EVIDENCE_REMOTE'] = str(lab.origins / 'unavailable.git')
    lab.run('keep', '--check', str(root))
    assert not (lab.tmp / 'qa').exists()
    (root / 'report.md').write_text('token=literal-fixture\n')
    result = lab.run('keep', '--check', str(root), status=2)
    assert 'report.md' in result.stderr and 'assigned/user' in result.stderr
    assert 'literal-fixture' not in result.stderr and not (lab.tmp / 'qa').exists()




def evidence_prune_rechecks_custody_claims_processes_and_paths(lab):
    lab.walk(now='2026-10-01T00:00:00Z')
    directory, state = lab.walk_state()
    lab.end_run()
    lab.watch(now='2026-10-01T00:00:00Z')
    expiry = '2026-10-08T00:00:00Z'
    # Saved releases cannot override fresh malformed or live observations.
    for config in (dict(login_list_failure=True), dict(claim_list_lines=['malformed']),
                   dict(unit_job='9'), dict(unit_query_failure=True)):
        before = json.loads((lab.root / 'tools.json').read_text())
        lab.configure(**config)
        lab.watch(now=expiry)
        assert directory.exists(), config
        (lab.root / 'tools.json').write_text(json.dumps(before))
    # Inventory holds for old attempts also keep scratch, without returning an unowned grant.
    lab.configure(logins_held=[CHATGPT], login_holders={CHATGPT: state['holder']},
                  logins_out=[CHATGPT], logins_refused=[CHATGPT])
    lab.watch(now=expiry)
    assert directory.exists()
    lab.configure(logins_held=[], logins_out=[], logins_refused=[])
    protected = directory.with_name('protected-fixture')
    directory.rename(protected)
    directory.symlink_to(protected, target_is_directory=True)
    lab.watch(now=expiry)
    assert directory.is_symlink() and (protected / 'report.md').exists()
    directory.unlink()
    protected.rename(directory)
    lab.watch(now=expiry)
    assert not directory.exists()


def evidence_refused_prune_keeps_one_accepted_notice_with_latest_diagnostic(lab):
    lab.walk(now='2026-10-01T00:00:00Z')
    directory, _ = lab.walk_state()
    lab.end_run(report='token=first-literal\n')
    lab.watch(now='2026-10-01T00:00:00Z')
    (directory / 'report.md').write_text('token=second-literal\n')
    lab.watch(now='2026-10-08T00:00:00Z', extra={'QA_POST_STATUS': '1'})
    # The refusal diagnostic changes in the existing delivered receipt; it
    # does not require another message before otherwise eligible pruning.
    assert not directory.exists()
    assert len([p for p in lab.sent() if p['args'][2] == 'qa: evidence refused']) == 1
    lab.watch(now='2026-10-08T00:00:00Z')
    assert len([p for p in lab.sent() if p['args'][2] == 'qa: walk scratch pruned']) == 2


def evidence_invalid_settings_cannot_block_login_return(lab):
    lab.walk()
    directory, state = lab.walk_state()
    lab.end_run()
    lab.env.update(QA_EVIDENCE_REMOTE='invalid-remote', QA_EVIDENCE_KIB='bad')
    lab.watch()
    assert directory.exists() and lab.walk_state()[1]['slot_claim']['released']
    assert ['give', CHATGPT, '--as', state['holder']] in lab.calls('logins')
    assert not (lab.tmp / 'qa/evidence' / state['walk']).exists()
    lab.env.update(QA_EVIDENCE_REMOTE='', QA_EVIDENCE_KIB='2048')
    lab.watch()
    assert (lab.tmp / 'qa/evidence' / state['walk'] / 'report.md').exists()


def scratch_budget_counts_paused_pinned_and_saved_reservations(lab):
    lab.env.update(QA_WALK_SCRATCH_BYTES='1000', QA_SCRATCH_BUDGET_BYTES='48000000000')
    lab.walk()
    directory, state = lab.walk_state()
    assert state['scratch_bytes'] == 1000
    # Configuration changes do not change active reservations already granted.
    lab.env.update(QA_WALK_SCRATCH_BYTES='2000', QA_SCRATCH_BUDGET_BYTES='3000')
    lab.walk('b1')
    assert len(lab.walk_states()) == 2
    lab.run('pin', state['walk'])
    lab.env['QA_WALK_SCRATCH_BYTES'] = '1'
    lab.walk('b2', '--kind', 'claude')
    assert len(lab.walk_states()) == 2 and 'scratch budget' in lab.run('queue').stdout
    lab.run('queue', 'cancel', json.loads(lab.run('queue', '--json').stdout)[0]['id'])
    (directory / 'paused').write_text('waiting for repair\n')
    lab.end_run(state)
    lab.watch()
    assert lab.walk_states()[0][1]['stage'] == 'paused'
    lab.run('unpin', state['walk'])
    lab.walk('b2', '--kind', 'claude')
    assert len(lab.walk_states()) == 2  # Paused bytes still consume budget without a pin.


def evidence_archive_damage_cannot_authorize_pruning(lab):
    lab.walk(now='2026-10-01T00:00:00Z')
    directory, state = lab.walk_state()
    lab.end_run()
    lab.watch(now='2026-10-01T00:00:00Z')
    archive = lab.tmp / 'qa/evidence' / state['walk']
    original = (archive / 'report.md').read_bytes()
    (archive / 'report.md').write_text('changed archive\n')
    lab.watch(now='2026-10-08T00:00:00Z')
    assert directory.exists()
    lab.run('keep', state['walk'], status=1)
    (archive / 'report.md').write_bytes(original)
    (archive / 'notes').symlink_to(directory)
    # A corrupt recovery manifest cannot redirect a content read through a directory link.
    index = json.loads((archive / 'index.json').read_text())
    index['entries'] = ['evidence/report.md']
    index['files'] = 1
    index['bytes'] = len(original)
    (archive / 'index.json').write_text(json.dumps(index))
    (archive / 'evidence').symlink_to(directory, target_is_directory=True)
    lab.watch(now='2026-10-08T00:00:00Z')
    assert directory.exists()
    lab.run('keep', state['walk'], status=1)


CASES = (
    evidence_archive_damage_cannot_authorize_pruning,
    evidence_snapshot_never_opens_credentials_or_unsafe_entries,
    evidence_snapshot_detects_replacement_before_read,
    evidence_check_is_network_free_and_does_not_adopt_scratch,
    evidence_prune_rechecks_custody_claims_processes_and_paths,
    evidence_refused_prune_keeps_one_accepted_notice_with_latest_diagnostic,
    evidence_invalid_settings_cannot_block_login_return,
    scratch_budget_counts_paused_pinned_and_saved_reservations,
    evidence_scan_rules_and_placeholders,
    evidence_snapshot_checks_names_types_and_limits,
    evidence_keep_is_local_and_immutable_by_default,
    evidence_refusals_retry_notice_without_holding_custody,
    evidence_prune_requires_seven_days_and_pin_guards,
    evidence_prune_preserves_pauses_and_pending_publication,
    scratch_bytes_queue_counts_reservations_and_retained_data,
    a_queued_walk_uses_the_first_free_inventory_slot,
    plus_slot_lists_validate_and_keep_legacy_forms,
    unknown_slot_inventory_refuses_without_claiming,
    a_machine_stuck_recipient_replaces_the_fallback_file,
    stuck_recipient_settings_validate_and_follow_precedence,
    a_walk_records_its_launched_run_on_every_hold,
    a_failed_run_binding_retries_without_cancelling_the_walk,
    a_recovered_launch_binds_its_run_to_the_hold,
    the_queue_json_fixture_matches_real_output,
    the_watcher_selects_the_oldest_ready_entry_once_per_kind,
    a_busy_inventory_slot_is_queued_and_runs_when_freed,
    orphan_release_and_its_notice_survive_an_interrupted_save,
    a_damaged_queue_keeps_custody_cleanup_running,
    a_busy_slot_start_is_queued_then_started,
    a_watcher_refusal_keeps_the_queue_and_updates_one_notice,
    the_queue_lists_and_cancels_without_taking_resources,
    a_queued_resume_no_longer_paused_is_dropped_with_notice,
    pending_attention_notices_retry_until_post_accepts,
    orphan_claims_release_after_ten_minutes_with_exact_what,
    orphan_claims_keep_live_or_uncertain_runs_and_reset_grace,
    stale_legacy_holders_are_silent_at_a_start,
    a_queue_admission_survives_a_crash_after_launch,
    a_local_successor_claim_survives_atomic_release,
    a_remote_successor_claim_survives_atomic_release,
    legacy_saved_claims_release_with_their_exact_what,
    fast_readonly_fixture_results_match_external_services,
    an_overdue_live_launcher_does_not_block_other_walks,
    a_missing_launch_keeps_grace_and_unknown_custody,
    slot_release_refuses_without_the_walks_lock,
    release_preflight_and_delete_exclude_other_walks,
    detached_heads_contained_in_origin_history_are_accepted,
    an_unreadable_grant_keeps_the_claim_until_inventory_confirms_give_back,
    fleet_settings_accept_commas_and_plus_without_whitespace,
    failed_remote_or_unreadable_claim_never_prepares_or_falls_back,
    empty_and_unknown_claim_results_refuse_even_if_record_was_created,
    release_preflight_mismatch_updates_one_notice_and_keeps_successors,
    release_waits_for_give_back_even_when_all_units_are_stopped,
    a_release_crash_before_call_retries_the_durable_intent,
    unknown_walk_holders_alert_once_and_hand_holders_are_untouched,
    a_saved_attempt_holder_authorizes_only_its_exact_stray,
    a_held_named_slot_allows_the_next_free_slot,
    all_named_slots_held_queues_without_taking_anything,
    dirty_slots_are_preserved_refused_and_released,
    a_slot_is_never_created_replaced_or_used_with_the_wrong_origin,
    low_disk_refuses_and_releases_before_taking_a_login,
    target_stays_warm_and_trim_failure_is_logged_before_fetch,
    claims_over_ssh_quote_both_shell_levels_and_use_saved_endpoint,
    claim_release_failure_is_retried_and_alerted_once,
    a_claim_lost_between_acceptance_and_save_gets_orphan_grace,
    an_orphan_claim_without_any_state_waits_for_grace,
    a_saved_claim_precedes_any_checkout_preparation,
    a_release_saved_after_a_crash_never_releases_a_successor,
    a_pause_releases_and_resume_waits_for_its_own_slot,
    a_pause_with_unconfirmed_release_queues_resume_until_retry,
    named_slot_settings_validate_and_override_the_old_counts,
    a_hard_linked_rung_brief_is_never_read_or_copied,
    hard_linked_metadata_is_never_read,
    unowned_metadata_is_never_read,
    symlinked_metadata_is_never_read,
    brief_copy_validates_and_reads_the_same_descriptor,
    queued_and_running_start_jobs_keep_custody,
    a_job_created_during_launcher_scan_keeps_custody,
    hand_give_cannot_release_a_saved_walk_holder_or_claim,
    hand_give_protects_foreign_walks_and_saved_attempts,
    hand_give_refuses_unreadable_saved_custody,
    the_first_kind_is_never_blocked,
    pass_states_are_left_untouched,
    workspace_defaults_and_fixture_overrides_are_gated,
    a_new_walk_grant_checks_existing_claims_before_giving,
    conflicting_walk_claims_give_for_neither,
    unsupported_commands_are_refused_without_state,
    watch_runs_once_per_machine_and_loops_on_its_mailbox,
    deeply_nested_and_oversized_states_keep_custody_without_stopping_checks,
    walk_kind_settings_are_validated_and_follow_precedence,
    a_resume_recovers_its_thread_from_events,
    stale_legacy_claims_allow_a_fabrig_walk_to_end,
    a_current_legacy_holder_keeps_its_login,
    a_legacy_holder_is_protected_even_without_a_named_claim,
    unavailable_inventory_preserves_legacy_claims,
    an_unknown_login_holder_preserves_legacy_claims,
    saved_alerts_retry_when_the_run_state_is_unknown,
    the_stuck_list_is_read_at_each_check,
    no_list_alerts_the_director_alone,
    an_alert_goes_once_per_stuck_login,
    a_refused_alert_is_sent_again,
    a_recipient_launch_error_does_not_block_the_other_alerts,
    stuck_recipients_are_bounded_in_file_order,
    an_oversized_stuck_list_does_not_block_cleanup,
    a_fifo_stuck_list_does_not_block_cleanup,
    a_bare_branch_resolves_to_origins,
    a_build_never_resolves_through_a_tag_or_a_stale_ref,
    a_damaged_walk_state_does_not_block_others_cleanup,
    a_failed_resume_launch_gives_back_and_stays_paused,
    a_failed_walk_fetch_takes_no_login,
    a_kind_at_its_cap_queues_at_once,
    a_linked_log_or_registry_writes_nowhere_else,
    a_linked_pause_marker_is_not_read,
    a_linked_walk_state_keeps_its_grant_held,
    a_manual_take_refuses_unknown_inventory_and_a_broken_cap,
    a_manual_take_selects_its_pool_and_give_passes_through,
    a_non_dumpable_process_does_not_block_walk_cleanup,
    an_ended_not_found_session_with_an_empty_job_releases_custody,
    a_missing_walk_unit_is_ended_after_the_launch_grace,
    a_paused_walk_frees_its_slot_and_logins,
    a_refused_login_starts_nothing,
    a_busy_now_take_queues_and_undoes_the_attempt,
    a_resume_before_the_pause_is_complete_is_refused,
    a_resume_by_name_keeps_its_kind,
    a_resume_refuses_pool_changes_but_accepts_its_cap,
    a_resume_whose_thread_is_gone_starts_fresh,
    a_resume_without_its_meta_starts_fresh,
    a_resumed_launch_without_a_unit_keeps_its_new_grant,
    a_resumed_walk_fetches_before_taking_a_login,
    a_saved_pause_decision_survives_its_marker_removal,
    a_second_pause_has_its_own_clock_event,
    a_take_by_hand_is_refused_past_its_kinds_cap,
    a_third_walk_is_queued_at_once,
    a_timed_out_walk_launch_keeps_custody_for_recovery,
    a_unit_created_during_launcher_scan_keeps_its_custody,
    a_walk_end_append_survives_an_interrupted_save,
    a_walk_fetches_its_build_before_taking_a_login,
    a_walk_grant_lost_in_a_crash_is_given_back,
    a_walk_launch_lost_in_a_crash_is_recovered,
    a_walk_preparation_refusal_returns_its_grants,
    a_walk_reads_its_inventory_strictly,
    a_walk_refuses_invalid_inputs_before_taking_anything,
    a_walk_resolves_origin_branches_and_commit_prefixes,
    a_walk_resolves_remote_branches_despite_colliding_tags,
    a_walk_takes_a_login_and_a_slot_and_starts,
    an_accepted_resume_recovers_only_its_new_run,
    an_interrupted_resume_releases_only_its_new_grant,
    an_old_pending_end_does_not_turn_into_a_pause,
    damaged_attempt_history_keeps_walk_custody,
    deploy_passes_a_literal_dollar,
    deploy_runs_the_real_systemd_run,
    invalid_pause_lines_end_the_walk,
    login_refuses_another_kinds_pool,
    manual_and_generated_walk_holders_never_share_custody,
    manual_kind_holders_stay_held_when_watcher_checks,
    manual_login_commands_refuse_invalid_inputs_before_tools,
    numbering_survives_a_change_of_default_kind,
    pre_kind_walks_drain_before_kind_admission,
    resume_refuses_a_walk_not_paused,
    walks_of_two_kinds_take_their_own_slots_and_pools,
)


def run_case(name, built):
    isolation = runpy.run_path(str(KIT / 'isolation.py'))
    isolation['run_one'](globals()[name], lambda case, root, baseline: case(Lab(root, baseline)), built, 'qa-walk-')


class WalkTests(unittest.TestCase):
    isolated = False
    cases = CASES
    script = Path(__file__).resolve()
    @classmethod
    def setUpClass(cls):
        cls.baseline = tempfile.TemporaryDirectory(prefix='qa-baseline-')
        baseline = Path(cls.baseline.name)
        Lab(baseline)
        if cls.isolated:
            cls.pool = ThreadPoolExecutor(max_workers=8)
            cls.futures = {case.__name__: cls.pool.submit(cls.child, case.__name__, baseline) for case in cls.cases}

    @classmethod
    def child(cls, name, baseline):
        process = subprocess.Popen([sys.executable, '-I', '-B', str(cls.script),
                                    '--one', name, str(baseline)], stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            output = process.communicate(timeout=90)[0].decode(errors='replace')
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                output = process.communicate(timeout=5)[0].decode(errors='replace')
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.communicate()
                output = 'case timed out'
            return 1, output
        return process.returncode, output

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, 'pool'):
            cls.pool.shutdown(wait=True)
        cls.baseline.cleanup()


# Only Git contracts retain writable real repositories.
REAL_REPOSITORIES = (
    'a_bare_branch_resolves_to_origins',
    'a_build_never_resolves_through_a_tag_or_a_stale_ref',
    'a_failed_walk_fetch_takes_no_login',
    'a_resumed_walk_fetches_before_taking_a_login',
    'a_slot_is_never_created_replaced_or_used_with_the_wrong_origin',
    'a_walk_fetches_its_build_before_taking_a_login',
    'a_walk_resolves_origin_branches_and_commit_prefixes',
    'a_walk_resolves_remote_branches_despite_colliding_tags',
    'a_walk_takes_a_login_and_a_slot_and_starts',
    'detached_heads_contained_in_origin_history_are_accepted',
    'dirty_slots_are_preserved_refused_and_released',
    'failed_remote_or_unreadable_claim_never_prepares_or_falls_back',
    'target_stays_warm_and_trim_failure_is_logged_before_fetch',
)


def test_method(name):
    def test(self):
        if hasattr(self, 'futures'):
            code, output = self.futures[name].result()
            self.assertEqual(code, 0, output)
            return
        with tempfile.TemporaryDirectory(prefix='qa-fast-') as directory:
            previous = os.umask(0o077)
            try:
                lab = Lab(Path(directory), Path(self.baseline.name), lightweight=name not in REAL_REPOSITORIES,
                          slot_numbers=(1, 2))
                lab.in_process = name != 'a_walk_takes_a_login_and_a_slot_and_starts'
                with support.case_deadline(90), support.scope(support.load(SCRIPT)):
                    globals()[name](lab)
            finally:
                os.umask(previous)
    return test


for case in CASES:
    setattr(WalkTests, 'test_' + case.__name__, test_method(case.__name__))


class EvidenceRepairTests(unittest.TestCase):
    """Small production-code probes: fresh HOME/state, no child interpreters."""
    def setUp(self):
        from unittest.mock import patch
        self.patch = patch
        temporary = self.enterContext(tempfile.TemporaryDirectory(prefix='qa-repair-'))
        self.root = Path(temporary)
        self.enterContext(patch.dict(os.environ, dict(HOME=str(self.root / 'home'), DEV_ROOT=str(self.root),
                         DEV_TMP=str(self.root / 'tmp'), QA_FIXTURE=str(self.root)), clear=True))
        (self.root / 'home').mkdir()
        (self.root / 'tmp').mkdir()
        previous = os.umask(0o077)
        self.addCleanup(os.umask, previous)
        module = support.load(SCRIPT)
        self.enterContext(support.scope(module))
        self.tool = module.__dict__
        self.ev = self.tool['evidence']
        self.tool['Watch'].check.__globals__['timestamp'] = lambda: '2026-10-08T00:00:00Z'
        self.watch = self.tool['Watch'](self.tool['Workspace'](), 'director@fixture')
        self.watch.workspace.machine = lambda: 'fixture'
        self.watch.options = self.tool['settings'](self.watch.workspace)
        self.walks, self.posts = [], []
        def local_walks(strict=True):
            self.watch.walks_valid = True
            return self.walks
        self.watch.local_walks = local_walks
        self.watch.outstanding = lambda state: {}
        self.watch.unit_status = lambda *a, **kw: 'stopped'
        self.watch.deployments = lambda *a: {}
        def call(tool, *args):
            if tool == 'logins' and args == ('list',):
                return subprocess.CompletedProcess([], 0, 'chatgpt: at rest\n', '')
            if tool == 'post':
                self.posts.append(args)
                return subprocess.CompletedProcess([], 0, '', '')
            raise AssertionError((tool, args))
        self.watch.call = call

    def walk(self, number=1, **updates):
        name = f'rung-repair-{number}'
        directory = self.root / 'tmp/qa-focused' / name
        directory.mkdir(parents=True)
        (directory / 'report.md').write_text('safe fixture report\n')
        info = directory.stat()
        state = dict(walk=name, repo='fabrig', rung='repair', holder='walk/forgejo/' + name,
                     stage='ended', released=True, posted=True, end_logged=True, run='',
                     started='2026-10-01T00:00:00Z', starter='owner@fixture', decision='walk-end',
                     logins={}, given=[], kinds={}, pools={}, requests=[], alerts={}, slot=None,
                     scratch_identity=dict(device=info.st_dev, inode=info.st_ino))
        state.update(updates)
        self.walks.append((directory, state))
        return directory, state

    def kept(self, state, **updates):
        saved = dict(walk=state['walk'], status='kept-locally', digest='a' * 64,
                     ended='2026-10-01T00:00:00Z', local='fixture', remote='', branch='evidence',
                     destination='walks/2026-10-01-' + state['walk'])
        saved['announced'] = self.watch.evidence_identity(saved)
        saved.update(updates)
        return saved

    def test_components_and_whole_paths_are_scanned_before_indexing(self):
        for number, name in enumerate(('--user=user:literal', 'nested/--user=user:literal'), 1):
            directory, _ = self.walk(number)
            target = directory / 'scripts' / name
            target.parent.mkdir(parents=True)
            target.write_text('safe\n')
            with self.subTest(name=name), self.assertRaises(self.ev['Refusal']) as failure:
                self.ev['snapshot'](directory, {})
            self.assertNotIn('literal', str(failure.exception))
            self.assertIn('entry', str(failure.exception))
        directory, _ = self.walk(3)
        (directory / 'scripts/--user=user:literal').mkdir(parents=True)
        with self.assertRaises(self.ev['Refusal']):
            self.ev['snapshot'](directory, {})

    def test_archive_index_components_refuse_before_opening_capture(self):
        directory, _ = self.walk()
        index = dict(entries=['scripts/--user=user:literal'], files=1, bytes=5, omissions=[])
        (directory / 'index.json').write_text(json.dumps(index))
        target = directory / index['entries'][0]
        target.parent.mkdir()
        target.write_text('safe\n')
        opened = os.open
        def guard(path, *args, **kwargs):
            self.assertNotEqual(path, '--user=user:literal', 'unsafe indexed capture was opened')
            return opened(path, *args, **kwargs)
        with self.patch.object(os, 'open', guard), self.assertRaises(self.ev['Refusal']) as failure:
            self.ev['read_snapshot'](directory)
        self.assertNotIn('literal', str(failure.exception))
        self.assertIn('entry', str(failure.exception))

    def test_replacement_between_check_and_quarantine_is_restored(self):
        directory, state = self.walk()
        protected = directory.parent / 'paused-protected'
        protected.mkdir()
        (protected / 'precious').write_text('retained paused work')
        original = directory.parent / 'original-parked'
        stat_call = os.stat
        swapped = False
        def swap_after_check(path, *args, **kwargs):
            nonlocal swapped
            info = stat_call(path, *args, **kwargs)
            if path == state['walk'] and kwargs.get('dir_fd') is not None and not swapped:
                swapped = True
                directory.rename(original)
                protected.rename(directory)
            return info
        saved = self.kept(state)
        with self.patch.object(os, 'stat', swap_after_check):
            self.watch.prune_walk(directory, state, saved)
        self.assertTrue(swapped)
        self.assertEqual((directory / 'precious').read_text(), 'retained paused work')
        self.assertTrue((original / 'report.md').exists())
        self.assertNotIn('pruned', saved)
        self.assertFalse(any('scratch pruned' in str(post) for post in self.posts))

    def test_missing_identity_retains_scratch_and_notifies_once(self):
        directory, state = self.walk()
        del state['scratch_identity']
        saved = self.kept(state)
        self.watch.prune_walk(directory, state, saved)
        self.watch.prune_walk(directory, state, saved)
        self.assertTrue(directory.exists())
        self.assertEqual(len(self.posts), 1)
        self.assertIn('identity', str(self.posts))
        self.assertNotIn('pruned', saved)

    def test_archive_entry_bound_precedes_capture_opens(self):
        directory, _ = self.walk()
        names = ['scripts/a.txt', 'scripts/b.txt', 'scripts/c.txt']
        (directory / 'index.json').write_text(json.dumps(dict(entries=names, files=3, bytes=15)))
        (directory / 'scripts').mkdir()
        for name in names:
            (directory / name).write_text('safe\n')
        opened = os.open
        def guard(path, *args, **kwargs):
            self.assertNotIn(path, ('a.txt', 'b.txt', 'c.txt'), 'capture opened beyond known index bound')
            return opened(path, *args, **kwargs)
        with self.patch.dict(self.ev['read_snapshot'].__globals__, MAX_ENTRIES=2):
            with self.patch.object(os, 'open', guard), self.assertRaises(self.ev['Refusal']) as failure:
                self.ev['read_snapshot'](directory)
        self.assertIn('bound', str(failure.exception))

    def test_interrupted_quarantine_resumes_from_saved_name(self):
        directory, state = self.walk()
        saved = self.kept(state)
        opened = os.open
        def interrupted(path, *args, **kwargs):
            if str(path).startswith('.qa-prune-'):
                raise OSError('fixture interruption after rename')
            return opened(path, *args, **kwargs)
        with self.patch.object(os, 'open', interrupted), self.assertRaises(OSError):
            self.watch.prune_walk(directory, state, saved)
        quarantine = directory.parent / saved['quarantine']
        self.assertFalse(directory.exists())
        self.assertTrue((quarantine / 'report.md').exists())
        self.assertEqual(self.watch.read_state(self.watch.preservation_path(state))['quarantine'], quarantine.name)
        self.watch.options.update(QA_WALK_SCRATCH_BYTES=1, QA_SCRATCH_BUDGET_BYTES=1)
        with self.assertRaises(self.tool['Deferred']):
            self.watch.scratch_room(self.walks)
        self.watch.prune_walk(directory, state, saved)
        self.assertFalse(quarantine.exists())
        self.assertIn('pruned', saved)
        self.assertEqual(len(self.posts), 1)

    def test_snapshot_entry_depth_and_time_bounds(self):
        for number, limit in enumerate(('entries', 'depth', 'time'), 1):
            directory, _ = self.walk(number)
            (directory / 'scripts/a/b').mkdir(parents=True)
            (directory / 'scripts/a/b/safe.txt').write_text('safe\n')
            limits = dict(MAX_ENTRIES=1 if limit == 'entries' else 100,
                          MAX_DEPTH=1 if limit == 'depth' else 20,
                          MAX_SECONDS=0 if limit == 'time' else 5)
            with self.subTest(limit=limit), self.patch.dict(self.ev['snapshot'].__globals__, limits):
                with self.assertRaises(self.ev['Refusal']) as failure:
                    self.ev['snapshot'](directory, {})
                self.assertIn('bound', str(failure.exception))

    def test_scan_follows_all_custody_cleanup_outside_admission(self):
        for number in (1, 2):
            self.walk(number, stage='ending', run=f'fixture-{number}', posted=False, end_logged=False)
        events, scans = [], []
        watch = self.watch
        watch.stuck_addresses = lambda: []
        watch.retry_notices = lambda: None
        watch.give_strays = lambda *a, **kw: None
        watch.repair_slot_claims = lambda *a: None
        watch.check_queue = lambda: None
        watch.record_run = lambda *a: None
        watch.unit_stopped = lambda *a: True
        watch.alert = lambda *a: None
        watch.facts = lambda *a: dict(exit='0')
        def end(directory, state):
            events.extend([('give', state['walk']), ('release', state['walk'])])
            state['released'] = True
        watch.end = end
        watch.walk_event = lambda directory, state, *a: state.update(end_logged=True)
        def prepare(directory, state):
            self.assertIsNone(watch.walk_lock)
            self.assertEqual(len(events), 4)
            scans.append(state['walk'])
            raise self.tool['Problem']('fixture scan refusal')
        watch.prepare_evidence = prepare
        watch.check(watch.options)
        self.assertEqual(scans, [s['walk'] for _, s in self.walks])

    def test_retention_rejects_unknown_or_inconsistent_end_times(self):
        for number, (started, ended) in enumerate((
                ('2026-10-01T00:00:00Z', 'unknown'),
                ('2026-10-01T00:00:00Z', '2026-09-30T00:00:00Z'),
                ('unknown', '2026-10-01T00:00:00Z'),
                ('2026-10-01T00:00:00Z', None),
                (None, '2026-10-01T00:00:00Z'),
                ('2026-10-01T00:00:00Z', '2026-10-09T00:00:00Z')), 1):
            directory, state = self.walk(number, started=started)
            saved = self.kept(state, ended=ended)
            self.watch.save_preservation(state, saved)
            with self.subTest(started=started, ended=ended):
                with self.assertRaises(self.tool['Problem']):
                    self.watch.preservation(state)

    def test_unknown_end_time_cannot_prune(self):
        directory, state = self.walk()
        self.watch.prune_walk(directory, state, self.kept(state, ended='unknown'))
        self.assertTrue(directory.exists())
        self.assertFalse(self.posts)

    def test_resume_growth_cannot_subtract_other_reservations(self):
        directory, paused = self.walk(stage='paused')
        other_dir, active = self.walk(2, stage='running', released=False, scratch_bytes=20)
        self.watch.options.update(QA_WALK_SCRATCH_BYTES=20, QA_SCRATCH_BUDGET_BYTES=25)
        def growing_size(path):
            growing_size.calls += 1
            return 10 if growing_size.calls == 1 else 30
        growing_size.calls = 0
        with self.patch.dict(self.ev, directory_bytes=growing_size):
            with self.assertRaises(self.tool['Deferred']):
                self.watch.scratch_room(self.walks, resume=paused['walk'])
        self.assertLessEqual(growing_size.calls, 1)

    def test_publication_needs_both_explicit_settings(self):
        for number, (remote, branch) in enumerate((('', ''), ('repo', ''), ('', 'evidence'), ('repo', 'evidence')), 1):
            directory, state = self.walk(number)
            remote = str(self.root / 'qa.git') if remote else ''
            with self.subTest(remote=bool(remote), branch=branch), self.patch.dict(os.environ,
                    dict(QA_EVIDENCE_REMOTE=remote, **({'QA_EVIDENCE_BRANCH': branch} if branch else {}))):
                self.watch.options = self.tool['settings'](self.watch.workspace)
                saved = self.watch.prepare_evidence(directory, state)
                self.assertEqual(saved['status'], 'waiting' if remote and branch else 'kept-locally')
                self.assertEqual(bool(saved['remote']), bool(remote and branch))
                self.assertFalse((self.watch.directory / 'evidence.git').exists())


    def _measurement_entries(self, names, error=None):
        class Entries:
            def __init__(self):
                self.values = iter(names)
            def __enter__(self):
                return self
            def __exit__(self, *args):
                self.close()
            def __iter__(self):
                return self
            def __next__(self):
                from types import SimpleNamespace
                try:
                    return SimpleNamespace(name=next(self.values))
                except StopIteration:
                    if error is not None:
                        raise error
                    raise
            def close(self):
                pass
        return Entries()

    def test_scratch_size_accepts_more_than_4096_entries(self):
        from types import SimpleNamespace
        directory, _ = self.walk()
        original_stat = os.stat
        def metadata(path, *args, **kwargs):
            if isinstance(path, str) and path.startswith('fake-'):
                return SimpleNamespace(st_size=3, st_mode=0o100600)
            return original_stat(path, *args, **kwargs)
        with self.patch.object(os, 'scandir', lambda fd: self._measurement_entries(
                f'fake-{n}' for n in range(5000))), self.patch.object(os, 'stat', metadata):
            result = self.ev['directory_bytes'](directory)
        self.assertTrue(result['complete'])
        self.assertEqual(result['bytes'], directory.stat().st_size + 15000)

    def test_scratch_size_has_no_depth_cap_and_never_follows_links_or_reads_content(self):
        directory, _ = self.walk()
        descendants = []
        deepest = directory
        for _ in range(40):
            deepest /= 'box'
            deepest.mkdir()
            descendants.append(deepest)
        payload = deepest / 'state'
        payload.write_text('fixture data')
        outside = self.root / 'outside'
        outside.mkdir()
        (outside / 'large').write_bytes(b'x' * 10000)
        link = deepest / 'outside-link'
        link.symlink_to(outside, target_is_directory=True)
        expected = (directory.stat().st_size + (directory / 'report.md').stat().st_size
                    + sum(p.stat().st_size for p in descendants) + payload.stat().st_size + link.lstat().st_size)
        opened = os.open
        def directories_only(path, flags, *args, **kwargs):
            self.assertTrue(flags & os.O_DIRECTORY, 'measurement opened file contents')
            self.assertNotEqual(path, 'outside-link', 'measurement followed a symlink')
            return opened(path, flags, *args, **kwargs)
        with self.patch.object(os, 'open', directories_only):
            result = self.ev['directory_bytes'](directory)
        self.assertTrue(result['complete'])
        self.assertEqual(result['bytes'], expected)

    def test_scratch_measurement_keeps_partial_counts_on_filesystem_errors(self):
        directory, _ = self.walk()
        (directory / 'large').write_bytes(b'x' * 20000)
        expected = directory.stat().st_size + 20000
        for error in (PermissionError('fixture'), FileNotFoundError('fixture'), OSError('fixture'), RuntimeError('fixture')):
            with self.subTest(error=type(error).__name__), self.patch.object(os, 'scandir',
                    lambda fd: self._measurement_entries(['large'], error)):
                result = self.ev['directory_bytes'](directory)
                self.assertFalse(result['complete'])
                self.assertEqual(result['bytes'], expected)
                self.assertEqual(result['reason'], type(error).__name__)

    def test_scratch_time_limit_preserves_counted_bytes(self):
        directory, _ = self.walk()
        (directory / 'large').write_bytes(b'x' * 20000)
        expected = directory.stat().st_size + 20000
        clock = [0]
        stat_call = os.stat
        def slow_stat(path, *args, **kwargs):
            info = stat_call(path, *args, **kwargs)
            if path == 'large' and kwargs.get('dir_fd') is not None:
                clock[0] = 11
            return info
        with self.patch.object(time, 'monotonic', lambda: clock[0]), self.patch.object(os, 'stat', slow_stat), \
                self.patch.object(os, 'scandir', lambda fd: self._measurement_entries(['large'])):
            result = self.ev['directory_bytes'](directory)
        self.assertFalse(result['complete'])
        self.assertEqual(result['bytes'], expected)
        self.assertEqual(result['reason'], 'TimeoutError')

    def test_incomplete_size_charges_maximum_and_retries_one_notice(self):
        directory, state = self.walk(scratch_bytes=100)
        calls = []
        original_call = self.watch.call
        def post(tool, *args):
            if tool == 'post':
                calls.append(args)
                return subprocess.CompletedProcess([], 1 if len(calls) == 1 else 0, '', '')
            return original_call(tool, *args)
        self.watch.call = post
        for counted in (40, 150):
            self.watch.options.update(QA_WALK_SCRATCH_BYTES=10, QA_SCRATCH_BUDGET_BYTES=max(100, counted) + 9)
            measurement = dict(bytes=counted, complete=False, reason='PermissionError', missing=False)
            with self.patch.dict(self.ev, directory_bytes=lambda *a, **kw: measurement):
                with self.assertRaises(self.tool['Deferred']) as failure:
                    self.watch.scratch_room([(directory, state)])
            self.assertIn(f'{max(100, counted)} bytes used', str(failure.exception))
            self.watch.attention_attempted.clear()
            self.watch.retry_notices()
        self.assertEqual(len(calls), 2)
        notices = list((self.watch.directory / 'attention').glob('*.json'))
        self.assertEqual(len(notices), 1)
        self.assertTrue(self.watch.read_state(notices[0])['delivered'])

    def test_manual_measurement_notice_waits_for_the_watcher_director(self):
        directory, state = self.walk(scratch_bytes=100)
        self.watch.director = ''
        def failed(*args, **kwargs):
            raise OSError('fixture')
        with self.patch.dict(self.ev, directory_bytes=failed):
            self.watch.scratch_room([(directory, state)])
        self.assertFalse(self.posts)
        notices = list((self.watch.directory / 'attention').glob('*.json'))
        self.assertEqual(len(notices), 1)
        self.watch.director = 'director@fixture'
        self.watch.retry_notices()
        self.assertEqual(len(self.posts), 1)
        self.assertTrue(self.watch.read_state(notices[0])['delivered'])

    def test_missing_or_invalid_measurement_state_keeps_reservation(self):
        directory, state = self.walk(scratch_bytes=100)
        (directory / 'report.md').unlink()
        directory.rmdir()
        self.assertEqual(self.watch.scratch_measurement(directory, state), 100)
        self.assertEqual(len(self.posts), 1)
        # Malformed preservation metadata must not lose a valid partial count,
        # escape admission, or make measurement visit an unvalidated path.
        self.watch.options.update(QA_WALK_SCRATCH_BYTES=10, QA_SCRATCH_BUDGET_BYTES=159)
        for saved in ([], None, {'quarantine': '../outside'}):
            paths = []
            def size(path, **kwargs):
                paths.append(path)
                return dict(bytes=150, complete=True, reason=None, missing=False)
            self.tool['replace'](self.watch.preservation_path(state), json.dumps(saved).encode())
            with self.subTest(saved=saved):
                self.assertEqual(self.watch.scratch_measurement(directory, state), 100)
            with self.subTest(saved=saved), self.patch.dict(self.ev, directory_bytes=size):
                with self.assertRaises(self.tool['Deferred']) as failure:
                    self.watch.scratch_room([(directory, state)])
                self.assertIn('150 bytes used', str(failure.exception))
                self.assertEqual(paths, [directory])
        self.assertEqual(len(self.posts), 1)

    def test_notice_failure_cannot_escape_size_admission(self):
        directory, state = self.walk(scratch_bytes=100)
        def failed(*args, **kwargs):
            raise self.ev['Refusal']('fixture', 'enumeration bound')
        def no_notice(*args, **kwargs):
            raise RuntimeError('fixture notice unavailable')
        self.watch.options.update(QA_WALK_SCRATCH_BYTES=10, QA_SCRATCH_BUDGET_BYTES=109)
        with self.patch.dict(self.ev, directory_bytes=failed), self.patch.object(self.watch, 'notify_once', no_notice):
            with self.assertRaises(self.tool['Deferred']):
                self.watch.scratch_room([(directory, state)])

    def test_quarantine_shares_size_deadline_and_uses_one_reservation_floor(self):
        directory, state = self.walk(scratch_bytes=500)
        quarantine = '.qa-prune-' + state['walk'] + '-' + 'a' * 32
        self.watch.save_preservation(state, self.kept(state, quarantine=quarantine))
        deadlines = []
        def partial(path, deadline=None):
            deadlines.append(deadline)
            return dict(bytes=100 if path == directory else 200, complete=path == directory,
                        reason=None if path == directory else 'TimeoutError', missing=False)
        self.watch.options.update(QA_WALK_SCRATCH_BYTES=10, QA_SCRATCH_BUDGET_BYTES=509)
        with self.patch.object(time, 'monotonic', lambda: 0), self.patch.dict(self.ev, directory_bytes=partial):
            with self.assertRaises(self.tool['Deferred']) as failure:
                self.watch.scratch_room([(directory, state)])
        self.assertIn('500 bytes used', str(failure.exception))
        self.assertEqual(deadlines, [10, 10])

    def test_changing_failures_update_one_notice_without_resending(self):
        from contextlib import ExitStack
        watch = self.watch
        original_call = watch.call
        messages = []
        def call(tool, *args):
            if tool == 'post':
                messages.append((args[-2], Path(args[-1]).read_text()))
            return original_call(tool, *args)
        watch.call = call
        for index, site in enumerate(('queue', 'claim', 'orphan', 'evidence', 'measurement', 'overdue'), 1):
            with self.subTest(site=site), ExitStack() as patches:
                attention = watch.directory / 'attention'
                if attention.exists():
                    shutil.rmtree(attention)
                self.posts.clear()
                messages.clear()
                watch.attention_attempted.clear()
                self.walks.clear()
                directory, state = self.walk(index)
                saved = self.kept(state)
                changing = [0]
                subject = None
                rounds = 100 if site == 'queue' else 4
                if site == 'queue':
                    entry = dict(id='a' * 32, kind='forgejo', repo='fabrig', rung='repair', cap=180,
                                 build='main', resume=None, after=[], login=['chatgpt'], reason='',
                                 starter='owner@fixture', since=state['started'], order=1)
                    watch.save_queue(entry)
                    watch.walks_valid = True
                    def failed_start(*args):
                        raise RuntimeError(f'fixture temp-{changing[0]} scratch-{changing[0]}')
                    patches.enter_context(self.patch.dict(watch.check_queue.__globals__, start_walk=failed_start))
                    invoke = watch.check_queue
                elif site == 'claim':
                    state['slot_claim'] = dict(host='fixture', slot=1, owner='s/qa', ssh='',
                                              what='qa walk ' + state['walk'] + ' attempt 1 claim ' + 'a' * 32)
                    def invoke():
                        state['slot_claim']['release_result'] = f'fixture temp-{changing[0]}'
                        watch.claim_notice(state)
                elif site == 'orphan':
                    patches.enter_context(self.patch.dict(watch.options,
                        QA_WALK_KINDS={'forgejo': dict(numbers=[1])}))
                    host, owner = watch.options['QA_SLOT_HOST'], watch.options['QA_CLAIM_OWNER']
                    what = 'qa walk ' + state['walk'] + ' attempt 1 claim ' + 'a' * 32
                    key = f'orphan slot {host} 1 {owner} {what}'
                    observation = dict(key=key, since=state['started'], released=False,
                                       name=state['walk'], slot=1, what=what, host=host)
                    path = watch.directory / 'orphans' / (hashlib.sha256(key.encode()).hexdigest() + '.json')
                    self.tool['replace'](path, json.dumps(observation).encode())
                    row = f'{host} 1 [{owner}]: {owner}: {what} (since 2026-10-01T00:00:00Z); held fixture'
                    def slot_call(claim, operation, *args):
                        return subprocess.CompletedProcess([], 0, row, '') if operation == 'list' else \
                            subprocess.CompletedProcess([], 1, '', f'fixture temp-{changing[0]}')
                    patches.enter_context(self.patch.object(watch, 'slot_call', slot_call))
                    patches.enter_context(self.patch.object(watch, 'orphan_live', lambda *a: None))
                    invoke = lambda: watch.repair_slot_claims([])
                elif site == 'evidence':
                    saved.pop('digest')
                    saved.update(status='refused')
                    saved.pop('announced')
                    patches.enter_context(self.patch.object(watch, 'prune_walk', lambda *a: None))
                    subject = 'qa: evidence refused'
                    def invoke():
                        saved.update(refusal=f'fixture temp-{changing[0]}', refusal_digest=f'{changing[0]:064x}')
                        watch.preserve_walk(directory, state, None, saved)
                elif site == 'measurement':
                    patches.enter_context(self.patch.dict(self.ev, directory_bytes=lambda *a, **kw:
                        dict(bytes=100 + changing[0], complete=False, missing=False, reason='OSError')))
                    def invoke():
                        # Manual admission must also refresh its pending receipt.
                        watch.director = '' if changing[0] < 2 else 'director@fixture'
                        watch.scratch_measurement(directory, state)
                else:
                    state.update(stage='starting', run='')
                    def invoke():
                        state['started'] = f'2026-10-0{changing[0] + 1}T00:00:00Z'
                        watch.overdue_launch_notice(state, f'fixture temp-{changing[0]}')
                for attempt in range(rounds):
                    changing[0] = attempt
                    watch.attention_attempted.clear()  # Separate watcher passes.
                    invoke()
                receipts = list(attention.glob('*.json'))
                self.assertEqual(len(receipts), 1, (site, len(receipts)))
                receipt = watch.read_state(receipts[0])
                self.assertTrue(receipt['delivered'])
                diagnostic = 'Counted 103 bytes' if site == 'measurement' else f'fixture temp-{rounds - 1}'
                self.assertIn(diagnostic, receipt['body'])
                self.assertNotIn('temp-', receipt['key'])
                self.assertNotIn('2026-', receipt['key'])
                matching = [message for message in messages if subject is None or message[0] == subject]
                self.assertEqual(len(matching), 1, (site, messages))
                if site == 'queue':
                    self.assertIn('scratch-99', watch.queue_entries()[0]['reason'])
                if site == 'evidence':
                    self.assertEqual(len(messages), 2)  # One director notice and one starter status.
                    # Stable identities still require initial notice acceptance
                    # before an otherwise eligible refused walk can be pruned.
                    receipt['delivered'] = False
                    self.tool['replace'](receipts[0], json.dumps(receipt).encode())
                    self.tool['Watch'].prune_walk(watch, directory, state, saved)
                    self.assertTrue(directory.exists())
                    receipt['delivered'] = True
                    self.tool['replace'](receipts[0], json.dumps(receipt).encode())
                # A fresh watcher retries the durable receipt without resending it.
                fresh = self.tool['Watch'](watch.workspace, 'director@fixture')
                fresh.call = call
                fresh.retry_notices()
                self.assertEqual(len(messages), 2 if site == 'evidence' else 1)

    def test_watcher_retries_each_failed_step_and_reaches_next_walk_and_pass(self):
        watch = self.watch
        watch.stuck_addresses = lambda: []
        watch.give_strays = lambda *a, **kw: None
        watch.repair_slot_claims = lambda *a: None
        watch.finish_walk = lambda directory, state, kept: state
        watch.save_queue = lambda entry: None
        watch.drop_queue = lambda identity: self.fail('fixture entry should remain queued')
        original_preserve = watch.preserve_walk
        for index, (phase, error_type) in enumerate((p, e) for p in ('measurement', 'prepare', 'preserve', 'prune')
                for e in (self.ev['Refusal'], OSError, RuntimeError)):
            with self.subTest(phase=phase, error=error_type.__name__):
                self.walks.clear()
                first = self.walk(index * 2 + 1)
                second = self.walk(index * 2 + 2)
                events = []
                def failure():
                    return error_type('fixture', 'fake refusal') if error_type is self.ev['Refusal'] else error_type('fixture')
                def size(path, **kwargs):
                    events.append(('measurement', path.name))
                    if phase == 'measurement' and path == first[0]:
                        raise failure()
                    return dict(bytes=10, complete=True, reason=None, missing=False)
                def prepare(directory, state):
                    events.append(('prepare', state['walk']))
                    if phase == 'prepare' and state['walk'] == first[1]['walk']:
                        raise failure()
                    return self.kept(state)
                def prune(directory, state, saved):
                    events.append(('prune', state['walk']))
                    if phase == 'prune' and state['walk'] == first[1]['walk']:
                        raise failure()
                def preserve(directory, state, descriptor, saved=None):
                    events.append(('preserve', state['walk']))
                    if phase == 'preserve' and state['walk'] == first[1]['walk']:
                        raise failure()
                    return original_preserve(directory, state, descriptor, saved)
                def start(args, workspace, service, entry):
                    service.scratch_room([first if entry['kind'] == 'forgejo' else second])
                    return 1
                entries = [dict(id=str(n) * 32, kind=kind, repo='fabrig', rung='repair', cap=180,
                                build='main', resume=None, after=[], login=['chatgpt'], reason=None)
                           for n, kind in ((1, 'forgejo'), (2, 'claude'))]
                watch.queue_entries = lambda: entries
                watch.release_slot = lambda directory, state: events.append(('cleanup', state['walk']))
                watch.prepare_evidence, watch.prune_walk, watch.preserve_walk = prepare, prune, preserve
                with self.patch.dict(self.ev, directory_bytes=size), \
                        self.patch.dict(watch.check_queue.__globals__, start_walk=start):
                    watch.check(watch.options)
                    watch.check(watch.options)
                for step in ('cleanup', 'measurement', 'prepare', 'preserve', 'prune'):
                    self.assertEqual(events.count((step, second[1]['walk'])), 2, (phase, step, events))
                self.assertEqual(events.count((phase, first[1]['walk'])), 2, events)


if __name__ == '__main__':
    if sys.argv[1:2] == ['--one']:
        run_case(sys.argv[2], Path(sys.argv[3]))
    else:
        unittest.main(verbosity=2)
