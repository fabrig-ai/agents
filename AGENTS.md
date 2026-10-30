# Repository rules

- Python 3.13 standard library only (`tomllib` for TOML), plus minimal bash.
- Every tool has tests using a temporary HOME and fake services; never test
  against live machine state. Run Python with `-B` so tests leave no caches.
- Write files to a sibling and rename over the destination. Replace running
  scripts; never edit them in place.
- Nothing secret belongs in this repository. Never read credentials.
- `old/` is reference only: never modify it or depend on it.
- `tools/check.sh` is the gate. Main moves only through `tools/land` after the
  gate passes. A commit requiring machine action must say what action is needed.
- Every machine gives passwordless sudo; use it where a task truly needs root, never to get round a rule (heavy's units and state, another's checkout, credentials and keys).
- The design is the contract: `docs/design/`, cited by repository-root path and
  section. Code must be rebuildable from it at a high level. Every design has a
  Later section and an adjacent `.status.md` file; its designer keeps both.
- `docs/design/draft/` is the user's input. Agents read it and never edit it.
- A change that alters a design changes its document and status file in the
  same branch.
