# Verification subprocess only; tracked Makefile fallback, no sourced secrets.
export VIRTUAL_ENV=/root/.pyenv/versions/slo-harness PYENV_VERSION=slo-harness
export PATH="$VIRTUAL_ENV/bin:$PATH"
export SLO_ENV=test SLO_ROOT_DIR="$PWD" SLO_APP_DIR="$PWD" SLO_APP_NAME=slo SLO_LOG_FORMAT=text SLO_DEFAULT_MODEL_NAME=gpt-5.4 SLO_AUTO_VISUALIZE=0 SLO_HERDR_DISABLED=1 SLO_ANTHROPIC_API_KEY=ci-placeholder-tests-are-fully-mocked COLUMNS=120 LINES=40 PYTHONPATH="$PWD"
R=docs/implementation/94-herdr/integrated-gates-154-receipts
run_gate() {
    local name="$1" code integrity; shift
    printf '%q ' "$@" > "$R/$name.command"; printf '\n' >> "$R/$name.command"
    date -u +%FT%TZ > "$R/$name.started"
    "$@" > "$R/$name.log" 2>&1; code=$?
    printf '%s\n' "$code" > "$R/$name.exit"
    date -u +%FT%TZ > "$R/$name.finished"
    /usr/bin/dpkg -V coreutils > "$R/coreutils-$name.log" 2>&1; integrity=$?
    printf '%s\n' "$integrity" > "$R/coreutils-$name.exit"
    tail -10 "$R/$name.log"
    if [ "$integrity" != 0 ] || [ -s "$R/coreutils-$name.log" ]; then
        echo 'STOP: coreutils integrity anomaly'; cat "$R/coreutils-$name.log"; return 99
    fi
    return "$code"
}
