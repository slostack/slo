#!/bin/bash
set -o pipefail
export VIRTUAL_ENV=/root/.pyenv/versions/slo-harness
export PATH="$VIRTUAL_ENV/bin:$PATH" PYENV_VERSION=slo-harness
export MYPY_CACHE_DIR="$PWD/docs/implementation/94-herdr/static-A-153-receipts/mypy-cache"
R=docs/implementation/94-herdr/static-A-153-receipts
name=$1
shift
printf '%q ' "$@" > "$R/$name.command"
printf '\n' >> "$R/$name.command"
"$@" > "$R/$name.log" 2>&1
code=$?
printf '%s\n' "$code" > "$R/$name.exit"
tail -n 12 "$R/$name.log"
exit "$code"
