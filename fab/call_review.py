"""A Codex review of every Claude call's output before it lands (docs/design/calls.md, 2).

Whoever designs a thing never accepts it. A skeleton, answer or structure review call that
ends done leaves a branch; a read-only Codex run reviews it before the dispatcher lands it.
A refusal goes back once, as an amend call on the same branch; refused again, the call's
subject goes to a settle call. The calls of one branch and their review runs are a chain;
`chains` folds them from the log, and the tick turns each chain's state into its next step.
"""

from __future__ import annotations

import json
import tomllib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from fab import calls, channel, designer, log, run as runs
from fab.hosts import Host
from fab.plan import Task
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
INFRA_LIMIT = 3  # review runs ending infra since the reset that hold the chain
LAND_HOLD = "refused by fab land after its amendment"  # a landing refusal holds the amended tip
LAND_STEPS = ("fetch", "rebase", "paths", "test", "push")  # fab land, excluding queue and trunk steps
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
    reason: str = ""  # for hold: why the chain needs settlement, one line


def chains(events: Iterable[dict]) -> dict[str, Chain]:
    """Every chain in the events, keyed by root, in the order the roots' call.ended appear.

    A chain starts at a call.ended with outcome done whose call.started (same call) has a role
    in REVIEWED and no `amends` field; that call is its root. A call.started with role AMEND
    whose `amends` names a chain's root joins that chain (one naming no known root is
    ignored). The chain's review runs are the run.started records with kind KIND whose task is
    the root, each with the first run.ended of the same run; an ended review run refused
    unless its outcome is done or infra.

    The reset: a call.answered whose subject is the chain's subject, later than the chain's
    last call.parked (call the root). A chain.settled amend also resets counts; land
    approves the tip, user parks it. A question.answered resets nothing. Amend calls, infra
    review runs and the parked mark count only from the last reset on; `calls` and
    `refusals` keep the whole chain.

    The state is the first of these that holds:
    - finished: a call.finished names any call of the chain (its outcome aside; one logged by
      hand drops the chain);
    - parked: a call.parked names the root, after the last reset; a legacy park with a
      hold reason and no chain.settled is held again until settlement;
    - approved: a land settlement follows every review and the latest call;
    - amending: an amend call since the reset has no call.ended;
    - hold, reason `the amend call ended <outcome>`: the last amend call since the reset ended
      with an outcome other than done;
    - reviewing: the last review run has no run.ended;
    - review: no review run started after both latest's call.ended and the last reset; or the
      last one ended infra and fewer than INFRA_LIMIT review runs since the reset did;
    - hold, reason `<INFRA_LIMIT> review runs ended infra`: the last one ended infra;
    - approved: the last review run ended done;
    - amend: it refused, and the chain has no amend call since the reset;
    - hold, reason `refused by fab land after its amendment` for a fab land refusal,
      else `refused after its amendment`: it refused.
    Pure: no file is read. Records missing a field the rule reads are skipped."""
    started, owners, folded, reviews = {}, {}, {}, {}
    for position, event in enumerate(events):
        kind = event.get("ev", "")
        if kind in ("call.started", "call.ended"):
            _fold_call(event, position, started, owners, folded)
        elif kind in ("run.started", "run.ended", "branch.rejected"):
            _fold_review(event, position, folded, reviews)
        elif kind == "call.finished" and event.get("call") in owners:
            owners[event["call"]]["finished"] = True
        elif kind == "call.parked" and event.get("call") in folded:
            folded[event["call"]]["parked"] = position
            folded[event["call"]]["park_reason"] = event.get("reason", "")
        elif kind == "chain.settled" and event.get("call") in folded:
            _fold_settlement(event, position, folded[event["call"]])
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
    sections.append("# The diff\n\n" + _diff_text(base, tip, stat, diff))
    path = log.home() / "calls" / chain.root / "brief.md"
    try:
        text = path.read_text()
    except (OSError, UnicodeError):
        text = f"(brief missing: {path})"
    sections.append("# The call's brief\n\nWhat the call was asked, verbatim, to the end of this brief:\n\n" + text)
    return "\n\n".join(sections) + ("" if text.endswith("\n") else "\n")


def hold_reason(reason: str) -> bool:
    """Whether a pre-settlement park is one of the three automatic chain holds."""
    return (reason == "refused after its amendment"
            or reason.startswith("the amend call ended ")
            or reason == f"{INFRA_LIMIT} review runs ended infra")


