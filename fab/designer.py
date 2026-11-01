"""The designer's calls: the cut, shared contracts, a probe's decision, retiring a plan
(docs/design/fab-calls.md, 3).

Each is a Claude call like any other (fab.calls.start): a fresh session on a brief compiled
here, writing files on its own branch, which a Codex review run checks before the tick lands
it (fab-calls.md 2). The cut writes a new plan. A contract call designs a part the plan marks as a
shared contract, as a skeleton. A decision turns a probe's report into a design section.
Retire brings a finished plan's status files current and marks the plan retired.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from contextlib import redirect_stdout
from dataclasses import replace
from pathlib import Path

from fab import atomic, calls, integration, log, state
from fab import run as runs
from fab.plan import Plan, Task, load_plan, load_tasks, parse_options
from fab.sh import Failed, Runner, run

ROLES = ("cut", "contract", "decision", "retire")  # the designer's call roles, in fab.calls.ROLES
DESIGNS = "docs/design"  # a repository's designs; its draft/ holds the user's drafts
PLANS = "docs/plan"  # plans live under this suffix, with any repository-relative prefix
BESIDE_LINES = 200  # lines of other drafts in a cut brief, before the omitted count (fab-integration.md 4)


def subject(draft: str, role: str, part: str | None = None) -> str:
    """The subject a designer's call logs and parks under (docs/design/fab-gates.md, 2; fab-calls.md, 2):
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


def uncut(draft: str, repo: str, sources: Sequence[str] = (),
          options: Mapping[str, object] | None = None) -> Plan:
    """The stand-in for a plan whose plan.toml does not exist yet: Plan(draft, repo,
    tuple(sources), 1.0, 2.0, {}, ()), no parts, slices or questions, not retired. The cut's
    brief reads its sources through fab.calls.drafts_text; the tick of a plan directory
    being cut runs on it (fab.dispatch.tick). It inherits Plan's integration and ready defaults, without reviews and
    with every part direct (fab-integration.md 3); parsed options replace them."""
    return replace(Plan(draft, repo, tuple(sources), 1.0, 2.0, {}, ()), **(options or {}))


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


def plan_start(checkout: Path, draft: str, *, rev: str = "origin/main",
               sh: Runner = run, plan_path: str | None = None) -> str:
    """Return the oldest commit adding the plan's plan.toml (docs/design/fab-calls.md, 3).

    Read `git log --format=%H --diff-filter=A <rev> -- <plan_path>/plan.toml`,
    with check=True. plan_path defaults to <PLANS>/<draft>; ValueError naming the
    plan file when no commit added it. fab.sh.Failed when git fails.
    """
    plan_path = plan_path or f"{PLANS}/{draft}"
    plan_file = f"{plan_path}/plan.toml"
    commits = sh(["git", "log", "--format=%H", "--diff-filter=A", rev, "--", plan_file],
                 cwd=str(checkout), check=True).out.splitlines()
    if not commits:
        raise ValueError(f"no commit added {plan_file}")
    return commits[-1]


def design_diff(checkout: Path, start: str, design: str, *, rev: str = "origin/main",
                sh: Runner = run) -> str:
    """Return a design and its status file's diff since start (docs/design/fab-calls.md, 3).

    Run `git diff <start>^ <rev> -- <design> <status>` with check=True. If start
    has no parent, diff against the empty tree, whose id comes from
    `git hash-object -t tree --stdin` with empty input, for either hash format.
    fab.sh.Failed when git fails; the parent probe uses check=False.
    """
    base = f"{start}^"
    parent = sh(["git", "rev-parse", "--verify", "-q", base], cwd=str(checkout), check=False)
    if not parent.ok:
        base = sh(["git", "hash-object", "-t", "tree", "--stdin"], cwd=str(checkout),
                  input="", check=True).out.strip()
    return sh(["git", "diff", base, rev, "--", design, status_path(design)],
              cwd=str(checkout), check=True).out


