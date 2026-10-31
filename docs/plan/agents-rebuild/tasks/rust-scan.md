+++
id = "rust-scan"
part = "rust-gates"
kind = "feature"
needs = []
files = ["fab/rust.py", "fab/tests/test_rust.py", "fab/tests/rust_sources.py"]
effort = "high"
minutes = 60
+++
# Rust read without a compiler: tokens, public items, functions, test spans

Fill every body of `fab/rust.py` as its docstrings and its module
docstring's Tokens and Item lists rules say: `tokens`, `spaced`, `scan`,
`items`, `functions` and `masked`. This is what fabrig's gates read in
place of Python's ast; `fab/rust_digest.py` (task `rust-digest`) builds the
digest from it. Design: `docs/design/fab.md`, section 12, the bullet on
fabrig's branches.

## Acceptance

- `fab/tests/test_rust.py`, a `RustTestCase` from
  `fab.tests.rust_sources` (sources written with `rs`, `long_fn` and
  `block`), no git, no files:
  - `tokens`: an ident, a raw ident, `::` and `->`, `>>` as two `>`, a
    lifetime against a char literal (`'a` and `'a'`, `'\n'`, `'\u{1F600}'`,
    `b'x'`), a string with an escaped quote, a raw string `r#"a "b" c"#`, a
    byte string, `0..n` as three tokens, a nested block comment dropped,
    `///` and `/** */` as docs and `////`, `//!` dropped, each token's line
    across a multi-line string; an unterminated string and an unterminated
    block comment raise SyntaxError at their first line.
  - `spaced`: the docstring's example exactly; `Result<(), Error>`,
    `[u8; 4]`, `*const T`, `T: ?Sized + 'static`, `fn(u8) -> u8`, and the
    same signature spread over lines as rustfmt writes it giving the same
    text.
  - `scan` items (`assertItems`): a `pub fn` with `const`, `async`,
    `unsafe` and `extern "C"`; `pub(crate) fn` and a private fn absent; a
    `pub struct` with a where clause, a tuple struct with its parens, a unit
    struct; `pub enum`, `pub union`, `pub type`, `pub const` (text without
    its value) and `pub static mut`; an inherent impl's `pub fn` as
    `Type.name` from `impl<T> path::Type<T>`; a trait impl's methods absent;
    a `pub trait`'s methods with and without default bodies, a private
    trait's absent; an inline `pub mod wire { pub fn encode() }` as
    `wire.encode`; `mod x;`, `use`, `pub use` and an item-level macro call
    (`thread_local! { }`, `foo!(...);`) skipped; docs from `///` (first
    non-blank line), from `/** */` and from `#[doc = "..."]`; attributes
    before and between docs.
  - `scan` functions (`assertFunctions`): a free fn, an impl method, a
    trait default method, a fn with attributes and docs (start the `pub`
    line), a nested fn not listed; `long_fn(name, 61)` is 61 lines.
  - `scan` tests (`assertTests`): `#[cfg(test)] mod tests { }` as one span
    from the attribute's line, a `#[test]` fn and a `#[tokio::test]` fn
    outside it, none of them in items or functions.
  - unreadable (`assertUnreadable`): an unclosed `{` (its line), a stray
    `}`, the text ending inside a signature.
  - `masked`: line numbers kept; `use`, `pub use`, `pub(crate) use`,
    `mod x;`, `// comment`, `}`, `});` blanked; `let x = 1;` and a `pub fn`
    line kept; every line of a test span blanked; the trailing newline
    kept.
- `bin/fab test` passes; `test_rust.py` takes under a second.

## Options, settled up front

- One pass over the text by index for `tokens`; the item lists read over a
  cursor into the token list (a small private class or functions taking an
  index), recursing for `mod`, `impl` and `trait` blocks. `re` is allowed
  for identifiers and numbers; no third-party parser.
- Every function, docstring included, stays within 60 lines (the `size`
  gate): `tokens` and `scan` dispatch to private helpers, one per token
  kind and one per item keyword.
- A token's kind is one of KINDS; puncts keep their text, docs their
  content, so `spaced` and the attribute checks read texts alone.
- Add builders to `fab/tests/rust_sources.py` rather than beside a test;
  change none it already has.
