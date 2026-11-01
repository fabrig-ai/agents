"""The user's channel: the user's questions and the daily reports on one page (docs/design/channel.md, 2).

What is the user's is decided by whoever asks, never here: a plan's `[[question]]` without
an answer (the cut's), a call that ended `Question:`, a chain referred by settle or
parked when settlement failed, or a QA finding with a triage question. `asks` folds the
open ones from the plans and the log. The page,
FAB_HOME/PAGE on hel8, lists them with what to read and how to answer, then each standing
report's latest day with its signals. An answer comes back as `call.answered`, which names a
call's subject and never a task; every later call of the subject carries it in its brief.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from fab import atomic, findings, fixes, log, plan, tier_reds, triage, wake, walks
from fab.plan import Plan
from fab.report import LANDING
from fab.sh import Failed


def _deferred_editions(loaded: Plan, directory: Path) -> dict[str, str]:
    """Bind the edition reader after walks finishes importing this module first."""
    global read_editions
    from fab.walks import editions as read_editions
    return read_editions(loaded, directory)


# Keep an independent reader binding; walks may still be importing channel.
read_editions = getattr(walks, "editions", _deferred_editions)

PAGE = "user.md"  # the page, under FAB_HOME
PLANS = "plans"  # FAB_HOME/plans: the ticked plans' directories, one per line (tick.md 5)
KINDS = ("plan", "call", "parked", "finding")  # sources of the user's questions (channel.md 2)
QUESTION_LINES = 12  # lines of an asking report the page quotes
ANSWERED = "call.answered"  # the user's answer to a subject's open asks
SIGNALS = "## Signals"  # the standing reports' signals heading (fab.code_report, fab.landing_report)
SECTION = "# The user's answers"  # the brief section that carries a subject's answers


@dataclass(frozen=True)
class Ask:
    """One open question of the user's, as asks folds it."""

    kind: str  # one of KINDS
    draft: str  # the plan's draft; for log asks, the subject before its first `/`
    subject: str  # log asks: what `fab page answer` names; plan: the question's id
    text: str  # plan or finding: the question; parked: the reason; call: "" (in its report)
    since: str  # the ts it was asked (its call.ended or call.parked); "" for a plan's question
    call: str = ""  # call or finding: the asking call; parked: the chain's root; plan: ""
    report: str = ""  # what to read: call, FAB_HOME/calls/<call>/report.md; parked, the
    # call.parked's report (may be ""); finding, its walk report; plan, the plan.toml's path
    parts: tuple[str, ...] = ()  # plan: the parts that wait for it


@dataclass(frozen=True)
class Signal:
    """An open signal's page block, folded from the log (docs/design/channel.md, 2)."""

    id: str
    what: str
    since: str
    facts: tuple[str, ...]
    read: str
    clearable: bool


@dataclass(frozen=True)
class Report:
    """A standing report's latest day under FAB_HOME/reports."""

    name: str  # a draft, or fab.report.LANDING
    day: str  # "YYYY-MM-DD"
    path: Path
    signals: tuple[str, ...]  # its Signals section's lines, as signal_lines read them


def asks(plans: Sequence[tuple[Plan, Path]], events: Iterable[dict]) -> list[Ask]:
    """Every open question of the user's: the plans' first, then the log's.

    plans: (plan, the path of its plan.toml), in the order given. Each question of
    plan.questions whose answer is empty (after strip) gives Ask("plan", plan.draft,
    question.id, question.text, "", report=str(path), parts=question.parts), in plan order.

    The log's, walking events once in log order and keyed by (kind, subject), so a subject
    has at most one open ask of each kind:
    - a call.ended with outcome question and a subject, except amend and settle, opens
      Ask("call", <draft>, subject, "", ts, call=<call>,
      report=str(fab.log.home() / "calls" / <call> / "report.md"));
    - a call.parked with a subject opens Ask("parked", <draft>, subject, <reason>, ts,
      call=<its call>, report=<its report, or "">);
    - opening a key already open replaces its ask, which moves to the end of the order;
    - a finding.triaged with a user, brief or path question opens kind finding, subject
      <draft>/triage/<finding>, text its question, call the triage call, report the walk
      report under FAB_HOME/walks (docs/design/qa.md, 2);
    - an ANSWERED record closes every log kind of its subject;
    - a chain.settled record closes the parked kind of its subject;
    - a call.ended with outcome done and the same subject closes the call kind: the subject
      was designed after all (a call run by hand, or an answer logged before ANSWERED
      existed);
    - a call.finished whose call is an open parked ask's call closes that ask: its chain
      was landed or dropped by hand.
    The log's asks come in the order their keys were last opened. A question.answered never
    closes one: it names a task. Records missing a field the rule reads are skipped. Pure:
    no file is read (fab.log.home() reads the environment only)."""
    questions = [Ask("plan", plan.draft, question.id, question.text, "",
                     report=str(path), parts=question.parts)
                 for plan, path in plans for question in plan.questions
                 if not question.answer.strip()]
    return questions + _log_asks(events)


