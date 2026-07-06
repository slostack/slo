#!/usr/bin/env bash
#
# Launch the main slo API service.
#
# Convention (see awesome-agi bootstrap-project-scaffolding.md §11):
# the primary API service is always launched via ``launch.sh`` using
# ``poetry run uvicorn`` with production-grade flags. Migrations run first
# and are a hard prerequisite — ``set -euo pipefail`` ensures a failed
# ``make migrate`` aborts the launch rather than booting against an
# un-migrated database. This script launches ONE service only — it does
# not bring up Docker or any other composite infrastructure (use
# ``make dev-up`` for that).
set -euo pipefail

export PYTHONPATH="${PYTHONPATH:-${PWD}}"

make migrate

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
