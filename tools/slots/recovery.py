"""Whole-target eligibility and observations (tools/slots/design.md, 5)."""

from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import shutil
import shlex
import socket
import stat
import subprocess
import sys
import time
import uuid

sys.dont_write_bytecode = True
L = runpy.run_path(str(Path(__file__).resolve().with_name("lifetime.py")))
no_links, identity = L["no_links"], L["identity"]
canonical = L["canonical"]
read, write, locked = L["read"], L["write"], L["locked"]

# Ops must review FIRSTDAYDRYRUN evidence before changing this gate. There is
# deliberately no environment variable, CLI option or installation default override.
FIRSTDAYDRYRUN = True
CLAIM_SSH_TARGET = "free@204.168.210.29"


def command(*argv):
    result = subprocess.run(argv, text=True, capture_output=True, stdin=subprocess.DEVNULL)
    if result.returncode:
        raise RuntimeError(f"{argv[0]} exited {result.returncode}: {result.stderr.strip()}")
    return result.stdout


def units(slot, *, codex=False):
    evidence = []
    rows = command("systemctl", "--user", "list-units", "--type=service", "--plain",
                   "--no-legend", "--state=active,activating,reloading,deactivating,refreshing")
    for row in rows.splitlines():
        name = row.split()[0]
        heavy = "-heavy-" in name
        is_codex = name.startswith(("codex-run-", "codex-owner-")) or name == "codex-run.service"
        if not name.endswith(".service") or not (heavy or codex and is_codex):
            continue
        # This reserved observer has no build cwd. It is never a payload/wrapper.
        if heavy and name.endswith("-reconcile.service"):
            evidence.append(f"observer {name}")
            continue
        props = dict(line.split("=", 1) for line in command(
            "systemctl", "--user", "show", "-p", "WorkingDirectory,ActiveState,LoadState", name
        ).splitlines() if "=" in line)
        if props.get("ActiveState") in ("inactive", "failed"):
            if props.get("LoadState") in ("loaded", "not-found"):
                evidence.append(f"inactive {name}")
                continue
        if (props.get("LoadState") != "loaded" or props.get("ActiveState") not in
                ("active", "activating", "reloading", "deactivating", "refreshing")):
            raise RuntimeError(f"missing heavy unit properties or unknown service: {name}")
        directory = props.get("WorkingDirectory", "").removeprefix("-")
        if heavy and (not directory or not Path(directory).is_absolute()):
            raise RuntimeError(f"missing heavy unit properties: {name}")
        if directory and Path(directory).is_absolute() and canonical(directory).is_relative_to(slot):
            raise RuntimeError(f"live service {name} cwd={directory}")
        # Codex units have no systemd cwd. Run metadata and /proc are mandatory too.
        if is_codex and codex and not directory:
            run_id = name.removeprefix("codex-run-").removesuffix(".service")
            evidence.append(f"Codex service {name}")
            if name.startswith("codex-owner-"):
                raise RuntimeError(f"owner service without slot cwd cannot be excluded: {name}")
            yield ("run", run_id)
    yield ("evidence", evidence)


def process_class(comm, cgroup, uid):
    """Only protected host parents qualify; shells and task children never do."""
    prefix = f"0::/user.slice/user-{uid}.slice/"
    if comm in ("systemd", "(sd-pam)") and cgroup == prefix + f"user@{uid}.service/init.scope":
        return "user manager"
    if comm == "sshd-session" and re.fullmatch(re.escape(prefix) + r"session-\d+\.scope", cgroup):
        return "SSH session parent"
    return None


def processes(slot, proc=Path("/proc")):
    evidence = []
    uid = os.getuid()
    for entry in proc.iterdir():
        if not entry.name.isdecimal():
            continue
        try:
            if entry.stat().st_uid != uid:
                continue
            try:
                directory = os.readlink(entry / "cwd")
            except PermissionError:
                comm = (entry / "comm").read_text().strip()
                cgroup = (entry / "cgroup").read_text().strip()
                classification = process_class(comm, cgroup, uid)
                if classification:
                    evidence.append(f"protected pid={entry.name} {classification}")
                    continue
                # ssh-agent's service cwd must be explicitly outside the slots root.
                if comm == "ssh-agent" and cgroup.endswith("/app.slice/ssh-agent.service"):
                    props = dict(line.split("=", 1) for line in command(
                        "systemctl", "--user", "show", "-p", "WorkingDirectory,ActiveState,LoadState",
                        "ssh-agent.service").splitlines() if "=" in line)
                    wd = props.get("WorkingDirectory", "").removeprefix("!").removeprefix("-")
                    if (props.get("LoadState") == "loaded" and props.get("ActiveState") == "active"
                            and Path(wd).is_absolute() and not canonical(wd).is_relative_to(slot.parent)):
                        evidence.append(f"protected pid={entry.name} ssh-agent cwd={wd}")
                        continue
                raise RuntimeError(f"unreadable own-user cwd pid={entry.name} comm={comm} cgroup={cgroup}")
            if not directory.startswith("/"):
                raise RuntimeError(f"unknown own-user cwd pid={entry.name}")
            directory = directory.removesuffix(" (deleted)")
            if canonical(directory).is_relative_to(slot):
                raise RuntimeError(f"own-user process pid={entry.name} cwd={directory}")
        except (FileNotFoundError, ProcessLookupError):
            # A vanished process cannot start work; its surviving children are scanned.
            continue
    return [*evidence, "own-user cwd scan completed"]


