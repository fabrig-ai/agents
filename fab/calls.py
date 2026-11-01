"""Claude calls: fresh, short sessions on briefs compiled by code (docs/design/fab.md, 6).

A call never waits, polls or watches. Code compiles its brief from files; the call writes
files on its chain's branch and ends with a report whose first line is its outcome, as a
run's does. The dispatcher reviews the branch before landing it.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import shlex
import sys
import time
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from fab import atomic, channel, fix, fixes, foreman, integration, log, state, tier_reds, wake
from fab.plan import Plan, Task, load_plan, load_tasks
from fab.run import TASTE, outcome
from fab.sh import Failed, Runner, run
from fab.state import fold

ROLES = {
    "skeleton": Path(__file__).resolve().parent / "roles" / "skeleton.md",
    "answer": Path(__file__).resolve().parent / "roles" / "answerer.md",
    "reply": Path(__file__).resolve().parent / "roles" / "reply.md",
    "triage": Path(__file__).resolve().parent / "roles" / "triager.md",
    "review": Path(__file__).resolve().parent / "roles" / "reviewer.md",
    "settle": Path(__file__).resolve().parent / "roles" / "settle.md",
    "amend": Path(__file__).resolve().parent / "roles" / "amender.md",
    "cut": Path(__file__).resolve().parent / "roles" / "cut.md",
    "contract": Path(__file__).resolve().parent / "roles" / "contract.md",
    "decision": Path(__file__).resolve().parent / "roles" / "decision.md",
    "retire": Path(__file__).resolve().parent / "roles" / "retire.md",
}
MODEL = "claude-opus-5-5"  # every Claude call's model, explicit (the user, 10-30): Opus 5.5
BRIEF_LIMIT = 200_000  # characters, about 50k tokens: what code puts in; the call reads the rest itself
TIMEOUT = 60 * 60  # seconds; 40 minutes until the playground replay's cut ran out with its designers in flight (the user, 10-31)


class BriefError(ValueError):
    """A brief builder could not compile its text after the call's preconditions held."""


def park(role: str, subject: str, error: Exception, *, call: str = "",
         log_path: Path | None = None) -> None:
    """Log a failed brief's park and wake the tick so the user's page shows its reason."""
    lines = str(error).splitlines()
    reason = "brief failed: " + (lines[0] if lines else "")
    log.append("call.parked", path=log_path, subject=subject, role=role,
               reason=reason, report="", call=call)
    wake.want(f"park {subject}", path=wake.want_path(log_path))


@dataclass(frozen=True)
class Usage:
    """A call's Claude usage, as claude_usage reads it from claude's stream and call.ended
    carries it (docs/design/reports.md, 3). Every count is in tokens."""

    input: int  # uncached input: claude's input_tokens, which excludes cache reads and writes
    cache_write: int  # cache_creation_input_tokens
    cache_read: int  # cache_read_input_tokens
    output: int  # output_tokens
    peak: int  # the largest context of one main-thread message: input + cache_write + cache_read
    turns: int  # claude's num_turns

    def log_fields(self) -> dict:
        """call.ended's usage fields: tokens `<input>/<cache_read>/<output>` (the shape the
        log has always had, which fab.accounting.token_counts reads), then cache_write, peak
        and turns as ints."""
        return {"tokens": f"{self.input}/{self.cache_read}/{self.output}",
                "cache_write": self.cache_write, "peak": self.peak, "turns": self.turns}


@dataclass(frozen=True)
class Signature:
    module: str  # repository-relative path
    name: str  # `name` or `Class.name`
    text: str  # `def name(args) -> ret` or `class Name`
    doc: str  # the docstring's first line


def inventory(root: Path, package: str = "fab") -> list[Signature]:
    """The primitives in reach: every public module-level function and class, and every public
    method, of root/<package>/*.py (not tests), from ast, in path then source order. A name
    starting with _ is private. text keeps the parameters and annotations as written."""
    entries = []
    for path in sorted((root / package).glob("*.py")):
        if path.name.startswith("test_") or path.name.endswith("_test.py"):
            continue
        module = path.relative_to(root).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

        def add(node, prefix=""):
            if node.name.startswith("_"):
                return
            if isinstance(node, ast.ClassDef):
                text = f"class {node.name}"
            else:
                text = f"def {node.name}({ast.unparse(node.args)})"
                if node.returns is not None:
                    text += f" -> {ast.unparse(node.returns)}"
                if isinstance(node, ast.AsyncFunctionDef):
                    text = "async " + text
            doc = ast.get_docstring(node) or ""
            entries.append(Signature(module, prefix + node.name, text, doc.splitlines()[0] if doc else ""))
            if isinstance(node, ast.ClassDef):
                for member in node.body:
                    if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        add(member, node.name + ".")

        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                add(node)
    return entries


