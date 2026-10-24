# The workspace's operations

For the user and the director, not for agents at work: `AGENTS.md`
beside this file is what every agent reads.

## A new machine

Clone agents, skein, smith, jig, hearth and temper from
`git@github.com:fabrig-ai/` into `~/src/rust/`, then run
the director-owned quiet release procedure in
`agents/docs/design/build-infrastructure.md`, section 7. The copied stable
`setup --fix` links the tools (`heavy`, `land`,
`setup`) from the stable kit and (`post`, `codex-run`) from
`agents/scripts/devel/` in the checkout into `~/.local/bin`, links the
workspace's `AGENTS.md` and `CLAUDE.md` to `agents/scripts/devel/recovery-v1/workspace/` in the checkout,
and keeps Claude Code settings (`.claude/settings.json`) linked to the
read-only kit. It sets up the queue, and names what is still missing
(pueue, kache, jq,
cargo-nextest, and cargo's `[net] git-fetch-with-cli = true` in
`~/.cargo/config.toml`).

## Work

Work goes through owners: agents' `roles/owners.md`. The director
starts them (`roles/director.md`); their notes are
in `tmp/owners/<name>/`, and the director's in `tmp/director/`.