def builder(slot, home, host=None):
    canonical = L["slot_path"](slot, home)
    if canonical != slot or slot.parent != Path(home) / "src/fabrig/slots":
        raise RuntimeError("whole-target recovery requires an actual numeric slot root")
    host = host or socket.gethostname().split(".")[0]
    actual_hosts = {f"debian-16gb-hel1-{number}": f"hetzner{number}" for number in (3, 6, 7)}
    host = actual_hosts.get(host, host)
    if host not in ("hetzner3", "hetzner6", "hetzner7"):
        raise RuntimeError(f"not a builder: {host}")
    inventory = Path(__file__).with_name("hosts").read_text().splitlines()
    shares = dict(part.split("=", 1) for row in inventory if row.strip() and
                  not row.startswith("#") and row.split()[0] == host for part in row.split()[1:])
    if slot.name not in shares:
        raise RuntimeError(f"slot absent from builder inventory: {host}:{slot.name}")
    return host, shares[slot.name]


def automatic_terminal(task, slot=None):
    if slot is not None and task.get("slot") != str(slot):
        return False
    if task.get("status") == "completed" and task.get("release") == "released":
        return True
    claim, refusal = task.get("claim", {}), task.get("refusal", {})
    return (task.get("status") == "skipped" and task.get("acquired") is False
            and task.get("mutation_started") is False and task.get("release") == "not-acquired"
            and isinstance(claim, dict) and isinstance(refusal, dict)
            and claim.get("owner") == "ops" and claim.get("host") in ("hetzner3", "hetzner6", "hetzner7")
            and isinstance(claim.get("number"), str) and claim["number"].isascii() and claim["number"].isdecimal()
            and known_claim_refusal(claim.get("host"), claim.get("number"), claim.get("share"),
                                    refusal.get("code"), refusal.get("stdout"), refusal.get("stderr")))


@contextmanager
def maintenance(slot, home, *, release_hold=None, automatic_what=None, lock_fds=None):
    directory = L["state_root"](home) / slot.name
    L["private_directory"](directory)
    @contextmanager
    def hold(path):
        with locked(path) as fd:
            entry = {"pid": os.getpid(), "fd": fd, "identity": identity(path), "path": str(path), "active": True}
            if lock_fds is not None:
                lock_fds.append(entry)
            try:
                yield fd
            finally:
                entry["active"] = False
    with ExitStack() as stack:
        stack.enter_context(hold(directory / "lease"))
        for path in directory.iterdir():
            no_links(path)
            if (path.name.endswith(".hold") and release_hold is None or path.name.startswith(".write-")):
                raise RuntimeError(f"durable uncertain/live lifetime: {path}")
            if path.name not in ("lease", "completion.lock", "completed.json", "ack.json", "reclaim.json", "owner-notice.json", "automatic.json") and not re.fullmatch(
                    r"(?:[0-9a-f]{32}\.(?:hold|released\.json)|automatic-[0-9a-f]{32}\.json)", path.name):
                raise RuntimeError(f"unknown maintenance state: {path}")
            if path.suffix == ".json":
                read(path)
        automatic = directory / "automatic.json"
        if automatic.exists():
            task = read(automatic)
            if not automatic_terminal(task, slot):
                if automatic_what is None or task.get("claim", {}).get("what") != automatic_what:
                    raise RuntimeError("automatic claim/task needs operator reconciliation")
        journal = directory / "reclaim.json"
        if journal.exists() and read(journal).get("status") != "completed":
            raise RuntimeError(f"interrupted reclaim needs operator reconciliation: {journal}")
        # The legacy worker uses the sibling worker lock and mq-worker marker.
        gitdir = slot / ".git"
        no_links(gitdir)
        if not gitdir.is_dir():
            raise RuntimeError("recovery requires a standalone .git directory")
        if os.path.lexists(gitdir / "commondir"):
            raise RuntimeError("unsupported Git commondir indirection")
        for path in (slot.with_name(slot.name + ".queue.lock"),
                     slot.with_name(slot.name + ".worker.lock"),
                     gitdir / "worker.lock", gitdir / "precheck.lock"):
            # The sibling locks cover the precheck/worker entrance. Observe an
            # existing legacy inner lock without adding files to source metadata.
            if path.parent == gitdir and not path.exists() and not path.is_symlink():
                continue
            stack.enter_context(hold(path))
        markers = [gitdir / name for name in ("precheck.unresolved", "mq-worker-unresolved.json",
                                              "worker.unresolved", "queue.unresolved", "index.lock")]
        markers.extend(slot.with_name(slot.name + suffix) for suffix in
                       (".precheck.unresolved", ".worker.unresolved", ".queue.unresolved"))
        for path in markers:
            no_links(path)
            if path.exists():
                raise RuntimeError(f"unresolved ownership: {path}")
        yield directory


def evidence_path(path, slot):
    supplied = Path(path)
    if not supplied.is_absolute():
        raise RuntimeError(f"unknown protected evidence path: {path}")
    path = canonical(supplied)
    target = slot / "target"
    if path.is_relative_to(target) or target.is_relative_to(path):
        raise RuntimeError(f"protected evidence overlaps target: {path}")
    return path


