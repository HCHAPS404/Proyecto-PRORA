import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Braces,
  Check,
  ChevronRight,
  Clipboard,
  Clock3,
  Code2,
  Copy,
  KeyRound,
  LoaderCircle,
  LockKeyhole,
  Play,
  RefreshCw,
  Server,
  ShieldCheck,
  Sparkles,
} from 'lucide-react'
import { API_BASE_URL, apiSession, proraApi } from '../lib/api'

type Parameter = {
  key: string
  label: string
  type: 'text' | 'select' | 'number' | 'date'
  required?: boolean
  options?: string[]
  hint?: string
}

type Endpoint = {
  id: string
  method: 'GET' | 'POST'
  path: string
  title: string
  description: string
  parameters: Parameter[]
  auth?: boolean
}

const diseaseOptions = ['dengue', 'malaria', 'chikunguna', 'zika', 'leishmaniasis', 'ira']

const endpoints: Endpoint[] = [
  {
    id: 'current-reference', method: 'GET', path: '/api/v1/analytics/current-reference', title: 'Corte oficial reciente',
    description: 'Consulta la referencia provisional más reciente del BES del INS y declara si corresponde a municipio, distrito o contexto departamental.',
    parameters: [
      { key: 'disease', label: 'Enfermedad', type: 'select', required: true, options: diseaseOptions },
      { key: 'territory', label: 'Territorio', type: 'text', required: true, hint: 'national, 76 o 76001' },
    ],
  },
  {
    id: 'municipal-risk', method: 'GET', path: '/api/v1/risk/municipalities/{cod_dane}', title: 'Riesgo municipal',
    description: 'Retorna el riesgo proyectado de brote para un municipio específico.',
    parameters: [
      { key: 'cod_dane', label: 'Código DANE', type: 'text', required: true, hint: 'Ej. 76001' },
      { key: 'disease', label: 'Enfermedad', type: 'select', required: true, options: diseaseOptions },
      { key: 'horizon', label: 'Horizonte', type: 'select', required: true, options: ['3', '4'] },
    ],
  },
  {
    id: 'risk-map', method: 'GET', path: '/api/v1/risk/map', title: 'Mapa nacional de riesgo',
    description: 'Entrega el conjunto de riesgos municipales para generar el mapa de calor nacional.',
    parameters: [
      { key: 'disease', label: 'Enfermedad', type: 'select', required: true, options: diseaseOptions },
      { key: 'horizon', label: 'Horizonte', type: 'select', required: true, options: ['3', '4'] },
    ],
  },
  {
    id: 'explainability', method: 'GET', path: '/api/v1/risk/municipalities/{cod_dane}/explanation', title: 'Explicabilidad local',
    description: 'Muestra las variables que más contribuyen a la predicción de un municipio.',
    parameters: [
      { key: 'cod_dane', label: 'Código DANE', type: 'text', required: true },
      { key: 'disease', label: 'Enfermedad', type: 'select', required: true, options: diseaseOptions },
      { key: 'horizon', label: 'Horizonte', type: 'select', required: true, options: ['3', '4'] },
    ],
  },
  {
    id: 'history', method: 'GET', path: '/api/v1/risk/municipalities/{cod_dane}/history', title: 'Serie histórica',
    description: 'Retorna los casos observados publicados para un territorio, junto con sus indicadores de calidad y estado preliminar.',
    parameters: [
      { key: 'cod_dane', label: 'Código DANE', type: 'text', required: true },
      { key: 'disease', label: 'Enfermedad', type: 'select', required: true, options: diseaseOptions },
      { key: 'from', label: 'Desde', type: 'date', required: false },
      { key: 'to', label: 'Hasta', type: 'date', required: false },
    ],
  },
  {
    id: 'subscription', method: 'POST', path: '/api/v1/subscriptions', title: 'Crear suscripción',
    description: 'Guarda la intención de recibir resúmenes o señales. La respuesta declara qué canales tienen entrega operativa y cuáles requieren proveedor.',
    auth: true,
    parameters: [
      { key: 'topic', label: 'Tema', type: 'select', required: true, options: ['critical_alerts', 'territory_watch', 'epidemiological_summary', 'model_drift'] },
      { key: 'target', label: 'Destino', type: 'text', required: true, hint: '76001 o dengue' },
      { key: 'frequency', label: 'Frecuencia', type: 'select', required: true, options: ['immediate', 'daily', 'weekly'] },
      { key: 'channels', label: 'Canales', type: 'text', required: true, hint: 'email' },
    ],
  },
  {
    id: 'notifications', method: 'GET', path: '/api/v1/notifications', title: 'Mis notificaciones',
    description: 'Consulta entregas en la plataforma, estado del canal y trazabilidad de la regla que originó cada notificación.',
    auth: true,
    parameters: [
      { key: 'unread_only', label: 'Solo no leídas', type: 'select', options: ['true', 'false'] },
      { key: 'limit', label: 'Máximo de resultados', type: 'number', hint: '1 a 200' },
    ],
  },
  {
    id: 'model-meta', method: 'GET', path: '/api/v1/models/{disease}', title: 'Metadatos del modelo',
    description: 'Consulta la versión y las métricas de desempeño vigentes.',
    parameters: [{ key: 'disease', label: 'Enfermedad', type: 'select', required: true, options: diseaseOptions }, { key: 'horizon', label: 'Horizonte', type: 'select', required: true, options: ['3', '4'] }],
  },
  {
    id: 'data-coverage', method: 'GET', path: '/api/v1/sources/disease-coverage', title: 'Cobertura por enfermedad',
    description: 'Distingue observaciones históricas, modelo entrenado y salida operativa para cada evento.',
    parameters: [],
  },
]

