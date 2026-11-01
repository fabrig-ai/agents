# integration status

2026-11-01. Contract: `docs/design/integration.md`. Split from `docs/design/fab.status.md`.

## Present

- **Drafts beside each other** (4, 11-01): built by fab's loop as plan
  `docs/plan/trunk-overlaps` (four tasks, landed 12:09-12:27Z): the overlap
  probe (`fab/overlaps.py`, its cache, its call after every plan ticks), the
  page's `overlaps` panel, and the cut brief's `Drafts beside this one`.
  Untried live: no integration plan with `ready` runs yet, so no
  `trunks.overlap` has been logged. Retired by hand: its retire call's brief
  exceeded `BRIEF_LIMIT` (fab.md and fab.status.md, ~216k characters before
  the split).
- **The overlap probe's paper cuts** (4, 11-01, from its acceptance review):
  built by plan `docs/plan/paper-cuts` (landed 13:13-13:19Z). The cache
  holds `trees`, `pairs` and `conflicts` (a conflicting catch-up is not
  merged again while nothing moved), reads the first format without
  `conflicts`, keeps only the keys a probe looked up or stored, drops a
  tree a failed pair used, and is written only when it changed
  (`overlaps-cache`, 048cabd). `fab.overlaps.well_formed` is the one rule
  for a `trunks.overlap` record; `is_news`, `open_pairs` and through it
  `gone_pairs` and the page's `_public_overlaps` read only well-formed
  records, and `fab/serve.py` did not change (`overlaps-records`,
  1f8666b). `fab/tests/test_overlaps_git.py` runs the probe on real git
  (`git_pair()`): two trunks off main with a conflicting path holding a
  space, main moved ahead, the path logged; a planted cached tree missing
  from the object store is a failure, not an overlap (`overlaps-git`,
  08afbf7). The checkout wording of 4 was matched to the code with the
  design.

## Gaps and departures

- **An integration trunk through the queue is untried live:** the catch-up
  with main (before a check and along the way), catch-up repairs, the
  re-check after a rejection and the stops are tested against fakes and real
  git only; no plan has yet run with `ready = true`.
- **The flow of a real run (3) is on main, not run live yet**
  (10-31): the options with the run's defaults (agents-rebuild names the
  old flow), the trunk throughout, the tick's merges with the baseline
  recount and the trunk's ratchet, the end check (`fab check`), its
  repairs and the ready, reviews off, answers at once, the flow kept at
  the builders' places, and the run-derived texts (`cut-direct.md`,
  `fabrig-integration.md`). Simulated against codex-kit
  (`coord/fab-replay/simulation.md`), then run live once (10-31,
  15:32-16:49Z, hetzner11 and hetzner12): `component-kit/integration` green
  on the first end check at T+76.1 (codex-kit 54.75), never landed
  (`coord/fab-replay/report.md`). Five bugs found live are fixed on main. At the user's word
  (10-31, after the replay) three changes are being built: light merges
  without gates and the `files` gate removed (`light-merges`), the cut's
  early release of specs (`cut-early`) and the run's own texts
  (`run-texts`);
  `cut-run.md` allows designer subagents where the design is too wide for
  one writer (the user, 10-31: the playground replay's cut started four,
  then hit the call's 40-minute limit before they ended; the limit is now
  60 minutes); a park at the run limit goes to the answerer, never the
  foreman, and its answer grants fresh runs (the playground replay's loop);
  a repair's question queues, answer calls see and record it, and its answer
  folds into its body; after the playground replay, the answerer leaves what
  is not the task's, reruns start from their pushed branch, the cut writes
  plan.md and its report early, and a full builder hands a start on; early
  starts and checks along the way (3) are built (not run live yet);
  a run may leave what is not its own (3: the implementer's allowed
  edits and `## Left`, the foreman's `Accept:`, the cut's contracts note;
  not run live yet);
  and, with fabrig's `agents/` gone from its main
  (`2c39875fd2`), `cut-run.md` and `fabrig-run.md` no longer name it;
  what is left to match the run is in section 5. The replay ticked from
  its own install on hel8 (`FAB_HOME/replay-install`, a local hosts.toml),
  as a background command of a session, not a unit.