def history(slot, home, *, observational=False):
    root = evidence_path(canonical(Path(os.environ.get("DEV_ROOT", str(Path(home) / "src/rust"))) / "tmp/codex-run"), slot)
    if not root.is_dir():
        raise RuntimeError("no trustworthy Codex run history")
    matches, by_id = [], {}
    for run in sorted(root.iterdir()):
        if run.name == "runs.tsv":
            continue
        no_links(run)
        if not run.is_dir():
            raise RuntimeError(f"unknown Codex history entry: {run}")
        meta = run / "meta"
        meta_id = L["fingerprint"](meta)
        values = {}
        for line in meta.read_text().splitlines():
            key, separator, value = line.partition("=")
            if not separator or key in values:
                raise RuntimeError(f"corrupt run metadata: {meta}")
            values[key] = value
        supplied = Path(values.get("dir", ""))
        if not supplied.is_absolute():
            raise RuntimeError(f"unknown run directory: {run}")
        directory = canonical(supplied)
        # Report protection applies to every run, including a different slot's.
        report = evidence_path(values["report"], slot)
        if L["fingerprint"](meta) != meta_id:
            raise RuntimeError(f"run changed: {run}")
        by_id[run.name] = directory
        if not directory.is_relative_to(slot):
            continue
        started = datetime.fromisoformat(values["started"].replace("Z", "+00:00"))
        if started.utcoffset() is None:
            raise RuntimeError(f"unknown start time: {run}")
        ended = L["fingerprint"](run / "ended")
        report_id = L["fingerprint"](report)
        if ended["identity"][3] < int(started.timestamp() * 1e9):
            raise RuntimeError(f"completion predates start: {run}")
        if ended["identity"][3] > time.time_ns():
            raise RuntimeError(f"completion time is in the future: {run}")
        if L["fingerprint"](meta) != meta_id:
            raise RuntimeError(f"run changed: {run}")
        matches.append({"id": run.name, "meta": meta_id, "ended": ended, "report": report_id,
                        "started": values["started"], "owner": values["to"]})
    if not matches:
        raise RuntimeError("no completed slot run; old slots require explicit evidence")
    latest = max(matches, key=lambda run: (run["started"], run["id"]))
    completed = max(run["ended"]["identity"][3] for run in matches)
    lifetime = None
    # Observation must not create maintenance state or imply lease ownership.
    state = Path(home) / "src/fabrig/slot-maintenance" if observational else L["state_root"](home)
    completion = state / slot.name / "completed.json"
    record = L["read_completed"](completion.parent, slot)
    if record is not None:
        lifetime = {"record": record, "file": L["fingerprint"](completion)}
        completed = max(completed, record["completed_ns"])
    return {"runs": matches, "latest": latest["id"], "owner": latest["owner"],
            "completed_lifetime": lifetime, "completed_ns": completed}, by_id


def target_identity(slot):
    target = slot / "target"
    no_links(target)
    if not target.is_dir() or target.stat().st_dev != slot.stat().st_dev:
        raise RuntimeError("target absent, not a directory, or on another device")
    return identity(target)


def snapshot(slot, home, *, observational=False):
    host, share = builder(slot, home)
    history_value, runs = history(slot, home, observational=observational)
    evidence = []
    for kind, value in units(slot, codex=True):
        if kind == "run":
            if value not in runs:
                raise RuntimeError(f"live Codex unit with unknown run: {value}")
            if runs[value].is_relative_to(slot):
                raise RuntimeError(f"live Codex run: {value}")
        else:
            evidence.extend(value)
    evidence.extend(processes(slot))
    return {"slot": str(slot), "slot_identity": identity(slot), "target_identity": target_identity(slot),
            "root_identity": identity(slot.parent), "host": host, "share": share,
            "head": L["fingerprint"](slot / ".git/HEAD"), "history": history_value}, evidence


def acknowledge(number, home, by, reason):
    if not number.isascii() or not number.isdecimal():
        raise RuntimeError("acknowledgement requires a numeric slot number")
    slot = Path(home) / "src/fabrig/slots" / number
    builder(slot, home)
    with maintenance(slot, home) as directory:
        value, evidence = snapshot(slot, home)
        value.update(by=by, reason=reason, acknowledged=datetime.now(timezone.utc).isoformat(),
                     assertions=["report-handled", "no-pending-resume", "exclusive-lease-use"], evidence=evidence)
        write(directory / "ack.json", value)
        return f"slot {number}: acknowledged by={by} reason={reason} latest={value['history']['latest']} owner={value['history']['owner']}"


def release_hold(number, token, home, by, reason):
    if (not number.isascii() or not number.isdecimal() or len(token) != 32
            or any(c not in "0123456789abcdef" for c in token)):
        raise RuntimeError("release requires a numeric slot and exact 32-hex hold token")
    slot = Path(home) / "src/fabrig/slots" / number
    builder(slot, home)
    name = token + ".hold"
    with maintenance(slot, home, release_hold=name) as directory:
        hold = read(directory / name)
        if hold.get("slot") != str(slot) or hold.get("identity") != identity(slot):
            raise RuntimeError("hold does not match the slot identity")
        _, evidence = snapshot(slot, home)
        # Explicit reconciliation is separate from report acknowledgement. A
        # missing ended marker or unknown observation still refuses this API.
        write(directory / (token + ".released.json"),
              {"hold": hold, "by": by, "reason": reason, "evidence": evidence,
               "assertion": "all commands completed; no pending resume", "time": time.time_ns()})
        L["completed_lifetime"](directory, slot, token, "operator lifetime reconciliation")
        (directory / name).unlink()
        L["sync"](directory)
        return f"slot {number}: hold {token} released by={by} reason={reason}; fresh report acknowledgement required"


