"""Hand walks, their brief editions and result intake (docs/design/fab.md, 13.15)."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import sys
import tomllib
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path

from fab import atomic, channel, findings, log, wake
from fab.plan import Plan, Rung, load_plan
from fab.sh import Failed, Runner, run


LOCK = "qa.lock"  # under FAB_HOME: serializes walk and finding id allocation and intake
WALKS = "walks"  # under FAB_HOME: compiled briefs and walker artifacts
TITLE_LIMIT = 200  # characters in a finding title
TEXT_LIMIT = 4000  # characters in reproduction, expected or seen
FINDINGS_LIMIT = 30  # findings in one walk result


@dataclass(frozen=True)
class _Finding:
    """One walker's finding before it receives a global id."""

    same: str
    evidence: tuple[str, ...]
    title: str
    severity: str
    area: str
    blocking: bool
    reproduction: str
    expected: str
    seen: str


@dataclass(frozen=True)
class Result:
    """A validated result.toml, without log or machine state (docs/design/fab.md, 13.15)."""

    verdict: str
    reason: str
    findings: tuple[_Finding, ...]


def edition(files: Sequence[tuple[str, str]]) -> str:
    """First 12 hex of SHA-256 over ordered UTF-8 paths and texts, each NUL-terminated.
    Paths are spelled as in plan.toml. Pure; docs/design/fab.md, 13.15.
    """
    digest = hashlib.sha256()
    for path, text in files:
        digest.update(path.encode("utf-8") + b"\0")
        digest.update(text.encode("utf-8") + b"\0")
    return digest.hexdigest()[:12]


def editions(plan: Plan, plan_dir: Path, *, sh: Runner = run) -> dict[str, str]:
    """Each rung's edition in plan order, reading briefs at the checkout's origin/main.
    Find the checkout with git rev-parse, then git show each checkout-relative brief.
    Raise ValueError naming the rung and file when git show fails (docs/design/fab.md, 13.15).
    """
    return {identifier: edition(files) for identifier, files in
            _briefs(plan_dir, plan.rungs.values(), sh=sh).items()}


def _briefs(plan_dir: Path, rungs: Iterable[Rung], *, sh: Runner) -> dict[str, list[tuple[str, str]]]:
    """Read ordered brief paths and texts at origin/main for editions and walk briefs."""
    rungs = list(rungs)
    if not rungs:
        return {}
    directory = plan_dir.resolve()
    root = Path(sh(["git", "rev-parse", "--show-toplevel"],
                   cwd=str(directory), check=True).out.strip()).resolve()
    relative = directory.relative_to(root)
    texts = {}
    for rung in rungs:
        files = []
        for path in rung.brief:
            shown = sh(["git", "show", f"origin/main:{(relative / path).as_posix()}"],
                       cwd=str(root), check=False)
            if not shown.ok:
                raise ValueError(f"rung {rung.id}: cannot read brief {path} at origin/main")
            files.append((path, shown.out))
        texts[rung.id] = files
    return texts


def parse(text: str) -> Result:
    """Parse result.toml, refusing invalid fields and limits by name; pure (docs/design/fab.md, 13.15).

    A pass cannot have a blocking finding; a fail must have a finding. The log-aware
    check that same names a finding of this plan belongs to result.
    """
    try:
        fields = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise ValueError(f"result.toml: {error}") from error
    verdict = fields.get("verdict")
    if verdict not in findings.VERDICTS:
        raise ValueError("verdict: expected pass, fail or void")
    reason = _string(fields, "reason")
    entries = fields.get("finding", [])
    if not isinstance(entries, list) or not all(isinstance(entry, dict) for entry in entries):
        raise ValueError("finding: expected an array of tables")
    if len(entries) > FINDINGS_LIMIT:
        raise ValueError(f"finding: more than {FINDINGS_LIMIT} findings")
    parsed = []
    for index, entry in enumerate(entries, 1):
        prefix = f"finding[{index}]"
        strings = {key: _string(entry, key, prefix) for key in (
            "title", "severity", "area", "reproduction", "expected", "seen")}
        if strings["severity"] not in findings.SEVERITIES:
            raise ValueError(f"{prefix}.severity: expected low, medium or high")
        for key, limit in (("title", TITLE_LIMIT), ("reproduction", TEXT_LIMIT),
                           ("expected", TEXT_LIMIT), ("seen", TEXT_LIMIT)):
            if len(strings[key]) > limit:
                raise ValueError(f"{prefix}.{key}: more than {limit} characters")
        blocking = entry.get("blocking")
        if type(blocking) is not bool:
            raise ValueError(f"{prefix}.blocking: expected a boolean")
        evidence = entry.get("evidence")
        if not isinstance(evidence, list) or not all(isinstance(path, str) for path in evidence):
            raise ValueError(f"{prefix}.evidence: expected a list of strings")
        same = _string({"same": entry.get("same", "")}, "same", prefix)
        parsed.append(_Finding(**strings, blocking=blocking, evidence=tuple(evidence), same=same))
    if verdict == "pass" and any(entry.blocking for entry in parsed):
        raise ValueError("blocking: a pass cannot have a blocking finding")
    if verdict == "fail" and not parsed:
        raise ValueError("finding: a fail must have at least one finding")
    return Result(verdict, reason, tuple(parsed))


