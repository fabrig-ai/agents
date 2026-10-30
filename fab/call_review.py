"""A Codex review of every Claude call's output before it lands (docs/design/fab.md, 13.1).

Whoever designs a thing never accepts it. A skeleton, answer or structure review call that
ends done leaves a branch; a read-only Codex run reviews it before the dispatcher lands it.
A refusal goes back once, as an amend call on the same branch; refused again, the call's
subject parks for the user. The calls of one branch and their review runs are a chain;
`chains` folds them from the log, and the tick turns each chain's state into its next step.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from fab.hosts import Host
from fab.sh import Runner, run

REVIEWED = ("skeleton", "answer", "review")  # call roles whose branch is reviewed before it lands
AMEND = "amend"  # the role of the call that answers a refusal on the same branch
KIND = "review"  # the review run's kind in run.started (fab.run.KINDS)
EFFORT = "medium"  # the review run's Codex effort
ROLE = Path(__file__).resolve().parent / "roles" / "call-reviewer.md"  # the review run's role text
AMENDER = Path(__file__).resolve().parent / "roles" / "amender.md"  # the amend call's role text
DIFF_LIMIT = 120_000  # characters of the diff a review brief quotes; the run reads the rest itself
FINDINGS_LINES = 40  # lines of a refusing report quoted in later briefs
INFRA_LIMIT = 3  # review runs of a chain ending infra since its reset that park it
STATES = ("review", "reviewing", "approved", "amend", "amending", "hold", "parked", "finished")


@dataclass(frozen=True)
class Chain:
    root: str  # the first call's id; the chain's subject and branch are its own
    role: str  # the root's role, one of REVIEWED
    subject: str  # the root's subject: `<draft>/<part>`, `<draft>` or `<draft>/review`
    branch: str  # `calls/<root>`, which every call of the chain pushes to
    calls: tuple[str, ...]  # the root, then each amend call, in log order
    latest: str  # the last call of the chain that ended done: the output to review or land
    refusals: tuple[str, ...]  # review runs that refused, in log order, over the whole chain
    state: str  # one of STATES
    reason: str = ""  # for hold: why the chain parks, one line


def chains(events: Iterable[dict]) -> dict[str, Chain]:
    """Every chain in the events, keyed by root, in the order the roots' call.ended appear.

    A chain starts at a call.ended with outcome done whose call.started (same call) has a role
    in REVIEWED and no `amends` field; that call is its root. A call.started with role AMEND
    whose `amends` names a chain's root joins that chain (one naming no known root is
    ignored). The chain's review runs are the run.started records with kind KIND whose task is
    the root, each with the first run.ended of the same run; an ended review run refused
    unless its outcome is done or infra.

    The reset: a question.answered whose task is the chain's subject, later than the chain's
    last call.parked (call the root). Amend calls, infra review runs and the parked mark count
    only from the last reset on; `calls` and `refusals` keep the whole chain.

    The state is the first of these that holds:
    - finished: a call.finished names any call of the chain (its outcome aside; one logged by
      hand drops the chain);
    - parked: a call.parked names the root, after the last reset;
    - amending: an amend call since the reset has no call.ended;
    - hold, reason `the amend call ended <outcome>`: the last amend call since the reset ended
      with an outcome other than done;
    - reviewing: the last review run has no run.ended;
    - review: no review run started after both latest's call.ended and the last reset; or the
      last one ended infra and fewer than INFRA_LIMIT review runs since the reset did;
    - hold, reason `<INFRA_LIMIT> review runs ended infra`: the last one ended infra;
    - approved: the last review run ended done;
    - amend: it refused, and the chain has no amend call since the reset;
    - hold, reason `refused after its amendment`: it refused.

    Pure: no file is read. Records missing a field the rule reads are skipped."""
    raise NotImplementedError


def brief(chain: Chain, *, run_id: str, base: str, tip: str, stat: str, diff: str,
          report: str) -> str:
    """The review run's brief, its sections in this order, joined by blank lines and ending
    with a newline:

    1. The role text, ROLE's.
    2. `# Your review`: one line each, `- Run: <run_id>`, `- Call: <root> (<role>)`, and when
       latest is not the root `- Amended by: <latest>`, `- Subject: <subject>`,
       `- Branch: \\`<branch>\\``, `- Base: \\`<base>\\``, `- Tip: \\`<tip>\\``,
       `- Report: write it to \\`<report>\\``, then the line `Your checkout is the tip, read-only;
       \\`git diff <base> <tip>\\` is the change.`
    3. `# Earlier findings`, only when the chain has refusals: per refusal in order,
       `## <run>` and the first FINDINGS_LINES lines of FAB_HOME/runs/<run>/report.md
       (`(report missing)` when it cannot be read).
    4. `# The diff`: stat in a ```text fence, then diff in a ```diff fence. A diff longer than
       DIFF_LIMIT characters is cut at the last newline at or before DIFF_LIMIT and followed,
       after its fence, by the line `The diff is cut at <DIFF_LIMIT> characters; read the
       rest with \\`git diff <base> <tip>\\`.`
    5. `# The call's brief`: the line `What the call was asked, verbatim, to the end of this
       brief:`, then the text of FAB_HOME/calls/<root>/brief.md, or `(brief missing: <path>)`.

    Never refuses for size: the call's brief is already bounded by fab.calls.BRIEF_LIMIT."""
    raise NotImplementedError


