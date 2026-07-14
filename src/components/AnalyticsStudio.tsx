import {
  Activity,
  BarChart3,
  BrainCircuit,
  CalendarRange,
  Clock3,
  Info,
  LineChart,
  LoaderCircle,
  RefreshCw,
} from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import {
  ApiError,
  proraApi,
  type AnalyticsForecastSeries,
  type AnalyticsSeries,
  type AnalyticsSummary,
  type HistoricalTerritory,
} from '../lib/api'
import '../analytics-studio.css'
import SearchableSelect from './SearchableSelect'

type AnalyticsView = 'history' | 'current' | 'forecast'
type DiseaseId = 'dengue' | 'malaria' | 'chikunguna' | 'zika' | 'leishmaniasis' | 'ira'
type LoadState = 'loading' | 'live' | 'empty' | 'error'

interface AnalyticsStudioProps {
  diseaseId: DiseaseId
  horizon: 3 | 4
  territories?: HistoricalTerritory[]
  selectedTerritoryCode?: string
  onSelectTerritory?: (codDane: string) => void
}

const diseases: { id: DiseaseId; label: string }[] = [
  { id: 'dengue', label: 'Dengue' },
  { id: 'malaria', label: 'Malaria' },
  { id: 'chikunguna', label: 'Chikunguña' },
  { id: 'zika', label: 'Zika' },
  { id: 'leishmaniasis', label: 'Leishmaniasis' },
  { id: 'ira', label: 'IRA' },
]

const formatNumber = (value: number) => new Intl.NumberFormat('es-CO', { maximumFractionDigits: 1 }).format(value)
const formatDate = (value?: string | null) => value
  ? new Intl.DateTimeFormat('es-CO', { dateStyle: 'medium' }).format(new Date(`${value}T00:00:00`))
  : 'Sin corte disponible'

function forecastFailureMessage(reason: unknown) {
  if (reason instanceof ApiError) {
    if (reason.status === 404) return 'La API confirmó que no existe un pronóstico operativo publicado para este filtro.'
    return `La consulta de predicción falló (${reason.status || 'red'}): ${reason.message}`
  }
  return reason instanceof Error
    ? `La consulta de predicción falló: ${reason.message}`
    : 'La consulta de predicción falló antes de recibir una respuesta verificable.'
}

function EmptyPanel({ error, onRetry }: { error?: string; onRetry: () => void }) {
  return (
    <div className="empty-state" role="status">
      <Info size={28} />
      <h3>{error ? 'No fue posible consultar la analítica' : 'No hay datos publicados para este filtro'}</h3>
      <p>{error || 'La API respondió correctamente, pero todavía no existen observaciones o predicciones operativas.'}</p>
      <button className="button button--secondary" type="button" onClick={onRetry}><RefreshCw size={16} /> Reintentar</button>
    </div>
  )
}

function SeriesChart({ series, diseaseLabel }: { series: AnalyticsSeries; diseaseLabel: string }) {
  const points = series.points
  if (!points.length) return null
  const width = 760
  const height = 282
  const left = 58
  const top = 18
  const plotWidth = width - left - 22
  const plotHeight = height - top - 44
  const maximum = Math.max(...points.map((point) => point.observed_cases), 1)
  const x = (index: number) => left + (index / Math.max(points.length - 1, 1)) * plotWidth
  const y = (value: number) => top + plotHeight - (value / maximum) * plotHeight
  const path = points.map((point, index) => `${index ? 'L' : 'M'} ${x(index)} ${y(point.observed_cases)}`).join(' ')
  const tickIndexes = Array.from(new Set([0, Math.floor((points.length - 1) / 2), points.length - 1]))

  return (
    <div className="analytics-svg-wrap">
      <svg className="analytics-line-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`Serie observada de ${diseaseLabel}`}>
        {[0, .25, .5, .75, 1].map((fraction) => {
          const lineY = top + plotHeight * fraction
          const value = maximum * (1 - fraction)
          return <g key={fraction}><line x1={left} x2={width - 22} y1={lineY} y2={lineY} className="analytics-grid-line" /><text x={left - 9} y={lineY + 4} textAnchor="end" className="analytics-axis-label">{formatNumber(value)}</text></g>
        })}
        <path d={`${path} L ${x(points.length - 1)} ${top + plotHeight} L ${x(0)} ${top + plotHeight} Z`} className="analytics-history-area" />
        <path d={path} className="analytics-history-observed" />
        {points.map((point, index) => <circle key={`${point.week}-${index}`} cx={x(index)} cy={y(point.observed_cases)} r={index === points.length - 1 ? 5 : 3} className="analytics-history-point"><title>{formatDate(point.week)}: {formatNumber(point.observed_cases)} casos{point.is_preliminary ? ' · preliminar' : ''}</title></circle>)}
        {tickIndexes.map((index) => <text key={index} x={x(index)} y={height - 13} textAnchor="middle" className="analytics-axis-label">{formatDate(points[index].week)}</text>)}
      </svg>
    </div>
  )
}

