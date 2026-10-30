<!-- The user's execution model, copied verbatim from the Claude Docs doc of 2026-10-30
     (https://claude.ai/artifact/WEpCY6bb7m3Tn9onFdFKEr). The user's input: agents read it,
     never edit it. -->

# Execution modes for the code-producing pipeline

2026-10-30 · Free

## In one page

The pipeline runs every draft through one shared mechanism, configured by one of four execution modes; a big feature uses Feature mode, which starts its first implementer about an hour after the draft lands and delivers working end-to-end slices from about T+6. Claude designs and reviews in short calls, code runs the loop, and Codex writes the bulk, for a Claude to Codex weight near 0.1-0.2 instead of today's 1.09. The times and costs below are estimates.

- **One mechanism, four presets.** The dispatcher, gates, merge queue, ledger and the Claude and Codex roles are shared. Feature, Migration, Fix and Probe set what is designed, in what order, and how much Claude is involved. One draft can mix modes, part by part.
- **Claude is called, not resident.** Every Claude call is a fresh session on a brief that code compiles from files, under about 120k tokens, and ends by writing files. No Claude session waits, polls or watches a run.
- **Design flows part by part (Feature mode).** A thin cut names the parts, their dependencies, the shared contracts and the slices, without detail. Each part is then designed on its own, several at once, and shared contracts are early parts that only their readers wait for.
- **Design is pulled, not pushed.** The dispatcher keeps a buffer of ready tasks about one to two times the implementer slots, and asks for the next part's design when it runs low. Design stays just ahead of the code, so later parts are designed with what earlier ones taught.
- **Skeletons fix the shape.** Each part's design ends as code: modules, types, the shared primitives' signatures with doc comments, `todo!()` bodies, and the test vocabulary. Codex fills bodies inside that shape, so later work fills in rather than restructures.
- **Slices set the order of filling.** A slice is the smallest piece of work that runs a story end to end on main; the next slice fills more bodies and widens the cases. QA walks only the two or three slices where a user-visible story completes.
- **Quality is checked on every branch.** Code gates (clones, size, the public API against the skeleton, names, docs), a Codex self-critique, and a structure digest Claude reads in batches; consolidation runs on a cadence.
- **Judgement comes in batches.** Questions and skeleton amendments wait for an answer call every 2 hours or at 4 queued, and only the task that needs the answer parks.

## One mechanism

Every mode uses the same roles and files; a mode only decides which roles a part goes through and in what order. Three roles are code, six are Codex and four are Claude calls, with QA walking as its own design says; none of the Claude roles stays alive between jobs.

| Role | Run by | Does |
|---|---|---|
| Dispatcher | code | Reads `plan.md`, keeps the ready-task buffer, launches runs in dependency order, claims slots, prechecks, readies, compiles briefs, classifies events, keeps the ledger as data |
| Gates | code | On every branch: clone detection, function length and complexity caps, the public API against the skeleton, banned vague names, doc comments on public items; writes the branch's structure digest |
| Merge queue | code | Lands a set of branches as one candidate, reusing precheck receipts; classifies reds before anyone hears them |
| Surveyor | Codex, medium, read-only | Readers of what changes, the primitives in reach with their signatures, the test world in use, summaries for Claude |
| Foreman | Codex, medium | Reads reports, settles questions a task's pre-approved options answer, writes rebase and mechanical repair tasks |
| Implementer | Codex, high | Fills the named bodies of one module or concept, about 400-500 production lines, with precheck and merged readers' tests inside the run |
| Test-writer | Codex, high | Acceptance tests from the design, in the area's test vocabulary, apart from the implementer |
| Self-critic | Codex, high, read-only | Reviews a branch against its skeleton, the taste file and the gates' output; the implementer fixes what it finds before ready |
| Reviewer | Codex, medium, read-only | Checks each Claude output for contradictions and layering, at most 10 lines |
| QA walker | as the QA design says | Walks a walkable slice on real backends; its findings enter Fix mode |
| Designer | Claude, high | The cut, shared contracts, decisions after a probe, retiring the draft |
| Skeleton author | Claude, high | A part's compiling skeleton, test vocabulary and task specs; small amendments when a primitive is missing |
| Answerer | Claude, medium | Queued design questions and amendment requests, in one pass every 2 hours or at 4 |
| Structure reviewer | Claude, high | Every branch's digest, full code for flags and a sample; names consolidations and grows the taste file |

The memory is files, not sessions: `plan.md` (parts, dependencies, modes, slices, each part's state), the design sections, the skeletons, the taste file (good and bad pairs from this codebase), the primitives inventory, and the ledger as data.

Every Claude call follows five rules:

- **Its brief is compiled by code** from those files, never gathered by a Claude session reading around.
- **It has a hard budget** of about 120k context tokens and no shell loop; a skeleton call may run the build to fix its own compile errors.
- **Its structural decisions are code where they can be:** a skeleton, a test helper, a taste-file pair. Codex follows code more reliably than prose.
- **Its output is a file** a Codex reviewer and the gates check before the dispatcher acts on it.
- **Calls on independent parts run in parallel.** Total cost depends on the work, not the concurrency.

## Four modes

Feature mode is the one specified in full below; the other three are presets of the same mechanism, sketched here so the picture is complete. Claude's share falls from Feature to Fix, where it is near zero.

|  | Feature | Migration | Fix | Probe |
|---|---|---|---|---|
| When | A new capability, like `landing-model.md` | A change of form across the code, like dynamic memory | A finding, a red, a bug | A design question that must be answered before committing |
| Unit of flow | A part, pulled by the ready-task buffer | A crate or lane, in crate-graph order | One finding | One question, time-boxed |
| Claude designs | The cut, shared contracts, a skeleton and test vocabulary per part | The target form, the recipe and the ratchet's forms | Nothing by default | The question and its success criteria, then the decision |
| Order of work | Slices: what makes the next story run, within dependency order | Expand, move, contract; one root end to end first | Reproduce in the lowest tier, then fix | The cheapest experiment that answers the question |
| Codex does | Fills bodies, in tasks of about 400-500 production lines | Codemod-sized tasks per crate | The reproduction test, the fix, the self-critique | Builds the experiment, measures, reports |
| Quality | Skeletons, gates, digests, consolidation on a cadence | The ratchet, gates, and tests unchanged in meaning | Gates; a test that failed before the fix; a ledger class that ends in a tool check | The code is thrown away, or reaches main only through Feature mode |
| QA | At the walkable slices | At the end, and the after-landing tiers | The finding's own walk, rerun unchanged | None |
| Claude involvement | Highest, mostly design | Low | Only when the fix touches a public item, or after two failed tries | Short and medium |

How a draft mixes them:

- **The cut assigns a mode to each part.** A feature draft usually holds a Migration part (what it deletes or reshapes) and a Probe or two (its open questions with a measurable answer).
- **Modes hand over.** A Probe's decision becomes a design section and often a Feature part. A Fix that needs a new public item becomes a skeleton amendment, through the answer queue. QA's findings enter Fix mode.
- **The gates decide when Fix wakes Claude,** not a person or an agent's judgement: a change to a public item, or a second failed try.

## Feature mode

A part moves from the cut to a landed slice without waiting for anything but the parts it depends on. Claude touches it in three places: the cut, its skeleton call, and the structure reviews of its branches.

(A diagram appears here in the original doc.)

The top row is design, pulled by the ready-task buffer; the middle row is the code's path to main; the bottom row is the side loops: QA on walkable slices, structure review and consolidation on a cadence, and batched answers.

### The thin cut

- **About 20-30 minutes, output ****`plan.md`****.** The parts, each with its mode and dependencies; the shared contracts as parts of their own; the slices, each naming the parts and bodies its story needs and whether it is walkable; the user's questions. No signatures and no task specs yet.
- **A part** holds one concept and is small enough for one skeleton call to design: about 2-6 tasks.
- **The order** is contracts first, then the parts of slice 1, then slice 2, and so on; parts that touch no contract can start at once.

### Shared contracts are early parts

- **A contract part** is a stored format, public interface or protocol that more than one part reads. The designer writes it, a Codex reviewer checks it, and it lands alone as a skeleton.
- **Only its readers wait for it.** Hard-to-reverse work still comes first, but it no longer holds back parts that don't touch it.

### The pull buffer

- **The dispatcher keeps between one and two times the implementer slots in ready tasks.** Below one times, it starts the next parts' skeleton calls in backlog order, several at once if needed; above two times, it starts none.
- **Why a ceiling:** design stays only as far ahead as the code needs, so each part is designed with what the parts before it taught. That is the "detailed as knowledge arrives" rule, enforced by code instead of judgement.

### Skeletons

- **A skeleton call writes code, not prose:** the part's modules, types, shared primitives' signatures with doc comments, `todo!()` bodies, its test vocabulary (builders, fixtures, assertion helpers) and an exemplar test, plus its task specs. It runs the build and fixes its own compile errors.
- **Before each call,** a Codex survey refreshes the primitives in reach, so parts designed in parallel reuse what has landed instead of inventing their own.
- **The skeleton lands alone,** and its public API becomes the baseline the gates check every later branch against. A missing primitive is an amendment through the answer queue, never an implementer's improvisation.

### Slices

- **A slice is the smallest work that runs a story end to end on main:** words, a subsystem, or a user-visible flow, depending on the draft. It is complete when its story test passes on main.
- **Slices order the filling, not the shape.** The next slice fills more `todo!()` bodies and widens the cases; it doesn't restructure what is there. A body no story reaches yet stays `todo!()`, and no body is ever filled with a placeholder to make a story pass.
- **Dependency order wins.** If a slice needs a contract that isn't settled, the slice waits; it never fakes the contract.
- **QA walks the walkable slices only,** usually two or three per draft where a user-visible story completes. The first is almost always worth walking: it finds the integration surprises while they are cheap.

### Quality on every branch

- **Gates, then a self-critique:** clones, size and complexity, the public API against the skeleton, banned vague names and missing docs, then a Codex review against the skeleton and the taste file. The implementer fixes both before precheck and merged readers' tests.
- **A structure digest** of each branch (new public items, function sizes, clones, names, test setup per assertion) goes to a Claude structure review every ~10 landed tasks or 4 hours, which reads full code only for flags and a sample.
- **Consolidation:** the review names the merges, renames and splits it sees across parts; they become tasks at the head of the buffer, and the taste file gains a pair for each lesson.

### Questions

- **The foreman settles** what a task's pre-approved options answer. Design questions and skeleton amendments queue for the answer call, every 2 hours or at 4 queued; only the task that needs the answer parks.
- **The user hears from the designer only,** in batches: budgets, machines, and what is hard to reverse.

## Example: `landing-model.md`

In Feature mode, section 15.4's build list becomes 2 contract parts, about 18 feature parts, 1 migration part and 1 probe, delivered as 5 slices. The first implementer starts at T+1:10, the first slice runs end to end at T+6:30, and the draft retires at about T+27:30, against T+3:40, T+6:30 and T+31 when design moved in whole waves. Everything here is simulated.

| Slice | The story that runs end to end | Parts | QA walk |
|---|---|---|---|
| S1 | One change lands through the new serializer on the fake forge, with its precheck receipts reused at the gate | contracts for keys and receipts (L5, L6) and for the serializer's state (L9); F1; L4; L11; the serializer's behaviour; jig's holds (J2-J4) | yes |
| S2 | A batch lands, a red batch bisects, and every outcome is classed before anyone hears it | L1 (shaped by the probe), L7, L8 | no |
| S3 | Trains land on a certified parent, a repair goes first, and a path has one writer | L2, L10, L12, J5-J9 | no |
| S4 | After-landing tiers follow main, findings reach their coordinator by role, and QA passes run | L13-L16, J10-J12 | yes |
| S5 | The same stories on GitHub, shown in the client and `ctl` | F2-F5, L19 | yes, on GitHub |

Beside the slices, the cut assigns two parts to other modes:

- **A Migration part:** section 15.3's deletions, today's joining across repositories and the `queue` way, carried out by recipe and ratchet once S1 has landed their replacement.
- **A Probe:** section 17's open question on the batch's size and when to batch, answered by replaying the merge queue's own history at several sizes, before L1's skeleton is written.

(A diagram appears here in the original doc.)

The implementers fill up within three hours and stay at the slot limit until the last slice, because skeleton calls arrive in small groups whenever the buffer runs low, never as one big wave.

The key moments:

- **T+0:00** The draft lands. Four Codex surveys start: readers of the landing types, jig's holds, the primitives in reach, each area's test world.
- **T+0:20 The thin cut** (Claude, 25 minutes). It writes `plan.md` with the parts, slices and modes above, and two user questions: one change per landing in v0.1.0 (L20), and deleting today's joining across repositories now (H9).
- **T+0:45 Five Claude calls in parallel:** the two contracts, the skeletons of F1 and jig's holds, which touch no contract, and the probe's framing.
- **T+1:00** The probe starts: Codex replays the queue's history at batch sizes of 4, 8 and 16, within a 2-hour budget.
- **T+1:10 The first implementers** start on F1 and jig's holds: five in flight.
- **T+2:15** The contracts land alone. Their readers are pulled: three skeleton calls in parallel for L4, L11 and the serializer's behaviour. F1's first set lands at T+2:30.
- **T+3:40** The probe's decision (Claude, 10 minutes) goes into `landing.md` 6.2, before L1's skeleton call at T+4:30.
- **T+4:00** The first answer batch: two questions and one skeleton amendment. The user's two answers have arrived, which unblocks the migration recipe.
- **T+5:30** The first structure review, after 10 landed tasks: two taste-file pairs and one consolidation task at the head of the buffer.
- **T+6:30 Slice 1 runs end to end.** QA walks it for an hour; of its three findings, two become Codex-only fixes and one touches a public item, so it waits for the next answer batch as an amendment.
- **T+7:30 to T+11** The migration's codemod tasks run beside slice 2, under the ratchet.
- **From T+11** The buffer keeps nine implementers busy; skeleton calls arrive two or three at a time as it runs low. Slices land at about T+11, T+16, T+21 and T+26, and QA walks S4 and S5.
- **T+27:30** The last call: status files brought current, a Codex consistency pass over the changed designs, the draft retired. The taste file stays for the next draft.

## Cost and measures

Feature mode spends about a seventh of today's Claude weight while Codex work stays near today's, so the Claude to Codex weight falls from 1.09 to about 0.1-0.2. The extra Claude spend over a lean design-only model goes into writing skeletons and reading digests, not into re-reading long contexts. The dynamic-memory column is measured from the evidence tarball; the other is an estimate for the example below.

|  | Dynamic memory, measured | Feature mode on `landing-model.md`, estimated |
|---|---|---|
| Claude | coordinator and 4 leads resident; 9,611 turns at a median 336-402k context | about 45 calls, most small; about 2,000 turns at about 60k context, capped at 120k |
| Claude weight | about 484M | about 50-90M |
| Code Claude writes | none (task files and docs) | skeletons and test vocabulary, about 10-15% of the lines |
| Codex | about 89 hours, about 443M weight | about 100 hours (implementers 44, test-writers 20, self-critics 10, the rest 26), about 450-560M weight |
| Claude to Codex weight | 1.09 | about 0.1-0.2 |
| Tasks | 351 tasks, median 8 production lines | about 60 feature tasks of about 400 lines, plus consolidation, migration and fix tasks |
| Queue hops on a dependent chain | one per task, median 80 min from last commit to landed | one per set |

Weights are relative: input 1, cache write 1.25, cache read 0.1, output 5 for Claude and 8 for Codex.

The standing report tracks, per draft and per part:

- **Flow:** time to the first implementer, to the first landing and to each slice; implementers in flight against slots; the ready-task buffer against its band; questions per task and the share the foreman settled; queue hops and ready-to-landed time.
- **Quality:** rework (lines rewritten within 7 days of landing), digest flags per thousand lines, the duplication index, function sizes, test setup lines per assertion, skeleton amendments per task, and consolidation volume. Falling consolidation volume means the skeletons and the taste file are working.
- **Cost:** Claude to Codex weight (target at or under 0.2), Claude weight per landed production line, each call's peak context against the cap.
- **Overhead:** landings, tokens and slot-hours spent on the pipeline itself rather than the product.

## What to build first, and what is open

About three days of preparation lets Feature mode run its first trial: the contracts and slice 1 of `landing-model.md`, about 15 tasks, measured against the dynamic-memory numbers.

To build, in order:

- **The dispatcher loop** over the tools that already exist (`codex-run`, `claim`, `precheck`, `ready-check`, `post`, the queue): it reads `plan.md`, keeps the ready-task buffer, compiles briefs, starts Claude calls under their budget, and classifies events. A few hundred lines of Python, and later the first thing temper's own procedures replace.
- **The gates and the digest writer:** a clone detector, size and complexity caps, a public-API diff against the skeleton (for instance with `cargo public-api`), the banned-names list, doc-comment checks.
- **The role prompts** for the skeleton author, self-critic, structure reviewer and answerer, and a taste file seeded by one Claude call from good and bad code already in the repository.

How today's roles map onto it:

- **The coordinator** becomes the designer's calls; nothing resident remains.
- **Leads** disappear: their loop moves into the dispatcher, their light judgement to the foreman, their design to skeleton calls.
- **The operator** stays for the machines and the queue, with the ledger kept as data and its remedies as gates.

After Feature mode, Fix mode is next: it is the most frequent and the cheapest. Migration waits for the next large refactor, and Probe runs whenever a cut finds a measurable open question.

Still open, each to be set from the first trial's numbers:

- **Part size:** about 2-6 tasks per skeleton call is a guess.
- **The buffer band** of one to two times the implementer slots.
- **The review cadence** of about 10 landed tasks or 4 hours.
- **The answer interval** of 2 hours, which bounds how long a blocked task can park.
- **Who walks QA** (Codex or Claude), which is QA's own design to decide.
