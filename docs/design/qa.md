# QA

2026-10-30. Keeper: s/qa. Walks, custody and walk evidence preservation are
built; unattended passes and live tiers are planned. Code: `tools/qa/`.

## 1. In one page

- **QA exercises product stories with real signed-in use.** Rung owners ask
  for walks on held logins; QA after landing will exercise marked stories on
  published main commits. A clean pass is evidence about those stories, not
  proof that a merge caused or cannot cause a fault.
- **Walks come first.** The builder admits walks and resumes by kind and
  numeric slot. Planned passes reserve login capacity for walks. Live tiers
  are to run between walks, following director decisions 0007/0001 (external
  director decisions, as assigned by the coordinator).
- **Custody is explicit.** One holder owns each login until it is safely back
  at rest. Tools never read login contents. No operator changes custody by hand.
- **The watcher finishes what it starts.** Saved attempts, claims, launch
  recovery and independent retried end steps survive interruptions. Unknown
  liveness or ownership preserves custody and prevents conflicting admission.
- **Results must survive scratch.** Walk ends keep scanned allowlisted
  evidence locally by default, with opt-in private publication and guarded
  seven-day scratch pruning. Planned passes preserve required safe results
  too. Records implementation is paused by the user; the first pass version publishes QA-owned data without changing records.

## 2. Responsibilities and boundaries

**QA owns custody and the QA builder's walk service.** `logins` arbitrates
exclusive holds; `qa` admits and supervises work, deployments and cleanup.
The rung owner supplies the brief, reads the walk report and files findings.
The director resolves unknown holders, stuck returns and ownership exceptions.
Command syntax, configuration and detailed recovery rules stay in
`tools/qa/logins.md` and `tools/qa/qa.md`.

**Fabrig owns its merge queue and publication facts.** QA does not land code
or make its verdict a merge gate. Planned passes require the queue's durable
pre-push intent and confirmed merge feed, including immutable coordinator
routes. QA validates those facts against the fetched commit graph; ready refs
and uncertain pushes cannot create work. `tools/qa/passes.md`, sections 2
and 13a, specify this producer prerequisite and QA's read-only feed transport.

**After-landing owns the slow-tier verdict.** QA consumes a confirmed green
covering the enrolled profiles, selects an exact eligible main SHA and
revalidates before launch. It neither writes nor substitutes a runner verdict.
See `tools/after-landing/design.md`, sections 3, 4 and 6, and
`tools/qa/passes.md`, sections 4 and 13a. Live tiers scheduled between walks
are a separate planned responsibility, not an assertion that they run today.

**Records is an existing read-only input for the first pass version.** The
user has paused records changes for scope review. Read existing after-landing
facts; do not add QA writers, schemas, permissions or collector projections.
Publish QA reports, controls, verdicts and delivery history on the private
`fabrig-ai/qa` repository's `evidence` branch instead. Section 13a of
`tools/qa/passes.md` overrides that reference's earlier records destinations.

**The reaper does not acquire QA's authority to return logins.** Process or
scratch cleanup must respect held resources and uncertain launches; QA's
verified end protocol owns login returns and claim release. Evidence retention
and seven-day pruning are QA policy, not permission for general cleanup to
remove live or paused work.

**Pipeline-watch consumes metadata contracts.** Its QA observations use
`logins list --json` and `qa queue --json`, rather than parsing human output
or inspecting a login. These additive contracts retain field names, types and
meaning; consumers ignore added fields. Invalid state emits no partial JSON.
Fixtures and exact fields are in `tools/qa/logins.md`, “JSON contract”, and
`tools/qa/qa.md`, “Queued starts and resumes”. These interfaces do not imply
that pipeline-watch's deferred login-held alert rule is built.

## 3. Login custody

**A login is a resource, never readable input to QA.** The registry records
name, resting path, holder, original take time, note and optional run identity.
A caller uses the product's import/export protocol for a moved login or uses
a configuration directory in place. Custody itself does not move or inspect
contents and does not certify that an account is valid.

