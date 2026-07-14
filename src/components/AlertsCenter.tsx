import { FormEvent, useEffect, useMemo, useState } from 'react'
import type { LucideIcon } from 'lucide-react'
import {
  Bell,
  BellRing,
  Check,
  CheckCircle2,
  ChevronRight,
  Clock3,
  CloudRain,
  Droplets,
  Edit3,
  Filter,
  HeartPulse,
  LoaderCircle,
  Mail,
  MapPin,
  Plus,
  Save,
  Search,
  ShieldAlert,
  Smartphone,
  Sparkles,
  Trash2,
  TriangleAlert,
  Wind,
  X,
} from 'lucide-react'
import {
  ApiError,
  apiProfile,
  apiSession,
  proraApi,
  type AlertChannel,
  type AlertRuleInput,
  type ApiAlertEvent,
  type ApiAlertRule,
  type ApiSubscription,
  type ApiUser,
} from '../lib/api'

type RiskLevel = 'Crítico' | 'Alto' | 'Moderado'

type AlertItem = {
  id: string
  disease: string
  municipality: string
  department: string
  code: string
  risk: number
  level: RiskLevel
  horizon: string
  predictedCases: string
  drivers: string[]
  updated: string
  status: string
  operational: boolean
}

type SubscriptionPreset = {
  id: string
  topic: ApiSubscription['topic']
  name: string
  detail: string
  channel: string
  icon: LucideIcon
  target: string
  frequency: ApiSubscription['frequency']
  channels: ApiSubscription['channels']
}

type RuleForm = {
  id?: string
  name: string
  disease: string
  territories: string
  riskThreshold: number
  horizonWeeks: number
  channels: AlertChannel[]
  notes: string
  enabled: boolean
}

type SubscriptionForm = {
  id?: string
  topic: ApiSubscription['topic']
  target: string
  frequency: ApiSubscription['frequency']
  channels: AlertChannel[]
  enabled: boolean
}

const diseaseOptions = ['dengue', 'malaria', 'chikunguna', 'zika', 'leishmaniasis', 'ira']
const channelOptions: { id: AlertChannel; label: string }[] = [
  { id: 'in_app', label: 'En la plataforma' },
  { id: 'email', label: 'Correo (requiere proveedor)' },
  { id: 'push', label: 'Push (requiere proveedor)' },
  { id: 'webhook', label: 'Webhook (requiere proveedor)' },
]

const subscriptionOptions: SubscriptionPreset[] = [
  { id: 'critical-email', topic: 'critical_alerts', name: 'Alertas críticas', detail: 'Todos los territorios', channel: 'Plataforma · correo al configurar proveedor', icon: Mail, target: 'all', frequency: 'immediate', channels: ['email', 'in_app'] },
  { id: 'watched-mobile', topic: 'territory_watch', name: 'Territorios vigilados', detail: 'Selección por código DANE', channel: 'Plataforma · push al configurar proveedor', icon: Smartphone, target: 'selected', frequency: 'immediate', channels: ['push', 'in_app'] },
  { id: 'weekly-digest', topic: 'epidemiological_summary', name: 'Resumen epidemiológico', detail: 'Cobertura nacional', channel: 'Correo · requiere proveedor', icon: Bell, target: 'national', frequency: 'weekly', channels: ['email'] },
]

const emptyRule: RuleForm = { name: '', disease: 'dengue', territories: '', riskThreshold: 75, horizonWeeks: 4, channels: ['in_app'], notes: '', enabled: true }
const emptySubscription: SubscriptionForm = { topic: 'critical_alerts', target: 'all', frequency: 'immediate', channels: ['email', 'in_app'], enabled: true }

export type AlertsCenterProps = {
  onOpenAlert?: (alert: AlertItem) => void
  onNotify?: (message: string) => void
}

function titleCase(value: string) {
  return value.length > 0 ? `${value[0].toUpperCase()}${value.slice(1)}` : value
}

function mapRiskLevel(value: string): RiskLevel {
  const normalized = value.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase()
  if (normalized === 'critico') return 'Crítico'
  if (normalized === 'alto') return 'Alto'
  return 'Moderado'
}

function driverLabel(driver: Record<string, unknown>) {
  const raw = driver.feature ?? driver.name ?? driver.variable ?? driver.label
  return typeof raw === 'string' && raw.trim() ? raw.replace(/_/g, ' ') : 'Variable explicativa'
}

function mapAlert(alert: ApiAlertEvent): AlertItem {
  const disease = alert.disease === 'ira' ? 'IRA' : titleCase(alert.disease)
  const lower = Number.isFinite(alert.lower_bound) ? Math.round(alert.lower_bound) : Math.round(alert.predicted_cases)
  const upper = Number.isFinite(alert.upper_bound) ? Math.round(alert.upper_bound) : Math.round(alert.predicted_cases)
  return {
    id: alert.id,
    disease,
    municipality: alert.municipality,
    department: alert.department,
    code: alert.cod_dane,
    risk: Math.round(alert.risk_score),
    level: mapRiskLevel(alert.risk_level),
    horizon: `${alert.horizon} semanas`,
    predictedCases: `${lower}–${upper}`,
    drivers: alert.drivers.slice(0, 2).map(driverLabel),
    updated: new Intl.DateTimeFormat('es-CO', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(alert.created_at)),
    status: alert.status,
    operational: alert.operationally_eligible,
  }
}

