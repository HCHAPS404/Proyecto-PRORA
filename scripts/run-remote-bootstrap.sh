#!/usr/bin/env bash
# Publica commits locales, espera el deploy de Render y ejecuta sync+train remoto.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "==> Push a origin/main"
git push origin main

API_BASE="${PRORA_API_BASE:-https://prora-api.onrender.com/api/v1}"
EMAIL="${PRORA_OPERATOR_EMAIL:-helmut.chs@gmail.com}"
PASSWORD="${PRORA_OPERATOR_PASSWORD:-ProraOps2026Secure!}"

echo "==> Esperando redeploy + API lista (${API_BASE%/api/v1}/ready)"
for _ in $(seq 1 60); do
  if curl -fsS "${API_BASE%/api/v1}/ready" >/dev/null 2>&1; then
    break
  fi
  sleep 20
done
curl -fsS "${API_BASE%/api/v1}/ready"
echo

echo "==> Sync + train remoto (force + ventanas SIVIGILA)"
export PRORA_API_BASE="$API_BASE"
export PRORA_OPERATOR_EMAIL="$EMAIL"
export PRORA_OPERATOR_PASSWORD="$PASSWORD"
export PRORA_FORCE_TRAIN=1
python3 backend/scripts/remote_sync_and_train.py

echo "==> Listo. Republica Pages si hace falta:"
echo "    gh workflow run \"Publicar frontend en GitHub Pages\""
