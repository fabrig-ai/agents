"""The user's questions as forge issues (docs/design/channel.md, 3)."""

from __future__ import annotations

import argparse
import fcntl
import json
import sys
import urllib.request
from collections.abc import Callable, Sequence
from http.client import HTTPException
from pathlib import Path

from fab import calls, channel, log, units
from fab.sh import Failed, Runner, run

API = "http://127.0.0.1:3000/api/v1"
WEB = "https://git.fabrig.ai"
REPOSITORY = "fabrig-ai/agents"
LABEL = 1
USER = "free"
TOKEN = ".config/fab/forgejo.token"  # relative to HOME; never copied into a brief or log
ISSUES = f"/repos/{REPOSITORY}/issues"
PAGE_SIZE = 50
FOOTER = ("Answer in a comment. Ask for more context if you need it: the loop replies here. "
          "Your answer is recorded once the loop reads it as one.")
UNREADABLE = "The loop could not read this comment; it will retry on your next comment."


class ForgeError(Exception):
    """A forge failure carrying only the request's method and path."""


def request(method: str, path: str, payload: dict | None = None) -> dict | list:
    """Make one authenticated JSON request; failures expose only method and API path.

    Read the bot token from HOME/TOKEN. Never print response bodies, exception text or
    headers: a forge or connection error could contain the token. No redirects: the
    Authorization header belongs only to the local API.
    """
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    try:
        token = (Path.home() / TOKEN).read_text(encoding="utf-8").strip()
        if not token:
            raise ValueError("empty token")
        encoded = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(API + path, data=encoded, method=method,
                                     headers={"Authorization": f"token {token}",
                                              "Content-Type": "application/json"})
        with urllib.request.build_opener(NoRedirect()).open(req, timeout=30) as response:
            result = json.load(response)
        if not isinstance(result, (dict, list)):
            raise ValueError("expected JSON object or list")
        return result
    except (OSError, ValueError, HTTPException):
        raise ForgeError(f"{method} {path}") from None


def question(ask: channel.Ask) -> str:
    """The report excerpt, prefixed by a parked reason or finding question (13.6)."""
    if ask.kind == "parked" and not ask.report:
        return ask.text
    quoted = channel.excerpt(Path(ask.report)) if ask.report else "(report missing)"
    return f"{ask.text}\n\n{quoted}" if ask.kind in ("parked", "finding") else quoted


def reply_brief(ask: channel.Ask, thread: Sequence[dict]) -> str:
    """The reply role, call facts placeholder, question, report path and thread through this comment.

    Thread blocks preserve author, time and body; callers omit later comments so a
    decision cannot be attributed to a comment that has not been processed yet.
    """
    blocks = [f"**{entry['user']['login']}** ({entry.get('created_at', '-')}): {entry['body']}"
              for entry in thread]
    read = f"Read: {ask.report}\n\n" if ask.report or ask.kind != "parked" else ""
    return (calls.ROLES["reply"].read_text(encoding="utf-8") +
            "\n\n# Call facts\n\n(assigned at start)\n\n# Question\n\n" +
            f"Subject: {ask.subject}\n\n{question(ask)}\n\n" + read +
            "# Issue thread\n\n" + "\n\n".join(blocks) + "\n")


def reply_result(result: dict) -> tuple[str, str]:
    """Return (reply or answer, text) only for a done call's strict report; else ('', '')."""
    if result.get("outcome") != "done":
        return "", ""
    try:
        lines = Path(result["report"]).read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError, KeyError):
        return "", ""
    if len(lines) < 3 or lines[1] != "" or lines[0] not in ("Done: reply", "Done: answer"):
        return "", ""
    text = "\n".join(lines[2:]).strip()
    kind = lines[0].removeprefix("Done: ")
    if not text or (kind == "answer" and any(not line.strip() for line in text.splitlines())):
        return "", ""
    return kind, " ".join(text.split()) if kind == "answer" else text


def _opened(events: Sequence[dict]) -> list[dict]:
    closed = {entry["number"] for entry in events if entry.get("ev") == "issue.closed"}
    return [entry for entry in events
            if entry.get("ev") == "issue.opened" and entry["number"] not in closed]


def _needs_issue(ask: channel.Ask, events: Sequence[dict]) -> bool:
    """Compare log positions so a close and a fresh ask may share a timestamp."""
    latest = next((entry for entry in reversed(events)
                   if entry.get("ev") == "issue.opened" and entry.get("subject") == ask.subject), None)
    if latest is None:
        return True
    closed = next((index for index, entry in reversed(list(enumerate(events)))
                   if entry.get("ev") == "issue.closed" and entry.get("number") == latest["number"]), None)
    if closed is None:
        return False
    for index, entry in enumerate(events):
        if index <= closed or entry.get("call") != ask.call:
            continue
        if ask.kind == "finding":
            if (entry.get("ev") == "finding.triaged"
                    and entry.get("finding") == ask.subject.rsplit("/", 1)[-1]
                    and entry.get("decision") in ("user", "brief", "path")
                    and entry.get("question") == ask.text):
                return True
        elif entry.get("subject") == ask.subject:
            if (entry.get("ev") == "call.parked" if ask.kind == "parked" else
                    entry.get("ev") == "call.ended" and entry.get("outcome") == "question"):
                return True
    return False


