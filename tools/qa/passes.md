# QA passes after landing

Provisional, 2026-10-30; revised after the round-2 review the same day.
Proposed contract for unattended fabrig passes; not implemented or activated.
Walks remain described by [qa.md](qa.md).

## 1. In one page

- **Owners mark stories in git.** A landed branch's commits carry one-line
  `QA:` trailers describing the stories or surfaces to exercise. The queue's
  published merges identify which commits arrived together (section 2).
- **Fabrig defaults on from an explicit starting main.** Ancestry determines
  coverage. `qa decide COMMIT backlog|run` changes an exception; `qa candidates`
  shows marked landings that no default, decision or pass covers (section 3).
- **The watcher starts passes.** It selects the newest main with a published
  after-landing **green** run containing the chosen merges, batches up to five
  marked merges per pass, and caps each session at 120 minutes (section 4).
- **A pass has one existing numeric slot.** Pass slots 2 and 6 on hetzner6 are
  dedicated s/qa shares, separate from the walk shares (section 13). Claims,
  preparation, launch recovery,
  deployment supervision and cleanup reuse today's walk contracts. ChatGPT
  passes leave two logins for walks; stuck holdings count (sections 5 and 6).
- **Results outlive scratch.** Reports are records files and per-merge verdicts
  are records events. A finding goes to the coordinator recorded for the
  landing that carried its trailer, with report and evidence paths. The
  director handles exceptions (sections 7 and 8).
- **Evidence is scanned before publication.** Keep the allowlist on the private
  `fabrig-ai/qa` repository's `evidence` branch. Prune ended walk and pass scratch
  after seven days only when preservation and custody allow it (section 9).
- **No deployment comes with this document.** Section 12 divides implementation
  at the queue, records, scheduler and cleanup boundaries. Section 13
  records the coordinator's answered activation questions.

## 2. The mark and the landing feed

The landing's owner writes `QA: <stories or surfaces to exercise>` in the final
trailer block of each relevant branch commit. The value is nonempty, one
physical line of at most 160 characters, without controls; multiple `QA:`
trailers or continuations on one commit refuse that mark and raise a metadata
exception. For example: `QA: temper ctl: retry an interrupted forge import and
check both sides` belongs on one line in the commit. A trailer names observable
behavior, not an instruction to run a test suite. A library change can name the
product surface through which its effect is visible. Tests-only changes need
no mark. Unmarked commits never create work by themselves.

The input is successful, nondry, published queue landings, not ready branches,
commit dates or every commit reachable from main. Fabrig's queue keeps branch
commits and makes a no-fast-forward merge `M` with first parent `P` and branch
tip `B` as second parent. For each feed merge validate those parents and main's
first-parent membership, then enumerate `git rev-list --reverse --topo-order
B ^P`. This excludes commits already present before the landing and includes
marked commits below nested branch merges. Read each message's trailer block
from git. Queue baseline commits above merges create no candidate. Branch
deletion after landing loses nothing: M retains B. If a marked commit is
reachable through several branches, its carrying landing is the first merge
on main's first-parent chain for which it is in `B ^P`; later landings do not
schedule it again. A merge with no new marks is ignored.

One scheduling item is **one marked merge**, with its ordered marked commit
SHAs and trailer values. All its marks travel together in a pass. This makes a
per-merge cleared verdict meaningful and avoids splitting one branch's story
between sessions. The batch of five is consequently five marked merges, a
departure from the legacy's five individual marked commits.

### 2.1 Queue producer prerequisite

The supplied fabrig main's `tools/queue/design.md` describes the external
`~/src/fabrig/notes/queue.jsonl` journal. Its `mq` computes each merged branch's
merge SHA, but does not persist a `merges` list in that journal. Today's
`tools/queue/leads.txt` has **two** columns, key and lead address, rather than
the coordinator column required here. Today's records collector projects
branches/tips and batch parent/commit, not per-merge landing routes. These
are required producer changes, not interfaces the QA reader can assume exist.

Before the queue's **first push**, durably commit a publication intent outside
its checkout, under its existing authority lock. The version-1 intent has a
stable `publication_id`, origin/ref, original batch parent, exact candidate
SHA, ordered merge entries, roster snapshot digest, created UTC time and the
exact prospective journal metadata. Each merge has `name` (ready branch),
`tip` (B), `commit` (M), `parent` (P), and the route fields below. Stage safe
immutable data, fsync it and its containing directories, then replace the
intent through a sibling, fsyncing the file and parent directory; only that committed intent authorizes push.
No roster reread may change it after the first push attempt. A pre-intent
crash cannot have published anything; unreferenced staging is not authority.

Extend the successful publication row with `publication_id` and the saved
ordered `merges` list, plus published batch `commit` and `parent`. Only a
confirmed published candidate supplies landings; rejected halves, conflicts,
dry runs, preparations and unknown push outcomes do not. On restart, drain
or reconcile any original push child before another push; fetch the saved
origin/ref and test whether it contains the **saved candidate**, including
when main has advanced. If it does, append the journal row from the intent,
using its saved routes and identities, then save journal confirmation. If it
does not, retain the intent and reconcile/retry that same candidate under the
queue's publication guards; never rebuild its metadata from today's roster.
An unavailable/divergent remote preserves uncertainty and blocks replacement.
A crash after journal append replays `publication_id` without a second logical
row. Retire the intent only after journal confirmation; branch cleanup is
later. A collector outbox cannot substitute for this pre-push checkpoint.

Extend `leads.txt` to `KEY LEAD_ADDRESS COORDINATOR_ADDRESS`, preserving the
lead destination for queue notifications. Unique keys and hosted lead
addresses are required. The coordinator cell is either a hosted mailbox or
exactly `-` for unassigned. Two-column rows or malformed addresses refuse new
configuration; a missing key is a supported unresolved route. Snapshot the
loaded third-column route into the publication intent, not after push.
Update every roster reader, including record-collect, in this producer part.
Do not derive a coordinator from a prefix or mission README.

Use one canonical route object in intents, journal entries and merge events:

| State | Exact fields |
|---|---|
| Resolved | `route_status="resolved"`, `coordinator=HOSTED_ADDRESS`; omit `route_reason` |
| Unresolved | `route_status="unresolved"`, `route_reason=REASON`; omit `coordinator` |

REASON is `unassigned` for roster `-`, `missing_key` for no roster row, or
`historical_unknown` for reviewed old-data backfill. The text roster's `-`
is converted to that object at its parser boundary; it never becomes a
coordinator join value. Null, empty-string, sentinel-valued coordinator, or
an absent coordinator without unresolved status/reason is invalid on the
wire. The optional records `coordinator` join therefore remains a string
only when resolved. QA preserves this same object in its brief/authority
and routes unresolved findings to the director. Changing the roster later
must not reroute an old landing.

Have record-collect publish a source `queue`, kind `merge` event per saved
entry with id `merge:<full M>`, publication_id, batch tip, P, B, branch and
the canonical route fields. Events name their journal path; preserve existing
batch/attempt events. The intent fixes the event's source timestamp so a
crash across UTC midnight cannot change its deduplication file. Its `time`
reflects the intent observation, not a claim about the exact remote push
instant. A producer outbox retains exact event rows/timestamps across retries.
QA reads them through records and validates graph claims against its own
fabrig fetch; it needs no queue-host SSH reader.

Name producer/collector fixtures `route_resolved`, `route_unassigned`,
`route_missing_key`, `route_historical_unknown`, `route_invalid_wire`, and
`publication_lost_ack_roster_changed`. The last kills the queue after a
successful push and before journal append, changes the roster, and proves
that reconciliation/collection retain the intent's original route and ids.
Also kill before intent commit, after journal append and before retirement;
none may invent or duplicate a landing.

