#!/bin/bash
set -euo pipefail
kit=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
exec python3 -I -B "$kit/bootstrap.py" root "$@"
