"""Claude calls: fresh, short sessions on briefs compiled by code (docs/design/fab.md, 13).

A call never waits, polls or watches. Code compiles its brief from files; the call writes
files on a branch of its own and ends with a report whose first line is its outcome, as a
run's does. The dispatcher lands what it wrote.
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

from fab import log
from fab.plan import Plan, Task, load_plan, load_tasks
from fab.run import TASTE, _write, outcome
from fab.sh import Failed, Runner, run
from fab.state import fold

ROLES = {
    "skeleton": Path(__file__).resolve().parent / "roles" / "skeleton.md",
    "answer": Path(__file__).resolve().parent / "roles" / "answerer.md",
    "review": Path(__file__).resolve().parent / "roles" / "reviewer.md",
}
MODEL = "claude-opus-5-5"
BRIEF_LIMIT = 200_000  # characters, about 50k tokens: what code puts in; the call reads the rest itself
TIMEOUT = 40 * 60


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


def skeleton_brief(plan: Plan, part_id: str, tasks: dict[str, Task], statuses: dict[str, str],
                   root: Path, *, call_id: str, branch: str, report: str) -> str:
    """The skeleton author's brief: its role text; the call's facts (call, branch, report path);
    the plan's parts and slices as a table with each part's status (designed, done, or not
    designed); the part to design (id, title, mode, needs, design citation); the cited design
    text; the inventory; and the task specs that exist for the part's needs, as examples of
    the format. Raises ValueError past BRIEF_LIMIT, naming the largest section."""
    part = plan.parts[part_id]
    examples = []
    for task in tasks.values():
        if task.part in part.needs:
            path = Path(task.path)
            label = path.relative_to(root) if path.is_absolute() else path
            examples.append(f"## {task.id} ({label})\n\n{(root / path).read_text(encoding='utf-8')}")
    return _brief([
        ("Role", ROLES["skeleton"].read_text(encoding="utf-8")),
        ("Call facts", _facts(call_id, branch, report)),
        ("Plan parts and slices", _parts_table(plan, tasks, statuses)),
        ("Part to design", f"- Id: {part.id}\n- Title: {part.title}\n- Mode: {part.mode}\n"
         f"- Needs: {', '.join(part.needs) or '(none)'}\n- Design: {part.design}"),
        ("Cited design", design_text(root, part.design)),
        ("Inventory", render_inventory(inventory(root))),
        ("Task spec examples", "\n\n".join(examples) or "(none)"),
    ])


def _parts_table(plan: Plan, tasks: Mapping[str, Task], statuses: Mapping[str, str]) -> str:
    rows = ["| Part | Title | Mode | Needs | Status |", "| --- | --- | --- | --- | --- |"]
    for item in plan.parts.values():
        specs = [task for task in tasks.values() if task.part == item.id]
        status = ("done" if item.done or specs and all(statuses.get(task.id) == "landed" for task in specs)
                  else "designed" if specs else "not designed")
        rows.append(f"| {item.id} | {item.title} | {item.mode} | {', '.join(item.needs) or '-'} | {status} |")
    rows.extend(["", "| Slice | Story | Parts | Walk |", "| --- | --- | --- | --- |"])
    for item in plan.slices:
        rows.append(f"| {item.id} | {item.story} | {', '.join(item.parts)} | {item.walk} |")
    return f"Plan: {plan.draft}\nRepository: {plan.repo}\n\n" + "\n".join(rows)


def answer_brief(questions: list[dict], tasks: dict[str, Task], root: Path, *, call_id: str,
                 branch: str, report: str) -> str:
    """The answerer's brief: its role text; the call's facts; each open question (task, run,
    text) with its task spec and the run's report path; the inventory."""
    sections = [
        ("Role", ROLES["answer"].read_text(encoding="utf-8")),
        ("Call facts", _facts(call_id, branch, report)),
    ]
    for question in questions:
        task = tasks[question["task"]]
        path = Path(task.path)
        label = path.relative_to(root) if path.is_absolute() else path
        run_id = question["run"]
        report_path = log.home() / "runs" / run_id / "report.md"
        sections.append((f"Question: {task.id} ({run_id})",
                         f"- Task: {task.id}\n- Run: {run_id}\n- Report: `{report_path}`\n\n"
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


def claude_argv(brief_path: Path, workdir: Path, *, model: str = MODEL) -> list[str]:
    """`claude -p <prompt> --model <model> --output-format json --dangerously-skip-permissions
    --add-dir=<workdir>`, the prompt being a one-line instruction to read and follow brief_path.
    The prompt comes first and --add-dir takes `=`: --add-dir accepts several directories and
    would otherwise take the prompt for one."""
    return ["claude", "-p", f"Read and follow the brief at {shlex.quote(str(brief_path))}.",
            "--model", model, "--output-format", "json", "--dangerously-skip-permissions",
            f"--add-dir={workdir}"]


def start(role: str, subject: str, repo: Path, brief: str, *, sh: Runner = run,
          log_path: Path | None = None) -> dict:
    """Run one call to its end (calls are short; the dispatcher waits for them in a thread or
    a unit, not here). Create the worktree FAB_HOME/calls/<id>/wt on a new branch
    `calls/<id>` from origin/main of repo (a clone), write the brief to FAB_HOME/calls/<id>/brief.md,
    log call.started (call, role, subject, branch), run claude_argv in the worktree with
    TIMEOUT, keep its JSON output as result.json and its stderr as stderr.log, read the report
    (FAB_HOME/calls/<id>/report.md),
    log call.ended (call, role, subject, outcome as fab.run.outcome of the report, or failed
    when there is none; tokens from the JSON usage as "input/cache_read/output"; minutes), and
    remove the worktree, keeping the branch. Returns {call, branch, outcome, report}.

    The call is a fresh top-level session: claude runs with the environment minus every
    variable starting with CLAUDECODE or CLAUDE_CODE_, so a call started from inside another
    Claude session is not refused as nested."""
    if role not in ROLES:
        raise ValueError(f"unknown call role {role!r}")
    call_id = f"{role}-{uuid.uuid4().hex}"
    branch = f"calls/{call_id}"
    directory = log.home() / "calls" / call_id
    directory.mkdir(parents=True)
    worktree = directory / "wt"
    brief_path = directory / "brief.md"
    report_path = directory / "report.md"
    # Only the facts section is rebound; quoted designs and specs stay verbatim.
    marker = "# Call facts\n\n"
    before, found, after = brief.partition(marker)
    if found:
        _, separator, rest = after.partition("\n\n# ")
        brief = before + marker + _facts(call_id, branch, str(report_path))
        if separator:
            brief += separator + rest
    sh(["git", "worktree", "add", "-b", branch, str(worktree), "origin/main"],
       cwd=str(repo), check=True)
    began = time.monotonic()
    try:
        _write(brief_path, brief)
        log.append("call.started", path=log_path, call=call_id, role=role, subject=subject, branch=branch)
        environment = {key: value for key, value in os.environ.items()
                       if not key.startswith(("CLAUDECODE", "CLAUDE_CODE_"))}
        result = sh(claude_argv(brief_path, worktree), cwd=str(worktree), timeout=TIMEOUT,
                    env=environment)
        _write(directory / "result.json", result.out)
        _write(directory / "stderr.log", result.err)
        try:
            data = json.loads(result.out)
        except json.JSONDecodeError:
            data = {}
        usage = data.get("usage", {}) if isinstance(data, dict) else {}
        if not isinstance(usage, dict):
            usage = {}
        tokens = "/".join(str(usage.get(key, 0)) for key in
                          ("input_tokens", "cache_read_input_tokens", "output_tokens"))
        try:
            report_text = report_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            report_text = ""
        status = outcome(report_text)
        log.append("call.ended", path=log_path, call=call_id, role=role, subject=subject,
                   outcome=status, tokens=tokens, minutes=(time.monotonic() - began) / 60)
        return {"call": call_id, "branch": branch, "outcome": status, "report": str(report_path)}
    finally:
        sh(["git", "worktree", "remove", "--force", str(worktree)], cwd=str(repo), check=True)


def main(argv: list[str]) -> int:
    """`fab call skeleton PART --plan PLAN_DIR` and `fab call answer --plan PLAN_DIR`: compile the
    brief from the plan's repository (PLAN_DIR's checkout), run the call, print its outcome and
    branch; exit 0 when Done, 1 otherwise. `--brief-only` prints the brief and runs nothing."""
    parser = argparse.ArgumentParser(prog="fab call", description=__doc__)
    commands = parser.add_subparsers(dest="role", required=True)
    for role in ROLES:
        command = commands.add_parser(role)
        if role == "skeleton":
            command.add_argument("part")
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
        if args.role == "skeleton":
            if args.part not in plan.parts:
                raise ValueError(f"unknown part {args.part!r}")
            statuses = {key: view.status for key, view in fold(tasks, events).items()}
            text = skeleton_brief(plan, args.part, tasks, statuses, root, **facts)
            subject = f"{plan.draft}/{args.part}"
        elif args.role == "review":
            text = review_brief(plan, tasks, events, root, **facts)
            subject = f"{plan.draft}/review"
        else:
            questions = [item for item in open_questions(events) if item["task"] in tasks]
            text = answer_brief(questions, tasks, root, **facts)
            subject = plan.draft
        if args.brief_only:
            print(text)
            return 0
        result = start(args.role, subject, root, text, sh=run)
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
