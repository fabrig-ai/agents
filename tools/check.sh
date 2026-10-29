#!/bin/bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
export PYTHONDONTWRITEBYTECODE=1
bash -n tools/check.sh
python3 -I -B - <<'PY'
import importlib.util
from pathlib import Path
import sys
import unittest

suite = unittest.TestSuite()
for path in sorted(Path("tools").rglob("test_*.py")):
    # Import each file explicitly: unittest discovery skips non-package subdirs.
    # A path-derived module name also permits repeated basenames in subdirs.
    sys.path.insert(0, str(path.parent.resolve()))
    name = "gate_" + path.as_posix().encode().hex()
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    suite.addTests(unittest.defaultTestLoader.loadTestsFromModule(module))
result = unittest.TextTestRunner(verbosity=2).run(suite)
sys.exit(0 if result.wasSuccessful() else 1)
PY
