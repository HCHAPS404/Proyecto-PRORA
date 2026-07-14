# Despliegue y operación

## Perfiles recomendados

| Entorno | Base de datos | Modelos | Exposición |
| --- | --- | --- | --- |
| Desarrollo | SQLite o PostGIS local | ML sin PyTorch si se desea rapidez | puertos 5173/8000 |
| Integración | PostGIS administrado o Compose | ensemble completo | red privada + TLS de pruebas |
| Producción | PostgreSQL/PostGIS administrado con PITR | artefactos aprobados e inmutables | balanceador/WAF + TLS |

## Despliegue local reproducible

```powershell
Copy-Item .env.example .env
# Edite .env y reemplace al menos POSTGRES_PASSWORD y PRORA_JWT_SECRET.
docker compose config --quiet
docker compose up --build -d
docker compose ps
```

Comprobaciones:

```powershell
Invoke-RestMethod http://localhost:8000/health
Invoke-RestMethod http://localhost:8000/ready
Invoke-WebRequest http://localhost:8080/healthz
```

Los servicios arrancan en este orden: PostGIS saludable, migración completada,
API saludable, worker y frontend. `docker compose logs -f api worker` permite
seguir solicitudes, ingestas y entrenamientos sin entrar al contenedor.

El archivo de ejemplo usa `development` deliberadamente para impedir que valores
locales parezcan secretos de producción. En el entorno final establezca
`PRORA_ENVIRONMENT=production`; la aplicación exigirá una llave JWT adecuada y
mantendrá la creación automática de tablas deshabilitada.

## Despliegue tipo producción (Compose)

Use la superposición `docker-compose.prod.yml` para no publicar PostgreSQL ni la
API en el host. El único puerto expuesto es el del frontend (Nginx), que hace
proxy de `/api/`, `/health` y `/ready`.

```powershell
Copy-Item .env.example .env
# En .env:
#   PRORA_ENVIRONMENT=production
#   POSTGRES_PASSWORD=<secreto fuerte>
#   PRORA_JWT_SECRET=<al menos 32 caracteres aleatorios>
#   PRORA_CORS_ORIGINS=["https://su-dominio.example"]
# Opcional si el host tiene poca RAM/disco:
#   PRORA_BACKEND_EXTRAS=ml

docker compose -f docker-compose.yml -f docker-compose.prod.yml config --quiet
docker compose -f docker-compose.yml -f docker-compose.prod.yml up --build -d
```

Comprobaciones (solo puerto web):

```powershell
Invoke-WebRequest http://localhost:8080/healthz
Invoke-RestMethod http://localhost:8080/ready
Invoke-RestMethod http://localhost:8080/health
```

Termine TLS en un balanceador/ingress delante del puerto web. No monte `.env`
desde el repositorio en el entorno final; inyecte secretos con el gestor del
operador.

## Variables relevantes

| Variable | Uso | Producción |
| --- | --- | --- |
| `PRORA_DATABASE_URL` | DSN SQLAlchemy async | secreto administrado; TLS obligatorio |
| `PRORA_JWT_SECRET` | firma de tokens | aleatorio, mínimo 32 caracteres, rotación planificada |
| `PRORA_CORS_ORIGINS` | orígenes web permitidos | lista exacta, sin comodines |
| `PRORA_SOCRATA_APP_TOKEN` | cuota identificada de datos.gov.co | secreto opcional |
| `PRORA_OPENAI_API_KEY` | respuestas generativas del agente | opcional; no enviar datos personales |
| `PRORA_MODEL_REGISTRY_PATH` | artefactos versionados | volumen u objeto inmutable |
| `PRORA_INSTITUTIONAL_UPLOAD_DIR` | bandeja temporal autorizada | cifrada, acceso restringido y vaciado controlado |

`VITE_API_BASE_URL` se resuelve en compilación. La imagen oficial usa `/api/v1`
y Nginx hace proxy a la API, por lo que un cambio exige reconstruir el frontend.

## Preparación de producción

1. Use un gestor de secretos; no monte `.env` desde el repositorio.
2. Termine TLS en un balanceador o ingress y restrinja API, base y paneles a las
   redes necesarias. No publique el puerto de PostgreSQL.