function ForecastChart({ forecast, diseaseLabel }: { forecast: AnalyticsForecastSeries; diseaseLabel: string }) {
  const points = forecast.points
  if (!points.length) return null
  const operational = forecast.metadata.forecast_mode === 'operational'
    || forecast.metadata.operationally_eligible === true
  const observationCutoff = typeof forecast.metadata.observation_cutoff === 'string'
    ? forecast.metadata.observation_cutoff
    : null
  const width = 760
  const height = 282
  const left = 58
  const top = 18
  const plotWidth = width - left - 22
  const plotHeight = height - top - 44
  const maximum = Math.max(...points.map((point) => point.upper_bound), 1)
  const x = (index: number) => left + (index / Math.max(points.length - 1, 1)) * plotWidth
  const y = (value: number) => top + plotHeight - (value / maximum) * plotHeight
  const line = (values: number[]) => values.map((value, index) => `${index ? 'L' : 'M'} ${x(index)} ${y(value)}`).join(' ')
  const upper = points.map((point) => point.upper_bound)
  const lower = points.map((point) => point.lower_bound)
  const central = points.map((point) => point.predicted_cases)
  const band = `${line(upper)} ${[...lower].reverse().map((value, reverseIndex) => `L ${x(lower.length - 1 - reverseIndex)} ${y(value)}`).join(' ')} Z`
  const componentNames = Array.from(new Set(points.flatMap((point) => Object.keys(point.component_predictions))))
  const colors = ['#3966c5', '#a45bb7', '#c97b35', '#347c6a']

  return (
    <>
      <div className="analytics-chart-heading">
        <div><h3>{operational ? 'Predicción operativa' : 'Escenario retrospectivo del modelo'}</h3><p>{operational ? 'Valores e intervalos vigentes publicados por el backend para el horizonte seleccionado.' : `Resultado trazable para evaluación histórica${observationCutoff ? `, con corte observado ${formatDate(observationCutoff)}` : ''}. No representa el riesgo actual.`}</p></div>
        <div className="analytics-legend"><span><i className="analytics-legend__line analytics-legend__line--observed" /> Predicción central</span><span><i className="analytics-legend__line analytics-legend__line--baseline" /> Componentes disponibles</span></div>
      </div>
      <div className="analytics-svg-wrap">
        <svg className="analytics-line-chart analytics-forecast-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${operational ? 'Predicción operativa' : 'Escenario retrospectivo'} para ${diseaseLabel}`}>
          {[0, .25, .5, .75, 1].map((fraction) => {
            const lineY = top + plotHeight * fraction
            return <line key={fraction} x1={left} x2={width - 22} y1={lineY} y2={lineY} className="analytics-grid-line" />
          })}
          <path d={band} className="analytics-confidence-band" />
          <path d={line(central)} className="analytics-history-observed" />
          {componentNames.map((name, componentIndex) => {
            const values = points.map((point) => point.component_predictions[name]).filter((value): value is number => typeof value === 'number')
            if (values.length !== points.length) return null
            return <path key={name} d={line(values)} fill="none" stroke={colors[componentIndex % colors.length]} strokeWidth="2" strokeDasharray="6 5"><title>{name}</title></path>
          })}
          {points.map((point, index) => <circle key={point.target_week} cx={x(index)} cy={y(point.predicted_cases)} r="4" className="analytics-history-point"><title>{formatDate(point.target_week)}: {formatNumber(point.predicted_cases)} casos · IC {formatNumber(point.lower_bound)}–{formatNumber(point.upper_bound)}</title></circle>)}
          {points.map((point, index) => <text key={point.target_week} x={x(index)} y={height - 13} textAnchor="middle" className="analytics-axis-label">{formatDate(point.target_week)}</text>)}
        </svg>
      </div>
      <div className="analytics-model-metrics">
        {points.map((point) => <div key={`${point.target_week}-${point.model_version}`}><span>{formatDate(point.target_week)}</span><strong>{formatNumber(point.predicted_cases)} casos</strong><small>Modelo {point.model_version} · {point.municipalities} municipios</small></div>)}
      </div>
    </>
  )
}

