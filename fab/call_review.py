"""A Codex review of every Claude call's output before it lands (docs/design/fab.md, 13.1).

Whoever designs a thing never accepts it. A skeleton, answer or structure review call that
ends done leaves a branch; a read-only Codex run reviews it before the dispatcher lands it.
A refusal goes back once, as an amend call on the same branch; refused again, the call's
subject parks for the user. The calls of one branch and their review runs are a chain;
`chains` folds them from the log, and the tick turns each chain's state into its next step.
"""

from __future__ import annotations

import tomllib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from fab import calls, channel, designer, log, run as runs
from fab.hosts import Host
from fab.sh import Runner, run

REVIEWED = ("skeleton", "answer", "review") + designer.ROLES  # call roles whose branch is reviewed before it lands
AMEND = "amend"  # the role of the call that answers a refusal on the same branch
KIND = "review"  # the review run's kind in run.started (fab.run.KINDS)
EFFORT = "medium"  # the review run's Codex effort
ROLE = Path(__file__).resolve().parent / "roles" / "call-reviewer.md"  # the review run's role text
AMENDER = Path(__file__).resolve().parent / "roles" / "amender.md"  # the amend call's role text
CONSISTENCY = Path(__file__).resolve().parent / "roles" / "consistency.md"  # a retire chain's review
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

    The reset: a call.answered whose subject is the chain's subject, later than the chain's
    last call.parked (call the root). A question.answered resets nothing. Amend calls, infra
    review runs and the parked mark count only from the last reset on; `calls` and
    `refusals` keep the whole chain.

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
    started, owners, folded, reviews = {}, {}, {}, {}
    for position, event in enumerate(events):
        kind = event.get("ev", "")
        if kind in ("call.started", "call.ended"):
            _fold_call(event, position, started, owners, folded)
        elif kind in ("run.started", "run.ended"):
            _fold_review(event, position, folded, reviews)
        elif kind == "call.finished" and event.get("call") in owners:
            owners[event["call"]]["finished"] = True
        elif kind == "call.parked" and event.get("call") in folded:
            folded[event["call"]]["parked"] = position
        elif kind == channel.ANSWERED and "subject" in event:
            for chain in folded.values():
                if chain["subject"] == event["subject"] and chain["parked"] >= 0:
                    chain["reset"] = position
    result = {}
    for root, chain in folded.items():
        state, reason = _state(chain)
        result[root] = Chain(root, chain["role"], chain["subject"], chain["branch"],
                             tuple(chain["calls"]), chain["latest"], tuple(chain["refusals"]),
                             state, reason)
    return result


def brief(chain: Chain, *, run_id: str, base: str, tip: str, stat: str, diff: str,
          report: str, designs: Sequence[str] = (), answers: str = "") -> str:
    """The review run's brief, its sections in this order, joined by blank lines and ending
    with a newline:

    1. The role text, CONSISTENCY's for retire chains, ROLE's otherwise.
    2. `# Your review`: one line each, `- Run: <run_id>`, `- Call: <root> (<role>)`, and when
       latest is not the root `- Amended by: <latest>`, `- Subject: <subject>`,
       `- Branch: \\`<branch>\\``, `- Base: \\`<base>\\``, `- Tip: \\`<tip>\\``,
       `- Report: write it to \\`<report>\\``, then the line `Your checkout is the tip, read-only;
       \\`git diff <base> <tip>\\` is the change.`
       For retire only, follow with `# Designs changed since the plan started`, one
       `- \\`<path>\\`` line per designs entry, or `(none)`. Other roles ignore designs.
    3. `# Earlier findings`, only when the chain has refusals: per refusal in order,
       `## <run>` and the first FINDINGS_LINES lines of FAB_HOME/runs/<run>/report.md
       (`(report missing)` when it cannot be read).
    4. fab.channel.SECTION, then answers, only when answers is not empty.
    5. `# The diff`: stat in a ```text fence, then diff in a ```diff fence. A diff longer than
       DIFF_LIMIT characters is cut at the last newline at or before DIFF_LIMIT and followed,
       after its fence, by the line `The diff is cut at <DIFF_LIMIT> characters; read the
       rest with \\`git diff <base> <tip>\\`.`
    6. `# The call's brief`: the line `What the call was asked, verbatim, to the end of this
       brief:`, then the text of FAB_HOME/calls/<root>/brief.md, or `(brief missing: <path>)`.

    Never refuses for size: the call's brief is already bounded by fab.calls.BRIEF_LIMIT."""
    facts = [f"- Run: {run_id}", f"- Call: {chain.root} ({chain.role})"]
    if chain.latest != chain.root:
        facts.append(f"- Amended by: {chain.latest}")
    facts.extend([f"- Subject: {chain.subject}", f"- Branch: `{chain.branch}`",
                  f"- Base: `{base}`", f"- Tip: `{tip}`", f"- Report: write it to `{report}`",
                  f"Your checkout is the tip, read-only; `git diff {base} {tip}` is the change."])
    role = CONSISTENCY if chain.role == "retire" else ROLE
    sections = [role.read_text().rstrip("\n"), "# Your review\n\n" + "\n".join(facts)]
    if chain.role == "retire":
        sections.append("# Designs changed since the plan started\n\n" +
                        ("\n".join(f"- `{path}`" for path in designs) or "(none)"))
    if chain.refusals:
        sections.append("# Earlier findings\n\n" + _findings(chain.refusals))
    if answers:
        sections.append(channel.SECTION + "\n\n" + answers)
    cut = len(diff) > DIFF_LIMIT
    if cut:
        newline = diff.rfind("\n", 0, DIFF_LIMIT + 1)
        diff = diff[:newline] if newline >= 0 else ""
    stat, diff = stat.removesuffix("\n"), diff.removesuffix("\n")
    change = f"# The diff\n\n```text\n{stat}\n```\n\n```diff\n{diff}\n```"
    if cut:
        change += f"\n\nThe diff is cut at {DIFF_LIMIT} characters; read the rest with `git diff {base} {tip}`."
    sections.append(change)
    path = log.home() / "calls" / chain.root / "brief.md"
    try:
        text = path.read_text()
    except (OSError, UnicodeError):
        text = f"(brief missing: {path})"
    sections.append("# The call's brief\n\nWhat the call was asked, verbatim, to the end of this brief:\n\n" + text)
    return "\n\n".join(sections) + ("" if text.endswith("\n") else "\n")


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
    directory = log.home() / "calls"
    facts = [f"- Call: {chain.root} ({chain.role})", f"- Subject: {chain.subject}",
             f"- Branch: `{chain.branch}`", f"- Its brief: `{directory / chain.root / 'brief.md'}`"]
    facts.extend(f"- Amended by: {call} (report `{directory / call / 'report.md'}`)"
                 for call in chain.calls[1:])
    facts.append("Read its brief first: it is the task you are finishing.")
    return calls._brief([("Role", AMENDER.read_text().rstrip("\n")),
                         ("Call facts", calls._facts(call_id, branch, report)),
                         ("The call you amend", "\n".join(facts)),
                         ("Findings", _findings(chain.refusals))])


