"""The designer's calls: the cut, shared contracts, a probe's decision, retiring a plan
(docs/design/fab.md, 13.3).

Each is a Claude call like any other (fab.calls.start): a fresh session on a brief compiled
here, writing files on its own branch, which a Codex review run checks before the tick lands
it (13.1). The cut writes a new plan. A contract call designs a part the plan marks as a
shared contract, as a skeleton. A decision turns a probe's report into a design section.
Retire brings a finished plan's status files current and marks the plan retired.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from fab import atomic, calls, log, state
from fab import run as runs
from fab.plan import Plan, Task, load_plan, load_tasks
from fab.sh import Failed, Runner, run

ROLES = ("cut", "contract", "decision", "retire")  # the designer's call roles, in fab.calls.ROLES
DESIGNS = "docs/design"  # a repository's designs; its draft/ holds the user's drafts
PLANS = "docs/plan"  # a repository's plans: <PLANS>/<draft>/plan.toml


def subject(draft: str, role: str, part: str | None = None) -> str:
    """The subject a designer's call logs and parks under (docs/design/fab.md, 12 and 13.1):
    cut `<draft>/cut`, retire `<draft>/retire`, contract `<draft>/<part>` (as a skeleton
    call's, so either one designs the part), decision `<draft>/<part>/decision`. ValueError
    for a role not in ROLES, a part missing for contract or decision, or a part given for
    cut or retire."""
    if role not in ROLES:
        raise ValueError(f"unknown designer role {role!r}")
    if role in ("contract", "decision"):
        if not part:
            raise ValueError(f"{role} requires a part")
        return f"{draft}/{part}" + ("/decision" if role == "decision" else "")
    if part is not None:
        raise ValueError(f"{role} takes no part")
    return f"{draft}/{role}"


def uncut(draft: str, repo: str, sources: Sequence[str] = ()) -> Plan:
    """The stand-in for a plan whose plan.toml does not exist yet: Plan(draft, repo,
    tuple(sources), 1.0, 2.0, {}, ()), no parts, slices or questions, not retired. The cut's
    brief reads its sources through fab.calls.drafts_text; the tick of a plan directory
    being cut runs on it (fab.dispatch.tick)."""
    return Plan(draft, repo, tuple(sources), 1.0, 2.0, {}, ())


def repository(checkout: Path, *, sh: Runner = run) -> str:
    """The name of checkout's repository: the key of fab.run.REMOTES whose URL equals the
    output of `git remote get-url origin` run in checkout (check=True, stripped). ValueError
    naming the URL when no key matches; fab.sh.Failed when git fails."""
    url = sh(["git", "remote", "get-url", "origin"], cwd=str(checkout), check=True).out.strip()
    for name, remote in runs.REMOTES.items():
        if remote == url:
            return name
    raise ValueError(f"unknown repository URL {url!r}")


def designs(root: Path) -> list[str]:
    """The repository's designs: every `*.md` directly in root/DESIGNS, except README.md and
    the status files (`*.status.md`), as repository-relative POSIX paths, sorted. The drafts
    under DESIGNS/draft/ are not designs. Empty when the directory does not exist."""
    return sorted(path.relative_to(root).as_posix() for path in (root / DESIGNS).glob("*.md")
                  if path.is_file() and path.name != "README.md" and not path.name.endswith(".status.md"))


def status_path(design: str) -> str:
    """The status file beside a design: `docs/design/x.md` gives `docs/design/x.status.md`.
    ValueError for a path that does not end in `.md` or is already a status file."""
    if not design.endswith(".md") or design.endswith(".status.md"):
        raise ValueError(f"not a design path: {design!r}")
    return design[:-3] + ".status.md"


def design_index(root: Path) -> str:
    """The cut's map of the repository's designs, one line per entry of designs(root):
    `- \\`<path>\\` — <title> (<n> lines; status \\`<status path>\\`)`, the title being the
    first line starting with `# ` without that prefix (`(untitled)` when none), n the
    design's line count, and `no status file` in place of `status ...` when status_path's
    file does not exist. `(none)` when there are no designs. The call reads the designs it
    needs itself: all of them would pass fab.calls.BRIEF_LIMIT."""
    entries = []
    for design in designs(root):
        lines = (root / design).read_text(encoding="utf-8").splitlines()
        title = next((line[2:] for line in lines if line.startswith("# ")), "(untitled)")
        status = status_path(design)
        note = f"status `{status}`" if (root / status).is_file() else "no status file"
        entries.append(f"- `{design}` — {title} ({len(lines)} lines; {note})")
    return "\n".join(entries) or "(none)"


def changed_designs(checkout: Path, draft: str, *, rev: str = "origin/main",
                    sh: Runner = run) -> list[str]:
    """The designs changed since the plan started: those a commit after the plan's start
    changed, or whose status file it changed, up to rev, as design paths, sorted.

    In checkout, with check=True: the start is the oldest line of `git log --format=%H
    --diff-filter=A <rev> -- <PLANS>/<draft>/plan.toml`; ValueError naming the path when
    there is none. The changed paths are `git diff --name-only --no-renames <start>^ <rev>
    -- <DESIGNS>/` (so the cut's own design changes count), or `git ls-tree -r --name-only
    <rev> -- <DESIGNS>/` when the start has no parent (`git rev-parse --verify -q
    <start>^`, check=False, fails). A path counts when it is directly in DESIGNS and is a
    design (designs' rule) or a design's status file (then its design is returned, whether
    or not that design still exists at rev)."""
    plan_path = f"{PLANS}/{draft}/plan.toml"

    def git(*args, check=True):
        return sh(["git", *args], cwd=str(checkout), check=check)

    commits = git("log", "--format=%H", "--diff-filter=A", rev, "--", plan_path).out.splitlines()
    if not commits:
        raise ValueError(f"no commit added {plan_path}")
    start = commits[-1]
    if git("rev-parse", "--verify", "-q", f"{start}^", check=False).ok:
        paths = git("diff", "--name-only", "--no-renames", f"{start}^", rev, "--", f"{DESIGNS}/").out
    else:
        paths = git("ls-tree", "-r", "--name-only", rev, "--", f"{DESIGNS}/").out
    changed = set()
    for name in paths.splitlines():
        path = Path(name)
        if path.parent.as_posix() != DESIGNS or not name.endswith(".md"):
            continue
        design = name.removesuffix(".status.md") + ".md" if name.endswith(".status.md") else name
        if Path(design).name != "README.md":
            changed.add(design)
    return sorted(changed)


def retire_due(plan: Plan, tasks: Mapping[str, Task], events: Sequence[dict]) -> bool:
    """Whether the plan's retire call should start, from the plan and the log alone:
    the plan is not retired, has at least one part, every part's status is done
    (fab.state.part_statuses over fab.state.fold(tasks, events)), and no call.started with
    role retire and subject `<draft>/retire` has a call.ended with outcome done. A retire
    call in flight, a parked subject or an open chain is fab.dispatch.call_actions' to
    check, as for every call. Pure."""
    if plan.retired or not plan.parts:
        return False
    statuses = {key: view.status for key, view in state.fold(tasks, events).items()}
    if any(status != "done" for status in state.part_statuses(plan, tasks, statuses).values()):
        return False
    completed = {event["call"] for event in events
                 if event.get("ev") == "call.ended" and event.get("outcome") == "done"}
    return not any(event.get("ev") == "call.started" and event.get("role") == "retire"
                   and event.get("subject") == subject(plan.draft, "retire")
                   and event.get("call") in completed for event in events)


def enlist(plan_dir: Path) -> bool:
    """Start ticking a plan (docs/design/fab.md, 13.4): add plan_dir, resolved, as one line
    of FAB_HOME/plans, unless a line already names it; return whether it was added. The
    file is created when missing and rewritten whole through fab.atomic.write, its lines
    kept in order with the new one last."""
    path = log.home() / "plans"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        lines = []
    resolved = str(plan_dir.resolve())
    if any(str(Path(line).resolve()) == resolved for line in lines):
        return False
    atomic.write(path, "\n".join([*lines, resolved]) + "\n")
    return True


def cut_brief(plan: Plan, root: Path, *, call_id: str, branch: str, report: str) -> str:
    """The cut's brief, plan being uncut(draft, repo, sources), through fab.calls' section
    builder and facts (fab.calls._brief, _facts), sections in this order:

    1. `Role`: fab.calls.ROLES["cut"]'s text.
    2. `Call facts`.
    3. `The draft`: `- Draft: <draft>`, `- Repository: <repo>`, `- Plan: write
       \\`<PLANS>/<draft>/plan.toml\\``, `- Sources: \\`<source>\\`, ...` (comma-separated).
    4. `The user's drafts`: fab.calls.drafts_text(plan, root).
    5. `Designs`: design_index(root).
    6. `Plans`: one line `- \\`<path>\\`` per `<PLANS>/*/plan.toml` under root, sorted;
       `(none)` when there is none. Their format is the cut's to follow.
    7. `Inventory`: fab.calls.render_inventory(fab.calls.inventory(root)), or `(none)`
       when it is empty (a repository without fab/).

    ValueError past fab.calls.BRIEF_LIMIT, as every call's brief."""
    plans = sorted(path.relative_to(root).as_posix() for path in (root / PLANS).glob("*/plan.toml")
                   if path.is_file())
    role_text = calls.ROLES["cut"].read_text(encoding="utf-8")
    if plan.repo == "fabrig":
        role_text += "\n\n" + calls.ROLES["cut"].with_name("cut-fabrig.md").read_text(encoding="utf-8")
    return calls._brief([
        ("Role", role_text),
        ("Call facts", calls._facts(call_id, branch, report)),
        ("The draft", f"- Draft: {plan.draft}\n- Repository: {plan.repo}\n"
         f"- Plan: write `{PLANS}/{plan.draft}/plan.toml`\n"
         f"- Sources: {', '.join(f'`{source}`' for source in plan.sources)}"),
        ("The user's drafts", calls.drafts_text(plan, root)),
        ("Designs", design_index(root)),
        ("Plans", "\n".join(f"- `{path}`" for path in plans) or "(none)"),
        ("Inventory", calls.render_inventory(calls.inventory(root)) or "(none)"),
    ])


def decision_brief(plan: Plan, part_id: str, tasks: dict[str, Task], statuses: dict[str, str],
                   root: Path, run_id: str, *, call_id: str, branch: str, report: str) -> str:
    """The decision's brief: a probe part's report in, a design section out. Sections, through
    fab.calls._brief, in this order:

    1. `Role`: fab.calls.ROLES["decision"]'s text.
    2. `Call facts`.
    3. `Plan parts and slices`: fab.calls._parts_table(plan, tasks, statuses), then
       `Plan: \\`<PLANS>/<draft>/plan.toml\\``.
    4. `The probe`: `- Part: <id>`, `- Title: <title>`, `- Design: <citation>`,
       `- Run: <run_id>`, `- Report: \\`<FAB_HOME/runs/<run_id>/report.md>\\``.
    5. `The probe's report`: that file's text.
    6. `Its readers`: one line per part whose needs name the probe, in plan order,
       `- <id> — <title> (design: <citation>; <part status>)`, the status from
       fab.state.part_statuses; `(none)` when no part needs it.
    7. `The user's drafts`: fab.calls.drafts_text(plan, root).
    8. `Cited design`: fab.calls.design_text(root, <the probe's design>).

    ValueError when part_id is not a part of the plan, its mode is not probe, or the report
    cannot be read (naming its path); past fab.calls.BRIEF_LIMIT as every call's brief."""
    if part_id not in plan.parts:
        raise ValueError(f"unknown part {part_id!r}")
    part = plan.parts[part_id]
    if part.mode != "probe":
        raise ValueError(f"part {part_id!r} is not a probe")
    report_path = log.home() / "runs" / run_id / "report.md"
    try:
        probe_report = report_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise ValueError(f"cannot read {report_path}: {error}") from error
    parts = state.part_statuses(plan, tasks, statuses)
    readers = [f"- {item.id} — {item.title} (design: {item.design}; {parts[item.id]})"
               for item in plan.parts.values() if part_id in item.needs]
    return calls._brief([
        ("Role", calls.ROLES["decision"].read_text(encoding="utf-8")),
        ("Call facts", calls._facts(call_id, branch, report)),
        ("Plan parts and slices", calls._parts_table(plan, tasks, statuses) +
         f"\n\nPlan: `{PLANS}/{plan.draft}/plan.toml`"),
        ("The probe", f"- Part: {part.id}\n- Title: {part.title}\n- Design: {part.design}\n"
         f"- Run: {run_id}\n- Report: `{report_path}`"),
        ("The probe's report", probe_report),
        ("Its readers", "\n".join(readers) or "(none)"),
        ("The user's drafts", calls.drafts_text(plan, root)),
        ("Cited design", calls.design_text(root, part.design)),
    ])


def retire_brief(plan: Plan, tasks: dict[str, Task], statuses: dict[str, str], root: Path,
                 changed: Sequence[str], *, call_id: str, branch: str, report: str) -> str:
    """Retire's brief, changed being changed_designs(root, plan.draft). Sections, through
    fab.calls._brief, in this order:

    1. `Role`: fab.calls.ROLES["retire"]'s text.
    2. `Call facts`.
    3. `Plan parts and slices`: fab.calls._parts_table(plan, tasks, statuses), then
       `Plan: \\`<PLANS>/<draft>/plan.toml\\``.
    4. `The user's drafts`: fab.calls.drafts_text(plan, root).
    5. `Designs changed since the plan started`: per path of changed, in order, `## <path>`
       and the design's text (`(removed)` when it does not exist under root), then
       `## <status path>` and the status file's text (`(no status file)` when missing);
       `(none)` when changed is empty.
    6. `Inventory`: fab.calls.render_inventory(fab.calls.inventory(root)).

    ValueError past fab.calls.BRIEF_LIMIT: the designs are quoted whole, and a plan that
    changed more than the limit holds is retired by hand."""
    designs_text = []
    for design in changed:
        path = root / design
        text = path.read_text(encoding="utf-8") if path.exists() else "(removed)"
        status = status_path(design)
        path = root / status
        note = path.read_text(encoding="utf-8") if path.exists() else "(no status file)"
        designs_text.append(f"## {design}\n\n{text}\n\n## {status}\n\n{note}")
    return calls._brief([
        ("Role", calls.ROLES["retire"].read_text(encoding="utf-8")),
        ("Call facts", calls._facts(call_id, branch, report)),
        ("Plan parts and slices", calls._parts_table(plan, tasks, statuses) +
         f"\n\nPlan: `{PLANS}/{plan.draft}/plan.toml`"),
        ("The user's drafts", calls.drafts_text(plan, root)),
        ("Designs changed since the plan started", "\n\n".join(designs_text) or "(none)"),
        ("Inventory", calls.render_inventory(calls.inventory(root))),
    ])


def main(argv: list[str]) -> int:
    """The designer's calls as `fab call ROLE ...` (fab.calls.main hands argv over when its
    first item is in ROLES), each with `--brief-only` (print the brief, run nothing):

    - `fab call cut --plan PLAN_DIR --source PATH [--source PATH ...]`: the draft is
      PLAN_DIR's name; the checkout root is `git rev-parse --show-toplevel` in the nearest
      existing directory at or above PLAN_DIR; ValueError when PLAN_DIR is not
      root/PLANS/<draft>, PLAN_DIR/plan.toml exists, or a source is not a relative path
      naming a file under the root. The plan is
      uncut(draft, repository(root), sources); without --brief-only, enlist(PLAN_DIR)
      before the call.
    - `fab call contract PART --plan PLAN_DIR`: fab.calls.skeleton_brief with role
      contract; ValueError for an unknown part or one the plan does not mark contract.
    - `fab call decision PART --plan PLAN_DIR --run RUN`: decision_brief.
    - `fab call retire --plan PLAN_DIR`: retire_brief with changed_designs(root, draft);
      ValueError when the plan is already retired.

    The others load the plan and its tasks as fab.calls.main does (no problems check),
    statuses from fab.state.fold over fab.log.read(). Each runs fab.calls.start(role,
    subject(draft, role, part), root, brief), prints `<outcome> <branch>` and exits 0 when
    the outcome is done, 1 otherwise; an OSError, ValueError or fab.sh.Failed prints
    `fab call: <error>` on stderr and exits 1, starting nothing."""
    args = _arguments(argv)
    try:
        plan, tasks, root = _prepare(args)
        statuses = {key: view.status for key, view in state.fold(tasks, log.read()).items()}
        facts = dict(call_id="(assigned at start)", branch="(assigned at start)", report="(assigned at start)")
        text = _compile(args, plan, tasks, statuses, root, facts)
        if args.brief_only:
            print(text)
            return 0
        if args.role == "cut":
            enlist(args.plan)
        repo = log.home() / "repos/fabrig" if plan.repo == "fabrig" else root
        result = calls.start(args.role, subject(plan.draft, args.role, getattr(args, "part", None)),
                             repo, text, sh=run)
        print(f"{result['outcome']} {result['branch']}")
        return 0 if result["outcome"] == "done" else 1
    except (OSError, ValueError, Failed) as error:
        print(f"fab call: {error}", file=sys.stderr)
        return 1


def _arguments(argv):
    """Parse the designer roles without adding them to the other calls' parser."""
    parser = argparse.ArgumentParser(prog="fab call")
    commands = parser.add_subparsers(dest="role", required=True)
    for role in ROLES:
        command = commands.add_parser(role)
        command.add_argument("--plan", type=Path, required=True)
        command.add_argument("--brief-only", action="store_true")
        if role in ("contract", "decision"):
            command.add_argument("part")
        if role == "decision":
            command.add_argument("--run", required=True)
        if role == "cut":
            command.add_argument("--source", action="append", required=True)
    return parser.parse_args(argv)


def _prepare(args):
    """Find the checkout and read a plan, or validate a cut's destination and sources."""
    directory = args.plan.resolve()
    ancestor = directory
    while not ancestor.exists():
        ancestor = ancestor.parent
    root = Path(run(["git", "rev-parse", "--show-toplevel"], cwd=str(ancestor), check=True).out.strip()).resolve()
    if args.role != "cut":
        plan = load_plan(directory / "plan.toml")
        return plan, load_tasks(directory / "tasks", plan.draft, plan.repo), root
    if directory != root / PLANS / directory.name:
        raise ValueError(f"PLAN_DIR must be {root / PLANS}/<draft>: {directory}")
    if (directory / "plan.toml").exists():
        raise ValueError(f"plan.toml already exists: {directory / 'plan.toml'}")
    for source in args.source:
        path = root / source
        if Path(source).is_absolute() or not path.resolve().is_relative_to(root) or not path.is_file():
            raise ValueError(f"source must name a relative file under {root}: {source}")
    return uncut(directory.name, repository(root, sh=run), args.source), {}, root


def _compile(args, plan, tasks, statuses, root, facts):
    """Build a brief only after the role's preconditions hold."""
    if args.role == "cut":
        return cut_brief(plan, root, **facts)
    if args.role == "contract":
        if args.part not in plan.parts:
            raise ValueError(f"unknown part {args.part!r}")
        if not plan.parts[args.part].contract:
            raise ValueError(f"part {args.part!r} is not a contract")
        return calls.skeleton_brief(plan, args.part, tasks, statuses, root, role="contract", **facts)
    if args.role == "decision":
        return decision_brief(plan, args.part, tasks, statuses, root, args.run, **facts)
    if plan.retired:
        raise ValueError(f"plan {plan.draft!r} is already retired")
    return retire_brief(plan, tasks, statuses, root, changed_designs(root, plan.draft, sh=run), **facts)
