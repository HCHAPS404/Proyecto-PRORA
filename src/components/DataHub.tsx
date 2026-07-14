import { useCallback, useEffect, useMemo, useState } from 'react'
import type { LucideIcon } from 'lucide-react'
import {
  Activity,
  BookOpenText,
  Braces,
  Check,
  CheckCircle2,
  CloudSun,
  Database,
  ExternalLink,
  FileArchive,
  FileSpreadsheet,
  Fingerprint,
  Globe2,
  Info,
  KeyRound,
  Leaf,
  Link2,
  LoaderCircle,
  LockKeyhole,
  Map as MapIcon,
  RefreshCw,
  Search,
  ServerCog,
  ShieldCheck,
  Syringe,
  UsersRound,
  XCircle,
} from 'lucide-react'
import {
  API_BASE_URL,
  apiProfile,
  proraApi,
  type ApiUser,
  type DataSourceRecord,
  type IngestionRunRecord,
  type SnapshotManifest,
  type StoredDatasetInventory,
} from '../lib/api'

type CatalogState = 'loading' | 'live' | 'empty' | 'offline'
type DatasetType = 'epidemiology' | 'climate' | 'vaccination' | 'deforestation' | 'socioeconomic'
type SupportState = 'loading' | 'available' | 'unavailable'
type ProbeState = 'idle' | 'testing' | 'connected' | 'failed'

const numberFormat = new Intl.NumberFormat('es-CO')
const formatDate = (value?: string | null) => {
  if (!value) return 'No informado'
  const parsed = new Date(/^\d{4}-\d{2}-\d{2}$/.test(value) ? `${value}T00:00:00` : value)
  if (Number.isNaN(parsed.getTime())) return String(value)
  return new Intl.DateTimeFormat('es-CO', {
    dateStyle: 'medium',
    timeStyle: /^\d{4}-\d{2}-\d{2}$/.test(value) ? undefined : 'short',
  }).format(parsed)
}
const formatValue = (value: unknown) => {
  if (value == null || value === '') return 'No informado'
  if (typeof value === 'boolean') return value ? 'Sí' : 'No'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}
const shortHash = (value?: string | null) => value ? `${value.slice(0, 12)}…${value.slice(-8)}` : 'No informado'

function socrataProbeUrl(endpoint: string, datasetId: string) {
  const url = new URL(endpoint.trim())
  const id = datasetId.trim()
  if (!url.pathname.toLowerCase().endsWith('.json')) {
    const path = url.pathname.replace(/\/$/, '')
    url.pathname = path.toLowerCase().endsWith(`/resource/${id.toLowerCase()}`)
      ? `${path}.json`
      : `${path}/${encodeURIComponent(id)}.json`
  }
  url.searchParams.set('$limit', '1')
  return url.toString()
}

function sourceAppearance(source: DataSourceRecord): { icon: LucideIcon; accent: string } {
  if (source.institution.toUpperCase().includes('IDEAM')) return source.id.includes('deforestation') ? { icon: Leaf, accent: 'green' } : { icon: CloudSun, accent: 'cyan' }
  if (source.institution.toUpperCase().includes('DANE')) return { icon: UsersRound, accent: 'violet' }
  if (source.id.toLowerCase().includes('pai')) return { icon: Syringe, accent: 'blue' }
  return { icon: Activity, accent: 'teal' }
}

function sourceStatus(source: DataSourceRecord, run?: IngestionRunRecord) {
  if (run?.status === 'running' || run?.status === 'pending') return { label: 'Ingesta en proceso', className: 'validando', icon: RefreshCw }
  if (run?.status === 'failed') return { label: 'Último intento falló', className: 'error', icon: XCircle }
  if (run?.status === 'partial') return { label: 'Ingesta parcial', className: 'validando', icon: Info }
  if (run?.status === 'succeeded') return { label: 'Ingesta completada', className: 'actualizada', icon: CheckCircle2 }
  if (source.last_success_at) return { label: 'Con ingesta previa', className: 'actualizada', icon: CheckCircle2 }
  return { label: 'Sin ingesta registrada', className: 'programada', icon: Info }
}

