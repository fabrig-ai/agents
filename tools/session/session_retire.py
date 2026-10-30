"""Preview or hand retired role paths to reap; never delete paths here."""
from datetime import datetime, UTC
import json
from pathlib import Path
import re
import shutil
import subprocess

from session_lib import (AREAS, atomic_json, list_sessions, live_session, names,
                         registry, warmup_records, warmup_state_path)


def role_identity(role, values, name):
    if role == "lead":
        return name == values["lead_name"] or name.startswith(values["lead_name"] + "/")
    return bool(name) and (name.startswith(values["coordinator_name_prefix"])
            or name in (values["coordinator_mailbox"], values["warmup_name"],
                        values["coordinator_legacy_name"], values["coordinator_name_prefix"].rstrip("/")))


def role_paths(role, values):
    if role == "lead":
        return [Path(values["lead_scratch"]), Path(values["lead_start_dir"])]
    paths = [Path(values["coordinator_clone"]), Path(values["coordinator_brief"]),
             Path(values["coordinator_start_dir"])]
    handover = Path(values["coordinator_handover"]).parent
    if not any(handover.is_relative_to(path) for path in paths):
        paths.append(handover)
    return paths


def observe(argv):
    return subprocess.run(argv, capture_output=True, text=True, timeout=30, check=True).stdout


def retire(role, handle, area=None, yes=False):
    values = names(handle, area)
    owner = values["lead_name"] if role == "lead" else values["coordinator_name_prefix"].rstrip("/")
    mailbox = values["lead_mailbox" if role == "lead" else "coordinator_mailbox"]
    paths = role_paths(role, values)
    refusals = []
    if role == "coordinator" and registry()[handle].get("default", False):
        refusals.append("default coordinator has a shared start directory: " + values["coordinator_start_dir"])
    # Compare resolved paths too: a symlink must not turn a private path into
    # another role's scratch or a shared parent of one.
    others = [Path(names("director")["director_start_dir"])]
    for other in registry():
        if role != "coordinator" or other != handle:
            coordinator = names(other)
            others.extend(Path(coordinator[key]) for key in (
                "coordinator_clone", "coordinator_brief", "coordinator_start_dir", "coordinator_handover"))
        for other_area in AREAS:
            if (role, handle, area) != ("lead", other, other_area):
                others.extend(role_paths("lead", names(other, other_area)))
    for path in paths:
        resolved = path.resolve()
        if any(resolved.is_relative_to(other.resolve()) or other.resolve().is_relative_to(resolved)
               for other in others):
            refusals.append(f"path shared with another role: {path}")
    try:
        sessions = list_sessions()
        for session in sessions:
            name = session.get("name")
            if not isinstance(name, str) or live_session(name, [session]) is None:
                continue
            if role_identity(role, values, name):
                refusals.append(f"live session {name} ({session.get('sessionId', session.get('id', 'unknown'))})")
            elif role == "lead" and re.match(r"lead/(?:[a-z][a-z0-9]{0,7}/)?" + re.escape(area) + r"(?:/|$)", name):
                refusals.append(f"live successor for area {area}: {name}")
        if role == "lead" and values["lead_kind"] == "codex":
            from session_lib import unit_active
            if unit_active(values["lead_unit"]):
                refusals.append(f"active unit {values['lead_unit']}")
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        refusals.append(f"session observation unavailable: {error}")
    try:
        for line in observe(["claim", "list"]).splitlines():
            if not line.strip():
                continue
            match = re.fullmatch(r"\S+\s+\d+\s+\[[^]\r\n]+\]: (free|([^:\s]+): .+)", line)
            if match is None:
                raise ValueError(f"unrecognized claim list row: {line}")
            if match[2] == mailbox:
                refusals.append(f"claimed slot: {line}")
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        refusals.append(f"claim list unavailable: {error}")
    if role == "coordinator":
        try:
            leases = json.loads(observe(["lease", "list", "--json"]))
            if not isinstance(leases, list) or any(not isinstance(row, dict) or "owner" not in row
                                                  or "subject" not in row for row in leases):
                raise ValueError("expected lease records with owner and subject")
            for lease in leases:
                if lease["owner"] == mailbox:
                    refusals.append(f"lease held by {mailbox}: {lease['subject']}")
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            refusals.append(f"lease list unavailable: {error}")
    if shutil.which("reap") is None:
        refusals.append("reap absent from PATH; cannot hand over paths")
    print(f"retire {role} {owner}:")
    for path in paths:
        print(f"path={path}")
    for reason in refusals:
        print(f"refused: {reason}")
    if not yes:
        return 0
    if refusals:
        return 1
    records = warmup_records()  # Validate before handing anything over.
    identifier = f"retire-{owner.replace('/', '+')}-{datetime.now(UTC):%Y%m%dT%H%M%S%fZ}"
    command = ["reap", "record", "start", "--kind", "retired-scratch", "--owner", owner, "--id", identifier]
    for path in paths:
        command += ["--path", str(path)]
    for argv in (command, ["reap", "record", "end", "--kind", "retired-scratch", "--id", identifier],
                 ["systemctl", "--user", "start", "--no-block", "reap.service"]):
        observe(argv)
    remaining = {name: record for name, record in records.items() if not role_identity(role, values, name)}
    if remaining != records:
        atomic_json(warmup_state_path(), remaining)
    print(f"recorded {identifier}")
    return 0