def start(chain: Chain, repo: str, checkout: Path, host: Host, events: Iterable[dict], *,
          sh: Runner = run, log_path: Path | None = None) -> str:
    """Start the review run of chain's branch on host (a builder) and return its run id.

    1. In checkout (the plan's repository on this machine, a clone with origin), each with
       check=True: `git fetch origin`; the tip `git rev-parse --verify
       refs/remotes/origin/<branch>^{commit}`; the base `git merge-base
       refs/remotes/origin/main <tip>`; stat `git diff --stat <base> <tip>`; diff
       `git diff <base> <tip>`. For retire, get designer.changed_designs(checkout,
       <subject before its last slash>, rev=tip, sh=sh) for the consistency brief.
       Read the plan and its whole sources independently with `git show <tip>:<path>`;
       put them before the call's brief, even when that brief has only excerpts. Subjects
       name the draft before the part or reserved suffix (answer names the draft itself).
       Non-file sources get a note. A git failure reading the plan raises fab.sh.Failed;
       malformed TOML or missing plan history raises ValueError. Either starts nothing.
    2. The run id fab.run.next_run(chain.root, events): `<root>-<n>`.
    3. fab.run.launch_detached(host, run_id, repo, tip, task=chain.root, kind=KIND,
       branch=chain.branch, base=<base>, brief=brief(...), effort=EFFORT,
       call=chain.latest, tip=<tip>, sh=sh, log_path=log_path), the brief's report being
       `<fab.run.remote_home(host)>/runs/<run>/report.md`, where launch puts it.
       launch_detached fetches the builder's clone and adds the detached worktree before
       launching read-only; on a launch failure it removes the worktree and re-raises.
    fab.run.collect ends the run as any other: its run.ended carries the outcome the chain
    reads, and frees the worktree."""
    def git(*argv):
        return sh(["git", *argv], cwd=str(checkout), check=True).out

    git("fetch", "origin")
    tip = git("rev-parse", "--verify", f"refs/remotes/origin/{chain.branch}^{{commit}}").strip()
    base = git("merge-base", "refs/remotes/origin/main", tip).strip()
    stat = git("diff", "--stat", base, tip)
    diff = git("diff", base, tip)
    designs = (designer.changed_designs(checkout, chain.subject.rsplit("/", 1)[0], rev=tip, sh=sh)
               if chain.role == "retire" else ())
    draft = chain.subject if chain.role == "answer" else chain.subject.rsplit("/", 1)[0]
    if chain.role == "decision":
        draft = draft.rsplit("/", 1)[0]
    plan = tomllib.loads(git("show", f"{tip}:docs/plan/{draft}/plan.toml"))
    drafts = []
    for source in plan.get("sources", ()):
        path = Path(source)
        content = "(not a file in this repository)"
        if source and not path.is_absolute() and ".." not in path.parts:
            result = sh(["git", "show", f"{tip}:{source}"], cwd=str(checkout))
            if result.ok:
                content = result.out
        drafts.append(f"## {source}\n\n{content}")
    events = list(events)
    run_id = runs.next_run(chain.root, events)
    root = Path(runs.remote_home(host))
    text = brief(chain, run_id=run_id, base=base, tip=tip, stat=stat, diff=diff,
                 report=str(root / "runs" / run_id / "report.md"), designs=designs,
                 answers=channel.answers_text(chain.subject, events))
    before, marker, original = text.partition("# The call's brief\n\n")
    text = before + "# The user's drafts\n\n" + ("\n\n".join(drafts) or "(none)") + "\n\n" + marker + original
    return runs.launch_detached(host, run_id, repo, tip, task=chain.root, kind=KIND,
                                branch=chain.branch, base=base, brief=text, effort=EFFORT,
                                call=chain.latest, tip=tip, sh=sh, log_path=log_path)


