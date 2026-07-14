# PRORA API

Servicio FastAPI asíncrono para identidad, fuentes, ingesta agregada, modelos,
predicciones municipales, explicabilidad, alertas y el agente analítico de PRORA.

## Desarrollo

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev,ml]"
Copy-Item .env.example .env
uvicorn app.main:app --reload --port 8000
```

La documentación OpenAPI queda disponible en `/docs`, `/redoc` y
`/api/v1/openapi.json`. En producción configure `PRORA_DATABASE_URL` con
PostgreSQL, establezca un `PRORA_JWT_SECRET` en el gestor de secretos, desactive
`PRORA_AUTO_CREATE_TABLES` y ejecute `alembic upgrade head`.

## Flujo operativo

1. Cree el primer operador explícitamente con
   `python -m app.cli create-operator --email ... --role admin --full-name ...`.
2. Encole DIVIPOLA con `POST /api/v1/sources/dane-divipola/sync`. El endpoint
   responde `202`; el worker descarga por IDs y calcula marcadores WGS84.
3. Encole otras fuentes verificadas con cuerpo opcional, por ejemplo
   `{"mode":"backfill","from_date":"2018-01-01","to_date":"2019-01-01"}`.
4. Descargue una plantilla con
   `GET /api/v1/sources/templates/{dataset_type}`.
5. Cargue un CSV oficial y agregado con
   `POST /api/v1/sources/{source_id}/upload` usando multipart
   `dataset_type` + `file`. Requiere rol `analyst` o `admin`.
6. Ejecute `python -m app.jobs.worker`; verifica checksum, crea snapshot y
   manifiesto inmutables, valida esquema/DIVIPOLA/rangos y persiste cuarentena.
   En modo continuo también evalúa cada cinco minutos los `refresh_cron` y
   encola solo fuentes vencidas que no tengan otra ejecución activa.
7. Revise `GET /api/v1/sources/inventory`, `/sources/runs` y
   `/sources/runs/{run_id}/manifest` para ver almacenamiento, corte y linaje.
8. Solicite `POST /api/v1/models/train` para una enfermedad y horizontes 3/4.
9. Consulte `/api/v1/risk/map`, el histórico, la explicación, alertas y
   metadatos de versión. El agente `/api/v1/agent/query` funciona aun sin una
   llave de proveedor externo.

Tipos de plantilla: `epidemiology`, `climate`, `vaccination`,
`deforestation` y `socioeconomic`. El esquema bloquea columnas adicionales para
evitar que entren datos de paciente por error.

Los snapshots viven en `PRORA_RAW_SNAPSHOT_DIR` (`/app/data/raw` en Compose) y
el volumen `raw-snapshots` es persistente. Inclúyalo en backups junto con la
base y los modelos. No elimine snapshots referenciados por ejecuciones, modelos
o auditorías; la retención concreta debe aprobarla la entidad operadora.

## Procesos

```powershell
# API
uvicorn app.main:app --reload --port 8000

# Worker de ingesta y modelos
python -m app.jobs.worker

# Una sola iteración para operación/CI
python -m app.jobs.worker --once
```

## Pruebas

```powershell
pytest
ruff check app tests alembic scripts
alembic upgrade head
```