**Serialize decisions and preserve ownership.** Custody uses a global lock
then login locks in name order. Metadata is replaced through sibling files and
rename; ordered custody updates are not a cross-file transaction. Ordinary
requests share a fair queue; QA uses immediate pooled takes without reserving
logins ahead of walks. Only the matching holder can give a login, and only
when it is safely back at rest. Unsafe or missing state refuses operations.

**Bind runs after launch.** Starts normally take before a run ID exists. QA
attaches the acknowledged or recovered run to its current holds and retries
failed bindings. A resume gets its own run binding. Neither holder names nor
old attempts supply an inferred run. Details remain in `tools/qa/logins.md`.

## 4. Walk admission and execution

**A kind's ordered numeric slots define its cap.** Count manual, stuck and
in-flight holdings too. Under the shared admission lock, select a free
configured slot and obtain a central claim with a unique saved lifetime token.
Never create a fallback checkout or borrow another owner's slot. Validate the
existing clone, origin and local work before preparing an exact fetched SHA.

**Preparation precedes login takes.** Preserve unowned checkout work, use the
existing slot's warm target, and require at least 80,000,000,000 free bytes on
the root filesystem before admission. The walk brief requires the same floor
before each heavy command, waiting and rechecking below it. Builds use the
builder's background heavy class. Detailed preparation and disk rules are in
`tools/qa/qa.md`, “State, start and resume”.

**Persist the attempt before effects.** Save claims, grants, checkout identity,
launch intent and cleanup progress; pass the admission lock into takers and
launchers. The watcher recovers uncertain launches from matching metadata and
launcher observations. A missing run ID or ended worker marker alone cannot
prove that the session and its deployments have stopped.

**Queue scarcity and dependencies.** Starts and resumes waiting for scratch
bytes, a slot, login, pending release or landed dependency retain their
request and starter. Admission failures keep one notice per queue entry and
step; changing diagnostics update its receipt without another accepted message.
The watcher tries ready entries by kind after cleanup, without letting a busy
entry block later ready work. Main resolves at admission. Saved admission
identity prevents a recovered launch from starting twice. Resumes keep the
walk identity, history and numeric slot, but acquire fresh grants after a
completed pause. See `tools/qa/qa.md`, “Queued starts and resumes”.

## 5. Watching, ending and reconciliation

**Finish each end step independently.** At the cap, stop the session and
confirm its unit, jobs and launchers stopped, including its give-back wrapper.
Return moved logins before stopping deployments, confirm their stops, then
return in-place logins. Give only verified matching holds. Release a claim
only after all grants are returned and stop checks succeed, using the exact
saved owner and lifetime token. Retry unconfirmed returns, releases, clock
entries and posts on subsequent checks. Only after every walk has received its
custody cleanup attempt, scan evidence outside admission; enumeration is
bounded by entry count, depth and elapsed time.

**Uncertainty retains resources.** Invalid inventory or state cannot authorize
a give. Unknown holders are left held and reported. Foreign legacy states
remain opaque. Orphan QA slot claims require repeated unambiguously idle
observations, the grace period and a fresh ownership check before token-checked
release. Another owner's or successor's claim is never released.

**Pause keeps work, not active resources.** A completed pause frees grants and
the slot while retaining notes and deployment instructions for resume. Stuck
ends keep cleanup pending. Notices and completion posts have saved receipts;
failed sends retry, and acceptance followed by a crash may repeat delivery.
Notice identities contain only the queue entry, walk/attempt or claim lifetime
and step, never exception text, diagnostic paths or times. The latest subject
and diagnostic replace the text in the same receipt without clearing delivery.
The watcher commits no walk record today. Full ordering and orphan rules are
in `tools/qa/qa.md`, “Deployment and cleanup”.

## 6. Passes after landing

