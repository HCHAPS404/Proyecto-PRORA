#!/bin/sh
set -eu

PORT="${PORT:-8000}"
WORKER_PID=""

cleanup() {
  if [ -n "${WORKER_PID}" ] && kill -0 "${WORKER_PID}" 2>/dev/null; then
    kill "${WORKER_PID}" 2>/dev/null || true
    wait "${WORKER_PID}" 2>/dev/null || true
  fi
}

run_migrations_if_needed() {
  if [ "${PRORA_RUN_MIGRATIONS_ON_START:-false}" = "true" ]; then
    echo "prora: aplicando migraciones Alembic..."
    alembic upgrade head
  fi
}

bootstrap_admin_if_needed() {
  if [ -n "${PRORA_BOOTSTRAP_ADMIN_EMAIL:-}" ] && [ -n "${PRORA_BOOTSTRAP_ADMIN_PASSWORD:-}" ]; then
    echo "prora: bootstrap de operador (si no existe)..."
    python -m app.cli create-operator \
      --email "${PRORA_BOOTSTRAP_ADMIN_EMAIL}" \
      --role "${PRORA_BOOTSTRAP_ADMIN_ROLE:-admin}" \
      --full-name "${PRORA_BOOTSTRAP_ADMIN_NAME:-Operador PRORA}" \
      --password "${PRORA_BOOTSTRAP_ADMIN_PASSWORD}" \
      --promote-existing \
      || echo "prora: aviso — bootstrap de operador no aplicado (revise logs)"
  fi
}

start_embedded_worker_if_needed() {
  if [ "${PRORA_EMBEDDED_WORKER:-false}" = "true" ]; then
    echo "prora: arrancando worker embebido (plan free / un solo servicio)..."
    python -m app.jobs.worker --poll-seconds "${PRORA_WORKER_POLL_SECONDS:-10}" &
    WORKER_PID=$!
  fi
}

case "${1:-api}" in
  api)
    run_migrations_if_needed
    bootstrap_admin_if_needed
    start_embedded_worker_if_needed
    if [ -n "${WORKER_PID}" ]; then
      trap cleanup EXIT INT TERM
      uvicorn app.main:app \
        --host 0.0.0.0 \
        --port "$PORT" \
        --proxy-headers \
        --forwarded-allow-ips='*' &
      UVICORN_PID=$!
      wait "${UVICORN_PID}"
      exit_code=$?
      cleanup
      trap - EXIT INT TERM
      exit "${exit_code}"
    fi
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
