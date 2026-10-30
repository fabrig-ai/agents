# The landing pipeline

Draft, 2026-10-30, the user's (written down by the director from the user's words of 10-30 ~11:45Z and the day's surveys; the user edits it). One of the system's two north stars, with `code-producing-pipeline.md`: everything done operation-wise comes from these two documents.

## 1. In one page

- **What it is:** everything between a branch marked ready and its change being known good on main: the merge queue (selection, batches, the gate's steps, bisection, the turn onto main), then the checks after landing (the slow tiers, QA after landing) and their verdicts.
- **The ideal state:** a ready branch lands on its first attempt within minutes; every red the queue reports is a real fault of the branch it names; no branch waits for another's fault; after landing, the slow tiers and QA give their verdict on each landed change soon after, and a red reaches the branch's owner at once.
- **It runs unattended:** nobody watches the queue for it to work; people and agents hear only what needs judgement.
- **Measured, not felt:** a small set of metrics (section 3) is computed continuously from what the queue and the checks record, and reported as a standing report (section 5). Each metric has a target; a metric off its target is a signal with an owner and a first action (section 4).
- **Every red teaches once:** each red or stall gets its cause and a remedy where the next agent reads it; a red of a class seen before gets a tool check, never another rule (section 6).

## 2. The ideal state

- **Latency:** ready to landed within one batch's duration plus a short wait; no growing queue of ready branches.
- **First-attempt success:** a branch that passed its own checks before ready lands on its first attempt.
- **No false reds:** a rejection always names a fault in the branch it rejects; no rejection hits a branch that later lands unchanged; no batch is red for load, timing, the machine or the tools.
- **Bisection is rare and cheap:** a red batch is split only when it holds more than one suspect, and the split finds the faulty branch in few extra runs.
- **The gate within its budgets:** each step and each tier within its CPU-time budget; "starved" (past the wall-clock hard limit) is a warning that we are short on CPU, never a red.
- **Headroom:** the queue is busy well below saturation, so a burst of ready branches drains without a backlog; when demand stays high, capacity grows (a parallel or speculative batch, a second gate, more builders) rather than the waits.
- **After landing:** every landed change gets its slow-tier verdict and, where marked, a QA pass, in order, without a growing lag; a confirmed red goes to its owner with its evidence; a fixed red is confirmed green by the same checks.
- **No outages:** the queue, the gate machine and the after-landing runner never stop for want of a login shell, disk, a lock, a stale checkout or a tool fault.

## 3. Metrics

Per hour and per day, per draft where it applies:
- **Ready-to-landed latency:** median and 90th percentile; the count of ready branches waiting and the oldest wait.
- **Queue utilisation:** the share of time a batch is running; batches per hour; branches per batch.
- **Batch outcomes:** green, red, error, conflict; the share of red batches.
- **Rejections by kind:** real (the branch's own fault, by gate step: conflict, fmt, clippy, build, tests, tools, budget) against collateral (a branch rejected in a red batch that later lands unchanged); the false-red rate.
- **Bisection cost:** extra runs and minutes per red batch.
- **Repair rounds:** rejections per landed branch; time from rejection to the repaired branch's landing.
- **Step durations and CPU:** per gate step (tools, fmt, clippy, build, default, fuzzy) and per tier, against its budget; starved warnings per tier.
- **After-landing:** lag from landing to verdict; coverage (landed changes with a verdict); verdicts by outcome; true positives against flakes; time to the owner and to the confirmed fix; QA passes per landed change and their findings.
- **Outages and waits:** minutes the queue or runner was stopped, by cause; disk-admission waits at the gate.

## 4. Signals and first actions

| Signal | First action | Owner |
|---|---|---|
| ready branches waiting or the oldest wait grows for an hour | look for a stuck batch; else capacity (section 2, headroom) | ops |
| utilisation above the target for a day | throughput work: parallel or speculative batches, a second gate, the gate's slowest step | ops, with the pipeline's designer |
| a collateral rejection (false red) | the red's cause found and ledgered; a test failing under load retried once before bisecting; a flake goes to its owner | ops, the test's owner |
| a real rejection the branch's own checks could have caught | the precheck learns it (a tool check), not a role's text (a rule) | ops |
| a step or tier over its CPU budget | the three questions: does the test belong to this tier; can it be made faster; else report to the user | the tier's owner |
| starved warnings rising | the CPU picture: builders, gate, concurrency | ops |
| after-landing lag growing, or coverage below all | coalescing, runner capacity, the tier's budget | the after-landing owner |
| an outage | restart through the tool; the cause ledgered with a remedy in the tool | ops |

Targets (numbers) are the user's, set from the first week of measurements; until then each metric is reported with its trend.

## 5. The standing report

- **Generated, never kept by hand:** computed from what the queue and the checks record (the queue's log, the after-landing verdicts, the records' per-task summaries).
- **Daily,** and on demand: the metrics of section 3 against their targets, the signals raised and what was done about each, the red classes of the day.
- **To the director,** who passes the user what needs the user (targets, capacity, a red the three questions could not resolve).

## 6. Learning from reds

- **Every red or stall that cost throughput gets a ledger row:** what happened, its cost, its remedy and where the remedy lives (a tool, a rule, a test approach), within the hour.
- **A red of a class already in the ledger gets a tool remedy:** a check that fails before ready, or a queue behaviour, not another line in a role file.
- **The report shows classes, not only incidents:** a class that keeps returning is the next thing to fix.

## 7. Later

- Targets for each metric, once a week of numbers exists.
- A second gate or speculative batches, when utilisation says so.
- QA after landing on every marked change by default, once its scheduler runs unattended.
