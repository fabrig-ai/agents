#!/usr/bin/env python3
"""Local slot maintenance protocol (tools/slots/design.md, 5.1–5.4).

The flock excludes maintenance; durable holds survive loss of the supervisor.
No process absence, released flock, or report text clears a durable hold.
"""

import os
import sys

sys.dont_write_bytecode = True


def checked_path_text(path, *, collapse=True):
    """Check supplied components, including those later cancelled by dot-dot."""
    supplied = os.fspath(path)
    if not os.path.isabs(supplied):
        supplied = os.path.join(os.getcwd(), supplied)
    prefix = os.path.sep
    for component in supplied.split(os.path.sep):
        prefix = os.path.join(prefix, component)
        if os.path.islink(prefix):
            raise RuntimeError(f"symlink path: {prefix}")
    if not collapse:
        return supplied
    return os.path.sep + os.path.abspath(supplied).lstrip(os.path.sep)


def slot_text(directory, home=None):
    home = checked_path_text(home or os.path.expanduser("~"))
    root = os.path.join(home, "src/fabrig/slots")
    supplied = checked_path_text(directory)
    if not supplied.startswith(root + os.path.sep):
        return None
    number = supplied[len(root) + 1:].split(os.path.sep)[0]
    if not number.isascii() or not number.isdecimal():
        return None
    slot = os.path.join(root, number)
    if not os.path.isdir(slot):
        raise RuntimeError(f"not a slot directory: {slot}")
    return slot


def protected_text(path, home=None):
    path = checked_path_text(path)
    slot = slot_text(path, home)
    if slot is not None:
        target = os.path.join(slot, "target")
        if path == target or path.startswith(target + os.path.sep):
            raise RuntimeError(f"protected evidence overlaps target: {path}")
    return path


def history_root_text(path):
    path = checked_path_text(path)
    protected_text(os.path.join(path, "tmp/codex-run"))
    return path


def directory_text(path):
    directory = checked_path_text(path)
    membership = "slot" if slot_text(directory) is not None else "other"
    return f"{directory}\n{membership}"


def task_paths(root, report, directory):
    """Validate one launcher entrance together, without caching across execs."""
    root = history_root_text(root)
    report = protected_text(report)
    directory = checked_path_text(directory)
    membership = "slot" if slot_text(directory) is not None else "other"
    return root, report, directory, membership


def worker_paths(root, identifier):
    """Validate history before loading one worker's metadata and directory."""
    root = history_root_text(root)
    with open(root + "/tmp/codex-run/" + identifier + "/meta", "rb") as source:
        metadata = source.read().replace(b"\0", b"")
    directory = ""
    # Match `while IFS='=' read -r key value`: NULs are ignored, the final
    # unterminated line is not read, and the last complete dir field wins.
    for line in metadata.split(b"\n")[:-1]:
        key, _, value = line.partition(b"=")
        if key == b"dir":
            # A lone final delimiter terminates the second field; further
            # delimiters belong to its remaining text.
            if value.endswith(b"=") and value.count(b"=") == 1:
                value = value[:-1]
            directory = os.fsdecode(value)
    directory = checked_path_text(directory)
    membership = "slot" if slot_text(directory) is not None else "other"
    return root, metadata, directory, membership


def no_links(path):
    return Path(checked_path_text(path, collapse=False))


def canonical(path):
    return Path(checked_path_text(path))


def protected_output(path, home=None):
    return Path(protected_text(path, home))


def slot_path(directory, home=None):
    """Map any cwd within a numeric slot; other checkouts need no slot lease."""
    slot = slot_text(directory, home)
    return None if slot is None else Path(slot)


# Path validation needs only filesystem metadata; supervisor imports belong to
# commands that hold lifetimes, keeping repeated launcher validation inexpensive.
PATH_MODES = {"canonical": checked_path_text, "protect": protected_text,
              "root": history_root_text, "directory": directory_text}

