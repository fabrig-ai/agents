"""The user's channel: the user's questions and the daily reports on one page (docs/design/fab.md, 13.6).

What is the user's is decided by whoever asks, never here: a plan's `[[question]]` without
an answer (the cut's), a call that ended `Question:`, and a call's chain parked after its
review refused twice. `asks` folds the open ones from the plans and the log. The page,
FAB_HOME/PAGE on hel8, lists them with what to read and how to answer, then each standing
report's latest day with its signals. An answer comes back as `call.answered`, which names a
call's subject and never a task; every later call of the subject carries it in its brief.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from fab.plan import Plan

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
    raise NotImplementedError


def plan_dirs(given: Sequence[Path] = ()) -> list[Path]:
    """The plans the page covers: the lines of FAB_HOME/PLANS (stripped, blank ones skipped),
    then given, each resolved, without duplicates (compared as resolved path strings, the
    first kept), in that order. A missing FAB_HOME/PLANS gives given alone. Directories are
    not checked: a plan being cut has none yet."""
    raise NotImplementedError


def signal_section(text: str) -> tuple[str, ...]:
    """The lines of a report's Signals section: those after the line equal to SIGNALS, up to
    the next line starting `## ` or the end, blank lines dropped, each right-stripped. ()
    when the report has no such line. Pure."""
    raise NotImplementedError


def latest_reports(directory: Path) -> list[Report]:
    """Each standing report's latest day under directory (FAB_HOME/reports): per
    subdirectory holding at least one file named `YYYY-MM-DD.md` (the day parses as a date),
    the greatest such name, read as UTF-8, with signal_section of its text. Ordered by name,
    except fab.report.LANDING, which comes last. A missing directory gives []; a file that
    cannot be read gives signals ("(unreadable: <error>)",) and stays listed. Files and
    directories whose names start with `.` are skipped (fab.atomic.write's siblings)."""
    raise NotImplementedError


def excerpt(path: Path, lines: int = QUESTION_LINES) -> str:
    """The first lines of the file at path, each right-stripped, trailing blank ones dropped,
    joined by newlines: what the page quotes of an asking report. `(report missing)` when it
    cannot be read; `(empty report)` when nothing is left."""
    raise NotImplementedError


def answers_text(subject: str, events: Iterable[dict]) -> str:
    """The user's answers for subject, for a brief's SECTION: per ANSWERED record whose
    subject equals subject, in log order, the block

        ### <ts>, to <call>
        Question: <question>
        Answer (<by>): <answer>

    (the record's fields; a missing one is shown as `-`; a multi-line answer stays as it
    is), the blocks joined by blank lines. "" when there are none. Pure."""
    raise NotImplementedError


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
    raise NotImplementedError


def compose(directories: Sequence[Path], events: Sequence[dict], now: str) -> str:
    """The page for the plans at directories (as plan_dirs gives them) and the log.

    For each directory in order: PLAN_DIR/plan.toml missing is skipped (a plan being cut;
    its cut call's question is the log's); otherwise fab.plan.load_plan, a PlanError or an
    OSError adding `<directory>: <error, on one line>` to unread. asks over the loaded plans
    and events; each ask's body: plan, its text; call, excerpt(Path(report)); parked, its
    text, then a blank line and excerpt(Path(report)) when report is not "". The reports are
    latest_reports(fab.log.home() / "reports"). Return render(entries, reports, now,
    unread)."""
    raise NotImplementedError


def write(text: str) -> Path:
    """Write the page to FAB_HOME/PAGE through fab.atomic.write and return its path."""
    raise NotImplementedError


def answer(subject: str, text: str, events: Sequence[dict], *, by: str = "user",
           log_path: Path | None = None) -> dict:
    """Log the user's answer to subject's open asks of kind call or parked and return the
    record: fab.log.append(ANSWERED, path=log_path, subject=subject, call=<the ask's call>,
    by=by, question=<the question>, answer=<text stripped>).

    The ask is the last of asks((), events) whose subject equals subject (call or parked).
    The question: for call, the first non-blank line of excerpt(Path(<its report>)); for
    parked, `parked: <its text>`. ValueError, logging nothing, when text is blank,
    or when no such ask is open: the message names the subject and the open subjects in
    order, comma-separated, or `none`. A plan's question is not answered here: its answer is
    written in its plan.toml (13.3)."""
    raise NotImplementedError


def main(argv: list[str]) -> int:
    """`fab page show [PLAN_DIR...]`, `fab page write [PLAN_DIR...]` and `fab page answer
    SUBJECT TEXT...`, on hel8.

    show: print compose(plan_dirs(PLAN_DIRs), fab.log.read(), fab.log.now()), ending with
    its newline. write: write that text and print the path. answer: TEXT's words joined by
    single spaces; answer(SUBJECT, text, fab.log.read()), then write the page as write does,
    and print `answered <SUBJECT>` and the page's path. Exit 0; an OSError or ValueError
    prints `fab page: <error>` on stderr and exits 1; bad arguments exit 2 (argparse)."""
    raise NotImplementedError
