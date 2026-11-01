"""The public status page, live from the log (docs/design/fab-reports.md, 4)."""

from __future__ import annotations

import argparse
import html
import json
import math
import re
from collections import Counter
from collections.abc import Collection
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from fab import accounting, calls, channel, hosts as machines, log, logins, overlaps

DRAFT = re.compile(r"[a-z0-9][a-z0-9.-]{0,63}")
OUTCOMES = ("done", "question", "infra", "failed", "other")
ISSUES = "https://git.fabrig.ai/fabrig-ai/agents/issues?state=open&labels=1"

STYLE = """:root{color-scheme:light;--page:#f9f9f7;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#6f6d68;
--grid:#e1e0d9;--axis:#c3c2b7;--ring:rgba(11,11,11,.10);--run:#2a78d6;--wait:#eb6834;--info:#2a78d6;
--good:#0ca30c;--warning:#fab219;--critical:#d03b3b;--neutral:#898781;--code:#f0efec}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;--page:#0d0d0d;
--surface:#1a1a19;--ink:#f0efec;--ink2:#c3c2b7;--muted:#9a988f;--grid:#2c2c2a;--axis:#383835;
--ring:rgba(255,255,255,.10);--run:#3987e5;--wait:#d95926;--info:#3987e5;--code:#262624}}
:root[data-theme="dark"]{color-scheme:dark;--page:#0d0d0d;--surface:#1a1a19;--ink:#f0efec;--ink2:#c3c2b7;
--muted:#9a988f;--grid:#2c2c2a;--axis:#383835;--ring:rgba(255,255,255,.10);--run:#3987e5;--wait:#d95926;
--info:#3987e5;--code:#262624}
*{box-sizing:border-box}
a{color:var(--info)}
a.tile{color:inherit;text-decoration:none;display:block}
body{margin:0;background:var(--page);color:var(--ink);font:14px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1280px;margin:0 auto;padding:20px 16px 48px}
header{display:flex;flex-wrap:wrap;align-items:baseline;gap:6px 16px;margin-bottom:16px}
h1{font-size:22px;margin:0;font-weight:650}
h2{font-size:17px;margin:32px 0 10px;font-weight:650}
h3{font-size:14px;margin:20px 0 8px;font-weight:650}
h4{font-size:12px;margin:12px 0 4px;color:var(--ink2);font-weight:600;text-transform:uppercase;letter-spacing:.04em}
p{margin:6px 0}
.meta,.muted,.empty{color:var(--ink2)}
.empty{font-style:italic}
code{background:var(--code);padding:0 4px;border-radius:4px;font-size:12.5px;overflow-wrap:anywhere}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}
.tile,.card,.panel{background:var(--surface);border:1px solid var(--ring);border-radius:10px}
.tile{padding:12px 14px}
.tile .label{color:var(--ink2);font-size:12.5px}
.tile .value{font-size:28px;font-weight:650;margin:2px 0}
.tile .sub{color:var(--ink2);font-size:12px}
.panel{padding:4px 14px 12px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(330px,1fr));gap:10px}
.card{padding:4px 14px 12px}
.card ul{margin:2px 0;padding-left:0;list-style:none}
.card li{margin:3px 0}
.facts{color:var(--ink2);font-size:12.5px}
.scroll{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}
th,td{text-align:left;padding:6px 12px 6px 0;border-bottom:1px solid var(--grid);vertical-align:top;
white-space:nowrap}
td.wrap{white-space:normal;min-width:220px}
th{color:var(--ink2);font-weight:600;font-size:12.5px;white-space:nowrap}
td.num,th.num{text-align:right}
.badge{display:inline-flex;align-items:center;gap:5px;white-space:nowrap;font-size:12px;color:var(--ink);
border:1px solid var(--ring);border-radius:999px;padding:0 8px 0 6px;line-height:20px}
.badge i{width:8px;height:8px;border-radius:50%;background:var(--neutral)}
.badge.good i{background:var(--good)}.badge.warning i{background:var(--warning)}
.badge.critical i{background:var(--critical)}.badge.info i{background:var(--info)}
.meter{display:inline-block;width:80px;height:8px;background:var(--grid);border-radius:4px;overflow:hidden}
.meter i{display:block;height:100%;background:var(--info)}
.meter.warning i{background:var(--warning)}.meter.critical i{background:var(--critical)}
footer{margin-top:36px;color:var(--ink2);font-size:12.5px}"""


