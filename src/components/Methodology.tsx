import {
  Activity,
  BadgeCheck,
  BrainCircuit,
  CalendarRange,
  Database,
  FileCheck2,
  Fingerprint,
  GitBranch,
  Info,
  LoaderCircle,
  RefreshCw,
  Scale,
  ShieldCheck,
  TriangleAlert,
} from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import {
  proraApi,
  type ModelMetadata,
  type ModelPortfolioReadiness,
  type ModelTrace,
  type ModelVersion,
} from '../lib/api'

type DiseaseId = 'dengue' | 'malaria' | 'chikunguna' | 'zika' | 'leishmaniasis' | 'ira'
type LoadState = 'loading' | 'live' | 'empty' | 'error'

const diseases: { id: DiseaseId; label: string }[] = [
  { id: 'dengue', label: 'Dengue' },
  { id: 'malaria', label: 'Malaria' },
  { id: 'chikunguna', label: 'Chikunguña' },
  { id: 'zika', label: 'Zika' },
  { id: 'leishmaniasis', label: 'Leishmaniasis' },
  { id: 'ira', label: 'IRA' },
]

const formatDate = (value?: string | null) => value
  ? new Intl.DateTimeFormat('es-CO', { dateStyle: 'medium', timeStyle: value.includes('T') ? 'short' : undefined }).format(new Date(/^\d{4}-\d{2}-\d{2}$/.test(value) ? `${value}T00:00:00` : value))
  : 'No informado'
const formatMetric = (value: number) => new Intl.NumberFormat('es-CO', { maximumFractionDigits: 4 }).format(value)
const shortHash = (value?: string | null) => value ? `${value.slice(0, 12)}…${value.slice(-8)}` : 'No informado'
const readableLabel = (value: string) => value.replace(/_/g, ' ').replace(/\b\w/g, (letter: string) => letter.toUpperCase())
const limitationLabels: Record<string, string> = {
  no_epidemiological_observations: 'Sin observaciones epidemiológicas',
  no_explicit_zero_case_reports: 'La fuente no publica semanas con cero casos',
  low_reporting_density: 'Panel semanal incompleto',
  stale_or_missing_epidemiological_cutoff: 'Corte epidemiológico histórico o ausente',
  missing_trained_horizons: 'Faltan horizontes entrenados',
}
const covariateLabels: Record<string, string> = {
  climate: 'Clima IDEAM',
  pai_municipal: 'PAI municipal',
  deforestation: 'Deforestación',
  socioeconomic: 'Contexto social',
  urban_rural: 'Composición urbano-rural',
}

