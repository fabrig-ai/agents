+++
id = "gates"
part = "gates"
kind = "feature"
needs = []
files = ["fab/gates.py", "fab/tests/test_gates.py"]
effort = "medium"
minutes = 20
+++
# The gates as pure checks over a digest

Fill `banned_names`, `words`, `check` and `findings_text` in `fab/gates.py`
as their docstrings say. Leave `screen` raising NotImplementedError;
`gates-tick` fills it. Design: `docs/design/fab.md`, section 12.

## Acceptance

- `fab/tests/test_gates.py` covers, with Digests built by hand (no files,
  no git):
  - `banned_names` on `fab/taste.md` itself (holds `util` and `manager`),
    on a text with the heading followed by another `##` section, and on a
    text without the heading;
  - `words` on every example of its docstring;
  - `check`, one gate at a time: files; shape for a removed and a changed
    item, and nothing for an `interface` and a `migration` task; size;
    names for a new module (`fab/utils.py`), an added item
    (`TaskManager`) and a method of an existing class, and a clean name
    passing; docs; clones; a clean digest giving none; the order across
    gates;
  - `findings_text` grouping two gates' findings, and `fab.run.brief`
    quoting it whole when given as a rejection's `text` with step
    `gate:<first>`.
- `bin/fab test` passes; `test_gates.py` takes under a second.

## Options, settled up front

- The banned words compare lowercased; a name's words are matched whole,
  never as substrings (`metadata` does not hold `data`).
