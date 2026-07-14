# Despliegue en GitHub (Pages + Actions)

## Enlaces de este repositorio

| Recurso | URL |
| --- | --- |
| Código | https://github.com/HCHAPS404/Proyecto-PRORA |
| GitHub Pages (frontend) | https://hchaps404.github.io/Proyecto-PRORA/ |
| Imagen backend (GHCR) | https://github.com/HCHAPS404/Proyecto-PRORA/pkgs/container/proyecto-prora-api |
| Actions | https://github.com/HCHAPS404/Proyecto-PRORA/actions |
| Issues | https://github.com/HCHAPS404/Proyecto-PRORA/issues |

Tras el primer push a `main`, active Pages si aún no está activo:

1. **Settings → Pages**
2. **Source:** GitHub Actions
3. Espere el workflow **Publicar frontend en GitHub Pages**
4. Abra https://hchaps404.github.io/Proyecto-PRORA/

La app usa rutas hash (`#/panorama`, `#/fuentes`, …), compatibles con Pages sin `404.html` especial.

## Qué puede y no puede hacer GitHub Pages

| Componente | ¿En GitHub? | Dónde |
| --- | --- | --- |
| Frontend React (Vite) | Sí | **Pages** (`pages.yml`) |
| Landing, dashboard, mapas (UI) | Sí | Pages |
| Imagen Docker API/worker | Sí | **GHCR** (`backend-ghcr.yml`) |
| FastAPI / worker en ejecución | No en Pages | **Render** (`render.yaml`) u otro host que use la imagen GHCR |
| Entrenamiento ML / alertas | No en Pages | Worker + API desplegados |

Sin API pública, Pages sirve la plataforma en **modo invitado**. Para demo funcional completa: publique la imagen, despliegue Render (o VPS) y defina `PRORA_API_BASE_URL`. Guía: [backend-deploy.md](backend-deploy.md).

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

## Backend integrado en el mismo GitHub

1. **Actions → Publicar backend en GHCR** (automático en push a `main` con cambios en `backend/`)
2. **Render → New → Blueprint** con este repo (`render.yaml`)
3. Migrar: `./docker-entrypoint.sh migrate` en el shell del servicio
4. Variable `PRORA_API_BASE_URL` + republicar Pages

Detalle: [backend-deploy.md](backend-deploy.md).

Alternativa VPS con imagen de GitHub:

```powershell
docker compose -f docker-compose.yml -f docker-compose.prod.yml -f docker-compose.ghcr.yml up -d
```

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
| Backend GHCR | `.github/workflows/backend-ghcr.yml` | publica imagen API/worker en GitHub Packages |
| Operación (checklist) | `.github/workflows/operational-checklist.yml` | recordatorio semanal / dispatch de pasos operativos |

## Checklist rápido post-push

- [ ] Pages Source = GitHub Actions
- [ ] Workflow Pages en verde
- [ ] Workflow backend-ghcr en verde (paquete en Packages)
- [ ] Abrir https://hchaps404.github.io/Proyecto-PRORA/#/inicio
- [ ] Render Blueprint (o VPS) + `PRORA_API_BASE_URL` + CORS
- [ ] (Operativo) Datos SIVIGILA &lt; 35 días + bootstrap + re-build Pages
