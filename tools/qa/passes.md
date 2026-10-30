# QA passes after landing

Provisional, 2026-10-30. Proposed contract for unattended fabrig passes;
not implemented or activated. Walks remain described by [qa.md](qa.md).

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
- **A pass has one existing numeric slot.** Two pass slots on hetzner6 are
  separate from walks' slots 4 and 8. Claims, preparation, launch recovery,
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
  at the queue, records, scheduler and cleanup boundaries. Section 13 names the
  activation questions the sources cannot answer.

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

Extend the successful publication row with ordered `merges` entries:
`{name, tip, commit, parent, coordinator}`. Here name is the ready branch,
tip is B, commit is M, parent is P, and coordinator is a fully qualified
mailbox. Also retain the published batch `commit` and `parent`. A row describes
only merges in the confirmed published batch; conflicts, rejected halves,
dry runs, preparations and unknown push outcomes supply no landing. Recovery
must reconcile publication and append the same merge identities if the push
succeeded but its journal acknowledgement was lost.

Extend `leads.txt` to `KEY LEAD_ADDRESS COORDINATOR_ADDRESS`, preserving the
lead destination for queue notifications. A landing snapshots the third
column from the queue's loaded configuration when it publishes. Validate
unique keys and hosted addresses. A missing route is an explicit unresolved
coordinator, never a guessed lead-to-coordinator substitution; QA sends that
finding to the director. Updating the roster later must not reroute old
findings. Update every two-column reader, including record-collect, in that
producer change. Do not derive a coordinator from a prefix or mission README.

Have record-collect publish a source `queue`, kind `merge` event per entry,
with id `merge:<full M>`, the batch tip, P, B, branch and coordinator. Events
also name their source journal path. Preserve the existing batch/attempt
events. A producer outbox retains exact rows and timestamps across retries;
after a lost acknowledgement, a confirmed publication is replayed by id.
QA pulls these events through records, validates their graph claims against
its own fabrig fetch, and saves the route and event reference. It needs no SSH
reader on the queue host. This is a new feed contract and needs queue and
collector fixtures before activation.

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

The latest selection event wins: a default supplies an implicit run at its
on event, an explicit decision overrides it, and a pass's durable take consumes
that request. Order control events by the QA authority's increasing selection
sequence, not timestamps; at a tie an explicit decision beats the default,
and a take beats the decision it consumed. The sequence and consumed request
id are saved under admission before publication. Records replay reconstructs
the same ordering. A decision after a take requests a follow-up; it cannot
cancel a session or overlap another pass on the same merge. A prelaunch
reservation cancelled with proven no launcher restores its consumed request;
a possibly launched pass keeps it taken. Publish a cancellation event with
the restored request ids so records replay reaches the same choice; never
restore over a later explicit decision. A capped, failed or blocked pass
does not automatically loop on the same request: it remains visible as
uncleared and needs `qa decide ... run`. New marked merges still run unattended.

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
the next check. Save every disjoint share and take event before launching
the first session; restart cannot give two passes the same request.

Each brief names G, M/P/B, every marked SHA and exact trailer, branch,
coordinator, green event, numeric slot, scratch, rung, login names/resting
paths, cap and report path. It directs the session to read fabrig's rules and
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
length is the pass cap. Configure two on hetzner6 after allocation (section
13); there is no inferred pair of free numbers, fallback clone or use of a
walk slot. Reject duplicate pass numbers and overlap with any configured
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

Each step saves progress by sibling-and-rename before the next. An unavailable
writer never prevents a login return; an unavailable login never prevents
record publication or a stuck alert. Cleanup continues on every check after
the outcome is recorded. Preserve the current exceptional one-attempt
attention receipts for uncertain releases/orphan ownership and overdue
launches; these differ deliberately from retryable stuck/completion posts.
Normal complete clean passes need no director post. Capped, failed, blocked,
unreadable-report and metadata exceptions do. Do not use a walk's pause marker
to retain a pass box indefinitely.

## 7. Reports and verdicts in records

Reports are `qa/passes/NAME.md` in the private records repository. Add this
path class, an 8 KiB UTF-8 cap, and front-matter validation to `record`.
Use a leading `+++`-delimited TOML header, parsed with tomllib.
Required fields are repository (`fabrig`), pass, main G, green event,
merge/marked-commit lists, rung, host, slot, model/effort, run, started/ended,
wall, tokens (unknown allowed), outcome, login **names**, and evidence
(`unknown`, `refused`, or commit plus directory). Never credential contents.
Write a running report before launch and a completed safe report at end;
later evidence linkage replaces metadata without creating new findings.
Keep findings before cases when abbreviating to 8 KiB; the whole safe report
is available in evidence. Oversize findings require a safe evidence reference
and an explicit truncation note rather than silently losing a finding.