def eligible(slot, home, directory):
    ack = read(directory / "ack.json")
    current, evidence = snapshot(slot, home)
    if (any(ack.get(key) != value for key, value in current.items()) or
            ack.get("assertions") != ["report-handled", "no-pending-resume", "exclusive-lease-use"]
            or not isinstance(ack.get("by"), str) or not ack["by"].strip()
            or not isinstance(ack.get("reason"), str) or not ack["reason"].strip()):
        raise RuntimeError("acknowledgement stale or incomplete; check latest report/resume and acknowledge again")
    return ack, evidence


def target_size(slot, *, activity=False, inventory=False):
    target = slot / "target"
    expected = target_identity(slot)
    device = slot.stat().st_dev
    # Bind mounts on the same device also must not be traversed.
    for line in Path("/proc/self/mountinfo").read_text().splitlines():
        mount = re.sub(r"\\([0-7]{3})", lambda m: chr(int(m[1], 8)), line.split()[4])
        if Path(mount).is_relative_to(target):
            raise RuntimeError(f"mount beneath target: {mount}")
    size = 0
    newest = 0
    entries = []
    inodes = [expected]
    files_count = 0
    links = {}
    fd = os.open(target, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if [info.st_dev, info.st_ino] != expected:
            raise RuntimeError("target replaced before measurement")
        newest = max(info.st_mtime_ns, info.st_ctime_ns)
        if inventory:
            entries.append([".", info.st_ino, info.st_mtime_ns, info.st_ctime_ns])
        def fail(error):
            raise error
        for parent, directories, files, directory_fd in os.fwalk(
                ".", dir_fd=fd, follow_symlinks=False, onerror=fail):
            for name in [*directories, *files]:
                info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                if info.st_dev != device:
                    raise RuntimeError(f"device boundary in target: {parent}/{name}")
                if stat.S_ISREG(info.st_mode):
                    size += info.st_blocks * 512
                newest = max(newest, info.st_mtime_ns, info.st_ctime_ns)
                if inventory:
                    if (not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode))
                            or name in (".git", "auth.json", ".credentials.json", ".ssh")):
                        raise RuntimeError(f"unrecognized, linked or symlink target input: {parent}/{name}")
                    files_count += int(stat.S_ISREG(info.st_mode))
                    inodes.append([info.st_dev, info.st_ino])
                    entries.append([str(Path(parent) / name), info.st_ino, info.st_mode,
                                    info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_nlink])
                    if stat.S_ISREG(info.st_mode):
                        key = (info.st_dev, info.st_ino)
                        shape = [info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_blocks]
                        if key in links and links[key][0] != shape:
                            raise RuntimeError("target hardlink identity changed during inventory")
                        previous = links.get(key, (shape, 0))
                        links[key] = (shape, previous[1] + 1)
    finally:
        os.close(fd)
    if inventory:
        if any(shape[0] != count for shape, count in links.values()):
            raise RuntimeError("external or unaccounted target hardlinks")
        size = sum(shape[4] * 512 for shape, _ in links.values())
        return {"allocated_bytes": size, "newest_ns": newest, "files": files_count,
                "inodes": sorted(inodes), "sha256": digest(sorted(entries))}
    return (size, newest) if activity else size


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def observe_targets(slots, home, available_bytes, record):
    """Unexcluded metadata observations, never automatic deletion eligibility (5.5)."""
    now = time.time_ns()
    pressure = "YES" if available_bytes < 80_000_000_000 else "NO"
    for slot in sorted(slots, key=lambda path: path.name):
        fields = [f"slot {slot.name}: automatic-target PROTECTED", f"pressure-below80GB={pressure}",
                  "claim=UNKNOWN", "claim-age-seconds=UNKNOWN",
                  "central-exclusion=UNKNOWN", "terminal-no-resume=UNKNOWN",
                  "live-process=UNKNOWN", "source=UNKNOWN", "borrower=UNKNOWN",
                  "deletion=PROTECTED"]
        completed = newest = None
        try:
            builder(slot, home)
        except (OSError, ValueError, KeyError, RuntimeError) as error:
            fields.extend(["completion-age-seconds=UNKNOWN", "target-write-age-seconds=UNKNOWN",
                           "observed-idle-over24h=UNKNOWN", f"reason={json.dumps(str(error))}"])
            record(" ".join(fields))
            continue
        try:
            value, _ = history(slot, home, observational=True)
            completed = value["completed_ns"]
            if completed > now:
                completed = None
                raise RuntimeError("completion changed during observation")
            fields.extend([f"latest={value['latest']}", f"completion-age-seconds={(now - completed) / 1e9:.3f}"])
            if value["completed_lifetime"] is None:
                fields.append("lifetime-history=UNKNOWN")
        except (OSError, ValueError, KeyError, RuntimeError) as error:
            fields.extend(["completion-age-seconds=UNKNOWN", f"history-reason={json.dumps(str(error))}"])
        try:
            size, newest = target_size(slot, activity=True)
            if newest > now:
                newest = None
                raise RuntimeError("target activity is in the future or changed during observation")
            fields.extend([f"target-write-age-seconds={(now - newest) / 1e9:.3f}",
                           f"allocated-bytes={size}"])
        except (OSError, ValueError, KeyError, RuntimeError) as error:
            fields.extend(["target-write-age-seconds=UNKNOWN", f"target-reason={json.dumps(str(error))}"])
        age = "UNKNOWN" if completed is None or newest is None else (
            "YES" if now - max(completed, newest) > 24 * 60 * 60 * 1_000_000_000 else "NO")
        fields.extend([f"observed-idle-over24h={age}",
                       "reason=\"metadata snapshot only; no deletion exclusion or finality protocol\""])
        record(" ".join(fields))


