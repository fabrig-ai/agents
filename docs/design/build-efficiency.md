# Build efficiency

Provisional, 2026-10-25. What a build costs on its way from an
implementer's edit to a landed `main`, measured by replaying real history
on hetzner2 and hetzner4, and the changes the measurements argue for:
the findings of the build-efficiency session (d/build-efficiency@hetzner2).
The cache is [build-cache.md](build-cache.md); `heavy` is
[build-infrastructure.md](build-infrastructure.md); the landing flow is
[landing-flow.md](landing-flow.md) and the landing session's draft
`landing-proof.md`.

## 1. In one page

- **The goal (the user, 10-25):** no CPU idles while work waits, and no
  lower-priority work slows higher-priority work. Every option was open:
  pueue and `heavy`, the gate's exclusivity, kache and its quotas, the
  store, cargo's profiles.
- **Where the time goes** (section 3): over 10-23 to 10-25 the fleet's
  machines had nothing to run 42% of the time. Builds still queued 202
  task-hours, 71% of them behind the gate lane's exclusive holds, which
  took 27% of machine time while their payloads used 1 to 3 of 8 cores.
- **The largest waste is in the code, not the tools** (section 4.3):
  - Test code compiles its worktree's absolute path in, through
    `env!("CARGO_MANIFEST_DIR")`, `env!("CARGO_BIN_EXE_…")` and
    `env!("CARGO_TARGET_TMPDIR")`. kache's key soundly includes it,
    so no worktree, and no machine, ever reuses another's test
    executables, and those executables are 58% of the fleet's compile
    time on misses.
  - With the paths read at run time, a fresh worktree's test build fell
    from 88 s and 643 CPU-seconds to 27 s and 74, every executable
    restored.
  - A landing's prebuild after `main` moved fell from 118 s and 705
    CPU-seconds to 44 s and 147, compiling nothing (section 7.1).
- **The dev profile costs a quarter** (section 4.4):
  - `panic = "abort"` makes cargo build 131 dependencies twice, once
    for the binaries and once unwinding for the test harness: 16% of a
    cold test build's CPU.
  - Line tables in every dependency cost 18%, and 40% of the target's
    disk.
  - Without both, the build takes 27% less CPU.
- **The scheduler** (section 5): with four agents landing among each
  other's work, today's `heavy` took 164 s per landing, 121 s of it the
  gate waiting for the load to settle. CPU weights instead of a queue
  took 68 s, and the agents' own steps got faster, not slower. `heavy`
  now weights its tasks; `--gate` stays exclusive, for what needs a quiet
  machine.
- **The store** (section 6): Garage serves reads well (p50 93 ms;
  200 MB executables in about 1.2 s). Its limits are space and
  retention: at a busy hour's upload rate, the 80 GiB the pruner keeps
  holds under two hours.
- **The changes, in order,** are section 8.

## 2. The priorities

The classes, highest first, as `heavy` weights them
(build-infrastructure.md, 2):

| Class | Weight | What | Why there |
|---|---|---|---|
| Landing | 10000 | A prove's or a landing's prebuild and gate (`heavy --land`, or a `land ...` label) | Every landing of the fleet waits on it, and its gate is timed against wall-time budgets |
| Build | 1000 | An agent's builds: narrow steps and end steps | An agent waits on each |
| Background | 100 | After-landing's tiers, when they run again (`HEAVY_CLASS=background`) | Long and throughput-bound; slower costs little |
| Idle | idle | Warming a new `main`, speculative work (`HEAVY_CLASS=idle`) | Worth doing only on otherwise idle cores |

What the weighted run measured (section 5): landing work at 10000
against the agents' 1000 ran at about its speed alone, and nothing of
the agents' waited. The agents' narrow steps and end steps shared one
class; the end suites, side by side at 8 jobs, took a fifth longer than
under today's queue, and the narrow steps none, so a separate class for
end steps would buy little. With proves, most landing work runs outside
the set lock (landing-flow.md), and the weight follows it there.