def _string(fields: dict, key: str, prefix: str = "") -> str:
    """Read a required string, naming its field on refusal."""
    value = fields.get(key)
    if not isinstance(value, str):
        raise ValueError(f"{prefix + '.' if prefix else ''}{key}: expected a string")
    return value


def brief_text(texts: Sequence[str], walk_dir: Path,
               open_findings: Iterable[findings.Finding]) -> str:
    """Brief texts followed by reporting instructions and open findings; pure (docs/design/fab.md, 13.15).

    Reporting mechanics are outside the brief edition. Each finding occupies one line
    with its id, state, rung, area and title, so a walker can report same by id.
    """
    reporting = f'''# Reporting to fab

Write the prose report to `{walk_dir / "report.md"}` and the structured result to
`{walk_dir / "result.toml"}`. Submit with `fab qa result {walk_dir.name}`.
Use verdict pass, fail or void; fail requires a finding, pass permits no blocking finding.
Reason says where the walk broke, or why a void story was not walked.
Use one [[finding]] per finding (at most {FINDINGS_LIMIT}); omit the tables when none.
Titles are at most {TITLE_LIMIT} characters; reproduction, expected and seen at most
{TEXT_LIMIT} each. Evidence lists paths on the walk's machine. Set same to an open
finding's id below when it is the same cause, otherwise "".

```toml
verdict = "fail"
reason = "Where the story broke"

[[finding]]
title = "What failed"
severity = "medium" # low, medium or high
area = "Component"
blocking = true
reproduction = "Commands from a fresh box, in order"
expected = "What should happen"
seen = "What happened"
evidence = []
same = ""
```
'''
    lines = [" ".join(f"{entry.id} {entry.state} {entry.rung} {entry.area} {entry.title}".splitlines())
             for entry in open_findings]
    return "\n\n".join([*texts, reporting, "# Open findings\n\n" + "\n".join(lines)]) + "\n"


@contextmanager
def _locked() -> Iterator[None]:
    """Hold the global QA lock until all ids and their records are durable."""
    path = log.home() / LOCK
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def walk(plan_dir: Path, rung: str, commit: str, *, by: str = "session", sh: Runner = run,
         log_path: Path | None = None) -> tuple[str, Path]:
    """Fetch and compile a main-branch brief, log its walk and return id and path (docs/design/fab.md, 13.15).

    Refuse unknown rungs or a commit missing any landed repair of this rung, including
    targets of merged findings. Hold qa.lock from reading ids through walk.started.
    """
    plan_dir = plan_dir.resolve()
    plan = load_plan(plan_dir / "plan.toml")
    if rung not in plan.rungs:
        raise ValueError(f"rung: unknown rung {rung!r}")
    sh(["git", "fetch", "origin"], cwd=str(plan_dir), check=True)
    files = _briefs(plan_dir, (plan.rungs[rung],), sh=sh)[rung]
    with _locked():
        events = log.read(log_path)
        found = {key: entry for key, entry in findings.findings(events).items() if entry.draft == plan.draft}
        checked = set()
        for entry in found.values():
            if entry.rung != rung:
                continue
            target = found[findings.target(found, entry.id)]
            if not target.landed or target.id in checked:
                continue
            checked.add(target.id)
            contains = sh(["git", "merge-base", "--is-ancestor", target.landed, commit],
                          cwd=str(log.home() / "repos/fabrig"), check=False)
            if not contains.ok:
                raise ValueError(f"commit: {commit} is missing landed repair {target.id} at {target.landed}")
        identifier = f"walk-{1 + sum(event.get('ev') == 'walk.started' for event in events)}"
        path = log.home() / WALKS / identifier / "brief.md"
        opened = [entry for entry in found.values() if findings.mergeable(entry) or entry.holds
                  or entry.state in ("landed", "unfixed")]
        atomic.write(path, brief_text([text for _, text in files], path.parent, opened))
        log.append("walk.started", path=log_path, walk=identifier, draft=plan.draft,
                   rung=rung, backend=plan.rungs[rung].backend, edition=edition(files), commit=commit, by=by)
    return identifier, path


