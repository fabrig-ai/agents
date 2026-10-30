"""Gate selection, isolated execution and wait4 resource accounting (gate.md §2)."""
import argparse
import ctypes
from concurrent.futures import ProcessPoolExecutor
import fnmatch
import json
import math
import multiprocessing
import os
from pathlib import Path
import resource
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import tomllib

DEFAULTS = dict(file_cpu_s=8, file_wall_s=15, tier_cpu_s=100,
                merge_wall_s=60, enforce=False)
RUN_FILE = """
import importlib.util
from pathlib import Path
import sys
import unittest
path = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(path.parent))
name = "gate_" + path.relative_to(Path.cwd()).as_posix().encode().hex()
spec = importlib.util.spec_from_file_location(name, path)
module = importlib.util.module_from_spec(spec)
sys.modules[name] = module
spec.loader.exec_module(module)
suite = unittest.defaultTestLoader.loadTestsFromModule(module)
result = unittest.TextTestRunner(verbosity=2).run(suite)
sys.exit(0 if result.wasSuccessful() else 1)
"""


def configuration(root):
    path = root / 'tools/gate.toml'
    config = tomllib.loads(path.read_text()) if path.exists() else {}
    budget = DEFAULTS | config.get('budget', {})
    for key in DEFAULTS.keys() - {'enforce'}:
        value = budget[key]
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError(f'invalid budget {key}: {value}')
    if type(budget['enforce']) is not bool:
        raise ValueError('budget.enforce must be boolean')
    for path, limits in config.get('files', {}).items():
        if not isinstance(limits.get('owner'), str) or not limits['owner']:
            raise ValueError(f'missing owner: {path}')
        for key in ('file_cpu_s', 'file_wall_s'):
            value = limits.get(key, budget[key])
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise ValueError(f'invalid {key}: {path}')
    return config | {'budget': budget}


def discover(root, tier='gate'):
    return sorted(p.relative_to(root).as_posix()
                  for p in (root / 'tools').rglob('test_*.py')
                  if p.name.endswith('_periodic.py') == (tier == 'periodic'))


def select(root, config, changed, tier='gate', include_smoke=True):
    available = set(discover(root, tier))
    selected = set(config.get('smoke', [])) & available if include_smoke else set()
    for path in changed:
        if path.endswith('.md') or path.startswith('docs/'):
            selected.update(set(config.get('smoke', [])) & available)
            continue
        matches = [tests for pattern, tests in config.get('select', {}).items()
                   if fnmatch.fnmatchcase(path, pattern)]
        if matches:
            for tests in matches:
                selected.update(available if tests == ['*'] else set(tests) & available)
        elif path.startswith('tools/'):
            parent = Path(path).parent.as_posix()
            nearby = {p for p in available if Path(p).parent.as_posix() == parent}
            selected.update(nearby or available)
        else:
            selected.update(available)
    return sorted(selected)


def changed_paths(root, base, head='HEAD'):
    return subprocess.check_output(['git', 'diff', '--name-only', '-z',
                                    f'{base}...{head}'], cwd=root).decode().split('\0')[:-1]


def priority(cpu_limit):
    os.nice(max(0, 19 - os.getpriority(os.PRIO_PROCESS, 0)))
    if cpu_limit is not None:
        cap = max(1, math.ceil(cpu_limit))
        resource.setrlimit(resource.RLIMIT_CPU, (cap, cap + 1))


# Workers are Linux subreapers: fixtures may deliberately start new sessions.
# Adopted children are measured and drained before removing their HOME/TMPDIR.
DEADLINE = float('inf')


def subreaper():
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(36, 1, 0, 0, 0):  # PR_SET_CHILD_SUBREAPER
        raise OSError(ctypes.get_errno(), 'cannot become a test subreaper')


def drain_children():
    cpu = 0.0
    children = Path(f'/proc/{os.getpid()}/task/{os.getpid()}/children')
    while True:
        for child in children.read_text().split():
            try:
                os.kill(int(child), signal.SIGKILL)
            except ProcessLookupError:
                pass
        try:
            pid, status, usage = os.wait4(-1, os.WNOHANG)
        except ChildProcessError:
            return cpu
        if pid:
            cpu += usage.ru_utime + usage.ru_stime
        else:
            time.sleep(0.005)


def run_file(root, path, limits, enforce):
    # Each worker waits for exactly its own child. Popen.wait/poll must not
    # reap it first: wait4 is the source of user+system (including waited children).
    subreaper()
    if time.monotonic() >= DEADLINE:
        return dict(file=path, owner=limits.get('owner', 'ops'), cpu_s=0.0, wall_s=0.0,
                    budget_s=limits['file_cpu_s'], wall_limit_s=limits['file_wall_s'],
                    over=False, starved=True, failed=False, code=None,
                    output='unobserved: tier wall limit expired before this file started\n')
    priority(None)
    if not shutil.which('ionice'):
        raise OSError('ionice is required for idle IO priority')
    subprocess.run(['ionice', '-c3', '-p', str(os.getpid())], check=True)
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix='gate-file-') as directory:
        home = Path(directory) / 'home'
        home.mkdir()
        env = dict(os.environ, HOME=str(home), TMPDIR=directory)
        command = [sys.executable, '-I', '-B', '-c', RUN_FILE, path]
        if shutil.which('ionice'):
            command = ['ionice', '-c3', *command]
        with tempfile.TemporaryFile() as output:
            child = subprocess.Popen(command, cwd=root, env=env,
                                     stdin=subprocess.DEVNULL, stdout=output,
                                     stderr=subprocess.STDOUT, start_new_session=True,
                                     preexec_fn=lambda: priority(limits['file_cpu_s'] if enforce else None))
            starved = False
            try:
                while True:
                    pid, status, usage = os.wait4(child.pid, os.WNOHANG)
                    if pid:
                        break
                    if time.monotonic() >= min(started + limits['file_wall_s'], DEADLINE):
                        starved = True
                        os.killpg(child.pid, signal.SIGKILL)
                        _, status, usage = os.wait4(child.pid, 0)
                        break
                    time.sleep(0.01)
            finally:
                # Drain any surviving descendants, even after a successful child.
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                descendant_cpu = drain_children()
            child.returncode = os.waitstatus_to_exitcode(status)
            output.seek(0)
            text = output.read().decode(errors='replace')
    cpu = usage.ru_utime + usage.ru_stime + descendant_cpu
    over = cpu > limits['file_cpu_s'] or child.returncode in (-signal.SIGXCPU, -signal.SIGKILL) and not starved
    return dict(file=path, owner=limits.get('owner', 'ops'), cpu_s=cpu,
                wall_s=time.monotonic() - started, budget_s=limits['file_cpu_s'],
                wall_limit_s=limits['file_wall_s'], over=over, starved=starved,
                failed=(child.returncode != 0 and not starved) or (starved and any(
                    marker in text for marker in (' ... FAIL', ' ... ERROR', 'Traceback (most recent call last)'))), code=child.returncode, output=text)


