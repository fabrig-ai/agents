# Gate

2026-10-30. Owner: s/deploy. Code: `tools/check.sh`, `tools/gate.py`,
`tools/land`, `tools/land_remote.py`, `tools/periodic`. Status: `docs/design/gate.status.md`.

## 1. In one page

- **Land on a claimed builder.** `tools/land` rebases, ships HEAD as a complete
  git bundle, checks selected tests at nice 19 and idle IO, then fast-forwards
  main. Agents work must not consume fabrig's pipeline capacity unclaimed.
- **Keep the merge below 60 seconds.** `tools/gate.toml` declares ownership,
  selection and CPU/wall budgets. Enforcement starts report-only; only the
  user turns it on. No force push, queue, or production service calls in tests.
- **Tests use disposable HOME and TMPDIR.** Each file has a fresh interpreter.
  Discovery honors existing `load_tests` hooks. Fleet gate cases use focused
  component fixtures; exhaustive compatibility sweeps run in periodic files.
- **Main deploys itself.** Hosts poll main; this entrypoint remains policy,
  rather than remote branch protection (`docs/design/fleet.md`, section 3).

## 2. Check and budgets

`tools/check.sh [--tier gate|periodic] [--changed BASE] [FILES ...]` defaults
 to gate, excluding `test_*_periodic.py`; periodic selects only those files.
Explicit files override tier discovery. Fleet changes also select the landing,
disk-admission and periodic fixtures that read host/unit declarations; smoke
checks guard coverage of those declaration readers in both tiers. Changed selection uses
`git diff --name-only BASE...HEAD` and the glob map, plus the always-run smoke
set. Docs and Markdown select smoke; unmapped tools select their directory's
files (all files if empty); other unknown paths select every gate file.

Up to eight workers share a per-host lock. They use nice 19 and idle IO when
ionice is available. `wait4` reports each child's user+system CPU, including its
waited and adopted descendants, and wall time. Workers reap adopted zombies
throughout the run so fixture process groups can disappear before file exit. The table names file, owner, CPU, wall,
budget and status. Every tier/check/landing summary says `budget: REPORT-ONLY
(not enforced)` or `budget: ENFORCED`; report-mode merge-wall overruns say
`OVER (report-only)`. `--json PATH` saves the same observations atomically.
Defaults: file CPU 8 s, file wall 15 s, tier CPU 100 s, merge wall 60 s.
QA exceptions are `test_qa.py` CPU 10 s / wall 15 s and `test_logins.py`
CPU 3 s / wall 8 s. Every gate and periodic file has an owner row.
Report-only mode lets every selected file complete, regardless of CPU, file
wall or merge-wall targets. Overruns say `OVER (report-only)`; a separate
`report_hard_wall_s = 900` safety cap guards hangs. With enforcement enabled,
CPU overruns fail by name, workers receive an OS CPU ceiling, and file wall
and merge-wall targets become hard limits. Any killed or starved file fails
in either mode and is labelled unobserved, including files that never started.
A landing refuses an incomplete gate. Repair tier membership or inefficiency
before asking the user about budgets (fabrig testing-strategy, section 8.1).

## 3. Land and races

