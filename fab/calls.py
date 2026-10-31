"""Claude calls: fresh, short sessions on briefs compiled by code (docs/design/fab.md, 13).

A call never waits, polls or watches. Code compiles its brief from files; the call writes
files on its chain's branch and ends with a report whose first line is its outcome, as a
run's does. The dispatcher reviews the branch before landing it.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import shlex
import sys
import time
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from fab import atomic, foreman, log, state
from fab.plan import Plan, Task, load_plan, load_tasks
from fab.run import TASTE, outcome
from fab.sh import Failed, Runner, run
from fab.state import fold

ROLES = {
    "skeleton": Path(__file__).resolve().parent / "roles" / "skeleton.md",
    "answer": Path(__file__).resolve().parent / "roles" / "answerer.md",
    "review": Path(__file__).resolve().parent / "roles" / "reviewer.md",
    "amend": Path(__file__).resolve().parent / "roles" / "amender.md",
    "cut": Path(__file__).resolve().parent / "roles" / "cut.md",
    "contract": Path(__file__).resolve().parent / "roles" / "contract.md",
    "decision": Path(__file__).resolve().parent / "roles" / "decision.md",
    "retire": Path(__file__).resolve().parent / "roles" / "retire.md",
}
MODEL = "claude-opus-5-5"  # every Claude call's model, explicit (the user, 10-30): Opus 5.5
BRIEF_LIMIT = 200_000  # characters, about 50k tokens: what code puts in; the call reads the rest itself
TIMEOUT = 40 * 60


@dataclass(frozen=True)
class Usage:
    """A call's Claude usage, as claude_usage reads it from claude's stream and call.ended
    carries it (docs/design/fab.md, 13.5). Every count is in tokens."""

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
        raise NotImplementedError


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
    """The text a part's `design` cites, e.g. "docs/design/fab.md, 6 and 8": the whole document
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
    order for contract); the user's drafts; the cited design; the inventory; and the task
    specs for its needs as format examples. Accepts skeleton or contract, else ValueError.
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
    examples = []
    for task in tasks.values():
        if task.part in part.needs:
            path = Path(task.path)
            label = path.relative_to(root) if path.is_absolute() else path
            examples.append(f"## {task.id} ({label})\n\n{(root / path).read_text(encoding='utf-8')}")
    return _brief([
        ("Role", ROLES[role].read_text(encoding="utf-8")),
        ("Call facts", _facts(call_id, branch, report)),
        ("Plan parts and slices", _parts_table(plan, tasks, statuses)),
        ("Part to design", details),
        ("The user's drafts", drafts_text(plan, root)),
        ("Cited design", design_text(root, part.design)),
        ("Inventory", render_inventory(inventory(root))),
        ("Task spec examples", "\n\n".join(examples) or "(none)"),
    ])


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
    asking run's report path and, when present, its foreman report path; the inventory."""
    sections = [
        ("Role", ROLES["answer"].read_text(encoding="utf-8")),
        ("Call facts", _facts(call_id, branch, report)),
    ]
    if plan is not None:
        sections.append(("The user's drafts", drafts_text(plan, root)))
    for question in questions:
        task = tasks[question["task"]]
        path = Path(task.path)
        label = path.relative_to(root) if path.is_absolute() else path
        run_id = question["run"]
        report_path = log.home() / "runs" / run_id / "report.md"
        foreman_line = f"- Foreman: `{question['foreman']}`\n" if question.get("foreman") else ""
        sections.append((f"Question: {task.id} ({run_id})",
                         f"- Task: {task.id}\n- Run: {run_id}\n- Report: `{report_path}`\n{foreman_line}\n"
                         f"{question['text']}\n\n## Task spec ({label})\n\n"
                         f"{(root / path).read_text(encoding='utf-8')}"))
    sections.append(("Inventory", render_inventory(inventory(root))))
    return _brief(sections)


