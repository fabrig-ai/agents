+++
id = "taste-brief"
part = "gates"
kind = "feature"
needs = []
files = ["fab/run.py", "fab/tests/test_run.py"]
effort = "medium"
minutes = 20
+++
# The taste file in every brief; a gate's findings in the repair brief

Make `fab.run.role_text` and `fab.run.start` do what their amended
docstrings say: the role text is followed by `fab/taste.md` (TASTE), then
the repository's notes; a rejection that carries `findings` (logged by
`fab.gates.screen`) gives them as its text, with no ssh to the gate.
Design: `docs/design/fab.md`, section 12.

## Acceptance

- `fab/tests/test_run.py`:
  - `role_text("agents")` is the role text, a blank line, then the taste
    file; `role_text("fabrig")` adds fabrig's notes after the taste file
    (update the existing role_text test to this order);
  - `start` with a rejection holding `findings` and step `gate:files`:
    the fake runner sees no `tail` on the gate, and the brief written holds
    the findings under "The landing refused this branch";
  - a rejection without `findings` still reads its log on the gate.
- `bin/fab test` passes; `test_run.py` stays under a second.

## Options, settled up front

- Each of the three texts is stripped of trailing newlines, they are joined
  with one blank line, and the whole ends with one newline.