if (__name__ == "__main__" and len(sys.argv) > 1
        and (sys.argv[1] in PATH_MODES or sys.argv[1] in ("task-paths", "worker-paths"))):
    os.umask(0o077)
    try:
        if sys.argv[1] == "worker-paths":
            if len(sys.argv) != 4:
                raise RuntimeError("worker path validation requires root and run identifier")
            sys.stdout.buffer.write(b"\0".join(os.fsencode(value) for value in worker_paths(*sys.argv[2:])) + b"\0")
        elif sys.argv[1] == "task-paths":
            if len(sys.argv) != 5:
                raise RuntimeError("task path validation requires root, report and directory")
            # Publish only after every check succeeds. NUL preserves path newlines.
            sys.stdout.write("\0".join(task_paths(*sys.argv[2:])) + "\0")
        else:
            if len(sys.argv) != 3:
                raise RuntimeError("path validation requires exactly one path")
            print(PATH_MODES[sys.argv[1]](sys.argv[2]))
        sys.exit(0)
    except (OSError, ValueError, RuntimeError) as error:
        sys.exit(f"slot lifetime: {error}")


from pathlib import Path
from contextlib import contextmanager
import fcntl
import hashlib
import json
import stat



def identity(path):
    no_links(path)
    info = path.lstat()
    return [info.st_dev, info.st_ino]


def private_directory(path):
    no_links(path)
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.stat()
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise RuntimeError(f"state directory must be owned mode 0700: {path}")


