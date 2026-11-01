"""Logins: the machines' Claude and Codex sign-ins and QA's held logins (docs/design/machines.md, 3).

Every login rests in one shelf on the dispatcher's machine and is lent out: to a machine, at the
path its tools use, or to a run, at a path of the run's. Custody is the event log's `login.*`
records, folded by `fold`. A lent login is copied out and copied back: the copy last used is the
true one (both products refresh their tokens), so a lent login's shelf copy is only a
placeholder until it is returned. Credential bytes never pass through Python: tar, ssh and
sha256sum move and hash them, and every copy is checked by its digest at both ends.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import math
import os
import re
import shlex
import subprocess
import sys
import threading
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fab import hosts as fab_hosts
from fab import log
from fab.sh import Runner, run, ssh


@dataclass(frozen=True)
class Kind:
    item: str  # the login's name in its shelf entry
    machine: str = ""  # where a machine's tools use it, relative to HOME; "" for a run's login
    directory: bool = False
    fixed: str = ""  # the only lending path, relative to HOME, when its files name that path


KINDS = {
    "codex": Kind("auth.json", ".codex/auth.json"),
    "claude": Kind(".credentials.json", ".claude/.credentials.json"),
    "chatgpt": Kind("login"),  # temper's ChatGPT record: a live run's TEMPER_LIVE_ACCOUNT
    "claude-box": Kind("login", directory=True),  # a Claude Code directory: TEMPER_LIVE_CLAUDE
    # temper's GitHub conformance fixtures (TEMPER_LIVE_GITHUB_FIXTURES): app.json, the App's
    # app.pem and a person-<owner>.token per owner; neither refreshes.
    "github": Kind("login", directory=True),
    # smith's live root (SMITH_LIVE): config/smith/config.toml names the root absolutely,
    # host-id, tokens/chatgpt signed in by smith login chatgpt, and programs/claude.
    "smith-live": Kind("login", directory=True, fixed=".local/state/smith-live"),
}
# The machine logins each role uses: the dispatcher's calls and ops runs, a builder's runs.
NEEDS = {"dispatcher": ("claude", "codex"), "builder": ("claude", "codex")}

# Shared by every script: the digest of a file, or of a directory's files by relative path.
# A link is refused, so nothing is followed out of the login.
DIGEST = """
digest() {
  [ ! -L "$1" ] || { echo "fab logins: $1 is a link" >&2; return 3; }
  if [ -d "$1" ]; then
    (cd "$1" && find . -type f -print0 | LC_ALL=C sort -z | xargs -0r sha256sum) | sha256sum | cut -c1-64
  elif [ -f "$1" ]; then
    sha256sum < "$1" | cut -c1-64
  else
    echo "fab logins: $1 is missing" >&2; return 4
  fi
}
"""
# Drops the account Claude Code cached in ~/.claude.json (its settings, not the login), so the
# next start fetches the account of the login just lent; the rest of the file is kept.
FORGET_ACCOUNT = """
import json, os
path = os.path.expanduser("~/.claude.json")
try:
    settings = json.load(open(path))
except FileNotFoundError:
    raise SystemExit(0)
if settings.pop("oauthAccount", None) is not None:
    temporary = path + ".fab-new"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as out:
        json.dump(settings, out, indent=2)
    os.replace(temporary, path)
"""
SHA = re.compile(r"[0-9a-f]{64}")
PRELUDE = "set -euo pipefail; umask 077; cd ~\n" + DIGEST


def shelf_dir() -> Path:
    """FAB_LOGINS, or ~/src/fabrig/logins/shelf on the dispatcher's machine: entry ID is the
    directory `<shelf>/<ID>` (0700) holding the login under its kind's item name."""
    return Path(os.environ.get("FAB_LOGINS") or Path.home() / "src/fabrig/logins/shelf")


@dataclass
class Login:
    id: str
    kind: str
    origin: str  # where it came from: `<host>:<path>`
    sha: str  # the shelf copy's digest
    holder: str | None = None  # a machine's name or a run's id while lent
    host: str | None = None
    path: str | None = None  # on host, relative to its HOME unless absolute
    since: str | None = None
    email: str | None = None  # the account, from the last check
    plan: str | None = None
    used: float | None = None  # percent of the weekly limit, from the last check
    resets: int | None = None  # when the weekly window resets, Unix seconds
    checked: str | None = None
    error: str | None = None  # what the last check found wrong
    retired: str | None = None  # why it is no longer lent

    @property
    def free(self) -> bool:
        return self.holder is None and self.retired is None