def amend_brief(chain: Chain, *, call_id: str, branch: str, report: str) -> str:
    """The amend call's brief, through fab.calls' own section builder and facts (so
    fab.calls.start rebinds its `# Call facts` as for any call), sections in this order:

    1. `Role`: AMENDER's text.
    2. `Call facts`: call_id, branch and report as every call's.
    3. `The call you amend`: `- Call: <root> (<role>)`, `- Subject: <subject>`,
       `- Branch: \\`<chain.branch>\\``, `- Its brief: \\`<FAB_HOME/calls/<root>/brief.md>\\``,
       then per earlier amend call of the chain `- Amended by: <call> (report
       \\`<FAB_HOME/calls/<call>/report.md>\\`)`, then the line `Read its brief first: it is the
       task you are finishing.`
    4. `Findings`: per refusal in order, `## <run>` and the first FINDINGS_LINES lines of
       FAB_HOME/runs/<run>/report.md (`(report missing)` when it cannot be read); `(none)`
       when the chain has no refusals.

    ValueError past fab.calls.BRIEF_LIMIT, as every call's brief."""
    raise NotImplementedError


def start(chain: Chain, repo: str, checkout: Path, host: Host, events: Iterable[dict], *,
          sh: Runner = run, log_path: Path | None = None) -> str:
    """Start the review run of chain's branch on host (a builder) and return its run id.

    1. In checkout (the plan's repository on this machine, a clone with origin), each with
       check=True: `git fetch origin`; the tip `git rev-parse --verify
       refs/remotes/origin/<branch>^{commit}`; the base `git merge-base
       refs/remotes/origin/main <tip>`; stat `git diff --stat <base> <tip>`; diff
       `git diff <base> <tip>`. A failure raises fab.sh.Failed and starts nothing.
    2. The run id fab.run.next_run(chain.root, events): `<root>-<n>`.
    3. On host: clone = fab.run.fetch_clone(host, repo); the worktree
       `<fab.run.remote_home(host)>/wt/<run>`, added with `git -C <clone> worktree add
       --detach <worktree> <tip>` over ssh (check=True).
    4. fab.run.launch(host, run_id, task=chain.root, kind=KIND, workdir=<worktree>,
       branch=chain.branch, base=<base>, brief=brief(...), effort=EFFORT, read_only=True,
       call=chain.latest, tip=<tip>), the brief's report being
       `<remote_home>/runs/<run>/report.md`, where launch puts it.
    A failure after the worktree is added removes it (`git -C <clone> worktree remove --force
    <worktree>`, errors ignored) and re-raises. fab.run.collect ends the run as any other:
    its run.ended carries the outcome the chain reads, and frees the worktree."""
    raise NotImplementedError