def changed_designs(checkout: Path, draft: str, *, rev: str = "origin/main",
                    sh: Runner = run, plan_path: str | None = None) -> list[str]:
    """The designs changed since the plan started: those a commit after the plan's start
    changed, or whose status file it changed, up to rev, as design paths, sorted.

    In checkout, with check=True: the start is the oldest line of `git log --format=%H
    --diff-filter=A <rev> -- <PLANS>/<draft>/plan.toml`; ValueError naming the path when
    there is none. The changed paths are `git diff --name-only --no-renames <start>^ <rev>
    -- <DESIGNS>/` (so the cut's own design changes count), or `git ls-tree -r --name-only
    <rev> -- <DESIGNS>/` when the start has no parent (`git rev-parse --verify -q
    <start>^`, check=False, fails). A path counts when it is directly in DESIGNS and is a
    design (designs' rule) or a design's status file (then its design is returned, whether
    or not that design still exists at rev). plan_path overrides <PLANS>/<draft> with a
    repository-relative plan directory."""
    start = plan_start(checkout, draft, rev=rev, sh=sh, plan_path=plan_path)

    def git(*args, check=True):
        return sh(["git", *args], cwd=str(checkout), check=check)

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
    check, as for every call. Integration plans also wait for their trunk to land on main. Pure."""
    if plan.retired or not plan.parts:
        return False
    if plan.landing == "integration" and not any(
            event.get("ev") == "branch.landed" and not event.get("into")
            and event.get("task") == f"{plan.draft}/integration" for event in events):
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
    """Start ticking a plan (docs/design/fab-tick.md, 5): add plan_dir, resolved, as one line
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


def drafts_beside(plan: Plan, plans: Sequence[tuple[Plan, Mapping[str, Task]]],
                  events: Sequence[dict]) -> str:
    """Render the cut's other drafts in loaded plans' order (docs/design/fab-integration.md, 4).

    Keep the same repository, excluding this draft, retired plans and landed integration
    trunks. A latest cut call without an end marks its plan cut in flight and lists the
    tasks already loaded. Otherwise queue tasks exclude landed ones. Integration tasks
    include landed ones marked merged. Sort tasks by id, omitting files=("**",) repairs.
    Return at most BESIDE_LINES lines followed by an omitted-line count, or an empty
    string when no plans remain. Pure; the caller loads plans and reads the log.
    """
    cuts = {event.get("subject"): event for event in events
            if event.get("ev") == "call.started" and event.get("role") == "cut"}
    ended = {event.get("call") for event in events if event.get("ev") == "call.ended"}
    lines = []
    for other, tasks in plans:
        if other.repo != plan.repo or other.draft == plan.draft or other.retired:
            continue
        if other.landing == "integration" and integration.trunk_landed(other, events):
            continue
        cut = cuts.get(subject(other.draft, "cut"))
        in_flight = cut is not None and cut.get("call") not in ended
        label = "cut in flight" if in_flight else other.landing
        lines.append(f"- {other.draft} ({label})")
        views = state.fold(tasks, events)
        for identifier, task in sorted(tasks.items()):
            if task.files == ("**",):
                continue
            merged = views[identifier].status == "landed"
            if other.landing == "queue" and merged and not in_flight:
                continue
            mark = " (merged)" if merged and other.landing == "integration" else ""
            files = ", ".join(f"`{name}`" for name in task.files)
            lines.append(f"  - `{identifier}`{mark}: {files}")
    if len(lines) > BESIDE_LINES:
        return "\n".join([*lines[:BESIDE_LINES], f"({len(lines) - BESIDE_LINES} more lines)"])
    return "\n".join(lines)


