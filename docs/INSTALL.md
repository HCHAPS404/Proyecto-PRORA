# Instalación de PRORA

Instrucciones para dejar el sistema corriendo en un PC Windows. Linux/macOS
es análogo cambiando la activación del venv.

## 1. Preparar el entorno

```powershell
git clone https://github.com/HCHAPS404/Proyecto-PRORA.git
cd Proyecto-PRORA
```

Compruebe versiones:

```powershell
node -v          # 22+
python --version # 3.11 o 3.12
git --version
```

Active pnpm:

```powershell
corepack enable
corepack prepare pnpm@9.15.4 --activate
```

## 2. Dependencias del frontend

Desde la raíz del repo:

```powershell
pnpm install --frozen-lockfile
```

Si falla el lockfile, revise que la versión de pnpm sea 9.x.

## 3. Dependencias del backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev,ml]"
```

Extras opcionales:

| Extra | Para qué |
| --- | --- |
| `lstm` | modelo secuencial PyTorch |
| `explainability` | SHAP en explicaciones locales |
| `dev` | pytest y ruff (ya incluido arriba) |

Ejemplo completo:

```powershell
pip install -e ".[dev,ml,lstm,explainability]"
```

## 4. Variables de entorno (opcional en local)

Para desarrollo con SQLite no hace falta `.env` en la raíz. Si usa Docker o
quiere fijar CORS/JWT:

```powershell
cd ..
Copy-Item .env.example .env
```

Valores útiles en local:

```env
PRORA_ENVIRONMENT=development
VITE_API_BASE_URL=http://127.0.0.1:8000/api/v1
PRORA_CORS_ORIGINS=["http://127.0.0.1:5173","http://localhost:5173"]
```

## 5. Arranque diario

Desde la raíz:

```powershell
npm run dev:full
```

Orden interno:

1. Comprueba `/ready` en el puerto 8000  
2. Si no hay API, la inicia con el venv de `backend`  
3. Inicia el worker (`app.jobs.worker`)  
4. Inicia Vite en 5173 con la URL de la API  

Parar: `Ctrl+C` en la terminal de Vite.

### Arranque manual (tres terminales)

Terminal A — API:

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
$env:PRORA_DATABASE_URL = "sqlite+aiosqlite:///./prora.db"
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Terminal B — worker:

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
$env:PRORA_DATABASE_URL = "sqlite+aiosqlite:///./prora.db"
python -m app.jobs.worker --poll-seconds 2
```

Terminal C — frontend:

```powershell
$env:VITE_API_BASE_URL = "http://127.0.0.1:8000/api/v1"
pnpm run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

## 6. Primer usuario operador

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
python -m app.cli create-operator --email operador@entidad.gov.co --role admin --full-name "Operador PRORA"
```

Luego inicie sesión en la UI o con:

```powershell
$body = @{ email = "operador@entidad.gov.co"; password = "SU_CLAVE" } | ConvertTo-Json
Invoke-RestMethod -Method POST -Uri http://127.0.0.1:8000/api/v1/auth/login `
  -ContentType application/json -Body $body
```

Guarde el `access_token` para sync/train.

## 7. Cargar fuentes públicas (ejemplo)

```powershell
$headers = @{ Authorization = "Bearer $TOKEN" }

Invoke-RestMethod -Method POST `
  -Uri http://127.0.0.1:8000/api/v1/sources/dane-divipola/sync `
  -Headers $headers -ContentType application/json -Body "{}"

Invoke-RestMethod -Method POST `
  -Uri http://127.0.0.1:8000/api/v1/sources/sivigila-territorial-open/sync `
  -Headers $headers -ContentType application/json -Body "{}"
```

El worker procesa la cola. Consulte corridas en `GET /api/v1/sources/runs` o en
la pantalla de fuentes de la UI.

## 8. Entrenar modelos

```powershell
foreach ($d in @("dengue","malaria","chikunguna","zika","leishmaniasis","ira")) {
  Invoke-RestMethod -Method POST `
    -Uri http://127.0.0.1:8000/api/v1/models/train `
    -Headers $headers -ContentType application/json `
    -Body (@{ disease = $d; horizons = @(3,4) } | ConvertTo-Json)
}
```

El entrenamiento es pesado (varios minutos por enfermedad). Estado:
`GET /api/v1/models/readiness/portfolio`.

## 9. Docker (alternativa a SQLite)

```powershell
Copy-Item .env.example .env
# Cambie POSTGRES_PASSWORD y PRORA_JWT_SECRET
docker compose up --build -d
docker compose ps
Invoke-RestMethod http://localhost:8000/ready
```

Migraciones: el servicio `migrate` corre antes de la API.

## 10. Problemas frecuentes

| Síntoma | Qué revisar |
| --- | --- |
| UI dice backend no disponible | API caída o `VITE_API_BASE_URL` incorrecta |
| Puerto 8000 ocupado | Cierre otro uvicorn o cambie puerto |
| `database is locked` (SQLite) | Un solo writer; no abra dos workers a la vez |
| Sync queda en pending | Worker no está corriendo |
| Pages sin datos | Pages no incluye API; use PC o configure `PRORA_API_BASE_URL` |
| Error JWT en production | `PRORA_JWT_SECRET` ≥ 32 caracteres |

## 11. Despliegue fuera del PC

- Frontend: [github-deploy.md](github-deploy.md)  
- Backend (GHCR / Render / VPS): [backend-deploy.md](backend-deploy.md)  
- Operación Compose: [deployment.md](deployment.md)