Historical rows without routes/merge entries cannot invent them. An explicit
default start avoids importing the old backlog automatically; older marked
merges can be reconstructed from the batch interval's first-parent merges
only by a reviewed backfill that marks missing historical routes unresolved.
The feed cursor must cover every published first-parent merge after that
start; a gap blocks admission until collection/backfill fills it. Missing,
malformed or rewritten inputs preserve existing reservations and disable new
admission, while cleanup continues. A later fetch never silently resets a
non-fast-forward main cursor.

## 3. Defaults, decisions and candidates

Fabrig is the sole repository. All commands run on the designated QA host;
no REPO positional argument or multi-repository fairness is needed. First
activation runs `qa default on --at S`, where S is the exact then-current
origin/main agreed for activation. Save the start through records before any
pass can start. An absent or unreadable default is **uninitialized**, not an
invitation to test all history. `qa default on|off` thereafter records the
fresh origin/main; `--at` is first-initialization only. With no argument,
`qa default` shows the switch and boundary SHA.

An on boundary S and following off boundary E cover marked merges M reachable
from E but not S; an open interval uses current origin/main for E. Compare
ancestry, never author, committer or wall-clock dates. Off preserves work
already selected by its preceding interval. A later on does not absorb the
off interval; candidates there require an explicit decision. Overlapping
coverage uses the earliest on. Boundaries must remain on the known main
chain; a missing object or divergent history blocks selection.

`qa decide COMMIT backlog|run [--why TEXT]` accepts a unique commit prefix or
full SHA on main. It must name a marked commit or its carrying marked merge;
print the resolved merge and every affected mark. The exception applies to
the whole merge. `backlog` keeps it for later; `run` requests its next pass.
There is no exception that makes an unmarked landing eligible.

Every run request has a two-part identity `[event_id, M]`: default work is
`[default-event-id, M]` (one default can cover many merges), explicit run is
`[decision-event-id, M]`. A backlog decision suppresses that merge's earlier
request without consuming another merge covered by the same default.

The latest selection event wins: a default supplies an implicit run at its
on event, an explicit decision overrides it, and a pass's durable take consumes
that **request pair**. Order by the QA authority's increasing selection
sequence, not timestamps; explicit decisions beat a default at a tie, and
a take beats the request it consumed. Default intervals remain graph-based;
the sequence orders control, take and cancellation operations only.

Consumption, pass identity, every batch share/reservation and its initial
publication intents commit together through the single authority snapshot
in section 10.1. Separate selection/pass/outbox files are never independent
sources of truth. No claim, login take or launch precedes this commit. A
follow-up decision after a take cannot cancel a session or overlap a pass
on the same merge; it waits for prior ownership to drain.

Proven-unlaunched cancellation atomically records its synthetic final,
publication intents and the restoration of the same request pair, conditional
on there being no newer explicit decision. Keep a cancellation barrier on M
until all custody/claim uncertainty is resolved and the final/cancel events
are confirmed. Only then can the restored request be reserved again. A
possibly launched pass keeps its request consumed. Capped, failed or blocked
passes remain visible as uncleared and need a new explicit run decision;
new marked merges still run unattended. Section 10.1 covers every interrupted
transition, including cancellations whose publications are still pending.

`qa candidates` lists, in carrying-merge order, marked merges with no default,
decision or take covering them; each row includes M, marked SHAs, subjects
and trailers. Backlog, waiting, running, found and incomplete items belong in
`qa backlog`, `qa passes` or `qa findings`, not candidates. A failed read is
an error, never `no candidates`. CLI changes are locally durable first and
acknowledged only after records confirms publication; an exact pending event
survives a timeout and is retried rather than allocated again.

## 4. Selecting the build, batching and the brief

At a check, pull a consistent records main snapshot and fetch fabrig in a
dedicated metadata clone at `DEV_TMP/qa/fabrig.git`. It is bare, owns no build
target, and validates the fabrig origin; it is not a checkout in a numeric
slot. No pass may build in this metadata clone.

Read `events/after-landing/HOST/DATE.jsonl` for the configured producer host.
Use **after-landing-run** events, whose actual fields include `commit`,
`attempt`, `verdict` and `pairs` (after-landing/design.md, 4 and 6). For each
tip use its latest numeric attempt; conflicting duplicate identities are an
input fault. A usable run has verdict `green`, all configured pairs ran, and
no confirmed red. Red, partial, individual test/recovery events and bisection
results never authorize a build. Coalesced tips have no independent clearance;
their newer containing green tip can authorize it. Do not read the runner's
private cursor as a substitute for published events.

Choose the newest such green commit G along origin/main's first-parent chain,
not by event date or last file read. It can be behind current main. A later
red tip does not revoke a different older green tip; a later red/partial
attempt at G itself makes G unusable for new starts. Save the records snapshot
SHA, green event id and G with each reservation. Once launched, a pass stays
on its saved G; a subsequent verdict does not move its checkout underneath it.
No green, unreadable records, missing objects or an invalid pair schema means
wait, visibly, without taking a login. Fresh selection validates G again
before launching a reserved but not yet launched pass.

Waiting marked merges are ordered by main's first-parent position. G must
contain the oldest waiting merge; take only the prefix contained in G.
Let n be those waiting merges and k the available complete admissions, at
most n (slots plus every required login pool). Partition oldest first with
share `min(QA_BATCH, ceil(n/k))`, each time leaving one for each later pass.
Thus five merges over two slots become three and two; eleven over two become
five and five with one waiting. Failed reservations restore their work for
the next check once their cancellation barriers clear. Commit every disjoint
share, request pair, pass identity and publication intent in one authority
snapshot (section 10.1) before resource acquisition, then confirm the initial
reports/start events before launch. Restart cannot allocate a request twice.

The immutable brief root names G, M/P/B, every marked SHA and exact trailer,
branch/route object, green event, slot, scratch, rung, cap and report path.
It contains no not-yet-observed run or grants. The delivered task combines
that root with an authority-saved runtime annex of actual login names/resting
paths; save the exact task bytes/digest before the launch intent. It directs the session to read fabrig's rules and
the product's QA binding at G, read the marked diffs and touched designs,
write expected outcomes before testing, and exercise each marked story's
happy path plus two to four tricky cases. Several trees in one monorepo do
not become four independent products or four unrelated checkouts. Through
the binding's product tools, check observable outcomes on both sides; setup
and configuration failures are blocked cases, not product findings.

Use an explicit pass rung/pool setting (section 10), initially one ChatGPT
pool for the reviewed live-model binding. Binding path and rung must exist
at G before admission. The pass writes `plan.md`, `notes.md`, `report.md`,
helpers under `scripts/`, and captures under `evidence/`; it records commands,
expected/observed results, findings with stable numbers and likely marked
commit, blocked cases, and automation opportunities with time spent.
Its session cap starts at launch once its grants are held, persists across
watcher restarts, and defaults to 120 minutes. Tokens and wall time are
reported, not a new token budget. Passes do not pause or resume as walks do;
a retry is a new pass and request, preserving the previous report.

## 5. Slots, logins and safe admission

`QA_PASS_SLOTS` lists existing numeric fabrig slots on `QA_SLOT_HOST`. Its
length is the pass cap. Configure `2,6` on hetzner6 as dedicated s/qa
shares (section 13); no inferred free pair, fallback clone or walk slot is
a pass slot. Clone readiness and disk admission still gate activation. Reject duplicate pass numbers and overlap with any configured
walk kind. Each concurrent pass claims and prepares exactly one slot with
its warm target. Retain today's origin/dirty/unpublished-HEAD checks, fetch,
detached exact-SHA checkout, trim, decimal 80,000,000,000-byte disk admission,
locked source fetch before login takes, and background-heavy requirements
from qa.md. A refusal changes no unowned checkout and returns only confirmed
owned resources. No build or test runs on hel8.