Register `[qa] sources = ["qa"]` in writers.toml. Extend records' producer
permissions explicitly: `qa` may append source qa and write only
`qa/passes/NAME.md`. Today declared producers are append-only and cannot use
`write`; merely adding the writer declaration is insufficient. No generic
judgement or director-file permission is granted. Use proposed
`record write --as qa qa/passes/NAME.md --from SAFE_REPORT` and existing
`record append --as qa --batch HOST` for events.

All events have record's id/time/source/host envelope; source is `qa`, ids
and original UTC timestamps persist in the outbox. Carry `commit` (M for a
merge result), `branch`, `coordinator`, `run` when known, report and evidence
references. Keep each line under 16 KiB; details go in safe report/evidence,
not command outputs in an event.

| Kind | Natural identity and facts |
|---|---|
| `qa-default` | `default:UUID`; selection sequence, on/off, boundary SHA, reason |
| `qa-decision` | `decision:UUID`; sequence, M, marked SHAs, run/backlog, reason |
| `qa-pass-start` | `NAME:start`; selection sequence, consumed request ids, G, green event, merges, slot, rung, report |
| `qa-pass-end` | `NAME:end`; done/capped/failed, wall/tokens, blocked counts and report |
| `qa-pass-cancel` | `NAME:cancel`; proven unlaunched, restored request ids, sequence and reason |
| `qa-merge` | `NAME:merge:M`; verdict cleared/found/incomplete, marked SHAs, case/finding numbers |
| `qa-finding` | `NAME:finding:N`; likely marked SHA/M or unknown, concerns, report anchor, evidence reference |
| `qa-route` | `NAME:route:N:REV`; recipient or backlog/drop, finding id, reason and delivery acceptance |
| `qa-evidence` | `KIND:NAME:evidence:REV`; kept/refused, commit/directory or safe refusal digest |

`cleared` means every mark in that merge received its planned happy/tricky
cases with observed expected results, no blocked case and no attributed
finding, in a normally completed pass. `found` means at least one finding
attributed to that merge; it does not prove causation. Otherwise the merge
is `incomplete`, including an absent/unparseable/unsafe report, cap or setup
failure. An unknown-attribution finding prevents clearance of the whole
pass's selected merges until reviewed; never infer clearance from the
absence of a Findings heading. Verdicts describe that pass, not all future
main. A subsequent run adds events; it does not erase findings or history.

Require exactly one TOML result block between whole-line
`<!-- qa-results -->` and `<!-- /qa-results -->` sentinels, without a Markdown
fence inside. Its version is `version = 1`; its arrays of tables are:

- `[[merges]]`: `commit` (M), `marked` (the exact SHA array from the brief).
- `[[cases]]`: unique string `id`, `merge` (M), `commit` (a mark in M),
  `kind` (`happy` or `tricky`), `outcome` (`ok`, `finding` or `blocked`),
  nonempty `expected` and `observed` strings; `finding` is a positive finding
  number and is required only for a finding outcome.
- `[[findings]]`: unique positive integer `number`, `commit` (marked SHA,
  M or `unknown`), `concerns` (`ordinary`, `security` or `lost data`), nonempty
  `title`, `reproduce`, `expected`, `observed`, and `evidence` (safe relative
  capture path or `none`). No findings uses an empty array, not a missing key.

Every selected M appears once; every marked SHA has exactly one happy case
and two to four tricky cases. A blocked case still has an observed explanation.
Every finding reference resolves and every finding appears in the human body
under the same number. The service validates against the brief; duplicate or
missing marks/cases, conflicting fields and unknown status yield incomplete,
not cleared. The human Cases/Findings/Automation/Blocked body explains these
results. Fixture both header and result schemas in the records-contract part
before the scheduler relies on them.

Report confirmation precedes dependent end/verdict/finding events, and those
events precede routing posts. Every successful record call must confirm the
remote publication as record.md specifies. Preserve exact pending bytes
after exit 3, a conflict, timeout or lost reply; retries with the same ids
and dates are idempotent. A failed publication does not release a consumed
request for another pass. Late evidence updates append qa-evidence and
update the report link; they never reroute old findings.

## 8. Findings and the coordinator

