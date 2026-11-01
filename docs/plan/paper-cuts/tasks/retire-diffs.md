+++
id = "retire-diffs"
part = "bounded-retire"
kind = "interface"
needs = []
files = ["fab/designer.py", "fab/roles/retire.md", "fab/tests/test_designer.py"]
effort = "high"
minutes = 55
+++
# Retire's brief bounded

Read first: `docs/plan/paper-cuts/notes/common.md`,
`docs/plan/paper-cuts/notes/decisions.md` (2 and 3).

The request (1): "the brief quotes each changed design as the shorter of
its diff since the plan started and its text, fills its section only up to
`BRIEF_LIMIT` less the other sections and lists the designs that do not
fit (`fab.designer.retire_brief`, a new helper beside `changed_designs`,
which keeps returning paths); the retire role text (`fab/roles/retire.md`)
and `retire_brief`'s docstring say so." Design: `docs/design/calls.md`,
3, "retire", all of it.

## What to build

- `fab/designer.py`, beside `changed_designs` (near line 103): the plan's
  start (the oldest commit adding plan.toml, as `changed_designs` finds it
  now; one copy, which `changed_designs` then uses) and, for a design, its
  diff since the start: `git diff <start>^ <rev> -- <design> <status>`, or
  against the empty tree when the start has no parent (`git hash-object -t
  tree --stdin` with empty input gives its id in either hash format). One
  public helper or two; their names are yours. `changed_designs` keeps its
  signature and returns paths, as now.
- `retire_brief` (near line 358) gains keywords `rev: str = "origin/main"`
  and `sh: Runner = run`. Its section `Designs changed since the plan
  started` quotes each design of `changed`, in path order, as the shorter
  of (a) its diff and (b) its text and status file at rev (`git show
  <rev>:<path>`; `(removed)` and `(no status file)` when absent at rev),
  each quote headed `## <path>` and saying which of the two it is. The
  budget: `BRIEF_LIMIT` less the compiled text of every other section
  (headings and separators included, as `fab.calls._brief` joins them)
  less one list line per changed design (decision 3). A design whose quote
  does not fit is skipped and filling goes on; each skipped design is
  listed as `- <path> (<n> lines, diff <m> lines): read it in your
  worktree`, `<n>` its line count at rev (0 when removed). `(none)` when
  `changed` is empty, as now. Its docstring says all this and drops "a plan
  that changed more than the limit holds is retired by hand".
- `_compile` (near line 516) passes `sh=run` (and the default rev) to
  `retire_brief`.
- `fab/roles/retire.md`, "What you write" or a line before it: the changed
  designs come as diffs since the plan started or as their text, and those
  that did not fit as a list; read a design whole in your worktree when you
  need more than the brief gives.

## Acceptance

Tests in `fab/tests/test_designer.py`, in a real temporary repository as
the `changed_designs` tests build (near line 172):
- a large design with a small change since the start is quoted as its
  diff; a small design created since the start is quoted as its text (or
  whichever is shorter, asserted from the lengths); a design removed since
  the start says `(removed)`;
- a plan whose start has no parent diffs against the empty tree;
- with `BRIEF_LIMIT` patched small, a design too large to fit is listed
  with its line and diff counts, a later smaller one is still quoted, and
  the brief is within the limit; a brief whose other sections alone pass
  the limit still raises ValueError;
- `changed_designs` returns the same paths as before (its tests pass
  unchanged); `fab call retire --brief-only` (`designer.main`) still prints
  the brief.

## Pre-approved defaults

- Existing retire tests (near lines 389 and 591) that build `retire_brief`
  on a directory that is not a repository may pass a `FakeRunner` or move
  onto the real repository; keep what they assert about sections and
  order.
- A diff quoted in a fenced block (```` ```diff ````) is fine; so is plain
  text after the heading. The list lines go after the quotes, under a line
  saying they did not fit.

## Report

The helper's name and signature, the quote's format, and the size of the
section for a design with a one-line change in a 3000-line file.
