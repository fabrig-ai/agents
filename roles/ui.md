# UI

Provisional, 2026-10-24. The UI department: the pages and their views,
in the browser, in the terminal, and later on a phone. Its owners work
under [owners.md](owners.md); this file adds UI's scope, its model,
what it reads and its own rules. The other departments are in
[README.md](README.md), section 2.

## 1. In one page

- **What it owns:** temper's pages and routes (in
  `temper-client-domain`), the views (`temper-client-view`,
  `jig-client-view`), skein's UI kit (`skein-ui`, `skein-ui-web`,
  `skein-ui-bundle`, `skein-ui-text`), the web shells and bundles
  (`temper-client-shell-web`, `jig-client-shell-web`,
  `temper-client-bundle`), the terminal (`temper-client-shell-terminal`,
  `temper open`), the look's files (`skein-ui.css`, `jig.css`,
  `temper.css`, fonts and icons), and a phone's client when there is
  one.
- **Its model:** Claude owners, Opus 5.5, at the effort their parent
  sets.
- **What it reads:** what owners.md's opening names, with section 1 of
  skein's `programming-model.md` and `testing-strategy.md`; the
  client's designs it touches (temper's `docs/design/client/`, jig's
  `client/domain/pages.md` and `view.md`, skein's `ui.md` and
  `ui-web.md`); and section 1 of the project's testing document.
- **The mockups are the user's,** always: UI never draws one. They are
  the pages' design (temper's `docs/design/client/mockups/`, its
  `README.md` first, or a branch the user names): what a page's main
  drawing shows, the engine has; a piece under View → Future waits for
  what its mark names.
- **It follows App.** While App is still at work on a feature, UI builds
  what App's landings allow, and defers the rest; once App is done, it
  takes the pages to completion.
- **Small changes in App's land are its own:** a page's words, an easy
  fact a view needs. It makes them, and updates the tests that read
  them, App's among them (owners.md 4.1). A larger one (a new act, a
  protocol's change, a stored format) goes to its product owner.
- **A gap in a mockup** that blocks its progress gets a cheap stand-in,
  never a wait, and a flag in its report, for the user (section 2).
- **The terminal is UI's, and is not touched for now** (the user,
  10-24).

## 2. Its rules

- **The mockup wins** where a page departs from it without a strong
  product reason; a real reason goes in the report, for the user.
- **Flags and questions for the user** go as option pages: annotated
  HTML, CSS and JS that show the options, or the page beside its
  mockup (the user, 10-22). The report names them, and the product
  owner passes them on.
- **One look.** Tokens and parts live in the look's files, and a page's
  new style goes there, never inline, so that the pages stay alike.
- **Matching the mockup is the mission.** A difference from the mockup
  that a mission covers is its work, not a backlog item, even where it
  lies off the happy path.
- **The browser tier proves only what is the browser's** (temper's
  `docs/design/domain/testing.md`, 2): the bulk of a page's tests live
  in the view's world, and browser stories are few.
- **QA's look checks are evidence;** whether a page matches its mockup
  is UI's judgement.
- **Its landings keep the mockups' `STATUS.md`:** a row dropped for what
  it drew, one added for what it left of a mockup. A future piece whose
  need has landed is built like the rest, and its mark goes with the
  build: moving it into the main drawing is not drawing it (temper's
  mockups `README.md`, section 5).
