"""Registry, naming and launch support; Python standard library only."""

import json
from datetime import datetime, UTC
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
from string import Template
import tempfile
import tomllib
import time


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
        if not isinstance(entry, dict) or set(entry) - {"mailbox", "default", "lead_kind"}:
            raise ValueError(f"invalid coordinator entry: {handle}")
        if entry.get("lead_kind", "claude") not in ("claude", "codex"):
            raise ValueError(f"invalid lead_kind: {handle}")
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


def systemd_escape(name):
    """systemd-escape string mode: UTF-8 bytes, slash separators, literal hyphens escaped."""
    return "".join(
        "-" if byte == 47 else chr(byte) if (byte in b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789:_"
                                           or (byte == 46 and index != 0)) else f"\\x{byte:02x}"
        for index, byte in enumerate(name.encode("utf-8"))
    )


def unit_active(unit):
    result = subprocess.run(["systemctl", "--user", "is-active", "--quiet", unit],
                            capture_output=True, text=True, timeout=30)
    if result.returncode not in (0, 3, 4):
        raise ValueError(f"systemctl is-active failed for {unit} (exit {result.returncode})")
    # A disconnected user bus is an unavailable input, not an inactive unit.
    if result.returncode and result.stderr.strip():
        raise ValueError(f"systemctl is-active unavailable for {unit}")
    return result.returncode == 0


def names(handle, area=None):
    """Derive every identity and path here, including the incumbent exceptions."""
    entries = registry()
    if handle == "director":
        if area is not None:
            raise ValueError("the director has no area")
        start = Path.home() / "src/rust/tmp/supervise/director"
        return {
            "handle": "director", "director_mailbox": "director", "director_address": "director@hel8",
            "director_name": f"director/{datetime.now(UTC):%Y%m%dT%H%MZ}",
            "director_name_prefix": "director/", "director_legacy_name": "director",
            "warmup_name": "director-next", "director_start_dir": str(start),
            "director_handover": str(start / "handover.md"), "director_state": str(start / "state.md"),
        }
    if handle not in entries:
        raise ValueError(f"unknown coordinator: {handle}")
    if area is not None and area not in AREAS:
        raise ValueError(f"unknown area: {area}")
    entry = entries[handle]
    default = entry.get("default", False)
    home = Path.home()
    supervise = home / "src/rust/tmp/supervise"
    start = supervise / ("coordinator" if default else f"coordinators/{handle}")
    scratch = home / "src/fabrig/coord" / handle
    result = {
        "handle": handle,
        "coordinator_mailbox": entry["mailbox"],
        "coordinator_address": entry["mailbox"] + "@hel8",
        "coordinator_name_prefix": f"coordinator/{handle}/",
        "coordinator_name": f"coordinator/{handle}/{datetime.now(UTC):%Y%m%dT%H%MZ}",
        "coordinator_legacy_name": "coord-next" if default else "",
        "coordinator_start_dir": str(start),
        "coordinator_handover": str(supervise / "handover.md" if default else start / "handover.md"),
        "coordinator_branch_prefix": "coord" if default else handle,
        "coordinator_clone": str(home / "src/fabrig/coord/next2" if default else scratch / "repo"),
        "coordinator_brief": str(scratch / "brief.md"),
        "warmup_name": "coord-next" if default else f"{handle}-next",
    }
    if area is not None:
        key = area if default else f"{handle}-{area}"
        mailbox = f"lead/{area}" if default else f"lead/{handle}/{area}"
        scratch = home / "src/fabrig/leads" / key
        result.update(
            area=area, lead_mailbox=mailbox, lead_name=mailbox, branch_key=key,
            lead_kind=entry.get("lead_kind", "claude"),
            lead_scratch=str(scratch), lead_start_dir=str(supervise / "leads" / key),
            lead_clone=str(scratch / "repo"),
            lead_mail_dir=str(home / "src/rust/tmp/post" / mailbox.replace("/", "+") / "cur"),
        )
        if result["lead_kind"] == "codex":
            root = Path(os.environ.get("DEV_ROOT", home / "src/rust"))
            result.update(lead_unit="codex-owner-" + systemd_escape(mailbox),
                          lead_owner_state=str(root / "tmp/owners" / mailbox.rsplit("/", 1)[-1] / "codex"))
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


def paused_coordinators():
    """Read the local records checkout once, shared by ownership and inventory."""
    paused = set()
    records = Path(os.environ.get("RECORDS_REPO", Path.home() / "src/fabrig/records")).expanduser()
    for path in (records / "drafts").glob("*/draft.toml"):
        with path.open("rb") as stream:
            draft = tomllib.load(stream)
        handle = draft.get("coordinator")
        if isinstance(handle, str) and draft.get("state") == "paused":
            paused.add(handle)
    return paused