function isActiveStatus(status: string) {
  return status === 'open' || status === 'active'
}

function statusBucket(alert: AlertItem) {
  if (alert.status === 'acknowledged') return 'Revisadas'
  if (alert.status === 'closed' || alert.status === 'false_positive') return 'Cerradas'
  if (!alert.operational || alert.status === 'archived') return 'Archivadas'
  if (isActiveStatus(alert.status)) return 'Activas'
  return 'Cerradas'
}

function alertStatusLabel(alert: AlertItem) {
  if (alert.status === 'acknowledged') return 'Revisada'
  if (alert.status === 'false_positive') return 'Falso positivo'
  if (alert.status === 'closed') return 'Cerrada'
  if (!alert.operational || alert.status === 'archived') return 'Archivada'
  return 'Pendiente de revisión'
}

function alertStatusDescription(alert: AlertItem) {
  const label = alertStatusLabel(alert)
  if (label === 'Pendiente de revisión') return 'Alerta operativa vigente'
  if (label === 'Archivada') return 'Señal retrospectiva archivada'
  if (label === 'Falso positivo') return 'Marcada como falso positivo'
  return `Alerta ${label.toLocaleLowerCase('es')}`
}

function ruleToForm(rule: ApiAlertRule): RuleForm {
  return {
    id: rule.id,
    name: rule.name,
    disease: rule.disease,
    territories: rule.territories.join(', '),
    riskThreshold: Math.round(rule.risk_threshold * 100),
    horizonWeeks: rule.horizon_weeks,
    channels: rule.channels,
    notes: rule.notes ?? '',
    enabled: rule.enabled,
  }
}

function subscriptionToForm(subscription: ApiSubscription): SubscriptionForm {
  return { id: subscription.id, topic: subscription.topic, target: subscription.target, frequency: subscription.frequency, channels: subscription.channels, enabled: subscription.enabled }
}

function topicLabel(topic: ApiSubscription['topic']) {
  return ({ critical_alerts: 'Alertas críticas', territory_watch: 'Vigilancia territorial', epidemiological_summary: 'Resumen epidemiológico', model_drift: 'Deriva del modelo' } as const)[topic]
}