def _cut_role_options(plan: Plan, parsed: Mapping[str, object],
                      plan_path: str) -> tuple[bool, str, list[tuple[str, str]]]:
    """Return the effective cut role and option sections (docs/design/fab-calls.md, 3)."""
    direct = parsed.get("direct", plan.direct)
    run_role = direct and parsed.get("landing", plan.landing) == "integration"
    if run_role:
        role_text = calls.ROLES["cut"].with_name("cut-run.md").read_text(encoding="utf-8")
    else:
        role_text = calls.ROLES["cut"].read_text(encoding="utf-8")
        if plan.repo == "fabrig":
            role_text += "\n\n" + calls.ROLES["cut"].with_name("cut-fabrig.md").read_text(encoding="utf-8")
    option_sections = []
    text = ""
    if parsed:
        lines = "\n".join(f"{key} = {json.dumps(value)}" for key, value in parsed.items())
        text = ("Write these keys at the top of plan.toml, before the first table, verbatim:\n\n"
                f"```toml\n{lines}\n```")
    if direct and not run_role:
        role_text += "\n\n" + calls.ROLES["cut"].with_name("cut-direct.md").read_text(encoding="utf-8")
        if text:
            text += "\n\n"
        text += ("Every part is `mode = \"direct\"`, so the cut writes every task spec itself. "
                 f"Notes that several tasks share go once in `{plan_path}/notes/<name>.md`, "
                 "cited from each spec by repository path; the implementers read them in their checkout. "
                 "A task's `needs` name the tasks whose merged code it builds on.")
    if text:
        option_sections.append(("Plan options", text))
    return run_role, role_text, option_sections


def cut_brief(plan: Plan, root: Path, *, call_id: str, branch: str, report: str,
              plan_path: str | None = None, options: Sequence[str] = (),
              beside: str | None = None) -> str:
    """The cut's brief, plan being uncut(draft, repo, sources), through fab.calls' section
    builder and facts (fab.calls._brief, _facts), sections in this order:

    1. `Role`: cut-run.md alone for a direct integration plan; otherwise
       fab.calls.ROLES["cut"]'s text and the repository and direct-mode notes that apply.
    2. `Call facts`.
    3. `The draft`: `- Draft: <draft>`, `- Repository: <repo>`, `- Plan: write
       \\`<PLANS>/<draft>/plan.toml\\``, `- Sources: \\`<source>\\`, ...` (comma-separated).
    4. `The user's drafts`: fab.calls.drafts_text(plan, root).
    5. `Drafts beside this one`: beside, or `(none)` when empty; omitted for None (fab-integration.md 4).
    6. `Designs`: design_index(root).
    7. `Plans`: one line `- \\`<path>\\`` per `**/<PLANS>/*/plan.toml` under root, sorted;
       `(none)` when there is none. Their format is the cut's to follow.
    8. `Inventory`: fab.calls.render_inventory(fab.calls.inventory(root)), or `(none)`
       when it is empty (a repository without fab/).
    When cut-run.md is the role: section 4 is named `Sources`, a fabrig plan's brief then
    quotes fab/roles/fabrig-run.md as `What each implementer is told`, and sections 6 to 8
    are left out (cut-run.md holds the formats).

    When options are given, insert `Plan options` after `The draft`, with parsed
    KEY = VALUE lines to write verbatim at the top of plan.toml. With direct=true
    (the plan's default unless overridden), except when cut-run.md supplies the role,
    include that section's instructions for direct parts, task specs written by the cut,
    shared notes under the plan's notes/ cited by repository path, and needs naming tasks
    whose merged code is needed.
    plan_path overrides <PLANS>/<draft> with a repository-relative plan directory.
    ValueError past fab.calls.BRIEF_LIMIT, as every call's brief."""
    plan_path = plan_path or f"{PLANS}/{plan.draft}"
    plans = sorted(path.relative_to(root).as_posix() for path in root.glob(f"**/{PLANS}/*/plan.toml")
                   if path.is_file())
    parsed = parse_options(options)
    run_role, role_text, option_sections = _cut_role_options(plan, parsed, plan_path)
    return calls._brief([
        ("Role", role_text),
        ("Call facts", calls._facts(call_id, branch, report)),
        ("The draft", f"- Draft: {plan.draft}\n- Repository: {plan.repo}\n"
         f"- Plan: write `{plan_path}/plan.toml`\n"
         f"- Sources: {', '.join(f'`{source}`' for source in plan.sources)}"),
        *option_sections,
        # A run's cut gets its sources under their own name, and reads what each implementer is
        # told, as the run's lead read the implementers' role file; cut-run.md holds the formats.
        ("Sources" if run_role else "The user's drafts", calls.drafts_text(plan, root)),
        *([] if beside is None else [("Drafts beside this one", beside or "(none)")]),
        *([("What each implementer is told",
            runs.ROLE.with_name("fabrig-run.md").read_text(encoding="utf-8"))]
          if run_role and plan.repo == "fabrig" else []),
        *([] if run_role else [
            ("Designs", design_index(root)),
            ("Plans", "\n".join(f"- `{path}`" for path in plans) or "(none)"),
            ("Inventory", calls.render_inventory(calls.inventory(root)) or "(none)"),
        ]),
    ])


