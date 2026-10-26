#!/usr/bin/env python3
"""Best-effort cleanup shared by the landing and record commands."""
import os
from pathlib import Path
import sys


def warn(caller, message):
    print(f'{caller}: warning: {message}', file=sys.stderr, flush=True)


def clear_target(caller, worktree):
    target = worktree / 'target'
    try:
        if (worktree / '.git').is_file() and not target.is_symlink() and target.is_dir():
            import shutil
            shutil.rmtree(target)
    except OSError as error:
        warn(caller, f'cannot clear {target}: {error}')


def start_tidy(caller, variable, tmp, arguments):
    try:
        if variable in os.environ:
            command = os.environ[variable]
        else:
            import shlex
            tidy = Path(__file__).resolve().with_name('tidy')
            if not tidy.is_file() or not os.access(tidy, os.X_OK):
                warn(caller, f'cannot start tidy: {tidy} is not executable')
                return
            command = shlex.quote(str(tidy))
        if not command:
            return
        logs = tmp / 'logs'
        logs.mkdir(parents=True, exist_ok=True)
        with (logs / 'tidy.log').open('ab') as log:
            import subprocess
            subprocess.Popen(['setsid', 'bash', '-c', command + ' "$@"', 'tidy', *arguments],
                             cwd=tmp, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                             close_fds=True, start_new_session=True)
    except (OSError, ValueError) as error:
        warn(caller, f'cannot start tidy: {error}')


if __name__ == '__main__':
    clear_target('land', Path(sys.argv[1]))
    start_tidy('land', 'LAND_TIDY', Path(sys.argv[2]), [sys.argv[3]])
