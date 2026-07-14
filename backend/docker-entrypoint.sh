#!/bin/sh
set -eu

PORT="${PORT:-8000}"

case "${1:-api}" in
  api)
    exec uvicorn app.main:app \
      --host 0.0.0.0 \
      --port "$PORT" \
      --proxy-headers \
      --forwarded-allow-ips='*'
    ;;
  worker)
    exec python -m app.jobs.worker --poll-seconds "${PRORA_WORKER_POLL_SECONDS:-5}"
    ;;
  migrate)
    exec alembic upgrade head
    ;;
  *)
    exec "$@"
    ;;
esac
