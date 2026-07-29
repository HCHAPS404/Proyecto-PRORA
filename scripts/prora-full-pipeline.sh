#!/usr/bin/env bash
# PRORA — pipeline completo: push → redeploy Render → sync → train → verificación
#
# Uso:
#   ./scripts/prora-full-pipeline.sh              # todo (push + sync + train)
#   ./scripts/prora-full-pipeline.sh --train-only # solo entrenar (datos ya cargados)
#   ./scripts/prora-full-pipeline.sh --sync-only  # solo sincronizar fuentes
#   ./scripts/prora-full-pipeline.sh --no-push    # no hace git push
#
# Credenciales (elige una):
#   export PRORA_OPERATOR_PASSWORD='ProraOps2026Secure!'   # default render.yaml
#   # o deja que el script la pida por stdin (no se muestra)
#
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

MODE="full"
DO_PUSH=1

for arg in "$@"; do
  case "$arg" in
    --train-only) MODE="train" ;;
    --sync-only)  MODE="sync" ;;
    --no-push)    DO_PUSH=0 ;;
    -h|--help)
      sed -n '2,12p' "$0"
      exit 0
      ;;
    *)
      echo "Opción desconocida: $arg (usa --help)"
      exit 1
      ;;
  esac
done

API_BASE="${PRORA_API_BASE:-https://prora-api.onrender.com/api/v1}"
API_ROOT="${API_BASE%/api/v1}"
EMAIL="${PRORA_OPERATOR_EMAIL:-helmut.chs@gmail.com}"
PASSWORD="${PRORA_OPERATOR_PASSWORD:-ProraOps2026Secure!}"
LOG_DIR="${PRORA_LOG_DIR:-/tmp}"
STAMP="$(date +%Y%m%d-%H%M%S)"
LOG_FILE="${LOG_DIR}/prora-pipeline-${STAMP}.log"

mkdir -p "$LOG_DIR"
exec > >(tee -a "$LOG_FILE") 2>&1

echo "=============================================="
echo " PRORA pipeline — $(date -Iseconds)"
echo " Modo: $MODE | Log: $LOG_FILE"
echo " API:  $API_BASE"
echo "=============================================="

if [[ "$PASSWORD" == "TuPasswordActual" ]]; then
  echo "ERROR: no uses el placeholder 'TuPasswordActual'."
  echo "  export PRORA_OPERATOR_PASSWORD='ProraOps2026Secure!'"
  exit 1
fi

if [[ -z "${PRORA_OPERATOR_PASSWORD:-}" ]]; then
  echo "Usando contraseña por defecto de render.yaml (o define PRORA_OPERATOR_PASSWORD)."
fi

if [[ "$DO_PUSH" -eq 1 ]]; then
  echo ""
  echo "==> [1/4] Push a origin/main"
  git push origin main
else
  echo ""
  echo "==> [1/4] Push omitido (--no-push)"
fi

echo ""
echo "==> [2/4] Esperando API lista ($API_ROOT/ready)"
READY=0
for attempt in $(seq 1 60); do
  if curl -fsS --max-time 45 "${API_ROOT}/ready" >/dev/null 2>&1; then
    READY=1
    break
  fi
  echo "    intento $attempt/60 — API dormida o redeploy en curso…"
  sleep 20
done
if [[ "$READY" -ne 1 ]]; then
  echo "ERROR: la API no respondió a /ready tras ~20 min."
  exit 1
fi
curl -fsS "${API_ROOT}/ready"
echo ""

echo "==> [3/4] Verificando login operador"
export PRORA_API_BASE="$API_BASE"
export PRORA_OPERATOR_EMAIL="$EMAIL"
export PRORA_OPERATOR_PASSWORD="$PASSWORD"
python3 -u - <<'PY'
import json, os, sys, urllib.request
base = os.environ["PRORA_API_BASE"]
req = urllib.request.Request(
    f"{base}/auth/login",
    data=json.dumps({
        "email": os.environ["PRORA_OPERATOR_EMAIL"],
        "password": os.environ["PRORA_OPERATOR_PASSWORD"],
    }).encode(),
    headers={"Content-Type": "application/json"},
    method="POST",
)
try:
    with urllib.request.urlopen(req, timeout=120) as resp:
        token = json.loads(resp.read()).get("access_token")
except urllib.error.HTTPError as exc:
    body = exc.read().decode("utf-8", errors="replace")
    print(f"LOGIN FALLÓ ({exc.code}): {body}", file=sys.stderr)
    sys.exit(1)
if not token:
    print("LOGIN FALLÓ: sin access_token", file=sys.stderr)
    sys.exit(1)
print("login OK")
PY

echo ""
echo "==> [4/4] Sync + train remoto"
export PRORA_FORCE_TRAIN=1
export PRORA_TRAIN_HORIZONS="${PRORA_TRAIN_HORIZONS:-4}"
export PRORA_DISEASES="${PRORA_DISEASES:-ira,leishmaniasis,malaria,dengue}"

case "$MODE" in
  full)
    unset PRORA_SYNC_ONLY PRORA_TRAIN_ONLY
    ;;
  train)
    export PRORA_TRAIN_ONLY=1
    unset PRORA_SYNC_ONLY
    echo "    (solo train: ira → leishmaniasis → malaria → dengue, horizonte ${PRORA_TRAIN_HORIZONS})"
    ;;
  sync)
    export PRORA_SYNC_ONLY=1
    unset PRORA_TRAIN_ONLY
    echo "    (solo sync: territorial + PAI 2026 + microdatos + SIVIGILA por años)"
    ;;
esac

python3 -u backend/scripts/remote_sync_and_train.py

echo ""
echo "=============================================="
echo " PIPELINE TERMINADO — $(date -Iseconds)"
echo " Log completo: $LOG_FILE"
echo ""
echo " Siguiente paso (opcional): republicar Pages"
echo "   gh workflow run \"Publicar frontend en GitHub Pages\""
echo ""
echo " Verifica en la UI:"
echo "   • Panorama nacional → mapa con predicciones"
echo "   • Centro de alertas → señales del modelo"
echo "   • Metodología → versión entrenada + métricas"
echo "=============================================="