export default function Methodology() {
  const [disease, setDisease] = useState<DiseaseId>('dengue')
  const [horizon, setHorizon] = useState<3 | 4>(4)
  const [metadata, setMetadata] = useState<ModelMetadata | null>(null)
  const [versions, setVersions] = useState<ModelVersion[]>([])
  const [selectedVersion, setSelectedVersion] = useState('')
  const [trace, setTrace] = useState<ModelTrace | null>(null)
  const [portfolio, setPortfolio] = useState<ModelPortfolioReadiness | null>(null)
  const [portfolioState, setPortfolioState] = useState<LoadState>('loading')
  const [state, setState] = useState<LoadState>('loading')
  const [traceState, setTraceState] = useState<LoadState>('empty')
  const [reloadKey, setReloadKey] = useState(0)

  useEffect(() => {
    let active = true
    setPortfolioState('loading')
    proraApi.models.readiness()
      .then((result) => {
        if (!active) return
        setPortfolio(result)
        setPortfolioState(result.diseases.length ? 'live' : 'empty')
      })
      .catch(() => {
        if (!active) return
        setPortfolio(null)
        setPortfolioState('error')
      })
    return () => { active = false }
  }, [reloadKey])

  useEffect(() => {
    let active = true
    setState('loading')
    setMetadata(null)
    setVersions([])
    setTrace(null)
    Promise.allSettled([
      proraApi.models.metadata(disease, horizon),
      proraApi.models.versions(disease, horizon),
    ]).then(([metadataResult, versionsResult]) => {
      if (!active) return
      const nextMetadata = metadataResult.status === 'fulfilled' ? metadataResult.value : null
      const nextVersions = versionsResult.status === 'fulfilled' ? versionsResult.value : []
      setMetadata(nextMetadata)
      setVersions(nextVersions)
      const preferred = nextMetadata?.version || nextVersions[0]?.version || ''
      setSelectedVersion(preferred)
      if (nextMetadata || nextVersions.length) setState('live')
      else if (metadataResult.status === 'rejected' && versionsResult.status === 'rejected') setState('error')
      else setState('empty')
    })
    return () => { active = false }
  }, [disease, horizon, reloadKey])

  useEffect(() => {
    if (!selectedVersion) {
      setTrace(null)
      setTraceState('empty')
      return
    }
    let active = true
    setTraceState('loading')
    proraApi.models.trace(disease, horizon, selectedVersion)
      .then((result) => {
        if (!active) return
        setTrace(result)
        setTraceState('live')
      })
      .catch(() => {
        if (!active) return
        setTrace(null)
        setTraceState('error')
      })
    return () => { active = false }
  }, [disease, horizon, selectedVersion])

  const selectedVersionRecord = versions.find((item) => item.version === selectedVersion) ?? null
  const selectedTrace = trace?.version === selectedVersion ? trace : null
  const selectedMetadata = metadata?.version === selectedVersion ? metadata : null
  const metricEntries = useMemo(() => Object.entries(selectedTrace?.metrics ?? selectedMetadata?.metrics ?? {})
    .filter(([key, value]) => key !== '_trace' && typeof value === 'number')
    .map(([key, value]) => [key, value as number] as const), [selectedMetadata, selectedTrace])
  const datasetEntries = useMemo(() => Object.entries(selectedTrace?.dataset ?? {})
    .filter(([, value]) => value != null && typeof value !== 'object'), [selectedTrace])
  const modelLabel = diseases.find((item) => item.id === disease)?.label ?? disease
  const selectedStage = selectedTrace?.stage ?? selectedVersionRecord?.stage ?? selectedMetadata?.status ?? 'No informado'
  const selectedCreatedAt = selectedTrace?.created_at ?? selectedVersionRecord?.created_at ?? selectedMetadata?.trained_at
  const selectedActivatedAt = selectedTrace?.activated_at ?? selectedVersionRecord?.activated_at ?? selectedMetadata?.activated_at
  const selectedReadiness = portfolio?.diseases.find((item) => item.disease === disease) ?? null
  const trainedHorizons = selectedReadiness?.models.filter((item) => item.state === 'trained') ?? []

  return (
    <section className="workspace-view methodology-view" aria-labelledby="methodology-title">
      <header className="view-heading">
        <div><span className="eyebrow"><BrainCircuit size={15} /> Registro de modelos</span><h1 id="methodology-title">Metodología y trazabilidad</h1><p>Metadatos, validación y linaje leídos directamente del registro operativo.</p></div>
        <div className="heading-actions">
          <label className="form-field"><span>Evento</span><select value={disease} onChange={(event) => setDisease(event.target.value as DiseaseId)}>{diseases.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label>
          <label className="form-field"><span>Horizonte</span><select value={horizon} onChange={(event) => setHorizon(Number(event.target.value) as 3 | 4)}><option value={3}>3 semanas</option><option value={4}>4 semanas</option></select></label>
          <button className="button button-secondary" type="button" onClick={() => setReloadKey((value) => value + 1)}><RefreshCw size={16} /> Actualizar</button>
        </div>
      </header>

      <section className="content-card portfolio-readiness" aria-labelledby="portfolio-readiness-title">
        <div className="card-heading-row">
          <div><span className="eyebrow">Semáforo de evidencia</span><h2 id="portfolio-readiness-title">Preparación por enfermedad</h2><p>Separa suficiencia para investigación, modelo entrenado y elegibilidad operacional actual.</p></div>
          {portfolioState === 'loading' ? <LoaderCircle className="spin" size={22} /> : <ShieldCheck size={22} />}
        </div>
        {portfolioState === 'error' && <div className="technical-note technical-note--warning"><TriangleAlert size={18} /><span>No fue posible consultar el diagnóstico de preparación del backend.</span></div>}
        {portfolio && <>
          <div className="portfolio-disease-grid">
            {diseases.map((item) => {
              const readiness = portfolio.diseases.find((entry) => entry.disease === item.id)
              const trained = readiness?.models.filter((model) => model.state === 'trained').length ?? 0
              return <button key={item.id} type="button" className={disease === item.id ? 'is-active' : ''} onClick={() => setDisease(item.id)}>
                <span><i data-state={readiness?.readiness_level ?? 'insufficient'} />{item.label}</span>
                <strong>{readiness?.data.total_cases.toLocaleString('es-CO') ?? '—'} casos</strong>
                <small>{readiness?.data.week_start ? `${formatDate(readiness.data.week_start)} – ${formatDate(readiness.data.week_end)}` : 'Sin periodo observado'}</small>
                <em>{trained}/2 horizontes entrenados</em>
              </button>
            })}
          </div>
          {selectedReadiness && <div className="readiness-detail-grid">
            <div className="readiness-status-block">
              <span className={`readiness-badge readiness-badge--${selectedReadiness.readiness_level}`}>{selectedReadiness.readiness_level === 'operational' ? 'Operacional' : selectedReadiness.readiness_level === 'research_only' ? 'Solo investigación' : 'Evidencia insuficiente'}</span>
              <strong>{modelLabel}</strong>
              <p>{selectedReadiness.operational_forecast_eligible ? 'Cumple la puerta de datos para emitir pronósticos actuales.' : 'No puede emitir alertas actuales con el corte y la completitud disponibles.'}</p>
            </div>
            <dl className="readiness-facts">
              <div><dt>Observaciones</dt><dd>{selectedReadiness.data.observed_rows.toLocaleString('es-CO')}</dd></div>
              <div><dt>Territorios</dt><dd>{selectedReadiness.data.territories.toLocaleString('es-CO')}</dd></div>
              <div><dt>Semanas únicas</dt><dd>{selectedReadiness.data.unique_weeks.toLocaleString('es-CO')}</dd></div>
              <div><dt>Modelos</dt><dd>{trainedHorizons.length ? trainedHorizons.map((item) => `H${item.horizon}`).join(', ') : 'Sin entrenar'}</dd></div>
              <div><dt>Benchmark OOF</dt><dd>{trainedHorizons.length && trainedHorizons.every((item) => item.validation.benchmark_available === true) ? 'Disponible' : 'Pendiente'}</dd></div>
              <div><dt>Corte</dt><dd>{formatDate(selectedReadiness.data.week_end)}</dd></div>
            </dl>
            <div className="readiness-limitations">
              <span>Bloqueos vigentes</span>
              {selectedReadiness.limitations.length ? <ul>{selectedReadiness.limitations.map((item) => <li key={item}><TriangleAlert size={14} /> {limitationLabels[item] ?? readableLabel(item)}</li>)}</ul> : <p><BadgeCheck size={15} /> Sin bloqueos de datos registrados.</p>}
            </div>
          </div>}
          <div className="covariate-readiness" aria-label="Cobertura de variables explicativas">
            {Object.entries(portfolio.covariate_inventory).filter(([key]) => key in covariateLabels).map(([key, value]) => <div key={key} data-state={value.status}>
              <span>{covariateLabels[key]}</span><strong>{value.status === 'available' ? 'Disponible' : value.status === 'partial' ? 'Parcial' : 'Pendiente'}</strong><small>{value.rows != null ? `${value.rows.toLocaleString('es-CO')} filas · ${value.territories ?? 0} municipios` : value.territories ? `${value.territories.toLocaleString('es-CO')} municipios validados` : value.reason ?? 'Sin filas validadas'}</small>
            </div>)}
          </div>
        </>}
      </section>

      {state === 'loading' && <div className="content-card empty-state"><LoaderCircle className="spin" size={30} /><h2>Consultando el registro</h2><p>Recuperando versiones, métricas y linaje del modelo.</p></div>}
      {state === 'empty' && <div className="content-card empty-state"><BrainCircuit size={30} /><h2>Sin modelo registrado</h2><p>No existe una versión para {modelLabel} con horizonte de {horizon} semanas.</p></div>}
      {state === 'error' && <div className="content-card empty-state"><Info size={30} /><h2>Registro no disponible</h2><p>No fue posible consultar los endpoints de modelos. No se muestran valores de respaldo.</p><button className="button button-secondary" type="button" onClick={() => setReloadKey((value) => value + 1)}>Reintentar</button></div>}

      {state === 'live' && (
        <>
          <section className="content-card methodology-hero-card">
            <div><span className="eyebrow"><Activity size={14} /> Modelo seleccionado</span><h2>{modelLabel} · {selectedVersion || 'Sin versión activa'}</h2><p>El estado y las fechas siguientes provienen del registro del backend.</p></div>
            <div className="model-version-card"><span>Estado de esta versión</span><strong>{selectedStage}</strong><small>Creada: {formatDate(selectedCreatedAt)}</small><small>{selectedActivatedAt ? `Activada: ${formatDate(selectedActivatedAt)}` : 'Sin activación registrada'}</small></div>
          </section>

          <div className="methodology-grid">
            <article className="content-card">
              <div className="card-heading-row"><div><span className="eyebrow">Versionado</span><h2>Versiones registradas</h2><p>Seleccione una versión para consultar su traza verificable.</p></div><GitBranch size={21} /></div>
              {versions.length ? <div className="source-metadata">{versions.map((version) => <button key={version.version} type="button" className={`priority-item${selectedVersion === version.version ? ' is-active' : ''}`} onClick={() => setSelectedVersion(version.version)}><span className="priority-item__copy"><strong>{version.version}</strong><small>{version.stage} · creada {formatDate(version.created_at)}</small><em>{version.activated_at ? `Activada ${formatDate(version.activated_at)}` : 'Sin activación registrada'}</em></span><span className="priority-item__score"><strong>{version.temporal_mae == null ? '—' : formatMetric(version.temporal_mae)}</strong><small>MAE temporal</small></span></button>)}</div> : <div className="empty-state"><Info size={24} /><h3>Sin historial de versiones</h3><p>El endpoint respondió sin versiones para este filtro.</p></div>}
            </article>

            <article className="content-card">
              <div className="card-heading-row"><div><span className="eyebrow">Desempeño validado</span><h2>Métricas publicadas</h2><p>No se calculan métricas en el navegador.</p></div><BadgeCheck size={21} /></div>
              {metricEntries.length ? <div className="metric-grid methodology-metrics">{metricEntries.map(([key, value]) => <div className="methodology-metric" key={key}><span><Activity size={18} /></span><strong>{formatMetric(value)}</strong><b>{readableLabel(key)}</b><small>Valor registrado</small></div>)}</div> : <div className="empty-state"><Info size={24} /><h3>Sin métricas numéricas</h3><p>La versión existe, pero el registro no publicó métricas numéricas.</p></div>}
            </article>
          </div>

          <article className="content-card traceability-card">
            <div className="traceability-heading"><span className="traceability-icon"><Fingerprint size={21} /></span><div><h2>Ficha de trazabilidad</h2><p>Hashes, instantánea y artefacto obtenidos del endpoint de traza.</p></div></div>
            {traceState === 'loading' && <div className="empty-state"><LoaderCircle className="spin" size={26} /><p>Verificando artefacto y linaje…</p></div>}
            {traceState === 'error' && <div className="empty-state"><Info size={26} /><h3>Traza no disponible</h3><p>La versión está registrada, pero el backend no pudo verificar o devolver su traza.</p></div>}
            {traceState === 'live' && trace && <>
              <div className="traceability-steps">
                <span><small>Trabajo de entrenamiento</small><strong>{trace.training_job_id || 'No informado'}</strong></span>
                <span><small>Huella de datos</small><strong title={trace.data_fingerprint ?? ''}>{shortHash(trace.data_fingerprint)}</strong></span>
                <span><small>Instantánea</small><strong title={trace.dataset_snapshot_sha256 ?? ''}>{shortHash(trace.dataset_snapshot_sha256)}</strong></span>
                <span><small>Artefacto</small><strong title={trace.artifact_sha256}>{shortHash(trace.artifact_sha256)}</strong></span>
              </div>
              <div className="metric-strip">
                <article className="metric-card compact"><span className="metric-icon"><ShieldCheck size={19} /></span><div><strong>{trace.artifact_integrity_valid ? 'Verificada' : 'No verificada'}</strong><span>integridad del artefacto</span></div></article>
                <article className="metric-card compact"><span className="metric-icon"><CalendarRange size={19} /></span><div><strong>{formatDate(trace.training_period.from)}</strong><span>inicio del entrenamiento</span></div></article>
                <article className="metric-card compact"><span className="metric-icon"><FileCheck2 size={19} /></span><div><strong>{trace.fold_metrics.length}</strong><span>folds documentados</span></div></article>
                <article className="metric-card compact"><span className="metric-icon"><Database size={19} /></span><div><strong>{trace.features.length}</strong><span>variables registradas</span></div></article>
              </div>
              {datasetEntries.length ? <dl className="source-metadata">{datasetEntries.map(([key, value]) => <div key={key}><dt>{readableLabel(key)}</dt><dd>{String(value)}</dd></div>)}</dl> : <div className="technical-note"><Info size={17} /><span>La traza no expone atributos públicos adicionales de la instantánea.</span></div>}
            </>}
          </article>
        </>
      )}

      <article className="responsible-use-banner"><span><Scale size={22} /></span><div><strong>Interpretación responsable</strong><p>Una predicción orienta priorización preventiva; no reemplaza la vigilancia de campo, el criterio epidemiológico ni un diagnóstico clínico.</p></div><ShieldCheck size={25} /></article>
    </section>
  )
}
