# Codex runs status

copied from fabrig 9a0594837 on 10-30; PATH still points at fabrig until handover

Codex-run and slots are copied together from fabrig 9a0594837. Slot helpers
and trim always resolve from the same canonical agents release root; there is
no fabrig fallback. The test suite copies sibling `tools/slots/lifetime.py`
into its private agents release. State and slot directories retain their
existing paths; central claims remain exclusively on hel8, and existing local
maintenance locks and holds continue at their original builder paths.
`--help` now succeeds without reading run storage or invoking slot helpers.

Agents' focused gate files are `test_codex_run.py`, `test_final.py` and
`test_stale.py`; the latter two also retain the bash suite's fixture entrypoints.
`test_codex_run_periodic.py` wraps the complete bash suite in a temporary
workspace. Its original guard requires CPU below 15 seconds and wall below
60 seconds; periodic classification does not relax either assertion.
Owner `ops` is recorded using `[files."path"]` rows in `tools/gate.toml`,
with selectors covering both launcher and slot-helper dependencies. The old
base still discovers periodic files by default. Landing is deferred until
rebasing onto the coordinator-supplied repaired gate SHA on main; verification
uses the repaired gate from `origin/deploy/gate-fix-1` in a private worktree.
The installation description below records fabrig's existing installation;
this copy adds no `tools/installed` row and performs no link handover.

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
