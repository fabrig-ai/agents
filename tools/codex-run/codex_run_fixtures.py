"""Run the launcher suite with private HOME, workspace, PATH and services."""

import os
from pathlib import Path
import subprocess
import tempfile


KIT = Path(__file__).resolve().parent


def run_suite(case, *selection):
    with tempfile.TemporaryDirectory(prefix="codex-run-tests-") as directory:
        home = Path(directory) / "home"
        home.mkdir()
        env = dict(os.environ, HOME=str(home), TMPDIR=directory,
                   PYTHONDONTWRITEBYTECODE="1")
        # Do not inherit a caller's shell startup or exported Bash functions.
        for key in list(env):
            if key in ("BASH_ENV", "ENV", "CODEX_RUN_ISOLATION_LOG",
                       "CODEX_RUN_STALE_TRANSCRIPT") or key.startswith("BASH_FUNC_"):
                env.pop(key)
        result = subprocess.run(["/bin/bash", str(KIT / "test-codex-run"), *selection],
                                cwd=directory, env=env, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, timeout=900)
    case.assertEqual(result.returncode, 0, result.stdout)
    print(result.stdout, end="", flush=True)