def fold(records: Iterable[dict]) -> dict[str, Login]:
    """Each login's custody from the log's login.* records, in order; others are ignored."""
    logins: dict[str, Login] = {}
    for entry in records:
        ev, name = entry.get("ev"), entry.get("id")
        if ev == "login.added":
            logins[name] = Login(name, entry["kind"], entry.get("origin", ""), entry["sha"])
            continue
        login = logins.get(name)
        if login is None:
            continue
        if ev == "login.lent":
            login.holder, login.host, login.path = entry["holder"], entry["host"], entry["at"]
            login.since = entry["ts"]
        elif ev == "login.returned":
            login.sha, login.holder, login.host, login.path, login.since = entry["sha"], None, None, None, None
        elif ev == "login.checked":
            login.email, login.plan = entry.get("email"), entry.get("plan")
            login.used, login.resets, login.checked = entry.get("used"), entry.get("resets"), entry["ts"]
            login.error = entry.get("error")
        elif ev == "login.retired":
            login.retired, login.holder, login.host, login.path = entry.get("reason", ""), None, None, None
    return logins


class Refused(RuntimeError):
    """A login operation that would break custody; nothing was changed."""


class Shelf:
    """The dispatcher's side: every operation runs on the shelf's machine, under its lock."""

    def __init__(self, *, root: Path | None = None, hosts: Mapping[str, fab_hosts.Host] | None = None,
                 local: str | None = None, sh: Runner = run, log_path: Path | None = None):
        self.root = root or shelf_dir()
        self.hosts = fab_hosts.load() if hosts is None else hosts
        self.local = local if local is not None else fab_hosts.this_name(
            {name: host.hostname for name, host in self.hosts.items()})
        self.sh = sh
        self.log_path = log_path

    # Custody.

    def logins(self) -> dict[str, Login]:
        return fold(log.iterate(self.log_path))

    def login(self, name: str) -> Login:
        found = self.logins().get(name)
        if found is None:
            raise Refused(f"no login {name}")
        return found

    def _append(self, ev: str, **fields) -> dict:
        return log.append(ev, path=self.log_path, **fields)

    def _lock(self):
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        lock = open(self.root / ".lock", "a")
        fcntl.flock(lock, fcntl.LOCK_EX)
        return lock

    # Where scripts run.

    def _on(self, host: str, script: str) -> list[str]:
        """The argv running script with bash on host: here when host is this machine."""
        if host == self.local:
            return ["bash", "-c", script]
        if host not in self.hosts:
            raise Refused(f"no host {host} in hosts.toml")
        return ssh(self.hosts[host].ssh, ["bash", "-c", script])

    def _script(self, host: str, script: str, *, stdin_from: str | None = None) -> str:
        """Run script on host and return its stdout; stdin_from is a shell command run here
        whose output is piped in. A failure raises Refused with the script's last error line."""
        argv = self._on(host, PRELUDE + script)
        if stdin_from is not None:
            argv = ["bash", "-c", "set -o pipefail; " + stdin_from + " | " + shlex.join(argv)]
        result = self.sh(argv)
        if not result.ok:
            detail = (result.err.strip().splitlines() or [f"exit {result.code}"])[-1]
            raise Refused(f"on {host}: {detail}")
        return result.out.strip()

    def _entry(self, name: str) -> Path:
        return self.root / name

    # Transfers. Each checks digests at both ends before custody changes.

    def _pull(self, host: str, path: str, name: str, item: str) -> str:
        """Copy host's path into entry name as item, replacing the shelf copy only once the
        copy's digest equals the source's; return the digest."""
        source = self._script(host, f"digest {shlex.quote(path)}")
        if not SHA.fullmatch(source):
            raise Refused(f"on {host}: {path}'s digest is not a digest: {source[:80]!r}")
        parent, base = os.path.split(path)
        sender = self._on(host, PRELUDE + f"tar -C {shlex.quote(parent or '.')} -cf - -- {shlex.quote(base)}")
        entry = self._entry(name)
        self._script(self.local, f"""
entry={shlex.quote(str(entry))}; mkdir -p "$entry"; chmod 700 "$entry"
tmp=$(mktemp -d "$entry/.pull.XXXXXX"); trap 'rm -rf "$tmp"' EXIT
tar -C "$tmp" -xf -
[ "$(digest "$tmp"/{shlex.quote(base)})" = {source} ] || {{ echo "fab logins: the copy differs from {host}'s" >&2; exit 6; }}
if [ -d "$entry"/{shlex.quote(item)} ]; then
  old=$(mktemp -d "$entry/.old.XXXXXX"); mv "$entry"/{shlex.quote(item)} "$old"/
fi
mv -T "$tmp"/{shlex.quote(base)} "$entry"/{shlex.quote(item)}
[ -z "${{old:-}}" ] || rm -rf "$old"
""", stdin_from=shlex.join(sender))
        return source

    def _push(self, login: Login, host: str, path: str) -> None:
        """Copy the shelf copy to host's path, which must not exist; install it only once the
        copy's digest equals the shelf's, then check it again where it lies."""
        item = KINDS[login.kind].item
        entry = self._entry(login.id)
        found = self._script(self.local, f"digest {shlex.quote(str(entry / item))}")
        if found != login.sha:
            raise Refused(f"{login.id}: the shelf copy is not the one returned ({found[:12]}, not {login.sha[:12]})")
        sender = ["tar", "-C", str(entry), "-cf", "-", "--", item]
        self._script(host, f"""
dest={shlex.quote(path)}
[ ! -e "$dest" ] && [ ! -L "$dest" ] || {{ echo "fab logins: $dest exists; return its login first" >&2; exit 5; }}
mkdir -p "$(dirname "$dest")"
tmp=$(mktemp -d "$(dirname "$dest")/.fab-login.XXXXXX"); trap 'rm -rf "$tmp"' EXIT
tar -C "$tmp" -xf -
[ "$(digest "$tmp"/{shlex.quote(item)})" = {login.sha} ] || {{ echo "fab logins: the copy differs from the shelf's" >&2; exit 6; }}
if [ -d "$tmp"/{shlex.quote(item)} ]; then
  chmod 700 "$tmp"/{shlex.quote(item)}
  mv -T "$tmp"/{shlex.quote(item)} "$dest"
else
  ln "$tmp"/{shlex.quote(item)} "$dest"
fi
[ "$(digest "$dest")" = {login.sha} ]
""", stdin_from=shlex.join(sender))

    # Operations.

    def capture(self, host: str, kind: str, *, path: str | None = None, free: bool = False) -> Login:
        """Copy host's login of kind (at path, by default where the kind's machine use is) into a
        new entry. It stays lent to host, which goes on using it, unless free: then the caller
        has made sure the source is used no more (QA's custody holds it, its machine is gone)."""
        spec = KINDS.get(kind)
        if spec is None:
            raise Refused(f"no kind {kind}; kinds: {', '.join(KINDS)}")
        path = path or spec.machine
        if not path:
            raise Refused(f"a {kind} login has no machine path; name its --path")
        with self._lock():
            logins = self.logins()
            if not free and any(login.host == host and login.path == path for login in logins.values()):
                raise Refused(f"{host}:{path} is already a lent login's")
            number = 1 + max((int(name.rsplit("-", 1)[1]) for name, login in logins.items()
                              if login.kind == kind and name.rsplit("-", 1)[1].isdecimal()), default=0)
            name = f"{kind}-{number}"
            if self._entry(name).exists():
                raise Refused(f"{self._entry(name)} exists but the log has no {name}")
            sha = self._pull(host, path, name, spec.item)
            self._append("login.added", id=name, kind=kind, origin=f"{host}:{path}", sha=sha)
            if not free:
                self._append("login.lent", id=name, holder=host, host=host, at=path, sha=sha)
            return self.login(name)

    def lend(self, name: str, host: str, *, path: str | None = None, holder: str | None = None) -> Login:
        """Copy free login name to host at path (by default its kind's fixed or machine path,
        lent to the machine) for holder (a run's id; by default the machine)."""
        with self._lock():
            return self._lend(self.login(name), host, path, holder)

    def borrow(self, kind: str, host: str, *, path: str, holder: str) -> Login:
        """Lend the free login of kind with the lowest number to holder (a run) on host at path
        (empty for a kind's fixed path); Refused when none is free. Builders borrow over ssh."""
        if not path and kind in KINDS and not KINDS[kind].fixed:
            raise Refused(f"a {kind} login is lent to a run; name its --path")
        with self._lock():
            free = [login for login in self.logins().values() if login.kind == kind and login.free]
            if not free:
                raise Refused(f"no free {kind} login")
            first = min(free, key=lambda login: (len(login.id), login.id))
            return self._lend(first, host, path, holder)

    def _lend(self, login: Login, host: str, path: str | None, holder: str | None) -> Login:
        if not login.free:
            raise Refused(f"{login.id} is not free: " + (f"retired ({login.retired})" if login.retired is not None
                                                          else f"lent to {login.holder}"))
        spec = KINDS[login.kind]
        path = path or spec.fixed or spec.machine
        if spec.fixed:
            if path == f"~/{spec.fixed}":
                path = spec.fixed
            if path != spec.fixed:
                absolute = self._script(host, f'printf "%s/%s" "$HOME" {shlex.quote(spec.fixed)}')
                if path != absolute:
                    raise Refused(f"a {login.kind} login is lent only at ~/{spec.fixed}: its files name that path")
        if not path:
            raise Refused(f"a {login.kind} login is lent to a run; name its --path")
        self._push(login, host, path)
        if login.kind == "claude" and path == KINDS["claude"].machine:
            # Claude Code reports the account cached by the machine's previous login until it
            # fetches its own, which it does only when none is cached (11-01, three swaps).
            self._script(host, f"python3 -I -c {shlex.quote(FORGET_ACCOUNT)}")
        self._append("login.lent", id=login.id, holder=holder or host, host=host, at=path, sha=login.sha)
        return self.login(login.id)

    def give_back(self, name: str) -> Login:
        """Copy lent login name back from where it lies, then remove it there, if it has not
        changed since it was copied. Its consumer must have stopped."""
        with self._lock():
            login = self.login(name)
            if login.holder is None or login.host is None or login.path is None:
                raise Refused(f"{name} is not lent")
            sha = self._pull(login.host, login.path, name, KINDS[login.kind].item)
            self._script(login.host, f"""
[ "$(digest {shlex.quote(login.path)})" = {sha} ] || {{ echo "fab logins: {login.path} changed while it was returned; stop its user and return it again" >&2; exit 7; }}
rm -rf -- {shlex.quote(login.path)}
""")
            self._append("login.returned", id=name, sha=sha)
            return self.login(name)

    def swap(self, host: str, name: str) -> Login:
        """Give back the login of name's kind lent to host at its machine path, then lend name
        there. A failed lend leaves the machine without a login of that kind, and says so."""
        new = self.login(name)
        path = KINDS[new.kind].machine
        current = [login for login in self.logins().values() if login.host == host and login.path == path]
        if not new.free:
            raise Refused(f"{name} is not free")
        for login in current:
            self.give_back(login.id)
        try:
            return self.lend(name, host)
        except Refused as error:
            raise Refused(f"{host} has no {new.kind} login now: {error}") from error

    def retire(self, name: str, reason: str) -> Login:
        """Lend login name no more: expired, or lost with its machine."""
        with self._lock():
            self.login(name)
            self._append("login.retired", id=name, reason=reason)
            return self.login(name)

    def check(self, name: str) -> dict:
        """The account and limits of login name, by its product, recorded as login.checked.
        Every check makes a real request (which may refresh the login): `claude auth status`
        alone answers from the account a previous login left cached. A machine login lent to
        its machine is checked there in place; a free one is lent to this machine in a private
        directory and returned. A run's login is not checked."""
        login = self.login(name)
        spec = KINDS[login.kind]
        if login.kind not in ("codex", "claude", "claude-box"):
            raise Refused(f"a {login.kind} login has no check; its runs show whether it works")
        if login.holder is not None and login.host is not None and login.path == spec.machine:
            found = self._account(login.host, login.kind, validate=True)
        elif login.free:
            scratch = log.home() / "logins-check" / name
            path = str(scratch / spec.item) if login.kind != "claude-box" else str(scratch)
            self.sh(["rm", "-rf", str(scratch)])
            self.lend(name, self.local, path=path, holder=f"check/{name}")
            try:
                found = self._account(self.local, login.kind, home=path if spec.directory else str(scratch),
                                      validate=True)
            finally:
                self.give_back(name)
                self.sh(["rm", "-rf", str(scratch)])
        else:
            raise Refused(f"{name} is lent to {login.holder}; check it where it is used")
        fields = {key: found.get(key) for key in ("email", "plan", "used", "resets")}
        limits = found.get("limits", [])
        self._append("login.checked", id=name, **fields, error=found.get("error"),
                     limit_names=[limit["name"] for limit in limits],
                     limit_used=[limit["used"] for limit in limits],
                     limit_resets=[limit["resets"] for limit in limits])
        return found

    def _account(self, host: str, kind: str, *, home: str | None = None, validate: bool = False) -> dict:
        command = ["fab", "logins", "account", "claude" if kind == "claude-box" else kind]
        command += ["--home", home] if home else []
        command += ["--validate"] if validate else []
        if host == self.local:
            command[0] = str(Path(__file__).resolve().parents[1] / "bin/fab")
            argv = command
        else:
            argv = ssh(self.hosts[host].ssh, command)
        result = self.sh(argv, timeout=180)
        try:
            return json.loads(result.out.strip().splitlines()[-1])
        except (IndexError, json.JSONDecodeError):
            return {"error": (result.err.strip().splitlines() or [f"exit {result.code}"])[-1]}

    def missing(self) -> list[str]:
        """Each host's machine logins its roles need and no login is lent to it for."""
        lent = {(login.host, login.kind) for login in self.logins().values()
                if login.holder is not None and login.path == KINDS[login.kind].machine}
        return [f"{name}: no {kind} login" for name, host in self.hosts.items()
                for kind in sorted({kind for role in host.roles for kind in NEEDS.get(role, ())})
                if (name, kind) not in lent]


