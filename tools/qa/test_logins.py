#!/usr/bin/env -S python3 -I -B
"""Offline custody gate: fresh HOME/state, scoped CLI calls and bounded IPC."""
from datetime import datetime, timedelta, timezone
import fcntl
import json
import os
import re
import runpy
from pathlib import Path
import stat
import subprocess
import sys
import textwrap
import time

import ctypes
import signal
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import qa_test_support as support

HUNG_TOOL_S = 300
HUNG_CASE_S = 900

SCRIPT = Path(__file__).resolve().with_name('logins')
CHATGPT = 'chatgpt'
QA = 'qa-watch'
RUNG = 'director/rung-a'


def write_bytes(path, data):
    descriptor, name = tempfile.mkstemp(prefix='.' + path.name + '-', dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(data)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def write_text(path, data):
    write_bytes(path, data.encode())


class Lab:
    def __init__(self, root):
        self.root = root
        self.home, self.tmp = root / 'home', root / 'tmp'
        self.home.mkdir()
        self.tmp.mkdir()
        self.env = dict(PATH=os.environ['PATH'], HOME=str(self.home), DEV_ROOT=str(root),
                        DEV_TMP=str(self.tmp), LOGINS_POLL_SECONDS='0.01', LC_ALL='C.UTF-8')
        self.argv = [sys.executable, '-I', '-B', str(SCRIPT)]
        self.serial = 0

    def run(self, *args):
        body = getattr(self, 'driver_body', None) if self.argv[-1] == str(self.root / 'driver.py') else None
        # Audit hooks cannot be removed; crash failpoints must really exit.
        if body is not None and ('addaudithook' in body or '._exit(' in body):
            result = subprocess.run([*self.argv, *args], env=self.env, text=True,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=HUNG_TOOL_S)
        else:
            result = support.execute(support.load(SCRIPT), body or 'import sys; sys.exit(module.main())',
                                     [str(SCRIPT), *args], self.env, self.root)
        return result.returncode, result.stdout, result.stderr

    def source(self, mode=0o600):
        self.serial += 1
        path = self.root / f'dummy-{self.serial}'
        write_text(path, 'dummy fixture login\n')
        path.chmod(mode)
        return path

    def source_directory(self, mode=0o700, entries=1):
        self.serial += 1
        path = self.root / f'dummy-directory-{self.serial}'
        path.mkdir()
        for entry in range(entries):
            write_bytes(path / f'entry-{entry}', b'dummy fixture configuration\n')
        path.chmod(mode)
        return path

    def directory_login(self):
        self.run('add', CHATGPT, str(self.source_directory()))
        return self.directory() / 'login'

    def login(self, name=CHATGPT):
        self.run('add', name, str(self.source()))
        return self.directory(name) / 'login'

    def directory(self, name=CHATGPT):
        return self.tmp / 'logins' / name

    def log(self, name=CHATGPT):
        return [line.split('\t') for line in (self.directory(name) / 'log.tsv').read_text().splitlines()]

    def read(self, filename, name=CHATGPT):
        directory = self.tmp / 'logins' if filename == 'waiting.json' else self.directory(name)
        return json.loads((directory / filename).read_text())

    def write(self, filename, value, name=CHATGPT):
        directory = self.tmp / 'logins' if filename == 'waiting.json' else self.directory(name)
        write_text(directory / filename, json.dumps(value) + '\n')

    def driver(self, body):
        self.driver_body = textwrap.dedent(body)
        driver = self.root / 'driver.py'
        write_text(driver, 'import importlib.machinery, importlib.util, sys\n'
                          f'loader = importlib.machinery.SourceFileLoader("logins", {str(SCRIPT)!r})\n'
                          'spec = importlib.util.spec_from_loader(loader.name, loader)\n'
                          'module = importlib.util.module_from_spec(spec)\n'
                          'loader.exec_module(module)\n' + textwrap.dedent(body))
        self.argv = [sys.executable, '-I', '-B', str(driver)]

    def clock(self, stamp):
        # Fix only the fixture process's clock; the tool has no test-only environment switch.
        self.driver(f'module.timestamp = lambda: {stamp!r}\nsys.exit(module.main())\n')

    def observe_login(self, path, replacement=None):
        trace = self.root / 'calls.json'
        self.driver(f'login = {str(path)!r}\nreplacement = {str(replacement) if replacement else None!r}\n'
                    f'trace = {str(trace)!r}\n' + textwrap.dedent("""
            import json, os
            calls, descriptors, entries = [], {}, []
            originals = {name: getattr(os, name) for name in ('stat', 'lstat', 'open', 'scandir')}
            checking, swapped = False, False

            def record(name, path, kwargs):
                directory = kwargs.get('dir_fd')
                target = descriptors.get(path, path) if isinstance(path, int) else os.fspath(path)
                if directory is not None and not isinstance(target, int):
                    target = os.path.join(descriptors[directory], target)
                calls.append([name, target])

            def wrap(name):
                def call(path, *args, **kwargs):
                    global swapped
                    record(name, path, kwargs)
                    result = originals[name](path, *args, **kwargs)
                    if name == 'open':
                        descriptors[result] = os.fspath(path)
                    if name == 'lstat' and checking and not swapped and replacement and os.fspath(path) == login:
                        os.rename(login, login + '-away')
                        os.symlink(replacement, login, target_is_directory=True)
                        swapped = True
                    return result
                return call

            class CountedEntries:
                def __init__(self, iterator):
                    self.iterator = iterator
                    self.index = len(entries)
                    entries.append(0)

                def __enter__(self):
                    self.iterator.__enter__()
                    return self

                def __exit__(self, *args):
                    return self.iterator.__exit__(*args)

                def __iter__(self):
                    return self

                def __next__(self):
                    entry = next(self.iterator)
                    entries[self.index] += 1
                    return entry

            def scandir(path):
                record('scandir', path, {})
                iterator = originals['scandir'](path)
                target = descriptors.get(path, path) if isinstance(path, int) else os.fspath(path)
                return CountedEntries(iterator) if target == login else iterator

            original_check = module.login_check

            def check(path):
                global checking
                checking = True
                try:
                    return original_check(path)
                finally:
                    checking = False

            for name in ('stat', 'lstat', 'open'):
                setattr(os, name, wrap(name))
            os.scandir = scandir
            module.login_check = check
            try:
                status = module.main()
            finally:
                for name, function in originals.items():
                    setattr(os, name, function)
                module.replace(module.Path(trace),
                               json.dumps(dict(calls=calls, entries=entries, swapped=swapped)).encode())
            sys.exit(status)
        """))
        return trace


def adds_a_login_by_moving_it(lab):
    source = lab.source()
    code, out, err = lab.run('add', CHATGPT, str(source))
    path = lab.directory() / 'login'
    assert code == 0 and out == f'added: {CHATGPT} at {path}\n' and not err
    assert not source.exists() and path.exists() and stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(lab.directory().stat().st_mode) == 0o700
    assert all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in lab.directory().iterdir())
    assert [row[1] for row in lab.log()] == ['add']


def adds_a_directory_login_by_moving_it(lab):
    source = lab.source_directory()
    entries = {p.name: (p.stat().st_ino, p.stat().st_size) for p in source.iterdir()}
    code, out, err = lab.run('add', CHATGPT, str(source))
    path = lab.directory() / 'login'
    assert (code, out, err) == (0, f'added: {CHATGPT} at {path}\n', '')
    assert not source.exists() and path.is_dir()
    assert stat.S_IMODE(path.stat().st_mode) == 0o700
    assert {p.name: (p.stat().st_ino, p.stat().st_size) for p in path.iterdir()} == entries
    assert [row[1] for row in lab.log()] == ['add']


def add_refuses_an_empty_directory(lab):
    source = lab.source_directory(entries=0)
    code, _, err = lab.run('add', CHATGPT, str(source))
    assert code == 1 and 'empty' in err and source.is_dir()


def add_refuses_a_directory_that_is_not_private(lab):
    source = lab.source_directory(mode=0o755)
    code, _, err = lab.run('add', CHATGPT, str(source))
    assert code == 1 and 'not private' in err and source.is_dir()


def add_refuses_a_link_to_a_directory(lab):
    target = lab.source_directory()
    source = lab.root / 'linked-directory'
    source.symlink_to(target, target_is_directory=True)
    code, _, err = lab.run('add', CHATGPT, str(source))
    assert code == 1 and 'a link' in err and source.is_symlink() and target.is_dir()


def takes_and_gives_a_directory_login(lab):
    path = lab.directory_login()
    assert lab.run('take', CHATGPT, '--as', QA) == (0, f'{path}\n', '')
    assert lab.read('holder.json')['holder'] == QA
    assert lab.run('take', CHATGPT, '--as', QA) == (0, f'{path}\n', '')
    code, out, err = lab.run('list', CHATGPT)
    assert code == 0 and 'held by qa-watch' in out and ', at rest\n' in out and not err
    assert lab.run('give', CHATGPT, '--as', QA)[0] == 0
    assert not (lab.directory() / 'holder.json').exists()
    assert [row[1] for row in lab.log()] == ['add', 'take', 'give']


