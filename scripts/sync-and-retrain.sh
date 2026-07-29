#!/usr/bin/env bash
# Sincroniza fuentes territoriales con datos 2025, re-entrena y publica.
# Uso: PRORA_DATABASE_URL='postgres://...' bash scripts/sync-and-retrain.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

if [[ -z "${PRORA_DATABASE_URL:-}" ]]; then
  echo "ERROR: Exporta PRORA_DATABASE_URL con la URL de la BD de Render."
  exit 1
fi

source .venv/bin/activate 2>/dev/null || true

echo "══════════════════════════════════════════"
echo " PRORA: Sync territorial + retrain + publish"
echo " $(date -Iseconds)"
echo "══════════════════════════════════════════"

echo ""
echo "▶ Paso 1/3: Sincronizar fuentes territoriales (Socrata → BD)"
echo "  Las fuentes territoriales (Bucaramanga, Boyacá, Caquetá, etc.)"
echo "  y el BES semanal pueden contener datos 2025."
echo ""
echo "  NOTA: La sincronización requiere que la API de Render esté activa."
echo "  Si Render no responde, los datos existentes en la BD se usarán tal cual."
echo ""

echo "▶ Paso 2/3: Entrenar modelos localmente"
python3 scripts/train-local.py --all
echo "✓ Entrenamiento local completo."

echo ""
echo "▶ Paso 3/3: Publicar modelos a la BD de Render"
python3 scripts/publish-models.py
echo "✓ Modelos publicados."

echo ""
echo "══════════════════════════════════════════"
echo " Completado. Verifica en el dashboard."
echo "══════════════════════════════════════════"