# The machine's side: what its products say about a login, never the login itself.

def account(kind: str, *, home: str | None = None, validate: bool = False) -> dict:
    """The account, weekly use and all limits of this machine's kind login (home: its
    CODEX_HOME or CLAUDE_CONFIG_DIR), by the product's own commands. validate makes a real
    request first, so an expired login says so (a Claude call of a few tokens; Codex refreshes
    its token). Claude's local /usage can fail independently, leaving limits empty."""
    env = dict(os.environ)
    if kind == "codex":
        if home:
            env["CODEX_HOME"] = home
        return _codex_account(env, validate)
    if home:
        env["CLAUDE_CONFIG_DIR"] = home
    if validate:
        done = subprocess.run(["claude", "-p", "Reply with the single word OK.", "--model", "claude-haiku-5-5",
                               "--output-format", "json"], capture_output=True, text=True, timeout=120,
                              env=env, cwd=home or None)
        try:
            answer = json.loads(done.stdout)
        except json.JSONDecodeError:
            answer = {"is_error": True, "result": (done.stderr.strip().splitlines() or ["no answer"])[-1]}
        if answer.get("is_error"):
            return {"error": str(answer.get("result"))[:200]}
    done = subprocess.run(["claude", "auth", "status", "--json"], capture_output=True, text=True, timeout=60, env=env)
    try:
        status = json.loads(done.stdout)
    except json.JSONDecodeError:
        return {"error": "claude auth status said nothing readable"}
    if not status.get("loggedIn"):
        return {"error": "not logged in"}
    found = {"email": status.get("email"), "plan": status.get("subscriptionType"), "limits": []}
    try:
        done = run(["claude", "-p", "/usage", "--output-format", "json",
                    "--no-session-persistence", "--strict-mcp-config", "--tools", "",
                    "--model", "claude-haiku-5-5", "--settings", '{"disableAllHooks": true}'],
                   timeout=60, env=dict(env, TZ="UTC"), cwd=home or None)
        answer = json.loads(done.out)
        if (not done.ok or not isinstance(answer, dict) or answer.get("is_error")
                or answer.get("local_command") != "usage" or _number(answer.get("num_turns")) != 0
                or _number(answer.get("total_cost_usd")) != 0):
            return found
        found["limits"] = _claude_limits(answer.get("result"), datetime.now(timezone.utc).timestamp())
    except (OSError, subprocess.TimeoutExpired, ValueError):
        pass  # A failed usage check does not discard the account from auth status.
    return found


