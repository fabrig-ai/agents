# Implementers

Provisional, 2026-10-28. An implementer is a Codex run that takes one task file from its lead, in a slot, and writes, builds, tests and repairs until the task is done. It reads `AGENTS.md`, this file, its task, and section 1 of `skein/docs/foundation/programming-model.md` and `testing-strategy.md` (a later section only where the task names it). Where the task departs from this file, it says why, and the task wins.

## 1. The task

- **The sketches bind the outer layer:** modules, names, public types and signatures, what crosses a boundary, the tests' shape. Inside them the choices are yours, and the report names those that matter.
- **Done** is the task's acceptance criteria, their tests passing, in commits on the task's branch, pushed.
- **Not yours:** any `docs/design/` (what the code taught goes in the report), drafts, `docs/help/`, ready-check, ready refs and claim release.
- **The slot:** a fixed directory whose target stays warm across tasks. Start by trimming its stale test executables (`python3 -I tools/slots/trim <slot>` from the slot, or the command your task gives), then switch it to the task's base in place (`git fetch origin && git switch -c <branch> <base>`), never a fresh clone or worktree.
- **The log:** every 30 minutes, if the task runs that long, 3 or 4 lines appended to the log the task names: where you are, and whether you're on track.
- **A rebase** only when the task asks for one.

## 2. Building and testing

- After each change, the narrowest test that checks it (`AGENTS.md`, 6). A compile repair may use `heavy cargo check -p PKG --tests` while errors last.
- Find the test with `rg` for the changed items' uses, then read its assertions before choosing it.
- When the changes are done, once: `cargo fmt`; `heavy cargo clippy -p PKG [-p PKG ...] --all-targets -- -D warnings` naming every package you changed; the focused tests of the packages you changed and their direct dependents (`heavy cargo nextest run -p ...`). Never the whole workspace: the merge queue runs the wider set.
- **Direct dependents include every tree.** Before readying a public API change, check cross-tree consumers with `heavy cargo check -p <dependent> --tests`, naming each dependent package. A package-only check upstream does not verify its downstream struct initializers.
- When a queue lint passed on the branch but fails merged with main, the lead re-checks clippy in a throwaway merge with current main and reports that merged result before re-readying the repair.
- A repair of what the queue found runs the failing test alone in its profile (`--profile fuzzy -E 'test(=NAME)'`), then the narrowest tests its fix touches.
- **The task ends with its checks:** after pushing, in your own claimed slot, `git fetch origin`, then installed `precheck SLOT EXACT_TIP`; require exit 0, `outcome=passed`, `restored=true`. Keep its original `result.json` receipt unedited, including original failed receipts. Precheck runs within your lifetime; never request an exclusive maintenance lease against your own live shared lease. Fail closed on unknown child processes or uncertain restoration. Then recreate its recorded main base merged with that tip, without another fetch or commit, and run every candidate reader's tests through `heavy`, default then fuzzy, using the retained Cargo reverse graph (`agents/lead.md`, 2), never a grep or name subset. A missing required reader cannot certify completeness. Abort the merge and restore the branch clean at the checked tip. After grouped repairs, rerun these exact-tip checks. On a check failure, read its log and report; an unresolved slot stays claimed and untouched for the operator. The claim stays held through ready; the lead marks ready from your report after its skim and owns ready-check, the ready ref and claim release.
- **Disk admission:** the floor stays 80000000000 bytes. Until ops’ decision-0033 enable proof for your host, check `df -B1 --output=avail /` before every heavy command; below the floor, stop and report, keeping your claim. After your host is enabled, submit to `heavy` without a manual `df` refusal and wait on its bounded disk queue, up to 1200 accumulated below-minimum seconds. At the cap, report heavy’s capacity receipt as an infrastructure result, never a test red.

## 3. The report

- Written whole over the report's path; its first line is read first.
- Besides what the task asks: what ran (the tests, how many, what each found), any test you couldn't run, and the calls you made inside the sketches.
- Checks: exact checked tip, main base and checked merged tree OIDs, original precheck receipt path/SHA256 and logs (including original failed receipts), retained graph candidates, every reader’s outcome and per-package default/fuzzy counts and exclusions, clean restoration, and implementation minutes and check minutes reported separately within implementer minutes (`agents/lead.md`, 2).
- **On a doubt, stop:** the first line is `Question:`, with the options and a recommendation. Never improvise across a boundary; a tool the task lacks is such a question.
- Throwaway code lives untracked in the slot and is deleted before the push.
