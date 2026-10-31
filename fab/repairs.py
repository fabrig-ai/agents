"""The foreman reads a refusal and writes its repair or rebase, or retries the tip (13.1).

When the landing refuses a task's branch, the task waits for a foreman run before any repair
or rebase run starts. The foreman, a read-only Codex run, reads the refusal, the failing
step's log and the task spec, and says one of two things. Either the red is the branch's:
it writes what failed, where to look and what to change, which the tick appends to the spec
as a `## Repair` (or, for a conflict, `## Rebase`) section, lands, and hands to the next
run's brief. Or the red is not the branch's (a fault of the gate, a flake): the tick retries
the tip unchanged and no run starts. A foreman that cannot say leaves the repair run to
start as it did before, with the refusal quoted in its brief.

`refusals` folds where each open refusal stands from the log; fab.dispatch turns each state
into its next step. Refusal foremen are foreman runs (fab.foreman.task_field, KIND) whose
run.started carries `refused` instead of `asked`, so fab.foreman.questions leaves them out.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from fab import foreman, log, run as runs, spec_edit
from fab.hosts import Host
from fab.plan import Task
from fab.sh import Runner, run

KIND = foreman.KIND  # a refusal's foreman run is a foreman run
EFFORT = foreman.EFFORT
ROLE = Path(__file__).resolve().parent / "roles" / "foreman-repair.md"  # its role text
SETTLED = "refusal.settled"  # the event the tick logs once it has acted on a foreman's verdict
VERDICTS = ("fix", "retry", "none")  # refusal.settled's verdict
REBASE_STEPS = ("rebase", "merge")  # refused steps that are conflicts: a rebase run follows
NEVER_RETRIED = ("paths", "gate:")  # step prefixes whose red is the branch's by construction
SECTION_LINES = 30  # lines of a foreman's report after its first that the section keeps
STATES = ("foreman", "deciding", "decided", "settled", "fallback")


@dataclass(frozen=True)
class Refusal:
    """An open refusal of a task's branch and where it stands, as refusals folds it."""

    task: str  # the refused task's id, `<draft>/<task>`
    branch: str  # the refused branch, as branch.rejected names it
    tip: str  # the refused tip ("" when the record has none)
    step: str  # the refused step: rebase, merge, test, gate:<gate>, a queue step ...
    log: str  # the record's log: a queue log path on the gate, fab land's detail, a digest path
    findings: str  # the gates' findings ("" when the record has none)
    at: str  # the branch.rejected ts
    kind: str  # the run that follows: "rebase" when step is in REBASE_STEPS, else "repair"
    state: str  # one of STATES
    since: str  # the ts the state began
    retried: bool = False  # this branch was retried unchanged since the task's last run
    foreman: str | None = None  # the counted foreman run
    report: str = ""  # its run.ended's report path, once ended
    verdict: str = ""  # refusal.settled's verdict, once settled
    section: str = ""  # refusal.settled's section ("" unless the verdict is fix)