3. Ejecute `alembic upgrade head` como job único con la misma versión de imagen.
4. Mantenga réplicas de API sin estado. Ejecute un solo consumidor por trabajo o
   use bloqueo/cola distribuida antes de escalar workers.
5. Mueva artefactos y archivos institucionales a almacenamiento cifrado con
   versionado. Verifique checksum al promover modelos.
6. Configure logs JSON, métricas, trazas, alertas y un identificador de solicitud
   de extremo a extremo. Redacte tokens, correos y cuerpos sensibles.
7. Aplique límites de CPU/memoria; los entrenamientos LSTM deben ejecutarse en
   nodos separados de inferencia.
8. Ejecute pruebas de carga, restauración, escaneo de dependencias, DAST y revisión
   de autorización antes de recibir usuarios reales.

## GitHub Pages: alcance correcto

Guía detallada y URLs del repo: [github-deploy.md](github-deploy.md).

Sitio esperado para este proyecto:

- https://hchaps404.github.io/Proyecto-PRORA/
- https://hchaps404.github.io/Proyecto-PRORA/#/inicio

El workflow `.github/workflows/pages.yml` publica el frontend estático. En la
configuración del repositorio defina la variable `PRORA_API_BASE_URL` con la URL
HTTPS pública del backend, por ejemplo `https://api.example.gov.co/api/v1`.
El build configura automáticamente la ruta base `/<repositorio>/`; con dominio
propio puede establecer `PRORA_PAGES_BASE_PATH=/`.

GitHub Pages **no ejecuta FastAPI, workers, PostgreSQL ni entrenamientos**, y el
navegador no puede escribir usuarios o reportes dentro del repositorio. Sin API,
PRORA mantiene el modo invitado y sus preferencias locales en ese navegador;
cuentas compartidas, alertas, ingestas, modelos y reportes persistentes requieren
desplegar `api`, `worker` y PostgreSQL/PostGIS en infraestructura separada. No use
GitHub ni `localStorage` como base de datos epidemiológica.

Checklist operativo semanal: `.github/workflows/operational-checklist.yml` y
`scripts/operational-bootstrap.ps1`.

## Backfill y promoción de modelos

1. Cargue DIVIPOLA y registre fuentes con su licencia, fecha y responsable.
2. Ingrese los archivos autorizados desde 2018 o el periodo aprobado.
3. Revise reportes de calidad y cuarentena; no entrene con lotes rechazados.
4. Solicite entrenamiento por enfermedad y espere al worker.
5. Compare contra baseline estacional y último modelo aprobado usando ventanas
   temporales y regiones no vistas.
6. Una persona responsable de epidemiología aprueba umbrales y promoción.
7. Habilite inferencia y alertas progresivamente; monitoree deriva y falsos
   positivos. Conserve reversión a la versión anterior.

## Copias y recuperación

- Base: copias cifradas, recuperación a un punto en el tiempo y prueba mensual de
  restauración en un entorno aislado.
- Modelos: manifiesto, configuración, métricas, checksum y datos de referencia;
  nunca sobrescribir una versión publicada.
- Archivos de fuente: conservar según convenio y política institucional. Separar
  original, cuarentena y dato canónico.
- Objetivos iniciales de RPO/RTO deben acordarse con el operador; el repositorio
  no impone cifras sin conocer infraestructura ni criticidad contractual.

## Actualización y reversión

```powershell
docker compose build --pull
docker compose run --rm migrate
docker compose up -d --no-deps api worker frontend
```

Antes de migrar, revise si el cambio es compatible hacia atrás. Para revertir,
despliegue la etiqueta de imagen previa; no ejecute `alembic downgrade` en
producción sin un plan validado y copia reciente.

## Diagnóstico

- `db` no saludable: revise credenciales, volumen y espacio.
- `migrate` falla: consulte `docker compose logs migrate`; la API no arrancará,
  evitando operar con un esquema incompatible.
- `api` no lista: valide `/ready`, conectividad a PostGIS y variables Pydantic.
- `worker` reinicia: revise disponibilidad de artefactos, memoria científica y
  estado del job; el entrenamiento no debe bloquear la API.
- fuente en `requires_configuration`: proporcione el archivo o acceso oficial;
  no cambie el conector a un dataset regional solo para eliminar la advertencia.
