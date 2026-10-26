#!/usr/bin/env python3
"""What a landing taught, and a plain land's record in the landing feed.

land-feed.py land REPO BRANCH BASE COMMIT [GATE_LOG]
  From the worktree that pushed: append the landing's record to the feed
  (landing-flow.md, 12), with starved passes from GATE_LOG when given.
  Exit 0 when written, or when no feed is due; 1, with one line on stderr,
  when the append failed.
"""
from datetime import datetime, timezone
from pathlib import Path
import json
import os
import re
import secrets
import shlex
import socket
import subprocess
import sys
from urllib.parse import urlsplit

LIMIT, WIDTH = 10, 200  # a landing's lines per repository, and their width
# Copied verbatim from land-set: COORDINATOR, SSH and the FEED program.
COORDINATOR = 'debian-16gb-hel1-3'
SSH = ['ssh', '-T', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
       '-o', 'ConnectTimeout=5', '-o', 'ServerAliveInterval=5',
       '-o', 'ServerAliveCountMax=2', '-o', 'UpdateHostKeys=no',
       '-o', 'LogLevel=QUIET', 'free@2.29.124.199']
FEED = '''import fcntl, os, stat, sys
os.umask(0o077)
p = sys.argv[1]
parent = os.path.dirname(p)
os.makedirs(parent, mode=0o700, exist_ok=True)
os.chmod(parent, 0o700)
fd = os.open(p, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
with os.fdopen(fd, 'w') as out:
    if not stat.S_ISREG(os.fstat(out.fileno()).st_mode):
        raise ValueError('invalid feed')
    os.fchmod(out.fileno(), 0o600)
    fcntl.flock(out, fcntl.LOCK_EX)
    out.write(sys.stdin.read())
    out.flush()
'''
FEED_PATH = '/home/free/.local/state/agents-land-set/feed.jsonl'


def taught(path, base, tip):
    """The Taught: values of base..tip, oldest first, unfolded and stripped.

    Drop empty values; keep the first LIMIT, cut to WIDTH with a final …,
    and return those lines and the number left out. Git failure teaches none.
    """
    # land-set pulses its remote lock every 5s, with 10s liveness. Keep
    # this best-effort read below the remaining margin after a boundary.
    try:
        result = subprocess.run(['git', '-C', str(path), 'log', '--reverse', '-z',
                                 '--format=%(trailers:key=Taught,valueonly,unfold)',
                                 base + '..' + tip], check=True, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, timeout=2)
    except (OSError, subprocess.SubprocessError):
        return [], 0
    lines = [line.strip() for chunk in result.stdout.decode(errors='replace').split('\0')
             for line in chunk.splitlines() if line.strip()]
    return [line if len(line) <= WIDTH else line[:WIDTH - 1] + '…'
            for line in lines[:LIMIT]], max(0, len(lines) - LIMIT)


def starved(log):
    """Unique gate-starved names in log order, bounded like land's result."""
    try:
        text = Path(log).read_text(errors='replace')
    except OSError:
        return [], 0
    names = list(dict.fromkeys(re.findall(r'^gate-starved (.+)$', text, re.M)))
    return names[:50], max(0, len(names) - 50)


def hosted(url):
    """Whether a push URL, including a remote-helper address, names a host."""
    while match := re.match(r'^([^/:\[\]]+)::', url):
        if match[1] == 'ext':
            return False
        url = url[match.end():]
    if url.startswith('file:'):
        return False
    try:
        if '://' in url:
            return bool(urlsplit(url).hostname)
    except ValueError:
        return False
    return bool(re.match(r'^(?:[^/@:]+@)?(?:\[[^]]+\]|[^/:]+):.+', url))


def remote_host():
    """Only an origin with a host can cause a default feed append."""
    try:
        result = subprocess.run(['git', 'remote', 'get-url', '--push', 'origin'],
                                check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                timeout=30)
        return hosted(result.stdout.decode(errors='replace').strip())
    except (OSError, subprocess.SubprocessError):
        return False


def main():
    if len(sys.argv) not in (6, 7) or sys.argv[1] != 'land':
        print('usage: land-feed.py land REPO BRANCH BASE COMMIT [GATE_LOG]', file=sys.stderr)
        return 1
    local = os.environ.get('LAND_FEED')
    if local == '':
        return 0
    if local is None and (os.environ.get('HEAVY_RECOVERY_FIXTURE') == '1' or not remote_host()):
        return 0
    repo, branch, base, commit = sys.argv[2:6]
    lines, more = taught('.', base, commit)
    host = re.sub('[^A-Za-z0-9_.-]', '-', socket.gethostname()).lstrip('._-')[:64] or 'local'
    record = dict(time=datetime.now(timezone.utc).isoformat(), kind='land', event='landed',
                  host=host, token=secrets.token_hex(16), repo=repo, branch=branch,
                  base=base, commit=commit)
    if lines:
        record['taught'] = lines
    if more:
        record['taught_more'] = more
    if len(sys.argv) == 7:
        names, more = starved(sys.argv[6])
        if names:
            record['starved'] = names
        if more:
            record['starved_more'] = more
    # The same subprocess bounds flock and writing on local and remote paths.
    argv = ['python3', '-I', '-S', '-c', FEED, os.path.abspath(local) if local is not None else FEED_PATH]
    if local is None and socket.gethostname() != COORDINATOR:
        argv = [*SSH, shlex.join(argv)]
    try:
        subprocess.run(argv, input=(json.dumps(record) + '\n').encode(),
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        print('land-feed: feed append failed', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
