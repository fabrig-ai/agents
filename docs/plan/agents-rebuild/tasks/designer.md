+++
id = "designer"
part = "designer"
kind = "interface"
needs = ["atomic-write", "tick-split", "call-review-tick"]
files = ["fab/designer.py", "fab/plan.py", "fab/state.py", "fab/calls.py", "fab/tests/test_designer.py", "fab/tests/test_plan.py", "fab/tests/test_state.py", "fab/tests/test_calls.py"]
effort = "high"
minutes = 60
+++
# The designer's calls: cut, contract, decision, retire

Fill the bodies of `fab/designer.py` and `fab.state.part_statuses` as their
docstrings say. Make the plan read the fields `fab/plan.py` now declares,
and make `fab call` run the designer's four roles. Design:
`docs/design/fab.md`, 13.3 and 4; the calls in 12 and 13.1. The role texts
are written: `fab/roles/cut.md`, `contract.md`, `decision.md` and
`retire.md`. The tick does not start these calls yet; `designer-tick` does.

This task waits for `atomic-write` (`enlist` writes through
`fab.atomic.write`), `tick-split` (it changes `fab/plan.py`) and
`call-review-tick` (it changes `fab.calls.start` and `main`).

## What to build

- **`fab/designer.py`:** every body, as its docstring says. It imports
  `fab.calls`, `fab.log`, `fab.state`, `fab.run` and `fab.atomic` at the
  top and uses them only inside functions: `fab.calls` imports
  `fab.designer` inside `main`, and `fab.call_review` will import
  `fab.designer` at the top.
- **`fab/plan.py`:**
  - `load_plan` reads `retired`, each part's `contract` and the
    `[[question]]` tables into the declared fields, with the same type
    checks and PlanError messages as the other keys.
  - `problems` adds its three new lines, in its sorted order:
    - `part <id> takes a reserved id` for an id in RESERVED;
    - `question <id> is used twice`;
    - `question <id> names unknown part <part>`.
- **`fab/state.py`:** `part_statuses`.
- **`fab/calls.py`:**
  - `ROLES` gains `cut`, `contract`, `decision` and `retire`, each
    `roles/<role>.md`.
  - `main` hands argv to `fab.designer.main` when its first item is in
    `fab.designer.ROLES`. Its own subcommands cover the other roles only.
  - `_parts_table` takes its statuses from `fab.state.part_statuses` in
    place of its own rule. The table it writes is unchanged.
  - `skeleton_brief` gains the keyword `role: str = "skeleton"`. It accepts
    `skeleton` or `contract` (ValueError otherwise) and puts
    `ROLES[role]`'s text first. Its "Part to design" section gains these
    lines, after the design line:
    - `- Contract: yes` for a part the plan marks contract;
    - with role contract, `- Readers: <ids>`: the parts whose needs name
      it, in plan order, comma-separated, or `(none)`;
    - per question of the plan naming the part, in plan order, `- Question
      <id>: <text>`, then `  Answer: <answer>`, or `  Answer: (open)` while
      it has none.
  - Update the docstrings of `skeleton_brief` and `main` to say this.

## Acceptance

- `fab/tests/test_designer.py`, with a temporary HOME and FAB_HOME and
  `support.git_repo()` where git is the point:
  - `subject` for each role and each ValueError;
  - `uncut`;
  - `repository` with `support.FakeRunner`: each REMOTES URL, an unknown
    one;
  - `designs` and `status_path`: README and status files left out, drafts
    left out, a missing directory;
  - `design_index`: title, line count, status file present and missing, no
    title, no designs;
  - `changed_designs` on a real repository built in the test:
    - a design changed after the plan's commit, and one only by its status
      file;
    - a design changed in the plan's own commit;
    - a design changed only before the plan;
    - the plan's commit as the root commit;
    - no plan (ValueError).
  - `retire_due`:
    - all parts done (by `done` and by landed specs);
    - one part not done;
    - a plan with no parts;
    - a retired plan;
    - a retire call that ended done, and one that ended failed (still
      due).
  - `enlist`: creates the file, adds once, keeps the order;
  - each brief's sections and their order, the decision's refusals (not a
    probe, unreadable report), and a BRIEF_LIMIT refusal;
  - `main --brief-only` for each role through `fab.cli.main(["call", ...])`;
  - cut's refusals (an existing plan.toml, a PLAN_DIR elsewhere, a missing
    source);
  - `main` for cut with `fab.calls.start` patched: enlisted, and the
    subject and root passed.
- `fab/tests/test_plan.py`: the new fields read, their defaults, their
  wrong types, and the three new problems.
- `fab/tests/test_state.py`: `part_statuses` for each status, a part marked
  done, a task missing from the statuses.
- `fab/tests/test_calls.py`: `skeleton_brief`'s new lines for both roles
  and its refusal of another role. The existing brief tests pass unchanged.
- `bin/fab test` passes and `bin/fab status docs/plan/agents-rebuild` shows
  no problems. Each touched test module takes under a second.

## Options, settled up front

- `changed_designs` takes the oldest commit that added plan.toml: a plan
  deleted and re-added still started at its first cut.
- `design_index` counts lines with `str.splitlines`.
- `enlist` compares resolved paths as strings; it does not check that the
  directory exists (a plan being cut has none yet).
- A part's questions show in the skeleton or contract brief whether or not
  they are answered; the answer is what the call designs from.
- Briefs refuse past BRIEF_LIMIT rather than cutting designs: a cut design
  would be a contract read in part.
