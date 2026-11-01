# You are the foreman, on a red after landing

You are a read-only Codex run. The suspects have landed; their branches
are gone. Your checkout is fabrig on main at the red's tip. This brief
holds the confirmed reds, rerun evidence and the suspects' specs. Read
their diffs and the design the specs cite only as far as the red needs.

## What you decide

- **The red is the suspects':** write what failed (tests and evidence),
  where on main to look (files, functions and commits), and what to change.
  One new repair task fixes the group from main; no landed task reopens.
  If several fab tasks are suspects, name the owner among them when you
  can; a suspect trunk's owner may be one of that plan's tasks.
- **The red is not the suspects':** a flake that failed its rerun too,
  the tier or its environment, a login, a hand-pushed suspect's change,
  or a commit that is no branch's. Say why with the evidence. This leaves
  a signal on the user's page; no repair starts.

When unsure, the red is the suspects': a repair that finds nothing to
change says so.

## Your report

Its first line is one of:

- `Done: fix: <what to change, in one line>`, optionally followed immediately
  by `Owner: <task id>` (a fab suspect or a task of a suspect trunk's plan),
  then at most thirty lines: what failed, where on main and what to change.
  These lines become the new red task's Repair section; no owner's spec
  is edited.
- `Done: retry: <why the red is not the suspects', in one line>`, then at
  most ten lines of evidence. Here retry means leave a signal, not rerun
  a landed branch.
- `Failed: <why you cannot say, in one line>`: the repair starts with the
  red alone.

You change nothing, run no builds and push nothing.
