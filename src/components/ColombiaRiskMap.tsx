import { LocateFixed, Minus, Plus } from 'lucide-react'
import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
  type PointerEvent as ReactPointerEvent,
  type WheelEvent as ReactWheelEvent,
} from 'react'
import colombiaGeoUrl from '../data/colombia.geo.json?url'
import type { HistoricalTerritory, RiskMapItem } from '../lib/api'

export type RiskLevel = 'bajo' | 'moderado' | 'alto' | 'critico'

export interface ColombiaRiskMapProps {
  disease: string
  horizon: number
  selectedTerritory?: string | null
  selectedHistoricalTerritory?: HistoricalTerritory | null
  onSelectTerritory: (territory: string) => void
  riskItems?: RiskMapItem[]
  historicalTerritories?: HistoricalTerritory[]
  dataState?: 'loading' | 'live' | 'empty' | 'offline'
  historyState?: 'loading' | 'live' | 'empty' | 'offline'
  historicalTerritoryCount?: number
}

type GeoPoint = [number, number]
type RawCoordinates = number[][][] | number[][][][]
type GeoGeometry = { type: 'Polygon' | 'MultiPolygon'; coordinates: RawCoordinates }
type GeoFeature = { type: 'Feature'; properties: { NOMBRE_DPT?: string; DPTO?: string }; geometry: GeoGeometry }
type GeoCollection = { type: 'FeatureCollection'; features: GeoFeature[] }

interface RiskDefinition { label: string; color: string; range: string }
interface GeoBounds { minLon: number; maxLon: number; minLat: number; maxLat: number }
interface MapPan { x: number; y: number }

let featureCache: GeoFeature[] | null = null
let featureRequest: Promise<GeoFeature[]> | null = null

function loadFeatures() {
  if (featureCache) return Promise.resolve(featureCache)
  if (!featureRequest) {
    featureRequest = fetch(colombiaGeoUrl)
      .then((response) => {
        if (!response.ok) throw new Error('No fue posible cargar la geometría de Colombia')
        return response.json() as Promise<GeoCollection>
      })
      .then((collection) => {
        featureCache = collection.features.filter((feature) => !feature.properties.NOMBRE_DPT?.toLowerCase().includes('san andrés'))
        return featureCache
      })
      .catch((error) => {
        featureRequest = null
        throw error
      })
  }
  return featureRequest
}

function useColombiaFeatures() {
  const [features, setFeatures] = useState<GeoFeature[]>(() => featureCache ?? [])
  useEffect(() => {
    let active = true
    loadFeatures().then((loaded) => active && setFeatures(loaded)).catch(() => active && setFeatures([]))
    return () => { active = false }
  }, [])
  return features
}

const RISK_DEFINITIONS: Record<RiskLevel, RiskDefinition> = {
  bajo: { label: 'Bajo', color: '#2a9d72', range: '0–39' },
  moderado: { label: 'Moderado', color: '#f2c94c', range: '40–59' },
  alto: { label: 'Alto', color: '#f28c45', range: '60–74' },
  critico: { label: 'Crítico', color: '#d94b5b', range: '75–100' },
}

const LABELS = [
  ['La Guajira', 10.9, -72.7], ['Atlántico', 10.8, -74.7], ['Antioquia', 7.5, -75.4],
  ['Chocó', 5.8, -77.2], ['Santander', 6.8, -73.4], ['Bogotá', 4.6, -74.2],
  ['Valle del Cauca', 3.7, -76.4], ['Meta', 3.3, -72.9], ['Amazonas', -0.1, -71.7],
] as const

function normalizeText(value: string) {
  return value.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '')
}

function clampRisk(score: number) { return Math.max(0, Math.min(100, Math.round(score))) }

function collectPoints(feature: GeoFeature): GeoPoint[] {
  const points: GeoPoint[] = []
  const visit = (node: unknown): void => {
    if (!Array.isArray(node)) return
    if (typeof node[0] === 'number' && typeof node[1] === 'number') {
      points.push([node[0], node[1]])
      return
    }
    node.forEach(visit)
  }
  visit(feature.geometry.coordinates)
  return points
}

