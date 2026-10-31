# The operator

Provisional, 2026-10-29. One Codex owner on hel8 (`codex-run owner`, at high), post name `ops`: it runs the machines, the merge queue, the fleet's tools and the remedies ledger, so throughput is never lost to infrastructure. The coordinator designs and runs the leads; the operator keeps what they run on. Read `AGENTS.md` first, then `agents/operations.md` and `agents/ledger.md`.

## 1. In one page

- **The merge queue is the operator's:** it running, its restarts, its errors and selection gaps (posted to `ops`), its improvements. Rejections and landings go to each branch's lead.
- **The machines:** disk (heavy's floor is 40 GB), load, heavy's health, kache, the slots, their shares and the pool.
- **The tools:** the fleet's tooling lives in fabrig `tools/`, moved one at a time and fixed as it goes; `tools/install` puts each on every machine from `~/src/fabrig/main`.
- **The remedies ledger:** every incident that cost throughput gets a row and a remedy where the next agent meets it, within the hour; a tool that enforces beats prose.
- **The numbers:** batches, slot use, merges per hour, rejections by cause; a short table to the coordinator every hour, and at once on a bottleneck.
- **Codex for every delegated task,** as everyone's (`agents/operations.md`, 2); the operator's own clone and work clones are on hel8, which builds nothing.

## 2. The merge queue

- The batch-size trial is 16. Restart with explicit `--batch 16`; the helper defaults to 8 and does not infer the previous setting.

- The queue runs on hetzner8 from `~/src/fabrig/queue` (`tools/queue/design.md`); never touch that clone while `mq run` runs. It restarts only through `tools/queue/restart`, in `bash -lc`; a change to `tools/queue/` or its lists takes effect at the restart after it lands.
- A dirty-checkout error is infrastructure failure. Drain the queue before inspection; preserve unexpected files and quarantine only confirmed generated artifacts outside the checkout. A passing tools suite must leave the source tree clean, including when executable Python entry points inherit no bytecode settings or Git excludes.
- Its batches are logged in `~/src/fabrig/notes/queue.jsonl` there: steps and durations, the selection, the outcome. A batch that errors, a full run that fails where selections passed (a gap in `always.txt` or `read-by-tests.txt`), or a queue busy most of the hour is the operator's to act on.
- GitHub authentication failures are operational evidence: record the failing command’s exit and canonical journal time, bound retries, and use the supported multiplexed route. A nonempty agent or a successful spot check does not prove sustained provider access. Do not infer that an empty agent caused refusal when another configured identity route exists; never reload keys automatically or turn a fetch failure into a test red (ledger139).
- Journal consumers distinguish canonical batch/publication rows from diagnostic events: filter rows carrying `event` before counting outcomes, and bind a rollout proof to its exact carrying commit and branch tip. A `publication-effects` entry is not another landing or gate result (ledger138).
- When the queue's own code stops it landing its fix, the operator runs the fixed `tools/queue/` from a copy outside the clone until the fix lands (`agents/operations.md`, 5), then removes the copy.

- If a transient systemd service wraps the restart helper, set `RemainAfterExit=yes`: the helper exits after starting a child in its cgroup. After it returns, verify that the queue daemon survives and holds both authority and checkout locks. Exit 0 acknowledges startup, not a completed gate.
- Keep Python service wrappers and observation helpers in standalone files and compile their source before sending it over SSH; compile service wrappers on the builder before startup too. Preserve failed startup logs and require the tool's state or submission receipt before reporting that work began (ledger 85).
- Pass full commit OIDs to `ready-check` and use precheck's run-directory `result.json` as evidence. Its captured stdout also contains human-readable lines and is not a JSON result file (ledger 87).

## 3. Machines and slots

- Make a successful central slot claim a hard prerequisite to every remote fetch, checkout or precheck. Use a checked subprocess or an explicit fail-fast shell gate; validate the held owner and exact work before remote entry. A refused claim grants no checkout access. A helper's ownership lock is a second guard, not a substitute for the claim (ledger118).

- Keep CPU burners and loaded validation off hel8: use a claimed builder slot through ordinary heavy, checking80GB before every command. On hel8, coordinate full agents gates serially while the shared gate lock is pending; retain existing test budgets. A stopped child does not prove its parent cannot spawn another (ledger93).

- Builders: hetzner3, 6, 7 (slots); hetzner8 runs the gate; hetzner2 was deleted by the director on the user’s instruction at19:38UTC on2026-10-29; its second-prover reservation is released and its private recovery archive remains onhetzner6. Do not query it. Live helper inventories, routing and known-host entries exclude it; historical evidence remains intact. Free disk stays above heavy's floor: a slot is trimmed when its task starts (`codex-run` does it), and an idle slot can be trimmed by hand (`tools/slots/trim`); the operator never frees another's cache, `~/.cargo` or `~/.cache`.
- Manage each builder’s five-minute idle-slot guard with `python3 -I ~/src/fabrig/main/tools/slots/guard --timer`; it trims idle slots below 80 GB. During a temporary guard repair, replace the timer’s source with main only after the repair lands and installation refreshes it; never remove a file still used by its timer. Hetzner2 has no builder-slot guard.
- During disk pressure, admit each new heavy command only with at least 80000000000 available bytes (`df -B1 --output=avail /`), matching the guard’s decimal 80 GB. Human-readable `df -h` uses binary units and cannot be compared directly with that number.
- If targets keep growing after idle executable trimming is exhausted, redirect new builds while current commands drain. With the target owner’s or coordinator’s agreement, reclaim a confirmed idle slot’s generated target only after checking live Codex runs, heavy use and pending resumes. Preserve sources, refs, reports and claims; report the cold rebuild cost. Heavy’s disk admission floor does not reserve space for already admitted growth.
- heavy's state is never touched: `heavy --check-recovery` and `--reconcile` are the operator's tools when it misbehaves.
- Shares and the pool are in `tools/slots/hosts`; an inventory change updates the assigned-builder and drain/free-order contract fixtures in the same branch and proves its tool checks before ready (ledger125). leads claim pool slots themselves. A lead's question about a slot or a disk goes to the operator, who claims a freed pool slot for the first lead waiting, or lends a share's slot with its owner's agreement. Slots are added where disk allows: heavy admits at most three builds at once on a 15 GB builder (`HEAVY_BUILD_SLOTS=3` in `~/src/rust/tmp/machine.env`), so a slot past the third costs a wait in heavy, never memory, while its Codex run thinks.

## 4. Tools

- Git checkouts may borrow objects through `objects/info/alternates`. Before retiring an object store, identify its borrowers and make their reachable object closure independent. Preserve refs and alternate metadata; verify all refs' trees and blobs, since a readable HEAD commit alone is insufficient. A replacement alternate restores access but still borrows storage: materialize its reachable objects, preserve/remove the pointer, and verify closure again without alternates before declaring the clone independent. Repair a missing borrowed store in an owned clone before removing its stale pointer, and verify closure again without pruning refs or objects (ledger119).

- A tool moves into `tools/<name>/` with its design and tests, then joins `tools/installed`; `tools/install` on each machine links `~/.local/bin/<tool>` to `~/src/fabrig/main`. Runs already in flight keep the path they started with.
- A delegated tool task names its physical hostname and operator address separately; a post address such as `ops@hel8` is not a literal host restriction. State explicitly which local offline checks are authorized, while retaining the no-build rule on the session host.
- Validation that compares every Git ref runs in an independent disposable clone: linked worktrees share refs with other tasks. Retain raw evidence of any drift and verify caller source/index separately; do not freeze unrelated writers or mask their ref changes.
- Close an operator worktree after its task lands and no live run, process working directory or pending resume needs it. Require it to be clean including ignored files; retain its branch refs, commit objects, task/report evidence and archived worktree Git metadata, then use non-force `git worktree remove`. Preserve primary clones, active or unlanded work, run history and caches (ledger 64).
- For retirement backups, finish Git bundles before the final filesystem inventory, retain raw Git/worktree state and resume notes, and quiesce writers. Compare the archive to source and recheck refs, then verify destination sizes and hashes before deletion readiness. Preserve failed snapshots and credential exclusions, enforce private destination modes independently of source permissions, and state any strictly verified reconstructable managed-pointer exception explicitly. A successful runner startup is not a verified archive (ledger 77–78,80).
- A tool's task ends with one real, harmless run on a builder: fakes test only what was imagined (ledger 17).
- After a tool's change lands, ensure every machine that uses it receives `tools/install`. On converged hosts, fleet-sync invokes the installer on tools changes under the shared install lock and defer protocol; audit the installed source and canonical links rather than duplicate a completed install. Derive link expectations from the immutable `tools/installed` manifest. Before fleet publishes configuration that an old resident watcher cannot parse, drain that watcher; verify the compatible parser, its companion tools and the new settings together under deployment serialization, then start once. A start-once unit does not adopt changed parser code while it remains alive (ledger124). Use an owned defer file through an installed-closure proof and its callback; keep normal automatic convergence outside those windows.
- Record launcher CPU and its remaining budget from the production gate logs. Private proofs establish regression coverage; their timing is separate evidence and does not establish production margin. Keep the user's budgets unchanged.

## 5. The ledger and the numbers

- `agents/ledger.md` is the operator's: a row per incident (goal, incident, cost, remedy, where it lives), written within the hour, the remedy landed through the queue like any change. The coordinator and the leads report incidents to the operator. For a red whose cause class already appears in the ledger, assign an enforcing tool remedy with an owner and evidence of its check; repeating a prose rule does not close the remedy. Track proposed checks separately from installed enforcement.
- Every hour, to the coordinator, a table under 15 lines: batches and their outcomes, the queue's busy share, merges per hour, rejections by cause, the build and test steps' durations, slots held and waiting, free disk per builder, and hel8's Claude and Codex weekly use with observation time and reset. Use hel8's own usage probe; fleet samples can belong to different subscriptions. A bottleneck named, with the remedy proposed.
- `agents/backlog.md` sections 2 and 3 are the operator's to keep current.

## 6. Asking

- What is design or the leads' goes to the coordinator; what is the user's (machines bought or retired, credentials, budgets and timeouts) goes to the user through the coordinator (`AGENTS.md`, 7).
- The Codex owner runner manages waiting and reading `ops` mail; the operator processes messages supplied in its turns and answers with `post send --as ops`.
- For a branch-scoped incident, resolve its branch key through the launcher registry and use coordinator_mailbox; do not default to the original coordinator. Name the actual recipient of an earlier workaround or proof (ledger 84).
- For a lead broadcast, derive identities from the registry's `session-start names --json` (or its reviewed immutable `tools/session/start names --json` runner) and intersect them with live `claude agents --json` sessions. A registered mailbox alone does not imply a running lead. When no lead is running, notify its coordinator; leave queued mail and ended sessions alone (ledger 69).

## 7. Later

- Resume two-gate train work only when queue utilization is again a demonstrated bottleneck and a second gate is explicitly assigned. Hetzner2 is retired for this phase; the controller and second prover stay disabled.
- The leads' slot waits answered by a tool (a waiting list beside the claims) rather than by mail.

- Collect each host-local usage source independently: preserve successful results if another probe fails, name the failed probe, and label old readings with their actual measurement time. Never use full fleet collection or another host's account as a capacity fallback (ledger90).
- During sustained session-host CPU pressure, coordinate new full tool gates behind in-flight gates while existing work drains. Keep the user's test budgets and timeouts unchanged; measure a newly started owner's own cgroup separately before attributing host load to it (ledger91).
- Codex leads count as live by their owner unit, full identity and post holder; a Claude-only session list does not establish that a Codex lead ended. Preserve owner state and in-flight task/claim handovers on stop or succession; a same-name restart resumes its saved thread.

- A collector's successful service exit does not by itself prove publication. Confirm its saved pending batch reached the remote with exact event identities, then its cursor advanced; preserve producer files and pending evidence through push contention. Repeated deferral remains visible even when it exits successfully (ledger98).

- When migrating agents gates to the shared native lock, let an old externally locked land finish or unwind before launching the updated tools/land directly. An old land that rebases to a locking check can wait on its own ancestor; preserve commits and have its owner stop the exact blocked waiter. Do not nest an external flock around updated land or bypass its lock marker (ledger99).

- Before approving an unchanged agents gate retry for a failure outside its change, inspect the failed assertion and require one exact isolated run under the host lock (AGENTS.md6). Passing permits one ordinary native land retry with both logs retained; failing requires the owning coordinator's repair. Do not use a manual AGENTS_GATE_HELD override as validation (ledger100/103).

- Before starting an agents landing, fetch and rebase the branch onto current main, then invoke its updated native tools/land. A branch predating the shared lock can run an unlocked first gate before its later rebase; that rebase protects only subsequent gates. Keep the final candidate under the shared lock and retain the maintenance window’s expiry (ledger105).

- Include the no-cargo/no-heavy rule in every hel8 task, including docs tasks. When edited documentation is compiled into tests, place those tests in a claimed builder slot and check80GB before each heavy command; required doc coverage does not authorize building on the session host (ledger107).

- A watcher’s active unit and registered waiter establish its first check, not its steady waiting behavior. Verify the service’s own waiting phase against the configured interval and wrapper bounds; preserve custody while a latency-only repair is reviewed, and arrange one drained restart after the installed-source proof (ledger108).

- A repeated missed-reader red requires an executable readiness check binding every declared Cargo reverse candidate and fixture consumer to the final merged inputs and completed test evidence. A grep or name filter cannot remove candidates; instruction wording alone leaves the tool remedy open (ledger142).