def _number(value: object) -> float | None:
    """A finite product figure, never a boolean or free text."""
    return value if type(value) in (int, float) and math.isfinite(value) else None


def _claude_reset(value: str, now: float) -> float | None:
    """An English /usage reset in UTC, allowing the previous hour as the old page did."""
    match = re.fullmatch(r"(?:(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) ([0-9]{1,2}), )?"
                         r"([0-9]{1,2})(?::([0-9]{2}))?(am|pm)(?: \(UTC\))?", value)
    if not match:
        return None
    month, day, hour, minute, half = match.groups()
    hour, minute = int(hour), int(minute or 0)
    if not 1 <= hour <= 12 or minute > 59:
        return None
    hour = hour % 12 + (12 if half == "pm" else 0)
    today = datetime.fromtimestamp(now, timezone.utc)
    threshold = now - 3600
    if month:
        month = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split().index(month) + 1
        for year in range(today.year, today.year + 9):
            try:
                candidate = datetime(year, month, int(day), hour, minute, tzinfo=timezone.utc).timestamp()
            except ValueError:
                continue
            if candidate >= threshold:
                return candidate
        return None
    candidate = today.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate.timestamp() < threshold:
        candidate += timedelta(days=1)
    return candidate.timestamp()


def _claude_limits(result: object, now: float) -> list[dict]:
    """Only Current limit lines, with public window names and no Fable limits."""
    limits = []
    for line in result.splitlines() if isinstance(result, str) else ():
        match = re.fullmatch(r"Current ([A-Za-z0-9 ()\[\]]{1,40}): ([0-9]+(?:\.[0-9]+)?)% used"
                             r"(?: · resets (.*))?", line)
        if match:
            name, used, reset = match.groups()
            if "fable" in name.lower():
                continue
            name = {"session": "5 h", "week (all models)": "week"}.get(name, name)
            limits.append({"name": name, "used": _number(float(used)),
                           "resets": _claude_reset(reset, now) if reset else None})
    return limits


