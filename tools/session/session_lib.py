"""Registry, naming and launch support; Python standard library only."""

import json
import os
from pathlib import Path
import re
import subprocess
from string import Template
import tempfile
import tomllib


ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "pipeline/coordinators.toml"
AREAS = ("skein", "smith", "jig", "temper")


def registry(path=None):
    with (REGISTRY if path is None else Path(path)).open("rb") as stream:
        entries = tomllib.load(stream)
    mailboxes = set()
    defaults = 0
    for handle, entry in entries.items():
        if not re.fullmatch(r"[a-z][a-z0-9]{0,7}", handle):
            raise ValueError(f"invalid coordinator handle: {handle!r}")
        if not isinstance(entry, dict) or set(entry) - {"mailbox", "default"}:
            raise ValueError(f"invalid coordinator entry: {handle}")
        mailbox = entry.get("mailbox")
        if not isinstance(mailbox, str) or not re.fullmatch(r"s/[a-z0-9][a-z0-9-]*", mailbox):
            raise ValueError(f"invalid mailbox for {handle}")
        if mailbox in mailboxes:
            raise ValueError(f"duplicate mailbox: {mailbox}")
        mailboxes.add(mailbox)
        default = entry.get("default", False)
        if type(default) is not bool:
            raise ValueError(f"default must be a boolean: {handle}")
        defaults += default
    if defaults != 1:
        raise ValueError("registry must have exactly one default coordinator")
    return entries


def names(handle, area=None):
    """Derive every identity and path here, including the incumbent exceptions."""
    entries = registry()
    if handle not in entries:
        raise ValueError(f"unknown coordinator: {handle}")
    if area is not None and area not in AREAS:
        raise ValueError(f"unknown area: {area}")
    entry = entries[handle]
    default = entry.get("default", False)
    home = Path.home()
    supervise = home / "src/rust/tmp/supervise"
    start = supervise / ("coordinator" if default else f"coordinators/{handle}")
    result = {
        "handle": handle,
        "coordinator_mailbox": entry["mailbox"],
        "coordinator_address": entry["mailbox"] + "@hel8",
        "coordinator_name": entry["mailbox"],
        "coordinator_start_dir": str(start),
        "coordinator_handover": str(supervise / "handover.md" if default else start / "handover.md"),
        "coordinator_branch_prefix": "coord" if default else handle,
        "coordinator_clone": str(start / "repo"),
        "coordinator_brief": str(start / "brief.md"),
        "warmup_name": "coord-next" if default else f"{handle}-next",
    }
    if area is not None:
        key = area if default else f"{handle}-{area}"
        mailbox = f"lead/{area}" if default else f"lead/{handle}/{area}"
        scratch = home / "src/fabrig/leads" / key
        result.update(
            area=area, lead_mailbox=mailbox, lead_name=mailbox, branch_key=key,
            lead_scratch=str(scratch), lead_start_dir=str(supervise / "leads" / key),
            lead_clone=str(scratch / "repo"),
            lead_mail_dir=str(home / "src/rust/tmp/post" / mailbox.replace("/", "+") / "cur"),
        )
    return result


def state_time(path):
    if not path.exists():
        return "unknown"
    for line in path.read_text().splitlines():
        match = re.search(r"\b(?:\d{4}-\d{2}-\d{2}[T ])?\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?Z\b", line)
        if match:
            return match.group()
    return "unknown"


def render(template, values):
    # substitute (never safe_substitute) rejects missing or malformed placeholders.
    return Template(template.read_text()).substitute(values)


def live_session(name):
    result = subprocess.run(["claude", "agents", "--json"], capture_output=True, text=True, check=True)
    sessions = json.loads(result.stdout)
    if not isinstance(sessions, list) or any(not isinstance(item, dict) for item in sessions):
        raise ValueError("claude agents --json must return a list of sessions")
    for session in sessions:
        if session.get("name") == name:
            status = session.get("status", session.get("state", "unknown"))
            if status not in ("stopped", "completed"):
                return session
    return None


def create_empty(path):
    """Preserve inherited state; publish new files by sibling rename."""
    if path.exists():
        return
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, prefix=f".{path.name}.", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write("(empty)\n")
        if not path.exists():
            os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def clone(path):
    if not path.exists():
        subprocess.run([
            "git", "clone", "--reference", str(Path.home() / "src/fabrig/main"),
            "git@github.com:fabrig-ai/fabrig.git", str(path),
        ], check=True)


def session_id(output):
    """Accept JSON reports and Claude's human-readable background launch report."""
    try:
        report = json.loads(output)
    except json.JSONDecodeError:
        report = None
    if isinstance(report, dict):
        value = report.get("session_id") or report.get("sessionId") or report.get("id")
        if isinstance(value, str) and value:
            return value
    match = re.search(
        r"\b(?:session(?:[ _-]?id)?|agent(?:[ _-]?id)?)\s*[:=]\s*[`\"']?([a-zA-Z0-9][a-zA-Z0-9_-]*)",
        output, re.IGNORECASE,
    )
    if match:
        return match.group(1)
    # Some versions report only a UUID beside the background-start message.
    match = re.search(r"\b[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\b", output)
    return match.group() if match else None
