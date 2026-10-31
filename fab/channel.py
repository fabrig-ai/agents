"""The user's channel: the user's questions and the daily reports on one page (docs/design/fab.md, 13.6).

What is the user's is decided by whoever asks, never here: a plan's `[[question]]` without
an answer (the cut's), a call that ended `Question:`, and a call's chain parked after its
review refused twice. `asks` folds the open ones from the plans and the log. The page,
FAB_HOME/PAGE on hel8, lists them with what to read and how to answer, then each standing
report's latest day with its signals. An answer comes back as `call.answered`, which names a
call's subject and never a task; every later call of the subject carries it in its brief.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from fab import atomic, log, plan, wake
from fab.plan import Plan
from fab.report import LANDING

PAGE = "user.md"  # the page, under FAB_HOME
PLANS = "plans"  # FAB_HOME/plans: the ticked plans' directories, one per line (13.4)
KINDS = ("plan", "call", "parked")  # what asked: a plan's question, a call, a parked chain
QUESTION_LINES = 12  # lines of an asking report the page quotes
ANSWERED = "call.answered"  # the user's answer to a subject's call or parked chain
SIGNALS = "## Signals"  # the standing reports' signals heading (fab.code_report, fab.landing_report)
SECTION = "# The user's answers"  # the brief section that carries a subject's answers


@dataclass(frozen=True)
class Ask:
    """One open question of the user's, as asks folds it."""

    kind: str  # one of KINDS
    draft: str  # the plan's draft; for call and parked, the subject before its first `/`
    subject: str  # call and parked: the call's subject, which `fab page answer` names; plan: the question's id
    text: str  # plan: the question's text; parked: the call.parked reason; call: "" (its report holds it)
    since: str  # the ts it was asked (its call.ended or call.parked); "" for a plan's question
    call: str = ""  # call: the call that asked; parked: the chain's root; plan: ""
    report: str = ""  # what to read: call, FAB_HOME/calls/<call>/report.md; parked, the
    # call.parked's report (the refusing review run's, may be ""); plan, the plan.toml's path
    parts: tuple[str, ...] = ()  # plan: the parts that wait for it


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
    - a call.ended with outcome question and a subject opens Ask("call", <draft>, subject, "",
      ts, call=<call>, report=str(fab.log.home() / "calls" / <call> / "report.md"));
    - a call.parked with a subject opens Ask("parked", <draft>, subject, <reason>, ts,
      call=<its call>, report=<its report, or "">);
    - opening a key already open replaces its ask, which moves to the end of the order;
    - an ANSWERED record closes both kinds of its subject;
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
    is), the blocks joined by blank lines. "" when there are none. Pure."""
    blocks = []
    for event in events:
        if event.get("ev") == ANSWERED and event.get("subject") == subject:
            blocks.append(f"### {event.get('ts', '-')}, to {event.get('call', '-')}\n"
                          f"Question: {event.get('question', '-')}\n"
                          f"Answer ({event.get('by', '-')}): {event.get('answer', '-')}")
    return "\n\n".join(blocks)


def render(entries: Sequence[tuple[Ask, str]], reports: Sequence[Report], now: str,
           unread: Sequence[str] = ()) -> str:
    """The page as Markdown, ending with a newline, sections separated by one blank line.

    entries: each ask with its body, the text the page quotes for it (the caller reads it:
    a plan question's text, excerpt of a call's report, a parked chain's reason then the
    excerpt of its report).
    1. `# The user's page`, then the line `<now>. Only what is the user's: budgets,
       machines, what is hard to reverse.`
    2. `## Questions`, then per entry in order, a block:
       - plan: `### <draft>: question <subject>`, the body, `- Waits: <parts, comma-
         separated>` and `- Answer: write its \\`answer\\` in \\`<report>\\` and land it
         with \\`fab land\\``;
       - call: `### <subject>, asked <since>`, the body, `- Read: \\`<report>\\`` and
         `- Answer: \\`fab page answer <subject> TEXT\\``;
       - parked: `### <subject>, parked <since>`, the body, `- Read: \\`<report>\\`` (left
         out when report is "") and the same Answer line;
       the heading, the body and the list separated by blank lines. `(none)` when there
       are no entries.
    3. `## Daily reports`, then per report `### <name>, <day>`, the line `\\`<path>\\``, and
       its signals lines (`- none` when it has none); `(none)` when there are no reports.
    4. `## Unread`, one `- <line>` per unread entry; left out when unread is empty.
    Pure."""
    sections = ["# The user's page\n"
                f"{now}. Only what is the user's: budgets, machines, what is hard to reverse.",
                "## Questions"]
    for ask, body in entries:
        if ask.kind == "plan":
            heading = f"### {ask.draft}: question {ask.subject}"
            instructions = [f"- Waits: {', '.join(ask.parts)}",
                            f"- Answer: write its `answer` in `{ask.report}` and land it with `fab land`"]
        else:
            verb = "asked" if ask.kind == "call" else "parked"
            heading = f"### {ask.subject}, {verb} {ask.since}"
            instructions = [f"- Read: `{ask.report}`"] if ask.report or ask.kind == "call" else []
            instructions.append(f"- Answer: `fab page answer {ask.subject} TEXT`")
        sections.append("\n\n".join((heading, body, "\n".join(instructions))))
    if not entries:
        sections.append("(none)")
    sections.append("## Daily reports")
    for report in reports:
        signals = [line for line in report.signals
                   if line.endswith(" (user)") or line.startswith("(unreadable: ")]
        sections.append(f"### {report.name}, {report.day}\n\n`{report.path}`\n\n" +
                        "\n".join(signals or ["- none"]))
    if not reports:
        sections.append("(none)")
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
    latest_reports(fab.log.home() / "reports"). Return render(entries, reports, now,
    unread)."""
    plans, unread = [], []
    for directory in directories:
        path = directory / "plan.toml"
        try:
            if not path.exists():
                continue
            plans.append((plan.load_plan(path), path))
        except (plan.PlanError, OSError) as error:
            unread.append(f"{directory}: {' '.join(str(error).splitlines())}")
    entries = []
    for ask in asks(plans, events):
        body = excerpt(Path(ask.report)) if ask.kind == "call" else ask.text
        if ask.kind == "parked" and ask.report:
            body += "\n\n" + excerpt(Path(ask.report))
        entries.append((ask, body))
    return render(entries, latest_reports(log.home() / "reports"), now, unread)


