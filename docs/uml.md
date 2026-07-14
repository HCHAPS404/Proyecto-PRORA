# Diagramas UML (Mermaid)

Vista de diseño del sistema. Los diagramas usan sintaxis Mermaid compatible
con GitHub, VS Code y la mayoría de visores Markdown.

## 1. Casos de uso

```mermaid
usecaseDiagram
  actor Operador
  actor Admin
  actor Publico as "Visitante (solo UI)"
  actor Sistema as "Worker / cron"

  package "PRORA" {
    usecase UC1 as "Consultar mapa y alertas"
    usecase UC2 as "Ver series y analítica"
    usecase UC3 as "Iniciar sesión"
    usecase UC4 as "Sincronizar fuentes"
    usecase UC5 as "Entrenar modelos"
    usecase UC6 as "Promover champion"
    usecase UC7 as "Gestionar usuarios"
    usecase UC8 as "Procesar cola de jobs"
    usecase UC9 as "Generar predicciones"
  }

  Publico --> UC1
  Publico --> UC2
  Operador --> UC3
  Operador --> UC1
  Operador --> UC2
  Operador --> UC4
  Operador --> UC5
  Admin --> UC6
  Admin --> UC7
  Admin --> UC4
  Admin --> UC5
  Sistema --> UC8
  Sistema --> UC9
  UC4 ..> UC8 : incluye
  UC5 ..> UC8 : incluye
  UC9 ..> UC1 : alimenta
```

## 2. Diagrama de clases (dominio principal)

```mermaid
classDiagram
  class Territory {
    +str divipola_code
    +str name
    +str level
    +str parent_code
  }

  class DiseaseSeriesPoint {
    +str disease
    +str territory_code
    +date week_start
    +int cases
    +float incidence_rate
  }

  class ClimateObservation {
    +str territory_code
    +date observed_on
    +float precip_mm
    +float temp_mean_c
  }

  class SourceCatalogEntry {
    +str source_id
    +str provider
    +str connector_type
    +bool enabled
  }

  class SyncRun {
    +uuid id
    +str source_id
    +str status
    +datetime started_at
    +datetime finished_at
  }

  class Job {
    +uuid id
    +str job_type
    +str status
    +json payload
  }

  class ModelRun {
    +uuid id
    +str disease
    +int horizon
    +str status
    +float mae
    +float mape
  }

  class ModelArtifact {
    +uuid id
    +uuid model_run_id
    +str path
    +str format
  }

  class ChampionModel {
    +str disease
    +int horizon
    +uuid model_run_id
    +str stage
  }

  class Prediction {
    +str disease
    +str territory_code
    +date target_week
    +float y_hat
    +float lower
    +float upper
  }

  class Alert {
    +str disease
    +str territory_code
    +str level
    +str rationale
  }

  class User {
    +str email
    +str role
    +str password_hash
  }

  Territory "1" --> "*" DiseaseSeriesPoint
  Territory "1" --> "*" ClimateObservation
  Territory "1" --> "*" Prediction
  Territory "1" --> "*" Alert
  SourceCatalogEntry "1" --> "*" SyncRun
  Job "*" --> "0..1" SyncRun
  Job "*" --> "0..1" ModelRun
  ModelRun "1" --> "*" ModelArtifact
  ModelRun "1" --> "0..1" ChampionModel
  ChampionModel --> "*" Prediction
  Prediction --> "*" Alert
  User --> SyncRun : autoriza
  User --> ModelRun : autoriza
```

## 3. Secuencia: sincronización de fuente

```mermaid
sequenceDiagram
  actor Op as Operador
  participant UI as Frontend
  participant API as FastAPI
  participant DB as Base de datos
  participant W as Worker
  participant Ext as Fuente externa

  Op->>UI: Clic en sincronizar
  UI->>API: POST /sources/{id}/sync
  API->>API: Validar JWT y rol
  API->>DB: Crear SyncRun + Job(pending)
  API-->>UI: 202 Accepted {run_id}
  loop Poll
    W->>DB: Claim job
    W->>Ext: Descargar / consultar API
    Ext-->>W: Filas / archivo
    W->>W: Normalizar y validar
    W->>DB: Upsert series / factores
    W->>DB: Marcar SyncRun succeeded
  end
  UI->>API: GET /sources/runs
  API->>DB: Leer estado
  API-->>UI: Lista de corridas
```

## 4. Secuencia: entrenamiento y promoción