def decision_brief(plan: Plan, part_id: str, tasks: dict[str, Task], statuses: dict[str, str],
                   root: Path, run_id: str, *, call_id: str, branch: str, report: str,
                   plan_path: str | None = None) -> str:
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

    plan_path overrides <PLANS>/<draft> with a repository-relative plan directory.
    ValueError when part_id is not a part of the plan, its mode is not probe, or the report
    cannot be read (naming its path); past fab.calls.BRIEF_LIMIT as every call's brief."""
    plan_path = plan_path or f"{PLANS}/{plan.draft}"
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
         f"\n\nPlan: `{plan_path}/plan.toml`"),
        ("The probe", f"- Part: {part.id}\n- Title: {part.title}\n- Design: {part.design}\n"
         f"- Run: {run_id}\n- Report: `{report_path}`"),
        ("The probe's report", probe_report),
        ("Its readers", "\n".join(readers) or "(none)"),
        ("The user's drafts", calls.drafts_text(plan, root)),
        ("Cited design", calls.design_text(root, part.design)),
    ])


def _retire_quote(root: Path, start: str, design: str, rev: str,
                  sh: Runner) -> tuple[str, str]:
    """Read the two quote forms at rev; return the shorter quote and its omission line."""
    status = status_path(design)
    content = sh(["git", "show", f"{rev}:{design}"], cwd=str(root), check=False)
    note = sh(["git", "show", f"{rev}:{status}"], cwd=str(root), check=False)
    difference = design_diff(root, start, design, rev=rev, sh=sh)
    whole = (f"## {design}\n\nText at `{rev}`:\n\n"
             f"{content.out if content.ok else '(removed)'}\n\n## {status}\n\n"
             f"{note.out if note.ok else '(no status file)'}")
    patch = f"## {design}\n\nDiff since the plan started:\n\n```diff\n{difference}```"
    lines = len(content.out.splitlines()) if content.ok else 0
    listed = (f"- {design} ({lines} lines, diff {len(difference.splitlines())} lines): "
              "read it in your worktree")
    return min((patch, whole), key=len), listed


def _retire_designs(quotes: Sequence[tuple[str, str]], budget: int) -> str:
    """Fill the section in order, reserving all list lines and skipping quotes that do not fit."""
    if not quotes:
        return "(none)"
    notice = "Did not fit:\n"
    remaining = budget - len(notice) - 2 - sum(len(line) + 1 for _, line in quotes)
    selected, skipped = [], []
    for quote, line in quotes:
        if len(quote) + 2 <= remaining:
            selected.append(quote)
            remaining -= len(quote) + 2
        else:
            skipped.append(line)
    if skipped:
        selected.append(notice + "\n".join(skipped))
    return "\n\n".join(selected)


