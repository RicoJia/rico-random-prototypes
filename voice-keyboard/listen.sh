#!/usr/bin/env bash
# Always-on dictation: press Enter in this terminal to start/stop, then talk into any window.
exec "$(dirname "$0")/run.sh" --mode listen "$@"
