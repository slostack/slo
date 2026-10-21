#!/bin/bash
# Explicit approved harness and tracked safe Makefile fallback; no environment files sourced.
export VIRTUAL_ENV=/root/.pyenv/versions/slo-harness
export PATH="$VIRTUAL_ENV/bin:$PATH" PYENV_VERSION=slo-harness
export SLO_ENV=test SLO_ROOT_DIR="$PWD" SLO_APP_DIR="$PWD" SLO_APP_NAME=slo SLO_LOG_FORMAT=text SLO_DEFAULT_MODEL_NAME=gpt-5.4 SLO_AUTO_VISUALIZE=0 SLO_HERDR_DISABLED=1 SLO_ANTHROPIC_API_KEY=ci-placeholder-tests-are-fully-mocked COLUMNS=120 LINES=40 PYTHONPATH="$PWD"
label=$1
shift
root=docs/implementation/94-herdr/turn6-code-test-174-receipts
printf '%q ' "$@" > "$root/$label.command"
printf '\n' >> "$root/$label.command"
"$@" > "$root/$label.log" 2>&1
status=$?
printf '%s\n' "$status" > "$root/$label.exit"
dpkg -V coreutils > "$root/$label.coreutils" 2>&1
printf '%s\n' "$?" > "$root/$label.coreutils.exit"
tail -20 "$root/$label.log"
printf 'exit=%s coreutils_exit=%s\n' "$status" "$(cat "$root/$label.coreutils.exit")"
exit "$status"
