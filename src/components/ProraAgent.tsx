import {
  Bot,
  CheckCircle2,
  ChevronDown,
  Database,
  Eraser,
  LifeBuoy,
  MessageSquareText,
  Send,
  ShieldCheck,
  Sparkles,
  TrendingUp,
  X,
} from 'lucide-react'
import { FormEvent, KeyboardEvent, useEffect, useMemo, useRef, useState } from 'react'
import '../prora-agent.css'
import { ApiError, proraApi } from '../lib/api'

type AgentRole = 'assistant' | 'user'
type BotView = 'overview' | 'data' | 'api' | 'alerts' | 'methodology' | 'settings' | 'help'

interface AgentMessage {
  id: string
  role: AgentRole
  content: string
  timestamp: string
  source?: string
}

interface ProraAgentProps {
  contextLabel?: string
  onNavigate?: (view: BotView) => void
}

type LocalAnswer = { answer: string; source: string; navigate?: BotView }
type AnalysisContext = {
  disease?: string
  disease_label?: string
  territory_code?: string | null
  municipality?: string | null
  department?: string | null
  horizon?: number
}

// La versión de la clave separa el historial del antiguo “Agente PRORA”.
const STORAGE_KEY = 'prora-bot-messages-v3'

const quickPrompts = [
  { label: 'Último corte', prompt: '¿Cuál es el último corte observado y qué significa?', icon: TrendingUp },
  { label: 'Fuentes', prompt: '¿Qué fuentes y datasets tiene registrados PRORA?', icon: Database },
  { label: 'Cómo leer', prompt: '¿Cómo interpreto casos, predicción y alertas?', icon: LifeBuoy },
]

