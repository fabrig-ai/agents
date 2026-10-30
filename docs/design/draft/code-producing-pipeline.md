# The code-producing pipeline

Draft, 2026-10-30, the user's (written down by the director from the user's words of 10-30 ~11:45Z and the code-pipeline survey of that morning; brought in line with `execution-modes.md` the same evening, at the user's word; the user edits it). One of the system's two north stars, with `landing-pipeline.md`: everything done operation-wise comes from these two documents. How the pipeline works (its roles, modes, calls and runs) is `execution-modes.md`; this draft says what it is for and how it is measured.

## 1. In one page

- **What it is:** everything between the user's draft and a branch marked ready: the designer cuts the draft into parts, a skeleton author designs each part as code, Codex implementers fill it, and the dispatcher, which is code, keeps the flow and marks the result ready for the landing pipeline (`execution-modes.md`).
- **The ideal state is a growing pipeline:** a small first intake starts as quickly as possible and implementers start at once; while they build, design runs just ahead of them, part by part; the work grows as parallel as the work and the capacity allow, and it never stops while work remains.
- **It runs unattended:** code keeps the flow going without the user, and Claude is called for design and judgement, never resident; the user hears only what is the user's.
- **Measured, not felt:** the metrics of section 3 are computed from what runs, calls, the queue and records already record, and reported as a standing report (section 5). Each metric off its target is a signal with an owner and a first action (section 4).
- **Every stop teaches once:** each thing that stopped the flow gets its cause and a remedy; a stop of a class seen before gets a tool or a template change, not another rule.

## 2. The ideal state

- **Fast start:** a draft's first implementer about an hour after the draft lands; its first landing soon after.
- **Growth:** implementers in flight rise from a small start to the limit the work's independence and the capacity allow, and stay there while work remains; the limits are indicative, the flow and the discipline are what matter.
- **No idle gaps:** no part or line of work sits without a running task while it has work and capacity; a pause of a call or a question parks only the task that needs the answer.
- **Right-sized tasks:** each task is one module or concept a single implementer finishes in one run, production code and its tests together; longer runs are better than more round trips.
- **Few questions:** an implementer asks only beyond what its task settled up front (its files, the readers and neighbours it may change, the likely options with defaults); what the options settle is settled without Claude; the user is asked only what is the user's.
- **Separate sessions design, accept and review:** the session that designs a thing never accepts it.
- **First-time ready:** a task's branch passes its own checks and its readers' tests before ready, so it lands on its first attempt (the landing pipeline's first-attempt success starts here).
- **No infrastructure stops:** no task stops for disk, a slot, a machine's load, a usage limit or a permission prompt; capacity follows demand (builders added and retired as needed).
- **Continuity:** nothing lives only in a session: plans, designs, specs, the log and reports hold the state.

## 3. Metrics

Per draft and per part, per hour and per day:
- **Start-up:** time from a draft landing to its cut, its first implementer task and its first landing; time to each slice.
- **Flow:** implementers in flight over time against the capacity available; tasks started, readied and landed per hour; the ready-task buffer against its band; idle gaps (part, length, cause).
- **Task size:** lines changed per landed branch (production, tests, docs, aggregate: mean, median, largest); Codex runs and Codex minutes per task.
- **Questions:** questions per implementer report, by kind (design, scope or permission, disk, tooling, a red base, other); the share settled without Claude; time to answer; reruns they cost.
- **Repairs:** review rounds, gate refusals and queue rejections per task, with their causes.
- **Waits:** slot, disk admission, heavy, usage limits, permission denials, machine load: minutes per task and in total.
- **Cost:** Claude and Codex usage, their weight and their ratio; each call's peak context.
- **Capacity:** Claude and Codex usage against their limits; builders' slots, CPU and disk in use against what they have.

## 4. Signals and first actions

| Signal | First action | Owner |
|---|---|---|
| no first task within the start-up target | the cut and the first parts' readiness | the designer |
| implementers in flight flat below capacity while work waits | widen: more parts designed ahead, independent parts at once | the dispatcher's keeper |
| an idle gap while work exists | its cause: a missing pre-approved option, a parked question, a dependency | the dispatcher's keeper |
| the question rate above its target | the task template: settle scope and options up front | the skeleton author's role text |
| repair rounds or queue rejections per task rising | readers' tests before ready; the precheck; the task's scope | the skeleton author; ops |
| infrastructure waits (disk, slots, load) | capacity: bounded slots, more or bigger builders, elastic provisioning | ops |
| a usage limit near | slow down by the director's capacity rule; tell the user | the director |

Targets (numbers) are the user's, set from the first week of measurements; until then each metric is reported with its trend.

## 5. The standing report

- **Generated from records,** never assembled by hand: runs, calls, the queue's record and the log.
- **Daily per draft,** and on demand: the metrics against their targets, the growth curve, the stops ranked by time lost, what changed since the last report.
- **To the director;** the director passes the user what needs the user.

## 6. Placement and capacity

- **hel8 runs only the director, the dispatcher and the calls,** with its services (records, the status page, dev.fabrig.ai, git.fabrig.ai); Codex runs and builds run on builders.
- **Capacity is predictable:** each builder's disk is the cache's cap, plus its slots each within a bounded warm footprint, plus a small headroom for operation data; a builder with more slots than that holds fewer; demand beyond the slots starts a builder, and slack retires one.
- **Capacity is the user's to buy:** the director reports the numbers and asks.

## 7. Later

- Targets for each metric, once a week of numbers exists.
- Elastic builders: provisioning and retiring by demand, with the user's limits.
- Comparing kinds (Claude, Codex) and effort levels for each role by these metrics, to choose per part.
