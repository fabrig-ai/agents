# Codex runs status

Provisional, 2026-10-28. `tools/codex-run/design.md` is implemented by
`codex-run`, `final.py`, `test-codex-run`, `test-final.py`, `test-stale.py`,
`tools/install`, `tools/installed` and
`tools/test_install.py`. No known implementation departures.

Fleet installation is pending coordinator review. The agents repository's
copies remain in place. Run and owner storage remain under `~/src/rust/tmp`
by default, preserving resume access and accounting; migration is deferred.

Standard-library validators, lease supervisors, subreaper bootstrap and finality
run without Python site initialization. Finality imports liveness, JSON and
publication dependencies at their use sites after the preceding checks.

Recipient-owned start records, explicit `final` declarations and best-effort
end notifications are implemented (`tools/codex-run/design.md`, 3.1–3.2), with
private service fixtures and atomic-publication tests. Completion and stop
never infer finality. Identical declarations preserve marker timestamps and
do not replay end notifications. New UTC times retain microseconds and prove
ordering against completion nanoseconds and the current clock; repeats validate
that same ordering without modifying existing evidence. Deployment discovery
must adopt durable final
markers with missed notifications and reconcile older registry owners; no
backfill runs here. Retention, indefinite keeps for resumable/uncertain tasks
and deletion remain the reaper owner's work. Persistent owner lifecycle remains
MC's responsibility.

Stale filters completed runs without `post-failed` before metadata age checks,
including age-stat diagnostics. Unfinished and refused-post candidates retain
their notification checks (`tools/codex-run/design.md`, 3).
