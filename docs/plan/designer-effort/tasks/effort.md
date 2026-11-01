+++
id = "effort"
part = "effort"
kind = "feature"
needs = []
files = ["fab/calls.py", "fab/roles/cut-run.md", "fab/roles/cut-direct.md", "fab/tests/test_calls.py", "fab/tests/test_designer.py"]
effort = "medium"
minutes = 20
+++
# The designer's calls run at xhigh; their surveys are Claude sub-agents at high

Read first: `docs/plan/designer-effort/notes/common.md`,
`docs/plan/designer-effort/notes/decisions.md`, then
`docs/plan/designer-effort/inputs/request.md`.

The request: "claude designers should run at xhigh, if they deem appropriate to
run surveys, those should be run with claude sub-agents at high. Opus 5.5".

## What to build

Line numbers are approximate.

- **`fab/calls.py` ~467:** replace the comment and `EFFORTS` with:

  ```python
  # Each Claude role's effort, as the user's model sets it (execution-modes.md, the roles table), but for
  # the designer's calls (fab.designer.ROLES), xhigh at the user's word of 11-01 (docs/design/integration.md, 3):
  # the answerer, settler, issue reply and triager are medium; the skeleton author, its amendments and the
  # structure reviewer are high. Passed explicitly, so a user's own default never leaks in.
  EFFORTS = {"cut": "xhigh", "contract": "xhigh", "decision": "xhigh", "retire": "xhigh",
             "answer": "medium", "reply": "medium", "triage": "medium", "settle": "medium"}
  ```

  `EFFORT` stays `"high"`.

- **`fab/roles/cut-run.md` ~151, "Surveys":** the section's body, the `codex
  exec` block with it, becomes:

  ```markdown
  Survey only where you judge it worth it. A survey or investigation is a
  read-only Claude sub-agent you start with the Agent tool, `model` `opus`
  (Opus 5.5), `effort` `high`, in the background. Several may run at once.
  Each answers its brief and builds nothing.
  ```

- **`fab/roles/cut-run.md` ~167, "Designers":** the first sentence becomes:

  ```markdown
  Where the design is too wide for one writer to keep the slots fed, split
  it across Claude designer subagents (the Agent tool, `model` `opus`,
  `effort` `xhigh`, in the background), one per part or family of parts.
  ```

  The rest of the section stays. So does ~56's "reverse-dependency survey":
  it is such a survey.

- **`fab/roles/cut-direct.md` ~10:** the sentence "Survey the code in parallel:
  ..." becomes:

  ```markdown
  Where you judge a survey worth it, survey the code in parallel: start one
  Explore subagent, `model` `opus`, `effort` `high`, per family of sites (for
  example: the call sites a contract replaces, the private copies of a
  primitive, the test surfaces) while you write the contract tasks, and use
  their findings for the site tasks.
  ```

- **`fab/tests/test_calls.py`:** beside `test_claude_argv` ~574, or in it:
  - `role_effort` is `"xhigh"` for each of `designer.ROLES` and `"high"` for
    `skeleton`, `amend` and `review`, and `settle` stays `"medium"`.
  - A new test, modelled on the `reply` one ~686: `calls.start("cut", ...)` on
    a `FakeRunner` and `tmp_home`; the `claude` argv's `--effort` is `"xhigh"`.
    Do this for one designer role, `cut`; the loop above covers the others.

- **`fab/tests/test_designer.py`:** a new test beside
  `test_cut_roles_prefer_early_work_away_from_other_drafts_and_record_overlaps`
  ~655: `cut-run.md` holds no `codex exec`; it holds `` `effort` `high` `` and
  `` `effort` `xhigh` ``; `cut-direct.md` holds `` `effort` `high` ``. Read the
  files as that test does; mind rewrapped lines (compare on
  `" ".join(text.split())`).

## Acceptance

- `grep -n "codex exec" fab/roles/*.md` gives nothing.
- `grep -n "reverse-dependency survey" fab/roles/cut-run.md` still gives ~56.
- `git diff --stat main` names only the spec's `files`.
- `bin/fab test` green; `bin/fab status docs/plan/designer-effort` shows no
  plan problems.

## Pre-approved defaults

- A line has moved: find it by its text.
- A test fails because it pinned the old role text or a designer role's old
  effort (the cut found none): move it with the change, within the two test
  files, and name it in the report. One outside them is a `Question:`.
- The `cut-run.md` rewrite fails a role-text test by length or shape: rewrap,
  keeping the words.
- A wider `calls.py` comment line over the file's limit: rewrap it.

## Report

The lines changed in each file; every test that moved with the change, or that
none did; that `docs/design/` is untouched. No machine action.