def render_inventory(signatures: Iterable[Signature]) -> str:
    """Markdown: a `## <module>` heading per module, then one `- `text` — doc` line per entry."""
    lines = []
    previous = None
    for entry in signatures:
        if entry.module != previous:
            if lines:
                lines.append("")
            lines.extend([f"## {entry.module}", ""])
            previous = entry.module
        lines.append(f"- `{entry.text}` — {entry.doc}")
    return "\n".join(lines)


def design_text(root: Path, citation: str) -> str:
    """The text a part's `design` cites, e.g. "docs/design/landing.md, 2; fab.md, 4": the whole document
    at the cited path (sections are not cut out); an unreadable path gives a one-line note."""
    path = citation.split(",", 1)[0].strip()
    try:
        return (root / path).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        return f"Design unavailable: {path} ({' '.join(str(error).splitlines())})"


def drafts_text(plan: Plan, root: Path) -> str:
    """The plan's sources, the user's own words every call checks its work against: the text of
    each source that is a file under root, under a `## <path>` heading; a source that is not a
    file here is listed by name."""
    parts = []
    for source in plan.sources:
        path = root / source
        if source and not Path(source).is_absolute() and path.is_file():
            parts.append(f"## {source}\n\n{path.read_text(encoding='utf-8')}")
        else:
            parts.append(f"## {source}\n\n(not a file in this repository)")
    return "\n\n".join(parts) or "(none)"


def skeleton_brief(plan: Plan, part_id: str, tasks: dict[str, Task], statuses: dict[str, str],
                   root: Path, *, call_id: str, branch: str, report: str,
                   role: str = "skeleton") -> str:
    """The skeleton or contract author's brief: its role text; the call's facts; the plan's
    parts and slices with each part's status; the part to design (id, title, mode, needs,
    design citation, contract marker, questions and their answers, plus readers in plan
    order for contract); only draft sections cited by the reached design sections or
    named in the part's title or design; the cited design; inventory of modules cited by
    those design sections, owned by its direct needs, and the shared sh, log, atomic, plan
    and state primitives;
    one example spec, the first landed task of its first need in path order, else
    docs/plan/agents-rebuild/tasks/files.md (from fab's checkout when absent in root).
    Accepts skeleton or contract, else ValueError.
    Raises ValueError past BRIEF_LIMIT, naming the largest section."""
    if role not in ("skeleton", "contract"):
        raise ValueError(f"unknown skeleton brief role {role!r}")
    part = plan.parts[part_id]
    details = f"- Id: {part.id}\n- Title: {part.title}\n- Mode: {part.mode}\n"
    details += f"- Needs: {', '.join(part.needs) or '(none)'}\n- Design: {part.design}"
    if part.contract:
        details += "\n- Contract: yes"
    if role == "contract":
        readers = [item.id for item in plan.parts.values() if part_id in item.needs]
        details += f"\n- Readers: {', '.join(readers) or '(none)'}"
    for question in plan.questions:
        if part_id in question.parts:
            details += f"\n- Question {question.id}: {question.text}\n  Answer: {question.answer or '(open)'}"
    design = _cited_design(root, part.design)
    if plan.repo == "fabrig":
        patterns = [pattern for task in tasks.values() if task.part in part.needs for pattern in task.files]
        signatures = render_inventory(_rust_inventory(root, design, patterns))
    else:
        modules = {f"fab/{name}.py" for name in ("sh", "log", "atomic", "plan", "state")}
        modules.update(re.findall(r"\bfab/[\w]+\.py\b", design))
        modules.update(f"fab/{name}.py" for name in re.findall(r"\bfab\.([\w]+)\b", design))
        for task in tasks.values():
            if task.part in part.needs:
                for pattern in task.files:
                    modules.update(path.relative_to(root).as_posix() for path in root.glob(pattern)
                                   if path.suffix == ".py")
        signatures = render_inventory(entry for entry in inventory(root) if entry.module in modules)
    examples = sorted((task for task in tasks.values()
                       if part.needs and task.part == part.needs[0]
                       and statuses.get(task.id) == "landed"), key=lambda task: task.path)
    if plan.repo == "fabrig" and not examples:
        examples = sorted((task for task in tasks.values() if statuses.get(task.id) == "landed"),
                          key=lambda task: task.path)
    path = Path(examples[0].path if examples else "docs/plan/agents-rebuild/tasks/files.md")
    label = path.relative_to(root) if path.is_absolute() else path
    heading = f"{examples[0].id} ({label})" if examples else str(label)
    spec_path = root / path
    if not examples and not spec_path.is_file():
        spec_path = Path(__file__).resolve().parents[1] / path
    example = f"## {heading}\n\n{spec_path.read_text(encoding='utf-8')}"
    role_text = ROLES[role].read_text(encoding="utf-8")
    if plan.repo == "fabrig":
        role_text += "\n\n" + ROLES[role].with_name(f"{role}-fabrig.md").read_text(encoding="utf-8")
    return _brief([
        ("Role", role_text),
        ("Call facts", _facts(call_id, branch, report)),
        ("Plan parts and slices", _parts_table(plan, tasks, statuses)),
        ("Part to design", details),
        ("The user's drafts", _part_drafts(plan, part_id, root, design)),
        ("Cited design", design_text(root, part.design)),
        ("Inventory", signatures),
        ("Task spec examples", example),
    ])