def a_directory_login_not_back_stays_held(lab):
    path = lab.directory_login()
    lab.run('take', CHATGPT, '--as', QA)
    away = path.rename(lab.root / 'imported')
    code, _, err = lab.run('give', CHATGPT, '--as', QA)
    assert code == 1 and 'not back' in err and 'missing' in err
    assert lab.read('holder.json')['holder'] == QA
    code, out, err = lab.run('list', CHATGPT)
    assert code == 0 and 'held by qa-watch' in out and 'not at rest' in out and not err
    away.rename(path)
    assert lab.run('give', CHATGPT, '--as', QA)[0] == 0
    assert not (lab.directory() / 'holder.json').exists()
    assert [row[1] for row in lab.log()] == ['add', 'take', 'give']


def give_reads_nothing_inside_a_directory(lab):
    source = lab.source_directory(entries=3)  # Multiple entries expose an exhaustive scan.
    lab.run('add', CHATGPT, str(source))
    path = lab.directory() / 'login'
    lab.run('take', CHATGPT, '--as', QA)
    trace = lab.observe_login(path)
    assert lab.run('give', CHATGPT, '--as', QA)[0] == 0
    evidence = json.loads(trace.read_text())
    assert evidence['entries'] == [1]
    assert any(operation == 'scandir' and target == str(path)
               for operation, target in evidence['calls'])
    assert not any(isinstance(target, str) and target.startswith(str(path) + '/')
                   for _, target in evidence['calls'])
    assert not (lab.directory() / 'holder.json').exists()
    assert [row[1] for row in lab.log()] == ['add', 'take', 'give']


def give_refuses_a_directory_replaced_by_a_link(lab):
    path = lab.directory_login()
    lab.run('take', CHATGPT, '--as', QA)
    replacement = lab.source_directory()
    trace = lab.observe_login(path, replacement)
    code, _, err = lab.run('give', CHATGPT, '--as', QA)
    evidence = json.loads(trace.read_text())
    assert evidence['swapped'] and path.is_symlink()
    assert code == 1 and 'not back' in err and 'a link' in err
    assert lab.read('holder.json')['holder'] == QA
    assert evidence['entries'] == []
    assert [row[1] for row in lab.log()] == ['add', 'take']


def an_empty_directory_login_stays_held(lab):
    path = lab.directory_login()
    lab.run('take', CHATGPT, '--as', QA)
    (path / 'entry-0').unlink()
    code, _, err = lab.run('give', CHATGPT, '--as', QA)
    assert code == 1 and 'empty' in err
    assert lab.read('holder.json')['holder'] == QA
    assert lab.run('take', CHATGPT, '--as', QA)[0] == 1
    code, out, err = lab.run('list', CHATGPT)
    assert code == 0 and 'held by qa-watch' in out and 'not at rest' in out and not err
    assert [row[1] for row in lab.log()] == ['add', 'take']


def add_refuses_a_login_that_is_not_private(lab):
    source = lab.source(0o644)
    code, _, err = lab.run('add', CHATGPT, str(source))
    assert code == 1 and 'not private' in err and source.exists()


def add_refuses_a_second_login_at_rest(lab):
    lab.login()
    source = lab.source()
    code, _, _ = lab.run('add', CHATGPT, str(source))
    assert code == 1 and source.exists() and len(lab.log()) == 1


def replaces_a_login_without_opening_the_old_one(lab):
    path = lab.login()
    old_inode = path.stat().st_ino
    source = lab.source()
    new_inode = source.stat().st_ino
    trace = lab.root / 'renames.json'
    lab.driver(f'''
import json, os
login = {str(path)!r}
renames = []
original = os.rename
def audit(event, args):
    if event == 'open' and args[0] == login:
        raise AssertionError('opened the old login')
sys.addaudithook(audit)
def rename(source, target):
    renames.append([str(source), str(target)])
    return original(source, target)
os.rename = rename
status = module.main()
module.replace(module.Path({str(trace)!r}), json.dumps(renames).encode())
sys.exit(status)
''')
    assert lab.run('replace', CHATGPT, str(source)) == (0, f'replaced: {CHATGPT} at {path}\n', '')
    assert not source.exists() and path.stat().st_ino == new_inode != old_inode
    assert json.loads(trace.read_text()) == [[str(source), str(path)]]
    assert [row[1:] for row in lab.log()] == [['add', '', '0', ''], ['replace', '', '0', '']]
    lab.argv = [sys.executable, '-I', '-B', str(SCRIPT)]
    code, out, err = lab.run('list', CHATGPT)
    assert code == 0 and 'at rest' in out and '0 takes' in out and not err
    assert lab.run('take', CHATGPT, '--as', QA) == (0, f'{path}\n', '')


def replace_refuses_a_held_login_even_at_rest(lab):
    path = lab.login()
    lab.run('take', CHATGPT, '--as', QA)
    inode = path.stat().st_ino
    source = lab.source()
    code, out, err = lab.run('replace', CHATGPT, str(source))
    assert code == 1 and not out and f'held by {QA}' in err
    assert source.exists() and path.stat().st_ino == inode
    assert lab.read('holder.json')['holder'] == QA
    assert [row[1] for row in lab.log()] == ['add', 'take']


def replace_refuses_a_by_name_waiter(lab):
    waiter_with_age(lab, 0)
    source = lab.source()
    code, out, err = lab.run('replace', CHATGPT, str(source))
    assert code == 1 and not out and f'claimed by waiter {RUNG}' in err
    assert source.exists() and [row[1] for row in lab.log()] == ['add']
    assert lab.read('waiting.json')[0]['holder'] == RUNG


def replace_respects_only_the_pool_members_actually_reserved(lab):
    waiter_with_age(lab, 0)
    lab.login('chatgpt-2')
    lab.login('chatgpt-3')
    # The named waiter reserves chatgpt; the later pool waiter reserves chatgpt-2.
    rows = lab.read('waiting.json')
    rows.append(dict(rows[0], holder='z', pool=True))
    lab.write('waiting.json', rows)
    source = lab.source()
    code, out, err = lab.run('replace', 'chatgpt-2', str(source))
    assert code == 1 and not out and 'claimed by waiter z' in err
    assert source.exists() and [row[1] for row in lab.log('chatgpt-2')] == ['add']
    path = lab.directory('chatgpt-3') / 'login'
    assert lab.run('replace', 'chatgpt-3', str(source)) == (0, f'replaced: chatgpt-3 at {path}\n', '')
    assert lab.read('waiting.json') == rows


def replace_ignores_a_stale_waiter(lab):
    waiter_with_age(lab, 901)
    assert lab.run('replace', CHATGPT, str(lab.source()))[0] == 0
    assert lab.read('waiting.json') == []


def replace_refuses_a_missing_login(lab):
    source = lab.source()
    code, out, err = lab.run('replace', CHATGPT, str(source))
    assert code == 1 and not out and 'no login at rest' in err and source.exists()
    path = lab.login()
    path.rename(lab.root / 'away')
    code, out, err = lab.run('replace', CHATGPT, str(source))
    assert code == 1 and not out and 'no login at rest' in err and source.exists()
    assert [row[1] for row in lab.log()] == ['add']


def replace_refuses_bad_sources_and_the_resting_login_itself(lab):
    path = lab.login()
    inode = path.stat().st_ino
    missing = lab.root / 'missing'
    empty = lab.source()
    write_bytes(empty, b'')
    link = lab.root / 'link'
    link.symlink_to(path)
    fifo = lab.root / 'fifo'
    os.mkfifo(fifo)
    alias = lab.root / 'alias'
    os.link(path, alias)
    for source, reason in ((missing, 'missing'), (empty, 'empty'),
                           (lab.source(0o644), 'not private'), (link, 'a link'),
                           (fifo, 'not a regular file or directory'),
                           (path, 'already the resting login'), (alias, 'already the resting login')):
        code, out, err = lab.run('replace', CHATGPT, str(source))
        assert code == 1 and not out and reason in err, (source, code, err)
        assert path.stat().st_ino == inode and [row[1] for row in lab.log()] == ['add']


def replace_refuses_cross_filesystem_moves(lab):
    path = lab.login()
    inode = path.stat().st_ino
    source = lab.source()
    lab.driver('''
def rename(source, target):
    raise OSError(module.errno.EXDEV, 'fixture cross-device rename')
module.os.rename = rename
sys.exit(module.main())
''')
    code, out, err = lab.run('replace', CHATGPT, str(source))
    assert code == 1 and not out and 'same filesystem' in err
    assert source.exists() and path.stat().st_ino == inode
    assert [row[1] for row in lab.log()] == ['add']


def replace_refuses_directories_without_opening_the_old_one(lab):
    path = lab.directory_login()
    inode = path.stat().st_ino
    source = lab.source_directory()
    trace = lab.observe_login(path)
    code, out, err = lab.run('replace', CHATGPT, str(source))
    assert code == 1 and not out and 'directory login' in err and 'atomic rename' in err
    evidence = json.loads(trace.read_text())
    assert not any(operation in ('open', 'scandir') and target == str(path)
                   for operation, target in evidence['calls'])
    assert source.is_dir() and path.stat().st_ino == inode
    assert [row[1] for row in lab.log()] == ['add']
    lab.argv = [sys.executable, '-I', '-B', str(SCRIPT)]
    path.rename(lab.root / 'old-directory')
    lab.login()
    code, out, err = lab.run('replace', CHATGPT, str(source))
    assert code == 1 and not out and 'directory login' in err and source.is_dir()


