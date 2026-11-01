# Cutting a direct plan: the lead's way

This plan is cut as a lead cuts a change by hand: every part is direct, and
you write every task spec now. Nothing starts until your branch is merged,
so you are on the critical path of every implementer: be quick, and write
thin specs rather than explore at length. These rules
come before the ones above where they differ.

- **Read** the drafts and inputs in this brief, then only the code you
  must name in the specs. Survey the code in parallel: start one Explore
  subagent per family of sites (for example: the call sites a contract
  replaces, the private copies of a primitive, the test surfaces) while
  you write the contract tasks, and use their findings for the site tasks.
- **Decide** what the draft leaves to the implementer's lead: pick the
  recommended option of each question, record the choice and why in
  `notes/decisions.md`, and bind it in the specs. A question the brief or
  the kickoff tells the lead to settle (pick the recommended option) is
  yours: decide it, never a `[[question]]`. Only what is the user's and
  that no source settles (budgets, machines) is one, and no task waits for
  it: nothing answers it during the run.
- **Contract tasks first,** small: the public surface with its
  signatures binding, its bodies and tests. Every task that only uses a
  contract names it in `needs` and starts from the merged contract. If one
  task would block more than three others, split it so they start sooner.
- **One crate family per site task,** each owning disjoint files. Two
  tasks that must change the same files are ordered by `needs`.
- **Keep the critical path short.** The longest chain of `needs`, counted in
  implementer-minutes, sets the run's length: write it down in
  `notes/decisions.md` and keep it near the longest single task plus its
  contract. A task waits only for the tasks whose code it builds on or
  whose files it shares, never for a whole part; a task that would wait for
  more than three others is split by family so most of it starts early.
- **Counted forms:** when the draft sets counts that may only fall, a first
  task adds them to the tree's `scripts/old_forms.py` ratchet, every other
  spec lists it in `needs` (so no branch predates the counts it must not
  raise; it is a minutes-long task), and
  every task lowers `scripts/old-forms.txt` with `--write`. The tick
  recounts that file when merges meet on it.
- **A task's kind:** `interface` when it changes or removes the signature
  of an existing public item (a parameter added to a public function
  counts), since the shape gate refuses that in any other kind
  (`docs/design/gates.md`, 2); `feature` when it only adds. Two of the
  findings-loop cut's tasks were refused for it (11-01).
- **Shared notes** go once in the plan's `notes/`: `common.md` (the
  standing rules every implementer follows: scope, the checks, the code
  rules, commits, the report) and one note per family of tasks (what every
  task of the family does the same way, the pre-approved defaults for what
  they will meet). Each spec says which notes to read first.
- **A spec** holds: the goal, in the draft's words and section; the
  sites, by path and approximate line; what it owns and may change (its
  `files`); the pre-approved defaults for the questions it is likely to
  hit (a count that also matches the shared item itself, a site whose
  move would change what a test pins); its checks; and what its report
  must say. Its base is main's tip once its needs have landed.
- **Your branch** lands on main once reviewed (this repository through
  `bin/fab land`, fabrig through its queue).
