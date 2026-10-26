# Roles

Provisional, 2026-10-26. Who works on the workspace's repositories,
and what is still open. Each role's own file says how it works.

## 1. The roles

The chain is director → designers, where needed → owners →
implementers. Each answers to the one above it, by post
([post.md](../docs/design/post.md)).

- **The director** ([director.md](director.md)) holds the vision, the
  goals and the direction, beside every draft's state and the
  machines'. It starts a designer for a draft that needs design, and an
  owner for a mission that needs none. It keeps the machines, the spend
  and the security rules, and talks to the user.
- **A designer** ([designer.md](designer.md)) turns one draft into the
  design in `docs/design/`, a part at a time, and runs the owners who
  build it.
- **An owner** ([owners.md](owners.md)) takes one mission to `main`: it
  shapes the code and its tests, and implementers write them. It lands
  each slice that works end to end.
- **Implementers** ([implementer.md](implementer.md)) are Codex runs,
  each given a task file by its owner. They build and test narrowly
  while they work, and widen, lint and format once, when the task's
  changes are done.

Designers and owners are Claude Code sessions on Opus 5.5 at xhigh.
Claude is for taste; everything else goes to Codex.

## 2. Open questions

- **Testing what landed in the lab:** who starts a QA run, and who
  judges its findings, now that QA has no role of its own. For now, the
  director.
- **The resource watcher:** a tool that wakes an owner when CPU, memory
  or disk need it (owners.md 2), to be built.
- **temper's drafts that read our roles:** `draft/configuring.md` and
  `draft/temper-on-temper.md` describe how we worked before 10-26:
  product owners, departments and milestones.
- **The director's tools** left `tmp/director/` on 10-25 with every
  script there ([cleanup.md](../docs/design/cleanup.md) 2). Which come
  back as tools in `scripts/` is open (director.md 12).
