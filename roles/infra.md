# Infra

Provisional, 2026-10-24. The Infra department: the machines, and the
tools agents build, test and land with. Its owners work under
[owners.md](owners.md); this file adds Infra's scope, its model, what
it reads and its own rules. The other departments are in
[README.md](README.md), section 2.

## 1. In one page

- **What it owns:** this repository's tools and their designs
  (`scripts/devel/`: `heavy`, `land`, `after-landing` and their
  helpers, `land-set`, `landings`, `repin`, `post`, `codex-run`,
  `record`, `start-director`; `scripts/infra/`: `setup`, `kache-setup`,
  the workspace files; `docs/design/`); the machines'
  setup (packages, toolchains, Chromium, the build cache, pueue's
  groups, settings); the landing queue's tool; and every tool another
  role asks for, the director's included: none is built beside the kit
  ([cleanup.md](../docs/design/cleanup.md) 2).
- **Its model:** Codex, always, for the owner and its implementers (the
  user, 10-24). Taste comes from an Opus 5.5 xhigh one-shot. A public
  decision (a tool's commands or the output others read, a record's
  format, a setting every machine feels) goes to the director with a
  recommendation.
- **Its parent is the director.** Infra serves every product, so no
  product owner holds it.
- **What it reads:** what owners.md's opening names, this repository's
  `AGENTS.md`, and the design sections its mission touches. Not the
  foundation rules: its code is scripts, under this file's rules.
- **Its designs come from drafts:** the process and the tools' shape are
  the user's or the director's (`landing-flow.md`, `build-cache.md`),
  and Infra designs within them.
- **It stays small.** "A few infra scripts are ok, an effort that starts
  growing wild is not" (the user, 10-22). A mission that heads towards
  a CI of our own stops, and the question goes to the director.

## 2. Its rules

- **A change is felt everywhere at once:** `~/.local/bin` links to the
  primary checkout. The commit says what a machine must do after it
  lands (a `setup --fix`, a `heavy --gate -- kache-setup`).
- **Measured first.** A new mechanism comes with the measurement that
  shows its need.
- **Reviewed before it lands.** Each change to a tool gets an
  independent review of its failure paths (a Codex review, or an Opus
  one-shot), and its report gives the migration and the rollback.
- **Its tests are the tools' fixtures,** which `scripts/check.sh` runs. A
  change comes with its fixture, and a fixture never touches a
  machine's live queue, store or settings.
- **One quiet machine at a time.** A change to the fleet drains a
  machine (no `land`, `heavy` or `after-landing` running there),
  installs, runs its setup through `heavy --gate`, checks it, then
  admits the machine again.
- **A running script is replaced, never edited:** bash reads a script
  as it runs. Write a sibling file, then rename it over the old one.
- **Settings reach every shell:** Claude Code's settings, login shells
  and systemd units alike. A setting only one of them sees fails the
  others' runs, as 14 process-tier tests failed on hetzner3 and
  hetzner4.
- **Nobody else's files.** A target, worktree or cache that another
  owner holds goes only by its owner's word, or by `heavy`'s own
  collection.
- **The security rules** (director.md 10) bind Infra as everyone: its
  fixtures, never a machine's queue, are its tests' way into pueue.
