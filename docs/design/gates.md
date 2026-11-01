# fab: gates and the structure review

2026-11-01, split from `docs/design/fab.md` (its section 6 maps the old
section numbers). Status: `docs/design/gates.status.md`. Shared: the
overview, the event log and the tests are `docs/design/fab.md`'s.

## 1. In one page

- **Code gates run on every branch** (files, size, shape, names, docs, ratchets), from the digest of what the branch changes.
- **The structure review** reads what landed on a cadence and proposes consolidation tasks and taste pairs.

## 2. Gates and the structure review

From the user's execution model: quality is checked by code on every branch,
and Claude reads the code's structure in batches, never on the landing path.

- **The digest** of a branch (`fab/digest.py`) is what a reviewer needs
  without reading the code: the public items it adds, removes or changes
  (from `fab.calls.inventory` on its base and its tip), new modules, its
  changed paths split into production, tests and docs with their lines, the
  paths outside its task's `files`, new or changed functions longer than 60
  lines, and blocks of 8 lines repeated from elsewhere in the package. The
  base is the tip's merge base with main; both trees are `git archive`s of
  `fab/`. It is deterministic Markdown of at most 8,000 characters, written
  to `FAB_HOME/digests/<run>.md` when the tick gates the branch.
- **The gates** (`fab/gates.py`, not fabrig's `fab/gate.py`) are pure checks
  over the digest and the task. The tick runs them, in `fab land`'s clone and
  under its lock, before it lands a task's branch of this repository:
  - `shape`: no signature the base has is changed or removed, unless the
    task's kind is `interface` or `migration`;
  - `size`: no function the branch adds, or makes longer, is over 60 lines
    (a ratchet: touching an old long function without growing it passes);
  - `names`: no new public name or module holds a word from the banned list
    in `fab/taste.md`;
  - `docs`: every new public function, class and method has a docstring;
  - `clones`: no block of 8 lines (blank lines, comments and imports left
    out) touched by the branch also stands elsewhere in the package.
  `size` and `clones` read production modules only. A failed gate logs
  `branch.rejected` with step `gate:<the first failed gate>`, log the
  digest's path, and `findings`, the findings as text; a tip whose Python
  does not parse is step `gate:parse`. The repair run's brief quotes the
  findings (landing.md 2). A gating that cannot run (git fails) is a failed
  action and the branch waits; it never lands ungated. The first gates read
  Python (this repository); fabrig's, over Rust and its public API, come
  later.
- **A skeleton or contract call's tip is gated too,** before its tasks may
  start from it (the optimistic start, integration.md 2): the tick screens
  the tip with the gates (this repository) or the Rust gates (fabrig) as a
  task of kind `interface` owning `**`, and runs the tests (`bin/fab test`
  in a detached worktree; fabrig: `fab precheck` in an idle slot). Its
  `call.checked` (call, root, subject, branch, tip, outcome `green` or
  `red`, and when green the part's task ids, specs and paths, `findings`)
  pins the tip and the specs together; an infra failure logs nothing and
  the next tick retries. Each done call of the chain, root and amends, is
  checked. Cut, answer, review, decision and retire calls' branches are
  not gated.
- **The taste file,** `fab/taste.md`, holds the banned names and pairs of
  good and bad code from this repository, each with one line on why. It is
  added to every implementer's brief after the role text.
- **The structure review** is a Claude call, role `review`
  (`fab/roles/reviewer.md`, subject `<draft>/review`), when ten tasks have
  landed since the last review call started or four hours have passed since
  then with any landed. A failed review counts as the last one, so it waits
  for the next threshold. Its brief is the digests of the branches landed
  since the last review that ended done, the taste file, the inventory and
  the designs those branches cite; it reads full code only for what the
  digests flag and a sample. It writes consolidation task specs (merges,
  renames, splits; kind `interface` when a signature changes; each marked
  `consolidation = true`) into the plan and new pairs into the taste file, on its branch, which lands as a
  skeleton call's does. It never holds up a landing.
- **A question from a call parks its subject:** a skeleton, answer or
  review call that ends with a question starts no further call for that
  subject until `call.answered` names it (channel.md 2), or a later call of the
  subject ends done. An answer call's subject is its draft.

## 3. Later

- fabrig's api gate, the public API against the skeleton (rustdoc JSON);
  names, docs and clones over Rust (integration.md 2 has the minimal gates).
- Gates on review calls' branches.
