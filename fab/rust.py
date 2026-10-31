"""Rust source read without a compiler: the public items, the functions and the test-only
spans of one file (docs/design/fab.md, 12).

fabrig's gates read this the way the Python gates read ast. It is a tokenizer and a
recursive scan of item lists, standard library only: nothing is built, nothing is resolved.
An item is public when it is declared `pub` (not `pub(crate)` or any other restricted
form), wherever its module sits; re-exports are not followed. Fields, enum variants and a
trait's associated types and consts are not items: a struct's text is its header, as a
Python class's is `class Name`. What the scan cannot read (an unbalanced delimiter, an
unterminated string or comment) is a SyntaxError(message, (module, line, 1, None)), so
fab.gates.screen turns it into a `gate:parse` finding as it does Python's.

Tokens (`tokens`). Whitespace and comments are dropped, except doc comments:
- `///` (not `////`) to the line's end is a doc token, its text the rest of the line with one
  leading space removed when present. `/** ... */` (not `/**/` or `/***`) is a doc token, its
  text the content with each line's leading spaces and one `*` removed, lines joined by "\\n".
  `//!` and `/*! */` (inner docs) are dropped. Block comments nest.
- Identifiers `[A-Za-z_][A-Za-z0-9_]*` and raw identifiers `r#name` (text `r#name`) are
  ident tokens; keywords are idents too.
- Literals: strings `"..."` with backslash escapes, raw strings `r"..."` and `r#"..."#` (any
  number of #), each with an optional `b` or `c` prefix; chars `'x'`, `'\\n'`, `'\\u{..}'` and
  byte chars `b'x'`; numbers: a digit then letters, digits and `_`, and a `.` only when a
  digit follows it (so `0..n` is 0, `..`, n). A literal may span lines; its line is where it
  starts.
- A `'` that does not open a char literal opens a lifetime or label: `'` and the identifier
  after it, one lifetime token (`'a`, `'static`).
- Puncts: PUNCTS when they stand at that point, else one character each (so `>>` is two `>`,
  and `Vec<Vec<u8>>` closes cleanly).
An unterminated string, char or block comment is unreadable at the line it starts on.

Item lists (`scan`): the file, an inline `mod name { }`, an `impl` block and a `trait` block.
Before an item stand its outer attributes `#[...]` and doc tokens, in any order; inner
attributes `#![...]` are skipped. An item's doc is the first non-blank line of its doc
tokens' texts joined by "\\n", stripped, or the content of the string literal of a
`#[doc = "..."]` attribute when that comes first; "" without one. The item proper starts at
the first token after them (its visibility, a qualifier or its keyword): a function's start.
- Visibility: `pub` alone is public; `pub(...)` (crate, super, self, in path) and none are not.
- `fn`, after any of `const`, `async`, `unsafe`, `extern` with an optional ABI string: its
  text is the tokens from the item's start up to the first `{` or `;` at paren and bracket
  depth 0. With `{`, the body is the balanced group; it is skipped, not scanned, so functions
  nested in a body are not listed.
- `struct`, `enum`, `union`, `trait`: text the tokens from the start up to the first `{` or
  `;` at paren and bracket depth 0 (a tuple struct keeps its parens: `pub struct Id(pub
  u64)`). A struct's, enum's or union's braced body is skipped; a trait's is an item list
  whose `fn`s are its methods.
- `type`: text up to the `;` (`pub type Map = BTreeMap<String, u64>`). `const` (not before
  `fn`) and `static`: text up to the `=` at depth 0 (`pub const CAP: usize`), then skipped to
  the `;`.
- `mod name;`, `use` and `extern crate`: skipped to the `;`. `mod name { }`: an item list
  whose names are qualified by `name.`.
- `impl`, after an optional `unsafe`: its generics `<...>` skipped; when a `for` stands at
  angle depth 0 before the `{` (not one followed by `<`, a higher-ranked bound), the block is
  a trait impl and its type is what follows the `for`; otherwise its type is what follows
  the generics. The type's name is the last ident before the type's first `<` at depth 0 or
  its end (`impl<T> store::Map<T>` is `Map`), or the type's spaced text when it has no ident
  (`[T]`). Its `where` clause is skipped. The block is an item list whose names are
  qualified by `<type name>.`.
- `macro_rules!` and an item-level macro call `path!`: its delimited group skipped, then a
  `;` when one follows. Anything else: skipped to the next `;` at depth 0 or past the next
  balanced `{ }` group, whichever comes first.
Unbalanced delimiters, or the text ending inside an item, are unreadable at the opening
delimiter's line or the item's start.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from fab.calls import Signature
from fab.digest import Function

KINDS = ("ident", "lifetime", "literal", "punct", "doc")  # Token.kind
PUNCTS = ("..=", "...", "::", "->", "=>", "..")  # multi-character puncts, longest first
NO_SPACE_BEFORE = frozenset({",", ";", ":", ")", "]", ">", "::"})
NO_SPACE_AFTER = frozenset({"(", "[", "<", "&", "::", "?", "*", "#"})
CALLS = frozenset({"(", "<"})  # no space before either when it follows an ident or ">"
TEST_ATTRIBUTES = ("cfg(test)", "test")  # an item with one of these (or `<path>::test`) is test-only
BRACKETS = frozenset("{}()[];,")  # a line of only these says nothing; clones skip it


@dataclass(frozen=True)
class Token:
    kind: str  # one of KINDS
    text: str  # as written; a doc token's text is the comment's content (see tokens)
    line: int  # 1-based line of its first character


@dataclass(frozen=True)
class Source:
    """One file's scan, every tuple in source order."""

    items: tuple[Signature, ...]  # the public items
    functions: tuple[Function, ...]  # every function with a body, public or not
    tests: tuple[tuple[int, int], ...]  # test-only items: (first line, last line), 1-based


