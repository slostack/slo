#!/bin/bash
set -u
export VIRTUAL_ENV=/root/.pyenv/versions/slo-harness PYENV_VERSION=slo-harness
export PATH="$VIRTUAL_ENV/bin:$PATH"
export SLO_ENV=test SLO_ROOT_DIR="$PWD" SLO_APP_DIR="$PWD" SLO_APP_NAME=slo SLO_LOG_FORMAT=text SLO_DEFAULT_MODEL_NAME=gpt-5.4 SLO_AUTO_VISUALIZE=0 SLO_HERDR_DISABLED=1 SLO_ANTHROPIC_API_KEY=ci-placeholder-tests-are-fully-mocked COLUMNS=120 LINES=40 PYTHONPATH="$PWD"
r=docs/implementation/94-herdr/acquisition-owner-170-receipts
mkdir -p "$r"
label=$1; shift
printf '%q ' "$@" > "$r/$label.command"
printf '\n' >> "$r/$label.command"
"$@" > "$r/$label.log" 2>&1
result=$?
printf '%s\n' "$result" > "$r/$label.exit"
dpkg -V coreutils > "$r/$label.coreutils"
integrity=$?
if [ "$integrity" -ne 0 ] || [ -s "$r/$label.coreutils" ]; then cat "$r/$label.coreutils"; exit 99; fi
tail -15 "$r/$label.log"
exit "$result"
