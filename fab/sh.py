"""The runner seam: every command fab runs goes through a runner (docs/design/fab.md, 8).

Functions that run commands take `sh`, a callable with `run`'s signature, and
default to `run`. Tests pass `fab.tests.support.FakeRunner` instead.
"""

from __future__ import annotations

import shlex
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Result:
    code: int
    out: str = ""
    err: str = ""

    @property
    def ok(self) -> bool:
        return self.code == 0


class Failed(RuntimeError):
    """A command run with check=True exited non-zero."""

    def __init__(self, argv: Sequence[str], result: Result):
        self.argv = list(argv)
        self.result = result
        detail = (result.err or result.out).strip().splitlines()[-5:]
        super().__init__(f"{shlex.join(self.argv)} exited {result.code}" + "".join(f"\n  {line}" for line in detail))


class Runner(Protocol):
    def __call__(self, argv: Sequence[str], *, cwd: str | None = None, input: str | None = None,
                 env: Mapping[str, str] | None = None, timeout: float | None = None,
                 check: bool = False) -> Result: ...


TIMEOUT = 124


def run(argv: Sequence[str], *, cwd: str | None = None, input: str | None = None,
        env: Mapping[str, str] | None = None, timeout: float | None = None, check: bool = False) -> Result:
    """Run argv to completion and capture its output; exit 124 when it times out."""
    try:
        done = subprocess.run(list(argv), cwd=cwd, input=input, env=env, timeout=timeout,
                              capture_output=True, text=True)
        result = Result(done.returncode, done.stdout, done.stderr)
    except subprocess.TimeoutExpired as expired:
        result = Result(TIMEOUT, _text(expired.stdout), _text(expired.stderr) + f"\ntimed out after {timeout} s")
    if check and not result.ok:
        raise Failed(argv, result)
    return result


def ssh(target: str, argv: Sequence[str]) -> list[str]:
    """The argv that runs argv in a login shell on target (user@host), so PATH has the tools."""
    return ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", target,
            "bash -lc " + shlex.quote(shlex.join(argv))]


def _text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    return value.decode(errors="replace") if isinstance(value, bytes) else value
