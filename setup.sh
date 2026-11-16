#!/usr/bin/env bash
# One-time setup on macOS: creates .venv, installs deps, creates .env
set -euo pipefail
cd "$(dirname "$0")"

PY=""
for c in python3.13 python3.12 python3.11 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
    PY="$c"; break
  fi
done
if [ -z "$PY" ]; then
  echo "Python 3.11+ not found. Install with: brew install python@3.12"
  exit 1
fi
echo "Using $($PY --version)"

"$PY" -m venv .venv
.venv/bin/pip install --upgrade pip -q
.venv/bin/pip install -r requirements.txt

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env. Put your GEMINI_API_KEY in it (or leave blank for echo mode)."
fi
echo
echo "Done. Next:"
echo "  source .venv/bin/activate"
echo "  python -m skeleton.server          # terminal 1"
echo "  python -m skeleton.sim_client --mouth   # terminal 2"