`tools/land [--host NAME] [--local] [--dry-run] [--keep-branch]` refuses dirty trees, main and
detached HEAD, then fetches and performs a plain rebase on origin/main. A
checkout flock at `.git/agents-land.lock` (resolved with `git rev-parse --git-path` for
linked worktrees) is held from the initial checks through push. After the
initial rebase, land pins the exact candidate SHA; any unexpected HEAD change
during the run refuses the landing.
Auto selection matches hetzner3, hetzner7 and hetzner6 pool slots against
hel8's central free list. Before claiming, it reads `df -B1 --output=avail
"$HOME"` over SSH, skips unknown disk readings or availability below the
larger of 85 GiB and `machine_env.PLAN_MIN_DISK_GB`, and prefers the host with
most available bytes. Explicit `--host` (including h3/h7/h6 aliases) selects
that builder directly; disk admission applies to automatic selection.
Hel8's SSH target comes from `fleet/hosts.toml`. Atomic claim admission is
still authoritative if that list races. Claims use owner `s/deploy-gate` and
a unique `agents-gate <sha> <token>` description. There is no owner-only
release or stale-claim stealing.

Lander-side bundle scratch uses `/tmp/agents-gate.<token>.local.<random>`
with a matching private identity. Its exact `local_dir` is durably recorded
before remote preparation or upload. Known ends remove both builder and local
scratch, including red gates and bundle failures. Unknown ends keep the local
directory, claim and record; reconciliation removes local scratch only after
remote termination/restoration proof, validating the saved path and identity.
An interrupted local allocation has a durable intent and a token-scoped
recovery prefix. Builder allocation recovery excludes this local namespace.

A builder receives a full bundle of that pinned SHA in a private temporary
directory. A temporary local ref pins bundle construction, the builder checks
out that SHA detached, and land validates the remote receipt against it. It
runs `nice -n 19 ionice -c3 tools/check.sh --tier gate --changed BASE` with a
hard wall backstop of 905 s in report-only mode or 65 s when enforced,
including lock waiting (configured hard wall plus 5 s). A detached supervisor records
its process group, boot/start identity and exit status. It drains its fixture
descendants on completion; losing SSH does not terminate the remote run.

**Release requires a known end.** Normal landing must receive the remote exit
status, prove the process group and supervisor ended, remove the working
directory, verify it no longer exists, print that removal, and assert that heavy's read-only snapshot has no task submitted
from it. Gate scratch stays below that directory and submissions would carry
the unique claim label, so either cwd or label identifies a violation. A heavy submission is a bug; land never submits or cancels heavy work.
Unknown completion or restoration keeps the exact claim. This includes an SSH
drop, timeout, or interrupt before the exit status was received. Durable 0600
records in `~/.local/state/agents-gate/unreconciled/<token>.json` hold host,
slot, owner, WHAT, SHA, remote directory and process identity. Intent is saved
before claim, upload and gate-launch dispatch. Upload intent and its receipt
live in the same unknown-end record. A remote upload wrapper records its own
PID and the uploader's process group, boot ID and start ticks before releasing
a pipe barrier that permits the copy. A lost or interrupted upload retains the
claim and directory until reconciliation proves both wrapper and uploader gone;
removing a pathname is never proof that its writer ended. Cleanup and upload
launch share a remote lock and cancellation fence.

`tools/land --reconcile [CLAIM]` inspects those builders read-only first,
including both upload and gate process groups/supervisors, the directory and
heavy snapshot. Live processes are reported and keep the claim. Only `--reconcile ... --kill` may terminate a live run;
it verifies the saved process identity and kills no heavy task. Once ended,
reconciliation blocks delayed launches, removes any remaining owned directory,
rechecks restoration and releases the exact WHAT. Missing/corrupt observation
keeps the record and prints the reconcile command. A local record lock prevents
a live lander and reconciliation from acting together. `--local` explicitly
announces its unclaimed fallback; selection, budgets and host lock still apply.

After green, fetch again. A moved main is rebased; disjoint test selections
permit push under the no-overlap rule: record the previously checked SHA,
the exact new rebased SHA and upstream base in the claim record and output.
Overlapping selections require one further check of the new SHA and a matching
receipt. A second upstream race refuses and asks for a rerun. Immediately before
push, HEAD must still equal the permitted SHA. A plain
`<SHA>:refs/heads/main` push binds the update to that commit and refuses a final
upstream race. `--dry-run` follows the real flow but stops before push.
After a successful main push, delete origin's landed branch only if its tip
matches the local pre-rebase tip or landed HEAD. The ordinary deletion push
checks the server-advertised OID through a temporary pre-push guard, chaining
any existing hook, then relies on Git's normal old-OID check. A moved branch
is kept with a warning. Detach at landed HEAD and delete the local branch;
`--keep-branch` retains the local branch, while remote cleanup still applies.
Dry-runs, refusals and failed gates never delete branches. Cleanup failures
are reported separately from an already successful main push.
Report elapsed time from entry through push (or dry-run completion), labelled
with budget mode and report-only wall overruns.

## 4. Lock and periodic checks

`~/.local/state/agents-gate.lock` (`AGENTS_GATE_LOCK` override) serializes
checks on each host. Local landing takes this flock in the same process as
the checkout lock and holds both through fetch/rebase/check/push, including
while waiting for the host gate.
`AGENTS_GATE_HELD` is a trusted nesting marker; fixture children strip it and
the lock override. This is cooperation, not verified exclusion.

Every two hours `agents-periodic.timer` runs `tools/periodic`: periodic first,
then the full gate without selection. The deployed `current` release is a Git
archive; its `.fleet-release.json` supplies the exact release SHA. The runner
makes a private `git clone --shared --no-checkout` from fleet-sync's
`~/src/fabrig/agents` clone into mktemp, checks out that SHA detached and runs
both tiers there. The fleet clone is read-only; private refs, index and checkout
are removed on exit. This retains the history used by `git log`, `git show` and
`git archive` fixtures even if fleet's clone HEAD advances after deployment.
Direct invocation from a Git checkout pins its HEAD in the same way.
Builder role units render only with `machine_env.AGENTS_PERIODIC = 1`.
Periodic is paused as of ed5c048; the coordinator re-enables h3 after this fix
lands. The service also checks the runtime flag, uses nice 19 and idle IO. It mails each failed,
over-budget (CPU or `wall_s > wall_limit_s`) or starved file's owner using
`post send --as agents-periodic OWNER@hel8`; missing owners and runner failures go to ops. Fleet periodic files retain exhaustive process, historical and host matrices;
the gate retains focused component, safety and rollout checks. QA
compatibility matrices in `tools/qa/test_qa_periodic.py` belong to the periodic
tier and route failures to s/qa, alongside the bounded QA gate core. Historical
rollout assertions compare pinned revisions rather than today's declarations.

## 5. Later

- Enforce the landing entrypoint with remote main protection.
- Retain timing history with landing records; current tables are printed and
  optionally saved through `--json`.
