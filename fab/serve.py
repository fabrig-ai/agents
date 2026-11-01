"""The public status page, live from the log (docs/design/fab.md, 13.14)."""

from __future__ import annotations

import argparse
import html
import json
import re
from collections import Counter
from collections.abc import Collection
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from fab import accounting, calls, hosts as machines, log

DRAFT = re.compile(r"[a-z0-9][a-z0-9.-]{0,63}")
OUTCOMES = ("done", "question", "infra", "failed", "other")


def _stamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        stamp = datetime.fromisoformat(value)
        return stamp.astimezone(timezone.utc) if stamp.tzinfo is not None else None
    except (ValueError, OverflowError):
        return None


def _draft(event: dict) -> str:
    task = event.get("task")
    name = task.split("/", 1)[0] if isinstance(task, str) and "/" in task else ""
    return name if DRAFT.fullmatch(name) else "other"


def snapshot(events: list[dict], now: datetime, hosts: Collection[str]) -> dict:
    """Public counts and ages at now, in UTC, with only known hosts, call roles and safe
    draft names. Skip invalid timestamps and future events; pair ids across the log,
    fold questions and parked subjects in log order, and bound in-flight starts to 24 h.
    Today runs from UTC midnight through now. No event fields leave the fold."""
    now = now.astimezone(timezone.utc)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    recent = now - timedelta(hours=24)
    hour = now - timedelta(hours=1)
    runs, call_starts = {}, {}
    runs_ended, calls_ended = set(), set()
    questions, parked = {}, {}
    by_host, by_role = Counter(), Counter()
    drafts = {}
    landed = {"last_hour": 0, "today": 0}
    outcomes = dict.fromkeys(OUTCOMES, 0)
    rejected = 0
    codex = claude = 0.0
    last = None

    def draft_counts(event: dict) -> dict:
        return drafts.setdefault(_draft(event), {"runs_in_flight": 0, "landed_today": 0})

    for event in events:
        stamp = _stamp(event.get("ts"))
        if stamp is None or stamp > now:
            continue
        last = stamp
        kind = event.get("ev")
        run_id, call_id = event.get("run"), event.get("call")
        if kind == "run.started" and isinstance(run_id, str) and recent <= stamp:
            runs[run_id] = event
        elif kind == "run.ended":
            if isinstance(run_id, str):
                runs_ended.add(run_id)
            if stamp >= today:
                outcome = event.get("outcome")
                outcomes[outcome if isinstance(outcome, str) and outcome in outcomes else "other"] += 1
                weight = accounting.run_weight(event)
                if weight is not None:
                    codex += weight
        elif kind == "call.started" and isinstance(call_id, str) and recent <= stamp:
            call_starts[call_id] = event
        elif kind == "call.ended":
            if isinstance(call_id, str):
                calls_ended.add(call_id)
            if stamp >= today:
                weight = accounting.call_weight(event)
                if weight is not None:
                    claude += weight
        elif kind in ("question.asked", "question.answered", "call.parked", "call.answered"):
            waiting = questions if kind.startswith("question.") else parked
            subject = event.get("task" if kind.startswith("question.") else "subject")
            if isinstance(subject, str) and subject:
                if kind in ("question.asked", "call.parked"):
                    waiting[subject] = stamp
                else:
                    waiting.pop(subject, None)
        elif kind == "branch.landed":
            if stamp >= hour:
                landed["last_hour"] += 1
            if stamp >= today:
                landed["today"] += 1
                draft_counts(event)["landed_today"] += 1
        elif kind == "branch.rejected" and stamp >= today:
            rejected += 1

    for run_id, event in runs.items():
        if run_id in runs_ended:
            continue
        host = event.get("host")
        by_host[host if isinstance(host, str) and host in hosts else "other"] += 1
        draft_counts(event)["runs_in_flight"] += 1
    for call_id, event in call_starts.items():
        if call_id in calls_ended:
            continue
        role = event.get("role")
        by_role[role if isinstance(role, str) and role in calls.ROLES else "other"] += 1
    waiting_since = [*questions.values(), *parked.values()]
    return {
        "updated": now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        "log": "ok",
        "last_event_age_s": max(0, int((now - last).total_seconds())) if last else None,
        "runs_in_flight": {"total": sum(by_host.values()), "by_host": dict(sorted(by_host.items()))},
        "calls_in_flight": {"total": sum(by_role.values()), "by_role": dict(sorted(by_role.items()))},
        "waiting_on_user": {
            "questions": len(questions), "parked_calls": len(parked),
            "oldest_age_s": int((now - min(waiting_since)).total_seconds()) if waiting_since else None,
        },
        "landed": landed,
        "rejected_today": rejected,
        "runs_ended_today": outcomes,
        "weight_today": {"codex_m": round(codex / accounting.MILLION, 1),
                         "claude_m": round(claude / accounting.MILLION, 1)},
        "drafts": dict(sorted(drafts.items())),
    }


