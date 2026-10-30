"""Explicit finality against the launcher's private services and temporary HOME."""

import fcntl
import datetime
from contextlib import contextmanager
import importlib.util
import json
import os
import resource
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace


fixture, kit, recipient_run = sys.argv[1:]
fixture, kit = Path(fixture), Path(kit)
root = fixture / "workspace"
runs = root / "tmp/codex-run"
fake = root / "fake"
launcher = kit / "codex-run"
owner = "o/recipient"
sha = "1234567890abcdef1234567890abcdef12345678"
checks = 0


def cpu_usage():
    own = resource.getrusage(resource.RUSAGE_SELF)
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    return own.ru_utime + own.ru_stime + children.ru_utime + children.ru_stime


initial_cpu = cpu_usage()


def check(condition, label):
    global checks
    assert condition, label
    checks += 1


def run(name, callback="", ended=True):
    directory = runs / name
    directory.mkdir(mode=0o700)
    (directory / "meta").write_text(f"to={owner}\non_stop={callback}\n")
    if ended:
        (directory / "ended").touch(mode=0o600)
    return directory


def call(directory, *args, status=0, declared_owner=owner):
    result = subprocess.run([str(launcher), "final", directory.name, "--owner", declared_owner, *args],
                            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    check(result.returncode == status, (directory.name, args, result.returncode, result.stderr))
    return result


def snapshot(path):
    info = path.stat()
    return path.read_bytes(), info.st_ino, info.st_mtime_ns, info.st_ctime_ns


# Use the distinct caller/recipient run from the launcher fixture: final owner
# must agree with its start record, never the launching caller.
directory = runs / recipient_run
call(directory, "--withdrawn", "report-read")
check(json.loads((directory / "final.json").read_text())["owner"] == owner, "recipient owns final")
entries = [json.loads(line) for line in (fake / "reap.calls").read_text().splitlines()]
check(any(row["args"] == ["record", "end", "--kind", "codex-run", "--owner", owner,
                         "--id", recipient_run] for row in entries), "end includes recipient owner")

directory = run("final-landed")
call(directory, "--landed", sha)
marker = directory / "final.json"
record = json.loads(marker.read_text())
check(set(record) == {"state", "sha", "owner", "time"} and record["state"] == "landed"
      and record["sha"] == sha and record["owner"] == owner, "landed schema")
before = snapshot(marker)
notifications = (fake / "reap.calls").read_bytes()
call(directory, "--landed", sha)
check(snapshot(marker) == before, "repeat preserves exact bytes, inode, mtime and ctime")
check((fake / "reap.calls").read_bytes() == notifications, "repeat does not reset end notification time")
for args in [("--landed", "a" * 40), ("--withdrawn", "changed"),
             ("--landed", sha, "--withdrawn", "also"), ("--landed", "short"),
             ("--withdrawn", "   ")]:
    call(directory, *args, status=2)
    check(snapshot(marker) == before, "conflict leaves existing marker untouched")
call(directory, "--landed", sha, status=2, declared_owner="o/other")
check(snapshot(marker) == before, "owner mismatch leaves marker untouched")
(directory / "meta").write_text("to=o/reassigned\non_stop=\n")
call(directory, "--landed", sha, status=2, declared_owner="o/reassigned")
check(snapshot(marker) == before, "existing final owner cannot be reassigned")
(directory / "meta").write_text(f"to={owner}\non_stop=\n")
(fake / "final-liveness").write_text("active")
call(directory, "--landed", sha, status=2)
check(snapshot(marker) == before, "even identical input cannot finalize active run")
(fake / "final-liveness").unlink()

directory = run("final-withdrawn")
reason = 'owner read: spaces, "quotes", λ\nand a second line'
call(directory, "--withdrawn", reason)
check(json.loads((directory / "final.json").read_text())["reason"] == reason, "reason argv preserved")
directory = run("final-sha256")
call(directory, "--landed", "ab" * 32)
directory = run("final-read-only")
with (directory / "meta").open("a") as stream:
    stream.write("read_only=1\n")
check(not (directory / "final.json").exists(), "read-only completion is not finality")
call(directory, "--withdrawn", "report-read")
check(json.loads((directory / "final.json").read_text())["reason"] == "report-read", "review owner declaration")

for mode in ("active", "unknown", "malformed", "hang"):
    directory = run("final-liveness-" + mode)
    (fake / "final-liveness").write_text(mode)
    call(directory, "--withdrawn", "report-read", status=2)
    check(not (directory / "final.json").exists(), "unsafe liveness cannot publish")
(fake / "final-liveness").write_text("gone")
directory = run("final-collected")
call(directory, "--withdrawn", "report-read")
(fake / "final-liveness").unlink()

directory = run("final-running-lock")
with (directory / "meta").open() as meta:
    fcntl.flock(meta, fcntl.LOCK_SH | fcntl.LOCK_NB)
    call(directory, "--withdrawn", "report-read", status=2)
check(not (directory / "final.json").exists(), "worker lock prevents false inactive observation")
directory = run("final-unknown-completion", ended=False)
call(directory, "--withdrawn", "report-read", status=2)
directory = run("final-uncertain-stop", callback="/not/read/or/executed")
(directory / "on-stop").write_text("exit 3\n")
call(directory, "--withdrawn", "report-read", status=2)
check(not (directory / "final.json").exists(), "uncertain stop remains protected")

directory = run("final-unsafe")
for name, target in [("final.json", fixture / "task file.md"), ("meta", fixture / "task file.md")]:
    path = directory / name
    original = path.read_bytes() if path.exists() else None
    path.unlink(missing_ok=True)
    path.symlink_to(target)
    target_before = snapshot(target)
    call(directory, "--withdrawn", "report-read", status=2)
    check(snapshot(target) == target_before, "symlink target untouched")
    path.unlink()
    if original is not None:
        path.write_bytes(original)
(runs / "final-link").symlink_to(directory, target_is_directory=True)
call(runs / "final-link", "--withdrawn", "report-read", status=2)
call(runs / "..", "--withdrawn", "report-read", status=2)
directory.chmod(0o755)
call(directory, "--withdrawn", "report-read", status=2)
directory.chmod(0o700)
(directory / "meta").chmod(0o644)
call(directory, "--withdrawn", "report-read", status=2)
(directory / "meta").chmod(0o600)
os.link(directory / "meta", directory / "meta-link")
call(directory, "--withdrawn", "report-read", status=2)
(directory / "meta-link").unlink()

# Interrupt the publication boundary after file fsync, before atomic rename.
# This is an I/O fault in the production helper, with no runtime test switch.
spec = importlib.util.spec_from_file_location("finality", kit / "final.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

# The consumer parses ISO timestamps into timezone-aware Python datetimes.
# Keep both clocks deterministic while reproducing a fractional same-second end.
real_datetime = datetime.datetime
epoch = real_datetime(2026, 10, 30, 11, 20, 30, tzinfo=datetime.timezone.utc)
epoch_ns = int(epoch.timestamp()) * 1_000_000_000
timestamp_cpu_start = cpu_usage()


@contextmanager
def replace_attribute(target, name, value):
    original = getattr(target, name)
    setattr(target, name, value)
    try:
        yield
    finally:
        setattr(target, name, original)


@contextmanager
def clock(instant_ns):
    class FixedDateTime(real_datetime):
        @classmethod
        def now(cls, tz=None):
            seconds, fraction = divmod(instant_ns, 1_000_000_000)
            instant = real_datetime.fromtimestamp(seconds, datetime.timezone.utc).replace(
                microsecond=fraction // 1000)
            return instant.astimezone(tz) if tz is not None else instant.replace(tzinfo=None)

    # Unit liveness is covered by the CLI fixtures. Timestamp-only declarations
    # retain production file/lock/publication behavior without another manager.
    with replace_attribute(module, "inactive", lambda *_: None), \
            replace_attribute(module.time, "time_ns", lambda: instant_ns), \
            replace_attribute(module.datetime, "datetime", FixedDateTime):
        yield


def completion(directory, instant_ns):
    os.utime(directory / "ended", ns=(instant_ns, instant_ns))
    check((directory / "ended").stat().st_mtime_ns == instant_ns, "fractional completion fixture exact")


directory = run("final-same-second")
ended_ns = epoch_ns + 750_000_000
now_ns = epoch_ns + 900_000_000
completion(directory, ended_ns)
with clock(now_ns):
    check(module.declare(str(root), directory.name, owner, "withdrawn", "report-read", "1") == "created",
          "same-second declaration publishes")
record = json.loads((directory / "final.json").read_text())
parsed = real_datetime.fromisoformat(record["time"].replace("Z", "+00:00"))
check(record["time"] == "2026-10-30T11:20:30.900000Z", "same-second UTC precision")
check(parsed.tzinfo is not None and parsed >= real_datetime.fromtimestamp(
    (directory / "ended").stat().st_mtime, datetime.timezone.utc) and
    parsed <= real_datetime(2026, 10, 30, 11, 20, 30, 900000, tzinfo=datetime.timezone.utc),
    "consumer accepts time at or after completion and not in the future")
before = snapshot(directory / "final.json")
notifications = (fake / "reap.calls").read_bytes()
with clock(now_ns):
    check(module.declare(str(root), directory.name, owner, "withdrawn", "report-read", "1") == "existing",
          "same-second identical repeat accepted")
call(directory, "--withdrawn", "report-read")
check(snapshot(directory / "final.json") == before and
      (fake / "reap.calls").read_bytes() == notifications,
      "same-second repeat preserves bytes, inode, mtime, ctime, JSON time and notifications")

for name, ended_offset, now_offset in (
        ("clock-before-end", 750_000_000, 700_000_000),
        ("precision-insufficient", 750_000_001, 750_000_999)):
    directory = run("final-" + name)
    completion(directory, epoch_ns + ended_offset)
    with clock(epoch_ns + now_offset):
        try:
            module.declare(str(root), directory.name, owner, "withdrawn", "report-read", "1")
        except ValueError:
            pass
        else:
            raise AssertionError(name + " published invalid finality")
    check(not (directory / "final.json").exists(), name + " refuses without manufacturing future time")

for name, ended_offset, marker_time, accepted in (
        ("legacy-valid", -250_000_000, "2026-10-30T11:20:30Z", True),
        ("legacy-before-end", 750_000_000, "2026-10-30T11:20:30Z", False),
        ("fraction-before-end", 750_000_000, "2026-10-30T11:20:30.749999Z", False),
        ("future", 750_000_000, "2026-10-30T11:20:30.900001Z", False)):
    directory = run("final-time-" + name)
    completion(directory, epoch_ns + ended_offset)
    marker = directory / "final.json"
    marker.write_text(json.dumps({"state": "withdrawn", "reason": "report-read", "owner": owner,
                                  "time": marker_time}) + "\n")
    before = snapshot(marker)
    with clock(now_ns):
        try:
            result = module.declare(str(root), directory.name, owner, "withdrawn", "report-read", "1")
        except ValueError:
            check(not accepted, name + " refuses invalid immutable evidence")
        else:
            check(accepted and result == "existing", name + " accepts only valid ordering")
    check(snapshot(marker) == before, name + " leaves immutable evidence untouched")
    if name == "legacy-before-end":
        notifications = (fake / "reap.calls").read_bytes()
        call(directory, "--withdrawn", "report-read", status=2)
        check(snapshot(marker) == before and (fake / "reap.calls").read_bytes() == notifications,
              "invalid legacy CLI repeat refuses without repair or renotification")

timestamp_cpu = cpu_usage() - timestamp_cpu_start
try:
    module.private(SimpleNamespace(st_mode=0o100600, st_uid=os.geteuid() + 1, st_nlink=1))
except ValueError:
    check(True, "foreign owner refused without root fixture operations")
else:
    raise AssertionError("foreign owner accepted")
directory = run("final-interrupted")
fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)


def interrupt_install(*args):
    raise KeyboardInterrupt


try:
    with replace_attribute(module, "install", interrupt_install):
        try:
            module.publish(fd, {"state": "withdrawn", "reason": "report-read", "owner": owner})
        except KeyboardInterrupt:
            pass
        else:
            raise AssertionError("publication interrupt not exercised")
    check(not (directory / "final.json").exists() and not list(directory.glob(".final-*")),
          "interrupted publication exposes no marker or partial bytes")
finally:
    os.close(fd)
call(directory, "--withdrawn", "report-read")
before = snapshot(directory / "final.json")
fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
try:
    try:
        module.publish(fd, {"state": "withdrawn", "reason": "competing"})
    except FileExistsError:
        pass
    else:
        raise AssertionError("competing atomic publication replaced a marker")
    check(snapshot(directory / "final.json") == before, "atomic install never replaces an existing marker")
finally:
    os.close(fd)

# Every new final remains durable despite optional notification failure. Liveness
# remains available; the disappear story removes systemctl only after its reply.
for fault in ("missing-reap", "broken-reap", "hanging-reap", "missing-unit", "broken-unit", "hanging-unit"):
    directory = run("final-notify-" + fault)
    if fault == "missing-reap":
        (fixture / "bin/reap").rename(fixture / "reap.saved")
    elif fault.endswith("reap"):
        (fake / "reap-mode").write_text("hang" if fault.startswith("hanging") else "broken")
    elif fault == "missing-unit":
        (fake / "final-liveness").write_text("disappear")
    else:
        (fake / "unit-mode").write_text("hang" if fault.startswith("hanging") else "broken")
    call(directory, "--withdrawn", "report-read")
    before = snapshot(directory / "final.json")
    for name in ("reap-mode", "unit-mode", "final-liveness"):
        (fake / name).unlink(missing_ok=True)
    if (fixture / "reap.saved").exists():
        (fixture / "reap.saved").rename(fixture / "bin/reap")
    if (fixture / "bin/systemctl.saved").exists():
        (fixture / "bin/systemctl.saved").rename(fixture / "bin/systemctl")
    call(directory, "--withdrawn", "report-read")
    check(snapshot(directory / "final.json") == before, "failed notification cannot reset final time")

# Run completion and resume leave all nondeclared runs without a final marker.
check(all(not (path / "final.json").exists() for path in runs.iterdir()
          if path.is_dir() and path.name.startswith("20") and path.name != recipient_run),
      "ordinary and resumed runs remain unfinalized")
print(checks)
print(f'finality CPU: timestamps={timestamp_cpu:.3f}s total={cpu_usage() - initial_cpu:.3f}s', file=sys.stderr)
