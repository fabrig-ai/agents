+++
id = "acceptance-tasks"
part = "acceptance"
kind = "feature"
needs = []
files = ["fab/acceptance.py", "fab/tests/test_acceptance.py"]
effort = "high"
minutes = 45
+++
# Acceptance tasks from the plan, its specs and the log

Fill every body of `fab/acceptance.py` as its docstrings say: `tests_path`,
`owned`, `units`, `read_report`, `needs`, `accept_round`, `fix_files`, `tests_body`,
`accept_body`, `tasks` and `slices_done`. The module is pure; it imports
`fab.state` for `fold` and nothing that runs a command. Design:
`docs/design/fab.md`, section 13.1; the role texts the bodies speak to are
`fab/roles/test-writer.md` and `fab/roles/accepter.md`. Nothing calls the
module yet; `acceptance-tick` wires it into runs, the tick and `fab status`.

## Acceptance

- `fab/tests/test_acceptance.py`, in the vocabulary of
  `fab/tests/support.py` (`build_plan`, `build_part`, `build_task`,
  `History`), no files and no git:
  - `StoryTest`, the skeleton's exemplar, passes: remove its
    `@support.pending("agents-rebuild/acceptance")` line once it does. It is
    the skeleton's, not a test-writer's, so removing it is yours.
  - `tests_path` for a part and a slice, a draft with `-`, and an id that
    becomes empty (ValueError);
  - `owned` for `d/p/tests`, `d/p/accept-3`, `d/slice-2/accept-1`, and not
    for `d/task`, `d/task/foreman`, `d/p/accept-0`, `d/p/accept-01`,
    `d/p/fix-1`, `d//tests`, `a/b/c/tests`;
  - `units`: a feature part with an unlanded spec owes; a migration part, a
    part marked done, a part with no specs, and a plan of repo `fabrig` owe
    none; a part whose specs all landed owes only once a run.started names
    its tests task; a slice owes only once every part is designed or done and
    one part owes; owned tasks among the specs are ignored;
  - `needs` for a part and for a slice holding a part that owes, a part
    marked done and a migration part with specs, in that order;
  - `accept_round`, with `History.report` as the reader: no landing (1,
    False); a green first round; a first round red by its report (`Done:
    red, ...`) then a second round not landed and then green; a round red
    because a need landed after its run started; a report that cannot be
    read (red); a round landed by hand with no run.started, green by its
    waits alone; a need that never landed;
  - `read_report` with a temporary FAB_HOME: a report's text, and "" when
    it is missing;
  - `fix_files`: order, duplicates once, `fab/tests/test_accept_*` entries
    left out, a slice's parts merged;
  - `tests_body` and `accept_body`: the exact text for a part and for a
    slice (every line the docstrings name, the TOML strings quoted), one
    assertion of the whole text each;
  - `tasks`: every field of both tasks for a part and a slice, the order,
    a red round left out, repo `fabrig` giving none;
  - `slices_done`: none before the slice's round is green, one after, none
    once a slice.done names it, another draft's slice.done not counted.
- `bin/fab test` passes; `test_acceptance.py` stays under a second.

## Options, settled up front

- `tests_path` slugs with `re.sub("[^a-z0-9]+", "_", text.lower()).strip("_")`.
- `owned` is one `re.fullmatch` over the id.
- Every function that reaches accept_round takes `report` and passes it
  on; tests pass `History.report`, never touching FAB_HOME.
- `units` folds once (`fab.state.fold(specs, events)` over the specs that
  `owned` does not name) and shares it; `needs` and `tasks` may call `units`
  again: plans are small.
- The bodies are built with f-strings and `"\n\n".join` of their sections;
  TOML strings through `json.dumps` (a basic string's escapes are JSON's for
  these paths).