Resolve a finding's marked Commit to its carrying merge from section 2 and
route to that landing's saved coordinator mailbox. A finding naming M
directly uses M. A commit outside the pass's marks is unresolved unless an
unambiguous saved carrying marked landing establishes it. Missing/unknown
commit, ambiguous duplicate Commit/Concerns, no landing route, security or
lost-data concerns go to the director. Stuck logins and infrastructure/input
exceptions also go there. The queue's lead address is not a fallback, and
the director is not copied on ordinary attributed findings.

After confirmed report and finding-event publication, persist an outbox item
per finding and recipient. Send as qa-watch, subject bounded to 200 characters,
body under 15 lines: stable finding event id, G, M, marked SHA, title,
records report path/anchor, evidence repository/commit/directory (or refused/
pending status), and machine. If evidence is pending, also name the retained
scratch path, explicitly local to that host. Never put raw captures or
secret-match text in a post. Post exits 0 and 3 are accepted; save the receipt
before appending qa-route. A crash between delivery and receipt can repeat a
post; the stable event id lets the recipient recognize it. A records retry
after a saved receipt sends no post again.

`qa findings` lists finding events without a route or with a failed delivery.
`qa triage PASS N owner ADDRESS|backlog|drop [--why TEXT]` records a manual
override and revision; owner sends through the same outbox. Backlog/drop stay
as route events, not invented director/backlog.md writes. Finding numbers
stay stable across report metadata updates. An unreadable route does not
disappear from the queue; the director's exception and its retry are durable.

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
For the records report only, unsafe body lines become `(withheld: RULE)`;
unsafe findings keep a safe numbered heading and route an exception without
their text. Scan all report metadata, routes, event fields and generated
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
| `QA_PASS_SLOTS` | empty / two allocated hetzner6 numbers | Same compact number-list grammar as walk slots; empty disables starts |
| `QA_BATCH` | 5 | Positive marked merges per pass |
| `QA_CAP_MINUTES` | 120 | Positive; persisted at launch |
| `QA_LOGIN_RESERVE` | 2 | Nonnegative; at least each pool's summed walk slot caps |
| `QA_PASS_RUNG` | unset until binding reviewed | Lowercase rung slug; must exist in binding |
| `QA_PASS_BINDING` | unset until binding reviewed | Safe repo-relative Markdown path at G |
| `QA_PASS_POOLS` | `chatgpt` | Unique base pools in compact + separated form; explicit none for fakes |
| `QA_AFTER_LANDING_HOST` | unset until activation | One authoritative hosted records producer; required for starts |
| `QA_EVIDENCE_KIB` | 2048 | Positive snapshot cap |
| `QA_EVIDENCE_SECONDS` | 120 | Positive total bound per keep attempt |
| `QA_RETENTION_DAYS` | 7 | Fixed policy for this design; no deletion before it |

Reuse QA_INTERVAL_SECONDS=300, QA_STOP_SECONDS=50,
QA_GIVE_BACK_SECONDS=90 and existing slot host/claim owner/transport settings
and bounds from qa.md. Validate pass-only settings for pass admission without
preventing already held walks or passes from cleaning up after a settings
error. Settings lowering capacity never invalidates saved ownership.

Local state under DEV_TMP/qa (0700 directories, 0600 metadata) consists of
`passes/NAME.json`, existing `walks/NAME.json`, `selection.json` (sequence,
defaults/decisions, consumed requests and feed/snapshot cursors), publication
and post outboxes, evidence snapshots, attention receipts and tombstones.
Pass scratch is `DEV_TMP/qa-passes/NAME/`, walk scratch remains qa-focused.
Names contain host, UTC start and a random suffix, avoiding same-minute
collisions. Saved pass state includes the complete mark/route mapping, G and
green event, request ids, slot/claim/checkout sequence, grants and kinds,
task/report/run/launch observations, immutable cap, cleanup steps, report
digest, verdict/finding ids, evidence tree/status, delivery receipts and
end/prune times. State files are bounded, descriptor-validated and atomically
replaced as today's walks. Corrupt state blocks affected admission and stray
custody reconciliation without stopping other valid cleanup. State may be
rebuilt from confirmed records only under an explicit recovery procedure;
records alone cannot prove that a live deployment no longer owns resources.

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

1. Load safe saved states and current settings; recover possible launches
   before considering starts. A busy admission lock still permits current
   read-only overdue-launch attention, never custody mutations.