**Schedule marked landings, not arbitrary history.** The planned service starts
from an explicit main boundary, reads `QA:` stories on confirmed queue merges
and tracks defaults and explicit run/backlog decisions by ancestry. A pass
batches at most five marked merges on an eligible after-landing green SHA,
with a 120-minute cap. It saves selection, launch and publication authority so
restart cannot duplicate a consumed request.

**Reuse custody and lifetime rules.** Dedicated pass slots cannot overlap walk
slots. A shared admission lock and login reserve protect walks; stuck holdings
still consume capacity. Publication or feed failures block new passes while
cleanup continues. No pass implementation or activation is implied here.

**Publish before routing findings.** Required safe reports and complete results
survive refusal of optional captures. Findings use the landing's saved
coordinator route, with unresolved routes going to the director; they do not
establish causality. Stable revisions, event identities and delivery receipts
support retries. `tools/qa/passes.md`, sections 3–8, 10–13a, is the detailed
contract, with section 13a controlling first-version destinations and rollout.

## 7. Evidence and retention

**Scan exactly the bytes to be published.** Walk preservation snapshots
only allowed documents, scripts and captures, with ownership, link, type,
size and secret-shape checks on every path component and the whole path.
Never inspect a login or a suspected credential to diagnose a refusal. Publish append-only private evidence; retry uncertain
publication without replacing its saved identity. Required results and optional
scratch captures have separate preservation obligations.

**Admission accounts for scratch bytes.** Active walks reserve 2 GB each
against a default 48 GB budget. Retained ended and paused/pinned directories
contribute measured bytes; pinned active scratch also contributes its size.
Size measurement streams metadata through anchored directory descriptors,
never reads file contents or follows links, and has no entry or depth cap.
Each walk has one ten-second deadline shared across its normal and quarantine
names. An incomplete measurement charges max(saved reservation, bytes counted
so far), reserves one retried director notice and retries on later admission
passes. Missing names explained by a quarantine rename or confirmed prune are
expected; an unexplained absence keeps the reservation floor. Evidence scans
retain their separate 4096-entry, depth-32, five-second bounds.
Resumes exclude their own unpinned paused contribution from the initial total
and add a new reservation; changing measurements cannot subtract other work.
Scarcity queues through the existing admission queue before claiming or taking a login.

**Seven days is conditional scratch expiry.** Final keep, durable status and
notices, returned logins, stopped units/jobs/launchers and confirmed claim
release precede deletion of owned ended scratch. Pending publication or custody
retains it; paused walks are never age-pruned. Preserve small state and
outboxes, evidence history, login registry, slots, warm targets and transcripts.
`tools/qa/passes.md`, sections 9 and 13a, specifies scans and pruning. Walk
preservation is built: remote publication requires both an explicitly set
repository and branch. Safe local copies and receipts survive scratch, pins and pauses prevent age-pruning, and an
accepted scan refusal can expire after seven days. The evidence refusal notice
and starter's refused status each have one stable walk/step identity; changing
refusal diagnostics refresh the saved receipt without another accepted message.
Remote retries follow custody cleanup outside admission; they never delay
returns/releases.
Ordinary exceptions from a walk's measurement, preservation or pruning step
cannot end the watcher: continue other walks and retry the step next pass.
Queued admission failures likewise leave the preservation phase running.
Scratch identity (device/inode) is saved at creation. Pruning atomically
quarantines the candidate under its anchored parent, verifies that identity
and removes through its descriptor. A mismatch is retained and restored when
the original name is free; missing identities retain scratch with one retried
notice. Retention requires a concrete end time consistent with the walk start.
Pass preservation and required result publication remain planned.

## 8. Later

- Build and activate passes only after queue producer, feed coverage,
  publication, lifetime and scheduler acceptance checks in `tools/qa/passes.md`.
- Reuse the built walk scanner/publisher for passes and their required result
  publication when passes are implemented.
- Schedule live tiers between walks under director decisions 0007/0001;
  agree concrete enrollment and scheduling with the tier owners before activation.
- Revisit records integration only after the user's scope review; retain the
  first-version read-only boundary until then.
