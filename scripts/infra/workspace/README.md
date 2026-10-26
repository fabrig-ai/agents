# The workspace's operations

For the user and the director, not for agents at work: `AGENTS.md`
beside this file is what every agent reads.

## A new machine

Clone agents, skein, smith, jig, hearth, temper and qa from
`git@github.com:fabrig-ai/` into `~/src/rust/`, then run
`agents/scripts/infra/setup --fix`. Setup with `--fix` clones any of those
repositories that are missing. It links the tools (`heavy`, `land`,
`land-set`, `landings`, `repin`, `record`, `setup`, `post`, `codex-run`)
into `~/.local/bin`, and
`AGENTS.md`, `CLAUDE.md` and the Claude Code settings
(`.claude/settings.json`) into the workspace, all to the agents checkout:
a change to them reaches the machine as that checkout moves. It clones
records, sets up the queue, and names what is still missing (pueue,
kache, jq, python3, systemd-run, cargo-nextest, heavy's reconciler, and
cargo's `[net] git-fetch-with-cli = true` in `~/.cargo/config.toml`).

## Work

Work goes through the roles in agents' `roles/README.md`: director,
designers where needed, owners, implementers. Their notes are in
`tmp/owners/<name>/`, and the director's in `tmp/director/`.
