+++
id = "channel"
part = "user-channel"
kind = "feature"
needs = []
files = ["fab/channel.py", "fab/tests/test_channel.py"]
effort = "high"
minutes = 35
+++
# The user's open questions and the page's text

Fill these bodies of `fab/channel.py` as their docstrings say: `asks`,
`plan_dirs`, `signal_section`, `latest_reports`, `excerpt`, `answers_text`
and `render`. Leave `compose`, `write`, `answer` and `main` raising
NotImplementedError: `channel-tick` fills them. Design:
`docs/design/fab.md`, 13.6, with sections 3, 12 and 13.1 for the records
the fold reads.

## Acceptance

- `fab/tests/test_channel.py`, with plain event dicts (ts strings in
  `fab.log.now()`'s format), `Plan` and `Question` built in the test, and
  a temporary HOME and FAB_HOME for the functions that read files, covers:
  - `asks`:
    - a plan's open question, one with an answer, one whose answer is only
      spaces (open);
    - a call that ended question, then the same subject asking again (one
      ask, moved to the end);
    - a call.parked, and both kinds open for one subject;
    - call.answered closing both kinds;
    - a later done call of the subject closing the call kind only;
    - call.finished closing a parked ask;
    - a question.answered naming the subject closing nothing;
    - records missing a field skipped;
    - the order: plans first, then the log's by last opening;
    - the report paths under FAB_HOME.
  - `plan_dirs`: no file, the file's lines with a blank one, a given
    directory already listed (kept once, first place), relative paths
    resolved.
  - `signal_section`: both reports' Signals sections as `fab.code_report`
    and `fab.landing_report` render them (call their `render` on an empty
    log and empty `fab.report.Sources`), a report without one, the last
    section.
  - `latest_reports`: two days and a stray file in one directory, landing
    last, a dot-file sibling skipped, a missing directory, a day file
    that cannot be read listed (mode 000; skipped when the tests run as
    root).
  - `excerpt`: a long report cut at QUESTION_LINES, trailing blank lines,
    a missing file, an empty one.
  - `answers_text`: two answers in order, another subject's left out, a
    missing field, none.
  - `render`: each kind's block, no entries, no reports, unread present
    and absent, ending with one newline.
- `bin/fab test` passes; `test_channel.py` takes under half a second.

## Options, settled up front

- Times compare as ts strings; nothing here turns them into datetimes.
- `latest_reports` takes the greatest file name as the latest day: the
  names are fixed-width dates.
- `render` quotes bodies as they are: no escaping of Markdown in a report's
  lines.
- Private helpers are yours; the public functions keep their signatures.

## Answers

- 2026-10-30, the designer, before the first run: the page quotes from each
  report only the Signals lines whose owner is the user (13.6); a report's
  other signals stay in the report, which is the director's. The drafts
  send reports to the director, who passes the user only what needs them.
