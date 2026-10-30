# The code-producing pipeline

Draft, 2026-10-30, the user's (written down by the director from the user's words of 10-30 ~11:45Z and the code-pipeline survey of that morning; the user edits it). One of the system's two north stars, with `landing-pipeline.md`: everything done operation-wise comes from these two documents.

## 1. In one page

- **What it is:** everything between the user's draft and a branch marked ready: the coordinator designs and splits the work into parts, leads turn parts into tasks, Codex implementers write and check each task, and the lead marks the result ready for the landing pipeline.
- **The ideal state is a growing pipeline:** the coordinator starts a small first wave as quickly as possible, its leads do the same, implementers start at once; while they build, the coordinator and the leads think further and design the next waves; waves get bigger over time until the work runs as much in parallel as the work and the capacity allow, and it never stops while work remains.
- **It runs unattended:** coordinators, leads and implementers keep the flow going without the user; the user hears only what is the user's.
- **Measured, not felt:** the metrics of section 3 are computed from what sessions, runs, the queue and records already record, and reported as a standing report (section 5), the code-pipeline survey of 10-30 made permanent. Each metric off its target is a signal with an owner and a first action (section 4).
- **Every stop teaches once:** each thing that stopped the flow gets its cause and a remedy; a stop of a class seen before gets a tool or a template change, not another rule.

## 2. The ideal state

- **Fast start:** a lead's first task within minutes of the lead starting; a draft's first landing within the first hour.
- **Growth:** implementers in flight rise wave by wave to the limit the work's independence and the capacity allow, and stay there while work remains; a cap set for the first wave is lifted after the first clean landing.
- **No idle gaps:** no area, lead or line of work sits without a running task while it has work and capacity; a coordinator's or lead's pause (handover, a parked session, a usage limit) does not stop its implementers, who carry on down a pre-approved list.
- **Right-sized tasks:** each task is one coherent change a single implementer finishes in one run, small enough to review, large enough to be worth a branch; production code and its tests together.
- **Few questions:** an implementer asks only beyond what its task settled up front (its files, the readers and neighbours it may change, the likely options with defaults); a lead asks its coordinator only what the design leaves open; the coordinator asks the user only what is the user's.
- **First-time ready:** a task's branch passes its own checks and its readers' tests before ready, so it lands on its first attempt (the landing pipeline's first-attempt success starts here).
- **No infrastructure stops:** no task stops for disk, a slot, a lease, a machine's load, a usage limit or a permission prompt; capacity follows demand (builders added and retired as needed).
- **Continuity:** a session's end or succession loses nothing and stalls nothing; every session's state is in its files.

## 3. Metrics

Per draft, per area and per lead, per hour and per day:
- **Start-up:** time from a coordinator's start (or a part's brief) to the first lead, the first implementer task and the first landing.
- **Flow:** implementers in flight over time against the capacity available; tasks started, readied and landed per hour; waves and their sizes; idle gaps (area, length, cause).
- **Task size:** lines changed per landed branch (production, tests, docs, aggregate: mean, median, largest); Codex runs and Codex minutes per task.
- **Questions:** questions per implementer report and per lead-hour, by kind (design, scope or permission, disk, tooling, a red base, other); time to answer; resumes they cost.
- **Repairs:** review rounds and queue rejections per task, with their causes.
- **Waits:** slot, lease, disk admission, heavy, usage limits, permission denials, machine load: minutes per task and in total.
- **Continuity:** handovers and their duration; sessions deaf or gone and for how long; relaunches.
- **Capacity:** Claude and Codex usage against their limits; builders' slots, CPU and disk in use against what they have.

## 4. Signals and first actions

| Signal | First action | Owner |
|---|---|---|
| no first task within the start-up target | the lead's brief and the part's readiness | the coordinator |
| implementers in flight flat below capacity while work waits | widen: more leads on independent parts, more implementers per lead | the coordinator |
| an idle gap while work exists | its cause: a missing pre-approved list, a lease, a parked session | the coordinator; the lease holder |
| the question rate above its target | the task template: settle scope and options up front (`lead.md` 2) | the leads; the role files' keeper |
| repair rounds or queue rejections per task rising | readers' tests before ready; the precheck; the task's scope | the leads; ops |
| infrastructure waits (disk, slots, load) | capacity: bounded slots, more or bigger builders, elastic provisioning | ops; s/deploy |
| a usage limit near | slow down by the director's capacity rule; tell the user | the director |
| a session deaf, gone or a handover late | the watch's ladder: wake, restart from files, escalate | the watch; the supervisor |

Targets (numbers) are the user's, set from the first week of measurements; until then each metric is reported with its trend.

## 5. The standing report

- **The 10-30 code-pipeline survey, made standing:** generated from records (per-task summaries, sessions, runs, the queue's log), not assembled by hand.
- **Daily per draft,** and on demand: the metrics against their targets, the growth curve, the stops ranked by time lost, what changed since the last report.
- **To the director and the coordinators;** the director passes the user what needs the user.

## 6. Placement and capacity

- **hel8 runs only the director.** Coordinators, leads, implementers, the operator and every other agent session run on builders (the user, 10-30); hel8 keeps services (records, the status page, dev.fabrig.ai, git.fabrig.ai).
- **Capacity is predictable:** each builder's disk is the cache's cap, plus its slots each within a bounded warm footprint, plus a small headroom for operation data; a builder with more slots than that holds fewer; demand beyond the slots starts a builder, and slack retires one.
- **Capacity is the user's to buy:** the director reports the numbers and asks.

## 7. Later

- Targets for each metric, once a week of numbers exists.
- Elastic builders: provisioning and retiring by demand, with the user's limits.
- Comparing lead kinds (Claude, Codex) and effort levels by these metrics, to choose per part.