def _stamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        stamp = datetime.fromisoformat(value)
        return stamp.astimezone(timezone.utc) if stamp.tzinfo is not None else None
    except (ValueError, OverflowError):
        return None


def _draft(event: dict) -> str:
    task = event.get("into" if event.get("ev") == "branch.landed" and "into" in event else "task")
    return task.split("/", 1)[0] if isinstance(task, str) and "/" in task else ""


def _number(value: object) -> float | None:
    """Only finite numeric figures may enter the public snapshot."""
    return value if type(value) in (int, float) and math.isfinite(value) else None


def _limits(event: dict) -> list[dict]:
    """Rebuild the scalar lists, accepting only public window labels and finite figures."""
    columns = [event.get(key, []) for key in ("limit_names", "limit_used", "limit_resets")]
    if not all(isinstance(column, list) for column in columns) or len({len(c) for c in columns}) != 1:
        return []
    return [{"name": name, "used": _number(used), "resets": _number(resets)}
            for name, used, resets in zip(*columns)
            if isinstance(name, str) and re.fullmatch(r"[A-Za-z0-9 ()\[\]?]{1,46}", name)
            and "fable" not in name.lower()]


def _held_by(lent: list[logins.Login], hosts: Collection[str]) -> list[str]:
    """Sorted public labels, one per login with a holder, never custody details."""
    labels = []
    for login in lent:
        if login.holder is None:
            continue
        machine = logins.KINDS[login.kind].machine
        if machine and login.holder in hosts and login.path == machine:
            label = login.holder
        else:
            label = next((label for prefix, label in (("walk/", "QA walk"),
                                                      ("after-landing/", "after-landing"),
                                                      ("check/", "check"))
                          if login.holder.startswith(prefix)), "other")
        labels.append(label)
    return sorted(labels)


def _subscriptions(dated: list[tuple[dict, datetime]], now: datetime,
                   hosts: Collection[str]) -> list[dict]:
    """One subscription per account, with pace from its oldest usable window sample."""
    kinds, retired, checks, records = {}, set(), {}, []
    for event, stamp in sorted(dated, key=lambda pair: pair[1]):
        name = event.get("id")
        if not isinstance(name, str) or not re.fullmatch(r"(?:claude(?:-box)?|codex)-[0-9]+", name):
            continue
        records.append(event)
        ev = event.get("ev")
        if ev == "login.added" and event.get("kind") in ("claude", "claude-box", "codex"):
            kinds[name] = "claude" if event["kind"] == "claude-box" else event["kind"]
        elif ev == "login.retired":
            retired.add(name)
        elif ev == "login.checked":
            checks.setdefault(name, []).append((event, stamp))
    custody = logins.fold(records)
    groups = {}
    for name, samples in checks.items():
        event, stamp = samples[-1]
        email = event.get("email")
        if (name not in kinds or name in retired or (now - stamp).total_seconds() > 86400
                or event.get("error") or not isinstance(email, str) or not email):
            continue
        groups.setdefault((kinds[name], email), []).append(name)
    subscriptions = []
    for (kind, email), names in groups.items():
        samples = sorted((sample for name in names for sample in checks[name]
                          if not sample[0].get("error") and sample[0].get("email") == email),
                         key=lambda pair: pair[1])
        event, stamp = samples[-1]
        plan = event.get("plan")
        limits = []
        for limit in _limits(event):
            label, used, resets = limit["name"], limit["used"], limit["resets"]
            if label == "5 h" and (used is None or used <= 80):
                continue
            limit.update(rate_per_h=None, full_at=None, at_reset=None)
            if used is not None and resets is not None and resets > now.timestamp():
                for earlier, before in samples[:-1]:
                    elapsed = (stamp - before).total_seconds()
                    if elapsed < 1200:
                        continue
                    previous = next((sample for sample in _limits(earlier)
                                     if sample["name"] == label and sample["resets"] == resets
                                     and sample["used"] is not None), None)
                    if previous is None or previous["used"] > used:
                        continue
                    rate = (used - previous["used"]) * 3600 / elapsed
                    limit["rate_per_h"] = round(rate, 1)
                    full = stamp.timestamp() + (100 - used) * 3600 / rate if rate > 0 else None
                    if full is not None and full < resets:
                        limit["full_at"] = full
                    else:
                        limit["at_reset"] = round(used + rate * (resets - stamp.timestamp()) / 3600, 1)
                    break
            limits.append(limit)
        label = "***"
        parts = email.split("@")
        if len(parts) == 2 and all(parts):
            local, domain = parts
            label = f"{local[0]}***{local[-1] if len(local) > 2 else ''}@{domain.lower()}"
        held_by = _held_by([custody[name] for name in names], hosts)
        subscriptions.append({"subscription": label, "kind": kind, "logins": len(names),
                              "held": len(held_by), "held_by": held_by,
                              "plan": plan if isinstance(plan, str) and re.fullmatch(r"[a-z0-9_]{1,40}", plan)
                              else "",
                              "checked_age_s": int((now - stamp).total_seconds()),
                              "limits": limits})
    return sorted(subscriptions, key=lambda subscription: (subscription["kind"], subscription["subscription"]))


