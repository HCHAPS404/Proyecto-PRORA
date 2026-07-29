#!/usr/bin/env bash
# Entrena modelos PRORA sin trabar Cursor.
# Ejecutar en tmux/terminal externa, NO dentro del panel de Cursor.
#
# Uso:
#   ./scripts/prora-train-safe.sh          # entrena lo pendiente (con checkpoint)
#   ./scripts/prora-train-safe.sh --fresh  # ignora checkpoint previo
#   ./scripts/prora-train-safe.sh --verify # solo valida modelos en API
#
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export PRORA_API_BASE="${PRORA_API_BASE:-https://prora-api.onrender.com/api/v1}"
export PRORA_OPERATOR_EMAIL="${PRORA_OPERATOR_EMAIL:-helmut.chs@gmail.com}"
export PRORA_OPERATOR_PASSWORD="${PRORA_OPERATOR_PASSWORD:-ProraOps2026Secure!}"
export PRORA_TRAIN_ONLY=1
export PRORA_TRAIN_HORIZONS="${PRORA_TRAIN_HORIZONS:-4}"
export PRORA_DISEASES="${PRORA_DISEASES:-ira,leishmaniasis,malaria,dengue}"
export PRORA_SKIP_TRAINED=1
export PRORA_POLL_SECONDS="${PRORA_POLL_SECONDS:-30}"
export PRORA_CHECKPOINT_FILE="${PRORA_CHECKPOINT_FILE:-$HOME/.prora/train-checkpoint.json}"

MODE="resume"
for arg in "$@"; do
  case "$arg" in
    --fresh)  MODE="fresh" ;;
    --verify) MODE="verify" ;;
    -h|--help)
      sed -n '2,8p' "$0"
      exit 0
      ;;
  esac
done

if [[ "${PRORA_OPERATOR_PASSWORD:-}" == "TuPasswordActual" ]]; then
  echo "ERROR: configura PRORA_OPERATOR_PASSWORD"
  exit 1
fi

LOG="${PRORA_LOG_DIR:-/tmp}/prora-train-$(date +%Y%m%d-%H%M%S).log"
mkdir -p "$(dirname "$LOG")"

if [[ "$MODE" == "fresh" ]]; then
  rm -f "$PRORA_CHECKPOINT_FILE"
  echo "Checkpoint borrado → entrenamiento desde cero"
fi

if [[ "$MODE" == "verify" ]]; then
  PRORA_VERIFY_ONLY=1 python3 -u backend/scripts/remote_sync_and_train.py
  exit 0
fi

export PRORA_RESUME=1
# Primera corrida: force solo si no hay ningún modelo entrenado aún
export PRORA_FORCE_TRAIN="${PRORA_FORCE_TRAIN:-1}"

echo "=============================================="
echo " PRORA train-safe — $(date -Iseconds)"
echo " Log: $LOG"
echo " Checkpoint: $PRORA_CHECKPOINT_FILE"
echo " Enfermedades: $PRORA_DISEASES"
echo ""
echo " IMPORTANTE: corre esto en tmux, no en Cursor:"
echo "   tmux new -s prora-train"
echo "   ./scripts/prora-train-safe.sh"
echo "=============================================="

# Desacoplar de Cursor: nice + log a archivo
nohup nice -n 10 python3 -u backend/scripts/remote_sync_and_train.py >> "$LOG" 2>&1 &
PID=$!
echo "Proceso en background PID=$PID"
echo "  tail -f $LOG"
echo "  kill $PID   # para cancelar"
wait "$PID" || true
echo "Terminó con código $?"
echo "Validación rápida:"
PRORA_FORCE_TRAIN=0 "$0" --verify 2>/dev/null || true