def tokens(module: str, text: str) -> list[Token]:
    """text as tokens, in order, by the module docstring's Tokens rules; module names the file
    in a SyntaxError. Pure."""
    raise NotImplementedError


def spaced(words: Sequence[Token]) -> str:
    """The tokens' texts as one line, the form item texts are compared in, so that a reflow
    by rustfmt changes nothing: joined by one space, except no space before a text in
    NO_SPACE_BEFORE, none after one in NO_SPACE_AFTER, and none before a text in CALLS when
    the previous token is an ident or `>`. `pub fn get < 'a > ( & self , key : & 'a str ) ->
    Option < & 'a [ u8 ] >` gives `pub fn get<'a>(&self, key: &'a str) -> Option<&'a [u8]>`.
    Doc tokens are never passed. Pure."""
    raise NotImplementedError


def scan(module: str, text: str) -> Source:
    """The public items, functions and test-only spans of one Rust file at module (its
    repository-relative path), from tokens(module, text) read as the module docstring's item
    lists say. Pure.

    Items: a public free function, struct, enum, union, trait, type, const or static, named by
    its identifier qualified by enclosing inline modules (`wire.encode`); a public method of an
    inherent impl (`Map.get`, text from its `pub`); every method of a public trait
    (`Store.put`, text from its `fn`, public because the trait is). Methods of trait impls and
    items of non-public traits are not items. Each is Signature(module, name, spaced(its text
    tokens), doc).

    Functions: every `fn` with a body in an item list, public or not, methods and trait
    default methods too: Function(module, qualified name, start line, closing `}` line - start
    + 1).

    Tests: an item with an outer attribute whose content (the tokens between `#[` and `]`,
    spaced) is one of TEST_ATTRIBUTES, or whose path before any `(` ends `::test`
    (`#[tokio::test]`, `#[tokio::test(flavor = "current_thread")]`), is test-only: it gives no
    items and no functions, and its span runs from its first attribute's line to its last
    token's line. A `#[cfg(test)] mod tests { }` is one span."""
    raise NotImplementedError


def items(module: str, text: str) -> list[Signature]:
    """scan(module, text).items as a list."""
    raise NotImplementedError


def functions(module: str, text: str) -> list[Function]:
    """scan(module, text).functions as a list: what fab.digest.long_functions takes as find."""
    raise NotImplementedError


def masked(text: str, tests: Sequence[tuple[int, int]]) -> str:
    """text with the lines that say nothing about a clone blanked, line numbers kept: every
    line inside a span of tests, and every line whose stripped text, after a leading `pub` or
    `pub(...)` and its space, starts with `use ` or is `mod <name>;`, or starts with `//`, or
    is made only of BRACKETS characters. A blanked line becomes "", so fab.digest.clones,
    which skips blank lines, never keys a window on one. The result ends with a newline when
    text does. Pure."""
    raise NotImplementedError