def retire_brief(plan: Plan, tasks: dict[str, Task], statuses: dict[str, str], root: Path,
                 changed: Sequence[str], *, call_id: str, branch: str, report: str,
                 plan_path: str | None = None, rev: str = "origin/main", sh: Runner = run) -> str:
    """Retire's brief (docs/design/fab-calls.md, 3); changed is changed_designs' paths.
    Sections, through fab.calls._brief, in this order:

    1. `Role`: fab.calls.ROLES["retire"]'s text.
    2. `Call facts`.
    3. `Plan parts and slices`: fab.calls._parts_table(plan, tasks, statuses), then
       `Plan: \\`<PLANS>/<draft>/plan.toml\\``.
    4. `The user's drafts`: fab.calls.drafts_text(plan, root).
    5. `Designs changed since the plan started`: in path order, each design headed
       `## <path>`, as the shorter of its diff since plan_start and its text plus
       status file at rev. Quotes label the form; diffs use fenced diff blocks.
       Read text with `git show <rev>:<path>` through sh; `(removed)` for an absent
       design and `(no status file)` for absent status. `(none)` when changed is empty.
       Budget: BRIEF_LIMIT less every other section's compiled text, including
       headings and separators, and one list line per changed design, reserved first.
       Skip a quote that does not fit, continuing with later paths; list skipped
       designs after the quotes under `Did not fit:` as `- <path> (<n> lines, diff
       <m> lines): read it in your worktree`, n the design's lines at rev (0 removed).
    6. `Inventory`: fab.calls.render_inventory(fab.calls.inventory(root)).

    plan_path overrides <PLANS>/<draft> with a repository-relative plan directory.
    ValueError past fab.calls.BRIEF_LIMIT when the other sections alone exceed it.
    """
    plan_path = plan_path or f"{PLANS}/{plan.draft}"
    sections = [
        ("Role", calls.ROLES["retire"].read_text(encoding="utf-8")),
        ("Call facts", calls._facts(call_id, branch, report)),
        ("Plan parts and slices", calls._parts_table(plan, tasks, statuses) +
         f"\n\nPlan: `{plan_path}/plan.toml`"),
        ("The user's drafts", calls.drafts_text(plan, root)),
        ("Designs changed since the plan started", ""),
        ("Inventory", calls.render_inventory(calls.inventory(root))),
    ]
    budget = calls.BRIEF_LIMIT - len(calls._brief(sections))
    start = plan_start(root, plan.draft, rev=rev, sh=sh, plan_path=plan_path) if changed else ""
    quotes = [_retire_quote(root, start, design, rev, sh) for design in sorted(changed)]
    sections[4] = (sections[4][0], _retire_designs(quotes, budget))
    return calls._brief(sections)


def main(argv: list[str]) -> int:
    """The designer's calls as `fab call ROLE ...` (fab.calls.main hands argv over when its
    first item is in ROLES), each with `--brief-only` (print the brief, run nothing):

    - `fab call cut --plan PLAN_DIR --source PATH [--source PATH ...] [--set KEY=VALUE ...]`:
      the draft is
      PLAN_DIR's name; the checkout root is `git rev-parse --show-toplevel` in the nearest
      existing directory at or above PLAN_DIR; ValueError when PLAN_DIR is not
      root/<prefix>docs/plan/<draft>, PLAN_DIR/plan.toml exists, or a source is not a
      relative path naming a file under the root. The plan is
      uncut(draft, repository(root), sources, parse_options(entries)); parse options
      before preparing the checkout. Ready cuts load the listed plans without fetching
      for `Drafts beside this one` (fab-integration.md 4); loader messages go to stderr. An integration
      cut requires root's upstream to be origin/<draft>/integration. Without --brief-only,
      enlist(PLAN_DIR) before the call;
      raw option entries are logged in call.started's options.
    - `fab call contract PART --plan PLAN_DIR`: fab.calls.skeleton_brief with role
      contract; ValueError for an unknown part or one the plan does not mark contract.
    - `fab call decision PART --plan PLAN_DIR --run RUN`: decision_brief.
    - `fab call retire --plan PLAN_DIR`: retire_brief with changed_designs(root, draft);
      ValueError when the plan is already retired.

    The others load the plan and its tasks as fab.calls.main does (no problems check),
    statuses from fab.state.fold over fab.log.read(). Each runs fab.calls.start(role,
    subject(draft, role, part), root, brief, base=plan.trunk), prints `<outcome> <branch>` and exits 0 when
    the outcome is done, 1 otherwise; an OSError, ValueError or fab.sh.Failed prints
    `fab call: <error>` on stderr and exits 1, starting nothing."""
    args = _arguments(argv)
    try:
        options = parse_options(args.set) if args.role == "cut" else {}
        plan, tasks, root, plan_path = _prepare(args, options)
        events = log.read()
        statuses = {key: view.status for key, view in state.fold(tasks, events).items()}
        facts = dict(call_id="(assigned at start)", branch="(assigned at start)", report="(assigned at start)")
        text = _compile(args, plan, tasks, statuses, root, facts, plan_path, events)
        if args.brief_only:
            print(text)
            return 0
        if args.role == "cut":
            enlist(args.plan)
        repo = log.home() / "repos/fabrig" if plan.repo == "fabrig" else root
        fields = {"options": args.set} if args.role == "cut" and args.set else None
        result = calls.start(args.role, subject(plan.draft, args.role, getattr(args, "part", None)),
                             repo, text, sh=run, base=plan.trunk, fields=fields)
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
            command.add_argument("--set", action="append", default=[], metavar="KEY=VALUE")
    return parser.parse_args(argv)


