# Testing toward v0.1.0

Provisional, 2026-10-27, from the director's account to the user,
taken by them as the north star: "your write up for the QA/testing
strategy towards v0.1.0 is fantastic, please commit it somewhere under
docs/design so it remains as north star for you. Your job is to make
sure we are following it." What temper's `docs/design/draft/v0.1.0.md`
and the documents it names produce for testing and QA, from each
landing up to the release. The drafts hold the design; this holds how
it is proved, and the director checks the work against it (agents'
`roles/director-operations.md`).

## 1. In one page

- **Six layers, each from its own source** (sections 2 to 7): every
  landing's gates and tiers; QA after landing; the ladder of rungs on
  real backends; the reference case at the top; each part's own bar;
  the release, at one commit.
- **Proof flows down:** what a real walk finds becomes a test in the
  lowest world that shows it; a rung that passes leaves a live-tier
  story and a fake twin behind.
- **The bar is the ladder:** rungs 0 to B2 on ChatGPT with an owned
  Forgejo, then again on GitHub and on Claude; C, D and W above them.
- **Findings route by the happy path:** one on the ladder or a part's
  bar goes to the owner of what it names; the rest waits for after
  v0.1.0.
- **Nothing here moves a budget:** the real loop's 15 s, the tiers'
  ceilings and the bars are the user's.

## 2. Every landing: gates and tiers

| Source | What it produces |
|---|---|
| skein's `testing-strategy.md`, temper's `domain/testing.md` | each change's tests, in the lowest world that shows the behaviour; the real loop's default sum under the user's 15 s |
| `../qa.md`'s profile (temper), owners.md 4 | `qa_*` stories, skipped by the gates and run between a set's proof and its landing when the landing changes what a world's stories rely on |
| after landing's tiers (landing-flow.md 4) | the slower QA, process, lab and browser tiers on the newest `main`; a red bisected to its landing; temper's tier split across two runners |
| v0.1.0.md 4 | each finding's fix with a test in the lowest world that reproduces it, the real run's transcript as a fake model's script where the model's turn matters |

- **Flakes** that fail a gate or a tier go to the flakes' owner
  (director.md 11); a run starved of CPU passes and says so, an idle
  one fails (skein `testing-strategy.md` 2.8).

## 3. QA after landing

[qa-flow.md](qa-flow.md) with temper's `docs/design/qa.md`, its
binding.

- **A landing marks** what a user can now do, in its `QA:` trailers.
- **The director chooses** which marks to test (`qa decide`), from the
  ladder's priorities and the held login's room.
- **A QA session** drives temper through `temper ctl`, as people's
  agents do, and reads the forge through its API; it climbs `qa.md`'s
  rungs: fakes, a real model, GitHub. A rung lowers when its login or
  its findings hold it.
- **Findings** are triaged by the director (`qa triage`): on the happy
  path to the owner of what they name, otherwise to the backlog.

## 4. The ladder

temper's `draft/v0.1.0.md` 2 and 3; its stories from
`draft/reference-case.md`, mapped in temper's `domain/testing.md`
2.7.

| Rung | Story | What it leaves |
|---|---|---|
| 0 | a box's owned Forgejo set up through `ctl`; one chat turn on the held login | passed, 10-24 |
| A | the playground's three requests on a copy of `playground/widget`, one delegated, pushed, passed by CI and an agent's review, landed | a brief, walked, fixed, rerun unchanged as the pass |
| B0 | A, with a question and the person's answer (reference-case.md 4.2, 7.2) | the same |
| B1 | B0, with a gate the first push fails, and its repair (4.3) | the same |
| B2 | B1, with an advisor and two delegates, one depending on the other (4.1, 4.2) | the same |
| C | `reference-case.md`, act by act, by `process-model.md` | the top rung (section 5) |
| D | the case's process described to temper in words, its proposal accepted, C run under it | configuring's golden (section 6) |
| W | A and B walked through the web client | browser walks, after B2 and the user's word on the pages |

- **A rung is climbed** as a focused QA story: a brief a QA session
  walks, a report, an owner who makes it pass, the same brief rerun
  unchanged as the pass, in one sitting.
- **A passing rung leaves** a live-tier story bounded by the passing
  walk, run before the release and whenever a change touches it, and a
  fake twin in the worlds, replayed from its transcripts (temper's
  `tools/twin`).
- **The backends:** each rung climbs on ChatGPT with an owned Forgejo
  first; GitHub (connected, then managed) and Claude follow a rung
  behind; C runs with both plans. Each held login has one holder at a
  time.

## 5. The reference case at the top

`draft/reference-case.md`, applying `draft/process-model.md`.

- **On fakes:** each of its 20 steps a story, `fuzzy_case2_X_Y`, with
  each judgement scripted as the oracle.
- **On real backends, as rung C:** a QA driver types the person's words
  through `temper ctl`; each step is checked by its effects.
- **The process model's parts** are what C needs: its design names
  which of C's acts each part opens. It also brings QA after landing
  into the product (its T12): temper itself can run section 3's loop
  for its users.

## 6. Each part's own bar

temper's `draft/v0.1.0.md` 5, each part from its own draft.

| Part | What it produces for QA |
|---|---|
| configuring | rung D's golden: frozen copies of our own role files as the description; the settings temper proposes match a golden file; then C runs under them |
| upgrades | the store's disk format frozen, with golden stores and a test that a later build opens a v0.1.0 store; a baseline rehearsal first |
| the playground in the browser | story A walked in the gate and by the browser tier on the built playground; its bars (memory; the download, 6 MB gzipped) |
| documentation for agents | generated pages checked against the code's tables at every gate; the `box` walk of `temper help` is rung A's walk |
| the UI | each rung passing through `ctl` recorded as a journey of its pages, judged by the user; the user's look requests land the same way |
| the download | rung A walked from the released binary on a fresh machine, by `temper help` |
| public reading, the site | their bars in their own drafts, when the user's drafts come |

## 7. The release

temper's `draft/v0.1.0.md` 9, at one commit:

- every rung from 0 to B2 passes on ChatGPT with an owned Forgejo, and
  again on GitHub and on Claude;
- C passes, whole or close to it, what is left named for v0.2.0; D
  passes; W passes for A and B;
- no finding from the ladder is open;
- every part meets its bar;
- the user has taken the pages the ladder passes through;
- the download runs rung A on a fresh machine.

## 8. Following it

- **At each check** the director reads the work against this: which
  rung each owner climbs and which brief walks it, whether passing rungs
  have their live-tier stories and twins, whether QA after landing runs
  on its rung, whether each part's bar has its test, whether findings
  reach their owners.
- **A drift** (a rung skipped, a pass without its rerun, a part's bar
  untested, a budget moved) is the director's to correct with the
  designer it concerns, and the user's to hear when it changes this
  document.
- **This changes** when v0.1.0's draft or a part's draft changes, by
  the director, landed with `land --docs`.

## 9. Open questions

- **A rung's pass:** one sitting, or more, before the release (v0.1.0.md
  10).
- **Which of the case's acts** wait for v0.2.0, if any: decided as C
  climbs.
