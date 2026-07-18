#!/bin/sh
set -eu

companion_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
project_dir=$(dirname "$companion_dir")
venv="$companion_dir/.venv"

if [ ! -x "$venv/bin/python" ]; then
  python3 -m venv "$venv"
fi

if ! "$venv/bin/python" -c "import bleak" >/dev/null 2>&1; then
  "$venv/bin/python" -m pip install -r "$companion_dir/requirements.txt"
fi

cd "$project_dir"
export PYTHONPATH="$project_dir"
exec "$venv/bin/python" -m companion.codex_display "$@"
