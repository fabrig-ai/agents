+++
id = "guard"
part = "guard"
kind = "feature"
needs = []
files = ["fab/dispatch.py", "fab/fixes.py", "fab/gates.py", "fab/roles/foreman-finding.md", "fab/tests/test_dispatch.py", "fab/tests/test_fixes.py"]
effort = "medium"
minutes = 45
+++
# A finding repair leaves the plan's rung briefs

Read first: `docs/plan/brief-guard/inputs/request.md`;
`docs/design/qa.md`, 2, "A repair leaves the briefs" and "The repair is
`<draft>/finding-<n>`". Your base is main's tip.

The request: a changed path among the plan's rung brief files refuses a
finding repair before it is readied, and the repair's and foreman's text say
to leave them. A brief change makes a new edition and reopens every rung; a
brief's edit is triage's `brief` decision.

## What to build

**The check, in `fab/dispatch.py`:**

- `_take`'s `ready` case (near line 1128) passes `plan=plan`,
  `plan_dir=plan_dir`, `checkout=checkout` to `_screen_ready`.
- `_screen_ready` (near line 2065), after `rust_gates.screen` finds nothing
  and before `_ready`: when `task.kind == fixes.KIND`, its findings are a new
  private `_screen_briefs(action, task, plan, plan_dir, checkout, sh=sh,
  log_path=log_path) -> list[gates.Finding]`. The existing `if findings:`
  line then returns `rejected gate:briefs`, so the check has no return of its
  own.
- `_screen_briefs`:
  - the brief paths: the union of `rung.brief` over `plan.rungs.values()`
    (every rung's, since one kit is shared; `plan.rungs`' paths are relative
    to the plan directory), each joined under `plan_dir.resolve().relative_to(
    checkout.resolve())` and `.as_posix()`, as `fab/walks.py` `_briefs` does.
    No rungs: return `[]` with no git at all.
  - in `log.home() / "repos" / task.repo`, which `rust_gates.screen` has just
    cloned and fetched: `git rev-parse --verify
    refs/remotes/origin/<action.branch>^{commit}`, then `git merge-base
    refs/remotes/origin/main <tip>`, as `fab/rust_gates.py:60-63` do, then
    `fab.rust_digest.changes(repo, base, tip, sh=sh)` (it passes
    `--no-renames`, so a renamed or deleted brief shows under its old path).
    Add `rust_digest` to the imports at `fab/dispatch.py:25`.
  - one `gates.Finding("briefs", f"`{path}` is a rung brief, not this
    repair's to change: drop the edit")` per changed brief path, in `changes`'
    order.
  - any: `log.append("branch.rejected", path=log_path, task=task.id,
    branch=action.branch, tip=tip, step="gate:briefs", log=<the digest>,
    findings=gates.findings_text(findings))`, the fields
    `fab/rust_gates.py:74-75` logs; the digest is `log.home() / "digests" /
    f"{run}.md"`, which the screen just wrote, `run` from the task's last
    `run.started`.
- In `fab/gates.py`, only the comment on `Finding.gate` (line 30): it also
  names `briefs`, which is not in `GATES` because no digest decides it.

Only the `finding` kind is checked: red repairs and every other kind are
not, and run no git beyond the screen's.

**The text.** `fab/fixes.py` `_body`'s Acceptance (near line 178) ends with:
"The plan's rung briefs are not this repair's to change: leave them, and say
so in your report if one is at fault." The same sentence goes in
`fab/roles/foreman-finding.md`, in "What you decide", after "When unsure, it
is the code's", wrapped as the file wraps.

## Acceptance

Tests with fakes and fixture logs, as the gate tests near
`fab/tests/test_dispatch.py:4708` do (`rust_gates.screen` patched,
`FakeRunner` answering `git rev-parse --verify`, `git merge-base` and `git
diff --numstat`), beside `FindingDispatchTest` (near line 7203), driving
`dispatch._take` with a `ready` action. The plan has rungs (`fab.tests.
ladder_plans.write_ladder`, or `replace(plan, rungs=...)`) and its directory
sits below the checkout, so that the path compared is repository-relative:

- a finding repair changing a brief file: `branch.rejected` with step
  `gate:briefs`, task, branch, tip, log and findings naming the repository
  path; no `branch.ready`, no push of a `ready/` ref;
- a finding repair changing other files is readied;
- the same branch on a `feature` task and on a `red` task is readied, with no
  `git diff` run by the check;
- a plan without rungs: a finding repair is readied, no `git diff`;
- `rust_gates.screen` refusing: only its rejection is logged;
- a `gate:briefs` rejection of a finding repair gets its refusal foreman
  (`dispatch.repair_actions`, as `test_finding_dispatch_refusal_foreman_uses_main`).

In `fab/tests/test_fixes.py`: `tasks`' body holds the sentence under
`## Acceptance`; `fixes.ROLE.read_text()` holds it, whitespace normalised.

`bin/fab test` green within its budget; `bin/fab status docs/plan/brief-guard`
shows no plan problems.

## Pre-approved defaults

- A branch refused by a Rust gate is not checked that time; it meets the check
  on its next readying.
- The compared tip is the branch's remote tip, as `rust_gates.screen`'s is. A
  fetch between the two is not guarded: the tick is one process.
- The design already says this (`docs/design/qa.md` 2). Leave it and its
  status file alone; the retire call brings `docs/design/qa.status.md` current.
  Where the code shows the design cannot hold as written, change qa.md 2 and
  its status line in this branch and say so in your report.
- `fab/tests/test_fixes.py` or another test pinning `_body`'s exact text
  gains the sentence; nothing else about it changes.
- A file outside `files` is a `Question:`. No other gate, step or record.
- Python 3.13 standard library; docstrings and comments as the code beside
  them; `fab/taste.md` applies. Tests use `fab.tests.support.tmp_home()` and
  `FakeRunner`, never live state or real git.

## Report

First line `Done: <what landed, one line>`, `Question: <what you need>` (with
options and your recommendation) or `Failed: <why>`. Then: the functions added
or changed, the tests added, and any default above you took.
