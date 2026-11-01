# hel8-units: the plan

One direct part, `dispatcher-units` (`docs/design/machines.md`, 4), of the
request's two tasks: `status-issues` (the installer, its texts, `fab serve
--install` with the HEAD watch, `fab issues --install`), then
`logins-report` (`fab logins check --install`, `fab report daily
--install` and `fab report daily` with no plan dir), which needs it. Specs
in `tasks/`, the standing rules in `notes/common.md`, the decisions and the
critical path in `notes/decisions.md`.

The designs are already written; no task edits `docs/design/`. The status
line (`docs/design/machines.status.md`, "The dispatcher's own units") is the
retire call's.

## Overlaps with drafts beside this one

- `smith-live/kind` changes `fab/logins.py` and `fab/tests/test_logins.py`;
  `logins-report` changes the same files. It could not be avoided: `fab
  logins check --install` is parsed in `fab.logins.main`. The two touch
  different functions (`Kind` and `KINDS` there, `main` here), and
  `logins-report` comes second in this plan, so whichever lands later
  rebases cleanly over the other.
- `dogfood-faults` (`fab/dispatch.py`, `fab/run.py` and their tests) and
  `answer-findings`: no shared file.