export default function AlertsCenter({ onOpenAlert, onNotify }: AlertsCenterProps) {
  const authenticated = apiSession.isRegistered()
  const profile = apiProfile.load<Partial<ApiUser>>()
  const role = apiSession.role() ?? profile?.role ?? null
  const canReview = authenticated && (role === 'analyst' || role === 'admin')
  const [query, setQuery] = useState('')
  const [level, setLevel] = useState<'Todas' | RiskLevel>('Todas')
  const [disease, setDisease] = useState('Todas')
  const [alertStatus, setAlertStatus] = useState<'Todas' | 'Activas' | 'Revisadas' | 'Archivadas' | 'Cerradas'>('Todas')
  const [alertItems, setAlertItems] = useState<AlertItem[]>([])
  const [loadingAlerts, setLoadingAlerts] = useState(true)
  const [alertsError, setAlertsError] = useState('')
  const [acknowledged, setAcknowledged] = useState<Set<string>>(new Set())
  const [rules, setRules] = useState<ApiAlertRule[]>([])
  const [subscriptions, setSubscriptions] = useState<ApiSubscription[]>([])
  const [accountState, setAccountState] = useState<'guest' | 'loading' | 'ready' | 'error'>(authenticated ? 'loading' : 'guest')
  const [accountError, setAccountError] = useState('')
  const [editor, setEditor] = useState<'rule' | 'subscription' | null>(null)
  const [ruleForm, setRuleForm] = useState<RuleForm>(emptyRule)
  const [subscriptionForm, setSubscriptionForm] = useState<SubscriptionForm>(emptySubscription)
  const [savingConfig, setSavingConfig] = useState(false)
  const [configError, setConfigError] = useState('')
  const [showSubscriptionManager, setShowSubscriptionManager] = useState(false)
  const [showNationalAnalysis, setShowNationalAnalysis] = useState(false)
  const [selectedAlert, setSelectedAlert] = useState<AlertItem | null>(null)

  useEffect(() => {
    let active = true
    proraApi.alerts.list()
      .then((records) => {
        if (!active) return
        setAlertItems(records.map(mapAlert))
        setAcknowledged(new Set(records.filter((record) => record.status === 'acknowledged').map((record) => record.id)))
        setAlertsError('')
      })
      .catch((error: unknown) => { if (active) setAlertsError(error instanceof Error ? error.message : 'No fue posible consultar las alertas.') })
      .finally(() => { if (active) setLoadingAlerts(false) })
    return () => { active = false }
  }, [])

  useEffect(() => {
    if (!authenticated) return
    let active = true
    setAccountState('loading')
    Promise.all([proraApi.alertRules.list(), proraApi.subscriptions.list()])
      .then(([ruleRecords, subscriptionRecords]) => {
        if (!active) return
        setRules(ruleRecords)
        setSubscriptions(subscriptionRecords)
        setAccountError('')
        setAccountState('ready')
      })
      .catch((error: unknown) => {
        if (!active) return
        setAccountError(error instanceof Error ? error.message : 'No fue posible consultar reglas y suscripciones.')
        setAccountState('error')
      })
    return () => { active = false }
  }, [authenticated])

  const diseases = ['Todas', ...Array.from(new Set(alertItems.map((alert) => alert.disease)))]
  const visibleAlerts = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase('es')
    return alertItems.filter((alert) => {
      const matchesText = !normalized || `${alert.disease} ${alert.municipality} ${alert.department}`.toLocaleLowerCase('es').includes(normalized)
      return matchesText && (level === 'Todas' || alert.level === level) && (disease === 'Todas' || alert.disease === disease) && (alertStatus === 'Todas' || statusBucket(alert) === alertStatus)
    })
  }, [alertItems, alertStatus, disease, level, query])

  const activeAlerts = alertItems.filter((alert) => statusBucket(alert) === 'Activas')
  const activeCount = activeAlerts.length
  const reviewedCount = alertItems.filter((alert) => statusBucket(alert) === 'Revisadas').length
  const archivedCount = alertItems.filter((alert) => statusBucket(alert) === 'Archivadas').length
  const closedCount = alertItems.filter((alert) => statusBucket(alert) === 'Cerradas').length
  const historicalCount = reviewedCount + archivedCount + closedCount
  const criticalCount = activeAlerts.filter((alert) => alert.level === 'Crítico').length
  const diseaseCount = new Set(activeAlerts.map((alert) => alert.disease)).size
  const reviewedRate = alertItems.length ? `${Math.round((reviewedCount / alertItems.length) * 100)}%` : '—'
  const horizonSummary = Array.from(new Set(activeAlerts.map((alert) => alert.horizon))).join(' · ') || '—'
  const metricsAvailable = !loadingAlerts && !alertsError
  const rankedDrivers = Object.entries(activeAlerts.flatMap((alert) => alert.drivers).reduce<Record<string, number>>((counts, driver) => {
    counts[driver] = (counts[driver] ?? 0) + 1
    return counts
  }, {})).sort((left, right) => right[1] - left[1])
  const primaryDriver = rankedDrivers[0]

  const acknowledge = async (id: string) => {
    if (!canReview) {
      onNotify?.(authenticated ? 'La revisión requiere un perfil analista o administrador.' : 'Inicia sesión con un perfil analista o administrador para revisar alertas.')
      return
    }
    try {
      const reviewed = await proraApi.alerts.review(id, { status: 'acknowledged', notes: 'Revisada desde el centro de alertas de PRORA.' })
      const mapped = mapAlert(reviewed)
      setAlertItems((current) => current.map((alert) => alert.id === mapped.id ? mapped : alert))
      setSelectedAlert((current) => current?.id === mapped.id ? mapped : current)
      setAcknowledged((current) => new Set(current).add(id))
      onNotify?.('Alerta marcada como revisada y guardada.')
    } catch (error) {
      const message = error instanceof ApiError && error.status === 403 ? 'La revisión requiere un perfil analista o administrador.' : error instanceof Error ? error.message : 'No fue posible revisar la alerta.'
      onNotify?.(message)
    }
  }

  const openAlertDetail = (alert: AlertItem) => {
    setSelectedAlert(alert)
    onOpenAlert?.(alert)
  }

  const openRuleEditor = (rule?: ApiAlertRule) => {
    setRuleForm(rule ? ruleToForm(rule) : { ...emptyRule, channels: [...emptyRule.channels] })
    setConfigError(authenticated ? '' : 'Inicia sesión para guardar reglas en tu cuenta.')
    setEditor('rule')
  }

  const openSubscriptionEditor = (subscription?: ApiSubscription) => {
    setSubscriptionForm(subscription ? subscriptionToForm(subscription) : { ...emptySubscription, channels: [...emptySubscription.channels] })
    setConfigError(authenticated ? '' : 'Inicia sesión para guardar suscripciones en tu cuenta.')
    setEditor('subscription')
  }

  const toggleChannel = (channel: AlertChannel, current: AlertChannel[], update: (channels: AlertChannel[]) => void) => {
    update(current.includes(channel) ? current.filter((item) => item !== channel) : [...current, channel])
  }

  const saveRule = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!authenticated) return
    if (!ruleForm.channels.length) { setConfigError('Selecciona al menos un canal.'); return }
    const payload: AlertRuleInput = {
      name: ruleForm.name.trim(),
      disease: ruleForm.disease,
      territories: ruleForm.territories.split(',').map((item) => item.trim()).filter(Boolean),
      risk_threshold: Math.max(0, Math.min(100, ruleForm.riskThreshold)) / 100,
      horizon_weeks: ruleForm.horizonWeeks,
      channels: ruleForm.channels,
      enabled: ruleForm.enabled,
      notes: ruleForm.notes.trim() || null,
    }
    setSavingConfig(true)
    setConfigError('')
    try {
      const savedRule = ruleForm.id ? await proraApi.alertRules.update(ruleForm.id, payload) : await proraApi.alertRules.create(payload)
      setRules((current) => ruleForm.id ? current.map((rule) => rule.id === savedRule.id ? savedRule : rule) : [savedRule, ...current])
      setEditor(null)
      onNotify?.(ruleForm.id ? 'Regla actualizada.' : 'Regla creada y guardada.')
    } catch (error) {
      setConfigError(error instanceof Error ? error.message : 'No fue posible guardar la regla.')
    } finally { setSavingConfig(false) }
  }

  const setRuleEnabled = async (rule: ApiAlertRule, enabled: boolean) => {
    try {
      const updated = await proraApi.alertRules.update(rule.id, { enabled })
      setRules((current) => current.map((item) => item.id === updated.id ? updated : item))
    } catch (error) { onNotify?.(error instanceof Error ? error.message : 'No fue posible actualizar la regla.') }
  }

  const removeRule = async (rule: ApiAlertRule) => {
    if (!window.confirm(`¿Eliminar la regla “${rule.name}”?`)) return
    try {
      await proraApi.alertRules.remove(rule.id)
      setRules((current) => current.filter((item) => item.id !== rule.id))
      onNotify?.('Regla eliminada.')
    } catch (error) { onNotify?.(error instanceof Error ? error.message : 'No fue posible eliminar la regla.') }
  }

  const saveSubscription = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!authenticated) return
    if (!subscriptionForm.channels.length) { setConfigError('Selecciona al menos un canal.'); return }
    const payload = { topic: subscriptionForm.topic, target: subscriptionForm.target.trim(), frequency: subscriptionForm.frequency, channels: subscriptionForm.channels, enabled: subscriptionForm.enabled }
    setSavingConfig(true)
    setConfigError('')
    try {
      const savedSubscription = subscriptionForm.id ? await proraApi.subscriptions.update(subscriptionForm.id, payload) : await proraApi.subscriptions.create(payload)
      setSubscriptions((current) => subscriptionForm.id ? current.map((item) => item.id === savedSubscription.id ? savedSubscription : item) : [savedSubscription, ...current])
      setEditor(null)
      setShowSubscriptionManager(true)
      onNotify?.(subscriptionForm.id ? 'Suscripción actualizada.' : 'Suscripción creada y guardada.')
    } catch (error) {
      setConfigError(error instanceof Error ? error.message : 'No fue posible guardar la suscripción.')
    } finally { setSavingConfig(false) }
  }

  const removeSubscription = async (subscription: ApiSubscription) => {
    if (!window.confirm(`¿Eliminar la suscripción “${topicLabel(subscription.topic)}”?`)) return
    try {
      await proraApi.subscriptions.remove(subscription.id)
      setSubscriptions((current) => current.filter((item) => item.id !== subscription.id))
      onNotify?.('Suscripción eliminada.')
    } catch (error) { onNotify?.(error instanceof Error ? error.message : 'No fue posible eliminar la suscripción.') }
  }

  const toggleSubscription = async (option: SubscriptionPreset) => {
    if (!authenticated) { openSubscriptionEditor(); return }
    const existing = subscriptions.find((record) => record.topic === option.topic && record.target === option.target)
    try {
      const record = existing
        ? await proraApi.subscriptions.update(existing.id, { enabled: !existing.enabled })
        : await proraApi.subscriptions.create({ topic: option.topic, target: option.target, frequency: option.frequency, channels: option.channels, enabled: true })
      setSubscriptions((current) => existing ? current.map((item) => item.id === record.id ? record : item) : [record, ...current])
      onNotify?.('Preferencia de notificación guardada.')
    } catch (error) { onNotify?.(error instanceof Error ? error.message : 'No fue posible guardar la preferencia.') }
  }

  const reviewAction = (alert: AlertItem) => {
    if (statusBucket(alert) !== 'Activas') {
      return <span className="reviewed-label"><Check size={15} /> {alertStatusLabel(alert)}</span>
    }
    if (!canReview) {
      return <span className="reviewed-label" title="Solo los perfiles analista y administrador pueden cambiar el estado de una alerta.">{authenticated ? 'Solo analista' : 'Inicia sesión'}</span>
    }
    return <button className="button button-ghost button-small" type="button" onClick={() => void acknowledge(alert.id)}>Revisar</button>
  }

  return (
    <section className="workspace-view alerts-center" aria-labelledby="alerts-title">
      <header className="view-heading">
        <div><span className="eyebrow"><BellRing size={15} /> Monitoreo epidemiológico</span><h1 id="alerts-title">Centro de alertas</h1><p>Priorice señales de riesgo, documente su revisión y configure notificaciones.</p></div>
        <button className="button button-primary" type="button" onClick={() => openRuleEditor()}><Bell size={17} /> Configurar regla de alerta</button>
      </header>

      <div className="metric-strip alerts-metrics">
        <article className="metric-card metric-critical"><span className="metric-icon"><TriangleAlert size={19} /></span><div><strong>{loadingAlerts ? '…' : metricsAvailable ? criticalCount : '—'}</strong><span>riesgos críticos</span><small>Pronósticos publicados</small></div></article>
        <article className="metric-card"><span className="metric-icon"><ShieldAlert size={19} /></span><div><strong>{loadingAlerts ? '…' : metricsAvailable ? activeCount : '—'}</strong><span>alertas activas</span><small>{metricsAvailable ? `${diseaseCount} enfermedades en las alertas` : 'Sin respuesta de API'}</small></div></article>
        <article className="metric-card"><span className="metric-icon"><Clock3 size={19} /></span><div><strong>{loadingAlerts ? '…' : metricsAvailable ? horizonSummary : '—'}</strong><span>horizonte predictivo</span><small>Pronósticos publicados</small></div></article>
        <article className="metric-card"><span className="metric-icon"><CheckCircle2 size={19} /></span><div><strong>{loadingAlerts ? '…' : metricsAvailable ? reviewedRate : '—'}</strong><span>alertas revisadas</span><small>Estado persistido</small></div></article>
      </div>

      {editor === 'rule' && <article className="content-card alert-config-panel"><div className="card-heading-row"><div><span className="eyebrow"><Bell size={14}/> Regla persistida</span><h2>{ruleForm.id ? 'Editar regla de alerta' : 'Nueva regla de alerta'}</h2><p>Define exactamente cuándo y dónde debe notificarse una señal.</p></div><button className="icon-button" type="button" onClick={() => setEditor(null)} aria-label="Cerrar formulario"><X size={18}/></button></div><form onSubmit={saveRule}><div className="form-grid"><label className="form-field">Nombre<input required minLength={2} maxLength={140} value={ruleForm.name} onChange={(event) => setRuleForm((current) => ({ ...current, name: event.target.value }))} placeholder="Dengue crítico en territorios priorizados" /></label><label className="form-field">Enfermedad<select value={ruleForm.disease} onChange={(event) => setRuleForm((current) => ({ ...current, disease: event.target.value }))}>{diseaseOptions.map((item) => <option value={item} key={item}>{item === 'ira' ? 'IRA' : titleCase(item)}</option>)}</select></label><label className="form-field form-field-wide">Territorios <small>Códigos DANE separados por coma; vacío aplica a todos</small><input value={ruleForm.territories} onChange={(event) => setRuleForm((current) => ({ ...current, territories: event.target.value }))} placeholder="76001, 91001" /></label><label className="form-field">Umbral de riesgo (%)<input type="number" min="0" max="100" required value={ruleForm.riskThreshold} onChange={(event) => setRuleForm((current) => ({ ...current, riskThreshold: Number(event.target.value) }))} /></label><label className="form-field">Horizonte (semanas)<select required value={ruleForm.horizonWeeks} onChange={(event) => setRuleForm((current) => ({ ...current, horizonWeeks: Number(event.target.value) }))}><option value={3}>3 semanas</option><option value={4}>4 semanas</option></select></label><fieldset className="form-field form-field-wide channel-fieldset"><legend>Canales</legend><div>{channelOptions.map((channel) => <label key={channel.id}><input type="checkbox" checked={ruleForm.channels.includes(channel.id)} onChange={() => toggleChannel(channel.id, ruleForm.channels, (channels) => setRuleForm((current) => ({ ...current, channels })))} /> {channel.label}</label>)}</div></fieldset><label className="form-field form-field-wide">Notas<textarea maxLength={2000} value={ruleForm.notes} onChange={(event) => setRuleForm((current) => ({ ...current, notes: event.target.value }))} placeholder="Contexto para el equipo que revisará la alerta" /></label><label className="checkbox-label form-field-wide"><input type="checkbox" checked={ruleForm.enabled} onChange={(event) => setRuleForm((current) => ({ ...current, enabled: event.target.checked }))}/> Activar regla al guardar</label></div>{configError && <div className="inline-notice"><TriangleAlert size={16}/>{configError}</div>}<div className="config-form-actions"><button className="button button-secondary" type="button" onClick={() => setEditor(null)}>Cancelar</button><button className="button button-primary" type="submit" disabled={!authenticated || savingConfig}>{savingConfig ? <LoaderCircle className="spin" size={16}/> : <Save size={16}/>} {ruleForm.id ? 'Guardar cambios' : 'Crear regla'}</button></div></form></article>}

      {editor === 'subscription' && <article className="content-card alert-config-panel"><div className="card-heading-row"><div><span className="eyebrow"><Mail size={14}/> Canal persistido</span><h2>{subscriptionForm.id ? 'Editar suscripción' : 'Nueva suscripción'}</h2><p>Selecciona el tema, alcance, frecuencia y canales.</p></div><button className="icon-button" type="button" onClick={() => setEditor(null)} aria-label="Cerrar formulario"><X size={18}/></button></div><form onSubmit={saveSubscription}><div className="form-grid"><label className="form-field">Tema<select value={subscriptionForm.topic} onChange={(event) => setSubscriptionForm((current) => ({ ...current, topic: event.target.value as ApiSubscription['topic'] }))}><option value="critical_alerts">Alertas críticas</option><option value="territory_watch">Vigilancia territorial</option><option value="epidemiological_summary">Resumen epidemiológico</option><option value="model_drift">Deriva del modelo</option></select></label><label className="form-field">Frecuencia<select value={subscriptionForm.frequency} onChange={(event) => setSubscriptionForm((current) => ({ ...current, frequency: event.target.value as ApiSubscription['frequency'] }))}><option value="immediate">Inmediata</option><option value="daily">Diaria</option><option value="weekly">Semanal</option></select></label><label className="form-field form-field-wide">Destino<input required maxLength={160} value={subscriptionForm.target} onChange={(event) => setSubscriptionForm((current) => ({ ...current, target: event.target.value }))} placeholder="all, national o código DANE" /></label><fieldset className="form-field form-field-wide channel-fieldset"><legend>Canales</legend><div>{channelOptions.map((channel) => <label key={channel.id}><input type="checkbox" checked={subscriptionForm.channels.includes(channel.id)} onChange={() => toggleChannel(channel.id, subscriptionForm.channels, (channels) => setSubscriptionForm((current) => ({ ...current, channels })))} /> {channel.label}</label>)}</div></fieldset><label className="checkbox-label form-field-wide"><input type="checkbox" checked={subscriptionForm.enabled} onChange={(event) => setSubscriptionForm((current) => ({ ...current, enabled: event.target.checked }))}/> Suscripción activa</label></div>{configError && <div className="inline-notice"><TriangleAlert size={16}/>{configError}</div>}<div className="config-form-actions"><button className="button button-secondary" type="button" onClick={() => setEditor(null)}>Cancelar</button><button className="button button-primary" type="submit" disabled={!authenticated || savingConfig}>{savingConfig ? <LoaderCircle className="spin" size={16}/> : <Save size={16}/>} {subscriptionForm.id ? 'Guardar cambios' : 'Crear suscripción'}</button></div></form></article>}

      <div className="alert-history-toolbar" aria-label="Vigencia de las alertas">
        <div><Clock3 size={17}/><span><strong>Señales actuales e historial</strong><small>{loadingAlerts ? 'Consultando registro…' : `${activeCount} activas · ${historicalCount} históricas o resueltas`}</small></span></div>
        <div className="alert-history-tabs" role="group" aria-label="Filtrar por estado de alerta">
          {([
            ['Todas', alertItems.length],
            ['Activas', activeCount],
            ['Revisadas', reviewedCount],
            ['Archivadas', archivedCount],
            ['Cerradas', closedCount],
          ] as const).map(([label, count]) => <button key={label} type="button" className={alertStatus === label ? 'is-active' : ''} aria-pressed={alertStatus === label} onClick={() => setAlertStatus(label)}><span>{label}</span><strong>{loadingAlerts ? '…' : count}</strong></button>)}
        </div>
      </div>

      <div className="alerts-layout">
        <div className="alerts-main-column"><article className="content-card alert-feed-card"><div className="card-heading-row alert-feed-heading"><div><h2>Alertas epidemiológicas</h2><p>Ordenadas por nivel de riesgo predictivo.</p></div><span className="live-label"><span /> {loadingAlerts ? 'Consultando' : alertsError ? 'API no disponible' : alertItems.length ? 'Conectado' : 'Sin publicar'}</span></div><div className="filter-bar"><label className="search-field"><Search size={17} /><span className="sr-only">Buscar alertas</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Municipio, departamento o evento" /></label><label className="select-with-icon"><Filter size={16} /><span className="sr-only">Nivel de riesgo</span><select value={level} onChange={(event) => setLevel(event.target.value as 'Todas' | RiskLevel)}><option>Todas</option><option>Crítico</option><option>Alto</option><option>Moderado</option></select></label><select value={disease} onChange={(event) => setDisease(event.target.value)} aria-label="Filtrar por enfermedad">{diseases.map((item) => <option key={item}>{item}</option>)}</select></div><div className="alerts-table-wrap"><table className="data-table alerts-table"><thead><tr><th>Evento y territorio</th><th>Riesgo</th><th>Proyección</th><th>Principales impulsores</th><th>Actualización</th><th><span className="sr-only">Acciones</span></th></tr></thead><tbody>{visibleAlerts.map((alert) => <tr key={alert.id} className={acknowledged.has(alert.id) ? 'row-acknowledged' : ''}><td><div className="alert-identity"><span className={`disease-mark disease-${alert.disease.toLowerCase()}`}><HeartPulse size={17} /></span><div><strong>{alert.disease}</strong><span><MapPin size={12} /> {alert.municipality}, {alert.department}</span><span><Clock3 size={12} /> {alertStatusDescription(alert)}</span></div></div></td><td><div className="risk-cell"><span className={`risk-pill risk-${alert.level.toLowerCase()}`}>{alert.level}</span><strong>{alert.risk}%</strong></div></td><td><strong>{alert.predictedCases}</strong><span>{alert.horizon}</span></td><td><div className="driver-tags">{alert.drivers.map((driver, index) => <span key={driver}>{index === 0 ? <CloudRain size={12} /> : <Wind size={12} />}{driver}</span>)}</div></td><td><span className="updated-time">{alert.updated}</span></td><td>{reviewAction(alert)}<button className="icon-button" type="button" aria-label={`Abrir alerta de ${alert.disease} en ${alert.municipality}`} onClick={() => openAlertDetail(alert)}><ChevronRight size={17} /></button></td></tr>)}</tbody></table></div><div className="alerts-mobile-list">{visibleAlerts.map((alert) => <article className="mobile-alert-card" key={alert.id}><div className="mobile-alert-heading"><span className={`disease-mark disease-${alert.disease.toLowerCase()}`}><HeartPulse size={17} /></span><div><strong>{alert.disease}</strong><span>{alert.municipality} · {alert.department} · {alertStatusLabel(alert).toLocaleLowerCase('es')}</span></div><span className={`risk-pill risk-${alert.level.toLowerCase()}`}>{alert.level}</span></div><div className="mobile-alert-data"><span>Riesgo <strong>{alert.risk}%</strong></span><span>Casos <strong>{alert.predictedCases}</strong></span><span>Horizonte <strong>{alert.horizon}</strong></span></div><div className="mobile-alert-footer"><span>{alert.updated}</span><button className="button button-ghost button-small" type="button" onClick={() => openAlertDetail(alert)}>Ver detalle <ChevronRight size={14} /></button></div></article>)}</div>{visibleAlerts.length === 0 && <div className="empty-state"><Search size={27} /><h3>{loadingAlerts ? 'Consultando el backend' : alertsError ? 'No fue posible cargar las alertas' : alertItems.length === 0 ? 'No hay alertas publicadas' : 'No hay alertas con estos filtros'}</h3><p>{loadingAlerts ? 'Estamos verificando los pronósticos disponibles.' : alertsError || (alertItems.length === 0 ? 'Cargue datos autorizados y ejecute un entrenamiento para publicar señales predictivas.' : 'Ajuste la búsqueda para ampliar los resultados.')}</p></div>}</article></div>

        <aside className="alerts-side-column">
          <article className="content-card rules-card"><div className="card-heading-row"><div><h2>Mis reglas</h2><p>Umbrales operativos de tu cuenta.</p></div><button className="icon-button" type="button" onClick={() => openRuleEditor()} aria-label="Crear regla"><Plus size={17}/></button></div>{accountState === 'loading' && <div className="compact-loading"><LoaderCircle className="spin" size={18}/> Consultando reglas…</div>}{accountState === 'error' && <div className="inline-notice"><TriangleAlert size={15}/>{accountError}</div>}{accountState === 'guest' && <p className="account-required">Inicia sesión para crear y sincronizar reglas.</p>}<div className="account-rule-list">{rules.map((rule) => <div className="account-rule-row" key={rule.id}><span className={`status-dot${rule.enabled ? ' status-dot--online' : ''}`}/><div><strong>{rule.name}</strong><small>{titleCase(rule.disease)} · {Math.round(rule.risk_threshold * 100)}% · {rule.horizon_weeks} sem.</small></div><button className={`toggle ${rule.enabled ? 'active' : ''}`} type="button" role="switch" aria-checked={rule.enabled} onClick={() => void setRuleEnabled(rule, !rule.enabled)}><span/></button><button className="icon-button" type="button" onClick={() => openRuleEditor(rule)} aria-label={`Editar ${rule.name}`}><Edit3 size={14}/></button><button className="icon-button danger-action" type="button" onClick={() => void removeRule(rule)} aria-label={`Eliminar ${rule.name}`}><Trash2 size={14}/></button></div>)}</div>{accountState === 'ready' && rules.length === 0 && <p className="account-required">Aún no has creado reglas.</p>}</article>

          <article className="content-card subscriptions-card"><div className="card-heading-row"><div><h2>Mis suscripciones</h2><p>Canales y señales persistidas.</p></div><button className="icon-button" type="button" aria-label="Añadir suscripción" onClick={() => openSubscriptionEditor()}><Plus size={17}/></button></div><div className="subscription-list">{subscriptionOptions.map((option) => { const ChannelIcon = option.icon; const record = subscriptions.find((item) => item.topic === option.topic && item.target === option.target); return <div className="subscription-row" key={option.id}><span className="subscription-icon"><ChannelIcon size={17} /></span><div><strong>{option.name}</strong><span>{option.detail}</span><small>{option.channel}</small></div><button className={`toggle ${record?.enabled ? 'active' : ''}`} type="button" role="switch" aria-checked={Boolean(record?.enabled)} aria-label={`${record?.enabled ? 'Desactivar' : 'Activar'} ${option.name}`} onClick={() => void toggleSubscription(option)}><span /></button></div> })}</div><button className="button button-secondary button-block" type="button" onClick={() => setShowSubscriptionManager((value) => !value)} aria-expanded={showSubscriptionManager}>{showSubscriptionManager ? 'Ocultar gestión' : 'Gestionar notificaciones'}</button>{showSubscriptionManager && <div className="subscription-manager">{accountState === 'guest' ? <p>Inicia sesión para gestionar suscripciones.</p> : subscriptions.length ? subscriptions.map((subscription) => <div key={subscription.id}><span><strong>{topicLabel(subscription.topic)}</strong><small>{subscription.target} · {subscription.frequency} · {subscription.channels.join(', ')}</small></span><button className="icon-button" type="button" onClick={() => openSubscriptionEditor(subscription)} aria-label="Editar suscripción"><Edit3 size={14}/></button><button className="icon-button danger-action" type="button" onClick={() => void removeSubscription(subscription)} aria-label="Eliminar suscripción"><Trash2 size={14}/></button></div>) : <p>No hay suscripciones guardadas.</p>}</div>}</article>

          <article className="content-card forecast-callout"><div className="forecast-visual"><Droplets size={25} /><span><Sparkles size={14} /></span></div><span className="eyebrow">Lectura rápida</span><h3>{primaryDriver ? `${titleCase(primaryDriver[0])} concentra las señales actuales` : 'Aún no hay una señal nacional publicada'}</h3><p>{primaryDriver ? `Este impulsor aparece en ${primaryDriver[1]} de ${activeAlerts.length} alertas operativas vigentes.` : 'El resumen se calculará automáticamente con los impulsores de pronósticos validados.'}</p>{showNationalAnalysis && <div className="driver-ranking">{rankedDrivers.slice(0, 5).map(([driver, count]) => <div key={driver}><span>{titleCase(driver)}</span><strong>{count}</strong></div>)}{rankedDrivers.length === 0 && <p>Sin impulsores publicados para analizar.</p>}</div>}<button className="text-button" type="button" onClick={() => setShowNationalAnalysis((value) => !value)} aria-expanded={showNationalAnalysis}>{showNationalAnalysis ? 'Ocultar análisis' : 'Ver análisis nacional'} <ChevronRight size={15} /></button></article>
        </aside>
      </div>

      {selectedAlert && <div className="modal-backdrop criteria-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && setSelectedAlert(null)}><section className="criteria-modal alert-detail-modal" role="dialog" aria-modal="true" aria-labelledby="alert-detail-title"><div className="card-heading-row"><div><span className="eyebrow"><ShieldAlert size={14}/> Pronóstico publicado</span><h2 id="alert-detail-title">{selectedAlert.disease} · {selectedAlert.municipality}</h2><p>{selectedAlert.department} · código DANE {selectedAlert.code}</p></div><button className="icon-button" type="button" onClick={() => setSelectedAlert(null)} aria-label="Cerrar detalle"><X size={18}/></button></div><div className="alert-detail-grid"><div><small>Nivel</small><strong>{selectedAlert.level}</strong></div><div><small>Riesgo</small><strong>{selectedAlert.risk}%</strong></div><div><small>Proyección</small><strong>{selectedAlert.predictedCases} casos</strong></div><div><small>Horizonte</small><strong>{selectedAlert.horizon}</strong></div></div><h3>Impulsores publicados</h3>{selectedAlert.drivers.length ? <div className="driver-tags alert-detail-drivers">{selectedAlert.drivers.map((driver) => <span key={driver}><CloudRain size={13}/>{driver}</span>)}</div> : <p>No se publicaron impulsores para esta alerta.</p>}<div className="technical-note"><Clock3 size={16}/><span>Actualización registrada: {selectedAlert.updated}. La alerta debe contrastarse con vigilancia territorial antes de actuar.</span></div><div className="config-form-actions"><button className="button button-secondary" type="button" onClick={() => setSelectedAlert(null)}>Cerrar</button>{canReview && statusBucket(selectedAlert) === 'Activas' && <button className="button button-primary" type="button" onClick={() => { void acknowledge(selectedAlert.id); setSelectedAlert(null) }}><Check size={16}/> Marcar revisada</button>}</div></section></div>}
    </section>
  )
}
