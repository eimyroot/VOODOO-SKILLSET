#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-python3}"
HOST="${VOODOO_HOST:-127.0.0.1}"
PORT="${VOODOO_PORT:-8787}"
URL="http://${HOST}:${PORT}"

command -v "$PYTHON" >/dev/null 2>&1 || {
  echo "ERROR: Python interpreter '$PYTHON' was not found." >&2
  exit 127
}

cd "$ROOT"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

echo "VOODOO-SKILLSET cockpit"
echo "  root: $ROOT"
echo "  url:  $URL"
echo "  trust: fail-closed"
echo

if [[ "${VOODOO_OPEN_BROWSER:-0}" == "1" ]]; then
  (
    sleep 0.8
    if command -v open >/dev/null 2>&1; then
      open "$URL" >/dev/null 2>&1 || true
    elif command -v xdg-open >/dev/null 2>&1; then
      xdg-open "$URL" >/dev/null 2>&1 || true
    fi
  ) &
fi

exec "$PYTHON" -m voodoo_skillset.cli serve --host "$HOST" --port "$PORT"