def result(walk_id: str, directory: Path | None = None, *, log_path: Path | None = None) -> list[dict]:
    """Import a walk's artifacts; return newly appended records, ending with walk.ended (docs/design/fab.md, 13.15).

    Validate everything before writing. Hold qa.lock across counting ids and appending;
    retry an interrupted intake by reusing raised indices and skipping logged merges.
    Unknown or ended walks are refused. A missing report is allowed and logged as "".
    """
    with _locked():
        events = log.read(log_path)
        started = next((event for event in events if event.get("ev") == "walk.started"
                        and event.get("walk") == walk_id), None)
        if started is None:
            raise ValueError(f"walk: unknown walk {walk_id!r}")
        if any(event.get("ev") == "walk.ended" and event.get("walk") == walk_id for event in events):
            raise ValueError(f"walk: {walk_id} has ended")
        destination = log.home() / WALKS / walk_id
        source = directory if directory is not None else destination
        text = (source / "result.toml").read_text(encoding="utf-8")
        parsed = parse(text)
        found = {key: entry for key, entry in findings.findings(events).items()
                 if entry.draft == started["draft"]}
        targets = []
        for entry in parsed.findings:
            if entry.same and entry.same not in found:
                raise ValueError(f"same: {entry.same!r} names no finding of plan {started['draft']}")
            targets.append(found[findings.target(found, entry.same)] if entry.same else None)
        try:
            report = (source / "report.md").read_text(encoding="utf-8")
        except FileNotFoundError:
            report = None
        atomic.write(destination / "result.toml", text)
        if report is not None:
            atomic.write(destination / "report.md", report)
        raised = {event["index"]: event for event in events if event.get("ev") == "finding.raised"
                  and event.get("walk") == walk_id}
        number = sum(event.get("ev") == "finding.raised" for event in events)
        appended, identifiers = [], []
        for index, (entry, target) in enumerate(zip(parsed.findings, targets), 1):
            if index not in raised:
                number += 1
                fields = asdict(entry)
                fields.pop("same")
                appended.append(log.append(
                    "finding.raised", path=log_path, finding=f"finding-{number}",
                    **{key: started[key] for key in ("draft", "walk", "rung", "backend", "commit", "edition")},
                    index=index, kind="qa", **fields,
                    again=target.id if target is not None and not findings.mergeable(target) else ""))
                raised[index] = appended[-1]
            identifiers.append(raised[index]["finding"])
        merged = {event.get("finding") for event in events
                  if event.get("ev") == "finding.merged" and event.get("by") == walk_id}
        for identifier, target in zip(identifiers, targets):
            if target is not None and findings.mergeable(target) and identifier not in merged:
                appended.append(log.append("finding.merged", path=log_path, finding=identifier,
                                           into=target.id, by=walk_id, reason="same finding reported by walker"))
        appended.append(log.append("walk.ended", path=log_path, walk=walk_id, verdict=parsed.verdict,
                                   reason=parsed.reason, report=str(destination / "report.md")
                                   if report is not None else "", findings=identifiers))
        wake.want(f"qa {walk_id}", path=wake.want_path(log_path))
        return appended


def main(argv: list[str]) -> int:
    """Start a hand walk, ingest its result or print each rung's state (docs/design/fab.md, 13.15).

    fab qa walk PLAN_DIR RUNG --commit SHA [--by WHO]; fab qa result WALK [DIR];
    fab qa rungs [PLAN_DIR...]. A refusal prints its reason and returns 2.
    """
    parser = argparse.ArgumentParser(prog="fab qa", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    starting = commands.add_parser("walk")
    starting.add_argument("plan", type=Path)
    starting.add_argument("rung")
    starting.add_argument("--commit", required=True)
    starting.add_argument("--by", default="session")
    ending = commands.add_parser("result")
    ending.add_argument("walk")
    ending.add_argument("directory", nargs="?", type=Path)
    commands.add_parser("rungs").add_argument("plans", nargs="*", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "walk":
            identifier, path = walk(args.plan, args.rung, args.commit, by=args.by, sh=run)
            print(identifier)
            print(path)
        elif args.command == "result":
            result(args.walk, args.directory)
        else:
            events = log.read()
            for directory in args.plans or channel.plan_dirs():
                plan = load_plan(directory / "plan.toml")
                for state in findings.rungs(plan, events, editions(plan, directory, sh=run), log.now()):
                    print(findings.line(state))
        return 0
    except (OSError, ValueError, Failed) as error:
        print(f"fab qa: {error}", file=sys.stderr)
        return 2
