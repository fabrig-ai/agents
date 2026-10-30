"""Codex runs as user units on a builder (docs/design/fab.md, 5). Replaces fabrig's codex-run.

`fab codex start BRIEF DIR REPORT [--effort E] [--read-only] [--model M]` starts the unit and
prints `<id> <state>`, as codex-run did, so `fab.run` reads it the same way. The unit runs
`fab codex _exec ID`, which feeds the brief to `codex exec`, keeps its events, and touches
`<state>/ended` when everything is written.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

from fab.sh import Runner, run

CAPACITY = "Selected model is at capacity. Please try a different model."
DELAYS = (120, 300, 900)  # seconds before each retry of a turn the model refused for capacity
EFFORTS = ("medium", "high", "xhigh")


def state_root() -> Path:
    """FAB_HOME/codex: one directory per run, named by its id."""
    raise NotImplementedError


def new_id(now: Callable[[], str] | None = None) -> str:
    """`YYYYMMDDTHHMMSSZ-xxxx`: UTC seconds and four random hex digits."""
    raise NotImplementedError


def command(*, effort: str, read_only: bool, model: str | None, last: Path, thread: str | None) -> list[str]:
    """The codex argv: `codex exec`, then `resume` when a thread continues; `-m model` when given;
    `-c model_reasoning_effort=<effort>`; `--sandbox read-only` when read_only, else
    `--dangerously-bypass-approvals-and-sandbox`; `--skip-git-repo-check --json -o <last>`;
    the thread id when resuming; `-` (the prompt on stdin). --sandbox only without resume."""
    raise NotImplementedError


def start(brief: Path, workdir: Path, report: Path, *, effort: str = "high", read_only: bool = False,
          model: str | None = None, sh: Runner = run) -> tuple[str, Path]:
    """Refuse (ValueError) a relative path, a missing brief or workdir, an existing report or an
    unknown effort. Create the state directory with meta.json (brief, dir, report, effort,
    read_only, model, started), then `systemd-run --user --collect --quiet --unit fab-codex-<id>
    --property=UMask=0077 -- <python3> -I -B <this repo's bin/fab> codex _exec <id>`. Returns
    (id, state directory)."""
    raise NotImplementedError


def tokens(events: Sequence[dict]) -> dict[str, int]:
    """Sums of input_tokens, cached_input_tokens and output_tokens over turn.completed usages."""
    raise NotImplementedError


def at_capacity(events: Sequence[dict], stderr: str) -> bool:
    """Whether a turn failed because the model was at capacity (an error or turn.failed event
    whose message is CAPACITY, or CAPACITY in stderr)."""
    raise NotImplementedError


def execute(run_id: str, *, sh: Runner = run, sleep: Callable[[float], None] | None = None) -> int:
    """The unit's body. Run the command in the workdir with the brief on stdin, appending stdout
    to events.jsonl and stderr to stderr.log; keep the thread id from the first thread.started
    event in `thread`. On failure at capacity, sleep the next DELAYS entry and resume the thread
    with `Go on with the task: the model was at capacity.`, at most len(DELAYS) times. Then: if
    the report is missing, write it as `Failed: the run wrote no report.` followed by last.md
    (when any); write result.json (exit, tries, tokens, ended); touch `ended` last. Returns the
    codex exit code."""
    raise NotImplementedError


def main(argv: list[str]) -> int:
    """`fab codex start ...` (prints `<id> <state>`; exit 2 on a refusal with its reason) and
    `fab codex _exec ID` (the unit's entry; exits with execute's code)."""
    raise NotImplementedError
