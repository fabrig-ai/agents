"""The designer's calls: the cut, shared contracts, a probe's decision, retiring a plan
(docs/design/fab.md, 13.3).

Each is a Claude call like any other (fab.calls.start): a fresh session on a brief compiled
here, writing files on its own branch, which a Codex review run checks before the tick lands
it (13.1). The cut writes a new plan. A contract call designs a part the plan marks as a
shared contract, as a skeleton. A decision turns a probe's report into a design section.
Retire brings a finished plan's status files current and marks the plan retired.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from fab.plan import Plan, Task
from fab.sh import Runner, run

ROLES = ("cut", "contract", "decision", "retire")  # the designer's call roles, in fab.calls.ROLES
DESIGNS = "docs/design"  # a repository's designs; its draft/ holds the user's drafts
PLANS = "docs/plan"  # a repository's plans: <PLANS>/<draft>/plan.toml


def subject(draft: str, role: str, part: str | None = None) -> str:
    """The subject a designer's call logs and parks under (docs/design/fab.md, 12 and 13.1):
    cut `<draft>/cut`, retire `<draft>/retire`, contract `<draft>/<part>` (as a skeleton
    call's, so either one designs the part), decision `<draft>/<part>/decision`. ValueError
    for a role not in ROLES, a part missing for contract or decision, or a part given for
    cut or retire."""
    raise NotImplementedError


def uncut(draft: str, repo: str, sources: Sequence[str] = ()) -> Plan:
    """The stand-in for a plan whose plan.toml does not exist yet: Plan(draft, repo,
    tuple(sources), 1.0, 2.0, {}, ()), no parts, slices or questions, not retired. The cut's
    brief reads its sources through fab.calls.drafts_text; the tick of a plan directory
    being cut runs on it (fab.dispatch.tick)."""
    raise NotImplementedError


def repository(checkout: Path, *, sh: Runner = run) -> str:
    """The name of checkout's repository: the key of fab.run.REMOTES whose URL equals the
    output of `git remote get-url origin` run in checkout (check=True, stripped). ValueError
    naming the URL when no key matches; fab.sh.Failed when git fails."""
    raise NotImplementedError


def designs(root: Path) -> list[str]:
    """The repository's designs: every `*.md` directly in root/DESIGNS, except README.md and
    the status files (`*.status.md`), as repository-relative POSIX paths, sorted. The drafts
    under DESIGNS/draft/ are not designs. Empty when the directory does not exist."""
    raise NotImplementedError


def status_path(design: str) -> str:
    """The status file beside a design: `docs/design/x.md` gives `docs/design/x.status.md`.
    ValueError for a path that does not end in `.md` or is already a status file."""
    raise NotImplementedError


def design_index(root: Path) -> str:
    """The cut's map of the repository's designs, one line per entry of designs(root):
    `- \\`<path>\\` — <title> (<n> lines; status \\`<status path>\\`)`, the title being the
    first line starting with `# ` without that prefix (`(untitled)` when none), n the
    design's line count, and `no status file` in place of `status ...` when status_path's
    file does not exist. `(none)` when there are no designs. The call reads the designs it
    needs itself: all of them would pass fab.calls.BRIEF_LIMIT."""
    raise NotImplementedError


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
    raise NotImplementedError


def retire_due(plan: Plan, tasks: Mapping[str, Task], events: Sequence[dict]) -> bool:
    """Whether the plan's retire call should start, from the plan and the log alone:
    the plan is not retired, has at least one part, every part's status is done
    (fab.state.part_statuses over fab.state.fold(tasks, events)), and no call.started with
    role retire and subject `<draft>/retire` has a call.ended with outcome done. A retire
    call in flight, a parked subject or an open chain is fab.dispatch.call_actions' to
    check, as for every call. Pure."""
    raise NotImplementedError


def enlist(plan_dir: Path) -> bool:
    """Start ticking a plan (docs/design/fab.md, 13.4): add plan_dir, resolved, as one line
    of FAB_HOME/plans, unless a line already names it; return whether it was added. The
    file is created when missing and rewritten whole through fab.atomic.write, its lines
    kept in order with the new one last."""
    raise NotImplementedError


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
    raise NotImplementedError


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
    raise NotImplementedError


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
    raise NotImplementedError


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
    raise NotImplementedError