def _rust_inventory(root: Path, design: str, patterns: Iterable[str]) -> list[Signature]:
    """Public Rust items in cited crates and crates owned by direct needs."""
    from fab import rust_digest

    crates = set(re.findall(r"\b(?:skein|smith|jig|temper)/(?:crates|testing)/[\w-]+", design))
    for directory in (*root.glob("*/crates/*"), *root.glob("*/testing/*")):
        if directory.is_dir() and re.search(r"(?<![\w/-])" + re.escape(directory.name)
                                            + r"(?![\w-])", design):
            crates.add(directory.relative_to(root).as_posix())
    for pattern in patterns:
        for path in root.glob(pattern):
            for parent in (path, *path.parents):
                if parent == root:
                    break
                if (parent / "Cargo.toml").is_file():
                    crates.add(parent.relative_to(root).as_posix())
                    break
    return rust_digest.inventory(root, sorted(crates))


def _headings(text: str) -> list[tuple[int, str, int, int]]:
    """Markdown headings and their spans, including children but excluding fenced code."""
    headings = []
    offset, fence = 0, ""
    for line in text.splitlines(keepends=True):
        stripped = line.lstrip()
        if stripped.startswith(("```", "~~~")):
            marker = stripped[:3]
            if not fence:
                fence = marker
            elif marker == fence:
                fence = ""
        match = re.match(r"(#{1,6}) +(.+?)\s*#*\s*$", line) if not fence else None
        if match:
            headings.append((len(match[1]), match[2], offset))
        offset += len(line)
    return [(level, title, start,
             next((later for depth, _, later in headings[index + 1:] if depth <= level), len(text)))
            for index, (level, title, start) in enumerate(headings)]


def _section_number(title: str) -> str:
    """The leading dotted section number, or an empty string for a named heading."""
    match = re.match(r"(\d+(?:\.\d+)*)(?:\.?(?:\s|$))", title)
    return match[1] if match else ""


def _cited_design(root: Path, citation: str) -> str:
    """Only the numbered design sections in a citation; a bare path reaches the whole file."""
    text = design_text(root, citation)
    _, comma, sections = citation.partition(",")
    if not comma:
        return text
    numbers = set(re.findall(r"\d+(?:\.\d+)*", sections))
    spans = [(start, end) for _, title, start, end in _headings(text)
             if _section_number(title) in numbers]
    return _excerpt(text, spans)


def _excerpt(text: str, spans: list[tuple[int, int]]) -> str:
    """Join selected heading spans in source order, without repeating nested sections."""
    end = 0
    parts = []
    for start, stop in sorted(spans):
        if stop > end:
            parts.append(text[max(start, end):stop].rstrip())
            end = stop
    return "\n\n".join(parts)


def _part_drafts(plan: Plan, part_id: str, root: Path, design: str) -> str:
    """The draft sections reached by this part's title, citation and selected design."""
    part = plan.parts[part_id]
    named = f"{part.title}\n{part.design}\n{design}".replace("`", "").casefold()
    excerpts = []
    for source in plan.sources:
        path = root / source
        if not source or Path(source).is_absolute() or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        numbers, mentions = set(), []
        reference = r"(?<![\w/])(?:" + re.escape(source) + "|" + re.escape(path.name) + r")(?![\w./])"
        context = part.design + "\n" + design
        for match in re.finditer(reference, context):
            tail = context[match.end():]
            numbered = re.match(r"`?\s*,\s*(\d+(?:\.\d+)*(?:(?:\s+and\s+|\s*,\s*)\d+(?:\.\d+)*)*)", tail)
            if numbered:
                numbers.update(re.findall(r"\d+(?:\.\d+)*", numbered[1]))
            quoted = re.match(r'`?\s*,\s*["“`]([^"”`]+)["”`]', tail)
            if quoted:
                mentions.append(quoted[1].casefold())
        spans = []
        for level, title, start, end in _headings(text):
            if level == 1:
                continue
            number = _section_number(title)
            heading = title.removeprefix(number).lstrip(". ").replace("`", "").casefold()
            if ((number and number in numbers) or
                    re.search(r"(?<!\w)" + re.escape(heading) + r"(?!\w)", named) or
                    any(heading == mention or heading.startswith(mention + ":") for mention in mentions)):
                spans.append((start, end))
        excerpt = _excerpt(text, spans)
        if excerpt:
            excerpts.append(f"## {source}\n\n{excerpt}")
    return "\n\n".join(excerpts) or "(none)"


