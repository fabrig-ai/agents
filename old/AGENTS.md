# agents: what an agent must know before touching it

agents holds how agents work on the workspace's repositories: their
roles (`roles/`, whose `README.md` gives the whole picture), the designs
of the process they follow (`docs/design/`, whose `STATUS.md` says what
is built) and its tools (`scripts/`). It names no product, and no
repository builds on it. The user's drafts go in `docs/design/draft/`.

- **Its code is scripts,** under the rules below, not skein's
  foundation rules. A change to a tool is felt on every machine as it
  lands: `~/.local/bin` links to the primary checkout. Its commit says
  what a machine must do after it lands (a `setup --fix`, a `heavy
  --gate -- kache-setup`).
- **Disk space is checked before work:** heavy checks the machine floor
  (40 GB, or `PLAN_MIN_DISK_GB` in `tmp/machine.env`, environment first)
  at submission and again before the payload starts. A landing refuses
  below it before its prebuild, and checks again for its gate.
- **The gate,** `scripts/check.sh`, runs the tools' fixtures. A change
  comes with its fixture, and a fixture never touches a machine's live
  queue, store or settings. A change to the roles or the designs alone
  lands with `land --docs`.
- **It stays small.** A new mechanism comes with the measurement that
  shows its need, and a change to a tool with an independent review of
  its failure paths (a Codex review), its migration and its rollback.
- **A running script is replaced, never edited:** bash reads a script
  as it runs. Write a sibling file, then rename it over the old one.
- **Settings reach every shell:** Claude Code's settings, login shells
  and systemd units alike. A setting only one of them sees fails the
  others' runs.
- **A change to the fleet** goes one quiet machine at a time: drained
  (no `land`, `heavy` or `after-landing` running), installed, set up
  through `heavy --gate`, checked, then admitted again.
