# Agent guidance for ~/src/rust

This directory holds the Rust projects, each a git repository with its own
`AGENTS.md`, and the machine's working files in `tmp/`. Read a
repository's `AGENTS.md` before touching its code.

This file is agents' `scripts/infra/workspace/AGENTS.md`, linked into
`~/src/rust/`: change it there, and land it in agents. It holds only what
every agent here needs.

## The projects

| Repository | What it is | Builds on | Its gate |
|---|---|---|---|
| `agents` | the roles, the process's designs and the tools | — | `scripts/check.sh` |
| `skein` | the io and protocol kit, and the code's rules | — | `scripts/check.sh` |
| `smith` | the agent kit | skein | `scripts/check.sh` |
| `jig` | the kit for agentic applications | skein, smith | `scripts/check.sh` |
| `hearth` | the factory's build daemon | skein | `scripts/check.sh` |
| `temper` | the application | skein, smith, jig | `scripts/check.sh` |

Dependencies point upstream only: skein names neither smith nor temper,
smith never names temper, and jig never names temper.

On a machine that keeps its checkouts elsewhere (`~/src/` rather than
`~/src/rust/`), read that directory where this file says `~/src/rust`;
the tools find it by themselves.

## The code's rules

skein's `docs/foundation/programming-model.md` (how code is shaped) and
`testing-strategy.md` (how it is tested) are the rules for every
repository. Depart from them only with a reason, stated in the design or
the commit. Read each one's section 1, "In one page", first, and a
later section only when the work touches it. `notes.md` beside them
holds their reasons and open questions.

## Building and landing

- **Work on a branch in a worktree of your own,** never in a primary
  checkout.
- **A rebased branch is pushed under a new name;** never force-push.
- **Build and test through `heavy`:** `heavy cargo nextest run -p
  <crate>`. It queues every build on the machine, so that builds don't
  starve each other and gates run alone. What builds nothing (`cargo
  fmt`, `cargo tree`) runs directly. An implementer's loop is
  agents' `roles/implementer.md`.
- **`main` moves only through `land`,** which rebases, runs the
  repository's gate and pushes; `land --docs` for Markdown alone, and
  for the mockups under `docs/design/`, which need no tests or builds.
  Don't run the gate yourself before it.