const initialValues: Record<string, string> = {
  cod_dane: '76001', disease: 'dengue', territory: '76001', horizon: '4', from: '', to: '',
  topic: 'critical_alerts', target: '76001', frequency: 'immediate', channels: 'email',
  unread_only: 'true', limit: '20',
}

export type ApiExplorerProps = {
  baseUrl?: string
  onNotify?: (message: string) => void
}

export default function ApiExplorer({ baseUrl = API_BASE_URL.replace(/\/api\/v1$/, ''), onNotify }: ApiExplorerProps) {
  const [selectedId, setSelectedId] = useState(endpoints[0].id)
  const [values, setValues] = useState<Record<string, string>>(initialValues)
  const [copied, setCopied] = useState('')
  const [running, setRunning] = useState(false)
  const [latency, setLatency] = useState<number | null>(null)
  const [responsePayload, setResponsePayload] = useState<unknown>(null)
  const [responseStatus, setResponseStatus] = useState('Sin ejecutar')
  const [apiOnline, setApiOnline] = useState<boolean | null>(null)
  const [technicalMode, setTechnicalMode] = useState(false)

  const checkApi = useCallback(() => {
    setApiOnline(null)
    proraApi.health().then(() => setApiOnline(true)).catch(() => setApiOnline(false))
  }, [])

  useEffect(() => { checkApi() }, [checkApi])

  const selected = endpoints.find((endpoint) => endpoint.id === selectedId) ?? endpoints[0]

  const validationErrors = useMemo(() => {
    const errors: Record<string, string> = {}
    selected.parameters.forEach((parameter) => {
      const value = (values[parameter.key] ?? '').trim()
      if (parameter.required && !value) errors[parameter.key] = 'Este campo es obligatorio.'
      else if (value && parameter.options && !parameter.options.includes(value)) errors[parameter.key] = 'Seleccione una opción válida.'
      else if (value && parameter.key === 'cod_dane' && !/^\d{5}$/.test(value)) errors[parameter.key] = 'Use un código DIVIPOLA de 5 dígitos.'
      else if (value && parameter.key === 'territory' && value.toLowerCase() !== 'national' && !/^\d{2}$/.test(value) && !/^\d{5}$/.test(value)) errors[parameter.key] = "Use 'national', 2 dígitos de departamento o 5 de municipio."
      else if (value && parameter.key === 'limit' && (!Number.isInteger(Number(value)) || Number(value) < 1 || Number(value) > 200)) errors[parameter.key] = 'Use un entero entre 1 y 200.'
      else if (value && parameter.key === 'channels') {
        const channels = value.split(',').map((item) => item.trim()).filter(Boolean)
        if (!channels.length || channels.some((channel) => !['email', 'push', 'in_app', 'webhook'].includes(channel))) errors[parameter.key] = 'Canales permitidos: email, push, in_app o webhook.'
      }
    })
    if (values.from && values.to && values.from > values.to) {
      errors.from = 'La fecha inicial debe ser anterior a la final.'
      errors.to = 'La fecha final debe ser posterior a la inicial.'
    }
    return errors
  }, [selected, values])
  const authRequired = Boolean(selected.auth && !apiSession.isRegistered())
  const requestIsValid = Object.keys(validationErrors).length === 0 && !authRequired

  const request = useMemo(() => {
    let path = selected.path
      .replace('{cod_dane}', values.cod_dane || '{cod_dane}')
      .replace('{disease}', values.disease || '{disease}')
    const query = selected.parameters
      .filter((parameter) => !['cod_dane', 'disease'].includes(parameter.key) || !selected.path.includes(`{${parameter.key}}`))
      .filter(() => selected.method === 'GET')
      .filter((parameter) => Boolean(values[parameter.key]))
      .map((parameter) => `${encodeURIComponent(parameter.key)}=${encodeURIComponent(values[parameter.key] ?? '')}`)
      .join('&')
    path = `${baseUrl}${path}${query ? `?${query}` : ''}`
    const body = selected.method === 'POST'
      ? Object.fromEntries(selected.parameters.map((parameter) => [parameter.key, parameter.key === 'channels' ? (values[parameter.key] ?? '').split(',').map((item) => item.trim()).filter(Boolean) : values[parameter.key] ?? '']))
      : undefined
    return { url: path, body }
  }, [baseUrl, selected, values])

  const authHeader = selected.auth ? ` \\\n  -H 'Authorization: Bearer $PRORA_ACCESS_TOKEN'` : ''
  const curl = selected.method === 'POST'
    ? `curl -X POST '${request.url}' \\\n  -H 'Authorization: Bearer $PRORA_ACCESS_TOKEN' \\\n  -H 'Content-Type: application/json' \\\n  -d '${JSON.stringify(request.body)}'`
    : `curl '${request.url}'${authHeader}`

  const copyText = async (text: string, key: string) => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(key)
      onNotify?.('Copiado al portapapeles')
      window.setTimeout(() => setCopied(''), 1800)
    } catch {
      onNotify?.('No fue posible copiar automáticamente')
    }
  }

  const executeRequest = async () => {
    if (authRequired) {
      setResponsePayload({ error: 'Este endpoint requiere una cuenta registrada. Inicia sesión y vuelve a intentarlo.' })
      setResponseStatus('Inicio de sesión requerido')
      setLatency(null)
      onNotify?.('Inicia sesión para ejecutar esta operación privada')
      return
    }
    if (!requestIsValid) {
      setResponsePayload({ error: 'Corrija los parámetros antes de enviar la solicitud.', fields: validationErrors })
      setResponseStatus('Parámetros inválidos')
      setLatency(null)
      onNotify?.('Corrige los campos marcados antes de consultar la API')
      return
    }
    setRunning(true)
    const started = Date.now()
    const controller = new AbortController()
    const timeout = window.setTimeout(() => controller.abort(), 15_000)
    try {
      const token = apiSession.accessToken()
      const response = await fetch(request.url, {
        method: selected.method,
        headers: {
          Accept: 'application/json',
          ...(selected.method === 'POST' ? { 'Content-Type': 'application/json' } : {}),
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: selected.method === 'POST' ? JSON.stringify(request.body) : undefined,
        signal: controller.signal,
      })
      const payload = await response.json().catch(() => ({ message: 'Respuesta sin cuerpo JSON' }))
      setResponsePayload(payload)
      setResponseStatus(`${response.status} ${response.statusText}`)
      onNotify?.(response.ok ? 'Solicitud ejecutada contra la API real' : 'La API devolvió un error verificable')
    } catch (error) {
      const timedOut = error instanceof DOMException && error.name === 'AbortError'
      setResponsePayload({ error: timedOut ? 'La solicitud superó 15 segundos. Confirma que el backend esté iniciado.' : error instanceof Error ? error.message : 'No fue posible conectar' })
      setResponseStatus(timedOut ? 'Tiempo agotado' : 'Error de red')
      onNotify?.(timedOut ? 'La API no respondió dentro del tiempo esperado' : 'No fue posible conectar con la API')
    } finally {
      window.clearTimeout(timeout)
      setLatency(Date.now() - started)
      setRunning(false)
    }
  }

  return (
    <section className="workspace-view api-explorer" aria-labelledby="api-explorer-title">
      <header className="view-heading">
        <div>
          <span className="eyebrow"><Code2 size={15} /> Conexiones e integraciones</span>
          <h1 id="api-explorer-title">Conecta tus sistemas con PRORA</h1>
          <p>Empieza con una consulta guiada. La consola técnica queda disponible cuando necesites parámetros o código.</p>
        </div>
        <div className="api-heading-actions"><div className={`api-health-badge ${apiOnline === false ? 'is-offline' : ''}`}><span className="health-dot" /> {apiOnline === null ? 'Consultando API' : apiOnline ? 'API operativa' : 'API no disponible'} <small>estado en vivo</small>{apiOnline === false && <button type="button" onClick={checkApi} aria-label="Reconectar API"><RefreshCw size={14} /></button>}</div><button className="button button--secondary" type="button" onClick={() => setTechnicalMode((value) => !value)}><Braces size={16} /> {technicalMode ? 'Vista guiada' : 'Abrir consola técnica'}</button></div>
      </header>

      <div className="api-overview-strip">
        <div><Server size={18} /><span>Base URL</span><code>{baseUrl}/api/v1</code></div>
        <div><LockKeyhole size={18} /><span>Autenticación</span><strong>Bearer token</strong></div>
        <div><Clock3 size={18} /><span>Límite</span><strong>120 req / min</strong></div>
        <div><Braces size={18} /><span>Formato</span><strong>JSON</strong></div>
      </div>

      <section className="api-quickstart" aria-labelledby="api-quickstart-title">
        <div className="api-quickstart__heading"><span><Sparkles size={16} /></span><div><h2 id="api-quickstart-title">Empieza en tres pasos</h2><p>En desarrollo PRORA autoriza los dos orígenes locales; para producción se recomienda publicar <code>/api/v1</code> bajo el mismo dominio.</p></div></div>
        <div className="api-quickstart__steps">
          <article><span>1</span><div><strong>Comprueba la conexión</strong><small>{apiOnline === true ? 'El backend está respondiendo.' : apiOnline === false ? 'Inicia el backend en el puerto 8000 y reconecta.' : 'Verificando disponibilidad…'}</small></div>{apiOnline === false && <button type="button" onClick={checkApi}>Reconectar</button>}</article>
          <article><span>2</span><div><strong>Elige lo que necesitas</strong><small>Corte oficial, historia o trazabilidad del modelo.</small></div><div className="api-quick-actions"><button type="button" onClick={() => { setSelectedId('current-reference'); setTechnicalMode(true) }}>Corte oficial</button><button type="button" onClick={() => { setSelectedId('history'); setTechnicalMode(true) }}>Histórico</button><button type="button" onClick={() => { setSelectedId('model-meta'); setTechnicalMode(true) }}>Modelos</button></div></article>
          <article><span>3</span><div><strong>Integra con el contrato oficial</strong><small>OpenAPI documenta esquemas, autenticación y respuestas.</small></div><button type="button" onClick={() => window.open(`${baseUrl}/docs`, '_blank', 'noopener,noreferrer')}>Abrir documentación</button></article>
        </div>
      </section>

      {technicalMode ? <div className="api-workbench">
        <aside className="content-card endpoint-sidebar" aria-label="Endpoints disponibles">
          <div className="endpoint-sidebar-heading">
            <span>Referencia</span>
            <strong>{endpoints.length} endpoints</strong>
          </div>
          <nav className="endpoint-list">
            {endpoints.map((endpoint) => (
              <button
                type="button"
                className={`endpoint-item ${endpoint.id === selected.id ? 'active' : ''}`}
                key={endpoint.id}
                onClick={() => {
                  setSelectedId(endpoint.id)
                  setResponsePayload(null)
                  setResponseStatus('Sin ejecutar')
                  setLatency(null)
                }}
                aria-current={endpoint.id === selected.id ? 'page' : undefined}
              >
                <span className={`method-badge method-${endpoint.method.toLowerCase()}`}>{endpoint.method}</span>
                <span><strong>{endpoint.title}</strong><small>{endpoint.path}</small></span>
                <ChevronRight size={16} />
              </button>
            ))}
          </nav>
          <div className="api-security-note">
            <ShieldCheck size={19} />
            <div><strong>Datos agregados</strong><span>Sin información identificable de pacientes.</span></div>
          </div>
        </aside>

        <div className="api-main-column">
          <article className="content-card endpoint-detail">
            <div className="endpoint-title-row">
              <div>
                <div className="endpoint-path-line"><span className={`method-badge method-${selected.method.toLowerCase()}`}>{selected.method}</span><code>{selected.path}</code></div>
                <h2>{selected.title}</h2>
                <p>{selected.description}</p>
              </div>
              <span className="version-tag">v1 estable</span>
            </div>

            <div className="parameter-section">
              <div className="section-label-row"><h3>Parámetros</h3><span>{selected.parameters.length} campos</span></div>
              <div className="parameter-grid">
                {selected.parameters.map((parameter) => (
                  <label className={`form-field${validationErrors[parameter.key] ? ' has-error' : ''}`} key={parameter.key}>
                    <span>{parameter.label} {parameter.required && <b>Requerido</b>}</span>
                    {parameter.type === 'select' ? (
                      <select required={parameter.required} aria-invalid={Boolean(validationErrors[parameter.key])} value={values[parameter.key] ?? ''} onChange={(event) => setValues((current) => ({ ...current, [parameter.key]: event.target.value }))}>
                        {parameter.options?.map((option) => <option value={option} key={option}>{option === '3' || option === '4' ? `${option} semanas` : option}</option>)}
                      </select>
                    ) : (
                      <input
                        type={parameter.type}
                        required={parameter.required}
                        aria-invalid={Boolean(validationErrors[parameter.key])}
                        value={values[parameter.key] ?? ''}
                        placeholder={parameter.hint}
                        min={parameter.type === 'number' ? '0' : undefined}
                        max={parameter.type === 'number' ? '1' : undefined}
                        step={parameter.type === 'number' ? '0.05' : undefined}
                        onChange={(event) => setValues((current) => ({ ...current, [parameter.key]: event.target.value }))}
                      />
                    )}
                    {validationErrors[parameter.key] ? <small className="field-error">{validationErrors[parameter.key]}</small> : parameter.hint && <small>{parameter.hint}</small>}
                  </label>
                ))}
              </div>
            </div>

            <div className="request-builder">
              <div className="request-url">
                <span className={`method-badge method-${selected.method.toLowerCase()}`}>{selected.method}</span>
                <code>{request.url}</code>
                <button className="icon-button" type="button" title="Copiar URL" aria-label="Copiar URL" onClick={() => copyText(request.url, 'url')}>
                  {copied === 'url' ? <Check size={17} /> : <Copy size={17} />}
                </button>
              </div>
              <button className="button button-primary" type="button" onClick={executeRequest} disabled={running || !requestIsValid} title={authRequired ? 'Inicia sesión para usar este endpoint' : !requestIsValid ? 'Corrige los parámetros requeridos' : undefined}>
                {running ? <LoaderCircle className="spin" size={17} /> : <Play size={17} />}
                {running ? 'Ejecutando…' : authRequired ? 'Inicia sesión' : requestIsValid ? 'Enviar solicitud' : 'Completa los campos'}
              </button>
            </div>
          </article>

          <div className="api-console-grid">
            <article className="content-card code-panel">
              <div className="code-panel-heading"><span><Clipboard size={16} /> Solicitud cURL</span><button type="button" onClick={() => copyText(curl, 'curl')}>{copied === 'curl' ? <Check size={15} /> : <Copy size={15} />} {copied === 'curl' ? 'Copiado' : 'Copiar'}</button></div>
              <pre><code>{curl}</code></pre>
            </article>
            <article className="content-card code-panel response-panel">
              <div className="code-panel-heading">
                <span><Sparkles size={16} /> Respuesta</span>
                <div><span className="response-status">{responseStatus}</span><small>{latency === null ? '—' : `${latency} ms`}</small><button type="button" aria-label="Copiar respuesta" disabled={responsePayload === null} onClick={() => copyText(JSON.stringify(responsePayload, null, 2), 'response')}>{copied === 'response' ? <Check size={15} /> : <Copy size={15} />}</button></div>
              </div>
              <pre><code>{responsePayload === null ? 'Ejecute la solicitud para ver una respuesta real de PRORA.' : JSON.stringify(responsePayload, null, 2)}</code></pre>
            </article>
          </div>

          <article className="content-card api-key-callout">
            <span className="callout-icon"><KeyRound size={22} /></span>
            <div><h3>¿Listo para integrar?</h3><p>Consulte el contrato OpenAPI y use un token de sesión para las operaciones privadas.</p></div>
            <button className="button button-secondary" type="button" onClick={() => window.open(`${baseUrl}/docs`, '_blank', 'noopener,noreferrer')}>Abrir OpenAPI</button>
          </article>
        </div>
      </div> : <article className="content-card api-guided-empty"><Code2 size={25} /><div><h2>La consola avanzada está cerrada</h2><p>Usa una acción del paso 2 para abrir el endpoint correcto con parámetros guiados, ejemplo cURL y respuesta real.</p></div><button className="button button--primary" type="button" onClick={() => setTechnicalMode(true)}>Explorar endpoints <ChevronRight size={16} /></button></article>}
    </section>
  )
}
