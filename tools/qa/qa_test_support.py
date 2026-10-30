"""Scoped, serial CLI fixtures; production modules are loaded once per file."""
from contextlib import contextmanager, redirect_stderr, redirect_stdout
import importlib.machinery
import importlib.util
import io
import os
from pathlib import Path
import runpy
import subprocess
import sys
import time
import fcntl
import traceback
from types import ModuleType

_MODULES = {}


def load(path):
    path = Path(path).resolve()
    if path not in _MODULES:
        previous = os.umask(0o077)
        try:
            loader = importlib.machinery.SourceFileLoader('fixture_' + path.name, str(path))
            spec = importlib.util.spec_from_loader(loader.name, loader)
            module = importlib.util.module_from_spec(spec)
            loader.exec_module(module)
            _MODULES[path] = module
        finally:
            os.umask(previous)
    return _MODULES[path]


@contextmanager
def scope(module):
    """Restore injected globals, class methods and standard-library patches."""
    namespace = module.__dict__
    dictionaries = [(namespace, namespace.copy())]
    evidence = namespace.get('evidence')
    if evidence is not None:
        # runpy's returned mapping differs from function.__globals__.
        actual = evidence['snapshot'].__globals__
        dictionaries.extend((d, d.copy()) for d in (evidence, actual))
    standards = {value for value in namespace.values() if isinstance(value, ModuleType)}
    standards.update((os, sys, time, fcntl, subprocess, runpy, io))
    for standard in standards:
        dictionaries.append((standard.__dict__, standard.__dict__.copy()))
    classes = [(value, dict(vars(value))) for value in namespace.values()
               if isinstance(value, type) and value.__module__ == module.__name__]
    try:
        yield
    finally:
        for cls, saved in classes:
            for name in set(vars(cls)) - set(saved):
                delattr(cls, name)
            for name, value in saved.items():
                if name not in ('__dict__', '__weakref__'):
                    setattr(cls, name, value)
        for target, saved in reversed(dictionaries):
            target.clear()
            target.update(saved)


def execute(module, body, argv, env, cwd=None, setup=None):
    """Run a CLI/driver with subprocess-compatible output and process context."""
    from unittest.mock import patch
    out, err = io.StringIO(), io.StringIO()
    previous_argv, previous_cwd = sys.argv, Path.cwd()
    previous_umask = os.umask(0o077)
    original_run_path = runpy.run_path
    def cached(path, *args, **kwargs):
        path = Path(path).resolve()
        if path in _MODULES:
            return _MODULES[path].__dict__
        return original_run_path(str(path), *args, **kwargs)
    try:
        with scope(module), patch.dict(os.environ, env, clear=True), \
                redirect_stdout(out), redirect_stderr(err):
            sys.argv = list(map(str, argv))
            if cwd is not None:
                os.chdir(cwd)
            runpy.run_path = cached
            if setup is not None:
                setup(module.__dict__)
            status = 0
            try:
                exec(body, {'__name__': '__main__', 'tool': module.__dict__, 'module': module, 'sys': sys})
            except SystemExit as error:
                if isinstance(error.code, str):
                    print(error.code, file=sys.stderr)
                    status = 1
                else:
                    status = error.code or 0
            except Exception:
                traceback.print_exc()
                status = 1
    finally:
        sys.argv = previous_argv
        os.chdir(previous_cwd)
        os.umask(previous_umask)
    return subprocess.CompletedProcess(argv, status, out.getvalue(), err.getvalue())


def child_execute(module, body, argv, env, cwd, setup=None, timeout=60):
    """A bounded real child for irreversible hooks/exit, inheriting loaded code."""
    import multiprocessing
    import signal
    import tempfile
    with tempfile.TemporaryFile(mode='w+') as out, tempfile.TemporaryFile(mode='w+') as err:
        def run():
            os.setsid()
            result = execute(module, body, argv, env, cwd, setup)
            out.write(result.stdout)
            err.write(result.stderr)
            out.flush()
            err.flush()
            os._exit(result.returncode)
        child = multiprocessing.get_context('fork').Process(target=run)
        child.start()
        try:
            child.join(timeout)
            if child.is_alive():
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                child.join()
                raise subprocess.TimeoutExpired(argv, timeout)
            out.seek(0)
            err.seek(0)
            return subprocess.CompletedProcess(argv, child.exitcode, out.read(), err.read())
        finally:
            if child.is_alive():
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                child.join()
            child.close()


@contextmanager
def case_deadline(seconds):
    """Keep the original case bound after removing its interpreter wrapper."""
    import signal
    def expired(signum, frame):
        raise TimeoutError(f'fixture case exceeded {seconds} seconds')
    previous = signal.signal(signal.SIGALRM, expired)
    timer = signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, *timer)
        signal.signal(signal.SIGALRM, previous)
