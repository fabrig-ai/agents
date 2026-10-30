+++
id = "slots"
part = "slots"
kind = "feature"
needs = []
files = ["fab/slots.py", "fab/tests/test_slots.py"]
effort = "high"
minutes = 25
+++
# Slots: claims, the sweep, reclaim

Fill the bodies of `fab/slots.py` as their docstrings say. Design:
`docs/design/fab.md`, section 7. This is what keeps a builder's disk bounded
with eight slots, and what frees space for a build that waits for it.

## Acceptance

- `fab/tests/test_slots.py` builds small fake slots under a temporary
  FAB_SLOTS: `<n>/target/debug/{deps,incremental,build}` with a few files,
  some executable, some `.rlib`/`.rmeta`/`.d`, with chosen mtimes
  (`os.utime`). It covers:
  - claim, a second claim refused, read_claim, release by the holder (sweeps,
    removes the claim, touches the marker), release by another run refused,
    release with no claim;
  - sweep_plan: incremental directories of every profile, executables older
    than since_ns only, never rlib/rmeta/d/so, never through a symlink;
    since_ns None takes every executable;
  - idle's order (never released first, then oldest release);
  - reclaim with a fake `free` that grows as bytes are removed: stops after
    the first pass when enough, goes to whole targets when not, skips a
    claimed slot, leaves no claim behind;
  - main's four subcommands.
- `bin/fab test` passes; `test_slots.py` takes under a second.

## Options, settled up front

- Sizes count `st_blocks * 512`, as du does.
- No scan of `/proc` for open files: claimed slots are never reclaimed, and a
  run's own sweep happens after it ended.
- `fab slot list` prints one JSON object per line, keys sorted.