Use the existing `walks.lock` as the common admission lock for passes, walks,
resumes, manual takes and claim release. Fixed lock order is watch.lock then
walks.lock; foreground operations take walks.lock alone. Share the saved
slot checkout sequence across both kinds. Before touching a slot, durably
save the unique lifetime WHAT and obtain the central claim with the existing
bounded acknowledgement protocol, owner `QA_CLAIM_OWNER`, work description
`qa pass NAME attempt 1 claim TOKEN`. Keep the exact host, owner, WHAT and
transport for release; no owner-only fallback. Claim/launch uncertainty
retains the reservation and blocks conflicting use.

For each pool of size N, all `qa-watch` and `qa-watch/...` holdings together
have cap `max(0, N - QA_LOGIN_RESERVE)`. Reserve defaults to 2: four ChatGPT
accounts permit two pass holdings; a stuck one leaves capacity for only one
new pass. Count inventory holdings, saved grants and in-flight takes, without
double-counting a known grant. Include legacy/unknown pass holders, missing
resting logins and manual holdings in their respective classes. Unknown
holders are alert-only; they are never swept just because no pass owns them.

Each walk kind keeps today's cap, the number of its configured numeric slots
using that pool, including `qa take` holders. Validate reserve >= the sum of
those walk caps for every shared pool, rather than legacy COUNT values in
QA_WALK_KINDS (today those counts are compatibility only). Raising reserve
or lowering a cap reclaims nothing; drain excess holdings before another
take in that class. Pools no larger than reserve admit no pass using them.
Unclassified live takers break the capacity guarantee and are reported;
no service action exceeds a cap to compensate.

Parse `logins list` strictly, including duplicates, controls and waiters.
Malformed or unavailable inventory admits no pass and authorizes no gives.
An outstanding legacy qa-watch queue request blocks pass admission until
reconciled; ordinary passes never enqueue. Take pools in sorted order with
`logins take POOL --any --now --as qa-watch/NAME`; save each grant and whether
its resting path is a moved file or in-place directory before the next.
Stat paths only; never read, copy or print login contents. Inherit admission
lock descriptors into takes and launchers as walks do. A lost take reply is
recovered only from matching saved-holder inventory. One refused take cancels
the new admission and returns its other grants through normal cleanup.

## 6. Ending a pass without an operator

Reuse qa.md's **Deployment and cleanup** and **codex-run and installation**
contracts for managed passes as well as walks. Extend `qa deploy`'s saved
directory ownership check to passes; do not introduce a second unit discovery
or exporter implementation. The session's on-stop and deployment ExecStop
call the same bounded, locked give-back wrapper, before a box is signalled.

At session completion or the saved cap, save the end observation; stop the
session if necessary and confirm its unit, jobs, launcher and stop wrapper
have finished. A run's `ended` marker alone proves no stop. Apply the current
ten-minute launch grace, exact task/report metadata recovery, negative
launcher scan and metadata/unit rechecks even when no run id was saved.
Unknown observations preserve custody and claim. Never launch a replacement
because the first launch timed out.

Then advance these durable, independently retryable steps:

1. Snapshot and scan the report/evidence; stage the safe report, verdict
   events and publication outbox, recording absent report, capped or failed
   outcome explicitly. Try evidence preservation within its bound. Records
   or evidence network failure must not delay custody actions past that bound.
2. Return each moved login through logins; a failed export keeps custody and
   the deployment alive. Alert the director and configured stuck recipients
   using today's per-login retry receipts.
3. After all moved logins are back, discover every exact pass unit with its
   scratch WorkingDirectory through systemd, stop it and confirm completion.
   A deployment trace file is not authority. No-logins passes reach this step
   immediately. Failed, malformed, duplicate or unknown observations retain
   the slot; queued/running jobs on an inactive unit do too.
4. After all units stop, return in-place logins. Reconcile lost replies by
   strict inventory, including every saved attempt holder. Conflicting
   ownership authorizes no give for either claimant.
5. Release the central slot claim only after all units and launchers stopped
   and inventory proves all grants returned. Use the existing guarded
   `claim release HOST N OWNER --what WHAT` protocol under admission. Retain
   qa.md's `release_status` state machine: an uncertain release is held and
   alerted, never blindly repeated against a possible successor. Every check
   reconciles the pending step; it cannot bypass the atomic WHAT comparison.
6. Publish staged reports/events, send any exception notice, and route
   findings after their publication is confirmed. Retry unconfirmed records
   and ordinary post deliveries independently of freed resources.

Each step commits progress in an authority generation before the next. An unavailable
writer never prevents a login return; an unavailable login never prevents
record publication or a stuck alert. Cleanup continues on every check after
the outcome is recorded. Preserve the current exceptional one-attempt
attention receipts for uncertain releases/orphan ownership and overdue
launches; these differ deliberately from retryable stuck/completion posts.
Normal complete clean passes need no director post. Capped, failed, blocked,
unreadable-report and metadata exceptions do. Do not use a walk's pause marker
to retain a pass box indefinitely.

## 7. Reports and verdicts in records

### 7.1 Bounded summaries and durable complete details

`qa/passes/NAME.md` is an at-most-8-KiB UTF-8 **summary** in the private
records repository, with a leading `+++`-delimited TOML header and short safe
human body. It never has to contain every mark, case or finding. Complete
briefs and results live in immutable records files
`qa/details/sha256/DIGEST.json`, where DIGEST is the SHA-256 of the exact file
bytes. This is required records data, independent of optional evidence
preservation: refused evidence cannot remove the complete validated result.

Encode each detail file as canonical JSON (UTF-8, ensure_ascii=False, sorted
keys, compact separators, no NaN, newline at end), at most 32 KiB.
A version-1 leaf has
`schema_version=1`, `kind` (`brief`, `result`, `summary`, `grants` or `control`),
`type="leaf"`, `entries` (an ordered array). A branch has the same version/kind, `type="branch"`
and `children` (ordered child digests). No other fields; recursive ordered
concatenation gives the full entries. A single leaf can be the root. Leaves
hold complete brief entries, result tables, exact archived summary text,
runtime grant entries, or control/request/route details respectively. Logical entries carry
a `type` discriminator; their schemas belong to the corresponding contract.
Oversize logical entries (long reproduction/output text) become ordered
fragment entries with exactly `type="fragment"`, `entry_id`, `fragment`,
`fragments`, `text`, containing pieces of the canonical logical-entry JSON, each text fragment at most 8 KiB UTF-8;
fragment metadata must agree and reassembly must validate the logical entry.
Shrink a fragment further whenever JSON escaping would exceed 32 KiB; the
serialized byte bound takes precedence over its 8 KiB text bound.
Tree depth/fanout are validated, cycles/repeated fragments refuse, and readers
stream the tree rather than loading an unbounded report into a state file.
Use the same fragmentation for an unusually long identity. A fixed-size root
digest is sufficient in summaries/events regardless of the number of marks.

Scan logical entries before canonicalization/fragmentation and scan each
serialized file too; splitting cannot hide a secret across fragments. Publish
children before parents, verify every child digest and validate the complete
logical schema before confirming a root. New files are create-only; an
occupied digest path with different bytes is corruption. A missing file,
invalid digest or incomplete tree authorizes no verdict. The brief and current grants roots are
confirmed before the running summary; the result root before its final.

The human summary uses counts and at most three bounded finding-title
previews (160 characters each), plus immutable roots for full details.
Header identifiers are at most 256 UTF-8 bytes; oversized external text is
represented by `sha256:DIGEST` with its exact value in the referenced detail.
Host, SHA, numeric and fixed-enum fields retain their stated formats; locally
chosen names/rungs must fit their validated grammar and this bound. Header
revision/counter integers fit signed 64-bit positive/nonnegative ranges.
The header/body renderer has a byte-budget fixture proving every supported
variant fits 8 KiB; it abbreviates previews, never required fields or roots.
If an identifier alone would exceed the budget, store it in the detail root
and use its digest identity in the summary/event; exact identity remains in
that immutable detail. No admission limit on marked-commit count is needed.
The session's full report may be larger than 8 KiB and is parsed/streamed
separately from this generated summary.