def require_automatic_activation():
    if FIRSTDAYDRYRUN:
        raise RuntimeError("FIRSTDAYDRYRUN: automatic live mode refused; central exclusion and finality protocol unavailable until Ops review/activation")


class ClaimNotAcquired(RuntimeError):
    def __init__(self, result):
        super().__init__(result.stderr.strip())
        self.proof = {"code": result.returncode, "stdout": result.stdout, "stderr": result.stderr}


def known_claim_refusal(host, number, share, code, stdout, stderr):
    """Only two exit-1 diagnostics established by the unchanged authority source."""
    if type(code) is not int or code != 1 or stdout != "" or not isinstance(stderr, str):
        return False
    nonpool = re.fullmatch(re.escape(f"claim: {host} {number} belongs to share ") + r"([^\r\n]+); a lend requires --lent-by \1\n", stderr)
    if nonpool is not None and nonpool[1] not in ("pool", "ops"):
        return True
    match = re.fullmatch(re.escape(f"claim: {host}-{number} held by ") + r".+: .+ \(since ([^()\s]+)\)\n", stderr)
    if match is None:
        return False
    try:
        return datetime.fromisoformat(match[1]).utcoffset() is not None
    except ValueError:
        return False


def authority_argv(*args):
    """The verified HEL8 transport, with ordinary host-key checks (5.6)."""
    return ("ssh", "-o", "BatchMode=yes", CLAIM_SSH_TARGET, "bash", "-lc",
            shlex.quote(shlex.join(["claim", *args])))


def central_available(host, number, share):
    """An unlocked observation for filtering, never permission to mutate."""
    output = command(*authority_argv("list"))
    prefix = f"{host} {number} [{share}]: "
    rows = [line for line in output.splitlines() if line.startswith(f"{host} {number} [")]
    if rows == [prefix + "free"]:
        return True
    if len(rows) == 1 and re.fullmatch(re.escape(prefix) + r".+: .+ \(since [^()\s]+\); held \d+d \d{2}:\d{2}:\d{2}(?:; lent by .+)?", rows[0]):
        return False
    raise RuntimeError("unknown central claim snapshot; no acquisition attempted")


def central_claim(action, host, number, what, share=None):
    """Only hel8's installed authority; never builder-local claim state (5.6)."""
    args = [action]
    if action == "list":
        output = command(*authority_argv(*args))
        prefix = f"{host} {number} [{share}]: ops: {what} (since "
        rows = [line for line in output.splitlines() if line.startswith(f"{host} {number} [")]
        match = re.fullmatch(re.escape(prefix) + r"([^()\s]+)\); held \d+d \d{2}:\d{2}:\d{2}", rows[0]) if len(rows) == 1 else None
        if match is None:
            raise RuntimeError("central claim no longer matches exact guard owner/WHAT")
        created = datetime.fromisoformat(match[1])
        if created.utcoffset() is None or created.timestamp() * 1e9 > time.time_ns():
            raise RuntimeError("unknown central claim creation time")
        return
    args.extend([host, number, "ops"])
    if action == "claim":
        args.append(what)
        expected = f"{host}-{number} claimed by ops: {what}"
    elif action == "release":
        args.extend(["--what", what])
        expected = f"{host}-{number} released by ops"
    else:
        raise RuntimeError("unknown central claim action")
    argv = authority_argv(*args)
    if action == "claim":
        result = subprocess.run(argv, text=True, capture_output=True, stdin=subprocess.DEVNULL)
        if known_claim_refusal(host, number, share, result.returncode, result.stdout, result.stderr):
            raise ClaimNotAcquired(result)
        if result.returncode:
            raise RuntimeError(f"ssh exited {result.returncode}: {result.stderr.strip()}")
        output = result.stdout
    else:
        output = command(*argv)
    if output.strip() != expected:
        raise RuntimeError(f"ambiguous central claim {action} response; operator reconciliation required")


def finality(value):
    """Require explicit owner finality for every relevant run; never backfill."""
    finals = []
    for run in value["runs"]:
        path = Path(run["meta"]["path"]).parent / "final.json"
        before = L["fingerprint"](path)
        final = read(path)
        if not isinstance(final.get("time"), str):
            raise RuntimeError("unknown finality time")
        stamp = datetime.fromisoformat(final["time"].replace("Z", "+00:00"))
        if stamp.utcoffset() is None:
            raise RuntimeError("finality time has no UTC offset")
        timestamp = int(stamp.timestamp() * 1e9)
        if (final.get("owner") != run["owner"] or not run["owner"].strip()
                or not run["ended"]["identity"][3] <= timestamp <= time.time_ns()):
            raise RuntimeError("finality owner/time does not match completed run")
        if final.get("state") == "landed":
            if (not isinstance(final.get("sha"), str) or not re.fullmatch(r"(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})", final["sha"])
                    or not int(final["sha"], 16)):
                raise RuntimeError("unknown landed finality SHA")
        elif final.get("state") == "withdrawn":
            if not isinstance(final.get("reason"), str) or not final["reason"].strip():
                raise RuntimeError("withdrawn finality needs a reason")
        else:
            raise RuntimeError("unknown finality state")
        if before != L["fingerprint"](path):
            raise RuntimeError("finality changed while inspecting")
        finals.append({"id": run["id"], "file": before, "value": final})
    return finals