def refusals(tasks: Mapping[str, Task], events: Iterable[dict]) -> list[Refusal]:
    """Every open refusal of the given tasks, in the order of their branch.rejected, with
    where it stands.

    Open: a task's last branch.rejected with no later run.started, branch.ready or
    branch.landed for the same task (records whose task field is the task's id; a foreman
    run's task field is fab.foreman.task_field's, so it never closes one). A later
    branch.rejected of the task replaces it. A task outside tasks is left out.

    Its foreman run is the last run.started after the branch.rejected with kind KIND, task
    fab.foreman.task_field(<task>) and a `refused` field; with the first run.ended of the
    same run. Its settlement is the first SETTLED record after that run.ended with the same
    task and `run` equal to the foreman run.

    state and since, the first that holds:
    - foreman, since the branch.rejected ts: no foreman run yet;
    - deciding, since the foreman run's run.started ts: it has no run.ended;
    - fallback, since its run.ended ts: it ended with an outcome other than done (failed,
      question, infra): the repair or rebase run starts with the refusal in its brief, as
      it would without a foreman. A foreman runs once per refusal;
    - decided, since its run.ended ts: it ended done and nothing settled it yet;
    - settled, since the SETTLED ts: verdict and section from that record.
    foreman is the counted run's id and report its run.ended's report ("" before it ended).

    retried: a SETTLED record with verdict retry for the task lies after the task's last
    run.started before this branch.rejected (or anywhere before it, without one): the branch
    has already gone back unchanged once.

    tip, log and findings are the record's, "" when missing; kind follows REBASE_STEPS.
    Walk the events once in log order, keeping each record's index, so equal timestamps keep
    their order. Pure. Records missing a field the rule reads (a branch.rejected without
    task, branch, step or ts; a run.started without run, task, kind or ts; a run.ended
    without run, outcome or ts; a SETTLED without task, run, verdict or ts) are skipped."""
    opened, last_runs, retries, foremen, ends, settlements = {}, {}, {}, {}, {}, {}
    for position, event in enumerate(events):
        kind = event.get("ev")
        if kind == "branch.rejected" and all(k in event for k in ("task", "branch", "step", "ts")):
            task = event["task"]
            if task in tasks:
                opened[task] = position, event, retries.get(task, -1) > last_runs.get(task, -1)
        elif kind == "run.started" and all(k in event for k in ("run", "task", "kind", "ts")):
            task = event["task"]
            last_runs[task] = position
            opened.pop(task, None)
            if event["kind"] == KIND and "refused" in event:
                foremen[task] = position, event
        elif kind in ("branch.ready", "branch.landed") and "task" in event:
            opened.pop(event["task"], None)
        elif kind == "run.ended" and all(k in event for k in ("run", "outcome", "ts")):
            ends.setdefault(event["run"], (position, event))
        elif kind == SETTLED and all(k in event for k in ("task", "run", "verdict", "ts")):
            if event["verdict"] == "retry":
                retries[event["task"]] = position
            ended = ends.get(event["run"])
            if ended is not None and ended[0] < position:
                settlements.setdefault((event["task"], event["run"]), (position, event))
    return [_refusal(event, position, retried, foremen, ends, settlements)
            for position, event, retried in sorted(opened.values(), key=lambda entry: entry[0])]


def brief(refusal: Refusal, task: Task, *, run_id: str, report: str, spec: str,
          text: str, role: str) -> str:
    """The foreman run's brief for a refusal, its sections in this order, joined by blank
    lines and ending with a newline:

    1. role, the role text (ROLE's), its trailing newlines removed.
    2. `# The refusal`: one line each, `- Run: <run_id>`, `- Task: <task.id> (spec
       \\`<task.path>\\`)`, `- Branch: \\`<refusal.branch>\\` at \\`<refusal.tip or "-">\\``,
       `- Step: \\`<refusal.step>\\``, `- Next run: <refusal.kind>`, `- Retried unchanged
       since its last run: <yes or no>`, `- Report: write it to \\`<report>\\``, then the
       line `Your checkout is the task's repository at origin/<refusal.branch>, read-only.`
    3. `# The failing step's log`: text, the lines fab.run.refusal_text gives, in a ```text
       fence (its trailing newline removed first).
    4. `# The task spec`: spec, the spec file's whole text (its `+++` header too), verbatim.

    Pure: the caller reads the files and the log."""
    facts = [f"- Run: {run_id}", f"- Task: {task.id} (spec `{task.path}`)",
             f"- Branch: `{refusal.branch}` at `{refusal.tip or '-'}`",
             f"- Step: `{refusal.step}`", f"- Next run: {refusal.kind}",
             "- Retried unchanged since its last run: " + ("yes" if refusal.retried else "no"),
             f"- Report: write it to `{report}`",
             f"Your checkout is the task's repository at origin/{refusal.branch}, read-only."]
    sections = [role.rstrip("\n"), "# The refusal\n\n" + "\n".join(facts),
                "# The failing step's log\n\n```text\n" + text.rstrip("\n") + "\n```",
                "# The task spec\n\n" + spec]
    return "\n\n".join(sections) + ("" if spec.endswith("\n") else "\n")