function getBounds(features: GeoFeature[]): GeoBounds | null {
  const allPoints = features.flatMap(collectPoints)
  if (!allPoints.length) return null
  return {
    minLon: Math.min(...allPoints.map(([lon]) => lon)),
    maxLon: Math.max(...allPoints.map(([lon]) => lon)),
    minLat: Math.min(...allPoints.map(([, lat]) => lat)),
    maxLat: Math.max(...allPoints.map(([, lat]) => lat)),
  }
}

function project([longitude, latitude]: GeoPoint, bounds: GeoBounds) {
  const x = 35 + ((longitude - bounds.minLon) / (bounds.maxLon - bounds.minLon)) * 320
  const y = 22 + ((bounds.maxLat - latitude) / (bounds.maxLat - bounds.minLat)) * 500
  return [x, y] as const
}

function ringPath(ring: GeoPoint[], bounds: GeoBounds) {
  return ring.map((point, index) => {
    const [x, y] = project(point, bounds)
    return `${index === 0 ? 'M' : 'L'}${x.toFixed(2)} ${y.toFixed(2)}`
  }).join(' ') + ' Z'
}

function featurePath(feature: GeoFeature, bounds: GeoBounds) {
  const rings = feature.geometry.type === 'Polygon'
    ? feature.geometry.coordinates as GeoPoint[][]
    : (feature.geometry.coordinates as unknown as GeoPoint[][][][]).flat(1) as unknown as GeoPoint[][]
  return rings.map((ring) => ringPath(ring, bounds)).join(' ')
}

export function ColombiaOutline({ fill = '#d9eee6', stroke = '#ffffff', transform = 'translate(0 0)' }: { fill?: string; stroke?: string; transform?: string }) {
  const features = useColombiaFeatures()
  const bounds = useMemo(() => getBounds(features), [features])
  if (!bounds) return <g className="colombia-outline colombia-outline--loading" transform={transform} />
  return <g className="colombia-outline" transform={transform}>{features.map((feature) => <path key={feature.properties.DPTO ?? feature.properties.NOMBRE_DPT} d={featurePath(feature, bounds)} fill={fill} stroke={stroke} strokeWidth="1.2" strokeLinejoin="round" />)}</g>
}