def settle_calls(chain: Chain, events: Iterable[dict]) -> list[str]:
    """Settle attempts for this root since its last user reset, in start order. Pure.

    A settle's amend resets review counts but keeps these attempts: the second attempt
    permits land or user only. A user's answer after a park grants fresh attempts too.
    """
    attempts = []
    parked = False
    for event in events:
        if event.get("ev") == "call.parked" and event.get("call") == chain.root:
            parked = True
        elif event.get("ev") == channel.ANSWERED and event.get("subject") == chain.subject and parked:
            attempts = []
        elif (event.get("ev") == "call.started" and event.get("role") == "settle"
              and event.get("settles") == chain.root and "call" in event):
            attempts.append(event["call"])
    return attempts


def _diff_text(base: str, tip: str, stat: str, diff: str) -> str:
    """Fence a merge-base diff and its stat, bounding it as the review and settle briefs do."""
    cut = len(diff) > DIFF_LIMIT
    if cut:
        newline = diff.rfind("\n", 0, DIFF_LIMIT + 1)
        diff = diff[:newline] if newline >= 0 else ""
    stat, diff = stat.removesuffix("\n"), diff.removesuffix("\n")
    change = f"```text\n{stat}\n```\n\n```diff\n{diff}\n```"
    if cut:
        change += f"\n\nThe diff is cut at {DIFF_LIMIT} characters; read the rest with `git diff {base} {tip}`."
    return change


def settle_brief(chain: Chain, checkout: Path, events: Iterable[dict], *,
                 call_id: str, branch: str, report: str, sh: Runner = run) -> str:
    """Compile the held chain's judgement with its merge-base diff and report paths.

    Fetch the branch and quote its diff with the review brief's bound. Include every
    refusal and amend report's path and excerpt, the root brief's path and hold reason.
    A LAND_HOLD permits amend or user first, user only second; other holds permit land
    too. Commands go through sh (docs/design/calls.md, 2).
    """
    def git(*argv):
        return sh(["git", *argv], cwd=str(checkout), check=True).out

    git("fetch", "origin")
    tip = git("rev-parse", "--verify", f"refs/remotes/origin/{chain.branch}^{{commit}}").strip()
    base = git("merge-base", "refs/remotes/origin/main", tip).strip()
    stat = git("diff", "--stat", base, tip).rstrip("\n")
    diff = git("diff", base, tip)
    change = _diff_text(base, tip, stat, diff)
    directory = log.home() / "calls"
    facts = (f"- Call: {chain.root} ({chain.role})\n- Subject: {chain.subject}\n"
             f"- Branch: `{chain.branch}`\n- Base: `{base}`\n- Tip: `{tip}`\n"
             f"- Its brief: `{directory / chain.root / 'brief.md'}`\n- Hold: {chain.reason}")
    restriction = _settle_restriction(chain, bool(settle_calls(chain, events)))
    amendments = []
    for call in chain.calls[1:]:
        path = directory / call / "report.md"
        amendments.append(f"## {call}\n\n- Report: `{path}`\n\n" + channel.excerpt(path, FINDINGS_LINES))
    refusals = "\n".join(f"- Report: `{log.home() / 'runs' / run_id / 'report.md'}`"
                          for run_id in chain.refusals if not run_id.startswith("queue:"))
    return calls._brief([("Role", calls.ROLES["settle"].read_text().rstrip("\n")),
                         ("Call facts", calls._facts(call_id, branch, report)),
                         ("The held chain", facts + "\n\n" + restriction),
                         ("Findings", refusals + "\n\n" + _findings(chain.refusals)),
                         ("Amend reports", "\n\n".join(amendments) or "(none)"),
                         ("The diff", change)])


