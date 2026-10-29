#!/usr/bin/env python3
"""Offline walk cases, each a unittest in its own process and temporary HOME."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import runpy

KIT = Path(__file__).resolve().parent
SCRIPT = KIT / 'qa'
HUNG_TOOL_S = 60
P = '20261026-0915-fabrig'
CHATGPT = 'chatgpt'
CLAUDE = 'claude'
REAL = 'real-model'

WATCH_TOOLS = r'''import atexit, fnmatch, json, os, sys, shlex, shutil, signal, subprocess, time
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

def hang(when):
    operation = name + ':' + (args[0] if args else '')
    if config.get('hang', {}).get(operation) == when:
        (root / 'hung-tool').write_text(str(os.getpid()))
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

if name == 'cargo':
    assert args == ['fetch', '--locked'], args
    if 'cargo_lock' in config:
        assert Path('Cargo.lock').read_text() == config['cargo_lock']
    if config.get('cargo_refusal'):
        sys.exit(config['cargo_refusal'])
elif name == 'codex-run':
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
    runs.mkdir(parents=True, exist_ok=True)
    run = 'fixture-' + str(len(list(runs.glob('fixture-*'))) + 1)
    state = runs / run
    state.mkdir()
    started = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    (state / 'thread').write_text('fixture thread')
    (state / 'meta').write_text(f'model=gpt-6.1-sol\neffort=high\nstarted={started}\ntask={task}\nreport={report}\non_stop={args[4]}\n')
    Path(report).write_text(f'codex-run: run {run} is writing this report.\n')
    process = root / 'proc' / str(os.getpid())
    process.mkdir(parents=True)
    (process / 'cmdline').write_bytes(b'\0'.join(os.fsencode(word) for word in sys.argv) + b'\0')
    atexit.register(shutil.rmtree, process)
    hang('after')
    if config.get('delay_before_unit'):
        (root / 'launch-waiting').write_text(str(os.getpid()))
        while not (root / 'allow-launch').exists():
            time.sleep(0.01)
    (state / 'unit').touch()
    if config.get('interrupt_launch'):
        os.kill(os.getppid(), 9)
    print(run, state)
elif name == 'systemd-run':
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
    unit = args[-1].removesuffix('.service')
    run = unit.removeprefix('codex-run-')
    deployment = unit.startswith('qa-')
    path = units / (unit + '.json')
    saved = json.loads(path.read_text()) if deployment and path.exists() else None
    pass_name = unit.removeprefix('qa-').removesuffix('-*') if args[1] == 'list-units' else ''
    for owner, operation in config.get('hung_systemctl', {}).items():
        if args[1] == operation and (pass_name == owner or fnmatch.fnmatchcase(unit, 'qa-' + owner + '-[a-z]*')):
            child = subprocess.Popen([sys.executable, '-I', '-B', '-c', 'import time; time.sleep(600)'])
            (root / ('hung-' + owner)).write_text(f'{os.getpid()} {child.pid}')
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
                print('Job=' + config.get('unit_jobs', {}).get(unit, '0'))
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
                print('Job=' + config.get('unit_job', '0'))
        sys.exit(0)
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
        (root / 'take-waiting').write_text(str(os.getpid()))
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
    assert args[0] in ('take', 'give'), args
    login = args[1]
    position = args.index('--as')
    holder = args[position + 1]
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
        sys.exit(config.get('wait', [4])[index])
    assert args == ['read', 'qa-watch']
    print('fixture end mail')
'''

class Lab:
    def __init__(self, root, built=None):
        self.root = root
        self.home, self.tmp = root / 'home', root / 'tmp'
        self.origins = root / 'origins'
        self.post_log = root / 'post.jsonl'
        self.post = root / 'post'
        for path in (self.home, self.tmp, self.origins, root / 'proc'):
            path.mkdir(exist_ok=True)
        self.env = dict(PATH=str(root) + os.pathsep + os.environ['PATH'], HOME=str(self.home), DEV_ROOT=str(root),
                        DEV_TMP=str(self.tmp), QA_FIXTURE=str(root), QA_POST_LOG=str(self.post_log), QA_POST_STATUS='0',
                        USER='fixture', POST_NAME='o/fixture', GIT_CONFIG_GLOBAL='/dev/null', GIT_CONFIG_NOSYSTEM='1',
                        GIT_AUTHOR_NAME='Fixture', GIT_AUTHOR_EMAIL='fixture@invalid',
                        GIT_COMMITTER_NAME='Fixture', GIT_COMMITTER_EMAIL='fixture@invalid',
                        GIT_ALLOW_PROTOCOL='file', LC_ALL='C.UTF-8', PYTHONDONTWRITEBYTECODE='1')
        for index, (key, value) in enumerate((('maintenance.auto', 'false'), ('gc.auto', '0'),
                                             ('fetch.autoMaintenance', 'false'), ('receive.autogc', 'false'))):
            self.env[f'GIT_CONFIG_KEY_{index}'] = key
            self.env[f'GIT_CONFIG_VALUE_{index}'] = value
        self.env['GIT_CONFIG_COUNT'] = '4'
        self.configure(pools={CHATGPT: [CHATGPT, 'chatgpt-2', 'chatgpt-3'], CLAUDE: [CLAUDE, 'claude-2', 'claude-3']})
        for name in ('post', 'codex-run', 'systemctl', 'systemd-run', 'logins', 'cargo'):
            tool = root / name
            executable(tool, WATCH_TOOLS)
            self.env['QA_' + name.upper().replace('-', '_')] = str(tool)
        self.products = {'fabrig': root / 'fabrig'}
        self.serial = 0
        checkout = self.products['fabrig']
        if built is not None:
            shutil.copytree(built / 'fabrig', checkout)
            shutil.copytree(built / 'origins/fabrig.git', self.origins / 'fabrig.git')
            self.git(checkout, 'remote', 'set-url', 'origin', str(self.origins / 'fabrig.git'))
            return
        self.git(root, 'init', '-b', 'main', str(checkout))
        self.git(checkout, 'commit', '--allow-empty', '-m', 'baseline')
        self.git(root, 'clone', '--bare', str(checkout), str(self.origins / 'fabrig.git'))
        self.git(checkout, 'remote', 'add', 'origin', str(self.origins / 'fabrig.git'))


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
        command = [sys.executable, '-I', '-B', str(SCRIPT), *args]
        if now is not None:
            # Own the clock only in the fixture interpreter, never in qa's CLI.
            driver = (f'import runpy, sys; tool = runpy.run_path({str(SCRIPT)!r}); '
                      f'tool["main"].__globals__["timestamp"] = lambda: {now!r}; '
                      'sys.exit(tool["main"]())')
            command = [sys.executable, '-I', '-B', '-c', driver, *args]
        result = subprocess.run(command, env=dict(self.env, **(extra or {})), cwd=self.root,
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, timeout=HUNG_TOOL_S)
        assert result.returncode == status, (args, result.returncode, result.stdout, result.stderr)
        return result

    def head(self):
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
            path.write_bytes(b'Rung fixture brief.\n\x00Preserve these bytes.\n')
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


def a_detached_pipe_cannot_hold_a_timed_out_command(lab):
    marker = lab.root / 'detached.pid'
    script = lab.root / 'detach.py'
    script.write_text(f'''import os, time
from pathlib import Path
if os.fork() == 0:
    os.setsid()
    Path({str(marker)!r}).write_text(str(os.getpid()))
time.sleep(60)
''')
    driver = f'''import runpy, sys, time
tool = runpy.run_path({str(SCRIPT)!r})
start = time.monotonic()
result = tool['command']([sys.executable, '-I', '-B', {str(script)!r}], timeout=0.3)
assert result.returncode == 124
assert time.monotonic() - start < 7
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
    result = subprocess.run([sys.executable, '-I', '-B', '-c', driver], env=lab.env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert list(map(json.loads, log.read_text().splitlines())) == [['systemctl', [
        '--user', 'list-units', '--all', '--plain', '--no-legend', '--full', f'qa-{directory.name}-*']]]




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
    lab.watch()
    dead(pid)
    assert directory.exists() and lab.walk_state()[1]['stage'] == 'ended' and len(lab.sent()) == 2


def two_stops_take_turns(lab):
    directory = lab.root / P
    directory.mkdir()
    executable(directory / 'give-back', 'import time\nfrom pathlib import Path\n'
               "with Path('runs').open('a') as out:\n out.write('start\\n'); out.flush()\n"
               'time.sleep(1)\n'
               "with Path('runs').open('a') as out: out.write('end\\n')\n")
    processes = [subprocess.Popen([str(SCRIPT), '_give-back', str(directory), '5'], env=lab.env) for _ in range(2)]
    assert [proc.wait(timeout=10) for proc in processes] == [0, 0]
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
    started = time.monotonic()
    lab.run('_give-back', str(directory), '1')
    assert time.monotonic() - started < 5


def a_wrapper_past_its_bound_is_ended(lab):
    (lab.tmp / 'machine.env').write_text('QA_STOP_SECONDS=3\n')
    lab.env['QA_STOP_SECONDS'] = '2'
    directory, _ = deployment_pass(lab)
    unit, pid = deployment(lab, directory)
    executable(directory / 'give-back', 'import os, subprocess, time\nfrom pathlib import Path\n'
        + f'child = subprocess.Popen([{sys.executable!r}, "-I", "-B", "-c", "import time; time.sleep(60)"])\n'
          "Path('export-pids').write_text(f'{os.getpid()} {child.pid}')\n"
          'time.sleep(60)\n')
    started = time.monotonic()
    lab.run('_give-back', str(directory), '2')
    assert time.monotonic() - started < 10
    for process in map(int, (directory / 'export-pids').read_text().split()):
        dead(process)
    assert 'killed past 2 s' in (directory / 'give-back.log').read_text()
    # The bound also applies when the manager invokes the wrapper.
    saved = lab.root / 'units' / (unit + '.json')
    metadata = json.loads(saved.read_text())
    assert metadata['stop'][-1] == '2'
    assert '--property=TimeoutStopSec=62' in lab.calls('systemd-run')[0]
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
    lab.watch()
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
    lab.configure(stop_failures=[])
    lab.watch()
    state = lab.watch_state()[1]
    assert state['given'] == [CHATGPT, CLAUDE] and 'stopped' not in state
    dead(two)
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


def driven_watch(lab, patch, once=True, status=0):
    lab.prune_dead_launchers()
    driver = f'''import runpy, sys
tool = runpy.run_path({str(SCRIPT)!r})
{patch}
sys.exit(tool['main']())
'''
    result = subprocess.run([sys.executable, '-I', '-B', '-c', driver, 'watch', '--director',
                             'director@fixture', *(['--once'] if once else [])], env=lab.env, capture_output=True,
                            text=True, timeout=HUNG_TOOL_S)
    assert result.returncode == status, (result.stdout, result.stderr)
    return result


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
    lab.watch()
    dead(pid)
    assert directory.exists() and lab.walk_state()[1]['stage'] == 'ended'


def deploy_passes_a_literal_dollar(lab):
    directory = lab.root / P
    directory.mkdir()
    output = directory / 'arguments'
    program = executable(directory / 'capture', 'import json, sys\nfrom pathlib import Path\n'
                         "Path('arguments').write_text(json.dumps(sys.argv[1:]))\n")
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
    checkout = lab.tmp / 'qa/repos/fabrig-walk-forgejo-1'
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
    assert lab.calls('logins') == [['list'], ['list'], ['take', CHATGPT, '--any', '--now', '--as', state['holder'],
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
    lab.walk('b0', '--login', CLAUDE, '--login', CHATGPT, status=1)
    directory, state = lab.walk_state()
    assert state['stage'] == 'ended' and state['released'] and state['given'] == [CHATGPT]
    assert ['give', CHATGPT, '--as', state['holder']] in lab.calls('logins')
    assert not lab.calls('codex-run') and not (directory.parent / 'b0/loop.tsv').exists()
    config = json.loads((lab.root / 'tools.json').read_text())
    assert not config['logins_held'] and not config['login_queue']


def a_third_walk_is_refused_at_once(lab):
    lab.walk('b0')
    lab.walk('b0')
    before = lab.calls('logins')
    result = lab.walk('b0', '--login', CHATGPT, status=1)
    assert result.stderr == 'qa: kind forgejo holds 2 of its 2 logins of pool chatgpt\n'
    states = [state for _, state in lab.walk_states()]
    assert [state['slot'] for state in states] == [1, 2]
    assert lab.calls('logins') == before + [['list']] and len(lab.calls('codex-run')) == 2


def driven_walk(lab, patch, *args, status=0):
    brief = lab.tmp / 'qa-focused/rung-b0-brief.md'
    brief.parent.mkdir(parents=True, exist_ok=True)
    brief.write_text('fixture rung\n')
    driver = f'import os, runpy, sys\ntool = runpy.run_path({str(SCRIPT)!r})\n' + patch + '\nsys.exit(tool["main"]())\n'
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


def the_service_ends_a_walk_at_its_cap(lab):
    resting(lab, CHATGPT)
    lab.configure(logins_real=[CHATGPT])
    lab.walk('b0', '--login', CHATGPT, '--cap', '1', now='2026-10-27T10:00:00Z')
    directory, state = lab.walk_state()
    unit, pid = deployment(lab, directory, login=CHATGPT)
    before = lab.head()
    lab.watch(now='2026-10-27T10:01:01Z', extra={'QA_POST_STATUS': '2'})
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
        lab.watch()
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
    lab.watch()
    state = lab.walk_states()[0][1]
    assert state['given'] == [CHATGPT] and state['released'] and state['stage'] == 'ended'
    dead(pid)
    assert len(lab.sent()) == 2
    lab.walk('b0')
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
    assert lab.git(lab.tmp / 'qa/repos/fabrig-walk-forgejo-1', 'rev-parse', 'HEAD') == branch
    assert lab.git(lab.tmp / 'qa/repos/fabrig-walk-forgejo-2', 'rev-parse', 'HEAD') == main


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
    checkout = lab.tmp / 'qa/repos/fabrig-walk-forgejo-1'
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


def a_walk_fetch_is_bounded_before_taking_a_login(lab):
    lab.configure(hang={'cargo:fetch': 'before'})
    result = driven_walk(lab, '''original = tool['command']
def command(argv, cwd=None, timeout=None, **kwargs):
    if argv[0] == 'cargo':
        assert argv == ['cargo', 'fetch', '--locked'] and timeout == 300
        timeout = 0.3
    return original(argv, cwd=cwd, timeout=timeout, **kwargs)
tool['main'].__globals__['command'] = command
''', '--build', 'main', status=4)
    assert 'cannot fetch build main: command timed out' in result.stderr
    assert not any(args[0] == 'take' for args in lab.calls('logins'))
    assert not lab.calls('codex-run') and lab.walk_state()[1]['released']


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
    assert calls[fetches[-1]]['cwd'] == str(lab.tmp / 'qa/repos/fabrig-walk-forgejo-1')


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
    lab.watch()
    assert lab.walk_state()[1]['given'] == [CLAUDE] and lab.walk_state()[1]['stage'] == 'ended'
    dead(pid)


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


def pause_walk(lab, directory, state, line='step 4: blocked by a finding', post_status='0'):
    (directory / 'paused').write_text(line + '\n')
    (directory / 'notes.md').write_text('Finding: keep the deployment data and continue step 4.\n')
    lab.run('_give-back', str(directory), '5')
    lab.end_run(state, report='Blocking finding at step 4.\n')
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
    lab.watch()
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
    state = pause_walk(lab, directory, state)
    previous = state['attempts'][0]
    assert state['deployments'] == [dict(name='box', unit=unit, argv=[str(directory / 'box/server')])]
    dead(pid)
    lab.walk('other', '--login', CHATGPT)
    fix = lab.commit('fix before landing', branch='fix')
    report = (directory / 'report.md').read_bytes()
    lab.run('walk', 'fabrig', 'b0', '--resume', 'rung-b0-1', '--build', 'origin/fix', now='2026-10-27T09:00:00Z')
    resumed = next(saved for _, saved in lab.walk_states() if saved['walk'] == state['walk'])
    assert resumed['walk'] == state['walk'] and resumed['attempt'] == 2 and len(resumed['attempts']) == 2
    assert resumed['attempts'][0] == previous and resumed['run'] != state['run']
    assert resumed['pools'] == {CHATGPT: 'chatgpt-2'} and resumed['slot'] == 2
    assert resumed['main'] == fix and resumed['cap'] == 7 and resumed['started'] == '2026-10-27T09:00:00Z'
    assert lab.git(lab.tmp / 'qa/repos/fabrig-walk-forgejo-2', 'rev-parse', 'HEAD') == fix
    assert not (directory / 'paused').exists() and not (directory / 'give-back').exists()
    assert (directory / 'report-1.md').read_bytes() == report and kept.read_text() == 'kept deployment data\n'
    task = (directory / 'task.md').read_text()
    assert all(word in task for word in (state['pause_line'], str(directory / 'box/server'),
        str(directory / 'box'), resumed['logins']['chatgpt-2'], 'report-1.md', 'notes.md',
        'configuration', 'stored family', 'fresh deployment', 'main at the landed commit'))
    call = lab.calls('codex-run')[-1]
    assert call[:6] == ['task', '--resume', state['run'], '--to', 'qa-watch', '--on-stop']
    assert call[-3:] == [str(directory / 'task.md'), str(lab.tmp / 'qa/repos/fabrig-walk-forgejo-2'), str(directory / 'report.md')]
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
        str(lab.tmp / 'qa/repos/fabrig-walk-forgejo-1'), str(lab.tmp / 'qa/repos/fabrig-walk-claude-1')]
    assert (second[0] / 'brief.md').read_bytes() == (focused / 'rung-b0-claude-brief.md').read_bytes()
    rows = [row.split('\t') for row in (focused / 'b0/loop.tsv').read_text().splitlines()[1:]]
    assert [row[2] for row in rows] == ['1', 'claude-1']
    assert all('--now' in call and '--wait' not in call for call in lab.calls('logins') if call[0] == 'take')


def a_kind_at_its_cap_refuses_at_once(lab):
    lab.walk('b0')
    lab.walk('b0')
    before = [call for call in lab.calls('logins') if call[0] == 'take']
    result = lab.walk('another', status=1)
    assert 'kind forgejo holds 2 of its 2 logins of pool chatgpt' in result.stderr
    assert [call for call in lab.calls('logins') if call[0] == 'take'] == before
    directory, state = lab.walk_states()[0]
    lab.end_run(state)
    lab.configure(logins_out=[CHATGPT])
    lab.watch()
    current = lab.walk_states()[0][1]
    assert current['released'] and current['decision'] == 'walk-end' and not current['given']
    result = lab.walk('another', status=1)
    assert 'kind forgejo holds 2 of its 2 logins of pool chatgpt' in result.stderr
    assert [call for call in lab.calls('logins') if call[0] == 'take'] == before


def login_refuses_another_kinds_pool(lab):
    lab.walk('b0', '--kind', 'claude', '--login', CHATGPT, status=2)
    lab.walk('b0', '--kind', '', status=2)
    lab.walk('b0', '--kind', 'unknown', status=2)
    assert not lab.calls('logins') and not lab.calls('codex-run') and not lab.walk_states()


def a_resume_by_name_keeps_its_kind(lab):
    resting(lab, CLAUDE)
    lab.walk('b0', '--kind', 'claude')
    directory, state = lab.walk_state()
    state = pause_walk(lab, directory, state)
    lab.walk('b1', '--kind', 'claude')
    lab.walk('b2', '--kind', 'claude')
    before = [call for call in lab.calls('logins') if call[0] == 'take']
    result = lab.run('walk', 'fabrig', 'b0', '--resume', state['walk'], '--build', 'main', status=1)
    assert 'kind claude holds 2 of its 2 logins of pool claude' in result.stderr
    assert [call for call in lab.calls('logins') if call[0] == 'take'] == before
    lab.end_run(lab.walk_states()[1][1])
    lab.watch()
    lab.run('walk', 'fabrig', 'b0', '--resume', state['walk'], '--build', 'main')
    current = lab.walk_states()[0][1]
    assert current['kind'] == 'claude' and current['pools'] == {CLAUDE: CLAUDE}
    assert current['slot'] == 1 and current['holder'] == state['holder'] and current['attempt'] == 2
    assert lab.calls('codex-run')[-1][-2] == str(lab.tmp / 'qa/repos/fabrig-walk-claude-1')


def manual_kind_holders_stay_held_when_watcher_checks(lab):
    resting(lab, CHATGPT, in_place=True)
    lab.configure(logins_held=[CHATGPT], login_holders={CHATGPT: 'walk/forgejo/manual'})
    lab.watch()
    assert not [call for call in lab.calls('logins') if call[0] == 'give']
    lab.walk('b0')
    directory, state = lab.walk_state()
    assert state['pools'] == {CHATGPT: 'chatgpt-2'}
    result = lab.walk('b1', status=1)
    assert 'kind forgejo holds 2 of its 2 logins' in result.stderr
    lab.end_run(state)
    lab.watch()
    config = json.loads((lab.root / 'tools.json').read_text())
    assert config['logins_held'] == [CHATGPT] and config['login_holders'][CHATGPT] == 'walk/forgejo/manual'
    assert len(lab.sent()) == 1 and lab.sent()[0]['args'][1] == state['starter']


def a_refused_now_take_reports_the_broken_caps(lab):
    lab.configure(logins_busy=[CHATGPT])
    result = lab.walk('b0', status=1)
    assert 'the caps are broken: fixture login busy' in result.stderr
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


def a_surviving_launcher_keeps_custody_past_the_grace(lab):
    a_surviving_launcher_keeps_custody_until_its_unit_exists(lab, past_grace=True)


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


def an_orphan_manual_take_keeps_its_admission_lock(lab):
    orphaned_take_keeps_admission(lab, 'take')


def an_orphan_walk_take_keeps_its_admission_lock(lab):
    orphaned_take_keeps_admission(lab, 'walk')


def an_orphan_resume_take_keeps_its_admission_lock(lab):
    orphaned_take_keeps_admission(lab, 'resume')


def a_take_by_hand_is_refused_past_its_kinds_cap(lab):
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
    lab.env['QA_WALK_KINDS'] = 'forgejo=1:chatgpt'
    focused = lab.tmp / 'qa-focused'
    focused.mkdir()
    (focused / 'rung-b0-brief.md').write_text('Delayed launch fixture.\n')
    lab.configure(delay_before_unit=True, logins_real=[CHATGPT])
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
            lab.walk('b0', '--login', CHATGPT, status=1)
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


def queued_and_running_start_jobs_keep_custody(lab):
    directory, state = walk_with_logins(lab, CHATGPT)
    lab.env['QA_WALK_KINDS'] = 'forgejo=1:chatgpt'
    for job in ('42', '43', ''):
        lab.configure(unit_load='loaded', unit_state='inactive', unit_job=job)
        lab.watch()
        saved = lab.walk_state()[1]
        assert saved['stage'] == 'running' and not saved['given'] and not saved['released']
        assert not any(args[0] == 'give' for args in lab.calls('logins'))
        lab.walk('other', '--login', CHATGPT, status=1)
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
    assert lab.git(lab.tmp / 'qa/repos/fabrig-walk-forgejo-1', 'rev-parse', 'HEAD') == fix
    assert lab.git(lab.tmp / 'qa/repos/fabrig-walk-forgejo-2', 'rev-parse', 'HEAD') == main


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
    assert not lab.calls('codex-run') and not lab.calls('logins') and not lab.walk_states()
    lab.walk('b0', '--build', commit[:9].upper())
    state = next(state for _, state in lab.walk_states() if state['run'])
    assert state['main'] == commit


def a_bare_branch_resolves_to_origins(lab):
    main = lab.marked()
    fix = lab.commit('bare branch fix', branch='fix')
    # A branch moving after resolution must not change the saved build.
    driver = f'''original = tool['Repositories'].checkout
def checkout(self, root, repo, slot, main):
    tool['git'](root, 'update-ref', 'refs/remotes/origin/fix', {main!r})
    return original(self, root, repo, slot, main)
tool['Repositories'].checkout = checkout
'''
    lab.walk('b0', '--build', 'fix')
    driven_walk(lab, driver, '--build', 'origin/fix')
    first, second = lab.walk_states()
    assert first[1]['ref'] == 'fix' and second[1]['ref'] == 'origin/fix'
    assert first[1]['main'] == second[1]['main'] == fix
    for slot in (1, 2):
        assert lab.git(lab.tmp / f'qa/repos/fabrig-walk-forgejo-{slot}', 'rev-parse', 'HEAD') == fix
    assert lab.git(lab.tmp / 'qa/repos/fabrig', 'rev-parse', 'refs/remotes/origin/fix') == main


def an_unresolvable_build_takes_nothing(lab):
    for ref in ('nosuch', 'origin/missing', 'HEAD~1', '../main', 'bad..branch', 'abc', '1234'):
        result = lab.walk('b0', '--build', ref, '--login', CHATGPT, status=2)
        assert result.stderr == (f'qa: build {ref}: no branch origin/{ref} and no commit; '
                                 'try origin/<branch> or a commit\n')
    assert not lab.calls('logins') and not lab.calls('codex-run') and not lab.walk_states()
    assert not (lab.tmp / 'qa/walks').exists()
    assert not list((lab.tmp / 'qa/repos').glob('fabrig-walk-*'))
    assert not list((lab.tmp / 'qa-focused').glob('*/loop.tsv'))
    assert not list((lab.tmp / 'qa-focused').glob('rung-b0-1'))
    directory, state = walk_with_logins(lab, CHATGPT)
    pause_walk(lab, directory, state)
    saved = lab.tmp / 'qa/walks' / (state['walk'] + '.json')
    paths = [saved, directory / 'paused', directory / 'report.md', directory / 'notes.md',
             directory.parent / 'b0/loop.tsv']
    before = [path.read_bytes() for path in paths]
    calls = lab.calls('logins')
    slots = lab.git(lab.tmp / 'qa/repos/fabrig', 'worktree', 'list', '--porcelain')
    result = lab.run('walk', 'fabrig', 'b0', '--resume', state['walk'], '--build', 'nosuch', status=2)
    assert 'try origin/<branch> or a commit' in result.stderr
    assert lab.calls('logins') == calls and len(lab.calls('codex-run')) == 1
    assert [path.read_bytes() for path in paths] == before
    assert lab.git(lab.tmp / 'qa/repos/fabrig', 'worktree', 'list', '--porcelain') == slots
    assert len(lab.walk_states()) == 1 and not (directory / 'report-1.md').exists()


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
    assert lab.git(lab.tmp / 'qa/repos/fabrig', 'rev-parse', 'refs/remotes/origin/gone') == gone
    lab.git(checkout, 'push', 'origin', ':gone')
    result = lab.walk('b0', '--build', 'gone', '--login', CHATGPT, status=2)
    assert 'no branch origin/gone and no commit' in result.stderr
    assert not lab.calls('logins') and not lab.calls('codex-run') and not lab.walk_states()


def an_ambiguous_build_is_refused(lab):
    commit = lab.marked()
    fix = lab.commit('branch with a hexadecimal name', branch=commit[:9])
    result = lab.walk('b0', '--build', commit[:9], '--login', CHATGPT, status=2)
    assert 'ambiguous branch and commit' in result.stderr
    assert 'origin/' + commit[:9] in result.stderr and 'full commit ' + commit in result.stderr
    assert not lab.calls('logins') and not lab.calls('codex-run') and not lab.walk_states()
    assert not (lab.tmp / 'qa/walks').exists()
    assert not list((lab.tmp / 'qa/repos').glob('fabrig-walk-*'))
    assert not list((lab.tmp / 'qa-focused').glob('*/loop.tsv'))
    lab.walk('b0', '--build', 'origin/' + commit[:9])
    lab.walk('b0', '--build', commit)
    first, second = lab.walk_states()
    assert first[1]['main'] == fix and second[1]['main'] == commit




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
    expected = {'git': 300, 'systemctl': 30, 'logins': 60, 'post': 60, 'codex-run': 120}
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



def a_resume_recovers_its_thread_from_events(lab):
    directory, state = walk_with_logins(lab, CHATGPT)
    state = pause_walk(lab, directory, state)
    run = lab.tmp / 'codex-run' / state['run']
    (run / 'thread').unlink()
    (run / 'events.jsonl').write_text('{"type":"thread.started","thread_id":"fixture-thread"}\n')
    lab.run('walk', 'fabrig', 'b0', '--resume', state['walk'], '--build', 'main')
    assert len(lab.calls('codex-run')) == 2 and lab.walk_state()[1]['stage'] == 'running'



def walk_kind_settings_are_validated_and_follow_precedence(lab):
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
    for name in ('candidates', 'decide', 'default', 'backlog', 'passes', 'findings', 'rung', 'triage', 'keep'):
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


def a_hung_systemctl_bounds_the_check(lab):
    first, unit, pid, second, other_unit, other_pid = finished_pair(lab)
    bounded = """original = tool['command']
