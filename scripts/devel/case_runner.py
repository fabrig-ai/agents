"""One process, session and directory per fixture case, over a pool."""
from concurrent.futures import ThreadPoolExecutor
import ctypes
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import textwrap
import threading
import time


# Hang detection for honest subprocess work, never an assertion of tool speed.
# Local tidy/land commands measured below two seconds idle, but exceeded
# 60 seconds in a gate at load >100 on eight cores. Five minutes detects
# a hung tool; fifteen bounds a whole case with several tool invocations.
HUNG_TOOL_S = 300
HUNG_CASE_S = 900
CASE_STOP_S = 5


def stop_on_signals():
    """SIGINT and SIGTERM raise, so every cleanup on the way out still runs."""
    def stop(signum, frame):
        sys.exit(128 + signum)
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, stop)


def reap_descendants():
    """Kill what a case left running; as its subreaper, every orphan is this process's child."""
    me = os.getpid()
    while True:
        children = []
        for entry in Path('/proc').iterdir():
            try:
                if entry.name.isdigit() and int((entry / 'stat').read_text().rsplit(')', 1)[1].split()[1]) == me:
                    children.append(int(entry.name))
            except (OSError, ValueError, IndexError):
                pass
        if not children:
            return
        for pid in children:
            try:
                os.kill(pid, signal.SIGKILL)
                os.waitpid(pid, 0)
            except (ProcessLookupError, ChildProcessError):
                pass


def run_one(case, run, built, prefix):
    """Run one case in this process, on its own disposable lab."""
    # Orphans of nested sessions come back here, so a stopped case leaves none behind.
    assert ctypes.CDLL(None).prctl(36, 1, 0, 0, 0) == 0, 'cannot become child subreaper'  # PR_SET_CHILD_SUBREAPER
    stop_on_signals()
    with tempfile.TemporaryDirectory(prefix=prefix) as directory:
        try:
            run(case, Path(directory), built)
        finally:
            # A stop arriving now must not cut the lab's removal short.
            ignore_signals()
            reap_descendants()


def ignore_signals():
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, signal.SIG_IGN)


def stop_cases(procs):
    """SIGTERM lets each case's cleanups run; SIGKILL takes whatever remains of its session."""
    for sig in (signal.SIGTERM, signal.SIGKILL):
        for proc in procs:
            try:
                os.killpg(proc.pid, sig)
            except (ProcessLookupError, PermissionError):
                pass
        deadline = time.monotonic() + CASE_STOP_S
        for proc in procs:
            try:
                proc.wait(timeout=max(0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                pass


def main(suite, cases, run, slow=(), template=None, timeout=HUNG_CASE_S, prefix='fixture-'):
    """Run selected cases in private sessions over an affinity-sized pool.

    A template, when supplied, is built once and passed read-only by convention
    as --built DIR. Each case gets a fresh directory and run(case, directory,
    built); --one NAME without --built keeps standalone cases self-contained.
    Results print in case order, even when slow cases are submitted first.
    """
    names = {case.__name__: case for case in cases}
    args = sys.argv[1:]
    if args[:1] == ['--one']:
        if len(args) not in (2, 4) or args[1] not in names or (len(args) == 4 and args[2] != '--built'):
            sys.exit('expected --one NAME [--built DIR]')
        return run_one(names[args[1]], run, Path(args[3]) if len(args) == 4 else None, prefix)
    if args:
        cases = tuple(case for case in cases if case.__name__ in args)
    assert cases, 'no cases selected'
    start = time.monotonic()
    stop_on_signals()
    # The template outlives every worker, including their signal cleanups.
    with tempfile.TemporaryDirectory(prefix=prefix) as directory:
        built = Path(directory) / 'baseline' if template else None
        if template:
            built.mkdir()
            template(built)
        return run_pool(suite, cases, slow, timeout, directory, built, start)


def run_pool(suite, cases, slow, timeout, directory, built, start):
    live, guard = set(), threading.Lock()
    stopping = False

    def child(case):
        case_start = time.monotonic()
        with guard:
            if stopping:
                return None
            args = [sys.executable, str(suite), '--one', case.__name__]
            if built is not None:
                args += ['--built', str(built)]
            # Names never enter lab paths: fixture wrappers match argv substrings.
            proc = subprocess.Popen(args, stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True,
                                    env=dict(os.environ, TMPDIR=directory))
            live.add(proc)
        try:
            try:
                output, timed_out = proc.communicate(timeout=timeout)[0], False
            except subprocess.TimeoutExpired:
                stop_cases([proc])
                output, timed_out = proc.communicate()[0], True
        finally:
            with guard:
                live.discard(proc)
        return proc.returncode, timed_out, output.decode(errors='replace'), time.monotonic() - case_start

    pool = ThreadPoolExecutor(min(len(cases), len(os.sched_getaffinity(0))))
    failed = 0
    try:
        # The longest cases start first; results still print in case order.
        futures = {case: pool.submit(child, case)
                   for case in sorted(cases, key=lambda case: case.__name__ not in slow)}
        for number, case in enumerate(cases, 1):
            status, timed_out, output, elapsed = futures[case].result()
            if timed_out:
                failed += 1
                print(f'FAIL {number}: {case.__name__}: timed out after {timeout}s\n' + output, flush=True)
            elif status:
                failed += 1
                print(f'FAIL {number}: {case.__name__} ({elapsed:.2f}s) exit {status}\n' + output, flush=True)
            else:
                print(f'ok {number}: {case.__name__} ({elapsed:.2f}s)', flush=True)
                if output.strip():
                    print(textwrap.indent(output.rstrip('\n'), '    '), flush=True)
    except BaseException:
        # Repeated signals must not interrupt the stop or template removal.
        ignore_signals()
        with guard:
            stopping = True
            procs = list(live)
        pool.shutdown(wait=False, cancel_futures=True)
        stop_cases(procs)
        pool.shutdown(wait=True, cancel_futures=True)
        raise
    pool.shutdown()
    print(f'{"failed " + str(failed) + " of" if failed else "completed"} {len(cases)} cases '
          f'in {time.monotonic() - start:.2f}s', flush=True)
    return 1 if failed else 0