2. Under admission, obtain strict inventory and reconcile each owned walk
   and pass: cap stops, wrapper completion, grants, deployments, claims and
   saved attention. Isolate failures per state and preserve foreign custody.
3. Outside admission, retry safe evidence/report/event outboxes and accepted
   receipt bookkeeping, then finding/exception posts whose publications are
   confirmed. A publication deferral never prolongs an unlaunched reservation:
   cancel it through cleanup; uncertain launches retain custody.
4. Pull records once and fetch metadata with bounded calls. Validate feed
   completeness, main ancestry, defaults/decisions and authoritative green
   runs. If any admission input is unavailable, keep reservations unchanged
   and skip starts. Other cleanup, outbox and prune work continues.
5. Under admission, recheck counts/claims and plan disjoint shares; pending
   control publications disable new starts until resolved. Claim and prepare
   slots before taking logins. Persist all reservations/takes, publish
   running reports/start events, then launch complete admissions only. If
   publication waits, cancel proven unlaunched reservations through cleanup
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

Producer changes additionally extend records/test_record_collect.py and
test_record.py with the queue merge projection, narrowly scoped QA report
writes, invalid schemas and publication replay. Queue's own fake-origin
tests cover route snapshot, merge journal/recovery and all roster readers.
Run focused suites with Python 3.13 `-I -B`, then tools/check.sh in agents;
fabrig's producer change uses its queue tools gate. No cargo/heavy or live
machine test is required to review this design.

## 12. Implementation boundaries and legacy departures

Implement as reviewable parts with explicit dependencies:

1. **Queue feed:** fabrig tools/queue roster, confirmed merge journal and
   recovery; agents record-collect merge events. Publish fixtures/contracts
   together. This supplies stable landing identity and historical coordinator.
2. **Records contract:** scoped qa writer, report path/schema, event validation
   and replay; define the TOML result block and a pure selection/feed/green
   reader using local origins. No scheduler before these two parts pass.
3. **Preservation:** common snapshot scanner and evidence writer, keep CLI,
   walk final-end integration and guarded pruning. Preserve walk safety and
   earlier attempt reports before adding pass scheduling.
4. **Pass lifetime:** common slot/admission/claim/launch/deploy/cleanup code
   for pass states with regression tests for walks; no watcher scheduling
   until faked crash/custody worlds pass.
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
- Two pass slots are proposed, not legacy four, with actual numeric walk
  slots determining reserve validation. Current configured walk numbers do
  not justify restoring legacy COUNT caps.
- Evidence stays in the legacy durable location but uses a separate metadata
  clone, never legacy runtime code. Preservation/publication retries cannot
  block login returns. Current walks gain preservation and pruning only at
  final end; old foreign states are not silently adopted.
- Clean passes generate records without director completion mail; attributed
  findings go straight to the saved coordinator. Exceptions still receive
  attention. Structured results prevent absent prose from looking cleared.

## 13. Questions

- **Which two hetzner6 numeric slots?** Options: allocate two additional s/qa
  shares, or obtain two explicitly lent pool slots. Recommend two dedicated
  shares with fleet-created fabrig clones. The sources assign only walks'
  4 and 8; no other slot is authorized here. Pass starts stay disabled until
  ops/director allocates the pair; walks keep their slots.
- **Which fabrig binding/rung and after-landing producer host at activation?**
  Options: review the current live-model binding and ChatGPT pool, or start
  with its no-login fake rung. Recommend the reviewed live-model binding,
  ChatGPT reserve 2, and ops's actual after-landing host. The sources propose
  a host but do not establish its activation, and do not identify an approved
  monorepo binding/rung. Set the explicit settings only after that review.
- **Where does the default begin, and do old marks need backfill?** Options:
  activation main S with no backfill, or an older reviewed S plus reconstructed
  merge/route events. Recommend activation main with `qa default on --at S`;
  select important older work through explicit decisions after a reviewed
  backfill. New third-column roster entries require coordinator review,
  rather than guessing historic ownership from today's leads.

## 14. Later

- Automatic retry policy for incomplete passes, learned from costs and
  blockage causes; for now repeat work needs an explicit run decision.
- Multi-host pass scheduling and distributed admission authority, additional
  provider pools/rungs, adaptive batching and resource-based slot reductions.
- Reference-aware records/evidence GC, transcript preservation and a web
  findings view. Seven-day scratch pruning is not evidence retention expiry.
- Automated repair tasks, causality bisection of QA findings, or feeding QA
  verdicts back into merge-queue admission. A pass's found verdict proves
  neither the culprit nor that another merge is safe.
