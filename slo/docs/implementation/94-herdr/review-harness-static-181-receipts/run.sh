#!/bin/bash
set -u
cd /root/Code/slo-94-herdr-integration/slo || exit 1
export VIRTUAL_ENV=/root/.pyenv/versions/slo-harness
export PATH="$VIRTUAL_ENV/bin:$PATH" PYENV_VERSION=slo-harness
export SLO_ENV=test SLO_ROOT_DIR="$PWD" SLO_APP_DIR="$PWD" SLO_APP_NAME=slo SLO_LOG_FORMAT=text SLO_DEFAULT_MODEL_NAME=gpt-5.4 SLO_AUTO_VISUALIZE=0 SLO_HERDR_DISABLED=1 SLO_ANTHROPIC_API_KEY=ci-placeholder-tests-are-fully-mocked COLUMNS=120 LINES=40 PYTHONPATH="$PWD"
R=docs/implementation/94-herdr/review-harness-static-181-receipts
label="$1"; shift
printf '%q ' "$@" > "$R/$label.command"; printf '\n' >> "$R/$label.command"
"$@" > "$R/$label.log" 2>&1
result=$?; printf '%s\n' "$result" > "$R/$label.exit"
dpkg -V coreutils > "$R/$label.coreutils" 2>&1
integrity=$?; printf '%s\n' "$integrity" > "$R/$label.coreutils.exit"
tail -n 18 "$R/$label.log"
printf 'command_exit=%s coreutils_exit=%s\n' "$result" "$integrity"
if [ "$integrity" != 0 ] || [ -s "$R/$label.coreutils" ]; then cat "$R/$label.coreutils"; exit 99; fi
exit "$result"