def _public_overlaps(dated: list[tuple[dict, datetime]], known_drafts: Collection[str]) -> list[dict]:
    """Open pairs as sorted public labels and file counts (docs/design/fab-integration.md, 4)."""
    pairs = []
    for pair, record in overlaps.open_pairs([event for event, _ in dated]).items():
        labels = sorted(name if name in known_drafts and DRAFT.fullmatch(name) else "other"
                        for name in pair)
        pairs.append({"drafts": labels, "count": len(record["files"]) + record["more"]})
    return sorted(pairs, key=lambda pair: pair["drafts"])


def snapshot(events: list[dict], now: datetime, hosts: Collection[str]) -> dict:
    """Public counts and ages at now, in UTC, with only known hosts, call roles and safe
    draft names. Skip invalid timestamps and future events; pair ids across the log,
    fold the user's log asks through channel.asks, and bound runs to 24 h and calls to
    calls.TIMEOUT. Include recent account subscriptions with masked emails and pace.
    Separate main landings from trunk merges; drafts come from run starts, with
    by-hand for main landings without a known draft.
    Today runs from UTC midnight through now. Only public fields leave the fold."""
    now = now.astimezone(timezone.utc)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    recent = now - timedelta(hours=24)
    call_cutoff = now - timedelta(seconds=calls.TIMEOUT)
    dated = [(event, stamp) for event in events
             if (stamp := _stamp(event.get("ts"))) is not None and stamp <= now]
    known_drafts = {_draft(event) for event, _ in dated if event.get("ev") == "run.started"}
    hour = now - timedelta(hours=1)
    runs, call_starts = {}, {}
    runs_ended, calls_ended = set(), set()
    by_host, by_role = Counter(), Counter()
    drafts = {}
    landed = {"last_hour": 0, "today": 0}
    merged = {"last_hour": 0, "today": 0}
    outcomes = dict.fromkeys(OUTCOMES, 0)
    rejected = 0
    codex = claude = 0.0
    last = None

    def count_draft(event: dict, figure: str) -> None:
        name = _draft(event)
        task = event.get("task")
        if (event.get("ev") == "branch.landed" and "into" not in event
                and (not isinstance(task, str) or "/" not in task or name not in known_drafts)):
            public = "by-hand"
        elif name in known_drafts:
            public = name if DRAFT.fullmatch(name) else "other"
        else:
            return
        counts = drafts.setdefault(public, {"runs_in_flight": 0, "landed_today": 0, "merged_today": 0})
        counts[figure] += 1

    for event, stamp in dated:
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
        elif kind == "call.started" and isinstance(call_id, str) and call_cutoff <= stamp:
            call_starts[call_id] = event
        elif kind == "call.ended":
            if isinstance(call_id, str):
                calls_ended.add(call_id)
            if stamp >= today:
                weight = accounting.call_weight(event)
                if weight is not None:
                    claude += weight
        elif kind == "branch.landed":
            counts = merged if "into" in event else landed
            if stamp >= hour:
                counts["last_hour"] += 1
            if stamp >= today:
                counts["today"] += 1
                count_draft(event, "merged_today" if "into" in event else "landed_today")
        elif kind == "branch.rejected" and stamp >= today:
            rejected += 1
    for run_id, event in runs.items():
        if run_id in runs_ended:
            continue
        host = event.get("host")
        by_host[host if isinstance(host, str) and host in hosts else "other"] += 1
        count_draft(event, "runs_in_flight")
    for call_id, event in call_starts.items():
        if call_id in calls_ended:
            continue
        role = event.get("role")
        by_role[role if isinstance(role, str) and role in calls.ROLES else "other"] += 1
    asks = channel.asks((), [event for event, _ in dated])
    by_kind = Counter(ask.kind for ask in asks)
    waiting_since = [_stamp(ask.since) for ask in asks]
    return {
        "updated": now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        "log": "ok",
        "last_event_age_s": max(0, int((now - last).total_seconds())) if last else None,
        "runs_in_flight": {"total": sum(by_host.values()), "by_host": dict(sorted(by_host.items()))},
        "calls_in_flight": {"total": sum(by_role.values()), "by_role": dict(sorted(by_role.items()))},
        "waiting_on_user": {
            "asks": len(asks), "by_kind": {kind: by_kind[kind] for kind in ("call", "parked", "finding")},
            "oldest_age_s": int((now - min(waiting_since)).total_seconds()) if waiting_since else None,
        },
        "landed": landed,
        "merged": merged,
        "rejected_today": rejected,
        "runs_ended_today": outcomes,
        "weight_today": {"codex_m": round(codex / accounting.MILLION, 1),
                         "claude_m": round(claude / accounting.MILLION, 1),
                         "ratio": round(codex / claude, 1) if claude else None},
        "drafts": dict(sorted(drafts.items())),
        "overlaps": _public_overlaps(dated, known_drafts),
        "subscriptions": _subscriptions(dated, now, hosts),
    }