## 3. Where the time goes

`heavy`'s events and receipts on the five machines, 10-23 00:11 to 10-25
13:54Z: 15,369 tasks over 285 machine-hours.

- **Gates, not slots, make builds wait.** Builds queued 201.8
  task-hours between submit and admission:
  - 71% inside gate-lane holds;
  - 24% with both build slots busy;
  - 6% in the 1.7 s a build takes to be admitted when nothing is ahead.
- **The gate lane held 27% of machine time,** in 1,768 holds:

  | Holder | Holds | Hours | Builds waited behind it | Busy cores while holding 8 |
  |---|---|---|---|---|
  | Landing gates (`check.sh`) | 574 | 20.7 | 31.2 h | 3.0 |
  | `after-landing.sh` | 266 | 21.5 | 49.2 h | 1.2 |
  | Other exclusive commands: `-j 1` measurements, proofs, `true`, kache setup | 928 | 34.8 | 62.0 h | 1.9 |

- **Half of each machine idles.** 42% of machine time had nothing
  running or queued. A build gets `CARGO_BUILD_JOBS=4` and averaged 2.5
  busy cores. Most commands are latency-bound: a narrow `nextest`
  averaged 1.4 cores, `nextest -p` 2.5, a workspace `nextest` 4.1.
- **`cargo fmt` went through `heavy` 1,593 times,** to run 2.7 h and
  wait 30.1 h. It builds nothing.
- **The prebuild is a landing's long step:** 544 runs, p50 124 s, and
  its `nextest --workspace --no-run` is 63% of that. Only 21% ran on a
  tree already built on that machine, since the rebase makes a new tree.
- **kache hit 55.9%** of cacheable compiles. Test executables were 58%
  of miss compile time, and only 11.7% of the executable keys a machine
  compiled were hit again, against 45.8% for libraries. Every local
  store sat at its 40 GiB cap.

## 4. One agent

### 4.1 The narrow step

A temper range of 26 edits, replayed with implementer.md's narrow
commands and no think time, on hetzner4 at 8 jobs:
- through kache, 178 s in all, p50 5.0 s, p90 13.4 s;
- through plain cargo with incremental compilation, 165 s, p50 4.4 s,
  p90 12.9 s.

The difference is mostly one repin's `cargo check --workspace --tests`,
13.4 s against 4.4 s, where kache's adaptive mode passed 138 crates
through uncached. One agent leaves 53% of the cores idle: a narrow step
is latency-bound, and what makes it fast is reuse, not width.

### 4.2 What a landing costs

land's prebuild and today's gate, bare, at temper X (`c10874db7`) and
Y (`7a5493899`: `main` after a jig repin and three commits landed on
X), 8 jobs, alone on hetzner2:

| Probe | Wall | CPU-s | What it compiled |
|---|---|---|---|
| The implementer's worktree at X: prebuild | 39 s | 194 | Clippy of the packages the implementer hadn't linted |
| The same: gate | 59 s | 216 | wasm clippy cold, 20 s: the prebuild builds no wasm |
| The same gate again | 38 s | 169 | Nothing: fmt 8 s, the tests 24 s |
| A fresh worktree at Y: prebuild | 163 s | 1,014 | 237 test executables (546 s of compile) |
| Its gate | 44 s | 175 | |
| The implementer's worktree moved to Y: prebuild | 118 s | 705 | 161 test executables passed through (508 s), 66 libraries (112 s) |
| Its gate | 43 s | 175 | |
| A fresh worktree at X, every library in the store: prebuild | 108 s | 629 | 167 test executables (430 s) |

The gate itself is cheap and stable, 38 to 59 s. What a landing pays
after `main` moves is the prebuild, and nearly all of that is test
executables compiled again although their sources didn't change.

### 4.3 Why worktrees don't share test binaries