def atomic_json(path, result):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, prefix='.' + path.name,
                                     delete=False) as stream:
        json.dump(result, stream, indent=2)
        temporary = Path(stream.name)
    temporary.replace(path)


def budget_mode(budget):
    return 'budget: ENFORCED' if budget['enforce'] else 'budget: REPORT-ONLY (not enforced)'


def wall_status(elapsed, budget):
    if elapsed > budget['merge_wall_s']:
        return '; OVER (enforced)' if budget['enforce'] else '; OVER (report-only)'
    return ''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tier', choices=('gate', 'periodic'), default='gate')
    parser.add_argument('--changed')
    parser.add_argument('--json', type=Path)
    parser.add_argument('files', nargs='*')
    args = parser.parse_args()
    root = Path.cwd()
    config = configuration(root)
    budget = config['budget']
    if args.files and args.changed:
        parser.error('FILES and --changed are mutually exclusive')
    if args.files:
        paths = sorted({Path(p).resolve() for p in args.files})
        for path in paths:
            if not (path.is_relative_to(root / 'tools') and path.is_file()
                    and path.match('test_*.py')):
                parser.error(f'expected a tools/test_*.py file: {path}')
        paths = [p.relative_to(root).as_posix() for p in paths]
    elif args.changed:
        paths = select(root, config, changed_paths(root, args.changed), args.tier)
    else:
        paths = discover(root, args.tier)
    started = time.monotonic()
    global DEADLINE
    DEADLINE = started + budget['merge_wall_s']
    results = []
    workers = min(8, os.cpu_count() or 1)
    print('Selected: ' + ', '.join(paths), file=sys.stderr, flush=True)
    with ProcessPoolExecutor(max_workers=workers,
                             mp_context=multiprocessing.get_context('fork')) as pool:
        queued = sorted(paths, key=lambda p: (-(root / p).stat().st_size, p))
        futures = {p: pool.submit(run_file, root, p, budget | config.get('files', {}).get(p, {}),
                                  budget['enforce']) for p in queued}
        for path in paths:
            result = futures[path].result()
            results.append(result)
            print(f"=== {path} ({result['wall_s']:.3f}s) ===", file=sys.stderr)
            print(result['output'], end='' if result['output'].endswith('\n') else '\n', file=sys.stderr)
    wall = time.monotonic() - started
    cpu = sum(r['cpu_s'] for r in results)
    failed = sum(r['failed'] for r in results)
    reasons = [f"file CPU budget: {r['file']} ({r['owner']})" for r in results if r['over']]
    if cpu > budget['tier_cpu_s']:
        reasons.append(f"tier CPU budget: {args.tier} {cpu:.3f}s > {budget['tier_cpu_s']}s")
    print('FILE OWNER CPU_s WALL_s BUDGET_s STATUS', file=sys.stderr)
    for r in results:
        status = 'over' if r['over'] else 'ok'
        if r['starved']:
            status += ',starved/unobserved'
        if r['failed']:
            status += ',failed'
        print(f"{r['file']} {r['owner']} {r['cpu_s']:.3f} {r['wall_s']:.3f} {r['budget_s']:g} {status}", file=sys.stderr)
    print(f"Tier {args.tier}: CPU {cpu:.3f}s / {budget['tier_cpu_s']:g}s; wall {wall:.3f}s; "
          f"merge wall {wall:.3f}s / {budget['merge_wall_s']:g}s; "
          f"{budget_mode(budget)}{wall_status(wall, budget)}", file=sys.stderr)
    for reason in reasons:
        print(('FAIL: ' if budget['enforce'] else 'REPORT ONLY: ') + reason, file=sys.stderr)
    starved = sum(r['starved'] for r in results)
    print(f'Checked {len(paths)} files in {wall:.3f}s ({workers} workers; {failed} failed; '
          f'{starved} starved/unobserved); {budget_mode(budget)}{wall_status(wall, budget)}', file=sys.stderr)
    code = int(bool(failed or budget['enforce'] and reasons))
    if args.json:
        atomic_json(args.json, dict(tier=args.tier, files=[{k: v for k, v in r.items() if k != 'output'}
                                                        for r in results], cpu_s=cpu, wall_s=wall,
                                    failed=failed, starved=starved, reasons=reasons, code=code))
    return code


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        sys.exit(f'check: {error}')