def inventory():
    """Watch identities and supervisors; no live session queries or network."""
    entries = registry()
    paused = paused_coordinators()
    rows = []
    for handle in entries:
        values = names(handle)
        legacy = [values["coordinator_legacy_name"]] if values["coordinator_legacy_name"] else []
        rows.append({
            "role": "coordinator", "handle": handle, "mailbox": values["coordinator_mailbox"],
            "warmup_name": values["warmup_name"], "name_prefix": values["coordinator_name_prefix"],
            "legacy_names": legacy, "aliases": list(dict.fromkeys([values["warmup_name"], *legacy])),
            "start_dir": values["coordinator_start_dir"], "supervisor": "director", "paused": handle in paused,
        })
        for area in AREAS:
            lead = names(handle, area)
            rows.append({
                "role": "lead", "kind": lead["lead_kind"], "handle": handle, "area": area, "name": lead["lead_name"],
                "mailbox": lead["lead_mailbox"], "branch_key": lead["branch_key"],
                "scratch": lead["lead_scratch"], "start_dir": lead["lead_start_dir"],
                "coordinator_mailbox": values["coordinator_mailbox"],
                "supervisor": values["coordinator_mailbox"], "paused": handle in paused,
            })
            if lead["lead_kind"] == "codex":
                rows[-1].pop("start_dir")
                rows[-1].update(unit=lead["lead_unit"], owner_state=lead["lead_owner_state"])
    director = names("director")
    rows.append({
        "role": "director", "mailbox": director["director_mailbox"], "name_prefix": director["director_name_prefix"],
        "warmup_name": director["warmup_name"], "legacy_names": [director["director_legacy_name"]],
        "aliases": [director["director_legacy_name"], director["warmup_name"]],
        "start_dir": director["director_start_dir"], "supervisor": None, "paused": False,
    })
    for mailbox in ("ops", "s/deploy", "s/multi-coord"):
        rows.append({"role": "fixed", "mailbox": mailbox, "supervisor": "director",
                     "always_watched": True, "note": "always watched; bypass owns"})
    rows[-1].update(name_prefix="s/multi-coord/", aliases=["s/multi-coord-next"],
                    warmup_name="s/multi-coord-next")
    return rows


def owns(name):
    """Local-only ownership contract for post wake; never fetch records or sessions."""
    entries = registry()
    if name == "director" or name.startswith("director/"):
        return True, ""
    owner = None
    for handle in entries:
        values = names(handle)
        if (name in (values["coordinator_mailbox"], values["warmup_name"])
                or name.startswith(values["coordinator_name_prefix"])
                or any(name == names(handle, area)["lead_name"] for area in AREAS)):
            owner = handle
            break
    if owner is None:
        return False, f"not ours: {name}"
    if owner in paused_coordinators():
        return False, f"paused: {name} (coordinator {owner})"
    return True, ""


def list_sessions():
    result = subprocess.run(["claude", "agents", "--json"], capture_output=True, text=True, check=True)
    sessions = json.loads(result.stdout)
    if not isinstance(sessions, list) or any(not isinstance(item, dict) for item in sessions):
        raise ValueError("claude agents --json must return a list of sessions")
    return sessions


def live_session(name, sessions=None):
    for session in list_sessions() if sessions is None else sessions:
        if session.get("name") == name:
            status = session.get("status", session.get("state", "unknown"))
            if status not in ("stopped", "completed"):
                return session
    return None


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, prefix=f".{path.name}.", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def session_capabilities():
    try:
        result = subprocess.run(["session-context", "--capabilities"], capture_output=True,
                                text=True, timeout=10)
        return set(result.stdout.splitlines()) if result.returncode == 0 else set()
    except (OSError, subprocess.SubprocessError):
        return set()


def watched(role, handle, area=None):
    """All live role paths live here, ready for the factory's eventual move."""
    values = names(handle, area)
    if role == "director":
        root = Path.home() / "src/rust/tmp/supervise/monorepo"
        return [str(root / "director-role.md"), str(root / "director-records.md")]
    root = Path.home() / "src/fabrig/main"
    paths = [root / "AGENTS.md", root / "agents" / f"{role}.md", root / "agents/operations.md"]
    if role == "lead":
        if area is None:
            raise ValueError("a lead's watched files require an area")
        paths.append(Path(values["lead_scratch"]) / "brief.md")
    elif role == "coordinator":
        paths.append(root / "agents/lead.md")
    else:
        raise ValueError(f"unknown role: {role}")
    return [str(path) for path in paths]


