"""Owner-declared task finality (tools/codex-run/design.md, 3.2).

Only metadata and completion/stop evidence inside the named run are read.
Unit state is a liveness check, never evidence that a task landed.
"""

import datetime
import fcntl
import os
import re
import stat
import sys
import time


def private(info, directory=False):
    kind = stat.S_ISDIR if directory else stat.S_ISREG
    mode = 0o700 if directory else 0o600
    if (not kind(info.st_mode) or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) != mode
            or (not directory and info.st_nlink != 1)):
        raise ValueError("run evidence must be private, owned and without hard links")


def open_directory(path):
    """Walk descriptors so symlinks, including cancelled components, refuse."""
    if not path.startswith("/"):
        raise ValueError("run root must be absolute")
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.split("/"):
            if not part:
                continue
            if part in (".", ".."):
                raise ValueError("unsafe run path component")
            following = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = following
        return fd
    except BaseException:
        os.close(fd)
        raise


def read_private(directory, name, with_info=False):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    try:
        info = os.fstat(fd)
        private(info)
        with os.fdopen(fd, "r", encoding="utf-8", closefd=False) as stream:
            contents = stream.read()
            return (contents, info) if with_info else contents
    finally:
        os.close(fd)


def inactive(identifier, seconds):
    import subprocess

    result = subprocess.run(
        ["timeout", "--signal=KILL", seconds, "systemctl", "--user", "list-units",
         "--all", "--plain", "--no-legend", "--no-pager", "--full",
         "--", "codex-run-" + identifier + ".service"], stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if result.returncode != 0:
        raise ValueError("unit liveness is unknown")
    lines = result.stdout.decode("utf-8").splitlines()
    # A successful exact-unit enumeration also proves absence after --collect.
    if not lines:
        return
    fields = lines[0].split()
    if (len(lines) != 1 or len(fields) < 4
            or fields[0] != "codex-run-" + identifier + ".service"
            or tuple(fields[1:4]) not in {("loaded", "inactive", "dead"), ("loaded", "failed", "failed")}):
        raise ValueError("unit is active or its liveness is unknown")


def install(directory, name):
    """Linux renameat2 RENAME_NOREPLACE preserves any competing marker."""
    import ctypes

    libc = ctypes.CDLL(None, use_errno=True)
    rename = libc.renameat2
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(directory, os.fsencode(name), directory, b"final.json", 1) != 0:
        number = ctypes.get_errno()
        raise OSError(number, os.strerror(number))


def publish(directory, record):
    """Publish complete synced bytes atomically, without replacing any marker."""
    import json
    import secrets

    name = ".final-" + secrets.token_hex(12)
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                 0o600, dir_fd=directory)
    try:
        data = (json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
        while data:
            written = os.write(fd, data)
            if not written:
                raise OSError("short final marker write")
            data = data[written:]
        os.fsync(fd)
        install(directory, name)
        os.fsync(directory)
    finally:
        os.close(fd)
        try:
            os.unlink(name, dir_fd=directory)
        except FileNotFoundError:
            pass
        os.fsync(directory)


def validate_time(value, ended_ns, now_ns):
    """Use the consumer's datetime precision, then compare integer nanoseconds."""
    if not isinstance(value, str) or not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?Z", value):
        raise ValueError("invalid final UTC time")
    parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    elapsed = parsed - datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc)
    parsed_ns = ((elapsed.days * 86400 + elapsed.seconds) * 1_000_000_000
                 + elapsed.microseconds * 1000)
    if not ended_ns <= parsed_ns <= now_ns:
        raise ValueError("final time must not precede completion or be in the future")


def declare(root, identifier, owner, disposition, content, seconds):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", identifier):
        raise ValueError("unsafe run identity")
    if disposition == "landed":
        if not re.fullmatch(r"(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})", content) or set(content) == {"0"}:
            raise ValueError("landed requires a full nonzero commit OID")
        declaration = {"state": disposition, "sha": content.lower(), "owner": owner}
    elif disposition == "withdrawn" and content.strip():
        declaration = {"state": disposition, "reason": content, "owner": owner}
    else:
        raise ValueError("withdrawn requires a nonempty reason")
    parent = open_directory(root + "/tmp/codex-run")
    try:
        private(os.fstat(parent), directory=True)
        directory = os.open(identifier, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
    finally:
        os.close(parent)
    metadata = None
    try:
        private(os.fstat(directory), directory=True)
        metadata = os.open("meta", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        private(os.fstat(metadata))
        fcntl.flock(metadata, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with os.fdopen(metadata, "r", encoding="utf-8", closefd=False) as stream:
            lines = stream.read().splitlines()
        owners = [line.removeprefix("to=") for line in lines if line.startswith("to=")]
        if owners != [owner]:
            raise ValueError("final owner must equal the run's recorded recipient")
        # Completion evidence is required for safe liveness, not task finality.
        _, ended_info = read_private(directory, "ended", with_info=True)
        callbacks = [line.removeprefix("on_stop=") for line in lines if line.startswith("on_stop=")]
        if any(callbacks) and read_private(directory, "on-stop") not in ("exit 0\n", "absent\n"):
            raise ValueError("stop outcome remains uncertain")
        inactive(identifier, seconds)
        import json

        try:
            existing = json.loads(read_private(directory, "final.json"))
        except FileNotFoundError:
            existing = None
        if existing is not None:
            if (not isinstance(existing, dict) or set(existing) != set(declaration) | {"time"}
                    or {key: existing[key] for key in declaration} != declaration
                    or not isinstance(existing["time"], str)):
                raise ValueError("conflicting or invalid final marker")
            validate_time(existing["time"], ended_info.st_mtime_ns, time.time_ns())
            # Syncing an existing declaration changes neither its bytes nor times.
            marker = os.open("final.json", os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
            try:
                os.fsync(marker)
            finally:
                os.close(marker)
            os.fsync(directory)
            return "existing"
        now_ns = time.time_ns()
        seconds, fraction = divmod(now_ns, 1_000_000_000)
        declaration["time"] = datetime.datetime.fromtimestamp(seconds, datetime.timezone.utc).replace(
            microsecond=fraction // 1000).isoformat(timespec="microseconds").replace("+00:00", "Z")
        validate_time(declaration["time"], ended_info.st_mtime_ns, now_ns)
        publish(directory, declaration)
        return "created"
    finally:
        if metadata is not None:
            os.close(metadata)
        os.close(directory)


if __name__ == "__main__":
    os.umask(0o077)
    try:
        if len(sys.argv) != 7:
            raise ValueError("invalid final helper invocation")
        print(declare(*sys.argv[1:]))
    except (OSError, ValueError, UnicodeError) as error:
        print("codex-run: " + str(error).replace("\n", " "), file=sys.stderr)
        sys.exit(2)