def review_brief(plan: Plan, tasks: dict[str, Task], events: list[dict], root: Path, *,
                 call_id: str, branch: str, report: str) -> str:
    """The structure reviewer's brief (docs/design/fab.md, 12): its role text (ROLES["review"]);
    the call's facts; "Plan parts and slices", the same table skeleton_brief writes (shared,
    not copied), statuses from fab.state.fold(tasks, events), and a line `Specs:
    docs/plan/<draft>/tasks/`; "Landed since the last review": per record of
    landed_after(events, tasks, last_review(events, done=True)), in log order, a heading
    `## <task> (`<branch>`, main `<main[:12]>`)` and the text of FAB_HOME/digests/<run>.md for
    the task's last run.started before that record, or `(no digest)` when it has none or
    the file is missing; `(none)` when nothing landed; "Taste", the text of fab.run.TASTE;
    "Designs", per distinct path cited by the landed tasks' parts (the citation before its
    comma), in first-landed order, `## <path>` and design_text(root, citation); "Inventory".
    Raises ValueError past BRIEF_LIMIT, naming the largest section."""
    landed = landed_after(events, tasks, last_review(events, done=True))
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
        citation = plan.parts[tasks[record["task"]].part].design
        designs.setdefault(citation.split(",", 1)[0].strip(), citation)
    statuses = {key: view.status for key, view in fold(tasks, events).items()}
    return _brief([
        ("Role", ROLES["review"].read_text(encoding="utf-8")),
        ("Call facts", _facts(call_id, branch, report)),
        ("Plan parts and slices", _parts_table(plan, tasks, statuses) +
         f"\n\nSpecs: docs/plan/{plan.draft}/tasks/"),
        ("Landed since the last review", "\n\n".join(records) or "(none)"),
        ("Taste", TASTE.read_text(encoding="utf-8")),
        ("The user's drafts", drafts_text(plan, root)),
        ("Designs", "\n\n".join(f"## {path}\n\n{design_text(root, citation)}"
                                 for path, citation in designs.items())),
        ("Inventory", render_inventory(inventory(root))),
    ])