def _parts_table(plan: Plan, tasks: Mapping[str, Task], statuses: Mapping[str, str]) -> str:
    rows = ["| Part | Title | Mode | Needs | Status |", "| --- | --- | --- | --- | --- |"]
    parts = state.part_statuses(plan, tasks, statuses)
    for item in plan.parts.values():
        status = parts[item.id]
        rows.append(f"| {item.id} | {item.title} | {item.mode} | {', '.join(item.needs) or '-'} | {status} |")
    rows.extend(["", "| Slice | Story | Parts | Walk |", "| --- | --- | --- | --- |"])
    for item in plan.slices:
        rows.append(f"| {item.id} | {item.story} | {', '.join(item.parts)} | {item.walk} |")
    return f"Plan: {plan.draft}\nRepository: {plan.repo}\n\n" + "\n".join(rows)


def answer_brief(questions: list[dict], tasks: dict[str, Task], root: Path, *, call_id: str,
                 branch: str, report: str, plan: Plan | None = None) -> str:
    """The answerer's brief: its role text; the call's facts; the user's drafts when the plan
    is given; each queued question (task, run, text, foreman) with its task spec, the
    asking run's report path and, when present, its foreman report path; the inventory.
    A stop question carries `stop`, its preceding plan.stopped report: show its task, report
    and text under `Question: <draft>/integration (stop)`, with no task spec."""
    sections = [
        ("Role", ROLES["answer"].read_text(encoding="utf-8")),
        ("Call facts", _facts(call_id, branch, report)),
    ]
    if plan is not None:
        sections.append(("The user's drafts", drafts_text(plan, root)))
    for question in questions:
        if "stop" in question:
            sections.append((f"Question: {question['task']} (stop)",
                             f"- Task: {question['task']}\n- Report: `{question['stop']}`\n\n{question['text']}"))
            continue
        task = tasks[question["task"]]
        path = Path(task.path)
        label = path.relative_to(root) if path.is_absolute() else path
        run_id = question["run"]
        report_path = log.home() / "runs" / run_id / "report.md"
        foreman_line = f"- Foreman: `{question['foreman']}`\n" if question.get("foreman") else ""
        sections.append((f"Question: {task.id} ({run_id})",
                         f"- Task: {task.id}\n- Run: {run_id}\n- Report: `{report_path}`\n{foreman_line}\n"
                         f"{question['text']}\n\n## Task spec ({label if task.path else 'none: its body'})\n\n"
                         f"{(root / path).read_text(encoding='utf-8') if task.path else task.body}"))
    sections.append(("Inventory", render_inventory(inventory(root))))
    return _brief(sections)


def review_brief(plan: Plan, tasks: dict[str, Task], events: list[dict], root: Path, *,
                 call_id: str, branch: str, report: str, plan_path: str | None = None) -> str:
    """The structure reviewer's brief (docs/design/gates.md, 2): its role text (ROLES["review"]);
    the call's facts; "Plan parts and slices", the same table skeleton_brief writes (shared,
    not copied), statuses from fab.state.fold(tasks, events), and a line `Specs:
    docs/plan/<draft>/tasks/`; "Landed since the last review": per record of
    landed_after(events, tasks, last_review(events, done=True, draft=plan.draft)), so only
    this draft's done reviews set the cutoff; in log order, a heading
    `## <task> (`<branch>`, main `<main[:12]>`)` and the text of FAB_HOME/digests/<run>.md for
    the task's last run.started before that record, or `(no digest)` when it has none or
    the file is missing; `(none)` when nothing landed; "Taste", the text of fab.run.TASTE;
    "Designs", per distinct path cited by the landed tasks' parts (the citation before its
    comma), in first-landed order, `## <path>` and design_text(root, citation); "Inventory".
    plan_path overrides docs/plan/<draft> with a repository-relative plan directory.
    Raises ValueError past BRIEF_LIMIT, naming the largest section."""
    plan_path = plan_path or f"docs/plan/{plan.draft}"
    landed = landed_after(events, tasks, last_review(events, done=True, draft=plan.draft))
    records = []
    designs = {}
    for record in landed:
        run_id = None
        for event in events:
            if event is record:
                break
            if event.get("ev") == "run.started" and event.get("task") == record["task"]:
                run_id = event["run"]
        digest = "(no digest)"
        if run_id is not None:
            try:
                digest = (log.home() / "digests" / f"{run_id}.md").read_text(encoding="utf-8")
            except FileNotFoundError:
                pass
        records.append(f"## {record['task']} (`{record['branch']}`, main `{record['main'][:12]}`)\n\n{digest}")
        part = plan.parts.get(tasks[record["task"]].part)
        citation = part.design if part is not None else ""
        if citation:
            designs.setdefault(citation.split(",", 1)[0].strip(), citation)
    statuses = {key: view.status for key, view in fold(tasks, events).items()}
    return _brief([
        ("Role", ROLES["review"].read_text(encoding="utf-8")),
        ("Call facts", _facts(call_id, branch, report)),
        ("Plan parts and slices", _parts_table(plan, tasks, statuses) +
         f"\n\nSpecs: {plan_path}/tasks/"),
        ("Landed since the last review", "\n\n".join(records) or "(none)"),
        ("Taste", TASTE.read_text(encoding="utf-8")),
        ("The user's drafts", drafts_text(plan, root)),
        ("Designs", "\n\n".join(f"## {path}\n\n{design_text(root, citation)}"
                                 for path, citation in designs.items())),
        ("Inventory", render_inventory(inventory(root))),
    ])