def write(text: str) -> Path:
    """Write the page to FAB_HOME/PAGE through fab.atomic.write and return its path."""
    path = log.home() / PAGE
    atomic.write(path, text)
    return path


def answer(subject: str, text: str, events: Sequence[dict], *, by: str = "user",
           log_path: Path | None = None) -> dict:
    """Log the user's answer to subject's open asks of kind call or parked and return the
    record: fab.log.append(ANSWERED, path=log_path, subject=subject, call=<the ask's call>,
    by=by, question=<the question>, answer=<text stripped>), then wake the tick with
    `answer <subject>` beside log_path.

    The ask is the last of asks((), events) whose subject equals subject (call or parked).
    The question: for call, the first non-blank line of excerpt(Path(<its report>)); for
    parked, `parked: <its text>`. ValueError, logging nothing, when text is blank,
    or when no such ask is open: the message names the subject and the open subjects in
    order, comma-separated, or `none`. A plan's question is not answered here: its answer is
    written in its plan.toml (13.3)."""
    text = text.strip()
    opened = asks((), events)
    subjects = ", ".join(dict.fromkeys(ask.subject for ask in opened)) or "none"
    if not text:
        raise ValueError(f"answer text for {subject!r} is blank; open subjects: {subjects}")
    matching = [ask for ask in opened if ask.subject == subject]
    if not matching:
        raise ValueError(f"no open call or parked chain for {subject!r}; open subjects: {subjects}")
    ask = matching[-1]
    question = (next(line for line in excerpt(Path(ask.report)).splitlines() if line.strip())
                if ask.kind == "call" else f"parked: {ask.text}")
    record = log.append(ANSWERED, path=log_path, subject=subject, call=ask.call, by=by,
                        question=question, answer=text)
    wake.want(f"answer {subject}", path=wake.want_path(log_path))
    return record


def main(argv: list[str]) -> int:
    """`fab page show [PLAN_DIR...]`, `fab page write [PLAN_DIR...]` and `fab page answer
    SUBJECT TEXT...`, on hel8.

    show: print compose(plan_dirs(PLAN_DIRs), fab.log.read(), fab.log.now()), ending with
    its newline. write: write that text and print the path. answer: TEXT's words joined by
    single spaces; answer(SUBJECT, text, fab.log.read()), then write the page as write does,
    and print `answered <SUBJECT>` and the page's path. Exit 0; an OSError or ValueError
    prints `fab page: <error>` on stderr and exits 1; bad arguments exit 2 (argparse)."""
    parser = argparse.ArgumentParser(prog="fab page", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("show", "write"):
        commands.add_parser(command).add_argument("plans", nargs="*", type=Path)
    replying = commands.add_parser("answer")
    replying.add_argument("subject")
    replying.add_argument("text", nargs="+")
    args = parser.parse_args(argv)
    try:
        if args.command == "answer":
            answer(args.subject, " ".join(" ".join(args.text).split()), log.read())
        text = compose(plan_dirs(getattr(args, "plans", ())), log.read(), log.now())
        if args.command == "show":
            print(text, end="")
        else:
            path = write(text)
            if args.command == "answer":
                print(f"answered {args.subject}")
            print(path)
        return 0
    except (OSError, ValueError) as error:
        print(f"fab page: {error}", file=sys.stderr)
        return 1


def _log_asks(events: Iterable[dict]) -> list[Ask]:
    opened = {}
    for event in events:
        try:
            ev = event["ev"]
            if ev == ANSWERED:
                subject = event["subject"]
                for kind in ("call", "parked"):
                    opened.pop((kind, subject), None)
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