export default function AnalyticsStudio({ diseaseId, horizon, territories = [], selectedTerritoryCode = '', onSelectTerritory }: AnalyticsStudioProps) {
  const [view, setView] = useState<AnalyticsView>('current')
  const [territory, setTerritory] = useState('national')
  const [territoryDraft, setTerritoryDraft] = useState('national')
  const [summary, setSummary] = useState<AnalyticsSummary | null>(null)
  const [series, setSeries] = useState<AnalyticsSeries | null>(null)
  const [forecast, setForecast] = useState<AnalyticsForecastSeries | null>(null)
  const [forecastState, setForecastState] = useState<LoadState>('loading')
  const [forecastError, setForecastError] = useState('')
  const [state, setState] = useState<LoadState>('loading')
  const [error, setError] = useState('')
  const [reloadKey, setReloadKey] = useState(0)
  const diseaseLabel = diseases.find((item) => item.id === diseaseId)?.label ?? diseaseId
  const territoryLabel = territory === 'national'
    ? 'Colombia · Nacional'
    : territories.find((item) => item.cod_dane === territory)?.municipality ?? territory

  useEffect(() => {
    const nextTerritory = selectedTerritoryCode || 'national'
    setTerritory(nextTerritory)
    setTerritoryDraft(nextTerritory)
  }, [selectedTerritoryCode])

  useEffect(() => {
    let active = true
    setState('loading')
    setError('')
    setForecastState('loading')
    setForecastError('')
    Promise.allSettled([
      proraApi.analytics.summary(diseaseId, territory),
      proraApi.analytics.series(diseaseId, territory),
      proraApi.analytics.forecastSeries(diseaseId, territory, horizon),
    ]).then(([summaryResult, seriesResult, forecastResult]) => {
      if (!active) return
      const nextSummary = summaryResult.status === 'fulfilled' ? summaryResult.value : null
      const nextSeries = seriesResult.status === 'fulfilled' ? seriesResult.value : null
      const nextForecast = forecastResult.status === 'fulfilled' ? forecastResult.value : null
      setSummary(nextSummary)
      setSeries(nextSeries)
      setForecast(nextForecast)
      if (forecastResult.status === 'fulfilled') setForecastState(nextForecast?.points.length ? 'live' : 'empty')
      else {
        setForecastState('error')
        setForecastError(forecastFailureMessage(forecastResult.reason))
      }
      const hasData = Boolean(nextSummary?.latest || nextSeries?.points.length || nextForecast?.points.length)
      const allFailed = [summaryResult, seriesResult, forecastResult].every((result) => result.status === 'rejected')
      setState(hasData || !allFailed ? 'live' : 'error')
      if (allFailed) setError('La API de analítica no está disponible o rechazó los filtros solicitados.')
    })
    return () => { active = false }
  }, [diseaseId, horizon, territory, reloadKey])

  const applyTerritory = () => {
    const normalized = territoryDraft.trim().toLowerCase()
    if (normalized === 'national' || /^\d{2}$/.test(normalized) || /^\d{5}$/.test(normalized)) {
      setTerritory(normalized)
      if (/^\d{5}$/.test(normalized)) onSelectTerritory?.(normalized)
      return
    }
    setError("Use 'national', un código departamental de 2 dígitos o un DIVIPOLA de 5 dígitos.")
  }

  const currentBars = useMemo(() => {
    const values = [
      summary?.previous ? { label: formatDate(summary.previous.week), value: summary.previous.observed_cases } : null,
      summary?.latest ? { label: formatDate(summary.latest.week), value: summary.latest.observed_cases } : null,
    ].filter((item): item is { label: string; value: number } => Boolean(item))
    const maximum = Math.max(...values.map((item) => item.value), 1)
    return values.map((item) => ({ ...item, width: (item.value / maximum) * 100 }))
  }, [summary])

  const tabs: { id: AnalyticsView; label: string; icon: typeof LineChart }[] = [
    { id: 'history', label: 'Histórico', icon: LineChart },
    { id: 'current', label: 'Último corte', icon: BarChart3 },
    { id: 'forecast', label: 'Predicción IA', icon: BrainCircuit },
  ]

  return (
    <section className="analytics-studio" aria-labelledby="analytics-title">
      <header className="analytics-header">
        <div><span className="analytics-eyebrow"><Activity size={15} /> Inteligencia epidemiológica</span><h2 id="analytics-title">Análisis de {diseaseLabel}</h2><p>Histórico observado, último corte y resultados del modelo se presentan por separado, con su vigencia explícita, desde la API de PRORA.</p></div>
        <div className="analytics-cutoff"><Clock3 size={17} /><span><small>Último corte observado</small><strong>{formatDate(summary?.latest?.week)}</strong></span></div>
      </header>

      <div className="analytics-navigation">
        <div className="analytics-tabs" role="tablist">
          {tabs.map(({ id, label, icon: Icon }) => <button type="button" role="tab" key={id} className={view === id ? 'is-active' : ''} aria-selected={view === id} onClick={() => setView(id)}><Icon size={17} /> {label}</button>)}
        </div>
        <div className="analytics-filters">
          <div className="analytics-territory-field"><span>Territorio de análisis</span><SearchableSelect value={territoryDraft} onChange={setTerritoryDraft} ariaLabel="Territorio para analítica" searchPlaceholder="Buscar municipio, departamento o código DANE…" options={[{ value: 'national', label: 'Colombia · Nacional', group: 'Cobertura nacional' }, ...territories.map((item) => ({ value: item.cod_dane, label: `${item.municipality} · ${item.department}`, group: `Municipios con registros históricos (${territories.length})`, searchText: `${item.cod_dane} ${item.department}` }))]} /></div>
          <button className="button button--secondary" type="button" onClick={applyTerritory}>Aplicar</button>
          <div className="analytics-filter-context" aria-label="Filtros sincronizados con el tablero"><span>Evento</span><strong>{diseaseLabel}</strong></div>
          <div className="analytics-filter-context"><span>Horizonte</span><strong>{horizon} semanas</strong></div>
        </div>
      </div>

      {state === 'loading' && <div className="empty-state"><LoaderCircle className="spin" size={28} /><h3>Consultando analítica</h3><p>Recuperando observaciones, corte vigente y pronósticos.</p></div>}
      {(state === 'empty' || state === 'error') && <EmptyPanel error={state === 'error' ? error : undefined} onRetry={() => setReloadKey((value) => value + 1)} />}

      {state === 'live' && view === 'history' && (
        <div className="analytics-view analytics-view--history">
          {series?.points.length ? <><div className="analytics-summary-row"><div><span>Primer corte</span><strong>{formatDate(series.points[0].week)}</strong></div><div><span>Último corte</span><strong>{formatDate(series.points[series.points.length - 1]?.week)}</strong></div><div><span>Municipios con casos notificados</span><strong>{series.points[series.points.length - 1]?.municipalities_with_notified_cases ?? '—'}</strong></div></div><SeriesChart series={series} diseaseLabel={diseaseLabel} /></> : <EmptyPanel onRetry={() => setReloadKey((value) => value + 1)} />}
        </div>
      )}

      {state === 'live' && view === 'current' && (
        <div className="analytics-view analytics-view--current">
          {summary?.latest ? <><div className={`analytics-data-status analytics-data-status--${summary.data_status}`}><Info size={16} /><span><strong>{summary.data_status === 'fresh' ? 'Corte vigente' : 'Corte histórico, no vigente'}</strong> {summary.data_status === 'fresh' ? 'Puede utilizarse como contexto operacional según los protocolos de la entidad.' : `La última observación disponible corresponde al ${formatDate(summary.latest.week)}. No se presenta como situación epidemiológica actual.`}</span></div><div className="analytics-current-layout"><div className="analytics-bars-panel"><div className="analytics-chart-heading"><div><h3>Casos observados por corte</h3><p>Comparación directa de las dos últimas semanas disponibles.</p></div><span className="analytics-live-pill"><i /> {summary.data_status === 'fresh' ? 'Dato vigente' : 'Dato rezagado'}</span></div><div className="analytics-bars">{currentBars.map((item) => <div className="analytics-bar-row" key={item.label}><span className="analytics-bar-label">{item.label}</span><span className="analytics-bar-track"><i style={{ width: `${item.width}%` }} /></span><strong>{formatNumber(item.value)}</strong></div>)}</div></div><aside className="analytics-current-detail"><span className="analytics-detail-kicker">Lectura del último corte</span><div className="analytics-detail-icon"><Activity size={21} /></div><h3>{diseaseLabel}</h3><strong className="analytics-detail-value">{formatNumber(summary.latest.observed_cases)}</strong><span className="analytics-detail-unit">casos observados</span><div className={`analytics-detail-trend${summary.percent_change != null && summary.percent_change < 0 ? ' is-down' : ''}`}><span><strong>{summary.percent_change == null ? 'Sin comparación' : `${summary.percent_change >= 0 ? '+' : ''}${formatNumber(summary.percent_change)}%`}</strong> frente al corte anterior</span></div><div className="analytics-detail-note"><Info size={16} /><span>{summary.latest.is_preliminary ? 'Corte preliminar sujeto a actualización.' : 'Corte marcado como consolidado por la API.'}</span></div></aside></div></> : <EmptyPanel onRetry={() => setReloadKey((value) => value + 1)} />}
        </div>
      )}

      {state === 'live' && view === 'forecast' && (
        <div className="analytics-view analytics-view--forecast">
          {forecastState === 'loading' && <div className="empty-state"><LoaderCircle className="spin" size={28} /><h3>Consultando predicción</h3><p>Esperando una respuesta específica del endpoint de pronósticos.</p></div>}
          {forecastState === 'live' && forecast && <ForecastChart forecast={forecast} diseaseLabel={diseaseLabel} />}
          {forecastState === 'empty' && <EmptyPanel onRetry={() => setReloadKey((value) => value + 1)} />}
          {forecastState === 'error' && <EmptyPanel error={forecastError} onRetry={() => setReloadKey((value) => value + 1)} />}
        </div>
      )}

      <footer className="analytics-footer">
        <span><CalendarRange size={15} /> Territorio consultado: {territoryLabel}</span>
        <span>Fuentes: {summary?.sources.length ? summary.sources.map((source) => `${source.institution} · ${source.name}`).join(', ') : 'sin procedencia publicada'}</span>
        <span>{forecast?.points[0]?.model_version ? `Modelo ${forecast.points[0].model_version} · ${forecast.metadata.forecast_mode === 'operational' ? 'operativo' : 'retrospectivo'}` : forecastState === 'error' ? 'Pronóstico: consulta fallida' : 'Sin pronóstico publicado'}</span>
      </footer>
    </section>
  )
}