def last_review(events: Iterable[dict], *, done: bool = False,
                draft: str | None = None) -> str | None:
    """The ts of the latest call.started with role review; with done, only of one whose
    call.ended (same call) has outcome done. With draft, only subject <draft>/review
    counts. None when there is none."""
    events = list(events)
    completed = {event["call"] for event in events
                 if event.get("ev") == "call.ended" and event.get("outcome") == "done"}
    return next((event["ts"] for event in reversed(events)
                 if event.get("ev") == "call.started" and event.get("role") == "review"
                 and (draft is None or event.get("subject") == f"{draft}/review")
                 and (not done or event["call"] in completed)), None)


def landed_after(events: Iterable[dict], tasks: Mapping[str, Task], ts: str | None) -> list[dict]:
    """branch.landed records of the given tasks whose ts is later than ts (every one when ts is
    None), in log order. Timestamps compare as strings (fab.log.now's fixed format)."""
    return [event for event in events if event.get("ev") == "branch.landed"
            and event.get("task") in tasks and (ts is None or event["ts"] > ts)]


def open_questions(events: Iterable[dict]) -> list[dict]:
    """question.asked records with no later question.answered for the same task, in log order."""
    pending = []
    for event in events:
        if event.get("ev") == "question.asked":
            pending.append(event)
        elif event.get("ev") == "question.answered":
            pending = [item for item in pending if item["task"] != event["task"]]
    return pending


# Each Claude role's effort, as the user's model sets it (execution-modes.md, the roles table):
# the answerer, settler, issue reply and triager are medium; the designer's calls, the skeleton author,
# its amendments and the structure reviewer are high. Passed explicitly, so a user's own default never leaks in.
EFFORTS = {"answer": "medium", "reply": "medium", "triage": "medium", "settle": "medium"}
EFFORT = "high"


def role_effort(role: str) -> str:
    """The effort a call of this role runs at: EFFORTS, else EFFORT."""
    return EFFORTS.get(role, EFFORT)


def claude_argv(brief_path: Path, workdir: Path, *, model: str = MODEL, effort: str = EFFORT) -> list[str]:
    """`claude -p <prompt> --model <model> --effort <effort> --output-format stream-json --verbose
    --dangerously-skip-permissions --add-dir=<workdir>`, the prompt being a one-line
    instruction to read and follow brief_path. The stream (one JSON event per line; claude
    needs --verbose for it under -p) carries every message's usage, so claude_usage finds the
    call's peak context. No --max-turns: a call is measured, not capped (reports.md 3). The prompt
    comes first and --add-dir takes `=`: --add-dir accepts several directories and would
    otherwise take the prompt for one."""
    return ["claude", "-p", f"Read and follow the brief at {shlex.quote(str(brief_path))}.",
            "--model", model, "--effort", effort, "--output-format", "stream-json", "--verbose",
            "--dangerously-skip-permissions", f"--add-dir={workdir}"]


