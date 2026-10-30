#!/bin/bash
# Offline bounded commands; no environment files or live capabilities.
export VIRTUAL_ENV=/root/.pyenv/versions/slo-harness
export PATH="$VIRTUAL_ENV/bin:$PATH" PYENV_VERSION=slo-harness
export SLO_ENV=test SLO_ROOT_DIR="$PWD" SLO_APP_DIR="$PWD" SLO_APP_NAME=slo SLO_LOG_FORMAT=text SLO_DEFAULT_MODEL_NAME=gpt-5.4 SLO_AUTO_VISUALIZE=0 SLO_HERDR_DISABLED=1 SLO_ANTHROPIC_API_KEY=ci-placeholder-tests-are-fully-mocked COLUMNS=120 LINES=40 PYTHONPATH="$PWD"
label=$1
shift
root=docs/implementation/94-herdr/close-regression-167
mkdir -p "$root"
printf '%q ' "$@" > "$root/$label.command"
printf '\n' >> "$root/$label.command"
"$@" > "$root/$label.log" 2>&1
result=$?
printf '%s\n' "$result" > "$root/$label.exit"
dpkg -V coreutils > "$root/$label.coreutils"
if [ -s "$root/$label.coreutils" ]; then cat "$root/$label.coreutils"; exit 99; fi
tail -18 "$root/$label.log"
exit "$result"