export default function ColombiaRiskMap({ disease, horizon, selectedTerritory, selectedHistoricalTerritory = null, onSelectTerritory, riskItems = [], historicalTerritories = [], dataState = 'empty', historyState = 'empty', historicalTerritoryCount = 0 }: ColombiaRiskMapProps) {
  const [hoveredTerritory, setHoveredTerritory] = useState<string | null>(null)
  const [hoveredHistoricalCode, setHoveredHistoricalCode] = useState<string | null>(null)
  const [zoom, setZoom] = useState(1)
  const [pan, setPan] = useState<MapPan>({ x: 0, y: 0 })
  const [dragging, setDragging] = useState(false)
  const dragRef = useRef({ pointerId: -1, x: 0, y: 0, moved: false })
  const mainFeatures = useColombiaFeatures()
  const bounds = useMemo(() => getBounds(mainFeatures), [mainFeatures])
  const safeHorizon = Number.isFinite(horizon) ? Math.max(1, Math.min(4, Math.round(horizon))) : 4
  const historicalMode = Boolean(selectedHistoricalTerritory)

  const riskData = useMemo(() => {
    const liveTerritories = riskItems
      .filter((item) => Number.isFinite(item.latitude) && Number.isFinite(item.longitude))
      .map((item) => {
        const latitude = Number(item.latitude)
        const longitude = Number(item.longitude)
        const [x, y] = bounds ? project([longitude, latitude], bounds) : [195, 275]
        return {
          id: item.cod_dane,
          name: item.municipality,
          latitude,
          longitude,
          population: item.population ? new Intl.NumberFormat('es-CO', { notation: 'compact' }).format(item.population) : 'Sin dato',
          baseRisk: item.risk_score,
          climateSignal: `Predicción ${item.disease} · ${item.horizon} semanas`,
          x,
          y,
          score: clampRisk(item.risk_score),
          level: item.risk_level,
        }
      })
    return liveTerritories
  }, [bounds, riskItems])

  const selected = riskData.find((territory) => normalizeText(selectedTerritory ?? '') === territory.id || normalizeText(selectedTerritory ?? '') === normalizeText(territory.name))
  const active = historicalMode ? null : riskData.find((territory) => territory.id === hoveredTerritory) ?? selected ?? null
  const historicalData = useMemo(() => {
    if (!bounds) return []
    const located = historicalTerritories.filter((territory) => Number.isFinite(territory.latitude) && Number.isFinite(territory.longitude))
    const maximum = Math.max(...located.map((territory) => territory.latest_observed_cases), 1)
    return located.map((territory) => {
      const [x, y] = project([Number(territory.longitude), Number(territory.latitude)], bounds)
      return {
        ...territory,
        x,
        y,
        radius: 2.4 + Math.sqrt(Math.max(0, territory.latest_observed_cases) / maximum) * 4.6,
      }
    })
  }, [bounds, historicalTerritories])
  const activeHistorical = historicalData.find((territory) => territory.cod_dane === hoveredHistoricalCode)
    ?? historicalData.find((territory) => territory.cod_dane === selectedHistoricalTerritory?.cod_dane)
    ?? null
  const clampPan = (next: MapPan, nextZoom: number): MapPan => {
    const horizontalLimit = 155 * Math.max(0, nextZoom - 1)
    const verticalLimit = 220 * Math.max(0, nextZoom - 1)
    return {
      x: Math.max(-horizontalLimit, Math.min(horizontalLimit, next.x)),
      y: Math.max(-verticalLimit, Math.min(verticalLimit, next.y)),
    }
  }

  const markerTooltipStyle = (point: { x: number; y: number } | null, fallbackX = 214, fallbackY = 24) => {
    const viewX = point ? 195 + pan.x + (point.x - 195) * zoom + 18 : fallbackX
    const viewY = point ? 275 + pan.y + (point.y - 275) * zoom - 55 : fallbackY
    return {
      '--tooltip-x': `${Math.max(0, Math.min(390, viewX)) / 390 * 100}%`,
      '--tooltip-y': `${Math.max(0, Math.min(550, viewY)) / 550 * 100}%`,
    } as CSSProperties
  }

  const tooltipStyle = active ? markerTooltipStyle(active) : undefined
  const historyTooltipStyle = markerTooltipStyle(activeHistorical)

  const setZoomLevel = (nextZoom: number) => {
    const normalized = Math.max(1, Math.min(4, Number(nextZoom.toFixed(2))))
    setZoom(normalized)
    setPan((current) => normalized === 1 ? { x: 0, y: 0 } : clampPan(current, normalized))
  }
  const zoomIn = () => setZoomLevel(zoom + .25)
  const zoomOut = () => setZoomLevel(zoom - .25)
  const resetZoom = () => { setZoom(1); setPan({ x: 0, y: 0 }) }

  const handleWheel = (event: ReactWheelEvent<SVGSVGElement>) => {
    if (!event.cancelable) return
    event.preventDefault()
    const rectangle = event.currentTarget.getBoundingClientRect()
    const pointerX = (event.clientX - rectangle.left) / rectangle.width * 390
    const pointerY = (event.clientY - rectangle.top) / rectangle.height * 550
    const nextZoom = Math.max(1, Math.min(4, Number((zoom * Math.exp(-event.deltaY * .0015)).toFixed(2))))
    if (nextZoom === zoom) return
    const nextPan = nextZoom === 1 ? { x: 0, y: 0 } : {
      x: pointerX - 195 - nextZoom * (pointerX - 195 - pan.x) / zoom,
      y: pointerY - 275 - nextZoom * (pointerY - 275 - pan.y) / zoom,
    }
    setZoom(nextZoom)
    setPan(clampPan(nextPan, nextZoom))
  }

  const handlePointerDown = (event: ReactPointerEvent<SVGSVGElement>) => {
    if (event.button !== 0 || zoom <= 1) return
    dragRef.current = { pointerId: event.pointerId, x: event.clientX, y: event.clientY, moved: false }
    event.currentTarget.setPointerCapture(event.pointerId)
    setDragging(true)
  }

  const handlePointerMove = (event: ReactPointerEvent<SVGSVGElement>) => {
    if (!dragging || dragRef.current.pointerId !== event.pointerId) return
    const rectangle = event.currentTarget.getBoundingClientRect()
    const deltaX = (event.clientX - dragRef.current.x) * 390 / rectangle.width
    const deltaY = (event.clientY - dragRef.current.y) * 550 / rectangle.height
    if (Math.abs(deltaX) + Math.abs(deltaY) > .5) dragRef.current.moved = true
    dragRef.current.x = event.clientX
    dragRef.current.y = event.clientY
    setPan((current) => clampPan({ x: current.x + deltaX, y: current.y + deltaY }, zoom))
  }

  const finishPointerGesture = (event: ReactPointerEvent<SVGSVGElement>) => {
    if (dragRef.current.pointerId !== event.pointerId) return
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId)
    setDragging(false)
    dragRef.current.pointerId = -1
    window.setTimeout(() => { dragRef.current.moved = false }, 0)
  }

  const handleKeyboardSelection = (event: KeyboardEvent<SVGGElement>, territory: (typeof riskData)[number]) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      onSelectTerritory(territory.name)
    }
  }

  return (
    <figure className="colombia-risk-map" aria-labelledby="colombia-risk-map-title">
      <div className="colombia-risk-map__header">
        <div><p className="colombia-risk-map__eyebrow">{historicalMode ? 'Mapa de consulta · observación histórica' : `Mapa predictivo · ${dataState === 'live' ? 'Datos de la API' : dataState === 'loading' ? 'Consultando API…' : dataState === 'offline' ? 'API no disponible' : 'Sin pronósticos publicados'}`}</p><h3 id="colombia-risk-map-title" className="colombia-risk-map__title">{historicalMode ? `Ubicación del registro de ${disease || 'la enfermedad'}` : `Riesgo territorial de ${disease || 'enfermedad priorizada'}`}</h3></div>
        <span className={`colombia-risk-map__horizon${historicalMode ? ' is-historical' : ''}`} aria-label={historicalMode ? 'Contexto histórico observado' : `Horizonte de ${safeHorizon} semanas`}>{historicalMode ? 'Histórico' : `+${safeHorizon} sem.`}</span>
      </div>

      <div className="colombia-risk-map__canvas">
        {!bounds && <div className="colombia-risk-map__loading" role="status"><i/><span>Cargando geometría territorial…</span></div>}
        {bounds && !historicalMode && dataState !== 'live' && (
          <div className="colombia-risk-map__empty" role="status">
            <strong>{dataState === 'loading' ? 'Consultando predicciones' : dataState === 'offline' ? 'Capa predictiva no disponible' : 'Sin predicciones operacionales'}</strong>
            <span>{dataState === 'loading' ? 'Verificando el registro de modelos y el corte de datos…' : historyState === 'live' ? `${historicalTerritoryCount} municipios conservan análisis histórico en el selector superior.` : dataState === 'offline' ? 'La geometría permanece disponible; vuelva a intentar cuando la API responda.' : 'Publique un modelo válido con datos vigentes para habilitar la capa de riesgo.'}</span>
          </div>
        )}
        <div className="map-zoom-controls" aria-label="Controles de zoom del mapa">
          <button type="button" onClick={zoomIn} disabled={zoom >= 4} aria-label="Acercar mapa"><Plus size={17}/></button>
          <button type="button" onClick={zoomOut} disabled={zoom <= 1} aria-label="Alejar mapa"><Minus size={17}/></button>
          <button type="button" onClick={resetZoom} disabled={zoom === 1 && pan.x === 0 && pan.y === 0} aria-label="Restablecer vista"><LocateFixed size={16}/></button>
          <span aria-live="polite">{Math.round(zoom * 100)}%</span>
          <small>Rueda + arrastre</small>
        </div>
        <svg className={`colombia-risk-map__svg${dragging ? ' is-dragging' : ''}`} viewBox="0 0 390 550" role="img" aria-label={historicalMode ? `Ubicación del territorio con observaciones históricas de ${disease} en Colombia; no representa riesgo` : `Mapa departamental de riesgo de ${disease || 'enfermedades transmisibles'} en Colombia a ${safeHorizon} semanas`} onWheel={handleWheel} onPointerDown={handlePointerDown} onPointerMove={handlePointerMove} onPointerUp={finishPointerGesture} onPointerCancel={finishPointerGesture}>
          <defs><filter id="map-marker-shadow" x="-75%" y="-75%" width="250%" height="250%"><feDropShadow dx="0" dy="3" stdDeviation="4" floodColor="#153b36" floodOpacity="0.24" /></filter></defs>
          <g className="colombia-risk-map__zoom-layer" transform={`translate(${195 + pan.x} ${275 + pan.y}) scale(${zoom}) translate(-195 -275)`}>
            <g className="colombia-risk-map__departments" aria-label="Departamentos de Colombia">
              {bounds && mainFeatures.map((feature) => {
                const name = feature.properties.NOMBRE_DPT ?? 'Departamento'
                const selectedDepartment = historicalMode && (feature.properties.DPTO === selectedHistoricalTerritory?.department_code || normalizeText(name) === normalizeText(selectedHistoricalTerritory?.department ?? ''))
                return <path key={feature.properties.DPTO ?? name} className={`colombia-risk-map__department${selectedDepartment ? ' is-history-selected' : ''}`} d={featurePath(feature, bounds)}><title>{selectedDepartment ? `${name}: departamento del municipio seleccionado para consulta histórica` : name}</title></path>
              })}
            </g>
            <g className="colombia-risk-map__labels" aria-hidden="true">
              {bounds && LABELS.map(([label, latitude, longitude]) => { const [x, y] = project([longitude, latitude], bounds); return <text key={label} x={x} y={y}>{label}</text> })}
            </g>
            <g className="colombia-risk-map__markers" aria-label="Territorios con estimación de riesgo">
              {bounds && !historicalMode && riskData.map((territory) => {
                const isSelected = selected?.id === territory.id
                const risk = RISK_DEFINITIONS[territory.level]
                return <g key={territory.id} className={`colombia-risk-map__marker colombia-risk-map__marker--${territory.level}${isSelected ? ' is-selected' : ''}`} role="button" tabIndex={0} aria-pressed={isSelected} aria-label={`${territory.name}: riesgo ${risk.label.toLowerCase()}, ${territory.score} de 100. Seleccionar territorio.`} onClick={() => { if (!dragRef.current.moved) onSelectTerritory(territory.name) }} onKeyDown={(event) => handleKeyboardSelection(event, territory)} onMouseEnter={() => setHoveredTerritory(territory.id)} onMouseLeave={() => setHoveredTerritory(null)} onFocus={() => setHoveredTerritory(territory.id)} onBlur={() => setHoveredTerritory(null)}>
                  <circle className="colombia-risk-map__marker-pulse" cx={territory.x} cy={territory.y} r={isSelected ? 17 : 14} fill={risk.color} />
                  <circle className="colombia-risk-map__marker-core" cx={territory.x} cy={territory.y} r={isSelected ? 9 : 7} fill={risk.color} filter="url(#map-marker-shadow)" />
                  <title>{`${territory.name}: ${territory.score}/100, riesgo ${risk.label.toLowerCase()} (estimación del modelo).`}</title>
                </g>
              })}
              {bounds && historicalMode && historicalData.map((territory) => {
                const isSelected = territory.cod_dane === selectedHistoricalTerritory?.cod_dane
                return <g key={territory.cod_dane} className={`colombia-risk-map__history-marker${isSelected ? ' is-selected' : ''}`} role="button" tabIndex={isSelected ? 0 : -1} aria-label={`${territory.municipality}: ${territory.latest_observed_cases} casos en el último corte observado; no es una estimación de riesgo.`} onClick={() => { if (!dragRef.current.moved) onSelectTerritory(territory.cod_dane) }} onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onSelectTerritory(territory.cod_dane) } }} onMouseEnter={() => setHoveredHistoricalCode(territory.cod_dane)} onMouseLeave={() => setHoveredHistoricalCode(null)} onFocus={() => setHoveredHistoricalCode(territory.cod_dane)} onBlur={() => setHoveredHistoricalCode(null)}>{isSelected && <circle className="colombia-risk-map__history-marker-ring" cx={territory.x} cy={territory.y} r={territory.radius + 7}/>}<circle className="colombia-risk-map__history-marker-core" cx={territory.x} cy={territory.y} r={territory.radius} filter={isSelected ? 'url(#map-marker-shadow)' : undefined}/><title>{`${territory.municipality}: ${territory.latest_observed_cases} casos el ${territory.latest_week}; total publicado ${territory.total_observed_cases}. Sin clasificación de riesgo.`}</title></g>
              })}
            </g>
          </g>
        </svg>

        {active && <div className="colombia-risk-map__tooltip" style={tooltipStyle} role="status" aria-live="polite"><div className="colombia-risk-map__tooltip-heading"><strong>{active.name}</strong><span className={`colombia-risk-map__risk-badge colombia-risk-map__risk-badge--${active.level}`}>{RISK_DEFINITIONS[active.level].label}</span></div><dl className="colombia-risk-map__tooltip-metrics"><div><dt>Índice estimado</dt><dd>{active.score}/100</dd></div><div><dt>Población aprox.</dt><dd>{active.population}</dd></div></dl><p className="colombia-risk-map__tooltip-signal">Señal climática: {active.climateSignal}</p></div>}
        {historicalMode && activeHistorical && <div className="colombia-risk-map__tooltip colombia-risk-map__tooltip--history" style={historyTooltipStyle} role="status" aria-live="polite"><div className="colombia-risk-map__tooltip-heading"><strong>{activeHistorical.municipality}</strong><span className="colombia-risk-map__history-badge">Observado</span></div><dl className="colombia-risk-map__tooltip-metrics"><div><dt>Último corte</dt><dd>{new Intl.DateTimeFormat('es-CO', { dateStyle: 'medium' }).format(new Date(`${activeHistorical.latest_week}T00:00:00`))}</dd></div><div><dt>Casos del corte</dt><dd>{new Intl.NumberFormat('es-CO').format(activeHistorical.latest_observed_cases)}</dd></div></dl><p className="colombia-risk-map__tooltip-signal">Serie disponible: {new Intl.NumberFormat('es-CO').format(activeHistorical.total_observed_cases)} casos en {new Intl.NumberFormat('es-CO').format(activeHistorical.observation_rows)} cortes publicados. El tamaño del punto representa casos del último corte, no riesgo.</p></div>}
      </div>

      <div className="colombia-risk-map__footer">{historicalMode ? <div className="colombia-risk-map__legend" aria-label="Leyenda de consulta histórica"><span className="colombia-risk-map__legend-title">Tipo de dato</span><ul className="colombia-risk-map__legend-list"><li className="colombia-risk-map__legend-item"><span className="colombia-risk-map__legend-swatch colombia-risk-map__legend-swatch--history" aria-hidden="true"/><span>Casos observados · tamaño por último corte</span></li></ul></div> : <div className="colombia-risk-map__legend" aria-label="Leyenda del nivel de riesgo"><span className="colombia-risk-map__legend-title">Nivel de riesgo</span><ul className="colombia-risk-map__legend-list">{(Object.entries(RISK_DEFINITIONS) as [RiskLevel, RiskDefinition][]).map(([level, definition]) => <li key={level} className="colombia-risk-map__legend-item"><span className={`colombia-risk-map__legend-swatch colombia-risk-map__legend-swatch--${level}`} style={{ backgroundColor: definition.color }} aria-hidden="true" /><span>{definition.label}</span><span className="colombia-risk-map__legend-range">{definition.range}</span></li>)}</ul></div>}<figcaption className="colombia-risk-map__caption">{historicalMode ? `${historicalData.length} municipios con coordenadas se muestran como observaciones. Seleccionado: ${selectedHistoricalTerritory?.municipality}. Los puntos no representan incidencia ni riesgo.` : dataState === 'live' ? `${riskItems.length} predicciones municipales operacionales publicadas por PRORA.` : 'Mapa administrativo real de Colombia. No se muestran puntos sintéticos ni resultados históricos como si fueran actuales.'}</figcaption></div>
    </figure>
  )
}