def last_review(events: Iterable[dict], *, done: bool = False) -> str | None:
    """The ts of the latest call.started with role review; with done, only of one whose
    call.ended (same call) has outcome done. None when there is none."""
    events = list(events)
    completed = {event["call"] for event in events
                 if event.get("ev") == "call.ended" and event.get("outcome") == "done"}
    return next((event["ts"] for event in reversed(events)
                 if event.get("ev") == "call.started" and event.get("role") == "review"
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
# the answerer is medium; the designer's calls, the skeleton author, its amendments and the
# structure reviewer are high. Passed explicitly, so a user's own default never leaks in.
EFFORTS = {"answer": "medium"}
EFFORT = "high"


def role_effort(role: str) -> str:
    """The effort a call of this role runs at: EFFORTS, else EFFORT."""
    return EFFORTS.get(role, EFFORT)


def claude_argv(brief_path: Path, workdir: Path, *, model: str = MODEL, effort: str = EFFORT) -> list[str]:
    """`claude -p <prompt> --model <model> --effort <effort> --output-format stream-json --verbose
    --dangerously-skip-permissions --add-dir=<workdir>`, the prompt being a one-line
    instruction to read and follow brief_path. The stream (one JSON event per line; claude
    needs --verbose for it under -p) carries every message's usage, so claude_usage finds the
    call's peak context. No --max-turns: a call is measured, not capped (13.5). The prompt
    comes first and --add-dir takes `=`: --add-dir accepts several directories and would
    otherwise take the prompt for one."""
    return ["claude", "-p", f"Read and follow the brief at {shlex.quote(str(brief_path))}.",
            "--model", model, "--effort", effort, "--output-format", "json",
            "--dangerously-skip-permissions", f"--add-dir={workdir}"]


def start(role: str, subject: str, repo: Path, brief: str, *, sh: Runner = run,
          log_path: Path | None = None, branch: str | None = None,
          amends: str | None = None) -> dict:
    """Run a fresh call, keeping its own id, directory, brief, report and result artifacts.

    Create FAB_HOME/calls/<id>/wt on calls/<id> from origin/main, or fetch origin and
    reset the supplied branch from origin/<branch> with worktree add -B. Rebind Call facts,
    log call.started (including amends when supplied), run Claude without nested-session
    environment markers, keep its stdout as stream.jsonl and its stderr as stderr.log, then
    log call.ended with the report's outcome, claude_usage(stdout).log_fields() and the
    elapsed minutes. Nothing ends a call but TIMEOUT; a call cut short there is measured from
    what its stream holds. Remove the worktree even on failure; return {call, branch,
    outcome, report}."""
    if role not in ROLES:
        raise ValueError(f"unknown call role {role!r}")
    call_id = f"{role}-{uuid.uuid4().hex}"
    existing = branch is not None
    branch = branch if existing else f"calls/{call_id}"
    directory = log.home() / "calls" / call_id
    directory.mkdir(parents=True)
    worktree = directory / "wt"
    brief_path = directory / "brief.md"
    report_path = directory / "report.md"
    marker = "# Call facts\n\n"
    before, found, after = brief.partition(marker)
    if found:
        _, separator, rest = after.partition("\n\n# ")
        brief = before + marker + _facts(call_id, branch, str(report_path))
        if separator:
            brief += separator + rest
    if existing:
        sh(["git", "fetch", "origin"], cwd=str(repo), check=True)
    sh(["git", "worktree", "add", "-B" if existing else "-b", branch, str(worktree),
        f"origin/{branch}" if existing else "origin/main"], cwd=str(repo), check=True)
    began = time.monotonic()
    try:
        atomic.write(brief_path, brief)
        fields = {"amends": amends} if amends is not None else {}
        log.append("call.started", path=log_path, call=call_id, role=role, subject=subject,
                   branch=branch, **fields)
        environment = {key: value for key, value in os.environ.items()
                       if not key.startswith(("CLAUDECODE", "CLAUDE_CODE_"))}
        result = sh(claude_argv(brief_path, worktree, effort=role_effort(role)), cwd=str(worktree),
                    timeout=TIMEOUT,
                    env=environment)
        atomic.write(directory / "result.json", result.out)
        atomic.write(directory / "stderr.log", result.err)
        status, tokens = _call_result(result.out, report_path)
        log.append("call.ended", path=log_path, call=call_id, role=role, subject=subject,
                   outcome=status, tokens=tokens, minutes=(time.monotonic() - began) / 60)
        return {"call": call_id, "branch": branch, "outcome": status, "report": str(report_path)}
    finally:
        sh(["git", "worktree", "remove", "--force", str(worktree)], cwd=str(repo), check=True)


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
    raise NotImplementedError


def _call_result(text: str, report_path: Path) -> tuple[str, str]:
    """Read the report's outcome and JSON usage, tolerating missing or malformed output."""
    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        result = {}
    usage = result.get("usage", {}) if isinstance(result, dict) else {}
    if not isinstance(usage, dict):
        usage = {}
    tokens = "/".join(str(usage.get(key, 0)) for key in
                      ("input_tokens", "cache_read_input_tokens", "output_tokens"))
    try:
        report_text = report_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        report_text = ""
    return outcome(report_text), tokens


def main(argv: list[str]) -> int:
    """Compile and run skeleton PART, answer, review or amend ROOT with --plan PLAN_DIR.
    Delegate cut, contract, decision and retire to fab.designer.main.

    Answer briefs contain only queued questions and include any foreman report.
    Amend requires a known chain in state amend and reuses its subject and branch.
    --brief-only prints the brief; otherwise print outcome and branch, exiting 0 for Done
    and 1 for a failed call, invalid chain or compilation error."""
    from fab import call_review, designer

    if argv and argv[0] in designer.ROLES:
        return designer.main(argv)
    parser = argparse.ArgumentParser(prog="fab call", description=__doc__)
    commands = parser.add_subparsers(dest="role", required=True)
    for role in (name for name in ROLES if name not in designer.ROLES):
        command = commands.add_parser(role)
        if role in ("skeleton", "amend"):
            command.add_argument("part" if role == "skeleton" else "root")
        command.add_argument("--plan", type=Path, required=True)
        command.add_argument("--brief-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        directory = args.plan.resolve()
        plan = load_plan(directory / "plan.toml")
        tasks = load_tasks(directory / "tasks", plan.draft, plan.repo)
        checkout = run(["git", "rev-parse", "--show-toplevel"], cwd=str(directory), check=True)
        root = Path(checkout.out.strip())
        events = log.read()
        facts = dict(call_id="(assigned at start)", branch="(assigned at start)", report="(assigned at start)")
        options = {}
        if args.role == "amend":
            chain = call_review.chains(events).get(args.root)
            if chain is None or chain.state != "amend":
                raise ValueError(f"chain {args.root!r} must be in state amend")
            text = call_review.amend_brief(chain, **facts)
            subject = chain.subject
            options = dict(branch=chain.branch, amends=chain.root)
        elif args.role == "skeleton":
            if args.part not in plan.parts:
                raise ValueError(f"unknown part {args.part!r}")
            statuses = {key: view.status for key, view in fold(tasks, events).items()}
            text = skeleton_brief(plan, args.part, tasks, statuses, root, **facts)
            subject = f"{plan.draft}/{args.part}"
        elif args.role == "review":
            text = review_brief(plan, tasks, events, root, **facts)
            subject = f"{plan.draft}/review"
        else:
            questions = [dict(task=item.task, run=item.run, text=item.text, foreman=item.report)
                         for item in foreman.questions(tasks, events) if item.state == "queued"]
            text = answer_brief(questions, tasks, root, plan=plan, **facts)
            subject = plan.draft
        if args.brief_only:
            print(text)
            return 0
        result = start(args.role, subject, root, text, sh=run, **options)
        print(f"{result['outcome']} {result['branch']}")
        return 0 if result["outcome"] == "done" else 1
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