def _fold_call(event: dict, position: int, started: dict, owners: dict, folded: dict) -> None:
    """Join calls to their roots, keeping end positions for the state precedence."""
    call = event.get("call")
    if call is None:
        return
    if event["ev"] == "call.started":
        if event.get("role") == AMEND and event.get("amends") in folded and call not in owners:
            chain = folded[event["amends"]]
            amendment = {"call": call, "position": position, "outcome": None}
            chain["amendments"].append(amendment)
            chain["calls"].append(call)
            owners[call] = chain
            started[call] = amendment
        elif event.get("role") in REVIEWED and "amends" not in event:
            if all(field in event for field in ("subject", "branch")):
                started.setdefault(call, event)
        return
    if "outcome" not in event or call not in started:
        return
    if call in owners:
        chain = owners[call]
        amendment = started[call]
        if call != chain["root"] and amendment["outcome"] is None:
            amendment["outcome"] = event["outcome"]
            if event["outcome"] == "done":
                chain["latest"], chain["latest_position"] = call, position
    elif event["outcome"] == "done":
        first = started[call]
        folded[call] = owners[call] = {
            "root": call, "role": first["role"], "subject": first["subject"],
            "branch": first["branch"], "calls": [call], "latest": call,
            "latest_position": position, "refusals": [], "amendments": [], "reviews": [],
            "reset": -1, "parked": -1, "finished": False,
        }


def _state(chain: dict) -> tuple[str, str]:
    """Choose the first applicable state from the chain's ordered records."""
    reset = chain["reset"]
    amendments = [call for call in chain["amendments"] if call["position"] > reset]
    reviews = chain["reviews"]
    if chain["finished"]:
        return "finished", ""
    if chain["parked"] > reset:
        return "parked", ""
    if any(call["outcome"] is None for call in amendments):
        return "amending", ""
    if amendments and amendments[-1]["outcome"] != "done":
        return "hold", f"the amend call ended {amendments[-1]['outcome']}"
    latest = reviews[-1] if reviews else None
    if latest and latest["outcome"] is None:
        return "reviewing", ""
    if latest is None or latest["position"] <= max(chain["latest_position"], reset):
        return "review", ""
    if latest["outcome"] == "infra":
        count = sum(review["outcome"] == "infra" and review["position"] > reset for review in reviews)
        return ("review", "") if count < INFRA_LIMIT else ("hold", f"{INFRA_LIMIT} review runs ended infra")
    if latest["outcome"] == "done":
        return "approved", ""
    return ("hold", "refused after its amendment") if amendments else ("amend", "")


def _findings(refusals: tuple[str, ...]) -> str:
    """Quote each refusal once, with a bounded excerpt and an unreadable-report marker."""
    findings = []
    for run_id in refusals:
        try:
            text = (log.home() / "runs" / run_id / "report.md").read_text()
        except (OSError, UnicodeError):
            text = "(report missing)"
        findings.append(f"## {run_id}\n\n" + "\n".join(text.splitlines()[:FINDINGS_LINES]))
    return "\n\n".join(findings) if findings else "(none)"


def _fold_review(event: dict, position: int, folded: dict, reviews: dict) -> None:
    """Attach review runs and their first complete ending to an existing root."""
    if event["ev"] == "run.started" and event.get("kind") == KIND:
        root, run_id = event.get("task"), event.get("run")
        if root in folded and run_id is not None and run_id not in reviews:
            review = {"position": position, "outcome": None}
            reviews[run_id] = (folded[root], review)
            folded[root]["reviews"].append(review)
    elif event["ev"] == "run.ended" and "run" in event and "outcome" in event:
        if event["run"] in reviews:
            chain, review = reviews[event["run"]]
            if review["outcome"] is None:
                review["outcome"] = event["outcome"]
                if event["outcome"] not in ("done", "infra"):
                    chain["refusals"].append(event["run"])
