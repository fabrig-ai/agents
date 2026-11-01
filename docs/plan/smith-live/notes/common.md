# Every smith-live task

The standing rules of this plan's implementers. Read this, then your spec.

## Scope

- The request is `docs/plan/smith-live/inputs/request.md`. The shelf's design is
  `docs/design/machines.md`, section 3; its code is `fab/logins.py`.
- Change only your spec's `files`. A file you must touch outside them is a `Question:`.
- Never read, print or copy a credential. Tests use dummy files in `tmp_home()` and fake hosts.
  The existing tests' fake `ssh` (`fab/tests/test_logins.py`) runs commands locally under a fake
  HOME.

## Code

- Python 3.13 standard library only. Commands go through the injected runner, as `fab/logins.py`
  does now.
- Match the surrounding code and `fab/taste.md`; functions stay within the gates' 60-line cap.

## Tests

- Every behaviour your spec's acceptance names has a test in `fab/tests/test_logins.py`.
- Checks before you hand over: `bin/fab test` green within its 30 s budget, and
  `bin/fab status docs/plan/smith-live` showing no plan problems.

## Commits and the report

- One commit, its message saying why, ending with the trailer your run's brief gives.
- Your report's first line is `Done: <what landed, one line>`, `Question: ...`, `Infra: ...` or
  `Failed: ...`.