def start(role: str, subject: str, repo: Path, brief: str, *, sh: Runner = run,
          log_path: Path | None = None, branch: str | None = None,
          amends: str | None = None, base: str = "main",
          fields: Mapping[str, object] | None = None, report_only: bool = False) -> dict:
    """Run a fresh call, keeping its own id, directory, brief, report and result artifacts.

    Create FAB_HOME/calls/<id>/wt on calls/<id> from origin/<base>, fetching first
    when base is not main (also for fabrig), or fetch origin and
    reset the supplied branch from origin/<branch> with worktree add -B. With report_only,
    fetch origin and detach at origin/<base>, log no branch and push nothing; return
    branch "" (docs/design/qa.md, 2). A supplied branch is a ValueError in this mode.
    Rebind Call facts and insert the subject's user answers after them, before the next
    # section or at the end, before saving brief.md so reviews quote them too. --brief-only prints the compiled
    brief before facts and answers are bound. Log call.started (including amends when
    supplied, trunk when base is not main, and fields), run Claude without
    nested-session environment markers, keep its stdout as
    stream.jsonl and its stderr as stderr.log, then
    log call.ended with the report's outcome, claude_usage(stdout).log_fields() and the
    elapsed minutes, then wake the tick with `call <id>` beside log_path. Nothing ends a call
    but TIMEOUT; a call cut short there is measured from what its stream holds. Remove the worktree even on failure; return {call, branch,
    outcome, report}."""
    if role not in ROLES:
        raise ValueError(f"unknown call role {role!r}")
    if report_only and branch is not None:
        raise ValueError("report_only cannot use a branch")
    call_id = f"{role}-{uuid.uuid4().hex}"
    existing = branch is not None
    branch = "" if report_only else (branch if existing else f"calls/{call_id}")
    directory = log.home() / "calls" / call_id
    directory.mkdir(parents=True)
    worktree = directory / "wt"
    brief_path = directory / "brief.md"
    report_path = directory / "report.md"
    brief = _bind_brief(brief, call_id, branch, str(report_path),
                        channel.answers_text(subject, log.read(log_path)))
    fabrig = repo.resolve() == (log.home() / "repos/fabrig").resolve()
    if report_only or existing or fabrig or base != "main":
        sh(["git", "fetch", "origin"], cwd=str(repo), check=True)
    if report_only:
        sh(["git", "worktree", "add", "--detach", str(worktree), f"origin/{base}"],
           cwd=str(repo), check=True)
    else:
        sh(["git", "worktree", "add", "-B" if existing else "-b", branch, str(worktree),
            f"origin/{branch}" if existing else f"origin/{base}"], cwd=str(repo), check=True)
    began = time.monotonic()
    try:
        atomic.write(brief_path, brief)
        fields = dict(fields or {})
        if report_only:
            fields.pop("branch", None)
        else:
            fields["branch"] = branch
        if amends is not None:
            fields["amends"] = amends
        if base != "main":
            fields["trunk"] = base
        log.append("call.started", path=log_path, call=call_id, role=role, subject=subject,
                   **fields)
        environment = {key: value for key, value in os.environ.items()
                       if not key.startswith(("CLAUDECODE", "CLAUDE_CODE_"))}
        result = sh(claude_argv(brief_path, worktree, effort=role_effort(role)), cwd=str(worktree),
                    timeout=TIMEOUT,
                    env=environment)
        atomic.write(directory / "stream.jsonl", result.out)
        atomic.write(directory / "stderr.log", result.err)
        status = _call_result(report_path)
        if fabrig and not report_only:
            sh(["git", "push", "origin", branch], cwd=str(repo), check=True)
        log.append("call.ended", path=log_path, call=call_id, role=role, subject=subject,
                   outcome=status, **claude_usage(result.out).log_fields(), minutes=(time.monotonic() - began) / 60)
        wake.want(f"call {call_id}", path=wake.want_path(log_path))
        return {"call": call_id, "branch": branch, "outcome": status, "report": str(report_path)}
    finally:
        sh(["git", "worktree", "remove", "--force", str(worktree)], cwd=str(repo), check=True)


def _bind_brief(text: str, call_id: str, branch: str, report: str, answers: str) -> str:
    """Bind the run's facts and answers before the rest of its compiled brief."""
    marker = "# Call facts\n\n"
    before, found, after = text.partition(marker)
    if found:
        _, separator, rest = after.partition("\n# ")
        text = before + marker + _facts(call_id, branch, report)
        if answers:
            text += "\n\n" + channel.SECTION + "\n\n" + answers
        if separator:
            text += "\n\n# " + rest
    elif answers:
        text = text.rstrip("\n") + "\n\n" + channel.SECTION + "\n\n" + answers + "\n"
    return text


def claude_usage(stream: str) -> Usage:
    """A call's usage from claude's stdout, one JSON event per line (claude_argv's
    stream-json); a line that does not parse as a JSON object is skipped.

    - The messages: events with type "assistant" whose `message` is an object with a
      `usage` object. Several events of one message share its `message.id` and its usage is
      the last one seen; a message without an id stands alone. A message is the main
      thread's when the event's `parent_tool_use_id` is missing or None; others are
      subagents', whose context is their own.
    - A usage's counts are input_tokens, cache_creation_input_tokens,
      cache_read_input_tokens and output_tokens; a key missing or not a non-negative int
      (bools too) counts 0. A message's context is its input + cache creation + cache read.
    - peak: the largest context of a main-thread message; 0 when there is none.
    - The totals and turns: from the last event with type "result", its `usage` counts and
      its `num_turns` (0 when not an int). Without one (the call timed out or claude
      crashed): every message's counts summed, main thread and subagents, each message once;
      turns the number of main-thread messages.
    Usage(input, cache_write, cache_read, output, peak, turns), the cache write being
    cache_creation_input_tokens. Empty or unreadable output gives all zeros. Pure."""
    messages = {}
    try:
        legacy = json.loads(stream)
    except json.JSONDecodeError:
        legacy = None
    result = legacy if isinstance(legacy, dict) and "type" not in legacy else None
    lines = [legacy] if isinstance(legacy, dict) else []
    if not lines:
        for line in stream.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                lines.append(event)
    for event in lines:
        if event.get("type") == "result":
            result = event
        message = event.get("message")
        if event.get("type") != "assistant" or not isinstance(message, dict):
            continue
        if not isinstance(message.get("usage"), dict):
            continue
        identity = message.get("id")
        key = identity if isinstance(identity, str) else len(messages)
        messages[key] = (_usage_counts(message["usage"]), event.get("parent_tool_use_id") is None)
    peak = max((sum(counts[:3]) for counts, main in messages.values() if main), default=0)
    if result is not None:
        counts = _usage_counts(result.get("usage"))
        turns = result.get("num_turns")
        turns = turns if type(turns) is int else 0
    else:
        counts = tuple(sum(counts[index] for counts, _ in messages.values()) for index in range(4))
        turns = sum(main for _, main in messages.values())
    return Usage(*counts, peak, turns)