def signals(events: Iterable[dict], *, folded: Sequence[tier_reds.Red] | None = None) -> list[Signal]:
    """Open signals, oldest first, from the log alone (docs/design/channel.md, 2).

    Queue rejections open queue:<branch>; a landing, a rejection or collateral at another
    tip, or signal.cleared closes the prior rejection. A rejection after a clear opens
    again. Reds in state signal open red-<n>, until red.closed or a hand clear.
    Faults open fault:<profile> for consecutive tiers.run records faulting that pair;
    only a run without that fault closes it. Pending red closures are hidden.
    Left QA findings open finding-<n> until their rung passes again or a hand clear.
    folded may be tier_reds.reds(events), reused for this same snapshot. Pure: no files are read.
    """
    events = list(events)
    folded = tier_reds.reds(events) if folded is None else folded
    return sorted([*_queue_signals(events), *_red_signals(events, folded=folded),
                   *_fault_signals(events), *_finding_signals(events)],
                  key=lambda signal: signal.since)


def _queue_signals(events: Iterable[dict]) -> list[Signal]:
    """Fold hand-pushed rejections without raising a signal for collateral alone."""
    opened = {}
    for event in events:
        ev = event.get("ev")
        if ev == "signal.cleared":
            opened.pop(event.get("signal"), None)
            continue
        if ev not in ("queue.rejected", "queue.landed", "queue.collateral"):
            continue
        branch = event.get("branch")
        if not isinstance(branch, str):
            continue
        identifier = f"queue:{branch}"
        if ev == "queue.landed":
            opened.pop(identifier, None)
        elif isinstance(event.get("tip"), str):
            prior = opened.get(identifier)
            if prior is not None and prior["tip"] != event["tip"]:
                del opened[identifier]
            if ev == "queue.rejected" and isinstance(event.get("queue_ts"), str):
                opened[identifier] = event
    found = []
    for identifier, event in opened.items():
        tests = event.get("tests")
        tests = [test for test in tests if isinstance(test, str)] if isinstance(tests, list) else []
        facts = (f"- Tip: `{event['tip']}`", f"- Step: `{event.get('step', '-')}`",
                 "- Tests: " + (", ".join(tests) or "(see the log)"))
        found.append(Signal(identifier, f"rejected {event['branch']}", event["queue_ts"], facts,
                            f"{event.get('gate', 'gate')}:{event.get('log', '-')}", True))
    return found


def _red_signals(events: Sequence[dict], *, folded: Sequence[tier_reds.Red]) -> list[Signal]:
    """Show the red fold's signals, hiding every pending closure before the tick records it."""
    closing = {identifier for identifier, _, _ in tier_reds.closures(events, folded=folded)}
    found = []
    for red in folded:
        if red.state != "signal" or red.id in closing:
            continue
        tests = []
        for key in red.keys[:10]:
            try:
                case = json.loads(key)
            except (TypeError, json.JSONDecodeError):
                case = None
            tests.append(" ".join(case) if isinstance(case, list) and len(case) == 3
                         and all(isinstance(part, str) for part in case) else str(key))
        if len(red.keys) > 10:
            tests.append(f"and {len(red.keys) - 10} more")
        suspects = [str(branch) + (" (hand-pushed)" if branch in red.hand_pushed else "")
                    for branch in red.suspects]
        facts = (f"- Tip: `{red.tip}`", f"- Why: {red.signal_reason}",
                 "- Tests: " + (", ".join(tests) or "(none)"),
                 "- Suspects: " + (", ".join(suspects) or "(none)"))
        read = str(tier_reds.evidence_path(red.id))
        if red.report:
            read += "`, `" + str(red.report)
        found.append(Signal(red.id, "after-landing red", red.signal_ts, facts, read, True))
    return found


