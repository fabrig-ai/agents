+++
id = "kind"
part = "smith-live-kind"
kind = "feature"
needs = []
files = ["fab/logins.py", "fab/tests/test_logins.py", "docs/design/machines.md", "docs/design/machines.status.md"]
effort = "medium"
minutes = 30
+++
# A `smith-live` kind, lent only at its fixed path

Read first: `docs/plan/smith-live/notes/common.md` and `docs/plan/smith-live/inputs/request.md`.

## What to build

- **`fab/logins.py`, `Kind`:** add a field `fixed: str = ""`. It is the one path, relative to
  HOME, where a login of this kind may be lent, because the login names its own path inside it.
  "" means any path, as now.
- **`KINDS`:** add `"smith-live": Kind("login", directory=True, fixed=".local/state/smith-live")`.
  Its comment says what it is: smith's live root (SMITH_LIVE), with `config/smith/config.toml`
  (which names the root absolutely), `host-id`, `tokens/chatgpt` signed in by `smith login
  chatgpt`, and `programs/claude`.
- **`Shelf._lend`** (it serves `lend` and `borrow`): for a kind with `fixed`, the path defaults
  to `fixed`. A different path is refused with
  `Refused("a <kind> login is lent only at ~/<fixed>: its files name that path")` before
  anything is copied. A path equal to `fixed`, or to `~/<fixed>` (the absolute form on the host,
  `$HOME/<fixed>`), is accepted.
  - The borrow CLI's `--path` stays required for other kinds. For a fixed kind it may be omitted:
    make `--path` optional in the `borrow` subparser, and refuse a missing path for kinds without
    `fixed`, saying `name its --path`, as `_lend` already does for run kinds.
- **`capture`:** unchanged. It takes `--path` and `--free` as for any kind.
- **`check`:** a `smith-live` login is refused as for `chatgpt` ("has no check; its runs show
  whether it works").
- **`docs/design/machines.md`, section 3:**
  - add `smith-live` to the kinds bullet, in the same style as `github`;
  - add one sentence on `fixed`: a kind whose files name their own path is lent only there, so
    one root serves one run at a time on any builder.
- **`docs/design/machines.status.md`:** one line saying the kind exists and that live-smith's
  return to `fab.after_landing.LIVE` waits for the root's capture.

## Acceptance

- Tests in `fab/tests/test_logins.py`, with the existing fake hosts:
  - capture a dummy smith root directory `--free`;
  - borrow it with no path: it lands at `~/.local/state/smith-live`, mode 0700, and the return
    removes it;
  - a lend or borrow at another path is refused, and nothing is created there;
  - `check` refuses it;
  - the borrow CLI accepts a missing `--path` for `smith-live` and refuses it for `chatgpt`.
- `bin/fab test` is green within its budget; `bin/fab status docs/plan/smith-live` shows no plan
  problems.

## Pre-approved defaults

- The refusal's exact wording may differ if it names the kind and the fixed path.
- `fixed` may be checked in `_push` instead of `_lend`, if that reads better.

## Report

Show the `Kind` and `KINDS` lines as built, the refusal text, and the tests added.
