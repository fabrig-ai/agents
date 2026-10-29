# What waits on the user

Provisional, 2026-10-26, with the user. How a question or an action
that only the user can take reaches them, and how their answer comes
back:
- whoever needs the user opens an issue on the forge, with `issue`;
- the user answers in a comment there;
- a router on the forge's machine posts the answer to whoever asked;
- the asker closes the issue.

It replaces the director's relaying: its list of waits,
`director/waiting.md` ([records.md](records.md) 3), and the answers it
carried back to each owner.

## 1. In one page

- **Why.** Every wait went through the director: it wrote the item,
  pushed the user, read the answer and posted it on. "To reduce
  relaying" (the user, 10-26), a wait now lives where the user reads
  it, with its detail, and the answer goes straight back to the asker.
- **One issue per wait,** labelled `waiting-on-user`, in the repository
  it concerns on the forge, https://git.fabrig.ai: `fabrig-ai/agents`
  or `qa`, private, or `skein`, `smith`, `jig`, `hearth` or `temper`,
  public mirrors of GitHub's, whose issues anyone reads (section 2).
  The open issues so labelled are what waits on the user.
- **Who opens one:** a designer, an owner without a designer, or the
  director, once it has triaged a question as the user's (section 5).
  `issue open` writes, after the body, a marker naming the mission
  that asks, or the director (section 2.2).
- **The user answers in a comment.** Forgejo's webhook reaches the
  router on hel8, which finds the mission's owner in the records and
  posts it the comment's first lines and its link. When post says
  nobody will wake the owner, the reply goes to its parent, then to the
  director, as a safety net (section 4).
- **The asker closes the issue,** always: once the answer is acted on,
  or when the question no longer stands, even with nothing to do.
- **The director is not told** of new issues, for now (the user,
  10-26). The status page shows a link to the open labelled issues, and
  their count, where it showed the waits, and how many missions are
  blocked on them, from the record (section 5).
- **Nothing private reaches an issue:** a bot account whose token can
  only write issues; a tool that refuses a secret, a file from a
  private place, and in a public repository what names the fleet
  (section 3.3); a marker that names a mission alone; and a router
  that holds no token and routes the user's comments alone.

## 2. The issues

### 2.1 The forge

| Account | Who | Its token |
|---|---|---|
| `fabrig-agents` | the agents, through `issue`; a write collaborator of the seven repositories | `agents-issues.token`: `write:issue` and `read:repository`; `status-read.token`: `read:issue` and `read:repository`, the status page's |
| `fabrig-director` | the director; a site admin | `director.token`, on hel8 alone: it makes the webhooks |
| `free` | the user | none of the agents' |

The repositories are the workspace's seven, under `fabrig-ai/`, each
with the label: `agents` and `qa` private, with issues alone and no
sync with GitHub; `skein`, `smith`, `jig`, `hearth` and `temper`
public pull mirrors. Forgejo 17 runs on hel8, behind Caddy, as temper's
live deployment's forge. The agents only call its API (`/api/v1`) and
receive its webhooks: nothing of temper's deployment changes for them.

### 2.2 An issue

- **Its repository** is the one the wait concerns: by default the
  mission's, the first word of its README's `feature:`
  ([records.md](records.md) 3), and `agents` for the director or a
  mission whose feature names none of the seven.
- **Its title** says what the user decides or does, in one line of at
  most 200 characters, read in a list.
- **Its body** is the asker's: the question with its options and the
  recommendation first, so that "yes" answers it; the context the user
  needs, and links. In a private repository the detail goes here, not
  in a decision for the user to look up. In a public one, the text is
  written for anyone: no path, no machine, no address, no budget
  (section 3.3).