def _finding_signals(events: Sequence[dict]) -> list[Signal]:
    """Show left findings until their rung passes after settlement; pure (docs/design/channel.md, 2)."""
    surveys = fixes.foremen(events)
    settled, passed = {}, {}
    for index, event in enumerate(events):
        if (event.get("ev") == "finding.settled" and event.get("verdict") == "left"
                and all(isinstance(event.get(key), str)
                        for key in ("finding", "run", "ts", "reason", "section"))):
            survey = surveys.get(event["finding"])
            if survey is None or event["run"] == survey.run:
                settled.setdefault(event["finding"], (index, event["ts"]))
        elif (event.get("ev") == "rung.passed"
              and all(isinstance(event.get(key), str)
                      for key in ("draft", "rung", "walk", "edition", "commit", "ts"))):
            passed[event["draft"], event["rung"]] = index
    opened = []
    for finding in findings.findings(events).values():
        settlement = settled.get(finding.id)
        if finding.state != "left" or settlement is None:
            continue
        index, since = settlement
        if passed.get((finding.draft, finding.rung), -1) > index:
            continue
        facts = (f"- Rung: {finding.rung} ({finding.backend})",
                 f"- Why: not the code's: {finding.reason}", f"- Title: {finding.title}")
        read = str(log.home() / "walks" / finding.walk / "report.md")
        survey = surveys.get(finding.id)
        if survey is not None and survey.report:
            read += "`, `" + survey.report
        opened.append(Signal(finding.id, "QA finding left", since, facts, read, True))
    return opened


def _fault_signals(events: Iterable[dict]) -> list[Signal]:
    """Keep each pair's unbroken fault streak, with the newest fault text and host:log.

    Older imported records without a host use the `after-landing` role as a fallback.
    """
    opened = {}
    for event in events:
        if event.get("ev") != "tiers.run" or not isinstance(event.get("ts"), str):
            continue
        faults = {}
        entries = event.get("faults")
        for fault in entries if isinstance(entries, list) else ():
            if not isinstance(fault, str):
                continue
            profile, colon, _ = fault.partition(":")
            if colon and profile.strip():
                faults[profile.strip()] = fault
        current = {}
        for profile, fault in faults.items():
            since, count = opened[profile][:2] if profile in opened else (event["ts"], 0)
            current[profile] = (since, count + 1, fault,
                                f"{event.get('host', 'after-landing')}:{event.get('log', '-')}")
        opened = current
    return [Signal(f"fault:{profile}", "after-landing pair cannot run", since,
                   (f"- Fault: {fault}", f"- Runs: {count}"), path, False)
            for profile, (since, count, fault, path) in opened.items()]


def plan_dirs(given: Sequence[Path] = ()) -> list[Path]:
    """The plans the page covers: the lines of FAB_HOME/PLANS (stripped, blank ones skipped),
    then given, each resolved, without duplicates (compared as resolved path strings, the
    first kept), in that order. A missing FAB_HOME/PLANS gives given alone. Directories are
    not checked: a plan being cut has none yet."""
    try:
        listed = (log.home() / PLANS).read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        listed = []
    paths = [Path(line.strip()) for line in listed if line.strip()]
    resolved = {}
    for path in [*paths, *given]:
        absolute = path.resolve()
        resolved.setdefault(str(absolute), absolute)
    return list(resolved.values())


def signal_section(text: str) -> tuple[str, ...]:
    """The lines of a report's Signals section: those after the line equal to SIGNALS, up to
    the next line starting `## ` or the end, blank lines dropped, each right-stripped. ()
    when the report has no such line. Pure."""
    section = []
    reading = False
    for line in text.splitlines():
        if reading:
            if line.startswith("## "):
                break
            if line.strip():
                section.append(line.rstrip())
        elif line == SIGNALS:
            reading = True
    return tuple(section)


