+++
id = "brief-sections"
part = "calls"
kind = "feature"
needs = ["designer"]
files = ["fab/calls.py", "fab/call_review.py", "fab/designer.py", "fab/tests/test_calls.py", "fab/tests/test_call_review.py", "fab/tests/test_designer.py"]
effort = "high"
minutes = 30
+++
# Every Claude brief is built through fab.calls' public builder

Every Claude call's brief is a list of `# <name>` sections joined by blank
lines and held under `BRIEF_LIMIT`, with the same `Call facts` lines.
`fab.calls` builds them with three private functions: `_brief`, `_facts`
and `_parts_table`. Other modules already depend on them:

- `fab.call_review.amend_brief` calls `calls._brief` and `calls._facts`;
- `fab/designer.py`'s docstrings tell its implementer to use
  `fab.calls._brief`, `_facts` and `_parts_table` in `cut_brief`,
  `decision_brief` and `retire_brief`;
- `fab/tests/test_call_review.py` calls `calls._facts`.

The taste file's pair "A private name stays in its module" says why this
breaks: the underscore tells the next editor that nothing else calls them.
A change to `_facts` for the skeleton's sake would silently change the amend
call's facts, which `fab.calls.start` rebinds by text. Design:
`docs/design/fab.md`, sections 12 and 13.1 and 13.3.

## What changes

- `fab/calls.py`: the three become public, each with a docstring that
  states its contract, and every caller in the module uses the new names:
  - `assemble(sections: Sequence[tuple[str, str]]) -> str`, today's
    `_brief`: `# <name>`, a blank line and the body per section, joined by
    blank lines, ending with a newline; ValueError past BRIEF_LIMIT naming
    the largest section.
  - `call_facts(call_id: str, branch: str, report: str) -> str`, today's
    `_facts`: the three `Call facts` lines `fab.calls.start` rebinds.
  - `parts_table(plan: Plan, tasks: Mapping[str, Task], statuses:
    Mapping[str, str]) -> str`, today's `_parts_table`, as designer left it.
  The private names go; no alias stays behind.
- `fab/call_review.py`: `amend_brief` calls `calls.assemble` and
  `calls.call_facts`. Its docstring names them.
- `fab/designer.py`: the brief functions call the public names, and every
  docstring that names `fab.calls._brief`, `_facts` or `_parts_table` names
  the public one instead.
- The tests call the public names.

## Acceptance

- `grep -n 'calls\._' fab/*.py fab/tests/*.py` finds nothing.
- `fab/tests/test_calls.py`: `assemble` joins two sections as today's
  briefs do and raises past BRIEF_LIMIT naming the largest one;
  `call_facts` gives the three lines.
- Every brief compiles to the same text as before: `test_calls.py`,
  `test_call_review.py` and `test_designer.py` pass with only the renamed
  calls changed. A test may be added, none weakened.
- `bin/fab test` passes, with no change in behaviour.

## Options, settled up front

- The names are `assemble`, `call_facts` and `parts_table`. `facts` alone
  is not used: `fab.calls.main` has a local of that name.
- Kind `feature`: public names are added and no public signature changes.
- Codex briefs (`fab.run.brief`, `fab.foreman.brief`, `fab.call_review.brief`)
  keep their own form: they have no `# Role` heading and no BRIEF_LIMIT.