def _usage_counts(usage: object) -> tuple[int, int, int, int]:
    usage = usage if isinstance(usage, dict) else {}
    return tuple(value if type(value) is int and value >= 0 else 0
                 for value in (usage.get(key) for key in
                               ("input_tokens", "cache_creation_input_tokens",
                                "cache_read_input_tokens", "output_tokens")))


def _call_result(report_path: Path) -> str:
    """Read the report's outcome, tolerating a missing or unreadable report."""
    try:
        report_text = report_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        report_text = ""
    return outcome(report_text)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse arguments for roles run here, excluding delegated roles and issue replies."""
    from fab import designer

    parser = argparse.ArgumentParser(prog="fab call", description=__doc__)
    commands = parser.add_subparsers(dest="role", required=True)
    for role in (name for name in ROLES if name not in (*designer.ROLES, "reply", "triage")):
        command = commands.add_parser(role)
        if role in ("skeleton", "amend", "settle"):
            command.add_argument("part" if role == "skeleton" else "root")
        command.add_argument("--plan", type=Path, required=True)
        command.add_argument("--brief-only", action="store_true")
        command.add_argument("--tick", action="store_true")
    return parser.parse_args(argv)


def _retire_designs(repo: Path, draft: str, plan_path: str, branch: str) -> list[str]:
    """Designs changed on main but absent from the retire tip (docs/design/calls.md, 2)."""
    from fab import designer

    run(["git", "fetch", "origin"], cwd=str(repo), check=True)
    try:
        main = designer.changed_designs(repo, draft, rev="origin/main", sh=run, plan_path=plan_path)
        tip = designer.changed_designs(repo, draft, rev=f"origin/{branch}", sh=run, plan_path=plan_path)
    except ValueError:
        return []
    return sorted(set(main) - set(tip))


def _chain_call(role: str, root: str, repo: Path, events: list[dict],
                facts: Mapping[str, str], *, draft: str, plan_path: str) -> tuple[str, str, dict]:
    """Compile an amend or settle call from its root, refusing an invalid chain state."""
    from fab import call_review

    chain = call_review.chains(events).get(root)
    if role == "amend":
        if chain is None or chain.state != "amend":
            raise ValueError(f"chain {root!r} must be in state amend")
        designs = ()
        if chain.role == "retire" and chain.refusals and call_review.land_refusal(chain.refusals[-1]):
            designs = _retire_designs(repo, draft, plan_path, chain.branch)
        try:
            text = call_review.amend_brief(chain, designs=designs, **facts)
        except (ValueError, OSError) as error:
            raise BriefError(str(error)) from error
        return text, chain.subject, dict(branch=chain.branch, amends=chain.root)
    attempts = call_review.settle_calls(chain, events) if chain else []
    recorded = {event.get("settle") for event in events if event.get("ev") == "chain.settled"}
    if (chain is None or chain.state != "hold" or len(attempts) >= 2
            or (attempts and attempts[-1] not in recorded)):
        raise ValueError(f"chain {root!r} must be held with a settle attempt left")
    try:
        text = call_review.settle_brief(chain, repo, events, sh=run, **facts)
    except (ValueError, OSError) as error:
        raise BriefError(str(error)) from error
    return text, chain.subject + "/settle", dict(report_only=True, fields={"settles": chain.root})


def answer_tasks(plan: Plan, tasks: Mapping[str, Task], events: Sequence[dict], *,
                 folded: Sequence[tier_reds.Red] | None = None) -> dict[str, Task]:
    """The task set shared by the tick and the answer call's brief.

    Add integration repairs, drop loaded tasks of fix.FIX_KINDS, then fold red and
    finding repairs from events. folded reuses the round's red snapshot. A stop's
    question comes through fab.foreman.questions over this set, without a stop task.
    """
    tasks = integration.with_repairs(plan, tasks, events)
    return {**{identifier: task for identifier, task in tasks.items() if task.kind not in fix.FIX_KINDS},
            **tier_reds.tasks(plan, events, folded=folded), **fixes.tasks(plan, events)}


def _answer_questions(tasks: Mapping[str, Task], events: list[dict]) -> list[dict]:
    """Queued questions with stop reports captured before each ask, in log order."""
    queued = {(item.task, item.run, item.text, item.asked): item
              for item in foreman.questions(tasks, events) if item.state == "queued"}
    open_asks = {id(event) for event in open_questions(event for event in events if "task" in event)}
    stops, questions = {}, []
    for event in events:
        if event.get("ev") == "plan.stopped" and "task" in event:
            stops[event["task"]] = event.get("report", "")
        elif id(event) in open_asks:
            key = tuple(event.get(field) for field in ("task", "run", "text", "ts"))
            item = queued.get(key)
            if item is None:
                continue
            question = dict(task=item.task, run=item.run, text=item.text, foreman=item.report)
            if item.task not in tasks:
                question["stop"] = stops.get(item.task, "")
            questions.append(question)
    return questions


def _compile_call(args, plan, tasks, root, repo, events, facts, plan_path):
    """Validate a fresh call's part, then translate only brief builder failures."""
    if args.role in ("amend", "settle"):
        return _chain_call(args.role, args.root, repo, events, facts,
                           draft=plan.draft, plan_path=plan_path)
    if args.role == "skeleton" and args.part not in plan.parts:
        raise ValueError(f"unknown part {args.part!r}")
    if args.role == "skeleton":
        statuses = {key: view.status for key, view in fold(tasks, events).items()}
    if args.role == "answer":
        tasks = answer_tasks(plan, tasks, events)
        questions = _answer_questions(tasks, events)
    try:
        if args.role == "skeleton":
            text = skeleton_brief(plan, args.part, tasks, statuses, root, **facts)
            subject = f"{plan.draft}/{args.part}"
        elif args.role == "review":
            text = review_brief(plan, tasks, events, root, plan_path=plan_path, **facts)
            subject = f"{plan.draft}/review"
        else:
            text = answer_brief(questions, tasks, root, plan=plan, **facts)
            subject = plan.draft
    except (ValueError, OSError) as error:
        raise BriefError(str(error)) from error
    return text, subject, {}