def _age(seconds: int | None) -> str:
    if seconds is None:
        return "none"
    if seconds < 60:
        return f"{seconds} s"
    if seconds < 3600:
        return f"{seconds // 60} min"
    return f"{seconds // 3600} h"


def _duration(seconds: float) -> str:
    """Two adjacent units for a subscription countdown, rounded down to minutes."""
    minutes = max(0, int(seconds) // 60)
    if minutes >= 1440:
        return f"{minutes // 1440} d {minutes % 1440 // 60} h"
    if minutes >= 60:
        return f"{minutes // 60} h {minutes % 60} min"
    return f"{minutes} min"


def _text(value: object) -> str:
    """Escape a snapshot value for HTML text or attributes."""
    return html.escape(str(value))


def _badge(label: str, state: str) -> str:
    """Render an escaped state badge."""
    return f'<span class="badge {_text(state)}"><i></i>{_text(label)}</span>'


def _table(labels: tuple[str, ...], figures, *, badges: dict[str, str] | None = None) -> str:
    """Render escaped rows with numeric columns and optional first-column badges."""
    headings = []
    for index, label in enumerate(labels):
        headings.append(f'<th class="num">{_text(label)}</th>' if index else f"<th>{_text(label)}</th>")
    rows = []
    for values in figures:
        cells = []
        for index, value in enumerate(values):
            cell = _badge(value, badges[value]) if index == 0 and badges else _text(value)
            if index == 0 and labels == ("Kind", "Open"):
                cell = f'<a href="{_text(ISSUES)}">{cell}</a>'
            cells.append(f'<td class="num">{cell}</td>' if index else f"<td>{cell}</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return ('<div class="scroll"><table><thead><tr>' + "".join(headings) + '</tr></thead><tbody>'
            + "".join(rows) + '</tbody></table></div>')


def _overlaps_panel(pairs: list[dict]) -> str:
    """Render public overlap labels and counts after Drafts (docs/design/fab-integration.md, 4)."""
    body = (_table(("Drafts", "Files"), [(" · ".join(pair["drafts"]), pair["count"]) for pair in pairs])
            if pairs else '<p class="empty">No drafts overlap.</p>')
    return '<h2>Overlaps</h2><div class="panel">' + body + '</div>'


def _tile(label: str, value: object, sub: str = "") -> str:
    """Render an escaped count tile, linking waiting asks to their issues."""
    tag = "a" if label == "Waiting on the user" else "div"
    href = f' href="{_text(ISSUES)}"' if tag == "a" else ""
    return (f'<{tag} class="tile"{href}><div class="label">{_text(label)}</div>'
            f'<div class="value">{_text(value)}</div>'
            + (f'<div class="sub">{_text(sub)}</div>' if sub else "") + f"</{tag}>")


def _card(title: str, body: str) -> str:
    """Render a card with an escaped heading and an HTML body."""
    return f'<div class="card"><h3>{_text(title)}</h3>{body}</div>'


def _subscriptions_table(subscriptions: list[dict], now: datetime) -> str:
    """Render escaped subscriptions, custody and limits (docs/design/fab-reports.md, 4)."""
    if not subscriptions:
        return '<p class="empty">No login checked in the last 24 hours.</p>'
    rows = []
    for subscription in subscriptions:
        sign_ins = subscription["logins"]
        label = " · ".join(filter(None, (subscription["kind"].title(), subscription["plan"],
                                         subscription["subscription"],
                                         f"{sign_ins} sign-in" + ("s" if sign_ins != 1 else ""))))
        for index, limit in enumerate(subscription["limits"] or [{}]):
            used = limit.get("used")
            use = "–"
            if used is not None:
                state = " critical" if used >= 95 else " warning" if used >= 80 else ""
                use = (f'<span class="meter{state}"><i style="width:{max(0, min(100, used)):g}%"></i>'
                       f'</span> {used:g}%')
            if limit.get("name") and limit["name"] != "week":
                use += f' <small>· {_text(limit["name"])}</small>'
            reset = "–"
            if limit.get("resets") is not None:
                try:
                    when = datetime.fromtimestamp(limit["resets"], timezone.utc)
                except (ValueError, OverflowError, OSError):
                    pass
                else:
                    reset = (f'<time datetime="{when.strftime("%Y-%m-%dT%H:%M:%SZ")}" '
                             f'title="{when.strftime("%Y-%m-%d %H:%M UTC")}">'
                             f'in {_duration(limit["resets"] - now.timestamp())}</time>')
            rate = limit.get("rate_per_h")
            pace = "–"
            if limit.get("full_at") is not None:
                pace = "full in " + _duration(limit["full_at"] - now.timestamp())
            elif limit.get("at_reset") is not None:
                pace = f'lasts, {limit["at_reset"]:g}% at reset'
            held = (f'<span title="{_text(" · ".join(subscription["held_by"]) or "none")}">'
                    f'{subscription["held"]}</span>') if index == 0 else ""
            cells = (_text(label) if index == 0 else "", held, use,
                     reset, f"{rate:.1f}%/h" if rate is not None else "–", _text(pace))
            rows.append("<tr>" + "".join(f"<td>{cell}</td>" for cell in cells) + "</tr>")
    headings = ("Subscription", "Held", "Used", "Resets", "Rate", "At this pace")
    return ('<div class="scroll"><table><thead><tr>'
            + "".join(f"<th>{heading}</th>" for heading in headings)
            + '</tr></thead><tbody>' + "".join(rows) + '</tbody></table></div>')


def _tiles(snapshot: dict) -> str:
    """Render the overview tiles in status-page order (docs/design/fab-reports.md, 4)."""
    runs, active_calls = snapshot["runs_in_flight"], snapshot["calls_in_flight"]
    waiting, weights = snapshot["waiting_on_user"], snapshot["weight_today"]
    subscriptions = snapshot["subscriptions"]
    weekly = [limit["used"] for subscription in subscriptions
              for limit in subscription["limits"] if limit["name"] == "week" and limit["used"] is not None]
    return '<div class="tiles">' + "".join([
        _tile("Runs in flight", runs["total"],
              " · ".join(f"{host} {count}" for host, count in runs["by_host"].items())),
        _tile("Calls in flight", active_calls["total"],
              " · ".join(f"{role} {count}" for role, count in active_calls["by_role"].items())),
        _tile("Waiting on the user", waiting["asks"], f'oldest {_age(waiting["oldest_age_s"])}'),
        _tile("Landed on main today", snapshot["landed"]["today"],
              f'last hour {snapshot["landed"]["last_hour"]}'),
        _tile("Merged into a trunk today", snapshot["merged"]["today"],
              f'last hour {snapshot["merged"]["last_hour"]}'),
        _tile("Weight today · Codex/Claude",
              f'{weights["ratio"]:.1f}×' if weights["ratio"] is not None else "–",
              f'Codex {weights["codex_m"]:.1f}M · Claude {weights["claude_m"]:.1f}M'),
        _tile("Subscriptions", f"{max(weekly):g}%" if weekly else "–", f"{len(subscriptions)} subscriptions"),
    ]) + '</div>'


def _drafts_panel(draft_counts: dict) -> str:
    """Render draft activity and its empty state (docs/design/fab-reports.md, 4)."""
    drafts = []
    for name, counts in draft_counts.items():
        state = _badge("running", "info") if counts["runs_in_flight"] else _badge("idle", "neutral")
        drafts.append(f'<tr><td>{_text(name)}</td><td>{state}</td>'
                      f'<td class="num">{_text(counts["runs_in_flight"])}</td>'
                      f'<td class="num">{_text(counts["merged_today"])}</td>'
                      f'<td class="num">{_text(counts["landed_today"])}</td></tr>')
    draft_table = ('<div class="scroll"><table><thead><tr><th>Draft</th><th>State</th>'
                   '<th class="num">Runs in flight</th><th class="num">Merged today</th>'
                   '<th class="num">Landed today</th></tr></thead><tbody>'
                   + "".join(drafts) + '</tbody></table></div>')
    return ('<h2>Drafts</h2><div class="panel">'
            + (draft_table if drafts else '<p class="empty">No draft active today.</p>') + '</div>')


def render(snapshot: dict) -> str:
    """One escaped, self-refreshing HTML document of public counts and subscription limits,
    readable at phone width in light and dark; a fixed message when the log is unreadable."""
    updated = _stamp(snapshot["updated"])
    clock = updated.strftime("%H:%M UTC") if updated else snapshot["updated"]
    age = snapshot.get("last_event_age_s")
    last_event = f"last event {_age(age)} ago" if age is not None else "no events yet"
    header = ('<header><h1>Fabrig status</h1><span class="meta">'
              + _text(f"Updated {clock} · {last_event}") + '</span></header>')
    content = '<p class="empty">The event log is unreadable.</p>'
    if snapshot.get("log") == "ok":
        runs, active_calls = snapshot["runs_in_flight"], snapshot["calls_in_flight"]
        waiting = snapshot["waiting_on_user"]
        weights = snapshot["weight_today"]
        subscriptions = snapshot["subscriptions"]
        content = _tiles(snapshot)
        content += ('<h2>Waiting on the user</h2><div class="panel">'
                    + _table(("Kind", "Open"), [("Call questions", waiting["by_kind"]["call"]),
                                              ("Parked chains", waiting["by_kind"]["parked"]),
                                              ("Finding questions", waiting["by_kind"]["finding"])])
                    + f'<p class="facts">{_text("Oldest: " + _age(waiting["oldest_age_s"]))}</p>'
                    + f'<p><a href="{_text(ISSUES)}">Open the questions</a></p></div>')
        content += ('<h2>Subscriptions</h2><div class="panel">'
                    + _subscriptions_table(subscriptions, updated) + '</div>')
        content += _drafts_panel(snapshot["drafts"])
        content += _overlaps_panel(snapshot["overlaps"])
        ended = [(outcome, snapshot["runs_ended_today"][outcome]) for outcome in OUTCOMES]
        content += '<h2>Today</h2><div class="cards">' + "".join([
            _card("Runs ended", _table(("Outcome", "Runs"), ended,
                                      badges={"done": "good", "question": "warning", "infra": "neutral",
                                              "failed": "critical", "other": "neutral"})),
            _card("Landings", _table(("", "Last hour", "Today"), [
                ("Landed on main", snapshot["landed"]["last_hour"], snapshot["landed"]["today"]),
                ("Merged into a trunk", snapshot["merged"]["last_hour"], snapshot["merged"]["today"]),
                ("Rejected", "–", snapshot["rejected_today"]),
            ])),
            _card("Weight", _table(("", "Millions"), [
                ("Codex", f'{weights["codex_m"]:.1f}'), ("Claude", f'{weights["claude_m"]:.1f}'),
            ])),
        ]) + '</div>'
        content += '<h2>In flight</h2><div class="cards">' + "".join([
            _card("Codex runs by host", _table(("Host", "Runs"), runs["by_host"].items())
                  if runs["by_host"] else '<p class="empty">None.</p>'),
            _card("Claude calls by role", _table(("Role", "Calls"), active_calls["by_role"].items())
                  if active_calls["by_role"] else '<p class="empty">None.</p>'),
        ]) + '</div>'
    footer = ("<footer>From fab's event log on hel8; refreshes every 30 s. "
              'Release page: <a href="/v0.1.0.html">v0.1.0</a>.</footer>')
    return ("""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="30"><title>fab status</title>
<style>""" + STYLE + '</style></head><body><main>' + header + content + footer + '</main></body></html>')


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
