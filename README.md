# PRORA

PRORA es una plataforma full stack de alerta temprana para apoyar la vigilancia
de dengue, malaria, chikunguña, Zika, leishmaniasis e infecciones respiratorias
agudas (IRA) en Colombia. Integra datos municipales agregados, pronósticos a
3–4 semanas, explicabilidad, alertas, autenticación y un asistente analítico.

> PRORA es una herramienta de apoyo epidemiológico. No diagnostica, no sustituye
> al INS ni a las autoridades territoriales y no debe recibir datos clínicos
> individualizados. Una predicción solo puede considerarse operativa después de
> validación temporal, territorial y epidemiológica con datos autorizados.

## Componentes

- **Frontend:** React 18, TypeScript y Vite; dashboard, mapas, análisis histórico,
  predicciones, alertas, configuración, ayuda y agente PRORA.
- **API:** FastAPI asíncrona con OpenAPI, JWT de acceso/renovación, preferencias,
  fuentes, riesgo, modelos, alertas y suscripciones.
- **Datos:** PostgreSQL/PostGIS, contratos canónicos, trazabilidad, calidad y
  conectores para fuentes públicas o archivos institucionales.
- **Modelos:** ingeniería de rezagos, validación temporal y territorial, Random
  Forest, HistGradientBoosting, modelo secuencial LSTM cuando PyTorch está
  instalado y stacking; el candidato con mejor MAE fuera de muestra se registra
  como predictor de la versión, con intervalos, benchmark y explicabilidad.
- **Operación:** migraciones Alembic, worker desacoplado, contenedores,
  comprobaciones de salud, snapshots inmutables y proxy Nginx.

La arquitectura completa está en [docs/architecture.md](docs/architecture.md).

## Inicio rápido con Docker

Requisitos: Docker Engine con Compose v2 y, para la imagen completa, espacio
suficiente para las dependencias científicas y PyTorch.

```powershell
Copy-Item .env.example .env
# Cambie POSTGRES_PASSWORD y PRORA_JWT_SECRET antes de exponer el servicio.
docker compose up --build
```

Para un despliegue más cercano a producción (sin exponer PostgreSQL ni la API;
solo Nginx en el puerto web, con proxy de `/api/`):

```powershell
# En .env: PRORA_ENVIRONMENT=production y secretos reales.
docker compose -f docker-compose.yml -f docker-compose.prod.yml up --build -d
```

Servicios:

- Aplicación: `http://localhost:8080`
- API: `http://localhost:8000/api/v1`
- OpenAPI: `http://localhost:8000/docs`
- Salud: `http://localhost:8000/health`

Detener sin borrar los datos:

```powershell
docker compose down
```

Para borrar también volúmenes locales, use `docker compose down --volumes` solo
cuando haya confirmado que no necesita la base, archivos institucionales ni
snapshots crudos o artefactos de modelos.

## Desarrollo local

Para iniciar frontend y API juntos, comprobar que la base responde y cerrar la
API al finalizar Vite:

```powershell
npm run dev:full
```

Este comando evita dejar el frontend apuntando a una API apagada. Reutiliza una
API que ya esté lista en el puerto 8000 y falla de forma explícita si la API o
el puerto web no pueden iniciarse.

Frontend:

```powershell
corepack enable
pnpm install --frozen-lockfile
pnpm run dev
```

Backend (Python 3.11 o superior):

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev,ml]"
$env:PRORA_DATABASE_URL = "sqlite+aiosqlite:///./prora.db"
uvicorn app.main:app --reload --port 8000
```

El modo SQLite facilita desarrollo y pruebas, pero producción usa PostgreSQL con
PostGIS y migraciones Alembic. Para entrenar el modelo secuencial instale además
`.[lstm]`; para SHAP, `.[explainability]`.

## Verificación

```powershell
pnpm run lint
pnpm run build
cd backend
ruff check app tests
pytest
alembic upgrade head
```

También puede validar la composición sin iniciar servicios:

```powershell
docker compose --env-file .env.example config --quiet
```

## Fuentes y credenciales

El repositorio no incluye secretos ni datos epidemiológicos restringidos. Los
conectores públicos verificados se documentan en
[backend/docs/data-sources.md](backend/docs/data-sources.md). En particular:

- IDEAM (precipitación, temperatura, humedad y estaciones), DIVIPOLA 2025 y
  CNPV 2018 se consumen desde servicios públicos verificados y paginados.
- SIVIGILA `4hyg-wa9d` aporta agregados municipio/semana 2007–2022; PRORA usa
  2018–2022 como historia no actual. El conector público de microdatos 2024
  descarga XLSX por evento, calcula su huella, agrega de inmediato por
  municipio/semana y elimina el archivo temporal: nunca persiste filas nominales.
- El Boletín Epidemiológico Semanal (BES) se ingiere como referencia reciente
  departamental/distrital/nacional separada. No se convierte en casos municipales
  ni se usa para fabricar una capa operativa donde no existe una serie tabular.
- PAI incluye la tabla departamental pública 2019–2022 y ZIP municipales
  oficiales 1998–2025 y 2026, con SHA-256 y adaptador XLSX versionado.
- Deforestación sigue bloqueada hasta aprobar el contrato geoespacial y unidad.

Copie `.env.example` a `.env` y proporcione solamente las credenciales necesarias.
El agente funciona sin proveedor externo; `PRORA_OPENAI_API_KEY` es opcional.

Los archivos oficiales o institucionales se cargan sin datos personales desde
`POST /api/v1/sources/{source_id}/upload`. Antes puede descargar la plantilla
canónica en `GET /api/v1/sources/templates/{dataset_type}`. La API encola la
ingesta; el worker recalcula el checksum, archiva el original con manifiesto,
valida esquema, DIVIPOLA y rangos, y persiste cuarentena. El inventario público
`GET /api/v1/sources/inventory` separa catálogo de almacenamiento real. Después,
un analista puede solicitar entrenamiento en
`POST /api/v1/models/train` y seguir el trabajo por su identificador.

`GET /api/v1/sources/disease-coverage` informa, por cada enfermedad priorizada,
el periodo observado, fuentes, modelos champion, pronósticos históricos,
pronósticos operativos, alertas abiertas y bloqueos. Un modelo entrenado con
un corte histórico nunca se publica como señal actual.

No existe un administrador por defecto. El primer operador se crea explícitamente:

```powershell
cd backend
python -m app.cli create-operator --email operador@entidad.gov.co --role admin --full-name "Operador PRORA"
```

## Documentación de entrega

- [Arquitectura](docs/architecture.md)
- [Despliegue y operación](docs/deployment.md)
- [Seguridad y privacidad](docs/security.md)
- [Fuentes de datos](backend/docs/data-sources.md)
- [Backend](backend/README.md)
- [Plataforma de ML](backend/app/ml/README.md)

## Estado de preparación

El software, contratos, modelos y despliegue son integrables con un entorno de
producción. La activación epidemiológica final depende de cargar series históricas
oficiales, ejecutar el backfill, entrenar por enfermedad, aprobar los umbrales con
expertos y completar pruebas de carga, recuperación y seguridad en la
infraestructura de destino.