const formatTime = () => new Intl.DateTimeFormat('es-CO', { hour: '2-digit', minute: '2-digit' }).format(new Date())
const makeId = () => `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
const normalize = (value: string) => value.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase('es')

const createWelcomeMessage = (contextLabel?: string): AgentMessage => ({
  id: 'welcome',
  role: 'assistant',
  content: `Soy PRORA-BOT. Puedo consultar datos agregados de la API y también guiarte por ${contextLabel ?? 'la plataforma'} sin depender de un proveedor externo de IA. No inventaré cifras cuando falte información.`,
  timestamp: formatTime(),
  source: 'PRORA-BOT · Motor determinista',
})

function loadMessages(contextLabel?: string): AgentMessage[] {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (!stored) return [createWelcomeMessage(contextLabel)]
    const parsed = JSON.parse(stored) as AgentMessage[]
    return Array.isArray(parsed) && parsed.length ? parsed : [createWelcomeMessage(contextLabel)]
  } catch {
    return [createWelcomeMessage(contextLabel)]
  }
}

function loadAnalysisContext(): AnalysisContext {
  try {
    const parsed = JSON.parse(sessionStorage.getItem('prora-current-analysis') ?? '{}') as AnalysisContext
    return parsed && typeof parsed === 'object' ? parsed : {}
  } catch {
    return {}
  }
}

function localAnswer(prompt: string, contextLabel?: string): LocalAnswer {
  const question = normalize(prompt)
  const wantsNavigation = /(abre|abrir|ir a|llevame|muestra|ver)/.test(question)

  if (question.includes('alert')) {
    return {
      answer: wantsNavigation
        ? 'Abrí el Centro de alertas. Allí puedes separar señales activas del historial revisado o cerrado y consultar la evidencia publicada para cada territorio.'
        : 'Una alerta operativa solo existe cuando la API publica un pronóstico elegible. El Centro de alertas conserva también eventos revisados y cerrados; una observación histórica no se convierte automáticamente en alerta.',
      source: 'PRORA-BOT · Guía de plataforma',
      navigate: wantsNavigation ? 'alerts' : undefined,
    }
  }
  if (question.includes('fuente') || question.includes('dataset') || question.includes('calidad') || question.includes('dato')) {
    return {
      answer: wantsNavigation
        ? 'Abrí Fuentes y datos. Revisa institución, periodo cubierto, último intento de sincronización, filas almacenadas y calidad antes de interpretar cualquier resultado.'
        : 'Para auditar un dato, abre Fuentes y datos y verifica periodo cubierto, resolución territorial, última sincronización, filas aceptadas/rechazadas y huella SHA-256. PRORA distingue fecha de ingestión de fecha real del dato.',
      source: 'PRORA-BOT · Guía de trazabilidad',
      navigate: wantsNavigation ? 'data' : undefined,
    }
  }
  if (question.includes('api') || question.includes('integracion') || question.includes('endpoint')) {
    return {
      answer: wantsNavigation
        ? 'Abrí API e integraciones. Puedes elegir un endpoint, completar parámetros, ejecutar la solicitud y copiar el ejemplo reproducible.'
        : 'API e integraciones permite probar endpoints con parámetros reales. Las operaciones públicas funcionan sin cuenta; las privadas requieren iniciar sesión y usan un token Bearer.',
      source: 'PRORA-BOT · Guía de integración',
      navigate: wantsNavigation ? 'api' : undefined,
    }
  }
  if (question.includes('modelo') || question.includes('predic') || question.includes('pronostic') || question.includes('riesgo')) {
    return {
      answer: wantsNavigation
        ? 'Abrí Modelo y método. Allí se documentan candidatos, validación temporal y territorial, métricas y criterios para promover un modelo.'
        : 'Una predicción debe indicar territorio, horizonte, corte de observación, versión, intervalo e impulsores. Si el dato está rezagado o el modelo no es elegible, PRORA lo muestra como histórico y no como riesgo vigente.',
      source: 'PRORA-BOT · Guía metodológica',
      navigate: wantsNavigation ? 'methodology' : undefined,
    }
  }
  if (question.includes('caso') || question.includes('corte') || question.includes('semana')) {
    return {
      answer: '“Casos de la semana” corresponde únicamente al último corte del territorio elegido; no es un acumulado. Para evitar confusión, compara también los acumulados de 4 y 12 semanas, la variación contra la ventana anterior y la antigüedad del corte.',
      source: `PRORA-BOT · Lectura guiada · ${contextLabel ?? 'Panorama nacional'}`,
    }
  }
  if (question.includes('mapa') || question.includes('zoom') || question.includes('territorio')) {
    return {
      answer: 'En el mapa usa la rueda para acercar o alejar, arrastra para desplazarte y pulsa el control de mira para restablecer la vista. El selector territorial permite buscar por municipio, departamento o código DANE.',
      source: 'PRORA-BOT · Ayuda de navegación',
      navigate: wantsNavigation ? 'overview' : undefined,
    }
  }
  if (question.includes('configur') || question.includes('cuenta') || question.includes('sesion')) {
    return {
      answer: wantsNavigation
        ? 'Abrí Configuración. Desde allí puedes gestionar perfil, apariencia y preferencias persistentes de alertas.'
        : 'Sin iniciar sesión puedes consultar datos públicos. Con una cuenta, PRORA sincroniza preferencias, reglas y suscripciones mediante el backend.',
      source: 'PRORA-BOT · Guía de cuenta',
      navigate: wantsNavigation ? 'settings' : undefined,
    }
  }
  if (question.includes('ayuda') && wantsNavigation) {
    return { answer: 'Abrí el Centro de ayuda con guías de interpretación, operación y soporte.', source: 'PRORA-BOT · Guía de plataforma', navigate: 'help' }
  }
  if (wantsNavigation && (question.includes('panorama') || question.includes('tablero') || question.includes('inicio'))) {
    return { answer: 'Abrí el Panorama nacional. Desde aquí puedes elegir enfermedad, territorio, horizonte y nivel de lectura.', source: 'PRORA-BOT · Guía de plataforma', navigate: 'overview' }
  }

  return {
    answer: 'La API no respondió a esta consulta, pero puedo ayudarte sin inventar datos: pregunta cómo interpretar un corte, usar el mapa, revisar fuentes, probar la API, entender un modelo o gestionar alertas. También puedes escribir “abrir alertas”, “abrir fuentes” o “abrir metodología”.',
    source: 'PRORA-BOT · Modo de ayuda local',
  }
}

export default function ProraAgent({ contextLabel, onNavigate }: ProraAgentProps) {
  const [isOpen, setIsOpen] = useState(false)
  const [messages, setMessages] = useState<AgentMessage[]>(() => loadMessages(contextLabel))
  const [analysisContext, setAnalysisContext] = useState<AnalysisContext>(loadAnalysisContext)
  const [draft, setDraft] = useState('')
  const [isThinking, setIsThinking] = useState(false)
  const endRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const suggestedPrompts = useMemo(() => quickPrompts, [])

  useEffect(() => { localStorage.setItem(STORAGE_KEY, JSON.stringify(messages.slice(-24))) }, [messages])

  useEffect(() => {
    if (isOpen) {
      endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
      window.setTimeout(() => inputRef.current?.focus(), 100)
    }
  }, [isOpen, messages, isThinking])

  useEffect(() => {
    const handleEscape = (event: globalThis.KeyboardEvent) => { if (event.key === 'Escape') setIsOpen(false) }
    window.addEventListener('keydown', handleEscape)
    return () => window.removeEventListener('keydown', handleEscape)
  }, [])

  useEffect(() => {
    const updateContext = (event: Event) => {
      const detail = (event as CustomEvent<AnalysisContext>).detail
      setAnalysisContext(detail && typeof detail === 'object' ? detail : loadAnalysisContext())
    }
    window.addEventListener('prora-analysis-context', updateContext)
    return () => window.removeEventListener('prora-analysis-context', updateContext)
  }, [])

  const analysisLabel = analysisContext.municipality
    ? `${analysisContext.disease_label ?? analysisContext.disease ?? 'Evento'} en ${analysisContext.municipality}${analysisContext.department ? `, ${analysisContext.department}` : ''}`
    : contextLabel ?? 'Panorama nacional'

  const appendAnswer = (answer: LocalAnswer) => {
    if (answer.navigate) onNavigate?.(answer.navigate)
    setMessages((current) => [...current, {
      id: makeId(),
      role: 'assistant',
      content: answer.answer,
      source: answer.source,
      timestamp: formatTime(),
    }])
  }

  const submitPrompt = (prompt: string) => {
    const normalized = prompt.trim()
    if (!normalized || isThinking) return
    setMessages((current) => [...current, { id: makeId(), role: 'user', content: normalized, timestamp: formatTime() }])
    setDraft('')
    setIsThinking(true)

    if (/(abre|abrir|ir a|llévame|llevame|muestra|ver)/i.test(normalized)) {
      appendAnswer(localAnswer(normalized, contextLabel))
      setIsThinking(false)
      return
    }

    void proraApi.agent.query(normalized, {
      view: contextLabel ?? 'Panorama nacional',
      disease: analysisContext.disease,
      territory_code: analysisContext.territory_code,
      municipality: analysisContext.municipality,
      department: analysisContext.department,
      horizon: analysisContext.horizon,
    })
      .then((response) => {
        setMessages((current) => [...current, {
          id: makeId(),
          role: 'assistant',
          content: response.answer,
          source: response.sources.map((source) => source.label).slice(0, 3).join(' · ') || 'PRORA-BOT · Motor determinista',
          timestamp: formatTime(),
        }])
      })
      .catch((error: unknown) => {
        const fallback = localAnswer(normalized, contextLabel)
        if (error instanceof ApiError && error.status) fallback.source += ` · API ${error.status}`
        appendAnswer(fallback)
      })
      .finally(() => setIsThinking(false))
  }

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => { event.preventDefault(); submitPrompt(draft) }
  const handleInputKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Escape') { event.preventDefault(); setIsOpen(false) }
  }
  const clearConversation = () => {
    setIsThinking(false)
    setMessages([createWelcomeMessage(contextLabel)])
    inputRef.current?.focus()
  }

  return (
    <aside className={`prora-agent ${isOpen ? 'prora-agent--open' : ''}`} aria-label="PRORA-BOT, asistente de consulta epidemiológica">
      {isOpen && (
        <section className="prora-agent-panel" id="prora-agent-panel" aria-label="Conversación con PRORA-BOT">
          <header className="prora-agent-header">
            <div className="prora-agent-identity"><span className="prora-agent-avatar" aria-hidden="true"><Sparkles size={19} /></span><span><strong>PRORA-BOT</strong><small><i /> API local + ayuda determinista</small></span></div>
            <div className="prora-agent-header-actions"><button type="button" onClick={clearConversation} aria-label="Limpiar conversación" title="Limpiar conversación"><Eraser size={17} /></button><button type="button" onClick={() => setIsOpen(false)} aria-label="Minimizar PRORA-BOT" title="Minimizar"><ChevronDown size={18} /></button></div>
          </header>

          <div className="prora-agent-context"><ShieldCheck size={15} /><span>{analysisLabel} · datos agregados, sin información personal</span></div>

          <div className="prora-agent-messages" role="log" aria-live="polite" aria-relevant="additions">
            {messages.map((message) => <article key={message.id} className={`prora-agent-message prora-agent-message--${message.role}`}>{message.role === 'assistant' && <span className="prora-agent-message-icon" aria-hidden="true"><Bot size={15} /></span>}<div><p>{message.content}</p><footer>{message.source && <span><CheckCircle2 size={12} /> {message.source}</span>}<time>{message.timestamp}</time></footer></div></article>)}
            {isThinking && <div className="prora-agent-thinking" aria-label="PRORA-BOT está consultando"><span /><span /><span /><small>Consultando datos</small></div>}
            <div ref={endRef} />
          </div>

          <div className="prora-agent-suggestions" aria-label="Preguntas sugeridas">{suggestedPrompts.map(({ label, prompt, icon: Icon }) => <button key={label} type="button" onClick={() => submitPrompt(prompt)} disabled={isThinking}><Icon size={13} /> {label}</button>)}</div>

          <form className="prora-agent-composer" onSubmit={handleSubmit}>
            <label className="sr-only" htmlFor="prora-agent-input">Pregunta a PRORA-BOT</label>
            <input ref={inputRef} id="prora-agent-input" value={draft} onChange={(event) => setDraft(event.target.value)} onKeyDown={handleInputKeyDown} placeholder="Pregunta por un corte, territorio, alerta o modelo…" autoComplete="off" maxLength={360} />
            <button type="submit" disabled={!draft.trim() || isThinking} aria-label="Enviar pregunta"><Send size={17} /></button>
          </form>
          <p className="prora-agent-disclaimer">Si la API no responde, PRORA-BOT conserva la ayuda operativa sin generar cifras.</p>
        </section>
      )}

      <button type="button" className="prora-agent-launcher" onClick={() => setIsOpen((current) => !current)} aria-expanded={isOpen} aria-controls="prora-agent-panel" aria-label={isOpen ? 'Cerrar PRORA-BOT' : 'Abrir PRORA-BOT'}>
        {isOpen ? <X size={21} /> : <MessageSquareText size={22} />}
        {!isOpen && <span><strong>PRORA-BOT</strong><small>Consulta y guía</small></span>}
        {!isOpen && <i aria-hidden="true" />}
      </button>
    </aside>
  )
}
