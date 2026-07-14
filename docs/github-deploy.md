# Despliegue en GitHub (Pages + Actions)

## Enlaces de este repositorio

| Recurso | URL |
| --- | --- |
| Código | https://github.com/HCHAPS404/Proyecto-PRORA |
| GitHub Pages (frontend) | https://hchaps404.github.io/Proyecto-PRORA/ |
| Actions | https://github.com/HCHAPS404/Proyecto-PRORA/actions |
| Issues | https://github.com/HCHAPS404/Proyecto-PRORA/issues |

Tras el primer push a `main`, active Pages si aún no está activo:

1. **Settings → Pages**
2. **Source:** GitHub Actions
3. Espere el workflow **Publicar frontend en GitHub Pages**
4. Abra https://hchaps404.github.io/Proyecto-PRORA/

La app usa rutas hash (`#/panorama`, `#/fuentes`, …), compatibles con Pages sin `404.html` especial.

## Qué puede y no puede hacer GitHub Pages

| Componente | ¿En GitHub Pages? |
| --- | --- |
| Frontend React (Vite) | Sí |
| Landing, dashboard, mapas (UI) | Sí |
| FastAPI / worker / PostGIS | **No** |
| Entrenamiento ML / alertas operativas | **No** (requiere API + worker) |

Sin API pública, Pages sirve la plataforma en **modo invitado** (preferencias locales). Para mapa, catálogo y predicciones en vivo necesita `PRORA_API_BASE_URL`.

## Variables del repositorio (obligatorias para API remota)

**Settings → Secrets and variables → Actions → Variables**

| Variable | Valor ejemplo | Uso |
| --- | --- | --- |
| `PRORA_PAGES_BASE_PATH` | `/Proyecto-PRORA/` | Base de Vite (por defecto el workflow usa el nombre del repo) |
| `PRORA_API_BASE_URL` | `https://api.su-dominio.gov.co/api/v1` | Backend HTTPS público |

Tras cambiar variables, vuelva a ejecutar el workflow **Publicar frontend en GitHub Pages** (Actions → Run workflow).

## CORS en la API

La API debe permitir el origen exacto de Pages:

```text
PRORA_CORS_ORIGINS=["https://hchaps404.github.io"]
```

Si usa dominio propio para Pages, añada también ese origen HTTPS.

## Backend (fuera de Pages)

Opciones habituales:

1. **Docker Compose en VPS** (`docker-compose.yml` + `docker-compose.prod.yml`)
2. Máquina con `scripts/operational-bootstrap.ps1` tras cargar SIVIGILA reciente
3. Cualquier host con Python 3.12 + PostgreSQL/PostGIS + worker

Flujo tipico:

```powershell
# En el servidor de API
Copy-Item .env.example .env
# Edite secretos, PRORA_ENVIRONMENT=production y CORS con Pages
docker compose -f docker-compose.yml -f docker-compose.prod.yml up --build -d

# Cuando exista archivo SIVIGILA autorizado reciente:
.\scripts\operational-bootstrap.ps1 -ApiBase http://127.0.0.1:8000
```

Luego defina `PRORA_API_BASE_URL` en GitHub y republíque Pages.

## Activación operativa (alerta temprana)

Pages **no** convierte el sistema en operativo. Para `forecast_mode=operational`:

1. Cargar SIVIGILA municipal-semanal **autorizado** con corte ≤ 35 días (`sivigila-current-authorized` o sync equivalente).
2. Verificar `GET /api/v1/models/readiness/portfolio` → `operational_forecast_eligible: true`.
3. Ejecutar `scripts/operational-bootstrap.ps1` (entrene champions h3+h4).
4. Confirmar `GET /api/v1/risk/map?disease=dengue&horizon=4&include_research=false` con municipios.
5. Apuntar Pages a esa API HTTPS.

Sin datos recientes el sistema permanece en `research_only` / `retrospective_research` (correcto epidemiológicamente).

## Workflows incluidos

| Workflow | Archivo | Función |
| --- | --- | --- |
| CI | `.github/workflows/ci.yml` | lint, build, pytest, compose config |
| Pages | `.github/workflows/pages.yml` | publica frontend en GitHub Pages |
| Operación (checklist) | `.github/workflows/operational-checklist.yml` | recordatorio semanal / dispatch de pasos operativos |

## Checklist rápido post-push

- [ ] Pages Source = GitHub Actions
- [ ] Workflow Pages en verde
- [ ] Abrir https://hchaps404.github.io/Proyecto-PRORA/#/inicio
- [ ] (Opcional) Variable `PRORA_API_BASE_URL` + CORS
- [ ] (Operativo) Datos SIVIGILA &lt; 35 días + bootstrap + re-build Pages
