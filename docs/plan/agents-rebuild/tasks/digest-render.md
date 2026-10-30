+++
id = "digest-render"
part = "gates"
kind = "feature"
needs = ["digest"]
files = ["fab/digest.py", "fab/tests/test_digest.py"]
effort = "medium"
minutes = 20
+++
# The digest as Markdown, and its two git commands

Fill `render`, `changes` and `archive` in `fab/digest.py` as their
docstrings say. Design: `docs/design/fab.md`, section 12.

## Acceptance

- `fab/tests/test_digest.py` adds:
  - `render` of a hand-built Digest: the exact text for a small one (every
    section, `- none` for an empty one); LIST_CAP's `- ... and k more`;
    LINE_CAP's cut; a digest past DIGEST_LIMIT cut at a whole line with the
    cut line, the result within the limit; two renders equal.
  - `changes` with `fab.tests.support.FakeRunner` answering a `-z` numstat
    with a text file, a binary file (`-` counts) and a test file: the argv,
    each Change's kind and counts.
  - `archive` with real git (`support.git_pair`): a commit holding
    `fab/x.py` and `README.md` extracts only `fab/x.py` into dest, the tar
    removed; a rev without `fab/` raises `fab.sh.Failed`.
- `bin/fab test` passes; `test_digest.py` stays under a second.

## Options, settled up front

- The numstat is read as text (the runner's `out`); NUL splits records.
- `tarfile.open(path).extractall(dest, filter="data")`; the tar sits beside
  dest as `<dest>.tar`.
