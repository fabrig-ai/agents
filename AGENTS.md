# agents: what an agent must know before touching it

agents holds how agents work on the workspace's repositories: their
roles (`roles/`, whose `README.md` gives the whole picture), the designs
of the process they follow (`docs/design/`, whose `STATUS.md` says what
is built) and its tools (`scripts/`). It names no product, and no
repository builds on it. The user's drafts go in `docs/design/draft/`.

- **Its code is scripts,** under `roles/infra.md`, section 2, not
  skein's foundation rules. A change to a tool is felt on every machine
  as it lands: `~/.local/bin` links to the primary checkout.
- **The gate,** `scripts/check.sh`, runs the tools' fixtures. A change
  to the roles or the designs alone lands with `land --docs`.
