"""QA log records with complete defaults (docs/design/fab.md, 3; qa.md, 2)."""

from fab import log

# A fixed timestamp keeps fold tests independent of the clock.
STAMP = "2026-11-01T00:00:00.000Z"


def walk_started(walk: str, rung: str, *, draft: str = "ladder",
                 backend: str = "chatgpt-forgejo", edition: str = "edition", commit: str = "commit",
                 by: str = "walker", ts: str = STAMP) -> dict:
    """A walk.started record with its rung, edition and walked commit."""
    return log.record("walk.started", ts=ts, walk=walk, draft=draft, rung=rung,
                      backend=backend, edition=edition, commit=commit, by=by)


def walk_ended(walk: str, verdict: str, findings: tuple[str, ...] = (), *,
               reason: str = "walk complete", report: str = "report.md", ts: str = STAMP) -> dict:
    """A walk.ended record; findings is serialized as the log's list of ids."""
    return log.record("walk.ended", ts=ts, walk=walk, verdict=verdict, reason=reason,
                      report=report, findings=findings)


def finding_raised(finding: str, walk: str, rung: str, *, blocking: bool = False, again: str = "",
                   draft: str = "ladder", index: int = 1, backend: str = "chatgpt-forgejo",
                   commit: str = "commit", edition: str = "edition", kind: str = "qa",
                   title: str = "The story stalled", severity: str = "medium", area: str = "ctl",
                   reproduction: str = "Run the story", expected: str = "The story completes",
                   seen: str = "The story stalls", evidence: tuple[str, ...] = (),
                   ts: str = STAMP) -> dict:
    """A finding.raised record with every field, including an optional recurrence."""
    return log.record("finding.raised", ts=ts, finding=finding, walk=walk, rung=rung,
                      blocking=blocking, again=again, draft=draft, index=index, backend=backend,
                      commit=commit, edition=edition, kind=kind, title=title, severity=severity,
                      area=area, reproduction=reproduction, expected=expected, seen=seen, evidence=evidence)


def finding_merged(finding: str, into: str, *, by: str = "walk-1", reason: str = "Same cause",
                   ts: str = STAMP) -> dict:
    """A finding.merged record, attributed to a walk or a triage call."""
    return log.record("finding.merged", ts=ts, finding=finding, into=into, by=by, reason=reason)


def finding_triaged(finding: str, decision: str, *, call: str = "triage-1", owner: str = "",
                    reason: str = "Triage reason", question: str = "", into: str = "",
                    ts: str = STAMP) -> dict:
    """A finding.triaged record; unused fields remain present and empty."""
    return log.record("finding.triaged", ts=ts, finding=finding, call=call, decision=decision,
                      owner=owner, reason=reason, question=question, into=into)


def rung_passed(rung: str, *, draft: str = "ladder", walk: str = "walk-2",
                edition: str = "edition", commit: str = "main", ts: str = STAMP) -> dict:
    """A rung.passed record identifying the rerun and its unchanged edition."""
    return log.record("rung.passed", ts=ts, draft=draft, rung=rung, walk=walk,
                      edition=edition, commit=commit)
