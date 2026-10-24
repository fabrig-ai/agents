# agents: what an agent must know before touching it

agents holds how agents work on the workspace's repositories: their
roles, the designs of the process they follow, and its tools. It names
no product, and no repository builds on it. The rules for the code
itself are skein's: `docs/foundation/programming-model.md` and
`testing-strategy.md`.

## Where things are

- **The roles:** `roles/`, whose `README.md` gives the whole picture
  and the departments. `director.md` (the session that coordinates the
  rest), `product.md` (the product owners, in charge of features),
  `owners.md` (how an owner takes a mission to `main`) with the
  departments' files `app.md`, `ui.md` and `infra.md`, `qa.md` with
  `qa-milestone.md` and `qa-lab.md` (the QA agents), and `keeper.md`
  (the session that judges the landing queue's failures).
- **The designs:** `docs/design/`. `landing-flow.md` (how changes reach
  `main` across the repositories), `build-cache.md` (kache and the
  shared store), `build-infrastructure.md` (`heavy`, `land`, `repin`,
  `land-set` and the recovery kit), `gate-policy.md` (the gate's
  runtime identity). `STATUS.md` says what is built. The user's drafts
  go in `docs/design/draft/`.
- **The tools:** `scripts/devel/` for building and landing (`heavy`,
  `land`, `land-set`, `repin`, `after-landing`, the recovery kit
  `recovery-v1/`); `scripts/infra/` for setting up a machine (`setup`,
  `kache-setup`) and the workspace files that `setup` links into
  `~/src/rust/` (`workspace/`).

## The gate

- `scripts/check.sh` runs the tools' own tests. `land` runs it; do not
  run it yourself before `land`. `land --docs` lands Markdown alone.
- A change to a tool is felt on every machine at once: `~/.local/bin`
  links to the primary checkout. Say in the commit what a machine must
  do after it lands (a `setup --fix`, a `heavy --gate -- kache-setup`).