def amend_brief(chain: Chain, *, call_id: str, branch: str, report: str,
                designs: Sequence[str] = (), rebase: str = "") -> str:
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
       when the chain has no refusals. fab land refusals name their step and quote their log.
       rebase adds the test refusal's outcome: rebased, conflicted (aborted), or pending
       (--brief-only); empty keeps the findings unchanged.
    5. `Designs main changed since your branch`, only for non-empty designs: each design
       and its designer.status_path, then ask to check those status files against the branch
       (docs/design/calls.md, 2).

    ValueError past fab.calls.BRIEF_LIMIT, as every call's brief."""
    directory = log.home() / "calls"
    facts = [f"- Call: {chain.root} ({chain.role})", f"- Subject: {chain.subject}",
             f"- Branch: `{chain.branch}`", f"- Its brief: `{directory / chain.root / 'brief.md'}`"]
    facts.extend(f"- Amended by: {call} (report `{directory / call / 'report.md'}`)"
                 for call in chain.calls[1:])
    facts.append("Read its brief first: it is the task you are finishing.")
    sections = [("Role", AMENDER.read_text().rstrip("\n")),
                ("Call facts", calls._facts(call_id, branch, report)),
                ("The call you amend", "\n".join(facts)),
                ("Findings", _findings(chain.refusals))]
    if rebase:
        outcome = {
            "rebased": "The branch was rebased onto origin/main and pushed before this amend.",
            "conflicted": "The rebase onto origin/main conflicted and was aborted; nothing was pushed. "
                          "Rebase first and resolve the conflicts before fixing the test refusal.",
            "pending": "The branch would be rebased onto origin/main and pushed before this amend "
                       "(--brief-only).",
        }[rebase]
        sections[-1] = ("Findings", sections[-1][1] + "\n\n" + outcome)
    if designs:
        paths = "\n".join(f"- `{path}` (status `{designer.status_path(path)}`)" for path in designs)
        sections.append(("Designs main changed since your branch", paths + "\n\n" +
                         "Main changed these designs after your branch's tip: check each one's status file "
                         "against what your branch writes."))
    return calls._brief(sections)


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
    plan_path = f"docs/plan/{draft}/plan.toml"
    if repo == "fabrig":
        paths = git("ls-tree", "-r", "--name-only", tip).splitlines()
        matches = [path for path in paths if path == plan_path or path.endswith("/" + plan_path)]
        if len(matches) != 1:
            raise ValueError(f"expected one plan for {draft}, found {len(matches)}")
        plan_path = matches[0]
    plan = tomllib.loads(git("show", f"{tip}:{plan_path}"))
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
            "reset": -1, "parked": -1, "park_reason": "", "finished": False,
            "settled": -1, "approved": -1,
        }


def _fold_settlement(event: dict, position: int, chain: dict) -> None:
    """Apply a complete settlement to its root without discarding the chain's history."""
    if (event.get("subject") != chain["subject"] or "settle" not in event or "text" not in event
            or event.get("verdict") not in ("land", "amend", "user")):
        return
    chain["settled"] = position
    if event["verdict"] == "amend":
        chain["reset"] = position
    elif event["verdict"] == "land":
        chain["approved"] = position
    else:
        chain["parked"] = position
        chain["park_reason"] = "user: " + event["text"]


def _state(chain: dict) -> tuple[str, str]:
    """Choose the first applicable state from the chain's ordered records."""
    reset = chain["reset"]
    amendments = [call for call in chain["amendments"] if call["position"] > reset]
    reviews = chain["reviews"]
    if chain["finished"]:
        return "finished", ""
    if chain["parked"] > max(reset, chain["settled"]):
        if chain["settled"] >= 0 or not hold_reason(chain["park_reason"]):
            return "parked", ""
    elif chain["parked"] > reset and chain["park_reason"].startswith("user: "):
        return "parked", ""
    last_review = reviews[-1]["position"] if reviews else -1
    if chain["approved"] > max(reset, chain["latest_position"], last_review):
        return "approved", ""
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
    reason = LAND_HOLD if land_refusal(chain["refusals"][-1]) else "refused after its amendment"
    return ("hold", reason) if amendments else ("amend", "")


def land_refusal(refusal: str) -> dict | None:
    """Return fab land's branch.rejected record, else None (docs/design/calls.md, 2).

    A queue:-encoded record must have no queue_ts and a step in LAND_STEPS; review
    run ids, queue and integration trunk rejections are not fab land refusals.
    """
    if not refusal.startswith("queue:"):
        return None
    try:
        record = json.loads(refusal.removeprefix("queue:"))
    except json.JSONDecodeError:
        return None
    if (isinstance(record, dict) and record.get("ev") == "branch.rejected"
            and "queue_ts" not in record and record.get("step") in LAND_STEPS):
        return record
    return None


def land_tries(chain: Chain, events: Iterable[dict], step: str) -> list[dict]:
    """Fab land refusals at step since the later of latest's ending and the last reset.

    Count by log position for this branch, regardless of tip. A subject's call.answered
    or this root's chain.settled amend resets attempts; queue refusals never count.
    Pure; docs/design/calls.md, 2.
    """
    attempts = []
    for event in events:
        kind = event.get("ev")
        if ((kind == "call.ended" and event.get("call") == chain.latest)
                or (kind == channel.ANSWERED and event.get("subject") == chain.subject)
                or (kind == "chain.settled" and event.get("call") == chain.root
                    and event.get("verdict") == "amend")):
            attempts = []
        elif (kind == "branch.rejected" and event.get("branch") == chain.branch
              and "queue_ts" not in event and event.get("step") == step and step in LAND_STEPS):
            attempts.append(event)
    return attempts