def command(argv, cwd=None, timeout=None, pass_fds=(), **kwargs):
    if str(argv[0]).endswith('/systemctl'):
        assert timeout == 30
        timeout = 0.3
    return original(argv, cwd=cwd, timeout=timeout, pass_fds=pass_fds, **kwargs)
tool['main'].__globals__['command'] = command
"""
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
    lab.configure(hung_systemctl={})
    lab.watch()
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
    state.update(logins={}, kinds={}, pools={}, given=[])
    write_walk(lab, state)
    unit, pid = deployment(lab, directory)
    lab.end_run(state)
    lab.watch()
    dead(pid)
    assert lab.walk_state()[1]['stage'] == 'ended'


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
    tool = runpy.run_path(str(SCRIPT))
    with patch.dict(os.environ, lab.env, clear=True):
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
                    read()
                except tool['Problem'] as error:
                    assert str(target) in str(error), (label, error)
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
    forged = dict(other, logins=original['logins'], kinds=original['kinds'], pools=original['pools'])
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
    forged = dict(original, logins={claimed: str(lab.root / 'resting' / claimed)},
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
    result = subprocess.run([sys.executable, '-I', '-B', '-c', driver], env=lab.env, capture_output=True, text=True)
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

CASES = (
    a_hard_linked_rung_brief_is_never_read_or_copied,
    hard_linked_metadata_is_never_read,
    unowned_metadata_is_never_read,
    symlinked_metadata_is_never_read,
    brief_copy_validates_and_reads_the_same_descriptor,
    a_loaded_inactive_unit_keeps_a_surviving_launcher,
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
    a_walk_with_no_login_stops_its_units,
    an_edited_deployments_trace_never_controls_custody,
    a_walk_never_stops_its_successors_unit,
    one_walk_failing_its_end_lets_the_check_go_on,
    a_hung_systemctl_bounds_the_check,
    unsupported_commands_are_refused_without_state,
    watch_runs_once_per_machine_and_loops_on_its_mailbox,
    deeply_nested_and_oversized_states_keep_custody_without_stopping_checks,
    walk_kind_settings_are_validated_and_follow_precedence,
    a_resume_recovers_its_thread_from_events,
    legacy_repository_walks_are_opaque_and_count_for_numbering,
    saved_alerts_retry_when_the_run_state_is_unknown,
    the_stuck_list_is_read_at_each_check,
    no_list_alerts_the_director_alone,
    an_alert_goes_once_per_stuck_login,
    a_refused_alert_is_sent_again,
    a_stuck_login_alerts_the_director_and_the_list,
    a_recipient_launch_error_does_not_block_the_other_alerts,
    stuck_recipients_are_bounded_in_file_order,
    an_oversized_stuck_list_does_not_block_cleanup,
    a_fifo_stuck_list_does_not_block_cleanup,
    a_bare_branch_resolves_to_origins,
    a_build_never_resolves_through_a_tag_or_a_stale_ref,
    a_damaged_walk_state_does_not_block_others_cleanup,
    a_deployment_that_exited_leaves_its_login_out,
    a_detached_pipe_cannot_hold_a_timed_out_command,
    a_failed_export_leaves_the_unit_up,
    a_failed_resume_launch_gives_back_and_stays_paused,
    a_failed_stop_is_tried_again,
    a_failed_walk_fetch_takes_no_login,
    a_kind_at_its_cap_refuses_at_once,
    a_linked_log_or_registry_writes_nowhere_else,
    a_linked_pause_marker_is_not_read,
    a_linked_walk_state_keeps_its_grant_held,
    a_manual_take_refuses_unknown_inventory_and_a_broken_cap,
    a_manual_take_selects_its_pool_and_give_passes_through,
    a_missing_walk_unit_is_ended_after_the_launch_grace,
    a_pause_with_a_login_out_ends_stuck,
    a_paused_walk_frees_its_slot_and_logins,
    a_paused_walk_resumes_at_a_branch_with_another_login,
    a_refused_login_starts_nothing,
    a_refused_now_take_reports_the_broken_caps,
    a_refused_walk_deployment_preserves_its_saved_command,
    a_restarted_service_goes_on,
    a_resume_before_the_pause_is_complete_is_refused,
    a_resume_by_name_keeps_its_kind,
    a_resume_refuses_pool_changes_but_accepts_its_cap,
    a_resume_whose_thread_is_gone_starts_fresh,
    a_resume_without_its_meta_starts_fresh,
    a_resumed_launch_without_a_unit_keeps_its_new_grant,
    a_resumed_walk_fetches_before_taking_a_login,
    a_saved_pause_decision_survives_its_marker_removal,
    a_second_pause_has_its_own_clock_event,
    a_stopped_pass_gives_its_login_back,
    a_stuck_walk_login_alerts_the_director_and_the_list,
    a_stuck_walk_login_stays_held,
    a_surviving_launcher_keeps_custody_past_the_grace,
    a_surviving_launcher_keeps_custody_until_its_unit_exists,
    a_take_by_hand_is_refused_past_its_kinds_cap,
    a_third_walk_is_refused_at_once,
    a_timed_out_walk_launch_keeps_custody_for_recovery,
    a_unit_created_during_launcher_scan_keeps_its_custody,
    a_unit_of_another_directory_is_not_stopped,
    a_walk_end_append_survives_an_interrupted_save,
    a_walk_fetch_is_bounded_before_taking_a_login,
    a_walk_fetches_its_build_before_taking_a_login,
    a_walk_grant_lost_in_a_crash_is_given_back,
    a_walk_in_place_login_waits_for_its_unknown_unit,
    a_walk_launch_lost_in_a_crash_is_recovered,
    a_walk_preparation_refusal_returns_its_grants,
    a_walk_reads_its_inventory_strictly,
    a_walk_refuses_invalid_inputs_before_taking_anything,
    a_walk_resolves_origin_branches_and_commit_prefixes,
    a_walk_resolves_remote_branches_despite_colliding_tags,
    a_walk_takes_a_login_and_a_slot_and_starts,
    a_wrapper_past_its_bound_is_ended,
    an_accepted_resume_recovers_only_its_new_run,
    an_ambiguous_build_is_refused,
    an_in_place_login_waits_for_every_unit,
    an_interrupted_resume_releases_only_its_new_grant,
    an_old_pending_end_does_not_turn_into_a_pause,
    an_orphan_manual_take_keeps_its_admission_lock,
    an_orphan_resume_take_keeps_its_admission_lock,
    an_orphan_walk_take_keeps_its_admission_lock,
    an_unresolvable_build_takes_nothing,
    damaged_attempt_history_keeps_walk_custody,
    deploy_passes_a_literal_dollar,
    deploy_records_then_starts_its_unit,
    deploy_runs_the_real_systemd_run,
    deployments_names_only_its_own_units,
    hex_walk_builds_refuse_ambiguous_and_non_commit_objects,
    hung_manual_inventory_and_takes_are_bounded,
    invalid_pause_lines_end_the_walk,
    login_refuses_another_kinds_pool,
    manual_and_generated_walk_holders_never_share_custody,
    manual_kind_holders_stay_held_when_watcher_checks,
    manual_login_commands_refuse_invalid_inputs_before_tools,
    numbering_survives_a_change_of_default_kind,
    pre_kind_walks_drain_before_kind_admission,
    resume_refuses_a_walk_not_paused,
    the_service_ends_a_walk_at_its_cap,
    two_stops_take_turns,
    walks_of_two_kinds_take_their_own_slots_and_pools,
)


def run_case(name, built):
    isolation = runpy.run_path(str(KIT / 'isolation.py'))
    isolation['run_one'](globals()[name], lambda case, root, baseline: case(Lab(root, baseline)), built, 'qa-walk-')


class WalkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.baseline = tempfile.TemporaryDirectory(prefix='qa-baseline-')
        baseline = Path(cls.baseline.name)
        Lab(baseline)
        cls.pool = ThreadPoolExecutor(max_workers=min(8, len(os.sched_getaffinity(0))))
        cls.futures = {case.__name__: cls.pool.submit(cls.child, case.__name__, baseline) for case in CASES}

    @staticmethod
    def child(name, baseline):
        process = subprocess.Popen([sys.executable, '-I', '-B', str(Path(__file__).resolve()),
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
        cls.pool.shutdown(wait=True)
        cls.baseline.cleanup()


def test_method(name):
    def test(self):
        code, output = self.futures[name].result()
        self.assertEqual(code, 0, output)
    return test


for case in CASES:
    setattr(WalkTests, 'test_' + case.__name__, test_method(case.__name__))


if __name__ == '__main__':
    if sys.argv[1:2] == ['--one']:
        run_case(sys.argv[2], Path(sys.argv[3]))
    else:
        unittest.main(verbosity=2)
