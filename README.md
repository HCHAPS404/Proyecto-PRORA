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

## GitHub (Pages + Actions)

| Recurso | Enlace |
| --- | --- |
| Repositorio | https://github.com/HCHAPS404/Proyecto-PRORA |
| Sitio (GitHub Pages) | https://hchaps404.github.io/Proyecto-PRORA/ |
| Inicio | https://hchaps404.github.io/Proyecto-PRORA/#/inicio |
| Panorama | https://hchaps404.github.io/Proyecto-PRORA/#/panorama |
| Imagen backend (GHCR) | https://github.com/HCHAPS404/Proyecto-PRORA/pkgs/container/proyecto-prora-api |
| Actions | https://github.com/HCHAPS404/Proyecto-PRORA/actions |

### Qué muestra el enlace de GitHub Pages

El enlace de Pages es la **vitrina del frontend** (UI, navegación, paneles).  
**No** es un despliegue full-stack: GitHub Pages no ejecuta FastAPI, worker ni base de datos.

| Escenario | Qué obtener |
| --- | --- |
| Solo ver la interfaz | Abrir el sitio Pages |
| Demo funcional completa (datos, mapa, predicciones) | API + worker en PC (o Render) y conectar Pages con `PRORA_API_BASE_URL` |
| Desarrollo / defensa en máquina local | Seguir la sección **Arranque local** abajo |

Guías:
- Frontend en GitHub: [docs/github-deploy.md](docs/github-deploy.md)
- Backend (PC, GHCR, Render): [docs/backend-deploy.md](docs/backend-deploy.md)

Sin `PRORA_API_BASE_URL` el sitio queda en modo invitado. Con esa variable (y CORS)
apunta a su API HTTPS.

Para activar **alerta temprana operativa** (mapa/alertas vigentes) se requiere
SIVIGILA municipal reciente (≤35 días) y `scripts/operational-bootstrap.ps1`.
Los datos públicos actuales no cubren un SIVIGILA nacional 2025–2026 completo; el
portfolio puede permanecer en `research_only` hasta un corte autorizado reciente.

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

## Demo completa en PC (recomendado para probar que todo funciona)

GitHub Pages **no** sustituye este paso. En su máquina arranca API + worker + UI:

```powershell
# Primera vez (dependencias)
corepack enable
pnpm install --frozen-lockfile
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev,ml]"
cd ..

# Cada vez que quiera la demo funcional (desde la raíz del repo)
npm run dev:full
```

La API usa por defecto SQLite en `backend/prora.db` (cwd del proceso backend).
Si define `PRORA_DATABASE_URL`, hágalo relativo a `backend/` o con ruta absoluta.

Abra:

| Servicio | URL |
| --- | --- |
| Frontend | http://127.0.0.1:5173/ |
| API (docs) | http://127.0.0.1:8000/docs |
| Salud | http://127.0.0.1:8000/ready |

`npm run dev:full` (`scripts/dev.ps1`) inicia o reutiliza la API en `:8000`,
levanta el **worker** (sync/train) y Vite con `VITE_API_BASE_URL` apuntando a
esa API. Al cerrar Vite intenta detener lo que arrancó.

Alternativa equivalente:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\local-demo.ps1
```

El modo SQLite facilita desarrollo y pruebas; producción usa PostgreSQL/PostGIS
y Alembic. Para LSTM: `.[lstm]`; para SHAP: `.[explainability]`.

### Modelos de predicción en local

Las 6 enfermedades priorizadas tienen champions **h3 y h4** entrenados (modo
`research_only` mientras el corte epidemiológico nacional no sea ≤ 35 días).
El mapa y la analítica usan predicción retrospectiva de investigación cuando
no hay señal operativa.

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
- La federación `sivigila-territorial-open` suma publicaciones abiertas
  (Boyacá, Caquetá, Pereira, Tuluá, Bucaramanga multi-evento/IRA, Casanare,
  Santa Rosa de Cabal) con series tipicamente 2015–2025. También se integran
  IRCA (`nxt2-39c3`) y PAI Valle (`uw8e-gzpp`) como factores. Extiende
  trazabilidad local sin declarar cobertura nacional operativa 2026.
- Backend en el mismo GitHub: imagen Docker en **GHCR**
  (workflow `backend-ghcr.yml`) + Blueprint **Render** (`render.yaml`)
  conectado a Pages vía `PRORA_API_BASE_URL`. Guía:
  [docs/backend-deploy.md](docs/backend-deploy.md).
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
- [GitHub Pages](docs/github-deploy.md)
- [Backend público + Pages](docs/backend-deploy.md)
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
