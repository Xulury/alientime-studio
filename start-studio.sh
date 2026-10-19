#!/usr/bin/env bash
# ------------------------------------------------------------------------------------------
#  Alien Time Listing Studio - one-click start for macOS and Linux.
#  Run ./start-studio.sh (or double-click "Start Studio.command" on a Mac). It sets everything
#  up on the first run, starts the studio (backend + web interface) and opens it in your browser.
#  Developer mode (live reload, needs Node.js):  ./start-studio.sh dev
#  Other options: --port 8001  --no-browser  --reinstall  --rebuild
# ------------------------------------------------------------------------------------------
set -u
cd "$(dirname "$0")" || exit 1

is_ok() { "$1" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)' >/dev/null 2>&1; }

PY=""
for candidate in .venv/bin/python python3.13 python3.12 python3 python \
                 /opt/homebrew/bin/python3.13 /opt/homebrew/bin/python3.12 \
                 /usr/local/bin/python3.13 /usr/local/bin/python3.12; do
  if command -v "$candidate" >/dev/null 2>&1 && is_ok "$candidate"; then
    PY="$candidate"
    break
  fi
done

if [ -z "$PY" ]; then
  echo "[studio] Python 3.12 or newer was not found."
  if [ "$(uname)" = "Darwin" ]; then
    echo "[studio] Install it with:  brew install python@3.12   (or from https://www.python.org/downloads/)"
  else
    echo "[studio] Install it with your package manager, e.g.:  sudo apt install python3.12 python3.12-venv"
  fi
  echo "[studio] Then run this file again."
  exit 1
fi

exec "$PY" scripts/launch_studio.py "$@"
