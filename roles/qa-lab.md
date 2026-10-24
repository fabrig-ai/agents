# QA in the lab

Provisional, 2026-10-24. The lab run: a QA agent ([qa.md](qa.md)) that
a product owner starts on what has landed of its features, which drives
a running build in the lab, as a person's agent would, and reports to
that product owner. The lab's records, runner, verdicts and findings are
skein's `docs/design/lab.md`; temper's experiments, cluster, driver and
bounds are temper's `docs/design/qa.md`. This file cites them and never
restates them.

## 1. In one page

- **Started by the product owner** as something lands that it judges
  worth validating: its call, as soon as the landing allows. It may
  judge that a milestone needs none (product.md 4).
- **It drives a running build** through `temper ctl`, as an agent
  would (temper's `docs/design/client/tools.md`), on the lab's
  experiments, with the fakes the experiment names, or the live
  backends where its brief says.
- **The happy path first:** the feature's stories as a person would go
  through them, then what the brief allows beyond.
- **It commits no tests** (the user, 10-23). Its output is the lab's
  records and its report.
- **It reports to the product owner,** which sends each finding to the
  owner of the work, or judges it itself once that owner has ended.

## 2. The run

- **Its brief** names the feature, the commits that landed, the design
  sections and the stories they promise, the experiment (or the one to
  add, below), the machine, its budget and its notes directory,
  `tmp/owners/<name>/` like an owner's.
- **Only on what exists.** A run starts once what it drives has landed.
  Where a step it needs is missing (a tool of `ctl`, a fake's scenario,
  a part of the cluster), it reports the gap rather than build around
  it.
- **Calibrated first.** A new experiment's bounds (time, actions,
  tokens) come from a calibration on `main` before a verdict counts
  (temper's `docs/design/qa.md`, 6.3), and its checks from a planted
  fault they catch (qa.md 2).
- **Its records** are the lab's (`lab.md` 2), kept where `lab.md` 3
  says; its findings are entries of `lab.md` 9's form, and the report
  points at them.
- **The lab's tools stay small.** A run may add or fix an experiment's
  files and a small script in `scripts/lab/` or temper's `lab/`, landed
  with `land` like any change. A change that grows the runner or the
  lab's design goes to the product owner first: o/qa overbuilt its
  runner, and ran no paid driver in its whole mission.