def owned_hook(hook):
    if not isinstance(hook, dict) or hook.get("type") != "command":
        return False
    try:
        argv = shlex.split(hook.get("command", ""))
    except ValueError:
        return False
    return bool(argv) and (Path(argv[0]).name in ("reap-hook", "session-reap-hook") or
                           (Path(argv[0]).name == "session-context" and "--hook" in argv))


def hook_settings(values, role, capabilities):
    directory = values[f"{role}_start_dir"]
    path = Path(directory) / ".claude/settings.json"
    settings = json.loads(path.read_text()) if path.exists() else {}
    if not isinstance(settings, dict) or not isinstance(settings.get("hooks", {}), dict):
        raise ValueError(f"invalid settings object: {path}")
    hooks = settings.setdefault("hooks", {})
    # Remove only commands we own, including those mixed into foreign groups.
    for event in ("Stop", "SessionStart", "UserPromptSubmit", "SessionEnd"):
        groups = []
        for group in hooks.get(event, []):
            if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
                groups.append(group)
                continue
            remaining = [hook for hook in group["hooks"] if not owned_hook(hook)]
            if remaining or not group["hooks"]:
                groups.append({**group, "hooks": remaining})
        if groups:
            hooks[event] = groups
        else:
            hooks.pop(event, None)
    owned = {}
    if "hook-gating" in capabilities:
        command = ["session-context", "--hook", "--role", role]
        if role == "lead":
            command += ["--name", values["lead_name"]]
        else:
            command += ["--name-prefix", values[f"{role}_name_prefix"]]
            if values[f"{role}_legacy_name"]:
                command += ["--name", values[f"{role}_legacy_name"]]
        if role != "director":
            command += ["--coordinator", values["coordinator_address"]]
        command += ["--handover", values["director_handover" if role == "director" else "coordinator_handover"],
                    "--handle", values["handle"]]
        drift = "role-drift" in capabilities
        if drift:
            for watch_path in watched(role, values["handle"], values.get("area")):
                command += ["--watch", watch_path]
        hook = {"type": "command", "command": shlex.join(command), "timeout": 30}
        owned["Stop"] = [{"hooks": [hook]}]
        owned["SessionStart"] = [{"hooks": [hook.copy()]} if drift else {"matcher": "compact", "hooks": [hook.copy()]}]
        if drift:
            owned["UserPromptSubmit"] = [{"hooks": [hook.copy()]}]
        reason = "hook-gating and role-drift available" if drift else "hook-gating available"
    elif role == "lead":
        owned["Stop"] = [{"hooks": [{"type": "command", "command": "session-context --hook", "timeout": 30}]}]
        reason = "PATH session-context lacks hook-gating; using the plain legacy Stop hook"
    else:
        reason = f"{role} hooks skipped: PATH session-context lacks hook-gating"
    for event, groups in owned.items():
        hooks.setdefault(event, []).extend(groups)
    if shutil.which("session-reap-hook") is not None:
        reap = {"type": "command", "command": shlex.join([
            "session-reap-hook", values[f"{role}_name"]]), "timeout": 2}
        for event in ("SessionStart", "SessionEnd"):
            hooks.setdefault(event, []).append({"hooks": [reap.copy()]})
    else:
        reason += "; reap hooks skipped: session-reap-hook absent from PATH"
    if not hooks:
        settings.pop("hooks")
    return path, settings, reason


def publish_settings(values, role, capabilities, dry_run):
    path, settings, reason = hook_settings(values, role, capabilities)
    print(f"settings={path}: {reason}")
    if dry_run:
        print(json.dumps(settings, indent=2), flush=True)
    else:
        atomic_json(path, settings)


def warmup_state_path():
    return Path.home() / ".local/state/session-start/warmups.json"


def warmup_records():
    path = warmup_state_path()
    records = json.loads(path.read_text()) if path.exists() else {}
    if not isinstance(records, dict):
        raise ValueError(f"invalid warm-up state: {path}")
    return records


def recent_warmup(values, sessions, role="coordinator"):
    records = warmup_records()
    for session in sessions:
        name = session.get("name", "")
        record = records.get(name, {})
        if (name.startswith(values[f"{role}_name_prefix"])
                and record.get("next") is True
                and time.time() - record.get("started_at", 0) < 7200
                and live_session(name, [session]) is not None):
            return name
    return None


def record_warmup(name, identifier, started_at):
    records = warmup_records()
    records[name] = {"next": True, "started_at": started_at, "session_id": identifier}
    atomic_json(warmup_state_path(), records)


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