def source_preservation(slot):
    """Hash owned regular source/Git files, never expose file contents (5.6)."""
    files, directories, inodes = [], [], [identity(slot)]
    def fail(error):
        raise error
    for parent, names, leaves in os.walk(slot, followlinks=False, onerror=fail):
        parent = Path(parent)
        names.sort()
        if parent == slot:
            names[:] = [name for name in names if name != "target"]
        for name in sorted(names):
            path = parent / name
            no_links(path)
            info = path.stat()
            if not stat.S_ISDIR(info.st_mode) or info.st_dev != slot.stat().st_dev:
                raise RuntimeError(f"unsafe source directory: {path}")
            directories.append([str(path.relative_to(slot)), identity(path)])
            inodes.append(identity(path))
        for name in sorted(leaves):
            path = parent / name
            if parent == slot and name == "target":
                raise RuntimeError("target is not a directory")
            file = L["fingerprint"](path)
            if file["identity"][0] != slot.stat().st_dev:
                raise RuntimeError(f"cross-device source file: {path}")
            files.append(file)
            inodes.append(file["identity"][:2])
    return {"sha256": digest([sorted(directories), sorted(files, key=lambda file: file["path"])]), "files": len(files),
            "inodes": sorted(inodes)}


def borrowers(slot, home):
    """All Fabrig-managed clones/scratch live under this one host root (5.6)."""
    if os.environ.get("GIT_ALTERNATE_OBJECT_DIRECTORIES"):
        raise RuntimeError("unknown environment object-store borrowing")
    root = canonical(Path(home) / "src/fabrig")
    target = slot / "target"
    observations = []
    def inspect_objects(objects, seen):
        alternate = objects / "info/alternates"
        no_links(alternate)
        if not alternate.exists():
            return
        if objects in seen:
            raise RuntimeError("cyclic alternate object-store borrowing")
        before = L["fingerprint"](alternate)
        for line in alternate.read_text().splitlines():
            if not line or line.startswith('"'):
                raise RuntimeError(f"unknown alternate syntax: {alternate}")
            path = canonical(objects / line)
            if path.is_relative_to(target) or target.is_relative_to(path):
                raise RuntimeError(f"object-store borrower: {alternate}")
            if not path.is_dir() or not path.is_relative_to(root):
                raise RuntimeError(f"unrecognized alternate object store: {alternate}")
            inspect_objects(path, seen | {objects})
        if before != L["fingerprint"](alternate):
            raise RuntimeError("alternate changed while inspecting")
        observations.append(before)
    def fail(error):
        raise error
    for parent, directories, files in os.walk(root, followlinks=False, onerror=fail):
        parent = Path(parent)
        for name in directories:
            no_links(parent / name)
        if ".git" in files:
            raise RuntimeError(f"unrecognized linked checkout borrower: {parent / '.git'}")
        if (("commondir" in files or "commondir" in directories)
                and (".git" in parent.relative_to(root).parts or "HEAD" in files)):
            raise RuntimeError(f"unsupported Git commondir borrower: {parent}")
        gitdirs = [parent / ".git"] if ".git" in directories else []
        if "HEAD" in files and "objects" in directories and "refs" in directories:
            gitdirs.append(parent)
        # Orphaned stores and repositories with other ref layouts still have
        # standard objects/info/alternates and must not escape the host scan.
        if parent.name == "objects" and "info" in directories:
            inspect_objects(parent, set())
        for gitdir in gitdirs:
            inspect_objects(gitdir / "objects", set())
        # Stored submodule repositories beneath .git/modules can also borrow,
        # even when their worktrees no longer exist. Inspect Git directories too.
    return sorted(observations, key=lambda file: file["path"])


def own_lock_descriptor(entry, number, info, lock_fds):
    for held in lock_fds:
        if (held.get("active") is not True or held["pid"] != os.getpid() or entry.name != str(held["pid"])
                or number != str(held["fd"]) or [info.st_dev, info.st_ino] != held["identity"]):
            continue
        try:
            current = os.fstat(held["fd"])
            if [current.st_dev, current.st_ino] != held["identity"] or identity(Path(held["path"])) != held["identity"]:
                continue
            # fdinfo describes this open file description's kernel flock, not
            # descriptor contents. Closed/reopened same-inode fds have no proof.
            for line in Path(f"/proc/self/fdinfo/{held['fd']}").read_text().splitlines():
                parts = line.split()
                if len(parts) != 9 or parts[:1] != ["lock:"] or parts[2:6] != ["FLOCK", "ADVISORY", "WRITE", str(held["pid"])]:
                    continue
                major, minor, inode = parts[6].split(":")
                if (os.makedev(int(major, 16), int(minor, 16)), int(inode)) == (info.st_dev, info.st_ino):
                    return True
        except (OSError, ValueError):
            continue
    return False