def _settle_restriction(chain: Chain, second: bool) -> str:
    """Limit the verdicts to ones that can resolve this hold without landing a refused tip."""
    if chain.reason == LAND_HOLD:
        return ("Amend is no longer an option, and land would land the tip fab land refused: user only."
                if second else "A land verdict would land the tip fab land just refused "
                "(refused again at rebase, paths or test): choose amend or user.")
    return "Amend is no longer an option: land or user only." if second else "Choose land, amend or user."


def _findings(refusals: tuple[str, ...]) -> str:
    """Quote each refusal once, with a bounded excerpt and an unreadable-report marker."""
    findings = []
    for run_id in refusals:
        heading = run_id
        if run_id.startswith("queue:"):
            rejection = json.loads(run_id.removeprefix("queue:"))
            if land_refusal(run_id):
                heading = f"`fab land` refused at {rejection['step']}"
                text = f"Step: {rejection['step']}\nLog:\n{rejection.get('log', '(missing)')}"
            else:
                heading = "Queue rejection"
                text = (f"Step: {rejection['step']}\n" + rejection.get("findings", "") +
                        f"\nLog: {rejection.get('log', '(missing)')}")
        else:
            try:
                text = (log.home() / "runs" / run_id / "report.md").read_text()
            except (OSError, UnicodeError):
                text = "(report missing)"
        findings.append(f"## {heading}\n\n" + "\n".join(text.splitlines()[:FINDINGS_LINES]))
    return "\n\n".join(findings) if findings else "(none)"


def _fold_review(event: dict, position: int, folded: dict, reviews: dict) -> None:
    """Attach review runs and their first complete ending to an existing root."""
    if event["ev"] == "branch.rejected" and all(key in event for key in ("branch", "step")):
        if "queue_ts" not in event and event["step"] in ("fetch", "push"):
            return
        refusal = "queue:" + json.dumps(event, sort_keys=True)
        for chain in folded.values():
            if chain["branch"] == event["branch"] and refusal not in chain["refusals"]:
                chain["reviews"].append({"position": position, "outcome": "failed"})
                chain["refusals"].append(refusal)
    elif event["ev"] == "run.started" and event.get("kind") == KIND:
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


def task_source(task: Task, events: Iterable[dict]) -> tuple[dict, Chain] | None:
    """The green skeleton tip a task started from, or may start from before landing.

    The first run's base fixes provenance across amendments and later rebase runs.
    Fresh tasks use the newest green check until the chain finishes successfully.
    """
    events = list(events)
    first = next((event for event in events if event.get("ev") == "run.started"
                  and event.get("task") == task.id), None)
    own = chains(events)
    for event in reversed(events):
        if (event.get("ev") != "call.checked" or event.get("outcome") != "green"
                or event.get("subject") != f"{task.draft}/{task.part}"
                or task.id not in event.get("tasks", ())):
            continue
        chain = own.get(event.get("root", event.get("call")))
        if chain is None or chain.role not in ("skeleton", "contract"):
            continue
        if first is not None:
            if first.get("base") == event.get("tip"):
                return event, chain
        elif not any(record.get("ev") == "call.finished" and record.get("call") in chain.calls
                     and record.get("outcome") == "done" for record in events):
            return event, chain
    return None


def task_rebase(task: Task, events: Iterable[dict], *, trunk: str = "main") -> dict | None:
    """Rebase context when a task's checked skeleton landed with an amended tip.

    A successful rebase run from origin/<trunk> after the finish consumes the amendment once.
    The shell adds the amendment's diff to these facts before launching the run.
    """
    events = list(events)
    source = task_source(task, events)
    if source is None:
        return None
    checked, chain = source
    finish = next((index for index in range(len(events) - 1, -1, -1)
                   if events[index].get("ev") == "call.finished"
                   and events[index].get("call") in chain.calls
                   and events[index].get("outcome") == "done"), None)
    if finish is None:
        return None
    tip = events[finish].get("tip")
    if not tip or tip == checked["tip"]:
        return None
    later = [event for event in events[finish + 1:] if event.get("ev") == "run.started"
             and event.get("task") == task.id]
    completed = {event.get("run") for event in events if event.get("ev") == "run.ended"
                 and event.get("outcome") == "done"}
    if any(event.get("kind") == "rebase" and event.get("base") == f"origin/{trunk}"
           and event.get("run") in completed for event in later):
        return None
    return {"step": "rebase", "old_tip": checked["tip"], "tip": tip,
            "findings": "The skeleton was amended before landing.", "skeleton": chain.root}
