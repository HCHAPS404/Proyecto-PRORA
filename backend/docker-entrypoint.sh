#!/bin/sh
set -eu

PORT="${PORT:-8000}"

echo "prora: arranque (PORT=${PORT}, cmd=${1:-api})"

run_migrations_if_needed() {
  if [ "${PRORA_RUN_MIGRATIONS_ON_START:-false}" = "true" ]; then
    echo "prora: aplicando migraciones Alembic..."
    if ! alembic upgrade head; then
      echo "prora: ERROR — falló alembic upgrade head" >&2
      exit 1
    fi
    echo "prora: migraciones OK"
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

case "${1:-api}" in
  api)
    run_migrations_if_needed
    bootstrap_admin_if_needed
    if [ "${PRORA_EMBEDDED_WORKER:-false}" = "true" ]; then
      echo "prora: API + worker embebido (supervisor)"
      exec python -m app.runtime.serve_with_worker
    fi
    echo "prora: iniciando uvicorn en 0.0.0.0:${PORT}"
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
