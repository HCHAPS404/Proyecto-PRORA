import {
  ArrowRight,
  BrainCircuit,
  CalendarDays,
  CheckCircle2,
  CircleGauge,
  Database,
  Download,
  Info,
  LoaderCircle,
  MapPin,
  RefreshCw,
  Search,
  ShieldAlert,
  Sparkles,
} from 'lucide-react'
import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import AnalyticsStudio from './AnalyticsStudio'
import ColombiaRiskMap from './ColombiaRiskMap'
import SearchableSelect from './SearchableSelect'
import {
  ApiError,
  proraApi,
  type ApiAlertEvent,
  type AnalyticsSummary,
  type CurrentOfficialReference,
  type HistoricalPoint,
  type HistoricalTerritory,
  type ModelMetadata,
  type RiskExplanation,
  type RiskMapItem,
} from '../lib/api'

type DiseaseId = 'dengue' | 'malaria' | 'chikunguna' | 'zika' | 'leishmaniasis' | 'ira'
type LoadState = 'loading' | 'live' | 'empty' | 'offline'

interface DashboardProps {
  onOpenAlerts: () => void
  onOpenData: () => void
  onNotify: (message: string) => void
}

const diseaseOptions: { id: DiseaseId; label: string; color: string }[] = [
  { id: 'dengue', label: 'Dengue', color: '#ea6c55' },
  { id: 'malaria', label: 'Malaria', color: '#7758bd' },
  { id: 'chikunguna', label: 'Chikunguña', color: '#dd8a38' },
  { id: 'zika', label: 'Zika', color: '#d9a528' },
  { id: 'leishmaniasis', label: 'Leishmaniasis', color: '#327b65' },
  { id: 'ira', label: 'IRA', color: '#3d85c6' },
]

const numberFormat = new Intl.NumberFormat('es-CO', { maximumFractionDigits: 1 })
const formatNumber = (value?: number | null) => value == null ? '—' : numberFormat.format(value)
const formatDate = (value?: string | null) => value
  ? new Intl.DateTimeFormat('es-CO', { dateStyle: 'medium' }).format(new Date(/^\d{4}-\d{2}-\d{2}$/.test(value) ? `${value}T00:00:00` : value))
  : 'Sin corte publicado'
const titleCase = (value: string) => value.replace(/_/g, ' ').replace(/\b\w/g, (letter: string) => letter.toUpperCase())

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : null
}

function benchmarkRows(model: ModelMetadata | null) {
  const benchmark = asRecord(model?.metrics?.benchmark)
  const candidates = asRecord(benchmark?.candidates)
  if (!candidates) return []
  return Object.entries(candidates).flatMap(([name, value]) => {
    const metrics = asRecord(value)
    return typeof metrics?.mae === 'number'
      ? [{ name, mae: metrics.mae, kind: metrics.kind === 'baseline' ? 'baseline' as const : 'candidate' as const }]
      : []
  }).sort((left, right) => left.mae - right.mae)
}

function readableModelName(value: string) {
  const labels: Record<string, string> = {
    temporal_stacking_ensemble: 'Ensemble temporal',
    random_forest: 'Random Forest',
    hist_gradient_boosting: 'Gradient Boosting',
    temporal_lstm: 'LSTM temporal',
    persistence: 'Persistencia (base)',
    seasonal_naive_52w: 'Estacional 52 semanas (base)',
  }
  return labels[value] ?? titleCase(value)
}

function driverLabel(driver: Record<string, unknown>) {
  return String(driver.label ?? driver.name ?? driver.feature ?? driver.variable ?? 'Factor sin etiqueta')
}

function driverValue(driver: Record<string, unknown>) {
  for (const key of ['contribution', 'importance', 'shap_value', 'value']) {
    if (typeof driver[key] === 'number') return driver[key] as number
  }
  return null
}

function HistoryChart({ points }: { points: HistoricalPoint[] }) {
  if (!points.length) return null
  const width = 610
  const height = 190
  const maximum = Math.max(...points.map((point) => point.observed), 1)
  const x = (index: number) => 20 + (index / Math.max(points.length - 1, 1)) * (width - 40)
  const y = (value: number) => height - 24 - (value / maximum) * (height - 48)
  const path = points.map((point, index) => `${index ? 'L' : 'M'} ${x(index)} ${y(point.observed)}`).join(' ')
  const ticks = Array.from(new Set([0, Math.floor((points.length - 1) / 2), points.length - 1]))
  return (
    <div className="history-chart">
      <div className="chart-legend"><span><i className="legend-line legend-line--solid" /> Casos observados</span></div>
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Serie de casos observados publicada por la API">
        {[.25, .5, .75].map((fraction) => <line key={fraction} x1="20" x2={width - 20} y1={height * fraction} y2={height * fraction} className="chart-grid" />)}
        <path d={path} className="chart-line chart-line--observed" />
        {points.map((point, index) => <circle key={`${point.date}-${index}`} cx={x(index)} cy={y(point.observed)} r={index === points.length - 1 ? 4 : 2.7} className="chart-point"><title>{formatDate(point.date)}: {formatNumber(point.observed)} casos{point.is_preliminary ? ' · preliminar' : ''}</title></circle>)}
      </svg>
      <div className="chart-axis">{ticks.map((index) => <span key={index}>{formatDate(points[index].date)}</span>)}</div>
    </div>
  )
}