- **The footer** follows, for the user and for the router:

  ```
  ---
  Asked for the mission `user-issues`. Your comment here reaches it by post, and it closes the issue.
  <!-- waiting-on-user mission=user-issues -->
  ```

  The last line is the marker, an HTML comment that the page hides,
  naming a mission (records.md 3's names), or `<!-- waiting-on-user
  director -->` for the director ("Asked by the director."). Mission
  names are public already, on the status page. The router reads the
  body's last line of that form, and only on an issue that
  `fabrig-agents` opened.
- **Comments.** Every comment by the user is routed to the asker, as
  many as there are. Nobody else's is: not the asker's own, written with
  `issue comment` (a follow-up question, what it did), nor the
  director's, nor a stranger's on a public repository.
- **The end:** the asker closes the issue with `issue close`, with a
  last comment when one helps (what was done). An issue the user
  closes is closed; its asker sees it gone from `issue list`.

## 3. The tool

`scripts/devel/issue`, Python, linked into `~/.local/bin` by `setup`.
The client's commands run on any machine; `serve` and `install` are the
router's (section 4), and read no token.

### 3.1 Its commands

An issue is named `REPO#NUMBER`, `temper#12`.

- **`issue open [--mission M] [--repo R] [--public] TITLE FILE`**
  opens an issue with the label, TITLE, FILE's text and the footer, and
  prints `REPO#NUMBER URL`, with `public` after it in a public
  repository. A public repository needs `--public`, the asker's word
  that the text is fit for anyone; without it, the tool refuses and
  says the issue would be public.
- **`issue list [--mission M] [--all]`** prints the asker's open
  issues across the seven repositories, one line each: the issue, its
  age, its asker, its title, its link. `--all` prints every open
  labelled issue, whoever asks.
- **`issue comment [--mission M] REPO#NUMBER FILE`** adds FILE as a
  comment.
- **`issue close [--mission M] REPO#NUMBER [FILE]`** adds FILE as a
  last comment, if given, and closes the issue. A closed issue stays
  closed: exit 0.
- **Who asks:** a mission, `--mission`, else what follows the first `/`
  of `POST_NAME` (`o/user-issues` asks for `user-issues`,
  `design/forge` for `forge`); `POST_NAME` `director` is the director.
  A parent acts for a gone owner with `--mission`.
- **Only the asker's own:** `comment` and `close` refuse an issue whose
  marker names another asker, or none.
- **Exits:** 0 done; 2 refused, with the reason (a bad argument, a
  secret, a public issue without `--public`, another's issue, no
  token); 1 the forge failed (unreachable, an HTTP error), with its
  status and message. Nothing is retried: the caller runs it again.

### 3.2 Its token

On every machine, `~/src/rust/tmp/git-fabrig/agents-issues.token`
(`~/src/tmp/...` where the workspace is `~/src`), mode 0600 in a 0700
directory: the place it has on hel8, where the director made it. The
director copies it to each machine (director.md 10), and the client's
commands refuse to run without it.

### 3.3 What may go in an issue

Checked on the title and on every FILE, before any request; a refusal
is exit 2 and names the rule, never the text:

- **Never, anywhere:** the text of any file in `tmp/git-fabrig/` (the
  tokens and the webhook's secret, which no pattern recognises); a
  secret by `record`'s patterns ([records.md](records.md) 2); a FILE
  whose real path, links resolved, lies in a private place (`~/.ssh`,
  `~/.gnupg`, `~/.config`, `~/.local`, `~/.codex`, `~/.claude` but for
  its sessions' `jobs/` scratch, `/proc`, `/run`, `/sys`, and the
  workspace's `tmp/git-fabrig/`, `tmp/heavy/` and `tmp/post/`); a FILE
  that isn't a regular file of at most 60 KiB in UTF-8, or that holds a
  marker of its own.
- **In a public repository, besides:** a path (one starting `/`, `~/`
  or naming the workspace's `tmp/`), a post address (`NAME@MACHINE`),
  the name or the SSH target of a machine in post's machines file, an
  IP address, and an email address. These rules are the tool's floor;
  what else stays private (budgets, the director's notes) is the
  asker's judgement, under the user's word in `direction.md`.
- **The token** goes only into the request's `Authorization` header,
  from the tool's own memory: never in an argv, an environment, a URL,
  a log or an output. A failure prints the forge's status and message,
  never a request's headers.

## 4. The router

- **`issue serve [--listen HOST:PORT] [--route LOGIN]`** is the
  router: an HTTP server on a loopback address, `127.0.0.1:8391` by
  default, that takes Forgejo's webhooks at `/hook`. It runs on hel8 as
  the user unit `issue-router.service`, which **`issue install
  [--listen HOST:PORT] [--route LOGIN]`** writes, enables and
  restarts, as `status-page install` does; a new version of the tool
  runs once the unit restarts.
- **The webhooks,** one per repository of the seven, are made by the
  director with its admin token: the URL `http://127.0.0.1:8391/hook`,
  JSON, the "Issue comments" events alone, and the secret in
  `~/src/rust/tmp/git-fabrig/webhook.secret`, 0600, which `issue
  install` makes when it is missing and never prints. Forgejo's
  `[webhook] ALLOWED_HOST_LIST` must allow 127.0.0.1; temper writes it
  so when its deployment has a webhooks' listener.
- **Checked:** each request's `X-Forgejo-Signature`, the HMAC-SHA256
  of its body under the secret (403 when it is wrong or missing), and
  its size, 1 MiB at most.
- **What routes:** a comment created on an issue, not a pull request,
  of one of the seven repositories, by the user (`free`), on an issue
  that `fabrig-agents` opened and whose body holds a marker. Anything
  else is answered 204 and logged with why. `--route LOGIN`, given to
  `serve` and `install`, routes another account's comments too, for a
  proof (section 6). An allow-list, not the bots left out: a public
  repository's stranger must never reach an agent as the user.
- **The asker** is found when the reply is sent, from the records'
  checkout on the router's machine: the mission's README's `owner:`
  and `parent:` addresses, after a `record pull` when the README isn't
  there yet. The director is `director` on the router's machine.
- **The spool,** `~/.local/state/issue-router/`: a reply is written to
  `new/<repository>-<comment id>.json` before Forgejo is answered,
  since Forgejo waits 5 seconds and a post may take minutes. A comment
  already in the spool is a redelivery, and posts nothing again. One
  worker sends each reply, oldest first, at once, every minute, and at
  start, so that a reply spooled before a restart still goes; then it
  moves to `done/` or `failed/`. Each recipient tried is written into
  the reply's file before the next, so a restart resumes the chain
  where it stopped.
- **The chain:** `post send --as issues` to the owner. Exit 0 is done.
  Exit 3 (nobody will wake it) or 2 (not delivered) sends to the next
  of its parent, then the director, each address once, with a first
  line naming the owner and post's answer. The chain ends in `done/`
  after an exit 3, since the message waits in a mailbox where stuck
  mail surfaces ([post.md](post.md) 4), and in `failed/` after an exit
  2. A mission with no README, or no owner in it, starts the chain at
  its parent, or the director. Any other failure is tried again at the
  next wake, five times at most, then `failed/`.
- **The post:** from `issues@hel8`, the subject `REPO#NUMBER <author>
  replied: <title>`, the body at most 15 lines: who commented, with the
  comment's link; its first 10 lines, each cut to 300 characters; how
  many more there are; and how to answer and close (`issue comment`,
  `issue close`). Its mailbox's `sent/` is the record of what was
  routed. Nobody reads its `new/`: the asker answers on the issue.

## 5. In the roles

- **Triage.** A question that would go up (owners.md 5) is either the
  director's to decide, or the user's: what director.md 8 keeps theirs
  (long-term consequences hard to change, the user's rules: budgets,
  sign-ins and credentials, subscriptions, more machines). A designer,
  and an owner without a designer, triage their own, and their owners'
  that they can't answer: the director's goes to the director by post,
  the user's becomes an issue. An owner with a designer asks its
  designer, as before.
- **The repository** is the one the question concerns, the mission's
  by default. In a public one, the asker writes for anyone, and keeps
  to a private repository what can't be said so.
- **The director** opens an issue for each of its own questions and
  actions for the user, and pushes the user only for one that can't
  wait, naming it. The open issues are the waits; `waiting.md` retires
  with its check in `record`.
- **The asker waits** on its waiter as for any post, keeps the issue
  in its `progress.md`, and closes it once it has acted. An answer that
  sets a rule beyond its mission goes to its parent, and on to the
  director's `direction.md` (director.md 8). A mission that closes with
  an issue still open names it in its closing note, and its parent
  closes it, or keeps it with `--mission`.
- **Blocked on the user:** a mission that can go no further without
  the user's answer names the issues it waits on in its README's
  front matter, `blocked: temper#9` ([records.md](records.md) 3), and
  removes the line as it goes on, the answer read or the question
  gone. An issue it can work beside blocks nothing: an issue is a
  question, and a mission is blocked only when nothing of its end is
  left to do without it. An owner with a designer names the issue its
  designer asked; a parent that parks a mission on the user, its
  session stopped, writes the line in its stead. The status page counts
  these missions beside the open issues, and lists each in Blocked on
  you with its issues and since when (status-page.md 3).

## 6. Going live

1. **The tool** lands with its fixture (`test-issue`: a fake Forgejo
   and a fake `post`), unused.
2. **The director** copies the token to each machine (section 3.2),
   runs `issue install` on hel8, and makes the webhooks (section 4).
3. **The proof:** one round trip on the real forge: an issue opened
   with `issue open`, a comment by `fabrig-director` standing in for
   the user, routed for the proof alone (`issue install --route
   fabrig-director`, then `issue install` again), the reply delivered
   by post, the issue closed by the asker.
4. **The roles' lines** land (section 5). The items of
   `director/waiting.md` become issues, each asked by the mission that
   waits, or the director when it has gone; the status page links to
   them; then the file and `record`'s check of it retire.

## 7. Left out, on purpose

- **The director's sight of new issues** (the user, 10-26: not for
  now).
- **Edits, closings and reopenings by the user** are not routed: a
  comment is the answer.
- **Mail from the forge, and a post turned into a comment:** the
  answer to the user goes on the issue.
- **Issues for anything but the user's waits,** and a sync with
  GitHub's issues.
- **Durability past a power loss,** as in post ([post.md](post.md) 9).

## 8. Open questions

- **New issues at the director's check:** a count, or a line each, if
  the user wants it later.
- **Whether a mission may close** with an issue of its own open.
- **What else is private** in a public repository's issue: the user's
  answer, through the director, sets section 3.3's second rule.
