"""Process isolation for offline walk cases; each child reaps its descendants."""
import ctypes
import os
from pathlib import Path
import signal
import sys
import tempfile

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
