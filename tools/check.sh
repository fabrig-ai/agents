#!/bin/bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
export PYTHONDONTWRITEBYTECODE=1
bash -n tools/check.sh
python3 -I -B -m unittest discover -s tools -p 'test_*.py' -v
python3 -I -B tools/session/test_session_context.py