- **Test code compiles its absolute paths in.** Test crates and the
  test-support libraries ("worlds") locate fixtures and binaries at
  compile time:
  - `env!("CARGO_MANIFEST_DIR")`, as in `tests/codecs/src/lib.rs`, and
    in a `const` built with `concat!` in `tools/gallery`;
  - `env!("CARGO_BIN_EXE_temper")`, used 78 times in temper;
  - `env!("CARGO_TARGET_TMPDIR")`.
- **kache keys them soundly.** rustc reports each such variable as an
  input, so its value, the worktree's path, enters the key; kache
  refuses to normalise `CARGO_MANIFEST_DIR`, since the path is compiled
  into the output. A world library misses in every new worktree, and so
  does every crate built on it: all the integration tests.
- **On `main`,** files reading such paths at compile time: temper 55,
  smith 70, skein 37, jig 15.
- **The fix is in the code.** cargo 1.95 and nextest 0.9.148 both set
  `CARGO_MANIFEST_DIR` and `CARGO_BIN_EXE_<name>` when a test runs.
  `CARGO_TARGET_TMPDIR` is compile-time only: the target's `tmp`
  beside the test executable stands in for it. One rule comes with it:
  at run time `CARGO_MANIFEST_DIR` is the running test's package, so a
  library locates a workspace file from the workspace root, never from
  its own directory.
- **Measured** on temper X, two fresh worktrees one after the other,
  hetzner4, 8 jobs, the store emptied first:

  | Worktree | Wall | CPU-s | kache |
  |---|---|---|---|
  | First, as on `main` | 133 s | 977 | Everything compiled |
  | Second, as on `main` | 89 s | 643 | Libraries hit; 289 test executables compiled again |
  | First, paths read at run time | 98 s | 650 | The rewritten crates and their dependents compiled |
  | Second, paths read at run time | **27 s** | **74** | 677 hits: every executable restored |

  A mechanical rewrite of 52 files made the change. The focused suite
  then passed except 25 tests, all failing at one line, in a world
  library that joined a relative path to its own manifest directory:
  the rule above.

### 4.4 The profile

The tests' build (`nextest run --workspace --no-run`), cold and
without kache, temper X, 8 jobs, hetzner4. The variant overrides one
setting of `~/.cargo/config.toml` or the workspace's profile. The base
ran twice, 1,084 and 1,015 CPU-seconds, so differences under about 7%
are noise:

| Variant | Wall | CPU-s | Against base | Target | Of it, test executables |
|---|---|---|---|---|---|
| As today: `panic = "abort"`, line tables everywhere | 138–148 s | 1,050 | | 42.6 GB | 35.4 GB |
| `panic = "unwind"` (two runs) | 117–120 s | 880 | −16% | 41.3 GB | 35.4 GB |
| No debug info in dependencies (two runs) | 117 s | 867 | −18% | 25.8 GB | 19.0 GB |
| Both | 103 s | 766 | **−27%** | 24.7 GB | 19.1 GB |
| No debug info at all | 108 s | 797 | −24% | 19.2 GB | 13.0 GB |
| `strip = "debuginfo"` | 117 s | 874 | −17% | 20.2 GB | 13.1 GB |
| `split-debuginfo = "unpacked"` | 128 s | 951 | −9% | 31.6 GB | 24.3 GB |
| No frame pointers (two runs) | 132–134 s | 987 | −6% | 42.7 GB | 35.5 GB |
| `opt-level = 1` for dependencies | 257 s | 1,923 | +83% | 49.9 GB | 42.3 GB |

The focused suite's run took 9.5 to 13.4 s under every variant but the
last (6.2 s), within its noise.

- **`panic = "abort"` builds the dependencies twice.** All four
  repositories set it in `[profile.dev]` ("panics are fail-stop"). The
  test harness needs unwinding, so cargo builds every dependency of
  both the binaries and the tests twice: 131 libraries in temper.
