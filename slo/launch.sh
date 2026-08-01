#!/usr/bin/env bash
#
# Launch the main slo API service.
#
# The primary API service is launched via ``launch.sh`` using
# ``poetry run uvicorn`` with production-grade flags.
set -euo pipefail

export PYTHONPATH="${PYTHONPATH:-${PWD}}"

poetry run uvicorn src.main:app \
    --port "${SLO_WEB_PORT:-7700}" \
    --host 0.0.0.0 \
    --forwarded-allow-ips="0.0.0.0/0" \
    --proxy-headers \
    --limit-concurrency 120 \
    --timeout-keep-alive 15 \
    --backlog 240 \
    --log-level error \
    --workers "${SLO_WEB_WORKERS:-4}" \
    --loop uvloop
