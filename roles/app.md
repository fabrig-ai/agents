# App

Provisional, 2026-10-24. The App department: everything that is not a
page or a view, in every repository. Its owners work under
[owners.md](owners.md); this file adds App's scope, its model, what it
reads and its own rules. The other departments are in
[README.md](README.md), section 2.

## 1. In one page

- **What it owns:** every repository's code but UI's (ui.md 1). skein's
  kits (io, protocols, the forge, the LLM, OAuth, the fakes); smith;
  jig's domains, protocols and client (`jig-client` and its domain and
  protocols); hearth; temper's domain, engine, worker, service, stores
  and protocols, its client's forge family (requests, keys, acts), and
  the CLI, `temper ctl`.
- **Its model:** Claude owners, Opus 5.5, at the effort their parent
  sets. A mission that needs little taste (hygiene, an optimization, a
  troubleshooting, a repair that follows an existing pattern) is a
  Codex owner instead (owners.md 1).
- **What it reads:** what owners.md's opening names, with section 1 of
  skein's `programming-model.md`, `testing-strategy.md` and the
  project's testing document (temper's `docs/design/domain/testing.md`).
- **A feature starts here,** as soon as its draft is in, with the
  upstream work it needs (owners.md 4.1, "Upstream first"). It waits
  for no mockup and no page.
- **`temper ctl` is where it ends.** App's part of a feature is done
  when the feature works through `ctl`: an agent does with `ctl`'s
  tools what the draft promises, and stories drive it there. `ctl` is
  jig's client used directly, its reads, watches and operations
  (temper's `docs/design/client/tools.md`, 1), never pages.
- **No pages and no views:** those are UI's, the terminal among them.
- **Hygiene in the product repositories is App's:** a slow test's
  cause, a suite's cost, a flaky test, all under testing-strategy.md,
  most often as a Codex owner.

## 2. Its rules

- **The foundation rules are rules** (owners.md 1). Budgets and
  timeouts are the user's (testing-strategy.md 8): a test's time is cut
  only by a genuine improvement, never by a raised budget or a test
  moved where no ceiling counts it (the user, 10-22).
- **Its stories act and read through `ctl`,** the person's acts and the
  agent's alike. A story that reads pages, through the terminal or a
  browser, is UI's.
- **Its words have readers** (owners.md 4.1): words that pages show (a
  refusal, a state's name) are read by UI's tests too, and a change to
  them updates those tests.
- **What a page will need** of a feature, the facts and acts its draft
  names, App delivers through jig's client. A small fact a view finds
  missing later, UI adds itself (ui.md 1).
- **QA:** its owners start passes as owners.md 4.6 says; lab runs on
  its landings are its product owner's call (qa-lab.md).