def takes_a_login_at_rest(lab):
    path = lab.login()
    code, out, err = lab.run('take', CHATGPT, '--as', QA)
    assert (code, out, err) == (0, f'{path}\n', '')
    assert lab.read('holder.json')['holder'] == QA
    assert [row[1] for row in lab.log()] == ['add', 'take']


def a_second_taker_waits(lab):
    lab.login()
    lab.run('take', CHATGPT, '--as', QA)
    code, _, err = lab.run('take', CHATGPT, '--as', RUNG)
    assert code == 1 and 'held by qa-watch' in err
    assert [row['holder'] for row in lab.read('waiting.json')] == [RUNG]


def the_first_waiter_is_served_first(lab):
    lab.login()
    lab.run('take', CHATGPT, '--as', QA)
    lab.clock('2026-10-26T18:30:00Z')
    lab.run('take', CHATGPT, '--as', RUNG)
    lab.clock('2026-10-26T18:30:01Z')
    lab.run('take', CHATGPT, '--as', 'another')
    lab.run('give', CHATGPT, '--as', QA)
    code, _, err = lab.run('take', CHATGPT, '--as', 'another')
    assert code == 1 and 'waits for director/rung-a first' in err
    assert lab.run('take', CHATGPT, '--as', RUNG)[0] == 0


def waiter_with_age(lab, age):
    lab.clock('2026-10-26T18:30:00Z')
    lab.login()
    now = datetime(2026, 10, 26, 18, 30, tzinfo=timezone.utc)
    seen = (now - timedelta(seconds=age)).strftime('%Y-%m-%dT%H:%M:%SZ')
    lab.write('waiting.json', [dict(holder=RUNG, request=CHATGPT, pool=False, note='', since=seen, seen=seen)])


def a_stale_waiter_loses_its_turn(lab):
    waiter_with_age(lab, 901)
    assert lab.run('take', CHATGPT, '--as', 'another')[0] == 0
    assert lab.read('holder.json')['holder'] == 'another'


def a_waiter_seen_at_the_bound_keeps_its_turn(lab):
    waiter_with_age(lab, 900)
    code, _, err = lab.run('take', CHATGPT, '--as', 'another')
    assert code == 1 and 'waits for director/rung-a first' in err
    assert lab.read('waiting.json')[0]['holder'] == RUNG


def retaking_by_the_holder_is_idempotent(lab):
    path = lab.login()
    lab.run('take', CHATGPT, '--as', QA)
    before = {p.name: p.stat().st_mtime_ns for p in lab.directory().iterdir()}
    code, out, err = lab.run('take', CHATGPT, '--as', QA)
    assert (code, out, err) == (0, f'{path}\n', '')
    assert [row[1] for row in lab.log()].count('take') == 1
    assert before == {p.name: p.stat().st_mtime_ns for p in lab.directory().iterdir()}


def retaking_a_login_not_at_rest_is_refused(lab):
    path = lab.login()
    lab.run('take', CHATGPT, '--as', QA)
    path.rename(lab.root / 'imported')
    waiting = (lab.tmp / 'logins' / 'waiting.json').read_bytes()
    before = {p.name: p.stat().st_mtime_ns for p in lab.directory().iterdir()}
    code, out, err = lab.run('take', CHATGPT, '--as', QA)
    assert (code, out, err) == (1, '', f'logins: {CHATGPT} is held by {QA} and not at rest\n')
    assert (lab.tmp / 'logins' / 'waiting.json').read_bytes() == waiting
    assert before == {p.name: p.stat().st_mtime_ns for p in lab.directory().iterdir()}


def give_refuses_a_login_not_back(lab):
    path = lab.login()
    lab.run('take', CHATGPT, '--as', QA)
    path.rename(lab.root / 'imported')
    code, _, err = lab.run('give', CHATGPT, '--as', QA)
    assert code == 1 and 'not back' in err and 'missing' in err
    assert lab.read('holder.json')['holder'] == QA


def gives_a_login_back(lab):
    lab.clock('2026-10-26T18:30:00Z')
    lab.login()
    lab.run('take', CHATGPT, '--as', QA)
    holder = lab.read('holder.json')
    holder['since'] = '2026-10-26T17:05:00Z'
    lab.write('holder.json', holder)
    code, out, err = lab.run('give', CHATGPT, '--as', QA)
    assert (code, out, err) == (0, f'given: {CHATGPT} by {QA} after 1:25\n', '')
    assert not (lab.directory() / 'holder.json').exists()
    assert lab.log()[-1][1:4] == ['give', QA, '5100']


def giving_a_free_login_is_idempotent(lab):
    path = lab.login()
    lab.run('take', CHATGPT, '--as', QA)
    assert lab.run('give', CHATGPT, '--as', QA)[0] == 0
    before = {p.name: (p.stat().st_mtime_ns, p.stat().st_size) for p in lab.directory().iterdir()}
    assert lab.run('give', CHATGPT, '--as', QA) == (0, f'already free: {CHATGPT}\n', '')
    assert before == {p.name: (p.stat().st_mtime_ns, p.stat().st_size) for p in lab.directory().iterdir()}
    path.chmod(0o644)
    assert lab.run('give', CHATGPT, '--as', QA)[0] == 1
    path.unlink()
    assert lab.run('give', CHATGPT, '--as', QA)[0] == 1
    assert [row[1] for row in lab.log()] == ['add', 'take', 'give']


def give_by_another_holder_is_refused(lab):
    lab.login()
    lab.run('take', CHATGPT, '--as', QA)
    code, _, err = lab.run('give', CHATGPT, '--as', RUNG)
    assert code == 2 and err == f'logins: {CHATGPT} is held by {QA}\n'
    assert lab.read('holder.json')['holder'] == QA