Register `[qa] sources = ["qa"]` in writers.toml. Extend records' permissions
explicitly: qa may append source qa, replace only `qa/passes/NAME.md`, and
create only correctly addressed `qa/details/sha256/DIGEST.json` files. Today
declared producers are append-only; adding the declaration alone is
insufficient. No general judgement/director-file permission is granted.
Use proposed `record write --as qa PATH --from SAFE_FILE` with the new
validators, plus existing `record append --as qa --batch HOST` for events.

### 7.2 Version-1 running and final summary schemas

Reject unknown header fields. A SHA is a full Git commit SHA; a digest is
64 lowercase hex characters. UTC fields use record's UTC format. No TOML
nulls, empty stand-ins or fabricated run/case results are allowed.
All variants require these exact common fields:

| Field | Type and meaning |
|---|---|
| `schema_version` | Integer 1 |
| `variant` | String `running` or `final` |
| `revision` | Positive per-pass publication revision (section 7.4) |
| `repository`, `pass`, `host` | Strings: `fabrig`, pass name, inventory host |
| `main`, `green_event` | SHA G and nonempty after-landing event identity |
| `brief_digest` | Digest of the immutable complete brief root |
| `created` | UTC reservation-transaction time, unchanged on retries |
| `rung`, `slot` | Rung string, positive numeric slot from reservation |
| `model`, `effort` | Nonempty strings, `unknown` until observed if not selected explicitly |
| `logins`, `login_count` | Array of at most eight grant-name strings and nonnegative integer total grant count |
| `grants_digest` | Complete runtime-grants root digest; reservation root has an empty entry set |
| `evidence_status` | `unknown`, `refused` or `kept` |

`evidence_commit` (SHA) and `evidence_directory` (safe relative path) are
required only for kept and forbidden otherwise. They are the only optional
common fields. All later revisions retain the immutable brief identity.
Grant names/count/root reflect that revision's observed grants; revision 1 precedes resource
effects and has `logins=[]`, login_count 0 and a confirmed empty grants root.
Later revisions may add observations. Final grants detail lists every grant
from authority; preview names are bounded and never a custody authority.

A **running** summary additionally requires `outcome="running"` and
`launch_state="reserved"|"launching"|"running"`. `started` is absent for
reserved and required as a UTC time for launching/running: it is the durable
launch-intent time from which the cap runs. `run` is a nonempty string only
once metadata/acknowledgement establishes it; it is required for running,
optional for launching and forbidden for reserved. Running forbids `ended`,
`wall_seconds`, token fields, result fields and final `reason`; no completed
case set or result block is required. The mandatory prelaunch publication
is the reserved variant with no started/run/results. Launch-state updates
are optional serialized later revisions; the authority still records them.

A **final** summary additionally requires:

| Field | Type and permitted values |
|---|---|
| `outcome` | `done`, `capped`, `failed` or `cancelled` |
| `reason` | `completed`, `cap`, `run_failed`, `cancelled_before_launch`, `failed_launch`, `missing_output`, `invalid_output` or `unsafe_output` |
| `ended` | UTC final observation after stop/negative launch proof |
| `wall_seconds` | Nonnegative integer from started to ended; 0 when never launched |
| `result_status` | `complete`, `partial` or `synthetic` |
| `result_digest` | Immutable complete result-tree digest |
| `result_revision` | Revision that first published this final result |

Final `started` is present iff a launch intent was committed; final `run` is
present iff recovered/acknowledged, even for a failed launch. No launch intent
means both absent and wall_seconds 0. `tokens_in`, `tokens_cached` and
`tokens_out` are an all-or-none set of nonnegative integers when measured;
all three are absent when unknown or never launched. `launch_state` is
forbidden in finals.
Outcome/reason pairs are done/completed, capped/cap, cancelled/
cancelled_before_launch, or failed with any other reason. No header field
beyond these lists is allowed. A done report may still have blocked cases
and incomplete merge verdicts. Later evidence revisions preserve final
result_revision/result_digest exactly.

Create a **synthetic final** even without session output: cancellation is
cancelled/cancelled_before_launch; proven failed launch is failed/failed_launch;
a completed run with absent output is failed/missing_output. Invalid or unsafe
output similarly gets failed/invalid_output or failed/unsafe_output. Synthetic
results name every selected merge and mark through the brief root, contain
empty case/finding arrays, a safe service-written blocked explanation, and
incomplete for every selected merge. They never invent happy/tricky cases.
A launched nonzero exit or cap with valid partial output uses result_status
partial and records actual cases/findings; complete is reserved for normally
completed, fully validated output. Cancellation finals are required even if
a running summary never reached records. Cleanup and cancellation barriers
do not depend on the session having produced a report.

### 7.3 Complete result schema, verdicts and events

The session writes exactly one TOML block between whole-line
`<!-- qa-results -->` and `<!-- /qa-results -->` sentinels without an inner
Markdown fence. Parse with tomllib. `version=1`, arrays `merges`, `cases`,
`findings`, and optional `blocked` array of explanation strings are the only
root keys; absent findings/cases in partial output are normalized to empty
arrays and missing planned coverage is explicitly blocked. For complete
output all three arrays are required, including empty `findings=[]`.

- `[[merges]]`: `commit` (M), `marked` (exact ordered SHA array from brief).
- `[[cases]]`: unique nonempty `id`, `merge` (M), `commit` (a mark in M),
  `kind` (`happy` or `tricky`), `outcome` (`ok`, `finding` or `blocked`),
  nonempty `expected` and `observed`; positive `finding` number only when
  outcome is finding, required then and forbidden otherwise.
- `[[findings]]`: unique positive `number`, `commit` (marked SHA, M or
  `unknown`), `concerns` (`ordinary`, `security` or `lost data`), nonempty
  `title`, `reproduce`, `expected`, `observed`, and `evidence` (safe relative
  capture path or `none`). No unknown table fields are allowed.

Complete output has every selected M once, each marked SHA exactly once in
its merge table, one happy and two to four tricky cases per mark. Findings
and case references agree with the human body. Partial output retains only
validated actual observations and makes missing coverage explicit; ambiguous
identities or invalid syntax produce a synthetic final. Normalize validated
output into the durable result-tree logical entries: version/pass/brief
identity, result status, all merge/mark/case/finding/blocked tables and the
computed per-merge verdicts. Synthetic root metadata points to brief_digest
for the complete selected identity set. This root is the canonical result,
not the mutable summary or optional evidence copy.

`cleared` requires complete, normally completed output, every planned case
ok, no blocked case and no attributed finding for that merge. `found` means
at least one validated finding attributed to it; causation is not proven.
Otherwise it is incomplete. An unknown-attribution finding prevents clearance
of the pass's other merges. Synthetic/cancelled/absent output never clears.
A later pass adds results without deleting findings/history.

Events use record's id/time/source/host envelope, source qa. Exact ids and
UTC times persist in the authority outbox. `coordinator` is present only for
resolved route objects (section 2.1); `run` is omitted when unknown. Each
line is at most 16 KiB: bounded counts/previews and fixed digest references
replace unbounded merge/marked/case/finding arrays. Oversize identity text
is stored in detail and represented by its SHA-256 plus detail reference.
Brief/result roots hold all exact values; an oversized preview is omitted.