- **Fail-stop doesn't need the profile.** A panic hook that prints and
  then aborts, installed first in each binary's `main`, gives the same
  behaviour under `panic = "unwind"`. The release profile can keep
  `abort`. The fail-stop rule is the programming model's, so this is
  the user's decision.
- **Debug info:** `~/.cargo/config.toml` sets `debug =
  "line-tables-only"` for the dev and test profiles. Dropping it for
  dependencies alone (`[profile.dev.package."*"] debug = false`, and the
  same for test) keeps line numbers in the workspace's own frames, where
  an agent reads a backtrace, and halves the executables. Stripping or
  dropping all debug info saves a little more, but loses those line
  numbers too.
- **Not worth it:** `opt-level = 1` for dependencies, which nearly
  doubles the build to save seconds of test time; and dropping frame
  pointers, a gain near the noise that would cost profiling.

## 5. Agents side by side

Four agents replayed real ranges side by side, each landing at its end:
- a1 and a2 on temper, a3 on jig, a5 on smith;
- staggered starts, think time drawn from the traces;
- the store holding what landings of the bases left;
- executables not cached, to fit the disk (section 6).

The same replay ran under each scheduler, on twin machines:

| Scheduler | |
|---|---|
| Today, on hetzner2 | `heavy`: 2 build slots of 4 jobs; the gate exclusive, at 8 jobs, after the builds drain and the load settles |
| Weighted, on hetzner4 | No queue: every command at once at 8 jobs, in a cgroup slice by class: landing 10000, the agents' work 1000 |

| | Today | Weighted |
|---|---|---|
| A landing, prebuild plus gate, waits included (mean of 4) | 164 s | **68 s** |
| The gate's wait before it ran (p50) | 121 s | 0 s |
| An agent's edit step, p50 / p90 | 4.9 s / 26.0 s | 4.1 s / 20.4 s |
| Waits of the 74 edit steps, total | 211 s | 0 s |
| End clippy (p50) | 56 s | 28 s |
| End focused suite (p50) | 145 s | 178 s |
| The whole run | 2,039 s | 1,759 s |
| Cores idle while a command was running or waiting | 41% | 34% |
| Lowest free memory | 10.4 GiB | 9.2 GiB |

- **Landing is where today's scheduler hurts.** The gate's 121 s wait
  is the settle: it waits for the load average to drop below the cores,
  and with four agents working it never does before the 120 s cap.
- **Weights deliver both priorities.** Landing work never waited and
  ran at about its speed alone. The agents' steps were faster too, with
  no admission queue in front of them.
- **The one cost** is throughput work at the agents' weight: the end
  focused suites ran side by side at 8 jobs each, and took a fifth
  longer.
- **What idles under weights is idleness, not waiting.** No command
  waited, so the 34% of cores left were cores with nothing runnable: a
  narrow step uses 1 to 3 of them.
- **Memory held:** at worst 9.2 GiB of 15.6 free, and no gate failed
  but on the test the simulation's environment fails anyway. One
  difference is the runner's: `heavy` runs payloads under umask 077,
  which that test, about a private key file, needs.
- **Two runs were void,** both instructive:
  - The disk floor: four warm worktrees and the store's copies left 21
    GB, under the floor, and `heavy` refused every build (section 6).
  - The clean tree: a candidate with the gate's script written into it
    was refused by `heavy`'s check, as it should be.

## 6. The store

- **Reads are fast.** hetzner2's 2,152 remote hits in its last day of
  events: p50 93 ms, p90 372 ms. Executables of about 195 MB came in 1.1
  to 1.3 s, about 160 MB/s. Fetching took 0.11 h and saved 0.47 h of
  compiling. Keys match across machines whenever paths do: `land`'s
  set worktrees have the same path on every machine.
- **The 64 MiB upload limit is on the compressed pack,** so most test
  executables do upload.