def _prepare(args, options):
    """Find the checkout and read a plan, or validate a cut's destination and sources."""
    directory = args.plan.resolve()
    ancestor = directory
    while not ancestor.exists():
        ancestor = ancestor.parent
    root = Path(run(["git", "rev-parse", "--show-toplevel"], cwd=str(ancestor), check=True).out.strip()).resolve()
    plan_path = directory.relative_to(root)
    if args.role != "cut":
        plan = load_plan(directory / "plan.toml")
        return plan, load_tasks(directory / "tasks", plan.draft, plan.repo), root, plan_path.as_posix()
    if len(plan_path.parts) < 3 or plan_path.parts[-3:-1] != ("docs", "plan"):
        raise ValueError(f"PLAN_DIR must be {root}/<prefix>docs/plan/<draft>: {directory}")
    if (directory / "plan.toml").exists():
        raise ValueError(f"plan.toml already exists: {directory / 'plan.toml'}")
    for source in args.source:
        path = root / source
        if Path(source).is_absolute() or not path.resolve().is_relative_to(root) or not path.is_file():
            raise ValueError(f"source must name a relative file under {root}: {source}")
    plan = uncut(directory.name, repository(root, sh=run), args.source, options)
    if plan.landing == "integration":
        expected = f"origin/{plan.trunk}"
        upstream = run(["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"],
                       cwd=str(root), check=False)
        if not upstream.ok or upstream.out.strip() != expected:
            raise ValueError(f"checkout {root} must track {expected}")
    return plan, {}, root, plan_path.as_posix()


def _compile(args, plan, tasks, statuses, root, facts, plan_path, events):
    """Build a brief only after the role's preconditions hold."""
    if args.role == "cut":
        beside = None
        if plan.ready:
            # dispatch imports designer; defer the loader import until the cut is compiled.
            from fab import channel, dispatch
            with redirect_stdout(sys.stderr):
                loaded, _ = dispatch._load_plans(channel.plan_dirs(()), events, sh=run, fetch=False)
            beside = drafts_beside(plan, [(other, other_tasks) for other, other_tasks, _, _ in loaded], events)
        return cut_brief(plan, root, plan_path=plan_path, options=args.set, beside=beside, **facts)
    if args.role == "contract":
        if args.part not in plan.parts:
            raise ValueError(f"unknown part {args.part!r}")
        if not plan.parts[args.part].contract:
            raise ValueError(f"part {args.part!r} is not a contract")
        return calls.skeleton_brief(plan, args.part, tasks, statuses, root, role="contract", **facts)
    if args.role == "decision":
        return decision_brief(plan, args.part, tasks, statuses, root, args.run, plan_path=plan_path, **facts)
    if plan.retired:
        raise ValueError(f"plan {plan.draft!r} is already retired")
    changed = changed_designs(root, plan.draft, sh=run, plan_path=plan_path)
    return retire_brief(plan, tasks, statuses, root, changed, plan_path=plan_path, sh=run, **facts)