def automatic_processes(slot, inodes, proc=Path("/proc"), *, lock_fds=()):
    evidence = processes(slot, proc)
    protected = {tuple(pair) for pair in inodes}
    for entry in proc.iterdir():
        if not entry.name.isdecimal():
            continue
        try:
            first = entry.stat()
            if first.st_uid != os.getuid():
                continue
            cwd = (entry / "cwd").stat()
            if (cwd.st_dev, cwd.st_ino) in protected:
                raise RuntimeError(f"live source/target cwd inode pid={entry.name}")
            # Keep the enumeration descriptor open while inspecting its entries.
            # A detached name list would include our already-closed scanner fd.
            with os.scandir(entry / "fd") as descriptors:
                for fd in descriptors:
                    info = fd.stat()
                    if own_lock_descriptor(entry, fd.name, info, lock_fds):
                        continue
                    if (info.st_dev, info.st_ino) in protected:
                        raise RuntimeError(f"live source/target fd pid={entry.name}")
                    link = os.readlink(fd.path).removesuffix(" (deleted)")
                    if link.startswith("/") and Path(os.path.normpath(link)).is_relative_to(slot):
                        raise RuntimeError(f"live slot fd pid={entry.name}")
            for line in (entry / "maps").read_text().splitlines():
                parts = line.split(None, 5)
                if len(parts) < 5:
                    raise RuntimeError(f"unknown maps observation pid={entry.name}")
                major, minor = parts[3].split(":")
                mapped = (os.makedev(int(major, 16), int(minor, 16)), int(parts[4]))
                path = parts[5].removesuffix(" (deleted)") if len(parts) == 6 else ""
                if mapped in protected or path.startswith("/") and Path(os.path.normpath(path)).is_relative_to(slot):
                    raise RuntimeError(f"live source/target map pid={entry.name}")
            if entry.stat().st_ino != first.st_ino:
                raise RuntimeError("process replaced during observation")
        except (FileNotFoundError, ProcessLookupError) as error:
            if entry.exists():
                raise RuntimeError(f"incomplete own-user process observation pid={entry.name}") from error
        except (PermissionError, ValueError) as error:
            raise RuntimeError(f"unknown own-user fd/maps pid={entry.name}") from error
    return [*evidence, "own-user fd/maps scan completed"]


def automatic_snapshot(slot, home, *, lock_fds=(), observational=False):
    current, evidence = snapshot(slot, home, observational=observational)
    if current["history"]["completed_lifetime"] is None:
        raise RuntimeError("unknown completed source/build lifetime")
    current["finality"] = finality(current["history"])
    current["target"] = target_size(slot, inventory=True)
    current["preservation"] = source_preservation(slot)
    current["borrowers"] = borrowers(slot, home)
    evidence.extend(automatic_processes(slot, [*current["target"]["inodes"], *current["preservation"]["inodes"]], lock_fds=lock_fds))
    latest = max(current["history"]["completed_ns"], current["target"]["newest_ns"])
    if time.time_ns() - latest <= 86400 * 1_000_000_000:
        raise RuntimeError("target/run/lifetime not proven idle >24h")
    return current, evidence


