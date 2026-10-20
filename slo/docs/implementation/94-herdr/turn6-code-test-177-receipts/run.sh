#!/usr/bin/env bash
# Tracked synthetic fallback only; never sources development env.
# Approved slo-harness interpreter pinned so `poetry run` resolves to it.
set -u
label="$1"; shift
cd /root/Code/slo-94-herdr-integration/slo
export VIRTUAL_ENV=/root/.pyenv/versions/slo-harness
export PATH="$VIRTUAL_ENV/bin:$PATH" PYENV_VERSION=slo-harness
export SLO_ENV=test SLO_ROOT_DIR="$PWD" SLO_APP_DIR="$PWD" SLO_APP_NAME=slo SLO_LOG_FORMAT=text SLO_DEFAULT_MODEL_NAME=gpt-5.4 SLO_AUTO_VISUALIZE=0 SLO_HERDR_DISABLED=1 SLO_ANTHROPIC_API_KEY=ci-placeholder-tests-are-fully-mocked COLUMNS=120 LINES=40
export PYTHONPATH="$PWD"
dir=docs/implementation/94-herdr/turn6-code-test-177-receipts
printf '%q ' "$@" > "$dir/$label.command"; printf '\n' >> "$dir/$label.command"
"$@" > "$dir/$label.log" 2>&1
status=$?
echo "$status" > "$dir/$label.exit"
dpkg -V coreutils > "$dir/$label.coreutils" 2>&1
echo "$?" > "$dir/$label.coreutils.exit"
tail -5 "$dir/$label.log"
echo "exit=$status coreutils=$(cat "$dir/$label.coreutils.exit")"
