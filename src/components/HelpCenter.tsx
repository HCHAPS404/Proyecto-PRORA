import { BookOpen, CheckCircle2, ChevronDown, CircleHelp, ExternalLink, LifeBuoy, Mail, Search, ShieldCheck, X } from 'lucide-react'
import { useMemo, useState } from 'react'

const articles = [
  { category: 'Primeros pasos', title: '¿Cómo interpretar un nivel de riesgo?', text: 'El nivel resume una predicción publicada por el backend. Úsalo para priorizar validaciones y revisa siempre fecha de corte, versión del modelo, incertidumbre y contexto territorial; no equivale a un diagnóstico.' },
  { category: 'Primeros pasos', title: '¿Cómo cambio el municipio que estoy viendo?', text: 'Desde Panorama nacional usa el selector Territorio o selecciona un punto con predicción publicada en el mapa de Colombia.' },
  { category: 'Alertas', title: '¿Cómo creo una regla o suscripción?', text: 'En Centro de alertas abre Configurar regla para definir enfermedad, territorios, umbral, horizonte y canales. Gestionar notificaciones permite crear, editar y eliminar suscripciones guardadas en tu cuenta.' },
  { category: 'Datos', title: '¿Qué fuentes alimentan el sistema?', text: 'Fuentes y datos muestra únicamente el catálogo informado por la API, junto con estado de ingesta, cobertura, periodo persistido, calidad y trazabilidad disponibles.' },
  { category: 'Integraciones', title: '¿Dónde encuentro la API?', text: 'API e integraciones contiene endpoints, parámetros, respuestas reales y ejemplos cURL. Las operaciones privadas requieren una sesión autenticada.' },
]

const responsibleUse = [
  'Confirma que la predicción esté vigente y que su territorio, enfermedad y horizonte correspondan a la decisión.',
  'Contrasta la alerta con vigilancia de campo, lineamientos institucionales y criterio epidemiológico.',
  'Revisa intervalos de incertidumbre, calidad de datos, advertencias y versión del modelo antes de escalar.',
  'Documenta la revisión y el motivo de cualquier acción; una alerta prioriza trabajo, no sustituye protocolos.',
  'No ingreses datos personales o identificables de pacientes en búsquedas, notas ni consultas al agente.',
]

type HelpView = 'overview' | 'data' | 'api'

export default function HelpCenter({ onGoTo }: { onNotify?: (message: string) => void; onGoTo?: (view: HelpView) => void }) {
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState(articles[0].title)
  const [showCriteria, setShowCriteria] = useState(false)
  const [showSupport, setShowSupport] = useState(false)
  const filtered = useMemo(() => articles.filter((article) => `${article.title} ${article.category}`.toLowerCase().includes(query.toLowerCase())), [query])

  return (
    <section className="workspace-view help-view" aria-labelledby="help-title">
      <header className="view-heading"><div><span className="eyebrow"><LifeBuoy size={15}/> Acompañamiento territorial</span><h1 id="help-title">Centro de ayuda</h1><p>Encuentra respuestas rápidas, guías y rutas verificables para trabajar con PRORA.</p></div><button className="button button-primary" onClick={() => setShowSupport((value) => !value)} aria-expanded={showSupport}><Mail size={16}/> Estado del soporte</button></header>

      {showSupport && <article className="content-card support-status-panel" role="status"><span className="settings-icon"><LifeBuoy size={19}/></span><div><h2>Soporte institucional no configurado</h2><p>Este despliegue no publica todavía correo, mesa de servicio ni endpoint de recuperación. Para incidencias de acceso, solicita al administrador del despliegue que defina un canal oficial; PRORA no mostrará direcciones supuestas.</p></div><button className="icon-button" type="button" onClick={() => setShowSupport(false)} aria-label="Cerrar estado del soporte"><X size={17}/></button></article>}

      <div className="help-hero"><div><span className="help-hero-icon"><CircleHelp size={26}/></span><h2>¿Qué necesitas resolver?</h2><p>Busca por alertas, datos, API o interpretación del modelo.</p></div><label className="help-search"><Search size={18}/><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Buscar en el centro de ayuda…" aria-label="Buscar en el centro de ayuda" /></label></div>
      <div className="help-grid">
        <article className="content-card faq-card"><div className="card-heading-row"><div><span className="eyebrow"><BookOpen size={14}/> Guías frecuentes</span><h2>Respuestas para comenzar</h2></div><span className="help-count">{filtered.length} artículos</span></div><div className="faq-list">{filtered.map((article) => <div className={open === article.title ? 'faq-item is-open' : 'faq-item'} key={article.title}><button onClick={() => setOpen(open === article.title ? '' : article.title)} aria-expanded={open === article.title}><span><small>{article.category}</small><strong>{article.title}</strong></span><ChevronDown size={17}/></button>{open === article.title && <p>{article.text}</p>}</div>)}</div>{filtered.length === 0 && <div className="empty-state"><Search size={25}/><h3>No encontramos esa guía</h3><p>Prueba con otra palabra clave.</p></div>}</article>
        <aside className="help-aside"><article className="content-card help-contact-card"><ShieldCheck size={24}/><h2>Vigilancia responsable</h2><p>Consulta los criterios que deben acompañar cualquier interpretación o actuación basada en PRORA.</p><button className="button button-ghost button-block" onClick={() => setShowCriteria(true)}>Leer criterios de uso <ExternalLink size={14}/></button></article><article className="content-card help-shortcuts"><h2>Accesos rápidos</h2><button onClick={() => onGoTo?.('overview')}><span>01</span> Ver el panorama nacional <ExternalLink size={14}/></button><button onClick={() => onGoTo?.('data')}><span>02</span> Explorar las fuentes de datos <ExternalLink size={14}/></button><button onClick={() => onGoTo?.('api')}><span>03</span> Consultar la documentación API <ExternalLink size={14}/></button></article></aside>
      </div>

      {showCriteria && <div className="modal-backdrop criteria-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && setShowCriteria(false)}><section className="criteria-modal" role="dialog" aria-modal="true" aria-labelledby="criteria-title"><div className="card-heading-row"><div><span className="eyebrow"><ShieldCheck size={14}/> Uso responsable</span><h2 id="criteria-title">Criterios mínimos de interpretación</h2></div><button className="icon-button" type="button" onClick={() => setShowCriteria(false)} aria-label="Cerrar criterios"><X size={18}/></button></div><p>Aplica estos controles antes de convertir una señal predictiva en una acción operativa.</p><ul>{responsibleUse.map((criterion) => <li key={criterion}><CheckCircle2 size={18}/><span>{criterion}</span></li>)}</ul><div className="technical-note"><ShieldCheck size={17}/><span><strong>Límite de uso:</strong> PRORA apoya priorización y vigilancia; no diagnostica pacientes ni reemplaza la autoridad sanitaria.</span></div><button className="button button-primary button-block" type="button" onClick={() => setShowCriteria(false)}>Entendido</button></section></div>}
    </section>
  )
}