function MetricCard({ title, value, detail, icon: Icon, featured = false }: { title: string; value: string; detail: string; icon: typeof ShieldAlert; featured?: boolean }) {
  return <article className={`metric-card${featured ? ' metric-card--featured' : ''}`}><div className="metric-card__top"><span>{title}</span><Icon size={19} /></div><strong>{value}</strong><div className="metric-card__bottom"><small>{detail}</small></div></article>
}

export default function Dashboard({ onOpenAlerts, onOpenData, onNotify }: DashboardProps) {
  const [diseaseId, setDiseaseId] = useState<DiseaseId>('dengue')
  const [horizon, setHorizon] = useState<3 | 4>(4)
  const [selectedCode, setSelectedCode] = useState('')
  const [readingMode, setReadingMode] = useState<'simple' | 'advanced'>('simple')
  const [riskItems, setRiskItems] = useState<RiskMapItem[]>([])
  const [observedTerritories, setObservedTerritories] = useState<HistoricalTerritory[]>([])
  const [alerts, setAlerts] = useState<ApiAlertEvent[]>([])
  const [history, setHistory] = useState<HistoricalPoint[]>([])
  const [explanation, setExplanation] = useState<RiskExplanation | null>(null)
  const [model, setModel] = useState<ModelMetadata | null>(null)
  const [summary, setSummary] = useState<AnalyticsSummary | null>(null)
  const [currentReference, setCurrentReference] = useState<CurrentOfficialReference | null>(null)
  const [riskState, setRiskState] = useState<LoadState>('loading')
  const [territoriesState, setTerritoriesState] = useState<LoadState>('loading')
  const [alertsState, setAlertsState] = useState<LoadState>('loading')
  const [summaryState, setSummaryState] = useState<LoadState>('loading')
  const [referenceState, setReferenceState] = useState<LoadState>('loading')
  const [detailState, setDetailState] = useState<LoadState>('empty')
  const [reloadKey, setReloadKey] = useState(0)
  const disease = diseaseOptions.find((item) => item.id === diseaseId) ?? diseaseOptions[0]
  const selectedRisk = riskItems.find((item) => item.cod_dane === selectedCode) ?? null
  const selectedObservedTerritory = observedTerritories.find((item) => item.cod_dane === selectedCode) ?? null
  const selectedTerritoryName = selectedRisk?.municipality ?? selectedObservedTerritory?.municipality ?? null
  const selectedDepartment = selectedRisk?.department ?? selectedObservedTerritory?.department ?? null

  useEffect(() => {
    const analysisContext = {
      disease: diseaseId,
      disease_label: disease.label,
      territory_code: selectedCode || null,
      municipality: selectedTerritoryName,
      department: selectedDepartment,
      horizon,
    }
    sessionStorage.setItem('prora-current-analysis', JSON.stringify(analysisContext))
    window.dispatchEvent(new CustomEvent('prora-analysis-context', { detail: analysisContext }))
  }, [disease.label, diseaseId, horizon, selectedCode, selectedDepartment, selectedTerritoryName])

  useEffect(() => {
    let active = true
    setRiskState('loading')
    setTerritoriesState('loading')
    setAlertsState('loading')
    setRiskItems([])
    setObservedTerritories([])
    setAlerts([])
    setModel(null)
    Promise.allSettled([
      proraApi.risks.map(diseaseId, horizon),
      proraApi.alerts.list({ disease: diseaseId, limit: 100 }),
      proraApi.models.metadata(diseaseId, horizon),
      proraApi.analytics.historicalTerritories(diseaseId),
    ]).then(([riskResult, alertsResult, modelResult, territoriesResult]) => {
      if (!active) return
      const nextRisks = riskResult.status === 'fulfilled' ? riskResult.value : []
      setRiskItems(nextRisks)
      const publishedAlerts = alertsResult.status === 'fulfilled' ? alertsResult.value : []
      setAlerts(publishedAlerts)
      setAlertsState(alertsResult.status === 'rejected' ? 'offline' : publishedAlerts.length ? 'live' : 'empty')
      setModel(modelResult.status === 'fulfilled' ? modelResult.value : null)
      const nextObservedTerritories = territoriesResult.status === 'fulfilled' ? territoriesResult.value.items : []
      setObservedTerritories(nextObservedTerritories)
      setTerritoriesState(territoriesResult.status === 'rejected' ? 'offline' : nextObservedTerritories.length ? 'live' : 'empty')
      setSelectedCode((current) => (
        nextRisks.some((item) => item.cod_dane === current) || nextObservedTerritories.some((item) => item.cod_dane === current)
          ? current
          : nextRisks[0]?.cod_dane ?? nextObservedTerritories[0]?.cod_dane ?? ''
      ))
      setRiskState(riskResult.status === 'rejected' ? 'offline' : nextRisks.length ? 'live' : 'empty')
    })
    return () => { active = false }
  }, [diseaseId, horizon, reloadKey])

  useEffect(() => {
    let active = true
    setSummaryState('loading')
    setReferenceState('loading')
    setSummary(null)
    setCurrentReference(null)
    Promise.allSettled([
      proraApi.analytics.summary(diseaseId, selectedCode || 'national'),
      proraApi.analytics.currentReference(diseaseId, selectedCode || 'national'),
    ]).then(([summaryResult, referenceResult]) => {
      if (!active) return
      if (summaryResult.status === 'fulfilled') {
        const nextSummary = summaryResult.value
        setSummary(nextSummary)
        setSummaryState(nextSummary.latest ? 'live' : 'empty')
      } else {
        setSummary(null)
        setSummaryState('offline')
      }
      if (referenceResult.status === 'fulfilled') {
        setCurrentReference(referenceResult.value)
        setReferenceState('live')
      } else {
        setCurrentReference(null)
        setReferenceState(
          referenceResult.reason instanceof ApiError && referenceResult.reason.status === 404
            ? 'empty'
            : 'offline',
        )
      }
    })
    return () => { active = false }
  }, [diseaseId, selectedCode, reloadKey])

  useEffect(() => {
    if (!selectedCode) {
      setHistory([])
      setExplanation(null)
      setDetailState('empty')
      return
    }
    let active = true
    setDetailState('loading')
    const explanationRequest = selectedRisk
      ? proraApi.risks.explanation(selectedCode, diseaseId, horizon)
      : Promise.resolve<RiskExplanation | null>(null)
    Promise.allSettled([
      proraApi.risks.history(selectedCode, diseaseId),
      explanationRequest,
    ]).then(([historyResult, explanationResult]) => {
      if (!active) return
      const nextHistory = historyResult.status === 'fulfilled' ? historyResult.value : []
      const nextExplanation = explanationResult.status === 'fulfilled' ? explanationResult.value : null
      setHistory(nextHistory)
      setExplanation(nextExplanation)
      const detailUnavailable = historyResult.status === 'rejected' && (!selectedRisk || explanationResult.status === 'rejected')
      setDetailState(nextHistory.length || nextExplanation ? 'live' : detailUnavailable ? 'offline' : 'empty')
    })
    return () => { active = false }
  }, [diseaseId, horizon, selectedCode, selectedRisk])

  useEffect(() => {
    const applySelection = (selection: { territory?: string; disease?: string }) => {
      if (selection.disease && diseaseOptions.some((item) => item.id === selection.disease) && selection.disease !== diseaseId) {
        setDiseaseId(selection.disease as DiseaseId)
        return false
      }
      if (selection.territory) {
        if (territoriesState === 'loading' || riskState === 'loading') return false
        const territory = riskItems.find((item) => item.cod_dane === selection.territory || item.municipality === selection.territory)
          ?? observedTerritories.find((item) => item.cod_dane === selection.territory || item.municipality === selection.territory)
        if (territory) setSelectedCode(territory.cod_dane)
        else if (/^\d{5}$/.test(selection.territory)) setSelectedCode(selection.territory)
      }
      return true
    }
    const stored = sessionStorage.getItem('prora-global-selection')
    if (stored) {
      try {
        if (applySelection(JSON.parse(stored) as { territory?: string; disease?: string })) sessionStorage.removeItem('prora-global-selection')
      } catch { sessionStorage.removeItem('prora-global-selection') }
    }
    const handleSelection = (event: Event) => {
      const selection = (event as CustomEvent<{ territory?: string; disease?: string }>).detail
      if (applySelection(selection)) sessionStorage.removeItem('prora-global-selection')
    }
    window.addEventListener('prora-global-selection', handleSelection)
    return () => window.removeEventListener('prora-global-selection', handleSelection)
  }, [diseaseId, observedTerritories, riskItems, riskState, territoriesState])

  const highRiskItems = useMemo(() => riskItems.filter((item) => item.risk_level === 'alto' || item.risk_level === 'critico'), [riskItems])
  const populationUnderSignal = useMemo(() => highRiskItems.reduce((total, item) => total + (item.population ?? 0), 0), [highRiskItems])
  const completeness = useMemo(() => {
    const values = riskItems.map((item) => item.data_completeness).filter((value): value is number => typeof value === 'number')
    return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null
  }, [riskItems])
  const driverMaximum = Math.max(...(explanation?.drivers.map((driver) => Math.abs(driverValue(driver) ?? 0)) ?? []), 1)
  const apiResponded = summaryState !== 'offline' || riskState !== 'offline' || alertsState !== 'offline' || territoriesState !== 'offline'
  const weeklyVariation = summary?.percent_change
  const fourWeekWindow = (summary?.windows ?? []).find((window) => window.weeks === 4) ?? null
  const twelveWeekWindow = (summary?.windows ?? []).find((window) => window.weeks === 12) ?? null
  const currentForecastKeys = useMemo(() => new Set(riskItems.map((item) => `${item.cod_dane}:${item.disease}:${item.horizon}`)), [riskItems])
  const operationalAlerts = useMemo(
    () => alerts.filter((alert) => alert.operationally_eligible && (alert.status === 'open' || alert.status === 'active') && currentForecastKeys.has(`${alert.cod_dane}:${alert.disease}:${alert.horizon}`)),
    [alerts, currentForecastKeys],
  )
  const retrospectiveAlerts = useMemo(
    () => alerts.filter((alert) => !operationalAlerts.some((current) => current.id === alert.id)),
    [alerts, operationalAlerts],
  )
  const visiblePriorityAlerts = operationalAlerts.length ? operationalAlerts : retrospectiveAlerts
  const registeredBenchmarks = useMemo(() => benchmarkRows(model), [model])
  const benchmarkMetadata = asRecord(model?.metrics?.benchmark)
  const benchmarkWinner = typeof benchmarkMetadata?.best_candidate === 'string' ? benchmarkMetadata.best_candidate : null
  const territoryContext = selectedTerritoryName ?? (summary?.scope === 'department' ? `Departamento ${summary.territory}` : 'Colombia')
  const riskTerritoryCodes = useMemo(() => new Set(riskItems.map((item) => item.cod_dane)), [riskItems])
  const historicalOnlyTerritories = useMemo(
    () => observedTerritories.filter((item) => !riskTerritoryCodes.has(item.cod_dane)),
    [observedTerritories, riskTerritoryCodes],
  )
  const territorySelectOptions = useMemo(() => [
    ...riskItems.map((item) => ({
      value: item.cod_dane,
      label: `${item.municipality} · ${item.department}`,
      group: 'Con pronóstico operativo',
      searchText: `${item.cod_dane} ${item.department}`,
    })),
    ...historicalOnlyTerritories.map((item) => ({
      value: item.cod_dane,
      label: `${item.municipality} · ${item.department}`,
      group: `Con registros históricos (${historicalOnlyTerritories.length})`,
      searchText: `${item.cod_dane} ${item.department}`,
    })),
  ], [historicalOnlyTerritories, riskItems])
  const territoriesLoading = riskState === 'loading' || territoriesState === 'loading'
  const hasTerritories = riskItems.length > 0 || observedTerritories.length > 0

  const selectTerritoryByName = (territory: string) => {
    const match = riskItems.find((item) => item.municipality === territory || item.cod_dane === territory)
      ?? observedTerritories.find((item) => item.municipality === territory || item.cod_dane === territory)
    if (match) setSelectedCode(match.cod_dane)
  }

  const exportReport = () => {
    if (!summary && !selectedCode && !riskItems.length) {
      onNotify('No hay datos publicados para exportar')
      return
    }
    const payload = JSON.stringify({ generated_at: new Date().toISOString(), disease: diseaseId, horizon, analysis_context: selectedRisk ? 'operational_forecast' : selectedObservedTerritory ? 'historical_observations' : 'national', territorial_summary: summary, current_official_reference: currentReference, selected_forecast: selectedRisk, selected_historical_territory: selectedObservedTerritory, alerts, history, explanation, model }, null, 2)
    const url = URL.createObjectURL(new Blob([payload], { type: 'application/json;charset=utf-8' }))
    const link = document.createElement('a')
    link.href = url
    link.download = `prora-${diseaseId}-h${horizon}.json`
    link.click()
    URL.revokeObjectURL(url)
    onNotify('Reporte generado con los datos visibles de la API')
  }

  return (
    <div className="dashboard workspace-view">
      <header className="dashboard-heading">
        <div><div className="heading-meta"><span className={`status-dot${apiResponded ? ' status-dot--online' : ''}`} /> {summaryState === 'loading' ? 'Consultando fuentes epidemiológicas…' : !apiResponded ? 'Backend no disponible' : summary?.latest ? `Último corte observado: ${formatDate(summary.latest.week)}` : 'API conectada · sin observaciones para este evento'}</div><h1>Panorama nacional</h1><p>Observaciones históricas y señales operativas de {disease.label}, diferenciadas por vigencia y procedencia.</p></div>
        <div className="heading-actions"><div className="reading-switch" aria-label="Nivel de lectura"><button className={readingMode === 'simple' ? 'is-active' : ''} onClick={() => setReadingMode('simple')}>Lectura simple</button><button className={readingMode === 'advanced' ? 'is-active' : ''} onClick={() => setReadingMode('advanced')}>Lectura avanzada</button></div><button className="button button--secondary" onClick={exportReport} disabled={!summary && !selectedCode && !riskItems.length}><Download size={17} /> Exportar</button></div>
      </header>

      <section className="filter-ribbon" aria-label="Filtros del tablero">
        <div className="filter-control filter-control--disease"><span>Enfermedad</span><SearchableSelect value={diseaseId} ariaLabel="Enfermedad" searchPlaceholder="Buscar enfermedad…" options={diseaseOptions.map((option) => ({ value: option.id, label: option.label }))} onChange={(value) => { setSelectedCode(''); setDiseaseId(value as DiseaseId) }} leading={<i style={{ background: disease.color }} />} /></div>
        <div className="filter-control filter-control--territory"><span>Territorio de análisis</span><SearchableSelect value={selectedCode} ariaLabel="Territorio de análisis" searchPlaceholder="Buscar municipio, departamento o código DANE…" emptyLabel="No hay territorios que coincidan" placeholder={territoriesLoading ? 'Consultando territorios…' : territoriesState === 'offline' && riskState !== 'live' ? 'No fue posible cargar territorios' : 'Seleccione un territorio'} options={territorySelectOptions} onChange={setSelectedCode} disabled={!hasTerritories || territoriesLoading} leading={<Search size={17} />} /><small className="filter-control__hint">{territoriesState === 'loading' ? 'Cargando cobertura territorial…' : territoriesState === 'live' ? `${observedTerritories.length} municipios con registros históricos` : territoriesState === 'offline' ? 'Cobertura histórica no disponible' : 'Sin registros municipales'}</small></div>
        <div className="filter-control"><span>Horizonte de predicción</span><div className="horizon-switch"><button className={horizon === 3 ? 'is-active' : ''} onClick={() => setHorizon(3)}>3 semanas</button><button className={horizon === 4 ? 'is-active' : ''} onClick={() => setHorizon(4)}>4 semanas</button></div></div>
        <button className="button button--secondary" type="button" onClick={() => setReloadKey((value) => value + 1)}><RefreshCw size={16} /> Actualizar</button>
      </section>

      <div className={`data-availability-banner data-availability-banner--${riskState}`} role="status">
        <Info size={18} />
        <div>
          <strong>{riskState === 'loading' ? 'Verificando pronósticos operativos' : riskState === 'live' ? `${riskItems.length} municipios con predicción vigente` : riskState === 'offline' ? 'No hay conexión con el backend' : 'Sin predicciones operativas vigentes'}</strong>
          <span>{riskState === 'loading' ? 'Esta verificación termina automáticamente si el servicio no responde.' : riskState === 'live' ? `${highRiskItems.length} territorios en nivel alto o crítico · ${formatNumber(populationUnderSignal)} habitantes bajo señal · completitud ${completeness == null ? 'no informada' : `${formatNumber(completeness * 100)}%`}.` : riskState === 'offline' ? territoriesState === 'live' ? `La capa predictiva no respondió; aún puede consultar el histórico de ${observedTerritories.length} municipios.` : 'Inicia la API y pulsa Actualizar. El mapa conserva únicamente la geometría administrativa.' : territoriesState === 'live' ? `${observedTerritories.length} municipios tienen observaciones históricas disponibles para análisis. No se colorean ni clasifican como riesgo actual.` : model ? `Existe el modelo ${model.version}, pero la API no publicó pronósticos elegibles para el corte actual.` : 'No existe un modelo operativo publicado para esta enfermedad y horizonte.'}</span>
        </div>
        {riskState === 'offline' && <button className="button button--secondary button--small" type="button" onClick={() => setReloadKey((value) => value + 1)}><RefreshCw size={15} /> Reconectar</button>}
      </div>

      <section className="metric-grid" aria-label="Indicadores principales">
        <MetricCard title="Casos · último corte territorial" value={summaryState === 'loading' ? '…' : formatNumber(summary?.latest?.observed_cases)} detail={summary?.latest ? `${territoryContext} · ${formatDate(summary.latest.week)} · ${summary.data_status === 'fresh' ? 'vigente' : 'rezagado'}` : summaryState === 'offline' ? 'Analítica no disponible' : 'Sin observaciones publicadas'} icon={CalendarDays} featured />
        <MetricCard title="Variación frente al corte anterior" value={weeklyVariation == null ? '—' : `${weeklyVariation >= 0 ? '+' : ''}${formatNumber(weeklyVariation)}%`} detail={summary?.previous ? `${territoryContext} · frente a ${formatDate(summary.previous.week)}` : 'Sin dos cortes comparables'} icon={CircleGauge} />
        <MetricCard title="Casos acumulados · 4 semanas" value={summaryState === 'loading' ? '…' : formatNumber(fourWeekWindow?.observed_cases)} detail={fourWeekWindow ? `${fourWeekWindow.observed_week_count}/4 semanas con reporte · no se imputan ceros` : 'Sin ventana territorial disponible'} icon={MapPin} />
        <MetricCard title="Alertas operativas vigentes" value={alertsState === 'loading' ? '…' : alertsState === 'offline' ? '—' : formatNumber(operationalAlerts.length)} detail={alertsState === 'offline' ? 'API de alertas no disponible' : operationalAlerts.length ? `${disease.label} · horizonte ${horizon} semanas` : retrospectiveAlerts.length ? `${retrospectiveAlerts.length} registros históricos, no vigentes` : 'Sin alertas vigentes publicadas'} icon={ShieldAlert} />
      </section>

      {readingMode === 'simple' ? (
        <section className="simple-reading-summary" aria-label="Lectura simple del territorio">
          <Sparkles size={18} />
          <div><strong>Lectura rápida de {territoryContext}</strong><span>{summary?.latest ? `El último corte municipal notificó ${formatNumber(summary.latest.observed_cases)} casos; la ventana de cuatro semanas acumula ${formatNumber(fourWeekWindow?.observed_cases)}.` : 'No hay observaciones municipales suficientes para resumir este territorio.'} {summary?.data_status === 'stale' ? `El corte tiene ${formatNumber(summary.observation_age_days)} días de rezago y no debe interpretarse como situación actual.` : ''} {currentReference ? `Como referencia reciente separada, el INS informa ${formatNumber(currentReference.cumulative_cases)} casos acumulados en ${currentReference.reference_territory_name} hasta la semana epidemiológica ${currentReference.epidemiological_week} de ${currentReference.epidemiological_year}; esta referencia no reemplaza el corte municipal.` : ''}</span></div>
        </section>
      ) : (
        <section className="advanced-metric-panel content-card" aria-label="Indicadores avanzados del territorio">
          <div className="card-heading-row"><div><span className="eyebrow">Lectura avanzada</span><h2>Cobertura, incidencia y rezago</h2><p>Todos los valores conservan el alcance de {territoryContext}; una semana ausente no se convierte en cero.</p></div><Database size={20} /></div>
          {currentReference ? <div className="official-reference-card"><div><span>Referencia oficial reciente INS · contexto {currentReference.reference_territory_level === 'national' ? 'nacional' : currentReference.reference_territory_level === 'district' ? 'distrital' : 'departamental'}</span><strong>{currentReference.reference_territory_name} · SE {currentReference.epidemiological_week}/{currentReference.epidemiological_year}</strong><small>{formatNumber(currentReference.cumulative_cases)} casos acumulados · corte {formatDate(currentReference.period_end)} · {currentReference.is_preliminary ? 'preliminar' : 'consolidado'}</small></div><a href={currentReference.source_document_url} target="_blank" rel="noreferrer">Ver boletín · pág. {currentReference.source_page}</a><p>{currentReference.geographic_context_only ? 'Referencia de contexto geográfico: no sustituye ni corrige el KPI municipal histórico.' : currentReference.comparison_basis}</p></div> : referenceState === 'loading' ? <div className="official-reference-card official-reference-card--loading"><LoaderCircle className="spin" size={18} /><span>Consultando la referencia oficial reciente…</span></div> : referenceState === 'offline' ? <div className="official-reference-card official-reference-card--empty"><Info size={18} /><span>No fue posible consultar ahora la referencia BES reciente. El corte municipal se conserva sin alteraciones.</span></div> : <div className="official-reference-card official-reference-card--empty"><Info size={18} /><span>El registro no contiene una referencia BES reciente compatible con esta enfermedad y territorio.</span></div>}
          <dl className="advanced-metric-grid">
            <div><dt>Acumulado 12 semanas</dt><dd>{formatNumber(twelveWeekWindow?.observed_cases)}</dd><small>{twelveWeekWindow ? `${twelveWeekWindow.observed_week_count}/12 semanas reportadas` : 'Sin ventana'}</small></div>
            <div><dt>Variación 4 vs. 4 semanas</dt><dd>{fourWeekWindow?.percent_change_vs_previous == null ? '—' : `${fourWeekWindow.percent_change_vs_previous >= 0 ? '+' : ''}${formatNumber(fourWeekWindow.percent_change_vs_previous)}%`}</dd><small>{fourWeekWindow?.previous_observed_cases == null ? 'Sin periodo previo comparable' : `Periodo previo: ${formatNumber(fourWeekWindow.previous_observed_cases)}`}</small></div>
            <div><dt>Incidencia 4 semanas</dt><dd>{fourWeekWindow?.incidence_per_100k == null ? '—' : formatNumber(fourWeekWindow.incidence_per_100k)}</dd><small>Por 100.000 habitantes · denominador registrado</small></div>
            <div><dt>Semanas faltantes (4)</dt><dd>{formatNumber(fourWeekWindow?.missing_week_count)}</dd><small>No se imputan como cero casos</small></div>
            <div><dt>Rezago del corte</dt><dd>{summary?.observation_age_days == null ? '—' : `${numberFormat.format(summary.observation_age_days)} días`}</dd><small>{summary?.data_status === 'fresh' ? 'Dentro del umbral operativo' : summary?.data_status === 'stale' ? 'Fuente histórica rezagada' : 'Sin corte'}</small></div>
            <div><dt>Calidad media del corte</dt><dd>{summary?.latest?.mean_quality_score == null ? '—' : `${formatNumber(summary.latest.mean_quality_score * 100)}%`}</dd><small>{summary?.latest?.is_preliminary ? 'Dato preliminar' : 'Dato consolidado según la fuente'}</small></div>
          </dl>
        </section>
      )}

      <section className="dashboard-primary-grid">
        <div className="content-card map-card"><ColombiaRiskMap disease={disease.label} horizon={horizon} selectedTerritory={selectedRisk?.municipality} selectedHistoricalTerritory={selectedRisk ? null : selectedObservedTerritory} onSelectTerritory={selectTerritoryByName} riskItems={riskItems} historicalTerritories={observedTerritories} dataState={riskState} historyState={territoriesState} historicalTerritoryCount={observedTerritories.length} /></div>
        <aside className="content-card priority-panel">
          <div className="card-heading-row"><div><span className="eyebrow">{operationalAlerts.length ? 'Alertas operativas' : 'Archivo de alertas'}</span><h2>{operationalAlerts.length ? 'Prioridad territorial vigente' : 'Historial verificable'}</h2></div><ShieldAlert size={20} /></div>
          <p className="card-description">{operationalAlerts.length ? 'Orden vigente devuelto por el backend para el evento seleccionado.' : retrospectiveAlerts.length ? 'Registros emitidos anteriormente; no representan riesgo actual.' : 'No existen alertas emitidas para este filtro.'}</p>
          {visiblePriorityAlerts.length ? <div className="priority-list">{visiblePriorityAlerts.slice(0, 6).map((alert, index) => <button key={alert.id} className={selectedCode === alert.cod_dane ? 'priority-item is-active' : 'priority-item'} onClick={() => setSelectedCode(alert.cod_dane)}><span className={`priority-rank priority-rank--${alert.risk_level.replace('í', 'i')}`}>{String(index + 1).padStart(2, '0')}</span><span className="priority-item__copy"><strong>{alert.municipality}</strong><small>{alert.department} · {titleCase(alert.disease)}</small><em>{alert.operationally_eligible ? alert.status : `Histórica · objetivo ${formatDate(alert.target_week)}`}</em></span><span className="priority-item__score"><strong>{formatNumber(alert.risk_score)}</strong><small>/ 100</small><em>{formatNumber(alert.predicted_cases)} casos estimados</em></span></button>)}</div> : <div className="empty-state">{alertsState === 'loading' ? <LoaderCircle className="spin" size={26} /> : <ShieldAlert size={26} />}<h3>{alertsState === 'loading' ? 'Consultando alertas' : alertsState === 'offline' ? 'API de alertas no disponible' : 'Sin alertas registradas'}</h3><p>{alertsState === 'offline' ? 'No se muestran alertas locales de respaldo.' : 'El backend no contiene alertas vigentes ni históricas para este evento.'}</p></div>}
          <button className="button button--ghost button--full" onClick={onOpenAlerts}>Abrir centro de alertas <ArrowRight size={16} /></button>
        </aside>
      </section>

      <section className="dashboard-secondary-grid">
        <article className="content-card explain-card">
          <div className="card-heading-row"><div><span className="eyebrow">¿Por qué esta alerta?</span><h2>Factores publicados por el modelo</h2></div><span className="ai-badge"><Sparkles size={13} /> Explicabilidad</span></div>
          {detailState === 'loading' && <div className="empty-state"><LoaderCircle className="spin" size={25} /><p>Consultando explicación…</p></div>}
          {detailState !== 'loading' && explanation ? <><div className="territory-summary"><div className="territory-score" style={{ '--risk-score': Math.max(0, Math.min(100, explanation.risk_score)) } as CSSProperties}><span>{formatNumber(explanation.risk_score)}</span><small>Riesgo / 100</small></div><p><strong>{selectedRisk?.municipality}</strong> · modelo {explanation.model_version}. Los factores se muestran tal como fueron registrados para esta predicción.</p></div>{explanation.drivers.length ? <div className="driver-list">{explanation.drivers.map((driver, index) => { const value = driverValue(driver); return <div className="driver-row" key={`${driverLabel(driver)}-${index}`}><span className="driver-icon driver-icon--blue"><BrainCircuit size={17} /></span><span className="driver-copy"><strong>{driverLabel(driver)}</strong><small>{String(driver.detail ?? driver.direction ?? 'Sin detalle adicional')}</small></span><span className="driver-graph"><i style={{ width: value == null ? '0%' : `${Math.max(2, Math.abs(value) / driverMaximum * 100)}%` }} /></span><b>{value == null ? '—' : formatNumber(value)}</b></div>})}</div> : <div className="empty-state"><Info size={24} /><h3>Sin factores publicados</h3><p>La predicción existe, pero no incluye contribuciones locales.</p></div>}{readingMode === 'advanced' && <div className="technical-note"><BrainCircuit size={17} /><span><strong>Advertencias del modelo</strong> {explanation.warnings.length ? explanation.warnings.join(' · ') : 'No se publicaron advertencias para esta predicción.'}</span></div>}</> : detailState !== 'loading' && <div className="empty-state"><Info size={25} /><h3>{selectedObservedTerritory ? 'Lectura histórica, sin explicación predictiva' : 'Sin explicación disponible'}</h3><p>{selectedObservedTerritory ? `${selectedObservedTerritory.municipality} tiene registros observados, pero no un pronóstico operativo vigente. Esta sección no calcula ni infiere factores de riesgo.` : 'Seleccione un territorio de análisis para consultar la información disponible.'}</p></div>}
        </article>

        <article className="content-card history-card">
          <div className="card-heading-row"><div><span className="eyebrow">Contexto temporal</span><h2>Casos observados</h2></div><CalendarDays size={20} /></div>
          <p className="card-description">{selectedTerritoryName ? `${selectedTerritoryName} · ${history.length} cortes observados` : 'Sin territorio seleccionado'}</p>
          {detailState === 'loading' ? <div className="empty-state"><LoaderCircle className="spin" size={25} /><p>Consultando historia…</p></div> : history.length ? <HistoryChart points={history} /> : <div className="empty-state"><Info size={25} /><h3>Sin historia disponible</h3><p>No hay observaciones municipales para este filtro.</p></div>}
        </article>
      </section>

      <div className="dashboard-analytics-section"><AnalyticsStudio diseaseId={diseaseId} horizon={horizon} territories={observedTerritories} selectedTerritoryCode={selectedCode} onSelectTerritory={setSelectedCode} /></div>

      <section className="dashboard-bottom-grid">
        <article className="content-card trace-card">
          <div className="card-heading-row"><div><span className="eyebrow">Trazabilidad</span><h2>Estado del modelo</h2></div><button className="icon-button" onClick={onOpenData} aria-label="Abrir centro de datos"><Database size={18} /></button></div>
          {model ? <><div className="trace-grid"><span><small>Versión</small><strong>{model.version}</strong></span><span><small>Estado</small><strong>{model.status}</strong></span><span><small>Entrenamiento</small><strong>{formatDate(model.trained_at)}</strong></span><span><small>Huella de datos</small><strong title={model.data_fingerprint ?? ''}>{model.data_fingerprint ? `${model.data_fingerprint.slice(0, 12)}…` : 'No informada'}</strong></span></div>{readingMode === 'advanced' && (registeredBenchmarks.length ? <div className="benchmark-comparison"><div className="benchmark-comparison__heading"><span><BrainCircuit size={16} /> Benchmark temporal registrado</span><small>Menor MAE es mejor · misma validación fuera de muestra</small></div><div className="benchmark-comparison__rows">{registeredBenchmarks.map((row) => <div key={row.name} className={row.name === benchmarkWinner ? 'is-winner' : ''}><span><strong>{readableModelName(row.name)}</strong><small>{row.kind === 'baseline' ? 'Línea base' : row.name === benchmarkWinner ? 'Mejor candidato' : 'Candidato'}</small></span><b>{formatNumber(row.mae)} MAE</b></div>)}</div><div className="technical-note"><Info size={16} /><span><strong>{benchmarkMetadata?.passes_baseline_gate === true ? 'Supera la mejor línea base registrada' : 'No supera la puerta de línea base'}</strong> Solo se comparan resultados persistidos por el entrenamiento; el navegador no recalcula ni completa métricas.</span></div></div> : <div className="technical-note"><Info size={16} /><span><strong>Sin benchmark comparable</strong> La versión está registrada, pero no expone candidatos evaluados con MAE fuera de muestra.</span></div>)}</> : <div className="empty-state"><Database size={25} /><h3>Sin modelo registrado</h3><p>No se recibió metadata para este evento y horizonte.</p></div>}
        </article>
        <article className="content-card action-card"><div className="card-heading-row"><div><span className="eyebrow">Calidad de decisión</span><h2>Interpretación responsable</h2></div><CheckCircle2 size={20} /></div><div className="demo-disclaimer"><Info size={16} /><p>Las alertas orientan la priorización preventiva y deben complementarse con vigilancia de campo, protocolos institucionales y criterio epidemiológico.</p></div></article>
      </section>
    </div>
  )
}
