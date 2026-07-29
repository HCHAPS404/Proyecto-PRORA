# Guía paso a paso: GitHub Pages + Render (gratis)

Tras hacer **commit y push a `main`**, sigue solo esta guía. El repo ya trae
`render.yaml`, migraciones automáticas y worker embebido en la API.

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
| `prora-api` | free | FastAPI + migraciones al arrancar + worker embebido |

Variables ya definidas en el YAML:

- `PRORA_ENVIRONMENT=production`  
- `PRORA_RUN_MIGRATIONS_ON_START=true` (no hace falta Shell para migrar)  
- `PRORA_EMBEDDED_WORKER=true` (ingesta/train sin worker de pago)  
- `PRORA_CORS_ORIGINS=["https://hchaps404.github.io"]`  
- `PRORA_JWT_SECRET` generado por Render  
- `PRORA_DATABASE_URL` enlazada a `prora-db`  

**No** hace falta ejecutar `./docker-entrypoint.sh migrate` a mano.

---

## Parte 2 — (Opcional) Operador admin desde el Dashboard

Para poder hacer login de operador (sync/train) sin entrar al Shell:

1. En Render → servicio **`prora-api`** → **Environment**  
2. Añade (o edita si ya aparecen como “sync: false”):

| Key | Valor ejemplo |
| --- | --- |
| `PRORA_BOOTSTRAP_ADMIN_EMAIL` | `tu-correo@ejemplo.com` |
| `PRORA_BOOTSTRAP_ADMIN_PASSWORD` | contraseña fuerte (≥ 8 chars según reglas de la API) |
| `PRORA_BOOTSTRAP_ADMIN_NAME` | `Operador PRORA` |

3. Guarda → Render redespliega.  
4. En los logs debe verse `prora: bootstrap de operador…`.

También puedes crear el operador después con Shell:

```bash
python -m app.cli create-operator \
  --email tu-correo@ejemplo.com \
  --role admin \
  --full-name "Operador PRORA"
```

(te pedirá la contraseña de forma interactiva).

---

## Parte 3 — Comprobar que la API está viva

1. En Render → **`prora-api`** → copia la URL pública  
   (ej. `https://prora-api-xxxx.onrender.com`).  
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

Importante: debe terminar en `/api/v1` (sin barra final extra rara; una sola
barra antes de `api` está bien).

4. (Opcional) Si el repo no se llama `Proyecto-PRORA`:

| Name | Value |
| --- | --- |
| `PRORA_PAGES_BASE_PATH` | `/Proyecto-PRORA/` |

5. **Actions** → workflow **Publicar frontend en GitHub Pages** → **Run workflow**  
   (o haz un push vacío a `main`).  
6. Cuando termine, abre:

```text
https://hchaps404.github.io/Proyecto-PRORA/
```

El front ya no debería quedarse solo en modo invitado: llamará a tu API en Render.

---

## Parte 5 — Checklist rápido

- [ ] Push a `main` hecho  
- [ ] Pages Source = GitHub Actions  
- [ ] Blueprint Render aplicado (`prora-db` + `prora-api`)  
- [ ] `/ready` responde `database: up`  
- [ ] Variable `PRORA_API_BASE_URL` en GitHub  
- [ ] Workflow de Pages vuelto a ejecutar  
- [ ] UI carga y puede hablar con la API (guest login / panorama)

---

## Límites honestos del plan free

| Tema | Qué esperar |
| --- | --- |
| Cold start | ~30–60 s la primera vez tras dormir |
| Postgres free | Caduca a los **30 días** (luego upgrade o nueva DB) |
| Disco | Efímero: modelos/snapshots se pierden al redeploy |
| Worker aparte | No existe en free → usamos **worker embebido** |
| RAM | Imagen con extras `ml` (sin LSTM/SHAP en Render) |

Para demos: abre `/ready` un minuto antes de mostrar la UI.

---

## Si algo falla

| Síntoma | Qué mirar |
| --- | --- |
| Blueprint rechaza el worker | Este repo ya **no** define worker de pago; solo web free |
| Deploy API falla por DB/SSL | Logs: debe verse URL con `ssl=require` (automático) |
| CORS en el navegador | `PRORA_CORS_ORIGINS` debe ser exactamente `["https://hchaps404.github.io"]` |
| Pages sin datos | Falta `PRORA_API_BASE_URL` o no republicaste Pages |
| `/ready` timeout | Espera el wake-up del free o revisa logs de `prora-api` |
| Deploy failed en `prora-api` | Abre el servicio → **Logs**. Causa frecuente: SSL mal formado hacia Postgres (corregido en main reciente). Pulsa **Manual Deploy → Deploy latest commit** |
| Postgres expirado | Crea otra DB free o migra a Neon/Supabase y pega `PRORA_DATABASE_URL` |

---

## Después (datos y modelos)

Con la API arriba y un operador:

1. Login en la UI o vía `/api/v1/auth/login`  
2. Sync de fuentes (rol analyst/admin)  
3. Train de modelos  

Scripts locales: `scripts/operational-bootstrap.ps1` apuntando a tu URL de Render.

Más detalle técnico: [backend-deploy.md](backend-deploy.md) · [github-deploy.md](github-deploy.md).
