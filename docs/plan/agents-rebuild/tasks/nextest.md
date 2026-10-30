+++
id = "nextest"
part = "after-landing"
kind = "feature"
needs = []
files = ["fab/nextest.py", "fab/tests/test_nextest.py"]
effort = "medium"
minutes = 20
+++
# nextest's JUnit, exact filters and the config overlay

Fill the bodies of `fab/nextest.py` as their docstrings say: `Case.key`,
`junit`, `exact_filter`, `union` and `overlay`. Design:
`docs/design/fab.md`, section 11. The source is the agents repository's
`tools/after-landing/after-landing` (`junit`, `exact_filter`, `toml_value`
and the config written in `Runner.launch`); keep its rules, nothing more.

## Acceptance

- `fab/tests/test_nextest.py` covers, with small XML and TOML texts written
  in the test (no fixture files):
  - junit: passing, failed (`failure` and `error`, text and `message`),
    skipped cases across two suites, in order; the error cut to ERROR_LINE;
    a missing file, a bad root, a repeated identity and a wrong `tests`
    count each a ValueError;
  - exact_filter accepting `crate::module::test_name` and refusing a space,
    a quote and a parenthesis; union of one and of three filters, none
    refused;
  - overlay: the result parses with tomllib to the input's data plus the
    profile's junit table, a nested override (`[[profile.x.overrides]]`) and
    a non-ASCII string surviving; an existing junit table replaced; an
    unknown profile refused;
  - `Case.key` round-trips through json.loads.
- `bin/fab test` passes; `test_nextest.py` takes under half a second.

## Options, settled up front

- XML through `xml.etree.ElementTree`; no new dependency.
- overlay writes keys in the parsed order; floats through `repr`, refused
  when not finite.