function catalogStatus(source: DataSourceRecord) {
  const statuses = {
    active: { label: 'Activa', className: 'actualizada' },
    degraded: { label: 'Degradada', className: 'error' },
    requires_configuration: { label: 'Requiere configuración', className: 'validando' },
    disabled: { label: 'Deshabilitada', className: 'programada' },
  } as const
  return statuses[source.status]
}

function sourceKind(source: DataSourceRecord) {
  if (source.source_type === 'socrata') return { label: 'API tabular', detail: 'Consulta SODA', className: 'api', icon: Braces }
  if (source.source_type === 'arcgis-rest') return { label: 'Servicio geográfico', detail: 'ArcGIS REST', className: 'geo', icon: MapIcon }
  if (source.source_type === 'official-pdf') return { label: 'Referencia documental', detail: 'Boletín oficial', className: 'reference', icon: BookOpenText }
  if (source.source_type === 'institutional-file') return { label: 'Archivo institucional', detail: 'Carga autorizada', className: 'file', icon: FileArchive }
  return { label: 'Archivo publicado', detail: source.source_type, className: 'file', icon: FileArchive }
}

function templateDatasetType(source: DataSourceRecord): DatasetType | null {
  const explicit = source.configuration.dataset_type
  if (typeof explicit === 'string') {
    if (explicit.startsWith('epidemiology') && explicit !== 'epidemiology_current_reference') return 'epidemiology'
    if (explicit.startsWith('climate')) return 'climate'
    if (explicit.startsWith('vaccination')) return 'vaccination'
    if (explicit === 'deforestation') return 'deforestation'
    if (explicit === 'socioeconomic') return 'socioeconomic'
    return null
  }
  const inferred = inferDatasetType(source)
  return inferred === 'epidemiology' && !source.id.includes('sivigila') ? null : inferred
}

function inferDatasetType(source: DataSourceRecord): DatasetType {
  const explicit = source.configuration.dataset_type
  if (typeof explicit === 'string' && ['epidemiology', 'climate', 'vaccination', 'deforestation', 'socioeconomic'].includes(explicit)) return explicit as DatasetType
  const id = source.id.toLowerCase()
  if (id.includes('pai') || id.includes('vacc')) return 'vaccination'
  if (id.includes('climate') || id.includes('precip') || id.includes('temperature') || id.includes('humidity') || id.includes('station')) return 'climate'
  if (id.includes('deforestation') || id.includes('forest')) return 'deforestation'
  if (id.includes('dane') || id.includes('socio')) return 'socioeconomic'
  return 'epidemiology'
}

export type DataHubProps = { onNotify?: (message: string) => void }