def automatic_recover(slots, home, free, record):
    """Persistent central custody, durable terminal proof, then exact release (5.6)."""
    require_automatic_activation()
    state = L["state_root"](home)
    failed = False
    # Serialize intent publication with manual sweeps before any claim request.
    # The exclusive local slot/worker/precheck leases follow successful custody.
    with locked(state / "sweep.lock"):
        for slot in sorted(slots, key=lambda path: path.name):
            task = None
            try:
                require_automatic_activation()
                if free() >= 80_000_000_000:
                    break
                host, share = builder(slot, home)
                directory = state / slot.name
                L["private_directory"](directory)
                journal = directory / "automatic.json"
                no_links(journal)
                if journal.exists():
                    previous = read(journal)
                    if not automatic_terminal(previous, slot):
                        raise RuntimeError("prior automatic claim/task requires reconciliation")
                if share not in ("pool", "ops"):
                    record(f"slot {slot.name}: automatic skipped (share {share}; no invented --lent-by); no acquisition attempted")
                    continue
                if not central_available(host, slot.name, share):
                    record(f"slot {slot.name}: automatic skipped (central busy snapshot); no acquisition attempted")
                    continue
                # This is filtering only, not custody. Release the probe leases
                # before requesting the persistent claim, then repeat all proofs.
                preflight_fds = []
                with maintenance(slot, home, lock_fds=preflight_fds):
                    automatic_snapshot(slot, home, lock_fds=preflight_fds, observational=True)
                token = uuid.uuid4().hex
                started = datetime.now(timezone.utc).isoformat()
                what = f"guard reclaim {started} {token}"
                task = {"slot": str(slot), "claim": {"host": host, "number": slot.name, "share": share, "owner": "ops", "what": what},
                        "start": started, "status": "claim-requested", "release": "retained", "exit": None,
                        "acquired": None, "mutation_started": False}
                write(journal, task)
                try:
                    central_claim("claim", host, slot.name, what, share)
                except ClaimNotAcquired as error:
                    task.update(status="skipped", release="not-acquired", acquired=False, exit=0,
                                end=datetime.now(timezone.utc).isoformat(), refusal=error.proof)
                    write(directory / f"automatic-{token}.json", task)
                    write(journal, task)
                    record(f"slot {slot.name}: automatic skipped (known no acquisition: {error}); no claim release")
                    continue
                task["status"] = "uncertain"
                task["acquired"] = True
                write(journal, task)
                lock_fds = []
                with maintenance(slot, home, automatic_what=what, lock_fds=lock_fds):
                    central_claim("list", host, slot.name, what, share)
                    before, evidence = automatic_snapshot(slot, home, lock_fds=lock_fds)
                    available = free()
                    if available >= 80_000_000_000:
                        raise RuntimeError("pressure ended after claim; claim retained for reconciliation")
                    task.update(before_bytes=available, proofs=before, evidence=evidence)
                    write(journal, task)
                    record(f"slot {slot.name}: automatic reclaim-start claim-WHAT={what} target={slot / 'target'}")
                    central_claim("list", host, slot.name, what, share)
                    current, _ = automatic_snapshot(slot, home, lock_fds=lock_fds)
                    if current != before or free() >= 80_000_000_000:
                        raise RuntimeError("automatic evidence or pressure changed before mutation")
                    require_automatic_activation()
                    task["mutation_started"] = True
                    write(journal, task)
                    fd = os.open(slot, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                    try:
                        if (identity(slot) != before["slot_identity"] or identity(slot.parent) != before["root_identity"]
                                or [os.fstat(fd).st_dev, os.fstat(fd).st_ino] != before["slot_identity"]
                                or target_identity(slot) != before["target_identity"]):
                            raise RuntimeError("automatic slot/target identity changed")
                        if not shutil.rmtree.avoids_symlink_attacks:
                            raise RuntimeError("fd-safe rmtree unavailable")
                        shutil.rmtree("target", dir_fd=fd)
                        os.fsync(fd)
                    finally:
                        os.close(fd)
                    record(f"slot {slot.name}: automatic deletion returned; preservation proof pending; claim retained")
                    if os.path.lexists(slot / "target"):
                        raise RuntimeError("target reappeared; terminal deletion unknown")
                    history_after, _ = history(slot, home)
                    if (identity(slot) != before["slot_identity"] or identity(slot.parent) != before["root_identity"]
                            or source_preservation(slot) != before["preservation"]
                            or history_after != before["history"] or finality(history_after) != before["finality"]
                            or borrowers(slot, home) != before["borrowers"]):
                        raise RuntimeError("source/Git/history preservation failed after deletion")
                    central_claim("list", host, slot.name, what, share)
                    after = free()
                    write(directory / "owner-notice.json", {"owner": before["history"]["owner"], "slot": str(slot),
                          "message": "target reclaimed; next build is cold", "claim": task["claim"],
                          "before_bytes": available, "after_bytes": after})
                    task.update(status="completed", exit=0, end=datetime.now(timezone.utc).isoformat(),
                                after_bytes=after, bytes_freed=after - available,
                                files_removed=before["target"]["files"],
                                preservation={"source_git": before["preservation"], "history": digest(history_after),
                                              "finality": digest(before["finality"]), "target_absent": True})
                    archive = directory / f"automatic-{token}.json"
                    write(archive, task)
                    write(journal, task)
                    central_claim("release", host, slot.name, what)
                    task["release"] = "released"
                    write(archive, task)
                    write(journal, task)
                    record(f"slot {slot.name}: automatic reclaimed; completed evidence={archive}; next build is cold")
            except (OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
                failed = True
                if task is not None:
                    task.update(error=str(error))
                    if task["status"] != "completed":
                        task.update(status="uncertain", exit=1, end=datetime.now(timezone.utc).isoformat())
                    write(journal, task)
                record(f"slot {slot.name}: automatic PROTECTED/reconcile ({error}); no automatic claim release")
    return not failed


def recover(slots, home, below, dry_run, free, record):
    candidates = []
    for slot in slots:
        try:
            builder(slot, home)
            with maintenance(slot, home) as directory:
                ack, _ = eligible(slot, home, directory)
                candidates.append((ack["history"]["completed_ns"], slot.name, slot))
        except (OSError, ValueError, KeyError, RuntimeError) as error:
            record(f"slot {slot.name}: whole-target refused ({error})")
    for completed, _, slot in sorted(candidates):
        if free() > below:
            break
        try:
            with maintenance(slot, home) as directory:
                ack, evidence = eligible(slot, home, directory)
                size = target_size(slot)
                before = free()
                if before > below:
                    break
                fields = (f"owner={ack['history']['owner']} ack-by={ack['by']} ack-reason={ack['reason']} "
                          f"latest={ack['history']['latest']} target={slot / 'target'} "
                          f"age-seconds={(time.time_ns() - completed) / 1e9:.3f} allocated-GB={size / 1e9:.3f} "
                          f"before={before:.3f} evidence={json.dumps(evidence)}")
                if dry_run:
                    record(f"slot {slot.name}: would-reclaim {fields} after={free():.3f}")
                    continue
                # Durable intent and owner notice precede mutation. Logging is local;
                # post delivery never controls cleanup success or acknowledges reports.
                write(directory / "reclaim.json", {"status": "uncertain", "ack": ack, "before": before})
                record(f"slot {slot.name}: reclaim-start {fields}")
                eligible(slot, home, directory)
                fd = os.open(slot, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                try:
                    if ([os.fstat(fd).st_dev, os.fstat(fd).st_ino] != ack["slot_identity"]
                            or identity(slot.parent) != ack["root_identity"]
                            or identity(slot) != ack["slot_identity"]
                            or target_identity(slot) != ack["target_identity"]):
                        raise RuntimeError("slot/target replaced before deletion")
                    # Consume eligibility before touching generated data; no retry after a crash.
                    (directory / "ack.json").unlink()
                    L["sync"](directory)
                    if not shutil.rmtree.avoids_symlink_attacks:
                        raise RuntimeError("fd-safe rmtree is unavailable")
                    shutil.rmtree("target", dir_fd=fd)
                    os.fsync(fd)
                finally:
                    os.close(fd)
                after = free()
                write(directory / "reclaim.json", {"status": "completed", "ack": ack,
                                                   "before": before, "after": after})
                notice = {"owner": ack["history"]["owner"], "slot": str(slot), "before": before,
                          "after": after, "message": "target reclaimed; next build is cold", "ack_by": ack["by"]}
                write(directory / "owner-notice.json", notice)
                record(f"slot {slot.name}: reclaimed {fields} after={after:.3f} owner-notice={directory / 'owner-notice.json'}")
        except (OSError, ValueError, KeyError, RuntimeError) as error:
            record(f"slot {slot.name}: whole-target refused ({error})")
