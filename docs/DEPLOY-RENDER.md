# Guía paso a paso: GitHub Pages + Render (gratis)

Tras hacer **commit y push a `main`**, sigue solo esta guía. El repo ya trae
`render.yaml`, migraciones automáticas y **jobs inline** (`PRORA_JOBS_INLINE=true`)
para sync/train sin worker de pago.

```text
Tú haces push → GitHub Actions publica Pages + imagen
Tú conectas Render (Blueprint) → API + Postgres free
Tú pegas la URL en GitHub → republicas Pages → listo
```

---

## Parte 0 — Lo que ya hace el push a `main`

| Workflow | Qué publica |
| --- | --- |
| **Publicar frontend en GitHub Pages** | UI en `https://hchaps404.github.io/Proyecto-PRORA/` |
| **Publicar backend en GitHub Container Registry** | Imagen (opcional; Render construye desde el Dockerfile) |

Sin variable `PRORA_API_BASE_URL`, Pages queda en **modo invitado** (normal hasta
conectar Render).

Comprueba antes de seguir:

1. Repo en GitHub: https://github.com/HCHAPS404/Proyecto-PRORA  
2. **Settings → Pages → Source = GitHub Actions**  
3. Actions en verde (al menos el de Pages)

---

## Parte 1 — Crear cuenta y Blueprint en Render

