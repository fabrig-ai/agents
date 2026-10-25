#!/usr/bin/env python3
"""Best-effort cleanup shared by the landing and record commands."""
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys


def warn(caller, message):
    print(f'{caller}: warning: {message}', file=sys.stderr, flush=True)


def clear_target(caller, worktree):
    target = worktree / 'target'
    try:
        if (worktree / '.git').is_file() and not target.is_symlink() and target.is_dir():
            shutil.rmtree(target)
    except OSError as error:
        warn(caller, f'cannot clear {target}: {error}')


def start_tidy(caller, variable, tmp, arguments):
    command = os.environ.get(variable, shlex.quote(str(Path(__file__).resolve().with_name('tidy'))))
    if not command:
        return
    try:
        logs = tmp / 'logs'
        logs.mkdir(parents=True, exist_ok=True)
        # Catch a missing executable before detaching. Compound shell commands
        # remain shell commands; their later diagnostics go to the tidy log.
        lexer = shlex.shlex(command, posix=True, punctuation_chars=';&|()<>')
        lexer.whitespace_split = True
        words = list(lexer)
        if (words and not any(word and all(c in ';&|()<>' for c in word) for word in words)
                and not any(c in words[0] for c in '$`~*?[]{}')):
            available = subprocess.run(['bash', '-c', 'command -v -- "$1"', 'tidy', words[0]],
                                       cwd=tmp,
                                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL, check=False)
            if available.returncode and '=' not in words[0]:
                raise FileNotFoundError(f'tidy command not found: {words[0]}')
        with (logs / 'tidy.log').open('ab') as log:
            subprocess.Popen(['setsid', 'bash', '-c', command + ' "$@"', 'tidy', *arguments],
                             cwd=tmp, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                             close_fds=True, start_new_session=True)
    except (OSError, ValueError) as error:
        warn(caller, f'cannot start tidy: {error}')


if __name__ == '__main__':
    clear_target('land', Path(sys.argv[1]))
    start_tidy('land', 'LAND_TIDY', Path(sys.argv[2]), [sys.argv[3]])