def latest_reports(directory: Path) -> list[Report]:
    """Each standing report's latest day under directory (FAB_HOME/reports): per
    subdirectory holding at least one file named `YYYY-MM-DD.md` (the day parses as a date),
    the greatest such name, read as UTF-8, with signal_section of its text. Ordered by name,
    except fab.report.LANDING, which comes last. A missing directory gives []; a file that
    cannot be read gives signals ("(unreadable: <error>)",) and stays listed. Files and
    directories whose names start with `.` are skipped (fab.atomic.write's siblings)."""
    if not directory.exists():
        return []
    found = []
    for child in directory.iterdir():
        if child.name.startswith(".") or not child.is_dir():
            continue
        days = [path for path in child.iterdir() if _day_file(path)]
        if not days:
            continue
        path = max(days, key=lambda path: path.name)
        try:
            signals = signal_section(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError) as error:
            signals = (f"(unreadable: {error})",)
        found.append(Report(child.name, path.stem, path, signals))
    return sorted(found, key=lambda report: (report.name == LANDING, report.name))


def excerpt(path: Path, lines: int = QUESTION_LINES) -> str:
    """The first lines of the file at path, each right-stripped, trailing blank ones dropped,
    joined by newlines: what the page quotes of an asking report. `(report missing)` when it
    cannot be read; `(empty report)` when nothing is left."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return "(report missing)"
    quoted = [line.rstrip() for line in text.splitlines()[:lines]]
    while quoted and not quoted[-1]:
        quoted.pop()
    return "\n".join(quoted) or "(empty report)"


def answers_text(subject: str, events: Iterable[dict]) -> str:
    """The user's answers for subject, for a brief's SECTION: per ANSWERED record whose
    subject equals subject, in log order, the block

        ### <ts>, to <call>
        Question: <question>
        Answer (<by>): <answer>

    (the record's fields; a missing one is shown as `-`; a multi-line answer stays as it
    is), the blocks joined by blank lines. chain.settled amend contributes its guidance
    as a Settlement (<settle>) block in the same order. "" when there are none. Pure."""
    blocks = []
    for event in events:
        if (event.get("ev") == "chain.settled" and event.get("verdict") == "amend"
                and event.get("subject") == subject):
            blocks.append(f"### {event.get('ts', '-')}, to {event.get('call', '-')}\n"
                          f"Settlement ({event.get('settle', '-')}): {event.get('text', '-')}")
        elif event.get("ev") == ANSWERED and event.get("subject") == subject:
            blocks.append(f"### {event.get('ts', '-')}, to {event.get('call', '-')}\n"
                          f"Question: {event.get('question', '-')}\n"
                          f"Answer ({event.get('by', '-')}): {event.get('answer', '-')}")
    return "\n\n".join(blocks)


def landing_lines(events: Iterable[dict], *, folded: Sequence[tier_reds.Red] | None = None) -> list[str]:
    """The newest tiers.run's verdict, counts, faults, CPU and budget diagnostics,
    then its tiers.red records labelled `new red:` or `unattributed red:` with suspects.
    Append `<red> (<draft>/<red>): <state>, <k> tests at `<tip[:12]>`, since <ts>`
    for each open red that is not a signal, in opening order. Without a run, only those
    open-red lines remain. Pending closures are hidden. folded may be tier_reds.reds(events),
    reused for this same snapshot. Pure.
    """
    events = list(events)
    folded = tier_reds.reds(events) if folded is None else folded
    closing = {identifier for identifier, _, _ in tier_reds.closures(events, folded=folded)}
    last = next((event for event in reversed(events) if event.get("ev") == "tiers.run"), None)
    opened = [f"{red.id} ({red.task}): {red.state}, {len(red.keys)} tests at "
              f"`{str(red.tip)[:12]}`, since {red.since}"
              for red in folded if red.state not in ("closed", "signal") and red.id not in closing]
    if last is None:
        return opened
    line = (f"{last.get('verdict', '?')} at `{str(last.get('tip', ''))[:12]}`, {last.get('ts', '')}: "
            + ", ".join(f"{name} {last.get(key, 0)}" for name, key in (
                ("new", "new"), ("standing", "standing"), ("unattributed", "unattributed"),
                ("flakes", "flake"))))
    if last.get("faults"):
        line += "; faults: " + "; ".join(map(str, last["faults"]))
    if "cpu_s" in last:
        line += f"; CPU {last['cpu_s']:.3f}s, wall {last.get('wall_s', 0):.3f}s, starved {last.get('starved', 0)}"
        if last.get("wall_starved"):
            line += "; wall limit: starved"
    details = []
    if last.get("budget"):
        details.append("budget: " + ", ".join(map(str, last["budget"])))
    details.extend(f"over budget: {value}" for value in last.get("over_budget", []))
    details.extend(f"possible hang: {value}" for value in last.get("possible_hangs", []))
    reds = [f"{event.get('state', 'new')} red: {event.get('profile')} {event.get('test')}, since "
            + (", ".join(map(str, event.get("branches") or [])) or "unknown branches")
            for event in events if event.get("ev") == "tiers.red" and event.get("tip") == last.get("tip")
            and event.get("state", "new") in ("new", "unattributed")]
    return [line, *details, *reds, *opened]


def render(entries: Sequence[tuple[Ask, str]], reports: Sequence[Report], now: str,
           unread: Sequence[str] = (), landing: Sequence[str] = (),
           open_signals: Sequence[Signal] = ()) -> str:
    """The page as Markdown, ending with a newline, sections separated by one blank line.

    entries: each ask with its body, the text the page quotes for it (the caller reads it:
    a plan question's text, excerpt of a call's report, a parked chain's reason then the
    excerpt of its report).
    1. `# The user's page`, then `<now>. Only what is the user's (budgets, machines,
       what is hard to reverse) and what has no owner fab knows.`
    2. `## Questions`, then per entry in order, a block:
       - plan: `### <draft>: question <subject>`, the body, `- Waits: <parts, comma-
         separated>` and `- Answer: write its \\`answer\\` in \\`<report>\\` and land it
         with \\`fab land\\``;
       - call or finding: `### <subject>, asked <since>`, the body, `- Read: \\`<report>\\`` and
         `- Answer: \\`fab page answer <subject> TEXT\\``;
       - parked: `### <subject>, parked <since>`, the body, `- Read: \\`<report>\\`` (left
         out when report is "") and the same Answer line;
       the heading, the body and the list separated by blank lines. `(none)` when there
       are no entries.
    3. `## Open signals`, then per open_signals entry, `### <id>, <what>, since <since>`,
       its facts, `- Read: <read>` and, when clearable,
       `- Clear: fab page clear <id> TEXT`; `(none)` when empty.
    4. `## Daily reports`, then per report `### <name>, <day>`, the line `\\`<path>\\``, and
       its signals lines (`- none` when it has none); `(none)` when there are no reports.
    5. `## After landing`, one `- <line>` per landing line (landing_lines); left out when
       landing is empty.
    6. `## Unread`, one `- <line>` per unread entry; left out when unread is empty.
    Pure."""
    sections = ["# The user's page\n"
                f"{now}. Only what is the user's (budgets, machines, what is hard to reverse) "
                "and what has no owner fab knows.",
                "## Questions"]
    for ask, body in entries:
        if ask.kind == "plan":
            heading = f"### {ask.draft}: question {ask.subject}"
            instructions = [f"- Waits: {', '.join(ask.parts)}",
                            f"- Answer: write its `answer` in `{ask.report}` and land it with `fab land`"]
        else:
            verb = "parked" if ask.kind == "parked" else "asked"
            heading = f"### {ask.subject}, {verb} {ask.since}"
            instructions = [f"- Read: `{ask.report}`"] if ask.report or ask.kind in ("call", "finding") else []
            instructions.append(f"- Answer: `fab page answer {ask.subject} TEXT`")
        sections.append("\n\n".join((heading, body, "\n".join(instructions))))
    if not entries:
        sections.append("(none)")
    sections.append("## Open signals")
    for signal in open_signals:
        instructions = [*signal.facts, f"- Read: `{signal.read}`"]
        if signal.clearable:
            instructions.append(f"- Clear: `fab page clear {signal.id} TEXT`")
        sections.append(f"### {signal.id}, {signal.what}, since {signal.since}\n\n"
                        + "\n".join(instructions))
    if not open_signals:
        sections.append("(none)")
    sections.append("## Daily reports")
    for report in reports:
        signals = [line for line in report.signals
                   if line.endswith(" (user)") or line.startswith("(unreadable: ")]
        sections.append(f"### {report.name}, {report.day}\n\n`{report.path}`\n\n" +
                        "\n".join(signals or ["- none"]))
    if not reports:
        sections.append("(none)")
    if landing:
        sections.append("## After landing\n\n" + "\n".join(f"- {line}" for line in landing))
    if unread:
        sections.append("## Unread\n\n" + "\n".join(f"- {line}" for line in unread))
    return "\n\n".join(sections).rstrip("\n") + "\n"


def compose(directories: Sequence[Path], events: Sequence[dict], now: str) -> str:
    """The page for the plans at directories (as plan_dirs gives them) and the log.

    For each directory in order: PLAN_DIR/plan.toml missing is skipped (a plan being cut;
    its cut call's question is the log's); otherwise fab.plan.load_plan, a PlanError or an
    OSError adding `<directory>: <error, on one line>` to unread. asks over the loaded plans
    and events; each ask's body: plan, its text; call, excerpt(Path(report)); parked, its
    text, then a blank line and excerpt(Path(report)) when report is not "". The reports are
    latest_reports(fab.log.home() / "reports"). Render entries, reports, landing lines
    and signals, sharing one tier_reds.reds fold.
    Finding bodies quote title, rung and QUESTION_LINES of reproduction before the
    question. Loaded ladders add backlog signals at the current render and rung lines
    from walks.editions and findings.rungs after After landing, before Unread (docs/design/qa.md, 2).
    An unreadable edition adds the plan directory to Unread."""
    plans, unread = _load_plans(directories)
    found = findings.findings(events)
    entries = []
    for ask in asks(plans, events):
        body = excerpt(Path(ask.report)) if ask.kind == "call" else ask.text
        if ask.kind == "finding":
            finding = found[ask.subject.rsplit("/", 1)[-1]]
            reproduction = "\n".join(finding.reproduction.splitlines()[:QUESTION_LINES])
            body = (f"{finding.title}\n\nRung: {finding.rung}\n\n"
                    f"{reproduction}\n\n{ask.text}")
        if ask.kind == "parked" and ask.report:
            body += "\n\n" + excerpt(Path(ask.report))
        entries.append((ask, body))
    ladder = []
    for loaded, path in plans:
        if not loaded.rungs:
            continue
        try:
            editions = read_editions(loaded, path.parent)
        except (OSError, ValueError, Failed) as error:
            unread.append(f"{path.parent}: {' '.join(str(error).splitlines())}")
            continue
        lines = [f"- {findings.line(state)}"
                 for state in findings.rungs(loaded, list(events), editions, now)]
        count = sum(f.draft == loaded.draft and f.state == "backlog" for f in found.values())
        lines.append(f"- Backlog: {count} findings in `{loaded.ladder.backlog}`")
        ladder.append(f"### {loaded.draft}\n\n" + "\n".join(lines))
    folded = tier_reds.reds(events)
    opened = sorted([*signals(events, folded=folded), *_backlog_signals(plans, events)],
                    key=lambda signal: signal.since)
    page = render(entries, latest_reports(log.home() / "reports"), now,
                  landing=landing_lines(events, folded=folded), open_signals=opened)
    if ladder:
        page += "\n## The ladder\n\n" + "\n\n".join(ladder) + "\n"
    if unread:
        page += "\n## Unread\n\n" + "\n".join(f"- {line}" for line in unread) + "\n"
    return page


def _load_plans(directories: Sequence[Path]) -> tuple[list[tuple[Plan, Path]], list[str]]:
    """Load page plans and collect one-line read failures (docs/design/channel.md, 2)."""
    plans, unread = [], []
    for directory in directories:
        path = directory / "plan.toml"
        try:
            if path.exists():
                plans.append((plan.load_plan(path), path))
        except (plan.PlanError, OSError) as error:
            unread.append(f"{directory}: {' '.join(str(error).splitlines())}")
    return plans, unread


def _backlog_signals(plans: Sequence[tuple[Plan, Path]], events: Sequence[dict]) -> list[Signal]:
    """The loaded ladders held at their current backlog render; pure (docs/design/channel.md, 2)."""
    opened = []
    records = list(events)
    for loaded, _ in plans:
        if not loaded.rungs:
            continue
        key = triage.render_key(triage.backlog_text(loaded, records))
        held = triage.backlog_held(loaded, records, key)
        if held is not None:
            opened.append(Signal(f"backlog:{loaded.draft}", "backlog rejected twice", held["ts"],
                          (f"- Branch: `{held['branch']}`", f"- Step: `{held['step']}`"),
                          f"{held.get('gate', 'gate')}:{held['log']}", True))
    return opened


def write(text: str) -> Path:
    """Write the page to FAB_HOME/PAGE through fab.atomic.write and return its path."""
    path = log.home() / PAGE
    atomic.write(path, text)
    return path


def answer(subject: str, text: str, events: Sequence[dict], *, by: str = "user",
           log_path: Path | None = None) -> dict:
    """Log the user's answer to subject's open call, parked or finding asks and return the
    record: fab.log.append(ANSWERED, path=log_path, subject=subject, call=<the ask's call>,
    by=by, question=<the question>, answer=<text stripped>), then wake the tick with
    `answer <subject>` beside log_path.

    The ask is the last of asks((), events) whose subject equals subject. The question:
    for call, the first non-blank line of excerpt(Path(<its report>)); for parked,
    `parked: <its text>`; for finding, its question text. ValueError, logging nothing,
    when text is blank,
    or when no such ask is open: the message names the subject and the open subjects in
    order, comma-separated, or `none`. A plan's question is not answered here: its answer is
    written in its plan.toml (calls.md 3)."""
    text = text.strip()
    opened = asks((), events)
    subjects = ", ".join(dict.fromkeys(ask.subject for ask in opened)) or "none"
    if not text:
        raise ValueError(f"answer text for {subject!r} is blank; open subjects: {subjects}")
    matching = [ask for ask in opened if ask.subject == subject]
    if not matching:
        raise ValueError(f"no open call or parked chain or finding question for {subject!r}; open subjects: {subjects}")
    ask = matching[-1]
    question = ask.text
    if ask.kind == "call":
        question = next(line for line in excerpt(Path(ask.report)).splitlines() if line.strip())
    elif ask.kind == "parked":
        question = f"parked: {ask.text}"
    record = log.append(ANSWERED, path=log_path, subject=subject, call=ask.call, by=by,
                        question=question, answer=text)
    wake.want(f"answer {subject}", path=wake.want_path(log_path))
    return record


def clear(identifier: str, text: str, events: Sequence[dict], *, by: str = "user",
          log_path: Path | None = None) -> dict:
    """Clear an open, clearable signal, logging signal.cleared and waking the tick.

    Store signal, by and stripped text beside log_path. Blank text, an unknown or closed
    signal, or a signal that cannot be cleared raises ValueError without logging or waking.
    Backlog signals use the ladders registered in FAB_HOME/plans at their current render.
    The command rewrites the page after this record (docs/design/channel.md, 2).
    """
    text = text.strip()
    opened = signals(events)
    if identifier.startswith("backlog:"):
        plans, _ = _load_plans(plan_dirs())
        opened += _backlog_signals(plans, events)
    identifiers = ", ".join(signal.id for signal in opened) or "none"
    if not text:
        raise ValueError(f"clear text for {identifier!r} is blank; open signals: {identifiers}")
    signal = next((signal for signal in opened if signal.id == identifier), None)
    if signal is None:
        raise ValueError(f"no open signal for {identifier!r}; open signals: {identifiers}")
    if not signal.clearable:
        raise ValueError(f"signal {identifier!r} cannot be cleared")
    record = log.append("signal.cleared", path=log_path, signal=identifier, by=by, text=text)
    wake.want(f"clear {identifier}", path=wake.want_path(log_path))
    return record


def main(argv: list[str]) -> int:
    """`fab page show [PLAN_DIR...]`, `fab page write [PLAN_DIR...]` and `fab page answer
    SUBJECT TEXT...` and `fab page clear ID TEXT... [--by WHO]`, on hel8.

    show: print compose(plan_dirs(PLAN_DIRs), fab.log.read(), fab.log.now()), ending with
    its newline. write: write that text and print the path. answer: TEXT's words joined by
    single spaces; answer(SUBJECT, text, fab.log.read()), then write the page as write does,
    and print `answered <SUBJECT>` and the page's path. clear: clear(ID, text,
    fab.log.read(), by=WHO or user), rewrite the page and print `cleared <ID>` and its path.
    Exit 0; an OSError or ValueError
    prints `fab page: <error>` on stderr and exits 1; bad arguments exit 2 (argparse)."""
    parser = argparse.ArgumentParser(prog="fab page", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("show", "write"):
        commands.add_parser(command).add_argument("plans", nargs="*", type=Path)
    replying = commands.add_parser("answer")
    replying.add_argument("subject")
    replying.add_argument("text", nargs="+")
    clearing = commands.add_parser("clear")
    clearing.add_argument("id")
    clearing.add_argument("text", nargs="+")
    clearing.add_argument("--by", default="user")
    args = parser.parse_args(argv)
    try:
        if args.command == "clear":
            clear(args.id, " ".join(" ".join(args.text).split()), log.read(), by=args.by)
        if args.command == "answer":
            answer(args.subject, " ".join(" ".join(args.text).split()), log.read())
        text = compose(plan_dirs(getattr(args, "plans", ())), log.read(), log.now())
        if args.command == "show":
            print(text, end="")
        else:
            path = write(text)
            if args.command == "answer":
                print(f"answered {args.subject}")
            elif args.command == "clear":
                print(f"cleared {args.id}")
            print(path)
        return 0
    except (OSError, ValueError) as error:
        print(f"fab page: {error}", file=sys.stderr)
        return 1


def _log_asks(events: Iterable[dict]) -> list[Ask]:
    events = list(events)
    found = findings.findings(events)
    opened, roles = {}, {}
    for event in events:
        try:
            ev = event["ev"]
            if ev == "call.started":
                roles[event["call"]] = event.get("role")
                continue
            if ev == "call.ended" and event.get("role", roles.get(event.get("call"))) in ("amend", "settle"):
                continue
            if ev == ANSWERED:
                subject = event["subject"]
                for kind in ("call", "parked", "finding"):
                    opened.pop((kind, subject), None)
            elif ev == "chain.settled":
                opened.pop(("parked", event["subject"]), None)
            elif ev == "finding.triaged":
                if (event.get("decision") not in ("user", "brief", "path")
                        or not all(isinstance(event.get(key), str)
                                   for key in ("finding", "question", "call", "ts"))
                        or not event["question"].strip()):
                    continue
                finding = found.get(event["finding"])
                if finding is None:
                    continue
                subject = f"{finding.draft}/triage/{finding.id}"
                ask = Ask("finding", finding.draft, subject, event["question"], event["ts"],
                          call=event["call"],
                          report=str(log.home() / "walks" / finding.walk / "report.md"))
                key = (ask.kind, subject)
                opened.pop(key, None)
                opened[key] = ask
            elif ev == "call.finished":
                call = event["call"]
                for key, ask in list(opened.items()):
                    if ask.kind == "parked" and ask.call == call:
                        del opened[key]
            elif ev in ("call.ended", "call.parked"):
                subject = event["subject"]
                if ev == "call.ended" and event["outcome"] == "done":
                    opened.pop(("call", subject), None)
                    continue
                if ev == "call.parked":
                    ask = Ask("parked", subject.split("/", 1)[0], subject,
                              event["reason"], event["ts"], call=event["call"],
                              report=event.get("report", ""))
                elif event["outcome"] == "question":
                    call = event["call"]
                    ask = Ask("call", subject.split("/", 1)[0], subject, "", event["ts"],
                              call=call, report=str(log.home() / "calls" / call / "report.md"))
                else:
                    continue
                key = (ask.kind, subject)
                opened.pop(key, None)
                opened[key] = ask
        except KeyError:
            continue
    return list(opened.values())


def _day_file(path: Path) -> bool:
    if path.name.startswith(".") or path.suffix != ".md" or not path.is_file():
        return False
    try:
        return date.fromisoformat(path.stem).isoformat() == path.stem
    except ValueError:
        return False
