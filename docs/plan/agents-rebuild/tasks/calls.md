+++
id = "calls"
part = "calls"
kind = "feature"
needs = []
files = ["fab/calls.py", "fab/tests/test_calls.py", "fab/cli.py"]
effort = "high"
minutes = 30
+++
# fab call: Claude calls from compiled briefs

Fill the bodies of `fab/calls.py` as their docstrings say. Design:
`docs/design/fab.md`, section 12, and the user's execution model (each call
a fresh session on a brief compiled by code, ending by writing files). The
role texts are `fab/roles/skeleton.md` and `fab/roles/answerer.md`.

## Acceptance

- `fab/tests/test_calls.py` covers:
  - `inventory` on a small package written into a temporary directory:
    functions, classes, methods, private names left out, annotations kept,
    tests left out; and on this repository's `fab/` (it finds
    `fab.log.append`).
  - `render_inventory`, `design_text` (found, missing), `open_questions`.
  - `skeleton_brief` and `answer_brief` on a small hand-built plan: every
    section the docstrings name is present; the BRIEF_LIMIT refusal.
  - `claude_argv`.
  - `start` with the fake runner (git worktree, claude, worktree removal) and
    a fake claude result: call.started and call.ended with tokens, the
    outcome from the report, failed without one.
  - `main --brief-only` for both roles; `main` registers as `fab call` in
    `fab/cli.py` (you may add that one line).
- `bin/fab test` passes; `test_calls.py` takes under a second.

## Options, settled up front

- `ast.unparse` renders arguments and annotations.
- The tokens string reads `usage.input_tokens`, `usage.cache_read_input_tokens`
  and `usage.output_tokens` from claude's JSON result; a missing key counts 0.
- A part's status for the brief's table: `done` when it has specs and all
  have landed, `designed` when it has specs, else `not designed`.