def take_waits_until_the_login_is_given(lab):
    path = lab.login()
    lab.run('take', CHATGPT, '--as', QA)
    proc = subprocess.Popen([*lab.argv, 'take', CHATGPT, '--as', RUNG, '--run', 'run-after-wait',
                             '--wait', str(HUNG_TOOL_S)],
                            env=lab.env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + HUNG_TOOL_S
        while not lab.read('waiting.json') and time.monotonic() < deadline:
            time.sleep(0.01)
        lab.run('give', CHATGPT, '--as', QA)
        out, err = proc.communicate(timeout=HUNG_TOOL_S)
        assert (proc.returncode, out, err) == (0, f'{path}\n', '')
        assert lab.read('holder.json')['holder'] == RUNG
        assert lab.read('holder.json')['run'] == 'run-after-wait'
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.communicate()


def take_without_a_login_at_rest_says_so(lab):
    lab.login().rename(lab.root / 'imported')
    code, _, err = lab.run('take', CHATGPT, '--as', QA)
    assert code == 1 and err == f'logins: {CHATGPT} is not at rest and held by nobody\n'


def lists_holder_waiters_and_the_last_day(lab):
    lab.clock('2026-10-26T19:12:00Z')
    lab.login().rename(lab.root / 'imported')
    lab.write('holder.json', dict(holder=QA, note='20261026-1830-temper', since='2026-10-26T18:30:00Z',
                                  run='run-plain-unchanged'))
    lab.write('waiting.json', [dict(holder=RUNG, request=CHATGPT, pool=False, note='', since='2026-10-26T18:45:00Z',
                                    seen='2026-10-26T18:45:00Z')])
    write_text(lab.directory() / 'log.tsv',
        '2026-10-25T19:11:00Z\tgive\tqa-watch\t86400\t\n'
        '2026-10-26T10:00:00Z\tgive\tqa-watch\t3600\t\n'
        '2026-10-26T11:00:00Z\tgive\tqa-watch\t1800\t\n'
        '2026-10-26T09:00:00Z\ttake\tqa-watch\t0\t\n'
        '2026-10-26T10:30:00Z\ttake\tqa-watch\t300\t\n'
        '2026-10-26T18:30:00Z\ttake\tqa-watch\t60\t\n')
    before = {p.name: (p.stat().st_mtime_ns, p.stat().st_size) for p in lab.directory().iterdir()}
    code, out, err = lab.run('list', CHATGPT)
    assert (code, out, err) == (0,
        'chatgpt: held by qa-watch (20261026-1830-temper) since 2026-10-26T18:30:00Z, 0:42, not at rest\n'
        '  waiting: director/rung-a since 2026-10-26T18:45:00Z\n'
        '  last 24 hours: held 2:12, 3 takes, longest wait 0:05\n', '')
    assert before == {p.name: (p.stat().st_mtime_ns, p.stat().st_size) for p in lab.directory().iterdir()}


def refuses_an_unknown_login(lab):
    code, _, err = lab.run('take', CHATGPT, '--as', QA)
    assert code == 2 and 'unknown login' in err
    assert not lab.directory().exists()


def refuses_a_symlinked_state_path(lab):
    target = lab.root / 'elsewhere'
    target.mkdir()
    (lab.tmp / 'logins').mkdir()
    lab.directory().symlink_to(target, target_is_directory=True)
    code, _, err = lab.run('take', CHATGPT, '--as', QA)
    assert code == 4 and 'symlink refused' in err
    assert not tuple(target.iterdir())


def a_pool_take_grants_a_free_login_and_names_it(lab):
    names = (CHATGPT, 'chatgpt-2', 'chatgpt-3')
    paths = {name: lab.login(name) for name in (*names, 'chatgpt-tools')}
    assert lab.run('take', CHATGPT, '--as', 'a')[0] == 0
    for name in names[1:]:
        assert lab.run('take', CHATGPT, '--any', '--as', 'b') == (0, f'{name} {paths[name]}\n', '')
        assert lab.read('holder.json', name)['holder'] == 'b'
    code, out, err = lab.run('take', CHATGPT, '--any', '--as', 'c')
    assert code == 1 and not out and 'waiting' in err
    assert lab.read('waiting.json')[0]['request'] == CHATGPT
    for pool, reason in (('chatgpt-2', 'not a pool'), ('nopool', 'unknown pool')):
        code, out, err = lab.run('take', pool, '--any', '--as', 'c')
        assert (code, out) == (2, '') and f'{reason}: {pool}' in err
    assert not (lab.directory('chatgpt-tools') / 'holder.json').exists()


def a_now_take_never_joins_the_queue(lab):
    path = lab.login()
    lab.run('take', CHATGPT, '--as', 'a')
    queue = lab.tmp / 'logins/waiting.json'
    queue.unlink()
    assert lab.run('take', CHATGPT, '--any', '--now', '--as', 'qa-watch/p')[0] == 1
    assert not queue.exists()
    lab.clock('2026-10-27T10:00:00Z')
    assert lab.run('take', CHATGPT, '--any', '--as', 'b')[0] == 1
    before = queue.read_bytes()
    for holder in ('qa-watch/p', 'b'):
        assert lab.run('take', CHATGPT, '--any', '--now', '--as', holder)[0] == 1
        assert queue.read_bytes() == before
    lab.run('give', CHATGPT, '--as', 'a')
    before = queue.read_bytes()
    for args in ((CHATGPT, '--any'), (CHATGPT,)):
        assert lab.run('take', *args, '--now', '--as', 'c')[0] == 1
        assert queue.read_bytes() == before
    assert lab.run('take', CHATGPT, '--any', '--as', 'b') == (0, f'{CHATGPT} {path}\n', '')
    # --now by name requires a free login, even for its current holder.
    assert lab.run('take', CHATGPT, '--now', '--as', 'b')[0] == 1
    assert lab.run('take', CHATGPT, '--now', '--wait', '1', '--as', 'c')[0] == 2


def a_now_take_takes_a_free_unclaimed_login(lab):
    names = (CHATGPT, 'chatgpt-2', 'chatgpt-3', 'chatgpt-4')
    for name in names:
        lab.login(name)
        assert lab.run('take', name, '--as', 'a')[0] == 0
    assert lab.run('take', CHATGPT, '--any', '--as', 'b')[0] == 1
    for name in names[2:]:
        lab.run('give', name, '--as', 'a')
    queue = lab.tmp / 'logins/waiting.json'
    before = queue.read_bytes()
    assert lab.run('take', CHATGPT, '--any', '--now', '--as', 'qa-watch/p') == (
        0, f'chatgpt-4 {lab.directory("chatgpt-4") / "login"}\n', '')
    assert queue.read_bytes() == before
    assert lab.read('holder.json', 'chatgpt-4')['holder'] == 'qa-watch/p'
    assert lab.log('chatgpt-4')[-1][1:4] == ['take', 'qa-watch/p', '0']
    assert lab.run('take', CHATGPT, '--any', '--as', 'b')[0] == 0
    lab.run('give', 'chatgpt-4', '--as', 'qa-watch/p')
    before = queue.read_bytes()
    assert lab.run('take', 'chatgpt-4', '--now', '--as', 'c')[0] == 0
    assert queue.read_bytes() == before


def a_now_take_preserves_stale_and_legacy_queue_files(lab):
    path = lab.login()
    lab.clock('2026-10-27T10:00:00Z')
    assert lab.run('take', CHATGPT, '--as', 'a')[0] == 0
    assert lab.run('take', CHATGPT, '--as', 'b')[0] == 1
    queue = lab.tmp / 'logins/waiting.json'
    legacy = lab.directory() / 'waiting.json'
    row = lab.read('waiting.json')[0]
    # Leave both stale rows on disk while returning the login under the earlier clock.
    assert lab.run('give', CHATGPT, '--as', 'a')[0] == 0
    write_text(legacy, json.dumps([{key: row[key] for key in ('holder', 'note', 'since', 'seen')}]))
    before = queue.read_bytes(), legacy.read_bytes()
    lab.clock('2026-10-27T10:15:01Z')
    assert lab.run('take', CHATGPT, '--now', '--as', 'c') == (0, f'{path}\n', '')
    assert (queue.read_bytes(), legacy.read_bytes()) == before


def one_queue_in_arrival_order(lab):
    path = lab.login()
    lab.run('take', CHATGPT, '--as', 'a')
    lab.clock('2026-10-27T10:00:00Z')
    assert lab.run('take', CHATGPT, '--as', 'b')[0] == 1
    lab.clock('2026-10-27T10:00:01Z')
    assert lab.run('take', CHATGPT, '--any', '--as', 'c')[0] == 1
    assert [(r['holder'], r['pool']) for r in lab.read('waiting.json')] == [('b', False), ('c', True)]
    lab.run('give', CHATGPT, '--as', 'a')
    assert lab.run('take', CHATGPT, '--any', '--as', 'c')[0] == 1
    assert lab.run('take', CHATGPT, '--as', 'b') == (0, f'{path}\n', '')
    lab.run('give', CHATGPT, '--as', 'b')
    assert lab.run('take', CHATGPT, '--any', '--as', 'c') == (0, f'{CHATGPT} {path}\n', '')
    assert lab.read('waiting.json') == []


def a_waiter_for_a_stuck_login_holds_back_no_free_one(lab):
    stuck, free = lab.login(), lab.login('chatgpt-2')
    lab.run('take', CHATGPT, '--as', 'a')
    stuck.rename(lab.root / 'away')
    lab.clock('2026-10-27T10:00:00Z')
    assert lab.run('take', CHATGPT, '--as', 'b')[0] == 1
    lab.clock('2026-10-27T10:00:01Z')
    assert lab.run('take', CHATGPT, '--any', '--as', 'c') == (0, f'chatgpt-2 {free}\n', '')
    assert lab.read('holder.json')['holder'] == 'a'
    assert lab.read('waiting.json')[0]['holder'] == 'b'


def a_pool_waiter_keeps_one_free_login_not_all(lab):
    for name in (CHATGPT, 'chatgpt-2', 'chatgpt-3'):
        lab.login(name)
        assert lab.run('take', name, '--as', 'a')[0] == 0
    lab.clock('2026-10-27T10:00:00Z')
    assert lab.run('take', CHATGPT, '--any', '--as', 'b')[0] == 1
    lab.clock('2026-10-27T10:00:01Z')
    assert lab.run('take', CHATGPT, '--any', '--as', 'c')[0] == 1
    for name in (CHATGPT, 'chatgpt-2'):
        assert lab.run('give', name, '--as', 'a')[0] == 0
    assert lab.run('take', CHATGPT, '--any', '--as', 'c') == (
        0, f'chatgpt-2 {lab.directory("chatgpt-2") / "login"}\n', '')
    assert lab.run('take', CHATGPT, '--any', '--as', 'b') == (
        0, f'{CHATGPT} {lab.directory() / "login"}\n', '')


def a_stale_waiter_leaves_the_queue(lab):
    waiter_with_age(lab, 901)
    assert lab.run('take', CHATGPT, '--any', '--as', 'another')[0] == 0
    assert lab.read('waiting.json') == []
    lab.run('give', CHATGPT, '--as', 'another')
    waiter_with_age(lab, 900)
    assert lab.run('take', CHATGPT, '--any', '--as', 'another')[0] == 1
    assert lab.read('waiting.json')[0]['holder'] == RUNG


def two_takes_at_once_get_two_logins(lab):
    names = (CHATGPT, 'chatgpt-2', 'chatgpt-3', 'chatgpt-4')
    for name in names:
        lab.login(name)
    procs = []
    try:
        for holder in ('a', 'b', 'c', 'd'):
            proc = subprocess.Popen([*lab.argv, 'take', CHATGPT, '--any', '--as', holder, '--wait', '5'],
                                    env=lab.env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            procs.append((holder, proc))
        granted = set()
        for holder, proc in procs:
            out, err = proc.communicate(timeout=HUNG_TOOL_S)
            assert proc.returncode == 0 and not err, (out, err)
            name, path = out.strip().split(' ')
            assert path == str(lab.directory(name) / 'login')
            assert lab.read('holder.json', name)['holder'] == holder
            granted.add(name)
        assert granted == set(names) and lab.read('waiting.json') == []
    finally:
        for _, proc in procs:
            if proc.poll() is None:
                proc.kill()
            proc.communicate()


def old_per_login_queues_are_migrated(lab):
    lab.clock('2026-10-27T10:00:00Z')
    lab.login()
    lab.login('other')
    old = lab.directory() / 'waiting.json'
    fresh = dict(holder='b', note='old request', since='2026-10-27T09:58:00Z', seen='2026-10-27T09:59:00Z')
    stale = dict(holder='stale', note='', since='2026-10-27T09:40:00Z', seen='2026-10-27T09:44:59Z')
    write_text(old, json.dumps([fresh, stale]))
    assert lab.run('take', 'other', '--as', 'a')[0] == 0
    assert not old.exists()
    assert lab.read('waiting.json') == [dict(fresh, request=CHATGPT, pool=False)]
    assert lab.run('take', CHATGPT, '--any', '--as', 'c')[0] == 1
    assert lab.run('take', CHATGPT, '--as', 'b')[0] == 0
    # A still-running old process writes later; merge without resetting the earlier turn.
    lab.run('give', CHATGPT, '--as', 'b')
    lab.write('waiting.json', [dict(fresh, request=CHATGPT, pool=False, since='2026-10-27T09:57:00Z')])
    write_text(old, json.dumps([fresh]))
    assert lab.run('give', 'other', '--as', 'a')[0] == 0
    assert not old.exists()
    assert lab.read('waiting.json')[0]['since'] == '2026-10-27T09:57:00Z'
    assert lab.run('take', CHATGPT, '--as', 'b')[0] == 0


def a_note_with_a_control_character_is_refused(lab):
    lab.login()
    for note in ('a\x0bb', 'a\x85b', 'a\u2028b'):
        code, _, err = lab.run('take', CHATGPT, '--as', 'b', '--note', note)
        assert code == 2 and '--note' in err, (note, err)
    assert not (lab.directory() / 'holder.json').exists()


def a_request_granted_by_old_code_leaves_the_queue(lab):
    lab.clock('2026-10-27T10:00:00Z')
    lab.login()
    # An old process granted b by name, writing holder.json alone; b's row stayed in the queue.
    lab.write('waiting.json', [dict(holder='b', request=CHATGPT, pool=False, note='',
                                    since='2026-10-27T09:58:00Z', seen='2026-10-27T09:59:00Z')])
    lab.write('holder.json', dict(holder='b', note='', since='2026-10-27T09:59:30Z'))
    assert lab.run('give', CHATGPT, '--as', 'b')[0] == 0
    assert lab.read('waiting.json') == []
    code, out, _ = lab.run('take', CHATGPT, '--any', '--as', 'c')
    assert code == 0 and out.split()[0] == CHATGPT, out
    os.link(lab.tmp / 'logins/waiting.json', lab.root / 'queue-link')
    code, _, err = lab.run('take', CHATGPT, '--as', 'd')
    assert code == 4 and 'one link' in err, err


def an_old_process_lock_still_excludes(lab):
    path = lab.login()
    # Signal immediately before flock rather than guessing when the child has started.
    marker = lab.root / 'locking'
    lab.driver(f'''original = module.fcntl.flock
name = {str(lab.directory() / 'lock')!r}
def flock(fd, operation):
    if module.os.readlink('/proc/self/fd/' + str(fd.fileno())) == name:
        module.Path({str(marker)!r}).touch()
    return original(fd, operation)
module.fcntl.flock = flock
sys.exit(module.main())
''')
    proc = None
    with (lab.directory() / 'lock').open('r') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            proc = subprocess.Popen([*lab.argv, 'take', CHATGPT, '--as', 'b'], env=lab.env,
                                    text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            deadline = time.monotonic() + HUNG_TOOL_S
            while not marker.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert marker.exists() and proc.poll() is None
            assert not (lab.directory() / 'holder.json').exists()
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
            if proc is not None:
                try:
                    out, err = proc.communicate(timeout=HUNG_TOOL_S)
                    assert (proc.returncode, out, err) == (0, f'{path}\n', '')
                finally:
                    if proc.poll() is None:
                        proc.kill()
                    proc.communicate()


def list_names_pool_waiters_under_each_member(lab):
    for name in (CHATGPT, 'chatgpt-2', 'chatgpt-tools'):
        lab.login(name)
        assert lab.run('take', name, '--as', 'a')[0] == 0
    lab.clock('2026-10-27T10:00:00Z')
    assert lab.run('take', CHATGPT, '--any', '--as', 'b')[0] == 1
    queue = (lab.tmp / 'logins' / 'waiting.json').read_bytes()
    code, out, err = lab.run('list')
    assert code == 0 and not err
    for name in (CHATGPT, 'chatgpt-2'):
        section = out.split(f'{name}: ', 1)[1].split('  last 24 hours:', 1)[0]
        assert section.startswith('held by a')
        assert '  waiting: b since 2026-10-27T10:00:00Z (any of chatgpt)\n' in section
    assert out.count('(any of chatgpt)') == 2
    assert (lab.tmp / 'logins' / 'waiting.json').read_bytes() == queue


def pool_members_are_numbered_and_ties_go_by_holder(lab):
    for name in ('chatgpt-10', 'chatgpt-2', 'chatgpt-2-3', 'chatgpt-tools'):
        lab.login(name)
    lab.clock('2026-10-27T10:00:00Z')
    assert lab.run('take', CHATGPT, '--any', '--as', 'a')[1].startswith('chatgpt-2 ')
    assert lab.run('take', CHATGPT, '--any', '--as', 'a')[1].startswith('chatgpt-10 ')
    assert lab.run('take', CHATGPT, '--any', '--as', 'z')[0] == 1
    assert lab.run('take', CHATGPT, '--any', '--as', 'b')[0] == 1
    lab.run('give', 'chatgpt-2', '--as', 'a')
    assert lab.run('take', CHATGPT, '--any', '--as', 'z')[0] == 1
    assert lab.run('take', CHATGPT, '--any', '--as', 'b')[1].startswith('chatgpt-2 ')
    assert lab.run('take', 'chatgpt-2-3', '--any', '--as', 'b')[0] == 2
    assert lab.run('take', 'chatgpt-2-3', '--as', 'b')[0] == 0


def unsafe_global_state_is_refused(lab):
    lab.login()
    root = lab.tmp / 'logins'
    for filename in ('lock', 'waiting.json'):
        path = root / filename
        path.unlink(missing_ok=True)
        target = lab.root / ('outside-' + filename)
        write_text(target, '[]\n')
        path.symlink_to(target)
        for command in (('list',), ('take', CHATGPT, '--as', 'a')):
            code, out, err = lab.run(*command)
            assert code == 4 and not out and 'symlink refused' in err
            assert target.read_text() == '[]\n'
        path.unlink()
        write_text(path, '[]\n')
        path.chmod(0o644)
        assert lab.run('take', CHATGPT, '--as', 'a')[0] == 4
        path.chmod(0o600)
    assert not (lab.directory() / 'holder.json').exists()


def invalid_queues_are_refused_before_migration(lab):
    lab.login()
    fresh = dict(holder='b', request=CHATGPT, pool=False, note='',
                 since='2026-10-27T10:00:00Z', seen='2026-10-27T10:00:00Z')
    bad_rows = ({}, [dict(fresh, pool=1)], [dict(fresh, request='chatgpt-2', pool=True)],
                [fresh, fresh], [dict(fresh, since='2026-99-27T10:00:00Z')])
    for value in bad_rows:
        lab.write('waiting.json', value)
        for command in (('list',), ('take', CHATGPT, '--as', 'a')):
            code, out, err = lab.run(*command)
            assert code == 4 and not out and err
    lab.write('waiting.json', [])
    old = lab.directory() / 'waiting.json'
    write_text(old, '[{}]')
    assert lab.run('take', CHATGPT, '--as', 'a')[0] == 4
    assert old.read_text() == '[{}]' and lab.read('waiting.json') == []
    assert not (lab.directory() / 'holder.json').exists()


def an_interrupted_queue_write_does_not_break_discovery(lab):
    lab.login()
    assert lab.run('take', CHATGPT, '--as', 'a')[0] == 0
    queue = lab.tmp / 'logins' / 'waiting.json'
    before = queue.read_bytes()
    lab.driver(f'''original = module.os.replace
queue = {str(queue)!r}
def replace(source, target):
    if str(target) == queue:
        module.os._exit(77)
    return original(source, target)
module.os.replace = replace
sys.exit(module.main())
''')
    assert lab.run('take', CHATGPT, '--as', 'b')[0] == 77
    assert queue.read_bytes() == before
    assert any(p.name.startswith('.waiting.json-') for p in queue.parent.iterdir())
    lab.argv = [sys.executable, '-I', '-B', str(SCRIPT)]
    assert lab.run('list')[0] == 0
    assert lab.run('give', CHATGPT, '--as', 'a')[0] == 0
    assert lab.run('take', CHATGPT, '--any', '--as', 'b')[0] == 0
    assert lab.read('holder.json')['holder'] == 'b'


def a_wait_that_runs_out_leaves_the_queue(lab):
    lab.login()
    lab.run('take', CHATGPT, '--as', 'a')
    lab.driver("""clock = [0.0]
def sleep(seconds):
    clock[0] += seconds
module.time.monotonic = lambda: clock[0]
module.time.sleep = sleep
sys.exit(module.main())
""")
    code, out, err = lab.run('take', CHATGPT, '--as', 'b', '--wait', '0.2')
    assert code == 1 and not out and 'held by a' in err
    assert lab.read('waiting.json') == []


def drop_removes_a_waiters_row(lab):
    lab.login()
    lab.run('take', CHATGPT, '--as', 'a')
    lab.run('take', CHATGPT, '--as', 'b')
    lab.run('take', CHATGPT, '--any', '--as', 'c')
    assert lab.run('drop', CHATGPT, '--as', 'b') == (0, 'dropped: chatgpt\n', '')
    assert [row['holder'] for row in lab.read('waiting.json')] == ['c']
    assert lab.run('drop', CHATGPT, '--any', '--as', 'c') == (0, 'dropped: chatgpt\n', '')
    assert lab.read('waiting.json') == []
    assert lab.run('drop', CHATGPT, '--as', 'b') == (0, 'not waiting: chatgpt\n', '')
    assert lab.run('drop', CHATGPT, '--any', '--as', 'c') == (0, 'not waiting: chatgpt\n', '')


CASES = (replaces_a_login_without_opening_the_old_one, replace_refuses_a_held_login_even_at_rest,
         replace_refuses_a_by_name_waiter, replace_respects_only_the_pool_members_actually_reserved,
         replace_ignores_a_stale_waiter, replace_refuses_a_missing_login,
         replace_refuses_bad_sources_and_the_resting_login_itself,
         replace_refuses_cross_filesystem_moves, replace_refuses_directories_without_opening_the_old_one,
         a_note_with_a_control_character_is_refused, a_wait_that_runs_out_leaves_the_queue, drop_removes_a_waiters_row, a_now_take_preserves_stale_and_legacy_queue_files, a_now_take_never_joins_the_queue, a_now_take_takes_a_free_unclaimed_login, a_request_granted_by_old_code_leaves_the_queue, a_pool_take_grants_a_free_login_and_names_it, one_queue_in_arrival_order,
         a_waiter_for_a_stuck_login_holds_back_no_free_one, a_pool_waiter_keeps_one_free_login_not_all,
         a_stale_waiter_leaves_the_queue, two_takes_at_once_get_two_logins,
         old_per_login_queues_are_migrated, an_old_process_lock_still_excludes,
         list_names_pool_waiters_under_each_member, pool_members_are_numbered_and_ties_go_by_holder,
         unsafe_global_state_is_refused, invalid_queues_are_refused_before_migration,
         an_interrupted_queue_write_does_not_break_discovery,
         adds_a_directory_login_by_moving_it, add_refuses_an_empty_directory,
         add_refuses_a_directory_that_is_not_private, add_refuses_a_link_to_a_directory,
         takes_and_gives_a_directory_login, a_directory_login_not_back_stays_held,
         give_reads_nothing_inside_a_directory, give_refuses_a_directory_replaced_by_a_link,
         an_empty_directory_login_stays_held,
         adds_a_login_by_moving_it, add_refuses_a_login_that_is_not_private,
         add_refuses_a_second_login_at_rest, takes_a_login_at_rest, a_second_taker_waits,
         the_first_waiter_is_served_first, a_stale_waiter_loses_its_turn,
         a_waiter_seen_at_the_bound_keeps_its_turn, retaking_by_the_holder_is_idempotent,
         retaking_a_login_not_at_rest_is_refused, give_refuses_a_login_not_back,
         gives_a_login_back, giving_a_free_login_is_idempotent, give_by_another_holder_is_refused,
         take_waits_until_the_login_is_given, take_without_a_login_at_rest_says_so,
         lists_holder_waiters_and_the_last_day, refuses_an_unknown_login,
         refuses_a_symlinked_state_path)

def legacy_state_is_listed_taken_given_and_dropped(lab):
    lab.clock('2026-10-27T10:00:00Z')
    root = lab.tmp / 'logins'
    root.mkdir(mode=0o700)
    write_text(root / 'lock', '')
    for name in ('chatgpt', 'chatgpt-2'):
        directory = root / name
        directory.mkdir(mode=0o700)
        write_text(directory / 'lock', '')
        lab.source().rename(directory / 'login')
        write_text(directory / 'log.tsv',
                   '2026-10-27T09:00:00Z\tadd\t\t0\t\n'
                   '2026-10-27T09:30:00Z\ttake\ta\t60\tlegacy run\n')
    write_text(root / 'chatgpt/holder.json',
               '{"holder":"a","note":"legacy run","since":"2026-10-27T09:30:00Z"}\n')
    write_text(root / 'waiting.json',
               '[{"holder":"b","request":"chatgpt","pool":true,"note":"legacy wait",'
               '"since":"2026-10-27T09:58:00Z","seen":"2026-10-27T09:59:00Z"}]\n')
    before = {name: (root / name / 'login').stat() for name in ('chatgpt', 'chatgpt-2')}
    queue = (root / 'waiting.json').read_bytes()
    code, out, err = lab.run('list')
    assert code == 0 and not err
    assert 'chatgpt: held by a (legacy run)' in out
    assert 'chatgpt-2: at rest' in out
    assert out.count('waiting: b since 2026-10-27T09:58:00Z (any of chatgpt)') == 2
    assert 'held 0:30, 1 takes, longest wait 0:01' in out
    assert (root / 'waiting.json').read_bytes() == queue
    assert lab.run('take', 'chatgpt', '--any', '--now', '--as', 'c')[0] == 1
    assert lab.run('take', 'chatgpt', '--any', '--as', 'b') == (
        0, f'chatgpt-2 {root / "chatgpt-2/login"}\n', '')
    assert lab.read('holder.json', 'chatgpt-2') == dict(
        holder='b', note='legacy wait', since='2026-10-27T10:00:00Z')
    assert lab.read('waiting.json') == []
    assert lab.log('chatgpt-2')[-1] == [
        '2026-10-27T10:00:00Z', 'take', 'b', '120', 'legacy wait']
    assert lab.run('take', 'chatgpt', '--as', 'c')[0] == 1
    assert lab.run('drop', 'chatgpt', '--as', 'c') == (0, 'dropped: chatgpt\n', '')
    assert lab.read('waiting.json') == []
    assert lab.run('give', 'chatgpt', '--as', 'a') == (
        0, 'given: chatgpt by a after 0:30\n', '')
    assert lab.log()[-1] == ['2026-10-27T10:00:00Z', 'give', 'a', '1800', 'legacy run']
    assert lab.run('give', 'chatgpt-2', '--as', 'b')[0] == 0
    for name, info in before.items():
        assert not (root / name / 'holder.json').exists()
        after = (root / name / 'login').stat()
        assert (after.st_ino, after.st_size, after.st_mtime_ns, after.st_mode) == (
            info.st_ino, info.st_size, info.st_mtime_ns, info.st_mode)


def default_root_uses_temporary_home(lab):
    lab.env.pop('DEV_ROOT')
    lab.env.pop('DEV_TMP')
    root = lab.home / 'src/rust/tmp/logins'
    source = lab.source()
    code, out, err = lab.run('add', 'chatgpt', str(source))
    assert (code, out, err) == (0, f'added: chatgpt at {root / "chatgpt/login"}\n', '')
    assert (root / 'chatgpt/login').stat().st_size > 0
    assert not (lab.tmp / 'logins').exists()


def admission_lock_is_kept_by_a_child(lab):
    path = lab.login()
    marker = lab.root / 'locking'
    lab.driver(f'''original = module.fcntl.flock
def flock(fd, operation):
    module.Path({str(marker)!r}).touch()
    return original(fd, operation)
module.fcntl.flock = flock
sys.exit(module.main())
''')
    with (lab.root / 'admission').open('a') as admission, (lab.directory() / 'lock').open('r') as lock:
        fcntl.flock(admission, fcntl.LOCK_EX)
        fcntl.flock(lock, fcntl.LOCK_EX)
        proc = subprocess.Popen([*lab.argv, 'take', CHATGPT, '--as', 'b'], env=lab.env,
                                pass_fds=(admission.fileno(),), text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            deadline = time.monotonic() + HUNG_TOOL_S
            while not marker.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert marker.exists() and proc.poll() is None
            # Closing the caller's descriptor leaves the child holding admission.
            admission.close()
            with (lab.root / 'admission').open('r') as probe:
                try:
                    fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    pass
                else:
                    raise AssertionError('child lost the inherited admission lock')
            fcntl.flock(lock, fcntl.LOCK_UN)
            out, err = proc.communicate(timeout=HUNG_TOOL_S)
            assert (proc.returncode, out, err) == (0, f'{path}\n', '')
            with (lab.root / 'admission').open('r') as probe:
                fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.communicate()


CASES += (legacy_state_is_listed_taken_given_and_dropped,
          default_root_uses_temporary_home, admission_lock_is_kept_by_a_child)


def json_listing(lab, *names):
    code, out, err = lab.run('list', *names, '--json')
    assert code == 0 and not err, (code, out, err)
    rows = json.loads(out)  # Also refuses a second document or trailing plain output.
    assert_json_schema(rows)
    return rows


def assert_json_schema(rows):
    assert isinstance(rows, list)
    fields = {'name', 'pool', 'holder', 'since', 'note', 'use', 'run', 'waiters'}

    def stamp(value):
        assert isinstance(value, str) and re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ', value)
        datetime.fromisoformat(value.replace('Z', '+00:00'))

    for row in rows:
        assert isinstance(row, dict) and fields <= row.keys(), row
        assert all(isinstance(row[key], str) and re.fullmatch(r'[a-z][a-z0-9-]*', row[key])
                   for key in ('name', 'pool'))
        assert row['use'] in ('walk', 'pass', 'other')
        for key in ('holder', 'note', 'run'):
            assert row[key] is None or isinstance(row[key], str) and row[key], row
        if row['holder'] is None:
            assert all(row[key] is None for key in ('since', 'note', 'run'))
            assert row['use'] == 'other'
        else:
            stamp(row['since'])
        assert isinstance(row['waiters'], list)
        for waiter in row['waiters']:
            assert isinstance(waiter, dict) and {'holder', 'since', 'use'} <= waiter.keys()
            assert isinstance(waiter['holder'], str) and waiter['holder']
            assert waiter['use'] in ('walk', 'pass', 'other')
            stamp(waiter['since'])


def json_lists_empty_resting_and_missing_logins(lab):
    assert lab.run('list', '--json') == (0, '[]\n', '')
    for name in ('chatgpt-2-3', 'chatgpt-2', 'chatgpt-10', 'chatgpt'):
        lab.login(name)
    lab.directory('chatgpt-2').joinpath('login').rename(lab.root / 'away')
    names = ['chatgpt', 'chatgpt-10', 'chatgpt-2', 'chatgpt-2-3']
    rows = json_listing(lab)
    assert rows == [dict(name=name, pool='chatgpt' if name != 'chatgpt-2-3' else name,
                         holder=None, since=None, note=None, use='other', run=None, waiters=[])
                    for name in names]
    assert json_listing(lab, 'chatgpt-2') == [rows[2]]
    code, plain, err = lab.run('list')
    assert code == 0 and not err
    assert [line.split(':', 1)[0] for line in plain.splitlines() if not line.startswith(' ')] == names
    assert 'chatgpt-2: missing\n' in plain


def json_lists_a_walk_run_even_away_from_rest(lab):
    lab.clock('2026-10-30T10:00:00Z')
    path = lab.login()
    holder = 'walk/forgejo/rung-a-1'
    assert lab.run('take', CHATGPT, '--as', holder, '--note', 'rung a', '--run', 'run-W_1')[0] == 0
    path.rename(lab.root / 'away')
    assert json_listing(lab) == [dict(name=CHATGPT, pool=CHATGPT, holder=holder,
        since='2026-10-30T10:00:00Z', note='rung a', use='walk', run='run-W_1', waiters=[])]
    assert lab.read('holder.json')['run'] == 'run-W_1'


def json_lists_legacy_holders_and_pass_forms(lab):
    lab.clock('2026-10-30T10:00:00Z')
    lab.login()
    for holder, use in (('walk/rung-a-1', 'walk'), ('qa-watch', 'pass'),
                        ('qa-watch/pass-a', 'pass'), ('pass/a', 'pass'),
                        ('manual/a', 'other'), ('walker/a', 'other')):
        current = dict(holder=holder, note='', since='2026-10-30T09:00:00Z')
        lab.write('holder.json', current)
        row = json_listing(lab)[0]
        assert row['holder'] == holder and row['use'] == use
        assert row['run'] is None and row['note'] is None
        assert lab.read('holder.json') == current
    lab.write('holder.json', dict(current, run=None))
    assert json_listing(lab)[0]['run'] is None


def json_waiters_include_stale_legacy_and_pool_rows_in_order(lab):
    lab.clock('2026-10-30T10:00:00Z')
    for name in ('chatgpt', 'chatgpt-2', 'chatgpt-tools'):
        lab.login(name)
    early, late = '2026-10-30T08:00:00Z', '2026-10-30T09:00:00Z'
    rows = [dict(holder=holder, request=request, pool=pool, note='', since=since, seen=since)
            for holder, request, pool, since in (
                ('walk/forgejo/z', CHATGPT, True, late),
                ('pass/a', CHATGPT, False, late),
                ('manual/a', CHATGPT, True, early))]
    lab.write('waiting.json', rows)
    legacy = lab.directory() / 'waiting.json'
    write_text(legacy, json.dumps([dict(holder='qa-watch/old', note='', since=early, seen=early)]))
    before = (lab.tmp / 'logins/waiting.json').read_bytes(), legacy.read_bytes()
    result = json_listing(lab)
    early_pool = dict(holder='manual/a', since=early, use='other')
    late_pool = dict(holder='walk/forgejo/z', since=late, use='walk')
    assert result[0]['waiters'] == [early_pool, dict(holder='qa-watch/old', since=early, use='pass'),
                                  dict(holder='pass/a', since=late, use='pass'), late_pool]
    assert result[1]['waiters'] == [early_pool, late_pool]
    assert result[2]['waiters'] == []
    assert ((lab.tmp / 'logins/waiting.json').read_bytes(), legacy.read_bytes()) == before


def run_is_saved_for_named_pooled_now_and_wait_takes(lab):
    lab.clock('2026-10-30T10:00:00Z')
    lab.login()
    for options, run in (((), 'run-A_1'), (('--any',), 'session-123'),
                         (('--any', '--now'), 'codex-run@abc.service'),
                         (('--now',), 'session:9'), (('--wait', '1'), 'run-wait')):
        assert lab.run('take', CHATGPT, *options, '--as', 'manual/a', '--run', run)[0] == 0
        assert lab.read('holder.json')['run'] == run
        assert json_listing(lab)[0]['run'] == run
        assert lab.run('give', CHATGPT, '--as', 'manual/a')[0] == 0
    assert json_listing(lab)[0]['run'] is None


def retaking_preserves_original_run_note_and_since(lab):
    lab.clock('2026-10-30T10:00:00Z')
    lab.login()
    lab.run('take', CHATGPT, '--as', 'manual/a', '--run', 'original', '--note', 'first')
    original = lab.read('holder.json')
    lab.clock('2026-10-30T10:01:00Z')
    assert lab.run('take', CHATGPT, '--as', 'manual/a', '--run', 'replacement', '--note', 'second')[0] == 0
    assert lab.read('holder.json') == original
    assert len([row for row in lab.log() if row[1] == 'take']) == 1


def invalid_runs_are_refused_before_state_changes(lab):
    lab.login()
    for run in ('', '/tmp/a', 'has space', 'has\nnewline', 'a' * 257):
        code, out, err = lab.run('take', CHATGPT, '--as', 'manual/a', '--run', run)
        assert code == 2 and not out and '--run' in err
        assert not (lab.directory() / 'holder.json').exists()
        assert not (lab.tmp / 'logins/waiting.json').exists()
    for run in (42, [], '', '/tmp/a'):
        lab.write('holder.json', dict(holder='manual/a', note='', since='2026-10-30T10:00:00Z', run=run))
        for options in ((), ('--json',)):
            code, out, err = lab.run('list', *options)
            assert code == 4 and not out and 'invalid run' in err


def json_list_uses_plain_exit_codes_and_emits_no_partial_document(lab):
    for options in ((), ('--json',)):
        assert lab.run('list', 'unknown', *options) == (2, '', 'logins: unknown login: unknown\n')
        assert lab.run('list', 'INVALID', *options) == (2, '', 'logins: invalid login name\n')
    lab.login('chatgpt')
    lab.login('claude')
    write_text(lab.directory('claude') / 'log.tsv', 'invalid event\n')
    plain = lab.run('list')
    structured = lab.run('list', '--json')
    assert structured[0] == plain[0] == 4 and structured[2] == plain[2]
    assert structured[1] == ''
    lab.directory('claude').joinpath('log.tsv').unlink()
    queue = lab.tmp / 'logins/waiting.json'
    queue.symlink_to(lab.root / 'unused')
    assert lab.run('list', '--json')[0:2] == (4, '')


def json_listing_never_opens_a_login_or_reads_directory_entries(lab):
    path = lab.directory_login()
    trace = lab.observe_login(path)
    assert json_listing(lab)[0]['holder'] is None
    evidence = json.loads(trace.read_text())
    assert evidence['entries'] == [1]
    assert not any(isinstance(target, str) and target.startswith(str(path) + '/')
                   for _, target in evidence['calls'])
    lab.argv = [sys.executable, '-I', '-B', str(SCRIPT)]
    path.rename(lab.root / 'away')
    lab.login()
    lab.driver(f"""
def audit(event, args):
    if event == 'open' and args[0] == {str(path)!r}:
        raise AssertionError('opened a login')
sys.addaudithook(audit)
sys.exit(module.main())
""")
    assert json_listing(lab)[0]['holder'] is None


def consumer_fixture_matches_real_json_output(lab):
    fixture = json.loads(SCRIPT.with_name('fixtures').joinpath('logins-list.json').read_text())
    assert_json_schema(fixture)
    lab.clock('2026-10-30T10:00:00Z')
    for row in fixture:
        lab.login(row['name'])
        if row['holder'] is not None:
            options = ['--note', row['note']] if row['note'] is not None else []
            if row['run'] is not None:
                options += ['--run', row['run']]
            assert lab.run('take', row['name'], '--as', row['holder'], *options)[0] == 0
    lab.clock('2026-10-30T10:01:00Z')
    assert lab.run('take', 'claude', '--as', 'walk/claude/rung-b-1')[0] == 1
    assert json_listing(lab) == fixture


def qa_takes_forward_known_runs_to_custody(lab):
    namespace = runpy.run_path(str(SCRIPT.with_name('qa')), run_name='qa_fixture')
    watch = object.__new__(namespace['Watch'])
    calls = []
    watch.call = lambda *args: calls.append(args) or 'grant'
    base = ('logins', 'take', CHATGPT, '--any', '--now', '--as', 'walk/forgejo/a')
    for run in (None, '', 'run-known'):
        assert watch.take_login(CHATGPT, 'walk/forgejo/a', 'rung a', run) == 'grant'
        assert calls[-1] == (*base, '--note', 'rung a', *(['--run', run] if run else []))
    watch.take_login(CHATGPT, 'walk/forgejo/a')
    assert calls[-1] == base


CASES += (json_lists_empty_resting_and_missing_logins, json_lists_a_walk_run_even_away_from_rest,
          json_lists_legacy_holders_and_pass_forms, json_waiters_include_stale_legacy_and_pool_rows_in_order,
          run_is_saved_for_named_pooled_now_and_wait_takes, retaking_preserves_original_run_note_and_since,
          invalid_runs_are_refused_before_state_changes,
          json_list_uses_plain_exit_codes_and_emits_no_partial_document,
          json_listing_never_opens_a_login_or_reads_directory_entries,
          consumer_fixture_matches_real_json_output, qa_takes_forward_known_runs_to_custody)


def a_holder_sets_its_run_without_changing_the_hold_or_queue(lab):
    lab.clock('2026-10-30T10:00:00Z')
    lab.login()
    holder = 'walk/forgejo/rung-a-1'
    assert lab.run('take', CHATGPT, '--as', holder, '--note', 'rung a')[0] == 0
    assert lab.run('take', CHATGPT, '--as', 'manual/waiter')[0] == 1
    original = lab.read('holder.json')
    queue = (lab.tmp / 'logins/waiting.json').read_bytes()
    events = lab.log()
    lab.clock('2026-10-30T10:02:00Z')
    assert lab.run('set-run', CHATGPT, '--as', holder, '--run', 'run-live') == (
        0, f'run set: {CHATGPT} by {holder}: run-live\n', '')
    assert lab.read('holder.json') == dict(original, run='run-live')
    assert (lab.tmp / 'logins/waiting.json').read_bytes() == queue and lab.log() == events
    assert json_listing(lab)[0]['run'] == 'run-live'
    path = lab.directory() / 'holder.json'
    before = path.stat().st_mtime_ns
    assert lab.run('set-run', CHATGPT, '--as', holder, '--run', 'run-live')[0] == 0
    assert path.stat().st_mtime_ns == before
    assert lab.run('set-run', CHATGPT, '--as', holder, '--run', 'run-next')[0] == 0
    assert lab.read('holder.json') == dict(original, run='run-next')


def setting_a_run_refuses_another_holder_free_hold_and_invalid_ids(lab):
    lab.login()
    assert lab.run('set-run', CHATGPT, '--as', 'manual/a', '--run', 'run-a')[0] == 2
    assert lab.run('take', CHATGPT, '--as', 'manual/owner')[0] == 0
    original = lab.read('holder.json')
    assert lab.run('set-run', CHATGPT, '--as', 'manual/a', '--run', 'run-a')[0] == 2
    for value in ('', '/tmp/a', 'has space', 'has\nnewline', 'a' * 257):
        code, out, err = lab.run('set-run', CHATGPT, '--as', 'manual/owner', '--run', value)
        assert code == 2 and not out and '--run' in err
    assert lab.read('holder.json') == original
    assert lab.run('set-run', 'missing', '--as', 'manual/a', '--run', 'run-a')[0] == 2


def a_run_can_be_set_while_away_without_reading_the_login(lab):
    path = lab.login()
    assert lab.run('take', CHATGPT, '--as', 'walk/forgejo/a')[0] == 0
    path.rename(lab.root / 'away')
    lab.driver(f"""
    def audit(event, args):
        if event == 'open' and args[0] in ({str(path)!r}, {str(lab.root / 'away')!r}):
            raise AssertionError('opened a login')
    sys.addaudithook(audit)
    sys.exit(module.main())
    """)
    assert lab.run('set-run', CHATGPT, '--as', 'walk/forgejo/a', '--run', 'run-away')[0] == 0
    assert json_listing(lab)[0]['run'] == 'run-away'


CASES += (a_holder_sets_its_run_without_changing_the_hold_or_queue,
          setting_a_run_refuses_another_holder_free_hold_and_invalid_ids,
          a_run_can_be_set_while_away_without_reading_the_login)


def run_one(name, root):
    # Each case owns its process, umask, signal handlers and child processes.
    assert ctypes.CDLL(None).prctl(36, 1, 0, 0, 0) == 0, 'cannot become child subreaper'
    os.umask(0o077)
    children = []
    original_popen = subprocess.Popen

    class Child(original_popen):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            children.append(self)

    def stop(signum, frame):
        raise SystemExit(128 + signum)

    subprocess.Popen = Child
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, stop)
    try:
        next(case for case in CASES if case.__name__ == name)(Lab(root))
    finally:
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, signal.SIG_IGN)
        for child in children:
            if child.poll() is None:
                child.kill()
            child.communicate()
        # Tools spawn no grandchildren; reap any already-exited adopted children.
        while True:
            try:
                if os.waitpid(-1, os.WNOHANG) == (0, 0):
                    break
            except ChildProcessError:
                break


class LoginsTests(unittest.TestCase):
    """Fresh state per case; only audit, crash and IPC operations spawn."""


def isolated_case(case):
    def test(self):
        with tempfile.TemporaryDirectory(prefix='logins-test-') as directory:
            previous = os.umask(0o077)
            try:
                with support.case_deadline(HUNG_CASE_S):
                    case(Lab(Path(directory)))
            finally:
                os.umask(previous)
    test.__name__ = 'test_' + case.__name__
    return test


for case in CASES:
    setattr(LoginsTests, 'test_' + case.__name__, isolated_case(case))


class FixtureScopeTests(unittest.TestCase):
    def module(self):
        from types import ModuleType
        module = ModuleType('fixture_context')
        exec('import os, sys, secrets\nvalue = "original"\n'
             'class Example:\n    def value(self): return "original"\n', module.__dict__)
        return module

    def test_driver_failure_restores_process_context_and_module_patches(self):
        module = self.module()
        previous_cwd, previous_argv = Path.cwd(), sys.argv
        previous_env = dict(os.environ)
        token_hex = module.secrets.token_hex
        previous_umask = os.umask(0o077)
        os.umask(previous_umask)
        with tempfile.TemporaryDirectory(prefix='fixture-context-') as directory:
            result = support.execute(module, """module.value = 'changed'
module.Example.value = lambda self: 'changed'
module.secrets.token_hex = lambda count: 'changed'
module.os.environ['FIXTURE_LEAK'] = 'changed'
module.os.umask(0)
module.sys.argv = ['changed']
print('captured')
raise ValueError('fixture failure')
""", ['fixture', 'argument'], dict(HOME=directory), directory)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, 'captured\n')
        self.assertIn('ValueError: fixture failure', result.stderr)
        self.assertEqual(module.value, 'original')
        self.assertEqual(module.Example().value(), 'original')
        self.assertIs(module.secrets.token_hex, token_hex)
        self.assertEqual(Path.cwd(), previous_cwd)
        self.assertIs(sys.argv, previous_argv)
        self.assertEqual(dict(os.environ), previous_env)
        observed = os.umask(previous_umask)
        self.assertEqual(observed, previous_umask)

    def test_crash_child_keeps_durable_effects_and_isolates_memory(self):
        module = self.module()
        with tempfile.TemporaryDirectory(prefix='fixture-crash-') as directory:
            target = Path(directory) / 'saved'
            body = (f"from pathlib import Path\np = Path({str(target)!r})\n"
                    "sibling = p.with_suffix('.new')\nsibling.write_text('saved before exit')\n"
                    "sibling.replace(p)\nmodule.value = 'changed'\nmodule.os._exit(77)\n")
            result = support.child_execute(module, body, ['fixture'], dict(HOME=directory), directory)
            self.assertEqual(result.returncode, 77)
            self.assertEqual(target.read_text(), 'saved before exit')
            self.assertEqual(module.value, 'original')


if __name__ == '__main__':
    if sys.argv[1:2] == ['--one']:
        run_one(sys.argv[2], Path(sys.argv[3]))
    else:
        unittest.main(verbosity=2)