def sync(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write(path, value):
    import tempfile

    no_links(path)
    fd, temporary = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as output:
            json.dump(value, output, sort_keys=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        sync(path.parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def fingerprint(path):
    no_links(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as source:
        first = os.fstat(source.fileno())
        if not stat.S_ISREG(first.st_mode) or first.st_uid != os.getuid():
            raise RuntimeError(f"not an owned regular file: {path}")
        digest = hashlib.file_digest(source, "sha256").hexdigest()
        last = os.fstat(source.fileno())
    key = lambda s: [s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns]
    if key(first) != key(last) or key(last) != key(path.lstat()):
        raise RuntimeError(f"file changed while inspecting: {path}")
    return {"path": str(path), "identity": key(last), "sha256": digest}


def read(path):
    before = fingerprint(path)
    if stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise RuntimeError(f"state file must be mode 0600: {path}")
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise RuntimeError(f"state must be a JSON object: {path}")
    if fingerprint(path) != before:
        raise RuntimeError(f"state changed: {path}")
    return value


@contextmanager
def locked(path, exclusive=True, *, wait=False):
    no_links(path)
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1):
            raise RuntimeError(f"unsafe lock: {path}")
        try:
            fcntl.flock(fd, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | (0 if wait else fcntl.LOCK_NB))
        except BlockingIOError as error:
            raise RuntimeError(f"slot maintenance lease busy: {path}") from error
        if identity(path) != [info.st_dev, info.st_ino]:
            raise RuntimeError(f"lock replaced: {path}")
        yield fd
    finally:
        os.close(fd)


def state_root(home):
    root = Path(home) / "src/fabrig/slot-maintenance"
    private_directory(root)
    return root


def read_completed(directory, slot):
    import time

    path = directory / "completed.json"
    no_links(path)
    if not path.exists():
        return None
    record = read(path)
    timestamp, token = record.get("completed_ns"), record.get("token")
    if (record.get("slot") != str(slot) or record.get("identity") != identity(slot)
            or type(timestamp) is not int or not 0 < timestamp <= time.time_ns()
            or not isinstance(token, str) or len(token) != 32
            or any(c not in "0123456789abcdef" for c in token)
            or not isinstance(record.get("purpose"), str) or not record["purpose"].strip()):
        raise RuntimeError("unknown completed lifetime identity/time")
    return record


def completed_lifetime(directory, slot, token, purpose):
    """Publish completion before removing ownership, serializing shared holders."""
    import time

    with locked(directory / "completion.lock", wait=True):
        previous = read_completed(directory, slot)
        completed = max(time.time_ns(), previous["completed_ns"] if previous else 0)
        write(directory / "completed.json", {"slot": str(slot), "identity": identity(slot),
                                             "completed_ns": completed, "token": token,
                                             "purpose": purpose})


class Lease:
    def __init__(self, slot, home=None):
        self.home = Path(home or Path.home())
        self.slot = slot_path(slot, self.home)
        self.fd = None
        self.clean = False

    def __enter__(self):
        import uuid

        if self.slot is None:
            return self
        self.directory = state_root(self.home) / self.slot.name
        private_directory(self.directory)
        self.lock = locked(self.directory / "lease", exclusive=False)
        self.fd = self.lock.__enter__()
        self.token = uuid.uuid4().hex
        self.hold = self.directory / (self.token + ".hold")
        write(self.hold, {"slot": str(self.slot), "identity": identity(self.slot),
                          "pid": os.getpid(), "purpose": "source/build lifetime"})
        # Any command using a slot invalidates the prior report acknowledgement.
        ack = self.directory / "ack.json"
        no_links(ack)
        if ack.exists():
            ack.unlink(missing_ok=True)
            sync(self.directory)
        return self

    def adopt(self, token):
        if not token or self.slot is None:
            return
        if len(token) != 32 or any(c not in "0123456789abcdef" for c in token):
            raise RuntimeError("invalid launch hold token")
        path = self.directory / (token + ".hold")
        record = read(path)
        if record["slot"] != str(self.slot) or record["identity"] != identity(self.slot):
            raise RuntimeError("launch hold slot identity mismatch")
        path.unlink()
        sync(self.directory)

    def __exit__(self, kind, value, traceback):
        if self.fd is None:
            return
        try:
            if (self.clean and kind is None and self.hold.exists()
                    and not read(self.hold).get("uncertain")):
                if read(self.hold)["identity"] != identity(self.slot):
                    raise RuntimeError("slot replaced during lifetime")
                completed_lifetime(self.directory, self.slot, self.token, "source/build lifetime")
                self.hold.unlink()
                sync(self.directory)
        finally:
            self.lock.__exit__(kind, value, traceback)


def inherited(slot):
    """Validate the inherited open lease, rather than trusting an env sentinel."""
    try:
        fd = int(os.environ["FABRIG_SLOT_LEASE_FD"])
        token = os.environ["FABRIG_SLOT_HOLD"]
        directory = state_root(Path.home()) / slot.name
        if identity(directory / "lease") != [os.fstat(fd).st_dev, os.fstat(fd).st_ino]:
            return False
        record = read(directory / (token + ".hold"))
        return record["slot"] == str(slot) and record["identity"] == identity(slot)
    except (KeyError, ValueError, OSError, RuntimeError):
        return False


def main():
    os.umask(0o077)
    # Descriptor verification needs no command parser or child-process modules.
    if (len(sys.argv) == 3 and sys.argv[1] == "verify"
            and not sys.argv[2].startswith("-")):
        slot = slot_path(Path(sys.argv[2]))
        return 0 if slot is None or inherited(slot) else 1

    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("run", "launch", "verify", "uncertain", *PATH_MODES))
    parser.add_argument("directory", type=Path)
    parser.add_argument("--adopt", default="")
    args, command = parser.parse_known_args()
    if args.mode in PATH_MODES:
        print(PATH_MODES[args.mode](args.directory))
        return 0
    slot = slot_path(args.directory)
    if args.mode == "verify":
        return 0 if slot is None or inherited(slot) else 1
    if args.mode == "uncertain":
        if slot is None:
            return 0
        if not inherited(slot):
            raise RuntimeError("cannot mark uncertainty without an inherited lease")
        hold = state_root(Path.home()) / slot.name / (os.environ["FABRIG_SLOT_HOLD"] + ".hold")
        write(hold, {**read(hold), "uncertain": True})
        return 0
    import signal
    import subprocess

    if command[:1] == ["--"]:
        command = command[1:]
    if not command:
        parser.error("a foreground command is required after --")
    with Lease(args.directory) as lease:
        lease.adopt(args.adopt)
        env = dict(os.environ)
        descriptors = ()
        if lease.fd is not None:
            env.update(FABRIG_SLOT_LEASE_FD=str(lease.fd), FABRIG_SLOT_HOLD=lease.token,
                       FABRIG_SLOT_LEASE_MODE=args.mode)
            descriptors = (lease.fd,)
        # Signals leave a durable hold, including when children outlive this wrapper.
        def interrupted(number, frame):
            raise RuntimeError(f"interrupted by {number}; ownership remains uncertain")
        for number in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            signal.signal(number, interrupted)
        child = subprocess.Popen(command, env=env, pass_fds=descriptors,
                                 stdin=subprocess.DEVNULL)
        code = child.wait()
        lease.clean = code == 0 and args.mode != "launch"
        return code if code >= 0 else 128 - code


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, RuntimeError) as error:
        sys.exit(f"slot lifetime: {error}")
