export VIRTUAL_ENV=/root/.pyenv/versions/slo-harness
export PATH="$VIRTUAL_ENV/bin:$PATH"
export SLO_ENV=test SLO_ROOT_DIR="$PWD" SLO_APP_DIR="$PWD" SLO_APP_NAME=slo SLO_LOG_FORMAT=text SLO_DEFAULT_MODEL_NAME=gpt-5.4 SLO_AUTO_VISUALIZE=0 SLO_HERDR_DISABLED=1 SLO_ANTHROPIC_API_KEY=ci-placeholder-tests-are-fully-mocked COLUMNS=120 LINES=40 PYTHONPATH="$PWD"
record() {
    local name="$1"; shift
    local base="release-evidence/96-durable-composer/logs/turn4-$name"
    printf '%q ' "$@" > "$base.command"; printf '\n' >> "$base.command"
    date -u +%FT%TZ > "$base.started"
    "$@" > "$base.log" 2>&1
    local status=$?
    printf '%s\n' "$status" > "$base.exit"
    date -u +%FT%TZ > "$base.finished"
    tail -n 5 "$base.log"
    return "$status"
}
