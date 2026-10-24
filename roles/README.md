# Roles

Provisional, 2026-10-24. Who works on the workspace's repositories, how
the work is divided among them, and what is still open. Each role's own
file says how it works.

## 1. The roles

- **The director** ([director.md](director.md)) holds the vision, the
  goals and the direction, beside every product's state and the
  machines'. It coordinates the product owners and breaks their ties,
  keeps the machines, the spend and the security rules, runs Infra's
  missions, and talks to the user.
- **A product owner** ([product.md](product.md)) is in charge of one or
  more features, a draft each (temper's `draft/configuring.md`, say),
  across the departments. It cuts them into missions, starts their
  owners, checks their plans and designs, decides when the lab tests
  what landed, and judges findings once their owners have ended.
- **An owner** ([owners.md](owners.md)) takes one mission to `main`, in
  milestones, through implementers. Each belongs to a department, whose
  file adds its scope, its model, what it reads and its own rules.
- **A QA agent** ([qa.md](qa.md)) tests what has landed and reports to
  whoever started it. It never judges its findings, and never reads the
  code under test. In a milestone, [qa-milestone.md](qa-milestone.md);
  in the lab, [qa-lab.md](qa-lab.md).
- **The keeper** ([keeper.md](keeper.md)) judges the landing queue's
  failures, once the queue is built.
- **Implementers** ([implementer.md](implementer.md)) are Codex runs,
  each given a task file by its owner (owners.md 4.2 and 4.3). They
  build and test narrowly while they work, and widen, lint and format
  once, when a set of changes is done.

## 2. The departments

They help to schedule and divide the work (what runs beside what, what
waits on what), and keep each kind of work's rules in one file. A
mission belongs to one department; a feature that needs several gets a
mission in each.

| Department | File | What it owns | Who | Reads |
|---|---|---|---|---|
| App | [app.md](app.md) | everything that is not a page or a view: skein's kits, smith, jig, hearth, temper's domain, services, stores and protocols, and the CLI, `temper ctl` | Claude owners; Codex where little taste is needed | owners.md, app.md, the two foundation rules |
| UI | [ui.md](ui.md) | the pages and their views: the browser's, the terminal's, later a phone's; skein's UI kit, the web shells and bundles, the look | Claude owners | owners.md, ui.md, the two foundation rules |
| Infra | [infra.md](infra.md) | the machines and the tools: `heavy`, `land`, `land-set`, `repin`, the build cache, `setup`, the landing queue | Codex owners, under the director | owners.md, infra.md |
| QA | [qa.md](qa.md) | testing what has landed: passes in a milestone, runs in the lab | Codex agents | qa.md, and qa-milestone.md or qa-lab.md |

The foundation rules are skein's `docs/foundation/programming-model.md`
and `testing-strategy.md`. A Codex owner or agent takes its taste from
an Opus 5.5 one-shot, and brings its public decisions to its parent.

## 3. How a feature goes

1. **The user drafts it,** and the director gives it to a product owner.
2. **App starts at once,** with the upstream work it needs. App's part
   is done when the feature works through `temper ctl`, shown by
   stories that drive it there.
3. **QA follows the landings,** happy path first. A milestone may have
   passes, its owner's call; what lands may have a lab run, the product
   owner's call, who may judge that a milestone needs none. Findings go
   to the owner of the work, or to the product owner once that owner
   has ended. On v0.1.0's happy path, a finding is fixed now; anything
   else goes to the product owner's backlog, for later.
4. **The user draws the mockups,** during App's work or after it, as
   the pages' design. What App hasn't landed yet is drawn under View →
   Future, marked with what it needs. UI never draws one.
5. **UI builds the pages and views** from the mockups. While App is at
   work, it builds what App's landings allow and defers the rest; once
   App is done, it takes them to completion. A small change in App's
   land that a page needs (its words, an easy fact), UI makes itself,
   with the tests that read it. A gap in a mockup gets a cheap stand-in
   and a flag for the user.

## 4. Open questions

- **How product questions reach the user:** a UI owner's flag on a
  mockup, a feature's scope. For now only the director talks to the
  user (director.md 8), and product owners bring such questions to it.
  The user has ideas, for a second pass.
- **Placement:** product owners start their owners on the machines the
  director allots them. Placement of their own is for a second pass.
- **The terminal** (`temper open`) is UI's, and is not touched for now
  (the user, 10-24). When it opens again is open.
- **The landing flow's go-live** changes owners.md 3.1 and 4.2 to 4.6,
  and director.md (landing-flow.md 8). Until then, landing-flow.md 9.1
  says how sets land.
- **temper's drafts that read our roles:** `draft/configuring.md` and
  `draft/temper-on-temper.md` take owners.md and director.md as the
  description of how we work, and that description is now these files.
- **The director's scripts** live untracked in `tmp/director/`
  (director.md 12).
