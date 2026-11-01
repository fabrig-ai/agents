# smith-live: a shelf kind for smith's live root

agents/creds, 11-01, at the director's word (the user agreed that the `smith login` is a one-off
and should then live on the shelf).

smith's live tests (fabrig's `live-smith` tier) need `SMITH_LIVE`: a private root directory,
which `smith/tests/end-to-end/support/live.rs` checks:
- `config/smith/config.toml`;
- `host-id`;
- `tokens/chatgpt`, a ChatGPT record of smith's own, made by `smith login chatgpt`;
- `programs/claude`, a Claude Code directory.

after-landing took live-smith out on 11-01 (4daf0a0) because nothing could lend such a root. A
root now exists on hetzner9 at `~/.local/state/smith-live`, waiting for the user's
`smith login chatgpt`. Once it is signed in, agents/creds captures it onto the shelf.

The root's `config.toml` names the root by its absolute path
(`credentials = "/home/free/.local/state/smith-live"`), as smith's README sets it up. So a lent
root works only at that one path. The kind must therefore always be lent at
`~/.local/state/smith-live` on the host, never at a run's own path. Every builder has the same
user and HOME, so the absolute path stays right.

Wanted: a `smith-live` kind in `fab/logins.py`, a directory, lent only at its fixed path. Putting
live-smith back in `fab.after_landing.LIVE` is a later task, landed once the root is on the
shelf. Otherwise every after-landing run would fault the pair and stay partial.