- **Upload failures follow load and quota:** 4,992 on hetzner2 since
  10-24, almost all the client's 30 s timeout while writing a pack of
  about 28 MB:
  - 4,244 on 10-24 between 15:00 and 21:00Z, when the bucket hit its
    quota and hetzner3 was also building;
  - 535 at 09:30Z on 10-25, while Garage restarted.
- **The volume is slow for synchronous writes.** Garage's data and its
  lmdb metadata live on the 120 GB Hetzner volume:

  | | Sequential write | Sequential read | Synced 4 KiB writes |
  |---|---|---|---|
  | Volume `/srv/kache-store` | 236 MB/s | 205 MB/s | 7.8 ms each |
  | hetzner3's local disk | 868 MB/s | 1.8 GB/s | 1.1 ms each |

  hetzner3 builds nothing now, so the reason for a separate disk is
  gone. Its local disk has 225 GB free, against the volume's 31 GiB.
- **Retention is the store's limit.** Objects expire a day after
  upload, and the pruner holds the bucket between 70 and 80 GiB. On
  10-24 uploads ran at about 48 GiB per busy hour (build-cache.md 5), so
  an entry can be gone within two hours of its upload. With the paths
  read at run time, test executables become worth sharing, and space
  matters more.
- **Local stores are disk on top of the targets.** They are 40 GiB,
  full on every machine.
  - kache copies what it stores: hetzner2's daemon reports 139 GB
    copied against 10.5 GB hardlinked, the rest "ineligible" for a
    link.
  - None of the 42 GB in hetzner2's store shares a block with a target.
  - Restores hardlink more often: 27 GB, against 36 GB copied.

  A full store is mostly test executables, which no other worktree can
  hit today (section 4.3).
- **Disk binds before CPU.** In the four-agent runs, four warm
  worktrees took 121 GB. With the simulation's store holding copies of
  their executables, that left 21 GB of hetzner2's 301 GB, under
  `heavy`'s 40 GB floor, and `heavy` refused every build (section 5).

## 7. Landing in the mix

### 7.1 The landing probes, with paths read at run time

Section 4.2's probes again on hetzner4, with every checkout's
compile-time paths rewritten to run-time lookups. The rewrite covered
51 files and passed fmt and clippy with `-D warnings`. Every gate
passed: focused, fuzzy and the lab tests.

| Probe | As on `main` | Paths read at run time |
|---|---|---|
| The implementer's worktree at X: prebuild, gate, gate again | 39, 59, 38 s | 40, 60, 39 s |
| A fresh worktree at Y: prebuild | 163 s, 1,014 CPU-s | 157 s, 972 CPU-s |
| Its gate | 44 s | 44 s |
| **The implementer's worktree moved to Y: prebuild** | **118 s, 705 CPU-s** | **44 s, 147 CPU-s**: 773 hits, nothing compiled |
| Its gate | 43 s | 47 s |
| **A fresh worktree at X: prebuild** | **108 s, 629 CPU-s** | **54 s, 176 CPU-s**: 1,409 hits, nothing compiled |

- **A landing after `main` moved costs what a first landing costs**,
  91 s against 100 s, and compiles nothing once the store holds the new
  `main`. Today it costs 161 s.
- **The no-compile floor is about 40 s:** fmt's check (8 s), then
  clippy's and the tests' restores. Each hit costs about 0.3 s of key
  hashing, mostly of large upstream libraries.
- **New upstream code still costs its compile,** as at Y, a jig repin:
  157 s. Of it, 234 compiles (140 s) produced byte-identical outputs
  under new keys ("dup"), because a key includes its dependencies'
  hashes. A key that cut off at an unchanged interface would save them;
  that is kache's to change, not ours.

### 7.2 Landings among agents

The four-agent runs landed each set at its end, among the other agents'
work: 164 s per landing under today's `heavy`, 68 s under weights
(section 5).

## 8. The changes