def start(refusal: Refusal, task: Task, host: Host, events: Iterable[dict], *,
          sh: Runner = run, log_path: Path | None = None) -> str:
    """Start the foreman run of refusal on host (a builder) and return its run id.

    1. The run id fab.run.next_run(fab.foreman.task_field(task.id), events): the question
       foremen's numbering, `<task>/foreman-<n>`.
    2. On this machine: spec, the text of the file at task.path, and role, ROLE's text (an
       OSError from either propagates and starts nothing); text, fab.run.refusal_text(<the record>, task.repo, sh=sh), the
       record holding step, log and tip, and findings when refusal.findings is not empty.
    3. fab.run.launch_detached(host, run_id, task.repo, "origin/<refusal.branch>", sh=sh,
       log_path=log_path, task=fab.foreman.task_field(task.id), kind=KIND,
       branch=refusal.branch, base="origin/main", brief=brief(...), effort=EFFORT,
       refused=refusal.tip, step=refusal.step), the brief's report being
       `<fab.run.remote_home(host)>/runs/<run>/report.md`, where fab.run.launch puts it.
       The branch, not the tip: fab land's tip after its rebase was never pushed.
    fab.run.collect ends the run as any other: its run.ended carries the outcome refusals
    reads, and frees the worktree."""
    run_id = runs.next_run(foreman.task_field(task.id), events)
    spec, role = Path(task.path).read_text(), ROLE.read_text()
    record = {"step": refusal.step, "log": refusal.log, "tip": refusal.tip}
    if refusal.findings:
        record["findings"] = refusal.findings
    text = runs.refusal_text(record, task.repo, sh=sh)
    report = str(Path(runs.remote_home(host)) / "runs" / run_id / "report.md")
    compiled = brief(refusal, task, run_id=run_id, report=report, spec=spec, text=text, role=role)
    return runs.launch_detached(host, run_id, task.repo, f"origin/{refusal.branch}", sh=sh,
                                log_path=log_path, task=foreman.task_field(task.id), kind=KIND,
                                branch=refusal.branch, base="origin/main", brief=compiled,
                                effort=EFFORT, refused=refusal.tip, step=refusal.step)


def remedy(refusal: Refusal, report: str) -> tuple[str, str, str]:
    """What the tick does with a decided refusal's foreman report: (verdict, reason, body),
    verdict one of VERDICTS. Pure.

    The report's first non-blank line, stripped, must be `Done: fix: <line>` or `Done:
    retry: <line>` with a non-empty line (spaces around each colon optional):
    - fix: ("fix", <line>, body), body being <line> then the report's next lines, at most
      SECTION_LINES, each right-stripped, the trailing blank ones dropped, joined by
      newlines;
    - retry, when refusal.retried is false and refusal.step starts with no NEVER_RETRIED
      prefix: ("retry", <line>, "");
    - retry otherwise: ("none", "retry refused: <the branch was retried unchanged once
      since its last run | step <step> is the branch's>", "");
    - anything else: ("none", "no verdict: <the first line, at most 120 characters>", "").
    A report that is not the foreman's form never raises: the repair run starts as without
    a foreman."""
    lines = report.splitlines()
    first = next((i for i, line in enumerate(lines) if line.strip()), None)
    text = lines[first].strip() if first is not None else ""
    match = re.fullmatch(r"Done\s*:\s*(fix|retry)\s*:\s*(.+)", text)
    if match is None or not match[2].strip():
        return "none", "no verdict: " + text[:120], ""
    verdict, reason = match[1], match[2].strip()
    if verdict == "fix":
        kept = [reason, *(line.rstrip() for line in lines[first + 1:first + 1 + SECTION_LINES])]
        while not kept[-1]:
            kept.pop()
        return "fix", reason, "\n".join(kept)
    if refusal.retried:
        return "none", "retry refused: the branch was retried unchanged once since its last run", ""
    if refusal.step.startswith(NEVER_RETRIED):
        return "none", f"retry refused: step {refusal.step} is the branch's", ""
    return "retry", reason, ""


