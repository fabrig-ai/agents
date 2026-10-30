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


def process_paths(root):
    used, errors = set(), set()
    for process in Path(root).iterdir():
        if not process.name.isdigit():
            continue
        try:
            links = [process / 'cwd']
            try:
                links.extend((process / 'fd').iterdir())
            except FileNotFoundError:
                pass
            for link in links:
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
                    parts = line.split(None, 5)
                    if len(parts) == 6 and parts[5].startswith('/'):
                        target = re.sub(r'\\([0-7]{3})', lambda m: chr(int(m[1], 8)), parts[5].rstrip('\n'))
                        used.add(target)
                        used.add(target.removesuffix(' (deleted)'))
        except (OSError, ValueError) as exc:
            # ESRCH is the normal race with process exit. Permission or other
            # inspection failures make this snapshot incomplete.
            if isinstance(exc, ProcessLookupError):
                continue
            errors.add(type(exc).__name__)
    return dict(paths=sorted(used), errors=sorted(errors))


if __name__ == '__main__':
    if len(sys.argv) != 1:
        sys.exit('proc_paths takes no arguments')
    print(json.dumps(process_paths(Path('/proc'))))