| Kind | Identity and bounded facts |
|---|---|
| `qa-default` | `default:UUID`; sequence, on/off, boundary SHA, reason or reason digest |
| `qa-decision` | `decision:UUID`; sequence, M, run/backlog, request pair, brief/selection detail digest |
| `qa-pass-start` | `NAME:start`; sequence, request count, brief_digest, G, green event, slot/rung, running report revision/digest |
| `qa-pass-end` | `NAME:end`; outcome, wall/tokens/counts, final report revision/digest, result_revision/result_digest |
| `qa-pass-cancel` | `NAME:cancel`; restored-request count/digest, sequence/reason, synthetic final revision/digest |
| `qa-merge` | `NAME:merge:M`; M, cleared/found/incomplete, counts, final report revision/digest and result_digest |
| `qa-finding` | `NAME:finding:N`; safe title preview, likely SHA/M or unknown, concerns, final report revision/digest and result_digest |
| `qa-route` | `NAME:route:N:REV`; desired revision and owner/backlog/drop, address for owner, reason/digest, finding id |
| `qa-delivery` | `NAME:delivery:N:REV:ATTEMPT`; route revision, accepted/failed/uncertain/superseded, recipient, stable finding id |
| `qa-evidence` | `KIND:NAME:evidence:REV`; kept/refused/digest, report revision/digest for passes, unchanged result_digest when final |

### 7.4 Serialized report publication and exact references

All report publications for one pass share a single serialized authority
lane and `publish/NAME.lock`. Hold that lock across the writer call and
confirmation; inherit its descriptor into the bounded writer child so an
orphan still excludes another publisher. Under this lock take walks.lock
briefly for authority mutations, never the reverse; hold neither routes.lock
nor walks.lock across record calls. Queuing a later revision under admission
does not authorize publishing it while this lane is busy. Before any call,
commit its immutable bytes, SHA-256, monotonically increasing revision, variant
and dependent event intents in the authority.
Only the next unconfirmed revision may be sent; no concurrent report writers
or independently replayable old report outboxes exist. Calls and their child
processes are tracked until completion. A timeout is uncertain, not permission
to start a newer revision while an old writer might still publish.

Resolve an uncertain write by fetching records and inspecting the exact
path's bytes/header revision and digest. Matching bytes confirm it; an absent
path or lower revision permits retry of the exact saved next revision only after the old
writer is proven finished. A higher revision absent from the local authority
or equal revision with another digest is corruption: freeze the lane and
alert; never overwrite it. A higher *known* confirmed revision means the
older receipt was superseded locally and must never be replayed. After
confirmation, durably advance the cursor before the next revision; crash
recovery repeats this inspection, not an unconditional stale `record write`.

Publish all detail children/roots, then the corresponding summary, then its
dependent events. Every event referencing a pass report names
`report_revision` and `report_sha256`; verdict/finding/end events also name
`result_revision` and `result_digest`.
Retain immutable summary bytes as a `summary` logical entry in a separate
detail tree and put its `report_archive_digest` in events, allowing exact
verification after the path advances. That archive tree is published before
the mutable summary; it contains no self-reference. Later evidence metadata
gets the next report revision but preserves the original final result digest
and result_revision. Its event names the updated summary revision/digest.
Evidence update requests arriving before final confirmation wait behind that
final in the lane. No metadata retry may restore a running report over a
final or remove a later evidence link. Final verdict events may publish after
a later metadata revision only by their exact archived final reference.

Publication confirmation follows record.md: fetch and prove remote
containment/exact bytes, not exit status alone. Preserve exact pending bytes
and original ids/dates after deferred/conflict/lost replies. Report/evidence
publication failure never releases a consumed request or blocks login returns.
No finding post precedes confirmed final details, summary and finding event.

## 8. Findings and the coordinator

Resolve a finding's marked Commit to its carrying merge from section 2 and
route to that landing's saved coordinator mailbox. A finding naming M
directly uses M. A commit outside the pass's marks is unresolved unless an
unambiguous saved carrying marked landing establishes it. Missing/unknown
commit, ambiguous duplicate Commit/Concerns, no landing route, security or
lost-data concerns go to the director. Stuck logins and infrastructure/input
exceptions also go there. The queue's lead address is not a fallback, and
the director is not copied on ordinary attributed findings.

Create the initial automatic **desired route** at revision 1 in the authority
with its finding and publication intents. `qa-route` records intent, not
acceptance; `qa-delivery` records attempts/receipts separately. After confirmed
final report/details and finding/route events, a delivery can become eligible.
Every outbox item is bound to `(pass, finding number, route revision)`, desired
owner address, immutable body digest, finding/result references and attempt
state. Backlog/drop have a route revision but no new send item.

Use one routing lock `routes.lock` for triage and send, with fixed order
routes.lock then walks.lock when both are needed; release both before report
publication. Under that lock, `qa triage PASS N owner ADDRESS|backlog|drop
[--why TEXT]` atomically commits the next desired revision and marks older
**unsent or known-failed** items superseded in the same authority generation.
Owner creates a replacement item; backlog/drop does not. Old accepted
receipts remain historical facts, never reclassified as cancelled. The
new desired route is durably pending publication even if records is down;
older eligible items cannot slip through during that interval.

Immediately before sending, acquire routes.lock, reload the authority and
compare the item's revision/address to the current desired route. A mismatch
supersedes it without post. Persist an attempt intent, retain routes.lock
across the bounded post call and persist its result before unlocking. Pass
the routing-lock descriptor to that child, so a surviving send after watcher
death still excludes triage/send until reconciliation. Triage either
supersedes an unsent item before send or follows an already
attempted delivery; it cannot race between the check and post. All authority
updates take walks.lock briefly in that order, so concurrent cleanup updates
merge against the latest generation without losing triage. No other code
acquires routes.lock while holding walks.lock.

Send as qa-watch, subject at most 200 characters, body under 15 lines:
stable finding id, route revision/attempt id, G/M/marked SHA or digest,
bounded title, immutable result/report revision/digests, records paths,
evidence commit/directory or refused/pending status, and host. Pending
evidence can name retained host-local scratch. Never send raw captures or
secret-match text. Post exits 0/3 are accepted; persist that receipt before
publishing qa-delivery. Known failures retry only if their route revision
remains current, with a new saved attempt id.

Timeout, lost reply, or a crash with an unfinished attempt is **uncertain**.
On restart acquire routes.lock and reconcile/drain the exact send child
before another send for that finding. Preserve the uncertain receipt across
triage; do not claim that supersession withdrew a possibly delivered post.
After the child ends, a superseded uncertain attempt is recorded as uncertain
and is never retried; a current uncertain revision may be retried at least
once with its stable finding id, acknowledging possible duplicate delivery.
Accepted older deliveries may coexist with a newer backlog/drop or owner;
the route history makes that order explicit. A saved accepted receipt causes
no resend merely because its delivery event publication failed.

`qa findings` lists findings without a current desired route or with a current
owner delivery not accepted, including failed/uncertain states. Backlog/drop
remain as route events rather than invented director/backlog.md writes.
Finding numbers stay stable across report metadata revisions. Unreadable
route state freezes delivery and preserves an explicit director exception.

## 9. Evidence, scanning and seven-day pruning

Today's port keeps walk scratch/reports on the host, opens no evidence
repository and prunes nothing (qa.md). The legacy kept evidence on the private
`fabrig-ai/qa` repository's orphan `evidence` branch. Retain that one durable
place for both walks and passes: `passes/NAME/` and
`walks/FIRST-START-DATE-NAME/`. Existing evidence remains useful, blobs do not
inflate records main or public fabrig, and QA evidence does not need the code
gate. Add a bare evidence-only clone `DEV_TMP/qa/evidence.git`, with a separate
lock, validated origin/push target and no URL rewriting. No login migration,
reading a key or signing in is part of implementation or activation.

The common pass/walk/keep path takes one descriptor-based snapshot, validates
ownership and regular singly-linked files without following directory or file
links, and publishes exactly those scanned bytes. Allow only `brief.md`,
`plan.md`, `notes.md`, `report.md`, `scripts/` and `evidence/`; walks also allow
`report-N.md` for earlier attempts. Nothing else: no deployments, stores,
binaries, give-back scripts, service state or Codex transcripts. The index
names kind/name/host/source/run(s)/record, files/bytes and omissions, and is
scanned too. Known credential names refuse before their contents are opened.