def _comments(number: int, api: Callable) -> list[dict]:
    comments = []
    page = 1
    while True:
        path = f"{ISSUES}/{number}/comments?page={page}&limit={PAGE_SIZE}"
        batch = api("GET", path)
        if not isinstance(batch, list) or any(
                not isinstance(entry, dict) or type(entry.get("id")) is not int
                or not isinstance(entry.get("body"), str) or not isinstance(entry.get("user"), dict)
                or not isinstance(entry["user"].get("login"), str) for entry in batch):
            raise ForgeError(f"GET {path}")
        comments.extend(batch)
        if len(batch) < PAGE_SIZE:
            return sorted(comments, key=lambda entry: entry["id"])
        page += 1


def _converse(issue: dict, ask: channel.Ask, repo: Path, api: Callable, sh: Runner,
              log_path: Path | None) -> None:
    number = issue["number"]
    comments = _comments(number, api)
    seen = {entry["comment"] for entry in log.read(log_path)
            if entry.get("ev") == "issue.comment" and entry.get("number") == number}
    thread = [dict(user=dict(login="loop"), created_at=issue["ts"], body=question(ask))]
    for comment in comments:
        thread.append(comment)
        if comment["user"]["login"] != USER or comment["id"] in seen:
            continue
        # A hand answer or a previous comment's answer ends this conversation.
        if not any(item.subject == ask.subject for item in channel.asks((), log.read(log_path))):
            break
        seen.add(comment["id"])
        log.append("issue.comment", path=log_path, number=number, subject=ask.subject,
                   comment=comment["id"])
        result = {}
        try:
            result = calls.start("reply", f"issues/{number}", repo, reply_brief(ask, thread),
                                 sh=sh, log_path=log_path)
            kind, text = reply_result(result)
        except (OSError, ValueError, Failed):
            kind, text = "", ""
        if kind == "answer":
            try:
                channel.answer(ask.subject, text, log.read(log_path), by="user", log_path=log_path)
            except ValueError:
                kind, text = "", ""
            else:
                api("POST", f"{ISSUES}/{number}/comments", {"body": "Recorded as your answer: " + text})
                break
        body = text if kind == "reply" else UNREADABLE
        api("POST", f"{ISSUES}/{number}/comments", {"body": body})
        fields = {} if kind == "reply" else {"outcome": "failed"}
        log.append("issue.replied", path=log_path, number=number, call=result.get("call", ""), **fields)
        thread.append(dict(user=dict(login="loop"), created_at=log.now(), body=body))


def sync(repo: Path | None = None, *, api: Callable | None = None, sh: Runner = run,
         log_path: Path | None = None) -> int:
    """Open, converse and close once under FAB_HOME/issues.lock; a busy pass exits 0.

    The event log is the only state. Record each completed step, and consume a user
    comment before its call so failures are retried only on the user's next comment.
    A forge failure stops with exit 1 and one sanitized line naming the step and request.
    Calls run sequentially against the installed agents clone unless repo is supplied.
    """
    api = request if api is None else api
    repo = Path(__file__).resolve().parent.parent if repo is None else repo
    log.home().mkdir(parents=True, exist_ok=True)
    step = "open"
    with open(log.home() / "issues.lock", "a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0
        try:
            events = log.read(log_path)
            # Asks for one subject share one conversation, using the newest ask.
            asks = {ask.subject: ask for ask in channel.asks((), events)}
            for ask in asks.values():
                if not _needs_issue(ask, events):
                    continue
                text = question(ask)
                first = next(line.strip() for line in text.splitlines() if line.strip())
                read = f"Read: {ask.report}\n\n" if ask.report or ask.kind != "parked" else ""
                created = api("POST", ISSUES, {"title": f"{ask.subject}: {first}"[:200],
                              "body": f"{text}\n\n{read}{FOOTER}", "labels": [LABEL]})
                if not isinstance(created, dict) or type(created.get("number")) is not int:
                    raise ForgeError(f"POST {ISSUES}")
                number = created["number"]
                events.append(log.append("issue.opened", path=log_path, subject=ask.subject,
                              kind=ask.kind, number=number, url=f"{WEB}/{REPOSITORY}/issues/{number}"))
            step = "converse"
            for issue in _opened(events):
                ask = asks.get(issue["subject"])
                if ask is not None:
                    _converse(issue, ask, repo, api, sh, log_path)
            step = "close"
            events = log.read(log_path)
            subjects = {ask.subject for ask in channel.asks((), events)}
            for issue in _opened(events):
                if issue["subject"] in subjects:
                    continue
                number = issue["number"]
                api("POST", f"{ISSUES}/{number}/comments", {"body": "Answered; closing."})
                api("PATCH", f"{ISSUES}/{number}", {"state": "closed"})
                log.append("issue.closed", path=log_path, number=number, subject=issue["subject"])
            return 0
        except ForgeError as error:
            print(f"fab issues: {step}: {error}", file=sys.stderr)
            return 1
        except OSError:
            print(f"fab issues: {step}: local I/O failed", file=sys.stderr)
            return 1


def main(argv: list[str]) -> int:
    """Install the issue timer, or run one local sync pass."""
    parser = argparse.ArgumentParser(prog="fab issues", description=__doc__)
    parser.add_argument("command", nargs="?", choices=("sync",))
    parser.add_argument("--install", action="store_true")
    try:
        args = parser.parse_args(argv)
        if args.install:
            if args.command is not None:
                parser.error("--install takes no command")
            return units.cli_install("issues", units.issues_units(),
                                     primary="fab-issues.timer", restartable=False)
        if args.command is None:
            parser.error("a command is required without --install")
    except SystemExit as error:
        return error.code
    except (OSError, ValueError, Failed) as error:
        print("fab issues: " + " ".join(str(error).splitlines()), file=sys.stderr)
        return 1
    return sync()