```mermaid
sequenceDiagram
  actor Op as Operador
  participant API as FastAPI
  participant DB as DB
  participant W as Worker
  participant ML as Pipeline ML

  Op->>API: POST /models/train {disease, horizons}
  API->>DB: Crear ModelRun + Job
  API-->>Op: 202 Accepted
  W->>DB: Claim job train
  W->>ML: Feature store + split temporal
  ML->>ML: RF + HGB (+ LSTM/Ridge)
  ML->>ML: Stacking y métricas
  ML->>DB: Guardar ModelArtifact + métricas
  W->>DB: ModelRun succeeded
  Op->>API: POST /models/{id}/promote
  API->>DB: Actualizar ChampionModel
  Note over API,DB: Predicciones usan solo champion
```

## 5. Secuencia: consulta de alerta en el mapa

```mermaid
sequenceDiagram
  actor U as Usuario
  participant UI as Frontend
  participant API as FastAPI
  participant DB as DB

  U->>UI: Abre mapa / elige enfermedad
  UI->>API: GET /alerts?disease=dengue
  API->>DB: Leer alerts + territories
  DB-->>API: Filas
  API-->>UI: GeoJSON / DTO
  UI->>UI: Colorear municipios
  U->>UI: Clic en municipio
  UI->>API: GET /series?... & /predictions?...
  API->>DB: Series y forecast
  API-->>UI: Series + banda de predicción
```

## 6. Actividad: pipeline de datos semanal

```mermaid
flowchart TD
  A[Inicio semanal] --> B{Fuentes habilitadas}
  B --> C[Sync DIVIPOLA / población]
  B --> D[Sync SIVIGILA territorial + nacional]
  B --> E[Sync clima / IRCA / PAI]
  C --> F[Agregar a DiseaseSeriesPoint]
  D --> F
  E --> G[Factores por territorio]
  F --> H[Feature store]
  G --> H
  H --> I{¿Reentrenar?}
  I -->|Sí| J[Train + evaluar]
  J --> K{¿Mejora MAE/MAPE?}
  K -->|Sí| L[Promover champion]
  K -->|No| M[Conservar champion actual]
  I -->|No| N[Inferencia con champion]
  L --> N
  M --> N
  N --> O[Escribir Predictions]
  O --> P[Calcular Alerts]
  P --> Q[UI / API de lectura]
```

## 7. Despliegue (nodos)

```mermaid
flowchart TB
  subgraph pages [GitHub Pages]
    FE[SPA React / Vite]
  end

  subgraph host [PC / Render / VPS]
    API[uvicorn FastAPI]
    WRK[app.jobs.worker]
    DB[(Postgres + PostGIS)]
  end

  subgraph ext [Fuentes externas]
    GOV[datos.gov.co]
    INS[IDEAM / INS / DANE]
  end

  FE -->|HTTPS /api/v1| API
  API --> DB
  WRK --> DB
  WRK --> GOV
  WRK --> INS
  API -.->|cola jobs en DB| WRK
```
## 8. Componentes (capa de software)

```mermaid
flowchart TB
  subgraph frontend [Frontend]
    Pages[Rutas React]
    ApiClient[Cliente HTTP]
    Store[Estado UI]
  end

  subgraph api [API FastAPI]
    Routers[Routers REST]
    Auth[JWT / roles]
    Services[Servicios de dominio]
    Schemas[Pydantic]
  end

  subgraph jobs [Worker]
    Poller[Poll de jobs]
    Connectors[Conectores]
    Trainers[Entrenamiento]
  end

  subgraph data [Persistencia]
    ORM[SQLAlchemy models]
    Alembic[Migraciones]
    Files[Artefactos ML en disco/blob]
  end

  Pages --> ApiClient
  ApiClient --> Routers
  Routers --> Auth
  Routers --> Services
  Services --> ORM
  Poller --> Connectors
  Poller --> Trainers
  Connectors --> ORM
  Trainers --> ORM
  Trainers --> Files
  ORM --> Alembic
```

## 9. Estados de un Job

```mermaid
stateDiagram-v2
  [*] --> pending
  pending --> running : worker claim
  running --> succeeded : fin OK
  running --> failed : excepción
  failed --> pending : reintento manual
  succeeded --> [*]
  failed --> [*] : abandono
```

## 10. Estados de SyncRun / ModelRun

```mermaid
stateDiagram-v2
  [*] --> queued
  queued --> running
  running --> succeeded
  running --> failed
  succeeded --> [*]
  failed --> [*]
```

## Relación con el código

| Concepto UML | Ubicación aproximada |
| --- | --- |
| Connectors | `backend/app/connectors/` |
| Worker | `backend/app/jobs/worker.py` |
| Modelos ORM | `backend/app/models/` |
| Routers | `backend/app/api/` |
| Pipeline ML | `backend/app/ml/` |
| UI mapa / analítica | `src/` (componentes React) |