Reimplement the legacy qa-flow.md 11.2 rules in current Python, with no
runtime import or dependence on old/. Reject the entire snapshot on:

- **kind/binary:** symlinks, hard links, nonregular entries, non-UTF-8 or NUL.
- **name:** case-insensitive path words separated by `-`, `_`, `.`, or ends:
  cookie(s), password, passwd, secret, token, credential(s), netrc; exact
  auth.json, id_rsa, id_ed25519, login with/without extension; suffixes
  .header, .headers, .pem, .key, .env. Plural tokens and session-status.txt
  alone remain allowed.
- **key/jwt:** private-key blocks, known credential prefixes (include today's
  record scanner's prefixes), or three-part signed JWT shapes beginning eyJ.
- **header/cookie-jar:** Authorization/Proxy-Authorization scheme plus value,
  Cookie/Set-Cookie pairs, Netscape headings or tab-separated cookie lines.
- **link:** URL user/password or valued query/fragment code, token, secret,
  key, password, access_token, refresh_token, id_token, client_secret,
  signature parameters.
- **assigned/user:** valued password/passwd/secret/token/api_key/client_secret/
  access_token/refresh_token/private_key assignments (JSON, shell/form, or
  standalone key-colon-value), and curl -u/--user with a password.

Scan paths both componentwise and whole. A path containing a secret shape is
identified by safe directory and sorted entry number, never its matched name.
Other diagnostics give path, line and rule, never matched text. Placeholders
pass: empty/null/true/false, capital names, angle placeholders, ellipses,
asterisks, @FILE, shell variables of either case, and whole unexpanded
`${{ ... }}` expressions; a literal beside a placeholder still refuses.
Match the legacy handling of quoted whole values, unquoted comments, escaped
spaces and permitted trailing punctuation. HTTP folding and JSON escaped
keys remain documented scanner limits; unknown token shapes cannot be
detected. The brief requires captures to exclude credentials and sign-in
links. When preparing captures, mask values with `[masked]` and retain the
line's meaning; do not drop whole diagnostic lines. A forbidden name remains
forbidden regardless of masking.

The 2048 KiB cap omits evidence/ whole first, then scripts/ whole, with file/
byte counts and unreadable entries in the index. Documents alone over cap
refuse; other scan failures never cause selective copying of a snapshot.
For records summaries/details, unsafe text becomes a safe `(withheld: RULE)`
placeholder before publication; unsafe findings retain their number and route
an exception without their text. Any withheld required result produces a
synthetic unsafe_output final rather than a cleared result. The original
unsafe bytes never enter a detail tree or summary archive. Scan all report metadata, routes, event fields and generated
post bodies too. An unsafe marker/subject must not bypass the scan via
front matter. A withheld required result cannot yield cleared.

Keep copies append-only, fast-forward, never rewrite/delete evidence. Same
name and same content tree returns the original commit; a different tree
refuses the occupied name. Evidence operations get at most five push-race
tries inside QA_EVIDENCE_SECONDS (120); an unconfirmed push leaves waiting
state, exact snapshot/tree and an outbox for reconciliation. Once a copy is
kept, its snapshot is immutable. Before that, a refused copy can be rescanned
after a repair by safe path/line only; no agent opens a suspected file to
inspect the match. Retry on each check, deduplicating refusal notices by
digest. A confirmed later copy updates the records link and sends the walk
starter a link update, without repeating pass findings.

Keep walks only at final end, not pause; retain the current starter and clock
semantics. Store evidence state and pruning progress separately from the
small permanent custody record. `qa keep --check DIRECTORY` is local,
read-only, network-free, and uses the same snapshot/scan/cap; exit 0 clean,
2 refused. `qa keep --walk NAME DIRECTORY` preserves an already ended manual
walk on that machine; exit 0 prints commit/path, 2 refusal, 1 publication
failure for retry. It cannot use a directory belonging to an active managed
run. Service-managed passes and walks use the same preservation implementation.

Seven days after the saved session end, make a final keep attempt. Delete only
that owned scratch when its copy is kept or explicitly refused, the records
report/link or walk completion receipt names that status, notices/routes are
durable, all logins are back, all units/jobs/launchers are stopped and the slot
release is confirmed. Pending publication keeps scratch beyond seven days;
so do stuck custody and unknown release. An unchanged refusal may be pruned
once its notification was accepted; a changed refusal requires its new notice.
Paused walks are never age-pruned. Retain small states/outboxes/tombstones for
deduplication; prune no slot checkout, warm target, login registry, evidence
branch or codex-run transcript. Legacy foreign states remain opaque, and
enabling passes does not adopt old pass directories or erase them.

## 10. Settings, state and CLI

Use today's environment > safe DEV_TMP/machine.env > defaults precedence,
with no sourcing of shell. Preserve DEV_ROOT/DEV_TMP meanings and existing
director/stuck-address configuration. No additional credential configuration.
New paths and origin overrides are fixture-only under QA_FIXTURE; product,
records and evidence origins are fixed/validated in production.

| Setting | Default / activation value | Validation and use |
|---|---|---|
| `QA_PASS_SLOTS` | empty / `2,6` on hetzner6 | Same compact number-list grammar as walk slots; empty disables starts |
| `QA_BATCH` | 5 | Positive marked merges per pass |
| `QA_CAP_MINUTES` | 120 | Positive; persisted at launch |
| `QA_LOGIN_RESERVE` | 2 | Nonnegative; at least each pool's summed walk slot caps |
| `QA_PASS_RUNG` | reviewed live ChatGPT rung, explicit at activation | Lowercase rung slug; must exist in binding |
| `QA_PASS_BINDING` | reviewed live ChatGPT binding path, explicit at activation | Safe repo-relative Markdown path at G |
| `QA_PASS_POOLS` | `chatgpt` | Unique base pools in compact + separated form; explicit none for fakes |
| `QA_AFTER_LANDING_HOST` | deployed after-landing host, explicit at activation | One authoritative hosted records producer; required for starts |
| `QA_EVIDENCE_KIB` | 2048 | Positive snapshot cap |
| `QA_EVIDENCE_SECONDS` | 120 | Positive total bound per keep attempt |
| `QA_RETENTION_DAYS` | 7 | Fixed policy for this design; no deletion before it |

Reuse QA_INTERVAL_SECONDS=300, QA_STOP_SECONDS=50,
QA_GIVE_BACK_SECONDS=90 and existing slot host/claim owner/transport settings
and bounds from qa.md. Validate pass-only settings for pass admission without
preventing already held walks or passes from cleaning up after a settings
error. Settings lowering capacity never invalidates saved ownership.

Local state under DEV_TMP/qa uses 0700 directories and 0600 metadata.
`authority.json` is the sole authority for pass selection, reservation,
lifetime, report publications and routing. `passes/NAME.json`, selection
listings and standalone outbox files, if retained for inspection, are
read-only projections stamped with authority generation/digest; recovery
never trusts them over the authority. Existing `walks/NAME.json` remains
walk authority; no second authority for pass claims is introduced. Pass
scratch is `DEV_TMP/qa-passes/NAME/`; walks remain in qa-focused. Pass names
contain host, UTC reservation time and a random suffix allocated in the
reservation transaction and never regenerated on restart.

### 10.1 One authoritative write-ahead state and partial transitions

The version-1 `authority.json` contains `schema_version`, monotonically
increasing `generation`, and digest roots for selection, pass transactions,
publication lanes, routes/deliveries and attention/cleanup state. Use local
immutable canonical-JSON pages (at most 32 KiB, paged like section 7.1) so the
root/state reader bound does not limit marks or request count. Before a root
replacement, stage/fsync every referenced page and payload **and their
containing directory entries**, then fsync a sibling root, rename it and
fsync its parent directory. That single root
commit is the transaction boundary. Retain prior generations and referenced
payloads; reference-aware local page GC is Later. Unreferenced staging after
a crash supplies no authority and permits no external action.

Under walks.lock, a reservation transaction changes all of these together:
request-pair owners/consumption, stable pass ids and disjoint shares for the
whole batch, G/green snapshot, complete brief roots/route snapshots, selected
slots and unique claim WHAT values, stage `reserved`, report revision-1
bytes/digests and all initial detail/report/event publication intents. Publish
intent here means a durable plan, not a claim of remote success. All later
mutators reload the current root under walks.lock and commit a new generation;
no callback edits a projection or overwrites a stale root.

Every external effect has an intent committed before the call and an
observation committed afterward, keyed to the same pass/operation identity.
Retain task/report/run observations, pool/name/kind grants, unit/job proofs,
claim/release state, cap, cleanup progress, exact pending publication bytes,
report revisions/digests, route receipts, end/prune times and tombstones.
The recovery rules for interrupted boundaries are:

| Last durable boundary | Recovery |
|---|---|
| Pages staged, root not committed | Ignore staging; previous request ownership remains. No external effect was permitted. |
| Reservation/consumption committed, no effect intent | Resume that same pass/reservation or cancel it; never allocate its request elsewhere. |
| Claim or login-take intent, no saved reply | Reconcile the exact WHAT or saved holder through strict inventory/central claims; uncertainty retains ownership and forbids a replacement take/claim. |
| Brief/running report/start-event publication incomplete | Resume exact saved bytes/revision in dependency order; resources may be cleaned and cancellation queued, but do not launch before confirmation. |
| Running/start publications confirmed, no launch intent | Revalidate and either launch the same pass or commit cancellation. A remote running report does not itself mean a launcher exists. |
| Launch intent committed, reply/meta missing | Recover the exact task/report/launcher with qa.md's grace and negative proofs; never call launch twice. Proven failure gets a synthetic failed_launch final; unknown keeps custody. |
| End/cap observation or cleanup step interrupted | Reconcile that step's external outcome and continue from authority; retain the consumed request. |
| Cancellation committed, publication or release unfinished | Keep the restored request behind M's cancellation barrier; finish synthetic final/cancel publication and custody cleanup, then atomically clear the barrier. |
| Publication accepted, receipt/root update lost | Inspect saved revision/digest or event id on records; confirm or replay exact bytes without reallocating ids. |
| Send intent without receipt | Preserve uncertain delivery and reconcile under routes.lock (section 8); never silently cancel possible acceptance. |
| Projection/outbox export interrupted | Regenerate from the committed root; neither consumption nor ownership changes. |

Cancellation commits its terminal observation, synthetic-final/result intents,
conditional request restoration and barrier **in one root replacement**.
Barrier clearance is another single replacement after all required proofs;
a crash on either side exposes one consistent state. A newer explicit
backlog/run decision is preserved and never overwritten by restoration.
No records reconstruction can bypass local pending ownership. Corrupt/missing
referenced pages or roots disable pass admission/delivery and alert; safe
independent walk cleanup can continue. Records-based repair is explicit and
must account for active claims/units first. Ordinary bounded file/descriptor
safety rules still apply to every page and snapshot.

Commands added to the existing qa CLI:

```
qa candidates
qa decide COMMIT backlog|run [--why TEXT]
qa default [on|off [--at SHA] [--why TEXT]]
qa backlog
qa passes [--running]
qa findings
qa triage PASS N owner ADDRESS|backlog|drop [--why TEXT]
qa keep --check DIRECTORY
qa keep --walk NAME DIRECTORY
```

`qa watch --director ADDRESS [--once]` remains the one service, ending walks
and passes and scheduling passes. `qa passes` includes waiting request and
merge counts, running/completed outcomes and times/tokens, green build/event,
unresolved inputs, slots/claims, every pool/class holding versus cap, and why
admission waits. Read commands pull records and never write invented results.
Walk/take/give/deploy syntax stays as documented. Mutation success is exit 0;
refused input/configuration is 2; operational/publication failure is 1 and
names the pending operation id. `keep` uses its explicit statuses above.

## 11. Every watcher check and the test worlds

Under the existing nonblocking watch lock, at startup, every mailbox wake
and each 300-second timeout:

1. Load the committed authority root and safe walk states/settings; recover
   partial transitions by section 10.1 and possible launches before starts. A busy admission lock still permits current
   read-only overdue-launch attention, never custody mutations.
2. Under admission, obtain strict inventory and reconcile each owned walk
   and pass: cap stops, wrapper completion, grants, deployments, claims and
   saved attention. Isolate failures per state and preserve foreign custody.
3. Outside admission, retry safe evidence/report/event outboxes and accepted
   receipt bookkeeping in the per-pass serialized lanes, then revision-checked
   finding/exception posts whose publications are confirmed. A publication
   deferral never prolongs an unlaunched reservation: cancel it through cleanup; uncertain launches retain custody.
4. Pull records once and fetch metadata with bounded calls. Validate feed
   completeness, main ancestry, defaults/decisions and authoritative green
   runs. If any admission input is unavailable, keep reservations unchanged
   and skip starts. Other cleanup, outbox and prune work continues.
5. Under admission, recheck counts/claims and plan disjoint shares; pending
   control publications disable new starts until resolved. First commit the
   complete reservation/consumption transaction, then claim/prepare slots
   before taking logins, committing each effect intent/observation. Release
   admission before publishing running details/summaries/start events in the
   report lane; reacquire it and revalidate before launch. If publication
   waits, cancel proven unlaunched reservations through cleanup
   so they do not tie up logins until the next network recovery. Keep unknown
   launch ownership held. Revalidate saved selection if decisions advanced.
6. Retry eligible preservation and pruning (section 9), save progress, then
   mailbox-wait with the existing PID, timeout margin and replacement rules.

All external calls retain qa.md's bounds: systemctl 30 s, login/post/claims
60 s, codex-run 120 s, preparation trim/fetch 300 s, metadata/records calls
300 s maximum, evidence 120 s total. No external failure can skip a custody
precondition. Wait failures retain the interval backoff. One bad pass cannot
stop the others' cleanup or walks' admission where ownership is established.

Extend `Lab` in `tools/qa/test_qa.py`: its temporary HOME/DEV_ROOT, private
fabrig bare origin, numeric slot clones, fake claim/SSH/df/heavy/cargo,
systemd, logins, codex-run and post already supply the operational world.
Add a fake queue journal/records producer with a real local Git merge graph,
a private records origin/writer and local evidence origin. Use QA_FIXTURE
overrides exclusively; child Python is `-I -B`, stdin closed, descendants
killed/reaped. Never run a real model, service, network origin, claim or login.
Generate secret-shaped fixtures at runtime; no secret literals in sources.

Required acceptance worlds:

- Multiple branch/nested merges, already reachable marks, baseline commits,
  deleted ready refs, rejected/dry rows, lost queue publication replies and
  missing feed intervals; only published carrying merges become items.
- Default start/off/on by ancestry with misleading commit dates, overrides,
  ties, pending publication, retake after cap and decisions during launch;
  replay consumes each request once and candidates exclude covered work.
- Newest green by graph order, out-of-order records, red/partial latest
  attempts, coalescing, missing objects, rewritten main and unavailable
  records; none can launch at an unauthorized or moving SHA.
- Two passes share five merges as three/two in distinct slots; warm checkout
  and central claims protect walks, dirty/unpublished clones and successor
  claims. Claim failures never fall back to local ownership.
- Four ChatGPT logins leave two for walks, stuck and manual/unknown holdings
  count, reserve/cap validation, strict malformed inventory, legacy waiters,
  partial grants and inherited locks across orphan takes/launchers.
- Crashes before/after claim, grant, take save, report publish, launcher/meta,
  end observation, stop confirmation, give and release; retries never double
  launch, overlap a request, free live custody or delete a successor claim.
- End/cap with moved versus in-place logins, stuck export, deployments with
  queued jobs, failed/unknown systemd replies and delayed records; all cleanup
  steps finish once fakes recover, while walks and other passes continue.
- Report validation, incomplete versus found/cleared per merge, secret
  withholding, missing reports, publication conflict/deferred/lost replies
  across midnight, event ids replayed once and no posts before publication.
- Landing-time coordinator snapshot survives roster changes, two/three-column
  migration, unknown/security/lost-data exceptions, post exits 0/3/failure,
  receipt crashes and later evidence links without duplicate finding routes.
- Every evidence rule/placeholder, masked captures retaining lines, unsafe
  names never opened, symlink/hard-link swaps and changes after snapshot,
  cap omissions, occupied names, push races and lost replies. Nothing matched
  appears in stdout, stderr, records, Git publication or post bodies.
- Walk final ends (including prior reports), pauses, manual keep/check,
  seven-day boundaries, kept/refused/waiting copies, stuck custody, pending
  notices/routes and retained tombstones. Pruning touches only owned scratch.

Round-2 regression worlds are named as implementation acceptance tests:

- `authority_two_merges_one_default` consumes `[default_id, M1]` without
  consuming `[default_id, M2]`. `authority_crash_each_boundary` kills before/
  after root commit, every external intent/observation, cancellation commit
  and barrier clearance; projections can be stale without changing ownership.
- `report_reserved_without_results` accepts a running prelaunch header;
  `report_running_forbidden_fields` rejects invented final fields.
  `report_final_cancel`, `report_final_missing_output` and
  `report_final_failed_launch` validate synthetic finals and required absences.
- `details_many_marks_one_merge` exceeds 8 KiB with complete results;
  `details_evidence_refused` still reads them from confirmed records.
  `details_fragmented_entry` checks escaping/size/reassembly, missing children
  and a secret shape split across fragments before any publication.
- `report_lost_write_child_alive`, `report_old_retry_after_final` and
  `report_evidence_revision` prove serialized publication, exact archived
  references and stable result digests. `report_revision_digest_conflict`
  freezes publication rather than rolling back a final.
- `route_failed_then_backlog`, `route_failed_then_drop` and
  `route_failed_then_new_owner` never retry superseded sends. Include triage
  racing the pre-send revision check, an orphan holding routes.lock, and
  `route_uncertain_then_override` retaining possible prior delivery alongside
  the new desired revision. Accepted receipts survive event-publication retry.
- The six named route/publication producer fixtures in section 2.1 exercise
  resolved/unassigned/missing/historical data and reject every other wire
  spelling, including a null optional coordinator join.

Producer changes additionally extend records/test_record_collect.py and
test_record.py with the queue merge projection, narrowly scoped QA report
writes/details, both report variants and synthetic finals, invalid schemas
and publication replay. Queue's own fake-origin tests cover route snapshot, merge journal/recovery and all roster readers.
Run focused suites with Python 3.13 `-I -B`, then tools/check.sh in agents;
fabrig's producer change uses its queue tools gate. No cargo/heavy or live
machine test is required to review this design.

## 12. Implementation boundaries and legacy departures

Implement as reviewable parts with explicit dependencies:

1. **Queue feed:** fabrig tools/queue roster, confirmed merge journal and
   recovery; agents record-collect merge events. Publish fixtures/contracts
   together. This supplies stable landing identity and historical coordinator.
2. **Records contract:** scoped qa writer, report path/schema, event validation
   and replay; immutable detail trees, versioned report/result schemas and
   a pure selection/feed/green reader using local origins. No scheduler
   before these two parts pass.
3. **Preservation:** common snapshot scanner and evidence writer, keep CLI,
   walk final-end integration and guarded pruning. Preserve walk safety and
   earlier attempt reports before adding pass scheduling.
4. **Pass lifetime:** common slot/admission/claim/launch/deploy/cleanup code
   and the atomic authority snapshot for pass states, with walk regressions;
   no watcher scheduling until faked crash/custody worlds pass.
5. **Scheduler and routing:** control CLI, defaults, batch shares, brief/report
   interpretation, records outboxes, coordinator delivery and pass listings,
   followed by the watcher loop acceptance worlds.
6. **Activation:** reviewed slots, binding, records schema/producer deployment,
   old-state reconciliation, fleet settings and one explicit default start.
   A machine-action commit must name these actions. Installation alone starts
   no pass; no change to main except through each repository's normal gate
   and landing tool/queue. This design commit requires no machine action.

Compared with old/docs/design/qa-flow.md 2–4, 6, 10.6 and 11 and
old/roles/qa-operations.md 7–8, retain ancestry defaults, explicit exceptions,
batch five/cap 120, login reserve, unattended ordered cleanup, append-only
evidence, secret rules and guarded seven-day retention. Depart deliberately:

- One fabrig monorepo and a carrying-merge work item replace several product
  repositories and independent commit work items; all a branch's marks are
  covered before its merge can be cleared.
- Published queue/records merge facts replace legacy landings commands and
  mission README traversal. Landing-time coordinator replaces designer/mission
  inference; producer gaps are explicit prerequisites.
- Existing claimed numeric slots and warm targets replace private product
  clones/worktrees and per-pass targets. Walks' current custody checks replace
  legacy orphan sweeps and uncertain owner-only claim releases.
- Published after-landing-run green events replace landings cleared. QA
  verdicts/decisions/routes are records events and reports use today's locked
  writer, replacing free-form records/qa Markdown ledgers.
- Two dedicated pass slots are selected, not legacy four, with numeric walk
  slots determining reserve validation. Current configured walk numbers do
  not justify restoring legacy COUNT caps.
- Evidence stays in the legacy durable location but uses a separate metadata
  clone, never legacy runtime code. Preservation/publication retries cannot
  block login returns. Current walks gain preservation and pruning only at
  final end; old foreign states are not silently adopted.
- Clean passes generate records without director completion mail; attributed
  findings go straight to the saved coordinator. Exceptions still receive
  attention. Structured results prevent absent prose from looking cleared.

## 13. Questions — answered by coordinator q, 2026-10-30

- **Slots — answered:** dedicated s/qa pass shares on hetzner6 are **2 and
  6**. The selected walk allocation is forgejo **8 and 1**, claude **4 and
  3**: existing slots with warm targets, so no new target is made (5 and 7
  stay pool). Apply those settings only with the hosts change landed and
  successful disk checks. Reserve 2 covers forgejo's two ChatGPT slots and
  claude's two Claude slots separately; the common admission validation
  still checks the actually configured mappings during rollout.
- **Binding/rung and host — answered:** use the **reviewed live ChatGPT
  binding on the deployed after-landing host**, not the fake rung or a
  proposed undeployed host. Activation records the concrete approved binding
  path/rung and actual inventory host in the settings; no new design choice
  is delegated to the implementer and this doc does not guess those strings.
- **Default boundary — answered:** start at **activation main S**, with
  `qa default on --at S` and **no automatic backfill**. Important earlier
  work requires a separately reviewed backfill and explicit run decisions.
  Coordinator roster assignments still need their owners' concrete addresses;
  missing/historical routes use section 2.1's unresolved representation.

## 14. Later

- Automatic retry policy for incomplete passes, learned from costs and
  blockage causes; for now repeat work needs an explicit run decision.
- Multi-host pass scheduling and distributed admission authority, additional
  provider pools/rungs, adaptive batching and resource-based slot reductions.
- Reference-aware local authority-page and records/evidence GC, transcript
  preservation and a web findings view. Seven-day scratch pruning is not evidence retention expiry.
- Automated repair tasks, causality bisection of QA findings, or feeding QA
  verdicts back into merge-queue admission. A pass's found verdict proves
  neither the culprit nor that another merge is safe.
