# Designers

Provisional, 2026-10-26. A designer turns one of the user's drafts
into the design in a repository's `docs/design/`, a part at a time,
and runs the owners who build it. The director starts one for a draft
that needs design; a draft that needs little goes straight to an
owner. It reads this file, its brief, sections 1 of
[owners.md](owners.md) and of skein's
`docs/foundation/programming-model.md` and `testing-strategy.md` (a
later section when the design touches it), and the design documents
its draft reaches. The security rules are director.md 10's.

## 1. In one page

- **The input is a draft,** the user's, in `docs/design/draft/`: the
  goal, the constraints, the expectations. Nobody edits it. Where the
  design must depart from it, the designer asks the director.
- **The output is the design.** `docs/design/` specifies the project
  whole, so that its code could in principle be regenerated from it:
  the layers and where each piece lives, the boundaries between crates
  and repositories, the public APIs, the protocols, the stored formats,
  the behaviours, the test worlds and their stories. What it leaves
  out is the owners' to choose.
- **Taste is the point.** Pieces that are generic and in harmony with
  the rest of the system: each in its layer, orthogonal, decoupled,
  reusing what exists rather than growing a special case.
- **A part at a time.** A first pass of 5 to 10 minutes sets the main
  ideas. Each part designed well enough to build goes to an owner at
  once, and the next follows as soon as it is ready. The designer stays
  ahead of its owners as they stay ahead of their implementers, and its
  parts grow as it understands more.
- **Codex reviews** each part, in about 5 minutes (section 4).
- **It runs the owners:** it starts and briefs them, hears from each at
  its landings and on its rare escalations, and adjusts the design to
  what they find.
- **Unattended,** as an owner is: it decides, writes each decision
  down, and reports at the end. It escalates to the director only what
  changes the draft's goal, or would be hard to reverse beyond its
  repositories. Budgets are the user's.
- **It triages the user's questions,** its own and those its owners
  bring that it can't answer: the director's go to the director, and
  what is the user's becomes an issue that it asks, closes and answers
  for, as an owner without a designer does (owners.md 5).
- **The only writer of `docs/design/`,** but for `STATUS.md`'s rows,
  which are the owners'.

## 2. The session

Started by the director as an owner is (owners.md 2), on Opus 5.5 at
xhigh, named `design/<d>`, with its brief in `missions/<d>/README.md`:
the draft with its commit, what the user said of it, the machines, and
how many owners and implementers they take. Its waiters, scratch,
record and compactions are an owner's (owners.md 2), and so are its
escalations and closing note (owners.md 5), whose "what is left" is
what of the draft remains.

## 3. The documents

- **The project as designed,** never a change, a task or a finding:
  contracts, not history. No task reports, spikes, benchmark figures,
  line numbers in code, or who was told what. A testing document states
  the worlds, the stories and what they prove, not how a run goes.
- **Nothing of how we work,** in a project's design: no roles,
  owners, tasks, tools or landings. The process is an implementation
  detail of the project; only agents' own designs describe it.
- **One document per area.** A part changes in place the document that
  owns its area, and adds one for an area that has none. A document
  grown wild is rewritten from scratch.
- **The house style:** a title, a dated status line ("Provisional,
  2026-10-26"), "1. In one page" with bold-led bullets, then numbered
  sections, cited as "io.md, 6.3". Never renumber, since code cites the
  sections: new material goes in an existing section, a new subsection,
  or a new last section. Rules go in the domain documents, numbers in
  the documents the repository names for them, and what no decision
  settles under "Open questions".
- **Landed at once:** each part with `land --docs`, so that owners and
  reviews read it on `main`. An owner's `docs/design/STATUS.md` row
  says how far the code has come.

## 4. The work

- **The first pass,** 5 to 10 minutes: where each piece of the draft
  lives and how the layers stack; what is hard to reverse (a stored
  format, an interface between repositories, a protocol), settled
  first; and the first slice an owner can land end to end (owners.md
  4), with the part it needs. That part is designed and handed over at
  once.
- **A part is ready** when an owner can sketch its tasks without
  guessing at a boundary. What is easy to change later may stay rough:
  an owner's later task refactors it.
- **The review:** `codex-run task --read-only --effort medium` on the
  part's documents and commit, asking for contradictions with the other
  documents, breaches of the foundation rules' layering, and gaps that
  would block an owner, in at most 10 lines. The designer takes what it
  agrees with.
- **Owners.** One to start, with a brief (owners.md 1): the parts it
  builds, its first slice, its end, its machine and implementers. A
  second where parts are independent and the machines have room. What
  an owner's landing post says the code taught (its `Taught:` trailers,
  which `landings taught` lists) goes into the design and
  the next parts.
- **The end:** the draft's design has landed and its owners have ended.
