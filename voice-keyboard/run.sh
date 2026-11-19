#!/usr/bin/env bash
# Start the voice keyboard daemon. Extra args go to voicekey.py (see --help).
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  uv venv -q .venv -p 3.12
  uv pip install -q -p .venv -r requirements.txt
fi
exec .venv/bin/python -u voicekey.py "$@" 2> >(grep -v -i warning >&2)
