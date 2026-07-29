# Backend integrado con GitHub (GHCR + Pages + Render)

GitHub Pages **no ejecuta** FastAPI. La integración en el mismo repo es:

```text
GitHub repo
├─ Actions → Pages          → https://hchaps404.github.io/Proyecto-PRORA/
├─ Actions → GHCR           → ghcr.io/hchaps404/proyecto-prora-api
└─ Render Blueprint         → API free + Postgres free (+ worker embebido)
         └─ variable PRORA_API_BASE_URL une Pages ↔ API
```

**Guía corta para conectar Render ahora:** [DEPLOY-RENDER.md](DEPLOY-RENDER.md).

| Pieza | Dónde vive en GitHub | Resultado |
| --- | --- | --- |
| Frontend | workflow `pages.yml` | GitHub Pages |
| Imagen API/worker | workflow `backend-ghcr.yml` | [GHCR Packages](https://github.com/HCHAPS404/Proyecto-PRORA/pkgs/container/proyecto-prora-api) |
| Hosting runtime | `render.yaml` (Blueprint) | URL pública HTTPS |

## Paso 1 — Publicar imagen en GitHub (automático)

En cada push a `main` que toque `backend/**`, Actions ejecuta
**Publicar backend en GitHub Container Registry**.

También: Actions → ese workflow → **Run workflow**.

Paquete esperado:

```text
ghcr.io/hchaps404/proyecto-prora-api:latest
```

Si el paquete queda privado: **Packages → package settings → Change visibility → Public**
(necesario si otro host descarga la imagen sin token). Render Blueprint
**construye desde el Dockerfile** del repo; no depende de GHCR.

## Paso 2 — Desplegar API (Render Blueprint)

Detalle clic a clic: [DEPLOY-RENDER.md](DEPLOY-RENDER.md).

Resumen:

1. [Render Dashboard](https://dashboard.render.com/) → **New → Blueprint**
2. Conecte el repo `HCHAPS404/Proyecto-PRORA`
3. Render lee `render.yaml` y crea:
   - Postgres `prora-db` (free, caduca a 30 días)
   - Web `prora-api` (free: API + migraciones al arrancar + worker embebido)
4. No hace falta Shell para migrar (`PRORA_RUN_MIGRATIONS_ON_START=true`).
5. Copie la URL del servicio (ej. `https://prora-api.onrender.com`) y abra `/ready`.

Variables del blueprint: `PRORA_ENVIRONMENT=production`, CORS de Pages, JWT
generado, DB enlazada, worker embebido. Opcional en Dashboard:
`PRORA_BOOTSTRAP_ADMIN_*`, `PRORA_SOCRATA_APP_TOKEN`.

> **Nota:** Render no permite background workers en plan free. Por eso el
> worker corre dentro del mismo servicio web.

## Paso 3 — Conectar Pages al backend

En GitHub → **Settings → Secrets and variables → Actions → Variables**:

| Variable | Valor |
| --- | --- |
| `PRORA_API_BASE_URL` | `https://prora-api.onrender.com/api/v1` |

Luego: Actions → **Publicar frontend en GitHub Pages** → Run workflow.

Compruebe:

- UI: https://hchaps404.github.io/Proyecto-PRORA/#/panorama  
- API: `https://…onrender.com/ready` → `{"status":"ready",…}`

## Alternativa: VPS con imagen de GitHub

```powershell
docker login ghcr.io -u HCHAPS404
# token con read:packages si el paquete es privado

$env:PRORA_GHCR_IMAGE = "ghcr.io/hchaps404/proyecto-prora-api:latest"
docker compose `
  -f docker-compose.yml `
  -f docker-compose.prod.yml `
  -f docker-compose.ghcr.yml `
  up -d
```

## Activación de datos (después del deploy)

```powershell
$api = "https://SU-API.onrender.com"
# login operador → $token
$headers = @{ Authorization = "Bearer $token" }
Invoke-RestMethod -Method POST -Uri "$api/api/v1/sources/sivigila-territorial-open/sync" -Headers $headers -ContentType "application/json" -Body "{}"
.\scripts\operational-bootstrap.ps1 -ApiBase $api -Token $token -ForceTrain
```

## Limitaciones honestas (demo)

- Plan free de Render duerme el servicio; la primera petición puede tardar ~30–60 s.
- Postgres free caduca a los 30 días.
- Disco efímero: artefactos ML/snapshots se pierden al redeploy.
- Sin SIVIGILA municipal &lt; 35 días el sistema permanece en `research_only` (correcto).

## Checklist

- [ ] Push a `main` / workflow Pages en verde  
- [ ] Blueprint Render desplegado (`prora-api` + `prora-db`)  
- [ ] `/ready` responde en HTTPS  
- [ ] Variable `PRORA_API_BASE_URL` en GitHub  
- [ ] Pages republicado y Panorama deja de mostrar “backend no disponible”