1. Entra en [https://dashboard.render.com/](https://dashboard.render.com/)  
2. Regístrate / inicia sesión (puedes usar **Sign in with GitHub**).  
3. Si pide crear un **Workspace**, usa el plan free / Hobby.  
4. Pulsa **New +** → **Blueprint**.  
5. Conecta el repositorio **`HCHAPS404/Proyecto-PRORA`**  
   - Si no aparece: **Configure account** / autoriza Render en GitHub y concede
     acceso a ese repo.  
6. Render lee `render.yaml` en la raíz. Debe mostrar algo como:
   - Database: `prora-db` (free)  
   - Web service: `prora-api` (free)  
7. Pulsa **Apply** / **Create resources** y espera el primer deploy (varios minutos).

### Qué crea el Blueprint (ya configurado)

| Recurso | Plan | Rol |
| --- | --- | --- |
| `prora-db` | free | Postgres (caduca a los **30 días** en free) |
| `prora-api` | free | FastAPI + migraciones + jobs inline (sync/train) |

Variables ya definidas en el YAML:

- `PRORA_ENVIRONMENT=production`  
- `PRORA_RUN_MIGRATIONS_ON_START=true`  
- `PRORA_JOBS_INLINE=true` (sync/train en BackgroundTasks de la API)  
- `PRORA_EMBEDDED_WORKER=false` (evita tumbar el health check en free)  
- `PRORA_CORS_ORIGINS=["https://hchaps404.github.io"]`  
- `PRORA_JWT_SECRET` generado por Render  
- `PRORA_DATABASE_URL` enlazada a `prora-db`  
- `PRORA_BOOTSTRAP_ADMIN_EMAIL` / `_PASSWORD` (operador inicial; **cámbialo** tras el primer login)

**No** hace falta ejecutar `./docker-entrypoint.sh migrate` a mano.

---

## Parte 2 — Operador admin

El Blueprint crea/rota el operador al arrancar con:

| Key | Valor en blueprint |
| --- | --- |
| `PRORA_BOOTSTRAP_ADMIN_EMAIL` | `helmut.chs@gmail.com` |
| `PRORA_BOOTSTRAP_ADMIN_PASSWORD` | `ProraOps2026Secure!` |

Tras el primer deploy, inicia sesión en la UI o:

```bash
curl -X POST https://prora-api.onrender.com/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"helmut.chs@gmail.com","password":"ProraOps2026Secure!"}'
```

**Cambia la contraseña** en Render → Environment y redespliega (el bootstrap
rota el hash si usas `--promote-existing`, que ya hace el entrypoint).

También puedes crear otro operador con Shell:

```bash
python -m app.cli create-operator \
  --email tu-correo@ejemplo.com \
  --role admin \
  --full-name "Operador PRORA" \
  --promote-existing
```

---

## Parte 3 — Comprobar que la API está viva

1. En Render → **`prora-api`** → copia la URL pública  
   (ej. `https://prora-api.onrender.com`).  
2. Abre en el navegador:

```text
https://TU-URL.onrender.com/ready
```

Respuesta esperada:

```json
{"status":"ready","database":"up"}
```

La **primera** petición tras inactividad puede tardar 30–60 s (el free se duerme).

También: `https://TU-URL.onrender.com/docs` (OpenAPI).

---

## Parte 4 — Conectar GitHub Pages al backend

1. GitHub → repo **Proyecto-PRORA** → **Settings**  
2. **Secrets and variables** → **Actions** → pestaña **Variables**  
3. **New repository variable**:

| Name | Value |
| --- | --- |
| `PRORA_API_BASE_URL` | `https://TU-URL.onrender.com/api/v1` |

Importante: debe terminar en `/api/v1`.

4. (Opcional) Si el repo no se llama `Proyecto-PRORA`:

| Name | Value |
| --- | --- |
| `PRORA_PAGES_BASE_PATH` | `/Proyecto-PRORA/` |

5. **Actions** → workflow **Publicar frontend en GitHub Pages** → **Run workflow**  
6. Cuando termine, abre:

```text
https://hchaps404.github.io/Proyecto-PRORA/
```

---

## Parte 5 — Datos 2024–2026, sync y train

### Realidad de cobertura

| Fuente | Hasta | Rol |
| --- | --- | --- |
| `sivigila-microdata-2024` | 2024 nacional municipio/semana | Base histórica para entrenar |
| Federación territorial | 2024–2025 (parcial) | Extiende series recientes |
| `ins-bes-weekly` | ~1–2 semanas de rezago | Contexto nacional/dept, no municipio |
| IDEAM / PAI / IRCA | 2024–2026 según fuente | Covariables / correlaciones |
| `sivigila-microdata-2025` | **aún no publicado** (404) | Queda catalogado como pendiente |
| `sivigila-current-authorized` | CSV institucional | Upload canónico 2025+ |

Sin corte municipal ≤35 días el portfolio queda en **modo investigación**
(`research_only`): predicciones y factores del modelo sí se muestran; no se
deben leer como alerta operativa del día.

### Sync + train remoto

```bash
export PRORA_API_BASE=https://prora-api.onrender.com/api/v1
export PRORA_OPERATOR_EMAIL=helmut.chs@gmail.com
export PRORA_OPERATOR_PASSWORD='ProraOps2026Secure!'
python backend/scripts/remote_sync_and_train.py
```

O desde la UI (**Fuentes y datos** → sync) y luego train vía API:

```bash
curl -X POST "$PRORA_API_BASE/models/train" \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"disease":"dengue","horizons":[3,4]}'
```

### Upload INS 2025+ (cuando tengas el CSV)

1. Descarga plantilla: `GET /api/v1/sources/templates/epidemiology`  
2. Columnas: `municipality_code,disease,week_start,cases[,population,is_preliminary,quality_score]`  
3. `POST /api/v1/sources/sivigila-current-authorized/upload` (multipart, rol analyst/admin)  
4. Con `PRORA_JOBS_INLINE=true` el upload se procesa en la misma API  
5. Re-entrena dengue (y otros eventos) para pasar a elegibilidad operativa si el corte ≤35 días

---

## Parte 6 — Checklist rápido

- [ ] Push a `main` hecho  
- [ ] Pages Source = GitHub Actions  
- [ ] Blueprint Render aplicado (`prora-db` + `prora-api`)  
- [ ] `/ready` responde `database: up`  
- [ ] Variable `PRORA_API_BASE_URL` en GitHub  
- [ ] Workflow de Pages vuelto a ejecutar  
- [ ] Login operador + sync/train ejecutados  
- [ ] UI muestra mapa, KPIs y (si hay modelo) predicción en modo investigación

---

## Límites honestos del plan free

| Tema | Qué esperar |
| --- | --- |
| Cold start | ~30–60 s la primera vez tras dormir |
| Postgres free | Caduca a los **30 días** |
| Disco | Efímero: modelos/snapshots se pierden al redeploy |
| Worker aparte | No existe en free → **jobs inline** |
| Syncs colgados | Al arrancar se limpian runs PENDING/RUNNING >30 min |
| RAM | Imagen con extras `ml` |

Para demos: abre `/ready` un minuto antes de mostrar la UI.

---

## Si algo falla

| Síntoma | Qué mirar |
| --- | --- |
| Blueprint rechaza el worker | Este repo **no** define worker de pago |
| Deploy API falla por DB/SSL | Logs: SSL hacia Postgres (asyncpg) |
| CORS en el navegador | `PRORA_CORS_ORIGINS=["https://hchaps404.github.io"]` |
| Pages sin datos | Falta `PRORA_API_BASE_URL` o no republicaste Pages |
| `/ready` timeout | Wake-up del free o logs de `prora-api` |
| `source_sync_already_queued` | Espera o reinicia API (limpia stuck) |
| Upload sin procesar | Debe estar `PRORA_JOBS_INLINE=true` |
| Postgres expirado | Nueva DB free o Neon/Supabase + `PRORA_DATABASE_URL` |

Más detalle técnico: [backend-deploy.md](backend-deploy.md) · [github-deploy.md](github-deploy.md) · [backend/docs/data-sources.md](../backend/docs/data-sources.md).