def _codex_limits(answer: dict) -> list[dict]:
    """Every bucket's primary and secondary windows, using fixed duration labels."""
    buckets = answer.get("rateLimitsByLimitId")
    buckets = [buckets[key] for key in sorted(buckets)] if buckets else [answer.get("rateLimits")]
    limits = []
    for bucket in buckets:
        if not isinstance(bucket, dict):
            continue
        prefix = "" if bucket.get("limitId") == "codex" else "other "
        for field in ("primary", "secondary"):
            window = bucket.get(field)
            if not isinstance(window, dict):
                continue
            minutes = _number(window.get("windowDurationMins"))
            name = "?"
            if minutes is not None and minutes > 0 and minutes == int(minutes):
                minutes = int(minutes)
                name = ("week" if minutes == 10080 else f"{minutes // 1440} d" if minutes % 1440 == 0
                        else f"{minutes // 60} h" if minutes % 60 == 0 else f"{minutes} min")
            limits.append({"name": prefix + name, "used": _number(window.get("usedPercent")),
                           "resets": _number(window.get("resetsAt"))})
    return limits


def _codex_account(env: dict, validate: bool) -> dict:
    """account/read and account/rateLimits/read from `codex app-server`, over its stdio JSON-RPC;
    a server that has not answered both in 90 s is killed."""
    answers: dict[int, dict] = {}
    with subprocess.Popen(["codex", "app-server"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL, text=True, env=env) as server:
        watchdog = threading.Timer(90, server.kill)
        watchdog.start()
        try:
            for message in ({"id": 1, "method": "initialize", "params": {"clientInfo": {"name": "fab", "version": "1"}}},
                            {"method": "initialized"},
                            {"id": 2, "method": "account/read", "params": {"refreshToken": validate}},
                            {"id": 3, "method": "account/rateLimits/read"}):
                server.stdin.write(json.dumps(message) + "\n")
            server.stdin.flush()
            for line in server.stdout:
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if message.get("id") in (2, 3):
                    answers[message["id"]] = message
                    if len(answers) == 2:
                        break
        finally:
            watchdog.cancel()
            server.kill()
    if len(answers) < 2:
        return {"error": "codex app-server did not answer"}
    for answer in answers.values():
        if "error" in answer:
            return {"error": str((answer["error"] or {}).get("message", answer["error"]))[:200]}
    who = ((answers.get(2) or {}).get("result") or {}).get("account") or {}
    windows = (answers[3].get("result") or {})
    limits = _codex_limits(windows)
    weekly = next((limit for limit in limits if limit["name"] == "week"), None)
    if weekly is None:
        primary = (windows.get("rateLimits") or {}).get("primary") or {}
        weekly = {"used": primary.get("usedPercent"), "resets": primary.get("resetsAt")}
    if not who:
        return {"error": "not logged in"}
    return {"email": who.get("email"), "plan": who.get("planType"), "used": weekly["used"],
            "resets": weekly["resets"], "limits": limits}


def table(logins: Iterable[Login]) -> list[str]:
    rows = [("id", "holder", "where", "account", "plan", "used", "checked")]
    for login in logins:
        where = f"{login.host}:{login.path}" if login.host else ("retired: " + login.retired if login.retired else "shelf")
        used = "" if login.used is None else f"{login.used:g}%"
        who = f"error: {login.error[:40]}" if login.error else login.email or ""
        rows.append((login.id, login.holder or "-", where, who, login.plan or "", used,
                     (login.checked or "")[:16]))
    widths = [max(len(row[column]) for row in rows) for column in range(len(rows[0]))]
    return ["  ".join(cell.ljust(width) for cell, width in zip(row, widths)).rstrip() for row in rows]


def main(argv: list[str]) -> int:
    """`fab logins list [--json]`, `capture HOST KIND [--path P] [--free]`, `lend ID HOST
    [--path P] [--holder RUN]`, `borrow KIND HOST [--path P] --holder RUN` (prints the id lent),
    `return ID`, `swap HOST ID`, `retire ID REASON`, `check ID... | --all`
    (on the shelf's machine); `account KIND [--home DIR] [--validate]` (on the login's)."""
    parser = argparse.ArgumentParser(prog="fab logins", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    listing = commands.add_parser("list")
    listing.add_argument("--json", action="store_true")
    capturing = commands.add_parser("capture")
    capturing.add_argument("host")
    capturing.add_argument("kind", choices=sorted(KINDS))
    capturing.add_argument("--path")
    capturing.add_argument("--free", action="store_true")
    lending = commands.add_parser("lend")
    lending.add_argument("id")
    lending.add_argument("host")
    lending.add_argument("--path")
    lending.add_argument("--holder")
    borrowing = commands.add_parser("borrow")
    borrowing.add_argument("kind", choices=sorted(KINDS))
    borrowing.add_argument("host")
    borrowing.add_argument("--path", default="")
    borrowing.add_argument("--holder", required=True)
    commands.add_parser("return").add_argument("id")
    swapping = commands.add_parser("swap")
    swapping.add_argument("host")
    swapping.add_argument("id")
    retiring = commands.add_parser("retire")
    retiring.add_argument("id")
    retiring.add_argument("reason")
    checking = commands.add_parser("check")
    checking.add_argument("id", nargs="*")
    checking.add_argument("--all", action="store_true")
    accounting = commands.add_parser("account")
    accounting.add_argument("kind", choices=["claude", "codex"])
    accounting.add_argument("--home")
    accounting.add_argument("--validate", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "check" and (bool(args.id) == args.all):
        parser.error("check requires IDs or --all")
    if args.command == "account":
        print(json.dumps(account(args.kind, home=args.home, validate=args.validate), sort_keys=True))
        return 0
    shelf = Shelf()
    try:
        if args.command == "list":
            logins = sorted(shelf.logins().values(), key=lambda login: (login.kind, len(login.id), login.id))
            if args.json:
                for login in logins:
                    print(json.dumps(asdict(login), sort_keys=True))
            else:
                print("\n".join(table(logins) + shelf.missing()))
            return 0
        if args.command == "capture":
            done = shelf.capture(args.host, args.kind, path=args.path, free=args.free)
        elif args.command == "lend":
            done = shelf.lend(args.id, args.host, path=args.path, holder=args.holder)
        elif args.command == "borrow":
            print(shelf.borrow(args.kind, args.host, path=args.path, holder=args.holder).id)
            return 0
        elif args.command == "return":
            done = shelf.give_back(args.id)
        elif args.command == "swap":
            done = shelf.swap(args.host, args.id)
        elif args.command == "retire":
            done = shelf.retire(args.id, args.reason)
        else:
            failed = 0
            names = ([login.id for login in shelf.logins().values()
                      if login.kind in ("codex", "claude", "claude-box")] if args.all else args.id)
            for name in names:
                try:
                    found = shelf.check(name)
                except Refused:
                    if not args.all:
                        raise
                    print(json.dumps({"id": name, "skipped": True}, sort_keys=True))
                    continue
                failed += "error" in found
                print(json.dumps({"id": name, **found}, sort_keys=True))
            return 0 if args.all else (1 if failed else 0)
    except Refused as error:
        print(f"fab logins: {error}", file=sys.stderr)
        return 1
    print("\n".join(table([done])[1:]))
    return 0
