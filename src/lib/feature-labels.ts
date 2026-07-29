/** Human-readable labels for ML feature names shown in the dashboard. */

const FEATURE_LABELS: Record<string, string> = {
  // --- Casos ---
  cases_current: 'Casos actuales',
  cases_lag_1: 'Casos sem. anterior',
  cases_lag_2: 'Casos hace 2 sem.',
  cases_lag_3: 'Casos hace 3 sem.',
  cases_lag_4: 'Casos hace 4 sem.',
  cases_roll_mean_4: 'Promedio móvil 4 sem.',
  cases_roll_mean_8: 'Promedio móvil 8 sem.',
  cases_roll_mean_12: 'Promedio móvil 12 sem.',
  cases_roll_sum_4: 'Acumulado 4 sem.',
  cases_roll_sum_8: 'Acumulado 8 sem.',
  cases_roll_sum_12: 'Acumulado 12 sem.',
  cases_roll_std_4: 'Variabilidad 4 sem.',
  cases_roll_std_8: 'Variabilidad 8 sem.',
  cases_roll_std_12: 'Variabilidad 12 sem.',

  // --- Territorio ---
  territory_historical_mean: 'Media histórica municipal',
  territory_historical_std: 'Variabilidad histórica municipal',
  outbreak_threshold: 'Umbral de brote',
  population: 'Población total',
  urban_population_pct: 'Población urbana (%)',
  rural_population_pct: 'Población rural (%)',
  populated_center_population_pct: 'Población en centros poblados (%)',
  rural_remainder_population_pct: 'Población rural dispersa (%)',

  // --- Clima ---
  precipitation: 'Precipitación (mm)',
  precipitation_anomaly: 'Anomalía de precipitación',
  precipitation_lag_1: 'Precipitación sem. anterior',
  precipitation_roll_mean_4: 'Precipitación prom. 4 sem.',
  temperature: 'Temperatura media (°C)',
  temperature_anomaly: 'Anomalía de temperatura',
  temperature_lag_1: 'Temperatura sem. anterior',
  temperature_roll_mean_4: 'Temperatura prom. 4 sem.',
  humidity: 'Humedad relativa (%)',
  humidity_anomaly: 'Anomalía de humedad',
  humidity_lag_1: 'Humedad sem. anterior',
  humidity_roll_mean_4: 'Humedad prom. 4 sem.',

  // --- Estacionalidad ---
  week_sin: 'Estacionalidad (seno)',
  week_cos: 'Estacionalidad (coseno)',
  year_trend: 'Tendencia anual',

  // --- Socioeconómico ---
  water_access_pct: 'Acceso a agua (%)',
  sewer_access_pct: 'Acceso a alcantarillado (%)',
  overcrowding_pct: 'Hacinamiento (%)',
  nbi_pct: 'Necesidades básicas insatisfechas (%)',
  irca_index: 'Calidad del agua (IRCA)',

  // --- Deforestación ---
  deforestation: 'Deforestación',
  deforestation_roll_sum_4: 'Deforestación acum. 4 sem.',
  deforestation_change_12: 'Cambio deforestación 12 sem.',

  // --- Vacunación / PAI ---
  pai_health_system_access_proxy: 'Acceso al sistema de salud (PAI)',
  pai_access_proxy_shortfall: 'Brecha de acceso a salud (%)',
  pai_access_proxy_change_4: 'Cambio acceso a salud 4 sem.',

  // --- Brote ---
  outbreak_h4: 'Indicador de brote H4',
  outbreak_h3: 'Indicador de brote H3',
}

/**
 * Returns a human-readable label for a feature variable name.
 * Falls back to title-casing the raw name if no label is defined.
 */
export function featureLabel(raw: string): string {
  if (FEATURE_LABELS[raw]) return FEATURE_LABELS[raw]
  return raw
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase())
}

export default FEATURE_LABELS