def _park_call(args, plan, events, error):
    """Name a chain's root and subject when its amend or settle brief failed."""
    from fab import call_review

    if args.role in ("amend", "settle"):
        chain = call_review.chains(events)[args.root]
        park(args.role, chain.subject, error, call=chain.root)
    else:
        subject = (f"{plan.draft}/{args.part}" if args.role == "skeleton" else
                   f"{plan.draft}/review" if args.role == "review" else plan.draft)
        park(args.role, subject, error)


def main(argv: list[str]) -> int:
    """Compile and run skeleton PART, answer, review or amend ROOT with --plan PLAN_DIR.
    Delegate cut, contract, decision and retire to fab.designer.main, and triage
    to fab.triage.main.

    Answer briefs contain only queued questions and include any foreman report.
    Amend requires a known chain in state amend and reuses its subject and branch.
    Settle ROOT judges a held chain in a report-only call, subject <subject>/settle.
    --brief-only prints the brief; otherwise print outcome and branch, exiting 0 for Done
    and 1 for a failed call, invalid chain or compilation error."""
    from fab import designer, triage

    if argv and argv[0] == "triage":
        return triage.main(argv[1:])
    if argv and argv[0] in designer.ROLES:
        return designer.main(argv)
    args = _parse_args(argv)
    try:
        directory = args.plan.resolve()
        plan = load_plan(directory / "plan.toml")
        tasks = load_tasks(directory / "tasks", plan.draft, plan.repo)
        checkout = run(["git", "rev-parse", "--show-toplevel"], cwd=str(directory), check=True)
        root = Path(checkout.out.strip()).resolve()
        plan_path = directory.relative_to(root).as_posix()
        events = log.read()
        facts = dict(call_id="(assigned at start)", branch="(assigned at start)", report="(assigned at start)")
        repo = log.home() / "repos/fabrig" if plan.repo == "fabrig" else root
        text, subject, options = _compile_call(args, plan, tasks, root, repo, events, facts, plan_path)
        if args.brief_only:
            print(text)
            return 0
        result = start(args.role, subject, repo, text, sh=run, base=plan.trunk, **options)
        print(f"{result['outcome']} {result['branch']}")
        return 0 if result["outcome"] == "done" else 1
    except BriefError as error:
        if args.tick and not args.brief_only:
            _park_call(args, plan, events, error)
        print(f"fab call: {error}", file=sys.stderr)
        return 1
    except (OSError, ValueError, Failed) as error:
        print(f"fab call: {error}", file=sys.stderr)
        return 1


def _facts(call_id: str, branch: str, report: str) -> str:
    return f"- Call: {call_id}\n- Branch: `{branch}`\n- Report: write it to `{report}`"


def _brief(sections: list[tuple[str, str]]) -> str:
    text = "\n\n".join(f"# {name}\n\n{body}" for name, body in sections) + "\n"
    if len(text) > BRIEF_LIMIT:
        name, body = max(sections, key=lambda item: len(item[1]))
        raise ValueError(f"brief exceeds BRIEF_LIMIT ({BRIEF_LIMIT} characters); largest section: {name} ({len(body)})")
    return text
