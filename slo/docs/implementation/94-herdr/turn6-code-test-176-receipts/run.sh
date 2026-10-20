#!/usr/bin/env bash
# Tracked synthetic fallback only; never sources development env.
set -u
label="$1"; shift
cd /root/Code/slo-94-herdr-integration/slo
export SLO_ENV=test SLO_ROOT_DIR="$PWD" SLO_APP_DIR="$PWD" SLO_APP_NAME=slo SLO_LOG_FORMAT=text SLO_DEFAULT_MODEL_NAME=gpt-5.4 SLO_AUTO_VISUALIZE=0 SLO_ANTHROPIC_API_KEY=ci-placeholder-tests-are-fully-mocked COLUMNS=120 LINES=40
export SLO_HERDR_DISABLED=1
export PYTHONPATH="$PWD"
dir=docs/implementation/94-herdr/turn6-code-test-176-receipts
printf '%s\n' "$*" > "$dir/$label.command"
/root/.pyenv/versions/slo-harness/bin/python "$@" > "$dir/$label.log" 2>&1
status=$?
echo "$status" > "$dir/$label.exit"
dpkg -V coreutils > "$dir/$label.coreutils" 2>&1
echo "$?" > "$dir/$label.coreutils.exit"
echo "exit=$status coreutils=$(cat "$dir/$label.coreutils.exit")"