export default function DataHub({ onNotify }: DataHubProps) {
  const profile = apiProfile.load<ApiUser>()
  const canManageSources = profile?.role === 'analyst' || profile?.role === 'admin'
  const [sources, setSources] = useState<DataSourceRecord[]>([])
  const [runs, setRuns] = useState<IngestionRunRecord[]>([])
  const [inventory, setInventory] = useState<StoredDatasetInventory[]>([])
  const [manifest, setManifest] = useState<SnapshotManifest | null>(null)
  const [catalogState, setCatalogState] = useState<CatalogState>('loading')
  const [runsState, setRunsState] = useState<SupportState>('loading')
  const [inventoryState, setInventoryState] = useState<SupportState>('loading')
  const [query, setQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState('all')
  const [selectedSourceId, setSelectedSourceId] = useState('')
  const [probeSourceId, setProbeSourceId] = useState('')
  const [endpoint, setEndpoint] = useState('')
  const [datasetId, setDatasetId] = useState('')
  const [token, setToken] = useState('')
  const [connectionState, setConnectionState] = useState<ProbeState>('idle')
  const [probeResult, setProbeResult] = useState('')
  const [notice, setNotice] = useState('')
  const [syncingSources, setSyncingSources] = useState<Set<string>>(new Set())

  const loadCatalog = useCallback(async (notify = false) => {
    setCatalogState('loading')
    setRunsState('loading')
    setInventoryState('loading')
    try {
      const [sourcesResult, runsResult, inventoryResult] = await Promise.allSettled([
        proraApi.sources.list(),
        proraApi.sources.runs(200),
        proraApi.sources.inventory(),
      ])
      if (sourcesResult.status === 'rejected') throw sourcesResult.reason
      const records = sourcesResult.value
      const runRecords = runsResult.status === 'fulfilled' ? runsResult.value : []
      setSources(records)
      setRuns(runRecords)
      setInventory(inventoryResult.status === 'fulfilled' ? inventoryResult.value : [])
      setRunsState(runsResult.status === 'fulfilled' ? 'available' : 'unavailable')
      setInventoryState(inventoryResult.status === 'fulfilled' ? 'available' : 'unavailable')
      setSelectedSourceId((current) => records.some((source) => source.id === current) ? current : records[0]?.id ?? '')
      setProbeSourceId((current) => records.some((source) => source.id === current && source.source_type === 'socrata')
        ? current
        : records.find((source) => source.source_type === 'socrata' && source.status === 'active')?.id ?? '')
      setCatalogState(records.length ? 'live' : 'empty')
      if (notify) onNotify?.(records.length ? 'Catálogo actualizado desde la API' : 'La API no tiene fuentes registradas')
    } catch {
      setSources([])
      setRuns([])
      setInventory([])
      setRunsState('unavailable')
      setInventoryState('unavailable')
      setSelectedSourceId('')
      setCatalogState('offline')
      if (notify) onNotify?.('No fue posible consultar el catálogo del backend')
    }
  }, [onNotify])

  useEffect(() => { void loadCatalog() }, [loadCatalog])

  const latestBySource = useMemo(() => {
    const map = new Map<string, IngestionRunRecord>()
    runs.forEach((run) => { if (!map.has(run.source_id)) map.set(run.source_id, run) })
    return map
  }, [runs])
  const selectedSource = sources.find((source) => source.id === selectedSourceId) ?? null
  const selectedRun = selectedSource ? latestBySource.get(selectedSource.id) : undefined
  const selectedInventory = selectedSource ? inventory.find((item) => item.source_id === selectedSource.id) : undefined
  const probeSources = sources.filter((source) => source.source_type === 'socrata')
  const probeSource = probeSources.find((source) => source.id === probeSourceId) ?? null

  useEffect(() => {
    setEndpoint(probeSource?.endpoint ?? '')
    setDatasetId(probeSource?.dataset_id ?? '')
    setConnectionState('idle')
    setProbeResult('')
  }, [probeSource])

  useEffect(() => {
    if (!selectedRun) {
      setManifest(null)
      return
    }
    let active = true
    proraApi.sources.manifest(selectedRun.id)
      .then((result) => { if (active) setManifest(result) })
      .catch(() => { if (active) setManifest(null) })
    return () => { active = false }
  }, [selectedRun])

  const filteredSources = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase('es')
    return sources.filter((source) => {
      const run = latestBySource.get(source.id)
      const status = sourceStatus(source, run).className
      const matchesStatus = statusFilter === 'all' || status === statusFilter
      const kind = sourceKind(source)
      const matchesQuery = !normalized || `${source.name} ${source.institution} ${source.source_type} ${kind.label}`.toLocaleLowerCase('es').includes(normalized)
      return matchesStatus && matchesQuery
    })
  }, [latestBySource, query, sources, statusFilter])

  const storedSources = inventory.filter((item) => item.has_stored_data).length
  const storedRows = inventory.reduce((total, item) => total + item.rows, 0)
  const rowsRejected = inventory.length
    ? inventory.reduce((total, item) => total + item.rows_rejected_last_run, 0)
    : runs.reduce((total, run) => total + run.rows_rejected, 0)

  const showNotice = (message: string) => {
    setNotice(message)
    onNotify?.(message)
    window.setTimeout(() => setNotice(''), 3000)
  }

  const triggerSync = async (source: DataSourceRecord) => {
    setSyncingSources((current) => new Set(current).add(source.id))
    try {
      const run = await proraApi.sources.sync(source.id, { mode: 'incremental' })
      showNotice(`Ingesta ${run.status} para ${source.name}`)
      await loadCatalog()
    } catch (error) {
      showNotice(error instanceof Error ? error.message : 'No fue posible iniciar la ingesta.')
    } finally {
      setSyncingSources((current) => { const next = new Set(current); next.delete(source.id); return next })
    }
  }

  const downloadTemplate = async (source: DataSourceRecord) => {
    const datasetType = templateDatasetType(source)
    if (!datasetType) {
      showNotice('Esta fuente no tiene una plantilla canónica compatible.')
      return
    }
    try {
      const response = await fetch(`${API_BASE_URL}/sources/templates/${datasetType}`)
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      const url = URL.createObjectURL(await response.blob())
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = `prora-${datasetType}-template.csv`
      anchor.click()
      URL.revokeObjectURL(url)
      showNotice(`Plantilla canónica de ${source.name} descargada`)
    } catch {
      showNotice('No fue posible descargar la plantilla desde la API')
    }
  }

  const testConnection = async () => {
    if (!endpoint.trim() || !datasetId.trim()) return
    setConnectionState('testing')
    setProbeResult('')
    try {
      const probeUrl = socrataProbeUrl(endpoint, datasetId)
      const response = await fetch(probeUrl, { headers: token ? { 'X-App-Token': token } : undefined })
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      const payload: unknown = await response.json()
      setConnectionState('connected')
      setProbeResult(JSON.stringify({
        http_status: response.status,
        records_returned: Array.isArray(payload) ? payload.length : null,
        sample: payload,
      }, null, 2))
      showNotice('Lectura SODA verificada con una respuesta real')
    } catch (error) {
      setConnectionState('failed')
      setProbeResult(JSON.stringify({ error: error instanceof Error ? error.message : 'No fue posible conectar' }, null, 2))
      showNotice('La conexión no respondió. Verifique URL, identificador, CORS y token.')
    }
  }

  return (
    <section className="workspace-view data-hub" aria-labelledby="data-hub-title">
      <header className="view-heading">
        <div><span className="eyebrow"><Database size={15} /> Ecosistema de datos</span><h1 id="data-hub-title">Centro de datos</h1><p>Catálogo, ejecuciones y calidad observadas directamente en el backend de PRORA.</p></div>
        <div className="heading-actions"><button className="button button-secondary" type="button" onClick={() => void loadCatalog(true)}><RefreshCw className={catalogState === 'loading' ? 'spin' : ''} size={17} /> {catalogState === 'loading' ? 'Consultando…' : 'Actualizar catálogo'}</button><button className="button button-primary" type="button" onClick={() => document.getElementById('socrata-panel')?.scrollIntoView({ behavior: 'smooth' })}><Link2 size={17} /> Probar conexión</button></div>
      </header>

      {notice && <div className="inline-notice inline-notice-success" role="status"><Check size={16} /> {notice}</div>}

      <div className="metric-strip" aria-label="Resumen de datos persistidos">
        <article className="metric-card compact"><span className="metric-icon"><Database size={19} /></span><div><strong>{catalogState === 'loading' ? '…' : catalogState === 'live' || catalogState === 'empty' ? sources.length : '—'}</strong><span>fuentes en el catálogo</span><small>{catalogState === 'offline' ? 'Catálogo no disponible' : 'Registro del backend'}</small></div></article>
        <article className="metric-card compact"><span className="metric-icon"><CheckCircle2 size={19} /></span><div><strong>{inventoryState === 'loading' ? '…' : inventoryState === 'available' ? storedSources : '—'}</strong><span>fuentes con datos almacenados</span><small>{inventoryState === 'unavailable' ? 'Inventario no disponible' : 'No equivale a dato vigente'}</small></div></article>
        <article className="metric-card compact"><span className="metric-icon"><ServerCog size={19} /></span><div><strong>{inventoryState === 'loading' ? '…' : inventoryState === 'available' ? numberFormat.format(storedRows) : '—'}</strong><span>filas canónicas persistidas</span><small>Suma informada por el inventario</small></div></article>
        <article className="metric-card compact"><span className="metric-icon"><XCircle size={19} /></span><div><strong>{inventoryState === 'loading' ? '…' : inventoryState === 'available' ? numberFormat.format(rowsRejected) : '—'}</strong><span>rechazos del último proceso por fuente</span><small>No son casos epidemiológicos</small></div></article>
      </div>

      <div className="content-card source-catalog-card">
        <div className="card-heading-row"><div><h2>Catálogo de fuentes</h2><p>Cada tarjeta separa el canal de publicación, el corte del dato y el estado de ingesta.</p></div><div className="catalog-toolbar"><label className="search-field"><Search size={17} /><span className="sr-only">Buscar fuente</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Buscar fuente, entidad o tipo" /></label><select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)} aria-label="Filtrar por última ingesta"><option value="all">Todas las ingestas</option><option value="actualizada">Completadas</option><option value="validando">En proceso o parciales</option><option value="error">Con error</option><option value="programada">Sin ingesta</option></select></div></div>

        <div className="source-reading-guide" aria-label="Cómo leer el tipo de fuente">
          <article><span className="source-kind source-kind-api"><Braces size={15} /> API tabular</span><p>Se consulta por HTTP y devuelve filas estructuradas. La ingesta sigue siendo un proceso separado.</p></article>
          <article><span className="source-kind source-kind-file"><FileArchive size={15} /> Archivo publicado</span><p>ZIP, XLSX o capa geográfica procesada por lotes; no implica una API consultable.</p></article>
          <article><span className="source-kind source-kind-reference"><BookOpenText size={15} /> Referencia documental</span><p>Aporta contexto oficial reciente; no se mezcla silenciosamente con los casos municipales.</p></article>
          <article><span className="source-kind source-kind-geo"><Globe2 size={15} /> Servicio geográfico</span><p>Expone geometrías o indicadores espaciales mediante ArcGIS REST.</p></article>
        </div>

        {catalogState === 'loading' && <div className="empty-state"><LoaderCircle className="spin" size={29} /><h3>Consultando catálogo</h3><p>Recuperando fuentes y ejecuciones de ingesta.</p></div>}
        {catalogState === 'offline' && <div className="empty-state"><Info size={29} /><h3>Catálogo no disponible</h3><p>No se muestran fuentes de respaldo porque no provienen de la API.</p><button className="button button-secondary" type="button" onClick={() => void loadCatalog()}>Reintentar</button></div>}
        {catalogState === 'empty' && <div className="empty-state"><Database size={29} /><h3>Sin fuentes registradas</h3><p>La API respondió correctamente, pero el catálogo está vacío.</p></div>}

        {catalogState === 'live' && <div className="source-grid">{filteredSources.map((source) => {
          const run = latestBySource.get(source.id)
          const appearance = sourceAppearance(source)
          const status = sourceStatus(source, run)
          const availability = catalogStatus(source)
          const kind = sourceKind(source)
          const SourceIcon = appearance.icon
          const StatusIcon = status.icon
          const KindIcon = kind.icon
          const stored = inventory.find((item) => item.source_id === source.id)
          const reason = typeof source.configuration.reason === 'string' ? source.configuration.reason : null
          const coverage = typeof source.configuration.coverage === 'string' ? source.configuration.coverage : null
          const verifiedOn = typeof source.configuration.verified_on === 'string' ? source.configuration.verified_on : null
          const templateType = templateDatasetType(source)
          const canSync = canManageSources && source.status === 'active' && stored?.sync_enabled !== false
          return <article className={`source-card source-accent-${appearance.accent}${selectedSourceId === source.id ? ' is-selected' : ''}`} key={source.id}>
            <div className="source-card-header">
              <span className="source-icon"><SourceIcon size={21} /></span>
              <span className={`source-kind source-kind-${kind.className}`} title={kind.detail}><KindIcon size={13} /> {kind.label}</span>
            </div>
            <div className="source-status-row">
              <span className={`status-pill status-${status.className}`}><StatusIcon className={run?.status === 'running' ? 'spin' : ''} size={13} /> {runsState === 'unavailable' ? 'Historial no disponible' : status.label}</span>
              <span className={`catalog-state status-${availability.className}`}>Catálogo: {availability.label}</span>
            </div>
            <div className="source-identity"><span>{source.institution}</span><h3>{source.name}</h3><p>{reason || `${kind.detail}. Cobertura declarada: ${coverage || 'no informada'}.`}</p></div>
            <dl className="source-metadata">
              <div><dt>Corte de los datos</dt><dd>{stored?.period_end ? formatDate(stored.period_end) : 'No informado'}</dd></div>
              <div><dt>Última ingesta</dt><dd>{formatDate(stored?.last_ingestion_at || run?.finished_at || source.last_success_at)}</dd></div>
              <div><dt>Periodo almacenado</dt><dd>{stored?.period_start || stored?.period_end ? `${formatDate(stored.period_start)} — ${formatDate(stored.period_end)}` : 'No informado'}</dd></div>
              <div><dt>Persistencia</dt><dd>{inventoryState === 'unavailable' ? 'Inventario no disponible' : stored ? `${stored.storage_status} · ${numberFormat.format(stored.rows)} filas` : 'Sin inventario'}</dd></div>
              <div><dt>Resolución</dt><dd>{stored ? `${stored.territorial_resolution} · ${stored.temporal_resolution}` : 'No informada'}</dd></div>
              <div><dt>Enlace verificado</dt><dd>{formatDate(verifiedOn)}</dd></div>
            </dl>
            <div className="source-actions">
              <button className="button button-ghost button-small" type="button" onClick={() => { setSelectedSourceId(source.id); document.getElementById('source-trace')?.scrollIntoView({ behavior: 'smooth', block: 'start' }) }}><Fingerprint size={15} /> Ver traza</button>
              {canSync && <button className="button button-ghost button-small" type="button" disabled={syncingSources.has(source.id)} onClick={() => void triggerSync(source)}><RefreshCw className={syncingSources.has(source.id) ? 'spin' : ''} size={15} /> {syncingSources.has(source.id) ? 'Encolando…' : 'Sincronizar'}</button>}
              {templateType && <button className="button button-ghost button-small" type="button" onClick={() => void downloadTemplate(source)}><FileSpreadsheet size={15} /> Plantilla CSV</button>}
              {source.endpoint && <button className="button button-ghost button-small source-open-link" type="button" onClick={() => window.open(source.endpoint!, '_blank', 'noopener,noreferrer')}><ExternalLink size={15} /> Fuente oficial</button>}
            </div>
            {!canSync && <div className="source-permission-note"><LockKeyhole size={13} /> {source.status !== 'active' ? `Sincronización ${availability.label.toLocaleLowerCase('es')}` : 'Sincronización disponible para analistas y administradores'}</div>}
          </article>
        })}</div>}

        {catalogState === 'live' && filteredSources.length === 0 && <div className="empty-state"><Search size={28} /><h3>No encontramos fuentes</h3><p>Pruebe otra búsqueda o cambie el filtro.</p></div>}
      </div>

      <div className="integration-layout" id="source-trace">
        <article className="content-card connection-card">
          <div className="card-heading-row"><div><span className="eyebrow"><Fingerprint size={14} /> Ejecución seleccionada</span><h2>Trazabilidad y calidad</h2><p>Última ejecución visible para la fuente seleccionada.</p></div>{selectedRun && <span className={`connection-state connection-${selectedRun.status === 'succeeded' ? 'connected' : 'idle'}`}>{selectedRun.status}</span>}</div>
          {!selectedSource && <div className="empty-state"><Database size={28} /><h3>Sin fuente seleccionada</h3><p>El catálogo debe contener al menos una fuente para mostrar su traza.</p></div>}
          {selectedSource && runsState === 'unavailable' && <div className="empty-state"><Info size={28} /><h3>Historial no disponible</h3><p>El catálogo respondió, pero la API de ejecuciones no estuvo disponible. No se interpreta como ausencia de ingestas.</p></div>}
          {selectedSource && runsState === 'available' && !selectedRun && <div className="empty-state"><Info size={28} /><h3>Sin ejecuciones registradas</h3><p>{selectedSource.name} no tiene una ingesta visible en el historial consultado.</p></div>}
          {selectedSource && selectedRun && <><div className="traceability-steps"><span><small>ID de ejecución</small><strong>{selectedRun.id}</strong></span><span><small>Inicio</small><strong>{formatDate(selectedRun.started_at)}</strong></span><span><small>Checksum SHA-256</small><strong title={selectedRun.checksum ?? ''}>{shortHash(selectedRun.checksum)}</strong></span><span><small>Objeto del manifiesto</small><strong title={manifest?.object_sha256 ?? ''}>{shortHash(manifest?.object_sha256)}</strong></span></div><div className="metric-strip"><article className="metric-card compact"><span className="metric-icon"><Database size={18} /></span><div><strong>{numberFormat.format(selectedRun.rows_read)}</strong><span>filas leídas</span></div></article><article className="metric-card compact"><span className="metric-icon"><CheckCircle2 size={18} /></span><div><strong>{numberFormat.format(selectedRun.rows_accepted)}</strong><span>aceptadas</span></div></article><article className="metric-card compact"><span className="metric-icon"><XCircle size={18} /></span><div><strong>{numberFormat.format(selectedRun.rows_rejected)}</strong><span>rechazadas</span></div></article></div><div className="methodology-grid"><div><h3>Reporte de calidad</h3>{Object.keys(selectedRun.quality_report ?? {}).length ? <dl className="source-metadata">{Object.entries(selectedRun.quality_report).map(([key, value]) => <div key={key}><dt>{key.replace(/_/g, ' ')}</dt><dd>{formatValue(value)}</dd></div>)}</dl> : <div className="technical-note"><Info size={16} /><span>La ejecución no publicó un reporte de calidad.</span></div>}</div><div><h3>Procedencia y manifiesto</h3>{selectedRun.provenance && Object.keys(selectedRun.provenance).length || manifest && Object.keys(manifest.manifest).length ? <dl className="source-metadata">{Object.entries({ ...(selectedRun.provenance ?? {}), ...(manifest?.manifest ?? {}) }).map(([key, value]) => <div key={key}><dt>{key.replace(/_/g, ' ')}</dt><dd>{formatValue(value)}</dd></div>)}</dl> : <div className="technical-note"><Info size={16} /><span>La API no publicó procedencia o manifiesto para esta ejecución.</span></div>}</div></div>{selectedRun.error_message && <div className="inline-notice"><XCircle size={16} /> {selectedRun.error_message}</div>}</>}
        </article>

        <aside className="content-card integration-summary">
          <span className="summary-illustration"><ShieldCheck size={24} /></span><h3>{selectedSource?.name || 'Fuente sin seleccionar'}</h3><p>{selectedInventory?.semantics || `Estado de catálogo: ${selectedSource?.status || 'no disponible'}.`}</p><ul className="check-list"><li><Check size={15} /> Resolución territorial: {selectedInventory?.territorial_resolution || 'no informada'}</li><li><Check size={15} /> Resolución temporal: {selectedInventory?.temporal_resolution || 'no informada'}</li><li><Check size={15} /> Calidad: {selectedInventory?.quality_status || 'no informada'}</li><li><Check size={15} /> Último snapshot: {shortHash(selectedInventory?.last_snapshot_sha256)}</li></ul><div className="next-sync"><span>Tabla canónica</span><strong>{selectedInventory?.canonical_table || 'No informada'}</strong></div>
        </aside>
      </div>

      <div className="integration-layout" id="socrata-panel">
        <article className="content-card connection-card">
          <div className="card-heading-row"><div><span className="eyebrow"><Link2 size={14} /> Prueba directa</span><h2>Lector de API Socrata</h2><p>Hace una consulta SODA limitada a un registro. No sincroniza, no modifica el catálogo y no almacena la respuesta.</p></div><span className={`connection-state connection-${connectionState}`}>{connectionState === 'connected' ? <CheckCircle2 size={15} /> : connectionState === 'failed' ? <XCircle size={15} /> : <ServerCog size={15} />}{connectionState === 'connected' ? 'Respuesta verificada' : connectionState === 'testing' ? 'Consultando' : connectionState === 'failed' ? 'Falló la prueba' : 'Sin ejecutar'}</span></div>
          <div className="form-grid"><label className="form-field"><span>API Socrata del catálogo</span><select value={probeSourceId} onChange={(event) => setProbeSourceId(event.target.value)}><option value="">Seleccione una API</option>{probeSources.map((source) => <option value={source.id} key={source.id}>{source.institution} · {source.name}</option>)}</select><small>Solo aparecen fuentes catalogadas como Socrata.</small></label><label className="form-field"><span>Identificador del conjunto</span><input value={datasetId} onChange={(event) => { setDatasetId(event.target.value); setConnectionState('idle'); setProbeResult('') }} placeholder="abcd-1234" /></label><label className="form-field form-field-wide"><span>Endpoint del recurso</span><div className="input-with-icon"><Link2 size={16} /><input value={endpoint} onChange={(event) => { setEndpoint(event.target.value); setConnectionState('idle'); setProbeResult('') }} placeholder="https://www.datos.gov.co/resource/abcd-1234.json" /></div></label><label className="form-field form-field-wide"><span>App token de Socrata <small>Opcional</small></span><div className="input-with-icon"><KeyRound size={16} /><input value={token} onChange={(event) => setToken(event.target.value)} type="password" autoComplete="off" placeholder="Se usa solo en esta solicitud" /></div></label></div>
          <div className="connection-preview"><code>{endpoint && datasetId ? (() => { try { return socrataProbeUrl(endpoint, datasetId) } catch { return 'Endpoint inválido: use una URL HTTPS de Socrata.' } })() : 'Complete el endpoint y el identificador para construir la consulta.'}</code></div>
          {probeResult && <div className={`probe-result probe-result-${connectionState}`}><div><strong>{connectionState === 'connected' ? 'Respuesta de prueba' : 'Detalle del error'}</strong><span>{connectionState === 'connected' ? 'Muestra devuelta por la fuente externa; no es un dato persistido por PRORA.' : 'La fuente externa no pudo validarse desde este navegador.'}</span></div><pre><code>{probeResult}</code></pre></div>}
          <div className="card-footer-actions"><div className="privacy-note"><ShieldCheck size={15} /> El token permanece en memoria durante esta vista y no se envía al backend de PRORA.</div><button className="button button-primary" type="button" onClick={() => void testConnection()} disabled={!endpoint.trim() || !datasetId.trim() || connectionState === 'testing'}>{connectionState === 'testing' ? <LoaderCircle className="spin" size={17} /> : connectionState === 'connected' ? <RefreshCw size={17} /> : <Link2 size={17} />}{connectionState === 'testing' ? 'Consultando…' : connectionState === 'connected' ? 'Probar de nuevo' : 'Ejecutar prueba'}</button></div>
        </article>
      </div>
    </section>
  )
}
