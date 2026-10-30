+++
id = "digest"
part = "gates"
kind = "feature"
needs = []
files = ["fab/digest.py", "fab/tests/test_digest.py"]
effort = "high"
minutes = 30
+++
# The structure digest's core: items, long functions, repeated blocks

Fill the bodies of `fab/digest.py` as their docstrings say, every one but
`render`, `changes` and `archive`: `classify`, `outside`, `items`,
`added_lines`, `functions`, `long_functions`, `clones` and `build`. Leave
those three raising NotImplementedError; `digest-render` fills them. Design:
`docs/design/fab.md`, section 12. `items` reuses `fab.calls.inventory` as is.

## Acceptance

- `fab/tests/test_digest.py` covers, on small trees written into a temporary
  directory (`<root>/fab/*.py`), no git:
  - `classify` for a module, a test under `fab/tests/`, a `test_` file
    elsewhere, a `.md` under `fab/roles/`, a path under `docs/`, `bin/fab`;
  - `outside` with an exact path, a `*` glob that must not cross `/`, a
    `**` glob, and no files at all;
  - `items`: an added function, a removed class, a changed signature, a
    method added to an existing class, a docstring-only change (not listed),
    a tree without `fab/`;
  - `added_lines` for an insert, a replace, a deletion only (empty) and a
    new file;
  - `functions` with a nested function and a method (qualified names,
    decorators excluded from the start);
  - `long_functions`: a new 61-line function listed, a 60-line one not, an
    untouched long one not, a long one with one changed line listed;
  - `clones`: an 8-line block copied into a changed file from another module
    (one Clone, merged across its windows), a 7-line copy not, an overlapping
    repeat of one line not, imports and comments ignored, a copy wholly in
    unchanged lines not;
  - `build` end to end on a base and a tip tree: every field, a new module
    in `modules`, a path outside the task's files.
- `bin/fab test` passes; `test_digest.py` takes under a second.

## Options, settled up front

- `difflib` and `ast` from the standard library; no third-party diff.
- A window's key is the tuple of its kept lines' stripped texts; an index of
  every window by key, built once per call, finds the matches.
- Production modules only feed `long` and `clones`; tests and docs are
  counted in `changes` and nothing else.
