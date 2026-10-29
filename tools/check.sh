#!/bin/bash
set -euo pipefail
self=$(realpath -- "${BASH_SOURCE[0]}")
cd -- "$(dirname -- "$self")/.."
# One agents gate at a time per host: concurrent gates starve each other and
# the sessions sharing the host. tools/land holds the same lock across its runs.
if [[ -z ${AGENTS_GATE_HELD:-} ]]; then
    lock=${AGENTS_GATE_LOCK:-$HOME/.local/state/agents-gate.lock}
    mkdir -p -- "$(dirname -- "$lock")"
    export AGENTS_GATE_HELD=1
    flock -n -o "$lock" true || echo "check.sh: waiting for another agents gate on this host ($lock)" >&2
    exec flock -o "$lock" bash "$self" "$@"
fi
export PYTHONDONTWRITEBYTECODE=1
bash -n tools/check.sh
python3 -I -B - "$@" <<'PYCODE'
from concurrent.futures import ProcessPoolExecutor
import multiprocessing
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

# Each file gets a fresh interpreter as well as its own HOME and temp root.
# Import explicitly: discovery skips non-package subdirs, and basenames repeat.
RUN_FILE = """
import importlib.util
from pathlib import Path
import sys
import unittest

path = Path(sys.argv[1])
sys.path.insert(0, str(path.parent))
name = "gate_" + path.relative_to(Path.cwd()).as_posix().encode().hex()
spec = importlib.util.spec_from_file_location(name, path)
module = importlib.util.module_from_spec(spec)
sys.modules[name] = module
spec.loader.exec_module(module)
suite = unittest.defaultTestLoader.loadTestsFromModule(module)
result = unittest.TextTestRunner(verbosity=2).run(suite)
sys.exit(0 if result.wasSuccessful() else 1)
"""


def run_file(path):
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="gate-file-") as directory:
        home = Path(directory) / "home"
        home.mkdir()
        env = dict(os.environ, HOME=str(home), TMPDIR=directory)
        result = subprocess.run([sys.executable, "-I", "-B", "-c", RUN_FILE, str(path)],
                                env=env, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    return result.returncode, result.stdout, time.monotonic() - started


root = Path.cwd()
if sys.argv[1:]:
    paths = sorted({Path(arg).resolve() for arg in sys.argv[1:]})
    for path in paths:
        if not (path.is_relative_to(root / "tools") and path.is_file()
                and path.match("test_*.py")):
            sys.exit(f"check: expected a tools/test_*.py file: {path}")
else:
    paths = sorted(path.resolve() for path in Path("tools").rglob("test_*.py"))
started = time.monotonic()
failed = 0
workers = min(8, os.cpu_count() or 1)
# Explicit fork lets this small stdin driver work without an importable module.
with ProcessPoolExecutor(max_workers=workers,
                         mp_context=multiprocessing.get_context("fork")) as pool:
    # Queue large fixture files first to avoid a long final worker. Presentation
    # still follows discovery order, independently of execution order.
    queued = sorted(paths, key=lambda path: (-path.stat().st_size, path))
    futures = {path: pool.submit(run_file, path) for path in queued}
    for path in paths:
        code, output, elapsed = futures[path].result()
        print(f"=== {path.relative_to(root)} ({elapsed:.3f}s) ===", file=sys.stderr)
        print(output, end="" if output.endswith("\n") else "\n", file=sys.stderr, flush=True)
        failed += code != 0
print(f"Checked {len(paths)} files in {time.monotonic() - started:.3f}s "
      f"({workers} workers; {failed} failed)", file=sys.stderr)
sys.exit(1 if failed else 0)
PYCODE
