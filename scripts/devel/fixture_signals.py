"""Linux fixture signals: explicit identities, pidfds, and no numeric kill fallback.

Owners publish their own identity, or capture an unreaped direct child. A
pidfd is opened before checking that identity, so a later reap/reuse cannot
redirect a signal. Group delivery snapshots pidfds while the leader lives.
"""
import ctypes
import os
from pathlib import Path
import select
import signal
import subprocess
import sys


def stat(pid):
    if int(pid) <= 1:
        raise ValueError("fixture PID must exceed 1")
    return Path(f"/proc/{int(pid)}/stat").read_text().rsplit(")", 1)[1].split()


def publish(path, text):
    """Readers see a complete identity or result, never a newly empty file."""
    temporary = path.with_name(path.name + '.new')
    temporary.write_text(text)
    temporary.replace(path)


def identity(pid):
    """Only call for oneself or a direct child that has not been reaped."""
    return dict(pid=int(pid), ticks=stat(pid)[19])


class Target:
    def __init__(self, owner, *, parent=None, group=None):
        self.pid, self.fd = int(owner["pid"]), None
        if self.pid <= 1:
            raise ValueError("fixture PID must exceed 1")
        try:
            self.fd = os.pidfd_open(self.pid)
            fields = stat(self.pid)
            if (fields[0] == "Z" or
                    (owner.get("ticks") is not None and fields[19] != str(owner["ticks"])) or
                    (parent is not None and int(fields[1]) != parent) or
                    (group is not None and int(fields[2]) != group) or
                    (owner.get("ticks") is None and parent is None and group is None) or
                    not self.alive()):
                self.close()
        except (ProcessLookupError, FileNotFoundError, PermissionError):
            self.close()
        except BaseException:
            self.close()
            raise

    def alive(self):
        if self.fd is None:
            return False
        poll = select.poll()
        poll.register(self.fd, select.POLLIN)
        return not poll.poll(0)

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def send(self, sig):
        if self.fd is None:
            return False
        try:
            signal.pidfd_send_signal(self.fd, sig)
            return True
        except ProcessLookupError:
            return False

    def capture_members(self):
        """Pin group members while the expected private leader is alive."""
        members = []
        try:
            if not self.alive() or int(stat(self.pid)[2]) != self.pid:
                return []
            for path in Path('/proc').iterdir():
                if not path.name.isdigit() or int(path.name) <= 1 or int(path.name) == self.pid:
                    continue
                member = Target(dict(pid=int(path.name)), group=self.pid)
                if member.fd is not None:
                    members.append(member)
            if self.alive():
                captured, members = members, []
                return captured
            return []
        except (FileNotFoundError, ProcessLookupError):
            return []
        finally:
            for member in members:
                member.close()

    def send_group(self, sig):
        members = self.capture_members()
        try:
            # Pinning is finished: kill the worker before its children can
            # wake its waits and let it publish a successful finalization.
            sent = self.send(sig)
            for member in members:
                member.send(sig)
            return sent
        finally:
            for member in members:
                member.close()


def send(owner, sig, *, group=False):
    target = Target(owner)
    try:
        return target.send_group(sig) if group else target.send(sig)
    finally:
        target.close()


def interrupt(sig):
    """The launcher supplies the target; adoption never selects a new one."""
    value = os.environ["FIXTURE_SIGNAL_TARGET"].split()
    return send(dict(pid=int(value[0]), ticks=value[1]), sig)


def run(command, **kwargs):
    """subprocess.run with an explicit launcher-owned identity handed to exec."""
    read_fd, write_fd = os.pipe()
    try:
        proc = subprocess.Popen([sys.executable, "-S", "-B", __file__, "handoff", str(read_fd), *command],
                                pass_fds=(read_fd,), **{k: v for k, v in kwargs.items() if k != "timeout"})
        owner = identity(proc.pid)  # Popen has not polled or reaped this child.
        os.write(write_fd, f"{owner['pid']} {owner['ticks']}".encode())
    finally:
        os.close(read_fd)
        os.close(write_fd)
    try:
        stdout, stderr = proc.communicate(timeout=kwargs.get("timeout"))
    except BaseException:
        send(owner, signal.SIGKILL)
        proc.communicate()
        raise
    return subprocess.CompletedProcess(command, proc.returncode, stdout, stderr)


def reap_children():
    """As a subreaper, retain every adopted child until its pidfd kill settles."""
    children = Path(f'/proc/self/task/{os.getpid()}/children')
    while pids := children.read_text().split():
        for value in pids:
            pid = int(value)
            # No other thread reaps: each identity belongs to our child
            # until waitpid below, including orphans of nested sessions.
            send(identity(pid), signal.SIGKILL)
            os.waitpid(pid, 0)


def supervise(directory, command):
    """Keep the session leader alive through child failure and orphan cleanup."""
    assert ctypes.CDLL(None).prctl(36, 1, 0, 0, 0) == 0, 'cannot become fixture subreaper'
    stopping = 0
    child_target = None

    def stop(signum, frame):
        nonlocal stopping
        stopping = signum
        if child_target is not None:
            child_target.send(signum)

    # Caught dispositions reset on exec, so the child gets default signals.
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, stop)
    if directory != '-':
        owner = identity(os.getpid())
        publish(Path(directory) / (str(owner['pid']) + '.identity'),
                str(owner['pid']) + ' ' + owner['ticks'])
        # The gate records cancellation before attempting any signal. Even
        # a supervisor not yet started at that instant must refuse its suite.
        if (Path(directory) / 'stop-requested').exists():
            return 143
    if stopping:
        return 128 + stopping
    try:
        child = subprocess.Popen(command)
        child_target = Target(identity(child.pid))
        if stopping:
            child_target.send(stopping)
        status = child.wait()
    finally:
        target, child_target = child_target, None
        if target is not None:
            target.close()
        reap_children()
    return status if status >= 0 else 128 - status


def main():
    mode, *args = sys.argv[1:]
    if mode == "supervise":
        sys.exit(supervise(args[0], args[1:]))
    elif mode == "handoff":
        fd = int(args.pop(0))
        value = os.read(fd, 128).decode()
        os.close(fd)
        if not value:
            sys.exit("fixture launcher disappeared before handoff")
        os.environ["FIXTURE_SIGNAL_TARGET"] = value
        os.execvpe(args[0], args, os.environ)
    elif mode == "record-exec":
        directory = Path(args.pop(0))
        owner = identity(os.getpid())
        publish(directory / str(owner["pid"]), str(owner["pid"]) + " " + owner["ticks"])
        os.execvpe(args[0], args, os.environ)
    elif mode in ("send", "alive"):
        path, *rest = args
        try:
            pid, ticks = Path(path).read_text().split()
        except FileNotFoundError:
            sys.exit(1 if mode == 'alive' else 0)
        owner = dict(pid=int(pid), ticks=ticks)
        if mode == 'alive':
            target = Target(owner)
            try:
                sys.exit(0 if target.alive() else 1)
            finally:
                target.close()
        sig, *flags = rest
        send(owner, getattr(signal, 'SIG' + sig), group=flags == ['group'])
    else:
        sys.exit("unknown fixture signal operation")


if __name__ == "__main__":
    main()
