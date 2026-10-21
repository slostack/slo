#!/bin/bash
# Bounded independent review: capture exact commands, outputs and integrity checks.
set -u
cd /root/Code/slo-94-herdr-integration/slo || exit 99
export VIRTUAL_ENV=/root/.pyenv/versions/slo-harness
export PATH="$VIRTUAL_ENV/bin:$PATH"
export PYENV_VERSION=slo-harness
export SLO_ENV=test SLO_ROOT_DIR="$PWD" SLO_APP_DIR="$PWD" SLO_APP_NAME=slo SLO_LOG_FORMAT=text SLO_DEFAULT_MODEL_NAME=gpt-5.4 SLO_AUTO_VISUALIZE=0 SLO_HERDR_DISABLED=1 SLO_ANTHROPIC_API_KEY=ci-placeholder-tests-are-fully-mocked COLUMNS=120 LINES=40
export PYTHONPATH="$PWD"
receipts=docs/implementation/94-herdr/review-wiring-180-receipts
label="$1"
shift
printf '%q ' "$@" > "$receipts/$label.command"
printf '\n' >> "$receipts/$label.command"
"$@" > "$receipts/$label.log" 2>&1
result=$?
printf '%s\n' "$result" > "$receipts/$label.exit"
dpkg -V coreutils > "$receipts/$label.coreutils" 2>&1
integrity=$?
printf '%s\n' "$integrity" > "$receipts/$label.coreutils.exit"
cat "$receipts/$label.log"
printf '\nRUN_EXIT=%s COREUTILS_EXIT=%s\n' "$result" "$integrity"
if [ "$integrity" -ne 0 ] || [ -s "$receipts/$label.coreutils" ]; then
  cat "$receipts/$label.coreutils"
  exit 99
fi
exit "$result"
