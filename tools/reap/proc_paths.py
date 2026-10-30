"""Read process path metadata only; optional privileged helper for reap.

Never reads process environments, command lines, file contents through fds,
credentials, or machine/service state. The CLI always uses the real /proc.
"""
import json
import os
from pathlib import Path
import re
import stat
import sys
import time


def children(path):
    with os.scandir(path) as entries:
        for entry in entries:
            yield Path(entry.path)


def process_paths(root):
    used, errors = set(), set()
    deadline = time.monotonic() + 20
    entries = 0
    def check():
        nonlocal entries
        entries += 1
        if entries > 200000 or time.monotonic() >= deadline:
            raise TimeoutError('budget')
    for process in children(root):
        try:
            check()
        except TimeoutError:
            errors.add('budget')
            break
        if not process.name.isdigit():
            continue
        try:
            check()
            links = [process / 'cwd']
            try:
                for link in children(process / 'fd'):
                    check()
                    links.append(link)
            except FileNotFoundError:
                pass
            for link in links:
                check()
                try:
                    target = os.readlink(link)
                    if target.startswith('/'):
                        used.add(target)
                        used.add(target.removesuffix(' (deleted)'))
                except FileNotFoundError:
                    pass
            try:
                fd = os.open(process / 'maps', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            except FileNotFoundError:
                continue
            with os.fdopen(fd, 'r', errors='replace') as stream:
                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                    raise ValueError('nonregular maps')
                for line in stream:
                    check()
                    parts = line.split(None, 5)
                    if len(parts) == 6 and parts[5].startswith('/'):
                        target = re.sub(r'\\([0-7]{3})', lambda m: chr(int(m[1], 8)), parts[5].rstrip('\n'))
                        used.add(target)
                        used.add(target.removesuffix(' (deleted)'))
        except TimeoutError:
            errors.add('budget')
            break
        except (OSError, ValueError) as exc:
            # ESRCH is the normal race with process exit. Permission or other
            # inspection failures make this snapshot incomplete.
            if isinstance(exc, ProcessLookupError):
                continue
            errors.add(type(exc).__name__)
    return dict(paths=sorted(used), errors=sorted(errors), entries=entries)


if __name__ == '__main__':
    if len(sys.argv) != 1:
        sys.exit('proc_paths takes no arguments')
    print(json.dumps(process_paths(Path('/proc'))))