In order. Changes 1 to 3 landed on 10-25, each through its repositories'
gates: 1 as two sets (skein's new crate first, then its consumers), 2 as
one, 3 with this document. 7 followed 3 on 10-26. The rest are
proposals.

| # | Change | Where | Gain | Cost or risk |
|---|---|---|---|---|
| 1 | Dev profile: `panic = "unwind"`, fail-stop by `skein_fail_stop::install()` first in every binary, checked by each gate; no debug info in dependencies | All five; skein's crate first, then the four | A cold test build −27% CPU, the target −42% | Every unit's key changes once; a binary that skipped the hook would unwind in dev (the gate's check) |
| 2 | Tests read their paths at run time: `skein_scratch::paths` | skein's helper first, then smith, jig, temper | A fresh worktree's tests 88 s → 27 s; a regate after `main` moved 118 s → 44 s; executables shared across machines | A library other packages' tests call finds files from the workspace root (testing-strategy.md, 8) |
| 3 | `heavy`: CPU weights, no build slots, all cores; `--land` for landing gates, one at a time; `--gate` exclusive; builds die first out of memory; fmt direct | agents | A landing among four agents 164 s → 68 s | A gate shares the machine; reviewed with the landing session |
| 4 | Implementers end with the gate's exact clippy and the focused suite, once 2 is in | agents' `implementer.md` | The landing's build moves off the lock and is restored, not compiled | None measured |
| 5 | After-landing's tiers, when they return, at `HEAVY_CLASS=background`, not `--gate` | agents | 21.5 h of exclusive holds in the traces | Timing-sensitive tiers run under load |
| 6 | The prebuild lints the wasm targets, so the gate's first wasm clippy isn't cold | land, the landing session's | 20 s off each temper gate | None |
| 7 | `heavy` without pueue: each wrapper a user unit of its own, task numbers and holds in the ledger alone, each lane in submission order (build-infrastructure.md, 1–7) | agents | One store of task state instead of two, no pauses to keep in step with the holds, no reused task numbers | A drained fleet to land and to roll back; waiting gates poll the ledger as waiting builds do |

Not now:
- **The store's disk:** reads are fast and the failures were explained;
  retention matters once 2 makes executables worth sharing. Revisit
  then, with the remote hit rate.
- **A filesystem with clones** (XFS, or btrfs with compression) would
  stop the store's copies costing disk. Revisit if disk still binds
  after 1 and 2.

## 9. How it was measured

- **Replayed history.** 10-25's landed sets, commit by commit, from
  their real bases. After each commit, implementer.md 1's narrow
  command; at a range's end its clippy and focused suite; then land's
  prebuild and the gate, bare. Think time is drawn from the gaps between
  one worktree's submissions in `heavy`'s events.
- **Isolated:** local clones and bare mirrors on each machine, its own
  kache daemon, store and `CARGO_HOME`, its own pueue for today's
  `heavy`. Nothing reached GitHub or the fleet's store.
- **Measured per command:** wall time, CPU-seconds and memory peak from
  its transient cgroup; per machine, CPU and memory every second; per
  unit, kache's events.
- **Caveats:**
  - Most probes ran once. A repeat of the profile's base variant gives
    their noise (section 4.4).
  - Two gate tests fail in the simulation's environment (temper's
    `fake refused_start`, smith's
    `host_id_drawn_by_two_processes_is_one_value`), so its gates run
    with `--no-fail-fast` and cost the whole suite.
- **The harness** was throwaway code in this session's worktree, gone
  with it (cleanup.md 2).

## 10. Open

- **A crate new upstream, used downstream in the same set,** can't land
  in one `land-set` run: moving a downstream's other pins re-resolves the
  upstream to its `main`, which lacks the crate. Such a change lands its
  upstream first, the others pin-only, then its consumers, as change 1
  did. A change to what skein generates for its consumers (change 2's
  patch-module template) is the opposite case: the consumers' generated
  files must move in the same set. The landing session's to fix, if it
  recurs.
- **The store's disk:** hetzner3's local disk, or a larger volume,
  once change 2 makes executables worth sharing (the user, 10-25: not
  now).
