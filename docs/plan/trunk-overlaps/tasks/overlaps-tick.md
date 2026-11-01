+++
id = "overlaps-tick"
part = "probe"
kind = "feature"
needs = ["overlaps-pure"]
files = ["fab/overlaps.py", "fab/tests/test_overlaps.py", "fab/dispatch.py", "fab/tests/test_dispatch.py"]
effort = "high"
minutes = 50
+++
# The probe's shell, its cache and its call from the tick

Read first: `docs/plan/trunk-overlaps/notes/common.md`,
`docs/plan/trunk-overlaps/notes/overlaps.md`,
`docs/plan/trunk-overlaps/notes/decisions.md` (4 and 5).

The request: "the overlap probe (`fab/overlaps.py` and its call from the
tick, the `trunks.overlap` event)". Design: `docs/design/fab.md`, 13.17,
"The overlap probe", all of it: "The shell is one function the tick calls
with its runner."

## What to build

- In `fab/overlaps.py`, on overlaps-pure's functions, one shell function
  the tick calls, taking the loaded plans with their checkouts, the log's
  records, whether every listed plan loaded, the runner and the log path,
  and returning the lines it prints. Per repository, every git command runs
  in the checkout of its first probed plan in draft-name order:
  - `git rev-parse --verify origin/main` and each probed trunk's
    `origin/<trunk>`; a trunk not on origin is not probed (and so forms no
    pair);
  - each trunk's catch-up merge, each pair's merge, as 13.17 gives them;
    a catch-up conflict or a failure skips that trunk's pairs this tick
    (they still count among this tick's pairs);
  - each pair's result logged as `trunks.overlap`, `reason` `probe`, when it
    is news; each failure printed, and logged as a note when news;
  - when every listed plan loaded, the pairs gone closed with `reason`
    `gone`.
- The cache, `FAB_HOME/overlaps.json` (`fab.log.home()`), written with
  `fab.atomic.write`: a trunk's tree keyed by main's sha and its tip, a
  pair's `files` and `more` keyed by main's sha and both tips; results
  only, never failures; a cached tree is dropped when a pair that used it
  fails. A missing or unreadable file is an empty cache. The format is
  yours; say it in the module's docstring.
- In `fab/dispatch.py`, `_round` (near line 891): after the
  `for plan, tasks, directory, checkout in loaded:` loop, and not with
  `only`, call it with `loaded` and `not any(action.kind == "load" for
  action in <the load actions>)`, and print its lines as the other steps
  print. A failure inside it (OSError, ValueError, `fab.sh.Failed` from the
  checkout) is printed and never stops the round.

## Acceptance

Tests in `fab/tests/test_overlaps.py` through the shell function with a
`FakeRunner` scripted for `rev-parse` and `merge-tree`:
- two overlapping trunks log one `trunks.overlap` with `drafts`, `tips`,
  `files`, `more` and `reason` `probe`; the same probe again logs nothing
  and runs no merge-tree (answered from the cache); a new tip runs it again;
- a trunk behind main is probed on its merged tree (the pair's command
  names the trees from the catch-up merges, `--merge-base=origin/main`);
- a catch-up conflict skips that trunk's pairs and logs nothing for them;
- a failing pair prints each tick, logs one note across two ticks, and
  drops the trees it used from the cache;
- two repositories: no cross-repository pair; each runs in its own
  checkout;
- a landed trunk closes its open pairs with `reason` `gone`; with a failed
  load, nothing is closed;
- a missing or corrupt `overlaps.json` costs only the merge-trees.

In `fab/tests/test_dispatch.py`, through `tick(...)`: two ready integration
plans probed once per round after their ticks; with `only`, no probe; the
existing tests pass unchanged (scripted runners that do not expect
merge-tree: a plan without a probed pair runs none).

## Pre-approved defaults

- The printed line for a logged result: `overlap <a> <b> <count>`, and for
  a closing one `overlap <a> <b> gone`.
- Existing tick tests that now meet an unexpected `rev-parse` may have the
  runner's default answer extended in their fixture, never their
  assertions changed.

## Report

Where the call sits in `_round`, the cache's format, and how many
merge-trees a tick with nothing moved runs (none).