def section(refusal: Refusal, *, day: str, run_id: str, body: str) -> str:
    """The section the spec gains and the next run's brief quotes, ending with a newline:
    `## Repair (<day>, step <refusal.step>, foreman <run_id>)` (`## Rebase` when
    refusal.kind is rebase), a blank line, then body. Pure."""
    title = "Rebase" if refusal.kind == "rebase" else "Repair"
    heading = f"## {title} ({day}, step {refusal.step}, foreman {run_id})"
    return heading + "\n\n" + body.rstrip("\n") + "\n"


def with_section(spec: str, text: str, *, run_id: str) -> str:
    """spec with text, a section as section gives it, appended, ending with a newline.

    A spec that already holds a line starting `## Repair (` or `## Rebase (` and ending
    ` foreman <run_id>)` is returned unchanged: the section was recorded before. Otherwise
    the spec's trailing newlines are stripped and one blank line and text follow. Pure."""
    if any(line.startswith(("## Repair (", "## Rebase ("))
           and line.endswith(f" foreman {run_id})") for line in spec.splitlines()):
        return spec
    return spec.rstrip("\n") + "\n\n" + text.rstrip("\n") + "\n"


def commit(refusal: Refusal, task: Task, text: str, checkout: Path, *, run_id: str,
           sh: Runner = run) -> str | None:
    """Record text, the section of the foreman run run_id, in the task's spec and return the
    branch to land, or None when origin/main already records it.

    fab.spec_edit.commit(task, checkout, <with_section of the spec, text, run_id>,
    branch="repairs/<run_id>", message="Write <task.id>'s <refusal.kind> from its refusal
    at <refusal.step>", worktree=FAB_HOME/runs/<run_id>/wt, sh=sh)."""
    if task.repo == "fabrig":
        relative = Path(task.path).resolve().relative_to(checkout.resolve())
        result = sh(["git", "show", f"refs/remotes/origin/repairs/{run_id}:{relative.as_posix()}"],
                    cwd=str(checkout))
        spec = result.out
        if result.ok and with_section(spec, text, run_id=run_id) == spec:
            return f"repairs/{run_id}"
    return spec_edit.commit(
        task, checkout, lambda spec: with_section(spec, text, run_id=run_id),
        branch=f"repairs/{run_id}",
        message=f"Write {task.id}'s {refusal.kind} from its refusal at {refusal.step}",
        worktree=log.home() / "runs" / run_id / "wt", sh=sh)


def _refusal(event: dict, position: int, retried: bool, foremen: dict, ends: dict,
             settlements: dict) -> Refusal:
    """Resolve one open refusal from indexes in log order."""
    task, stamp = event["task"], event["ts"]
    state, since, foreman_id, report, verdict, text = "foreman", stamp, None, "", "", ""
    started = foremen.get(foreman.task_field(task))
    if started is not None and started[0] > position:
        foreman_id, state, since = started[1]["run"], "deciding", started[1]["ts"]
        ended = ends.get(foreman_id)
        if ended is not None and ended[0] > started[0]:
            last = ended[1]
            state = "decided" if last["outcome"] == "done" else "fallback"
            since, report = last["ts"], last.get("report", "")
            settled = settlements.get((task, foreman_id))
            if state == "decided" and settled is not None and settled[0] > ended[0]:
                state, since = "settled", settled[1]["ts"]
                verdict, text = settled[1]["verdict"], settled[1].get("section", "")
    return Refusal(task, event["branch"], event.get("tip", ""), event["step"],
                   event.get("log", ""), event.get("findings", ""), stamp,
                   "rebase" if event["step"] in REBASE_STEPS else "repair", state, since,
                   retried, foreman_id, report, verdict, text)