def _age(seconds: int | None) -> str:
    if seconds is None:
        return "none"
    if seconds < 60:
        return f"{seconds} s"
    if seconds < 3600:
        return f"{seconds // 60} min"
    return f"{seconds // 3600} h"


def render(snapshot: dict) -> str:
    """One escaped, self-refreshing HTML document of the public snapshot's counts,
    readable at phone width in light and dark; a fixed message when the log is unreadable."""
    def text(value: object) -> str:
        return html.escape(str(value))

    def rows(figures) -> str:
        return "<dl>" + "".join(f"<dt>{text(label)}</dt><dd>{text(value)}</dd>"
                               for label, value in figures) + "</dl>"

    def section(title: str, body: str) -> str:
        return f"<section><h2>{text(title)}</h2>{body}</section>"

    content = "<p>Log unreadable</p>"
    if snapshot.get("log") == "ok":
        runs, active_calls = snapshot["runs_in_flight"], snapshot["calls_in_flight"]
        waiting = snapshot["waiting_on_user"]
        content = section("Now", rows([
            ("Last event", _age(snapshot["last_event_age_s"])),
            ("Runs in flight", runs["total"]), *runs["by_host"].items(),
            ("Calls in flight", active_calls["total"]), *active_calls["by_role"].items(),
        ]))
        content += section("Waiting on the user", rows([
            ("Questions", waiting["questions"]), ("Parked calls", waiting["parked_calls"]),
            ("Oldest", _age(waiting["oldest_age_s"])),
        ]))
        content += section("Today", rows([
            ("Landed in the last hour", snapshot["landed"]["last_hour"]),
            ("Landed today", snapshot["landed"]["today"]),
            ("Rejected", snapshot["rejected_today"]),
            *((f"Runs ended: {outcome}", snapshot["runs_ended_today"][outcome]) for outcome in OUTCOMES),
            ("Codex weight (millions)", f'{snapshot["weight_today"]["codex_m"]:.1f}'),
            ("Claude weight (millions)", f'{snapshot["weight_today"]["claude_m"]:.1f}'),
        ]))
        content += section("Drafts", "".join(
            f"<h3>{text(name)}</h3>" + rows([("Runs in flight", counts["runs_in_flight"]),
                                            ("Landed today", counts["landed_today"])])
            for name, counts in snapshot["drafts"].items()) or "<p>none</p>")
    return """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="30"><title>fab status</title>
<style>
:root { color-scheme: light dark; background: #fafafa; color: #222; }
body { font: 1rem/1.5 system-ui, sans-serif; max-width: 42rem; margin: auto; padding: 1rem; }
section { border-top: 1px solid #888; margin-top: 1.5rem; }
dl { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: .4rem 1rem; }
dt, h3 { overflow-wrap: anywhere; } dd { margin: 0; font-variant-numeric: tabular-nums; }
@media (prefers-color-scheme: dark) { :root { background: #181818; color: #eee; } }
</style></head><body><h1>fab status</h1>""" + f"<p>Updated {text(snapshot['updated'])}</p>{content}</body></html>"


class _Request(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # Requests can contain private paths and query strings.

    def _reply(self, code: int, content_type: str, body: str) -> None:
        encoded = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type + "; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        if code == 405:
            self.send_header("Allow", "GET")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(encoded)

    def __getattr__(self, name):
        if name.startswith("do_"):
            return lambda: self._reply(405, "text/plain", "method not allowed")
        raise AttributeError(name)

    def do_GET(self):
        now = datetime.now(timezone.utc)
        try:
            events = log.read()
        except OSError:
            current = {"updated": now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
                       "log": "unreadable"}
        else:
            try:
                hosts = machines.load().keys()
            except (OSError, ValueError, TypeError):
                hosts = ()
            current = snapshot(events, now, hosts)
        path = self.path.split("?", 1)[0]
        if path == "/":
            self._reply(200, "text/html", render(current))
        elif path == "/api/status":
            self._reply(200, "application/json", json.dumps(current, ensure_ascii=True))
        elif path == "/healthz":
            self._reply(200, "text/plain", "ok")
        else:
            self._reply(404, "text/plain", "not found")


def main(argv: list[str]) -> int:
    """Serve the read-only public page until interrupted; print the actual bound address."""
    parser = argparse.ArgumentParser(prog="fab serve", description=__doc__)
    parser.add_argument("--port", type=int, default=8370)
    parser.add_argument("--bind", default="127.0.0.1")
    args = parser.parse_args(argv)
    with ThreadingHTTPServer((args.bind, args.port), _Request) as server:
        print(f"serving on http://{args.bind}:{server.server_port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0
