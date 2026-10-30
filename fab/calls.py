"""Claude calls: fresh, short sessions on briefs compiled by code (docs/design/fab.md, 10).

A call never waits, polls or watches. Code compiles its brief from files; the call writes
files on a branch of its own and ends with a report whose first line is its outcome, as a
run's does. The dispatcher lands what it wrote.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from fab.plan import Plan, Task
from fab.sh import Runner, run

ROLES = {
    "skeleton": Path(__file__).resolve().parent / "roles" / "skeleton.md",
    "answer": Path(__file__).resolve().parent / "roles" / "answerer.md",
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
    raise NotImplementedError


def render_inventory(signatures: Iterable[Signature]) -> str:
    """Markdown: a `## <module>` heading per module, then one `- `text` — doc` line per entry."""
    raise NotImplementedError


def design_text(root: Path, citation: str) -> str:
    """The text a part's `design` cites, e.g. "docs/design/fab.md, 6 and 8": the whole document
    at the cited path (sections are not cut out); an unreadable path gives a one-line note."""
    raise NotImplementedError


def skeleton_brief(plan: Plan, part_id: str, tasks: dict[str, Task], statuses: dict[str, str],
                   root: Path, *, call_id: str, branch: str, report: str) -> str:
    """The skeleton author's brief: its role text; the call's facts (call, branch, report path);
    the plan's parts and slices as a table with each part's status (designed, done, or not
    designed); the part to design (id, title, mode, needs, design citation); the cited design
    text; the inventory; and the task specs that exist for the part's needs, as examples of
    the format. Raises ValueError past BRIEF_LIMIT, naming the largest section."""
    raise NotImplementedError


def answer_brief(questions: list[dict], tasks: dict[str, Task], root: Path, *, call_id: str,
                 branch: str, report: str) -> str:
    """The answerer's brief: its role text; the call's facts; each open question (task, run,
    text) with its task spec and the run's report path; the inventory."""
    raise NotImplementedError


def open_questions(events: Iterable[dict]) -> list[dict]:
    """question.asked records with no later question.answered for the same task, in log order."""
    raise NotImplementedError


def claude_argv(brief_path: Path, workdir: Path, *, model: str = MODEL) -> list[str]:
    """`claude -p --model <model> --output-format json --dangerously-skip-permissions
    --add-dir <workdir>`, the prompt being a one-line instruction to read and follow brief_path."""
    raise NotImplementedError


def start(role: str, subject: str, repo: Path, brief: str, *, sh: Runner = run,
          log_path: Path | None = None) -> dict:
    """Run one call to its end (calls are short; the dispatcher waits for them in a thread or
    a unit, not here). Create the worktree FAB_HOME/calls/<id>/wt on a new branch
    `calls/<id>` from origin/main of repo (a clone), write the brief to FAB_HOME/calls/<id>/brief.md,
    log call.started (call, role, subject, branch), run claude_argv in the worktree with
    TIMEOUT, keep its JSON output as result.json, read the report (FAB_HOME/calls/<id>/report.md),
    log call.ended (call, role, subject, outcome as fab.run.outcome of the report, or failed
    when there is none; tokens from the JSON usage as "input/cache_read/output"; minutes), and
    remove the worktree, keeping the branch. Returns {call, branch, outcome, report}."""
    raise NotImplementedError


def main(argv: list[str]) -> int:
    """`fab call skeleton PART --plan PLAN_DIR` and `fab call answer --plan PLAN_DIR`: compile the
    brief from the plan's repository (PLAN_DIR's checkout), run the call, print its outcome and
    branch; exit 0 when Done, 1 otherwise. `--brief-only` prints the brief and runs nothing."""
    raise NotImplementedError
