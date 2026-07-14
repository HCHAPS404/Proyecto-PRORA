# PRORA ML

Pipeline ejecutable para pronosticar casos y riesgo de brote a 3–4 semanas por
municipio. El contrato tabular mínimo es:

| columna | descripción |
|---|---|
| `week` | fecha de inicio de semana epidemiológica |
| `disease` | dengue, malaria, chikunguna, zika, leishmaniasis o ira |
| `territory_id` | código DIVIPOLA u otro identificador municipal estable |
| `cases` | casos observados no negativos |

Se reconocen, cuando están disponibles, `precipitation`, `temperature`,
`humidity`, `pai_health_system_access_proxy`, `deforestation`, `water_access`,
`sewer_access`, `overcrowding` y `population`.

## Diseño

- Variables semanales sin fuga: rezagos 1–12, ventanas 2/4/8/12, estacionalidad
  seno/coseno, anomalías climáticas, proxy de acceso al sistema de salud basado
  en coberturas agregadas PAI, deforestación y línea base territorial.
- Validación expanding-window por semanas únicas; ningún municipio futuro entra
  en entrenamiento por compartir corte con otro territorio.
- Random Forest, HistGradientBoosting y LSTM real con PyTorch, combinados por un
  metamodelo Ridge entrenado sobre predicciones fuera de muestra.
- Si PyTorch no está instalado, el tercer modelo cambia de manera explícita y
  determinista a Ridge (`temporal_backend=ridge_fallback`). Esto permite ejecutar
  API y CI sin una imagen de varios GB; `torch` queda como extra de entrenamiento.
- Intervalos marginales conformales a partir de residuales temporales fuera de
  muestra. Deben monitorearse y recalibrarse por enfermedad/territorio.
- Registro inmutable en disco con manifiesto, métricas y puntero `latest.json`.
- Explicabilidad global por permutation importance, análisis local por
  perturbación y SHAP opcional.
- Las coberturas PAI BCG/PENTA/N2D/TV se usan exclusivamente como proxy
  departamental/anual de acceso al sistema de salud. No representan protección
  causal frente a dengue, malaria, chikunguna, Zika o leishmaniasis. Una
  cobertura directa (por ejemplo influenza para IRA) solo se habilita tras
  ingerir y validar la fuente municipal específica.
- Toda importancia o contribución publicada es una asociación predictiva, no una
  estimación causal.

## Estado verificable y compuertas

`GET /api/v1/models/readiness/portfolio` devuelve, para cada enfermedad, cuatro
estados separados: cobertura epidemiologica, elegibilidad para investigacion,
versiones realmente entrenadas y elegibilidad operativa. Un modelo ausente se
reporta como `not_trained`; nunca se sustituye por una prediccion generica.

- Las semanas municipales sin fila se conservan como `NaN`, nunca como cero.
  Para uso operativo se exige una serie con ceros explicitos o una cobertura de
  calendario de al menos 95%, ademas de corte reciente y densidad minima.
- Los eventos escasos pueden entrenarse solo para investigacion si cumplen el
  minimo de filas observadas, territorios y semanas. Una densidad baja se
  publica como limitacion y bloquea siempre su uso operativo; no se rellena con
  ceros ni se presenta el resultado retrospectivo como alerta vigente.
- Cada nueva version compara el stack y sus tres componentes contra persistencia
  y naive estacional de 52 semanas sobre exactamente los mismos folds OOF. El
  manifiesto conserva metricas por fold, mejor candidato, mejor baseline y
  `passes_baseline_gate`. El candidato con menor MAE temporal (stack, Random
  Forest, HistGradientBoosting o learner temporal) queda persistido como
  `production_model`; inferencia, intervalos conformales y calibracion usan sus
  mismas predicciones OOF. Si ese ganador no supera el mejor baseline, sus
  pronosticos se almacenan para auditoria pero no alimentan mapa operativo ni alertas.
- La validacion territorial reentrena exactamente el candidato ganador dejando
  departamentos DIVIPOLA completos fuera de entrenamiento y publica skill contra
  persistencia. Cuando gana el stack, cada fold territorial usa un holdout
  cronologico interno para aprender el metamodelo; el benchmark temporal principal
  conserva cuatro folds expanding-window.
- PAI municipal se une desde el mes siguiente al corte publicado, hacia atras y
  sin fuga. PAI sigue siendo proxy de acceso al sistema, no efecto causal.
- La composicion urbano-rural procede de DANE CNPV 2018, capa 801, y se trata
  como covariable estructural. Deforestacion permanece `unavailable` hasta que
  exista una serie municipal versionada y aprobada.

Plan seguro para enfermedades sin modelo: cargar primero vigilancia completa y
reciente, revisar el readiness, entrenar una enfermedad por job, exigir ambos
horizontes y sus benchmarks, mantenerla `research_only` durante revision
retrospectiva, y activar operacion solo cuando pasen las compuertas de datos,
baseline, calibracion y revision epidemiologica humana.

## Uso

```python
from app.ml import ForecastService, MLConfig, ModelRegistry

registry = ModelRegistry("./artifacts/models")
service = ForecastService(registry, MLConfig())
service.train_all(history_dataframe, diseases=["dengue"], horizons=[3, 4])
forecast = service.forecast(history_dataframe, "dengue", "76001")
```

Instalar el núcleo con `pip install -r app/ml/requirements-ml.txt`. Para LSTM o
SHAP, instalar además las líneas opcionales comentadas, idealmente en la imagen
del worker de entrenamiento y no en la API de inferencia.

Los resultados son apoyo a vigilancia epidemiológica, no diagnóstico clínico.
Antes de producción se requiere validación retrospectiva del INS, auditoría de
calidad/SIVIGILA, calibración regional, monitoreo de deriva y aprobación humana
de las alertas.
