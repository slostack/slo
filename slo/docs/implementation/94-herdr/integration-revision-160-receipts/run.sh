#!/bin/bash
# Offline verification only; no environment files sourced.
export VIRTUAL_ENV=/root/.pyenv/versions/slo-harness
export PATH="$VIRTUAL_ENV/bin:$PATH" PYENV_VERSION=slo-harness
export SLO_ENV=test SLO_ROOT_DIR="$PWD" SLO_APP_DIR="$PWD" SLO_APP_NAME=slo SLO_LOG_FORMAT=text SLO_DEFAULT_MODEL_NAME=gpt-5.4 SLO_AUTO_VISUALIZE=0 SLO_HERDR_DISABLED=1 SLO_ANTHROPIC_API_KEY=ci-placeholder-tests-are-fully-mocked COLUMNS=120 LINES=40 PYTHONPATH="$PWD"
receipt=docs/implementation/94-herdr/integration-revision-160-receipts
name="$1"
shift
printf '%q ' "$@" > "$receipt/$name.command"
printf '\n' >> "$receipt/$name.command"
"$@" > "$receipt/$name.log" 2>&1
result=$?
printf '%s\n' "$result" > "$receipt/$name.exit"
tail -n 18 "$receipt/$name.log"
dpkg -V coreutils > "$receipt/$name.coreutils"
check=$?
if [ "$check" != 0 ] || [ -s "$receipt/$name.coreutils" ]; then cat "$receipt/$name.coreutils"; exit 99; fi
exit "$result"
