// Same-origin by default: Vite proxies this path locally and Nginx does the
// same in Docker. GitHub Pages must set VITE_API_BASE_URL to a public HTTPS API
// (Pages cannot host FastAPI). An empty string means "no remote API" → guest mode.
const configuredApi = import.meta.env.VITE_API_BASE_URL
const DEFAULT_API_URL = import.meta.env.DEV
  ? 'http://127.0.0.1:8000/api/v1'
  : '/api/v1'

export const API_BASE_URL = (
  configuredApi === undefined || configuredApi === null
    ? DEFAULT_API_URL
    : String(configuredApi)
).replace(/\/$/, '')

/** True when the build intentionally omits a backend (typical GitHub Pages guest publish). */
export const API_CONFIGURED = API_BASE_URL.length > 0

const ACCESS_TOKEN_KEY = 'prora-access-token'
const REFRESH_TOKEN_KEY = 'prora-refresh-token'
const PROFILE_KEY = 'prora-profile'

export class ApiError extends Error {
  status: number
  details: unknown

  constructor(message: string, status = 0, details?: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.details = details
  }
}

export interface ApiUser {
  id: string
  email: string
  full_name?: string
  name?: string
  organization?: string
  institution?: string
  role: string
  is_registered?: boolean
  is_active?: boolean
  preferences?: Record<string, unknown>
  created_at?: string
}

export interface TokenPair {
  access_token: string
  refresh_token?: string | null
  token_type?: string
  expires_in?: number
  user?: ApiUser
}

export interface ApiPreferences {
  theme: 'light' | 'dark' | 'system'
  locale: string
  timezone: string
  digest_enabled: boolean
  email_alerts: boolean
  push_alerts: boolean
  default_disease?: string | null
  default_territory?: string | null
  accessibility: Record<string, unknown>
}

export interface AgentAnswer {
  answer: string
  sources: { label: string; uri?: string; updated_at?: string }[]
  suggested_questions?: string[]
  trace_id?: string
}

export interface RiskMapItem {
  cod_dane: string
  municipality: string
  department?: string
  disease: string
  horizon: number
  risk_score: number
  risk_level: 'bajo' | 'moderado' | 'alto' | 'critico'
  expected_cases?: number
  lower_bound?: number
  upper_bound?: number
  population?: number
  latitude?: number
  longitude?: number
  updated_at?: string
  target_week?: string
  model_version?: string
  data_completeness?: number
  observation_cutoff?: string | null
  observation_age_days?: number | null
  operationally_eligible?: boolean
  forecast_mode?: 'operational' | 'retrospective_research'
}

export interface DataSourceRecord {
  id: string
  name: string
  institution: string
  source_type: string
  endpoint?: string | null
  dataset_id?: string | null
  status: 'active' | 'degraded' | 'requires_configuration' | 'disabled'
  is_public: boolean
  refresh_cron?: string | null
  configuration: Record<string, unknown>
  last_checked_at?: string | null
  last_success_at?: string | null
}

export interface IngestionRunRecord {
  id: string
  source_id: string
  status: 'pending' | 'running' | 'succeeded' | 'partial' | 'failed'
  started_at: string
  finished_at?: string | null
  rows_read: number
  rows_accepted: number
  rows_rejected: number
  checksum?: string | null
  cursor?: string | null
  provenance?: Record<string, unknown>
  quality_report: Record<string, unknown>
  error_message?: string | null
}

export interface StoredDatasetInventory {
  source_id: string
  source_name: string
  catalog_status: string
  sync_enabled: boolean
  canonical_table: string
  rows: number
  has_stored_data: boolean
  storage_status: 'empty' | 'raw_only' | 'canonical'
  raw_snapshot_count: number
  territorial_resolution: string
  temporal_resolution: string
  period_start?: string | null
  period_end?: string | null
  last_ingestion_at?: string | null
  last_snapshot_sha256?: string | null
  quality_status?: string | null
  rows_rejected_last_run: number
  semantics: string
}

export interface SnapshotManifest {
  ingestion_run_id: string
  source_id: string
  object_sha256: string
  manifest: Record<string, unknown>
}

export interface HistoricalPoint {
  date: string
  epidemiological_week?: number
  observed: number
  predicted?: number
  lower_bound?: number
  upper_bound?: number
  is_preliminary?: boolean
  quality_score?: number
}

export interface ModelMetadata {
  disease: string
  horizon: number
  version: string
  status: string
  trained_at?: string
  activated_at?: string | null
  metrics: Record<string, unknown>
  features?: string[]
  training_period?: { from?: string | null; to?: string | null }
  data_fingerprint?: string | null
  artifact_sha256?: string | null
  pipeline_fingerprint?: string | null
}

export interface ModelVersion {
  disease: string
  horizon: number
  version: string
  stage: string
  created_at: string
  activated_at?: string | null
  data_fingerprint?: string | null
  artifact_sha256?: string | null
  temporal_mae?: number | null
  territorial_mae?: number | null
}

export interface ModelTrace {
  disease: string
  horizon: number
  version: string
  stage: string
  artifact_ref: string
  artifact_sha256: string
  artifact_integrity_valid: boolean
  data_fingerprint?: string | null
  dataset_snapshot_sha256?: string | null
  pipeline_fingerprint?: string | null
  training_job_id?: string | null
  seed?: number | null
  parameters: Record<string, unknown>
  runtime: Record<string, unknown>
  metrics: Record<string, unknown>
  fold_metrics: Record<string, unknown>[]
  dataset: Record<string, unknown>
  features: string[]
  training_period: { from?: string | null; to?: string | null }
  created_at: string
  activated_at?: string | null
}

export interface ModelReadinessDisease {
  disease: string
  data: {
    observed_rows: number
    calendar_rows: number
    reporting_density: number
    explicit_zero_case_rows: number
    territories: number
    unique_weeks: number
    week_start?: string | null
    week_end?: string | null
    observation_age_days?: number | null
    total_cases: number
  }
  research_training_eligible: boolean
  operational_forecast_eligible: boolean
  readiness_level: 'operational' | 'research_only' | 'insufficient'
  requirements: Record<string, boolean>
  models: Array<{
    horizon: number
    state: 'trained' | 'not_trained'
    version?: string | null
    stage?: string | null
    training_period?: { from?: string | null; to?: string | null } | null
    validation: Record<string, unknown>
  }>
  latest_training_job?: Record<string, unknown> | null
  limitations: string[]
}

export interface ModelPortfolioReadiness {
  generated_at: string
  policy: Record<string, unknown>
  diseases: ModelReadinessDisease[]
  covariate_inventory: Record<string, {
    status: 'available' | 'partial' | 'unavailable' | string
    rows?: number
    territories?: number
    from?: string | null
    to?: string | null
    from_year?: number | null
    to_year?: number | null
    reason?: string
    interpretation?: string
  }>
}

export interface RiskExplanation {
  forecast_id: string
  cod_dane: string
  disease: string
  horizon: number
  risk_score: number
  drivers: Record<string, unknown>[]
  component_predictions: Record<string, unknown>
  warnings: string[]
  model_version: string
  observation_cutoff?: string | null
  operationally_eligible: boolean
  probability_calibration: Record<string, unknown>
}

export interface AnalyticsSeriesPoint {
  week: string
  observed_cases: number
  population?: number | null
  incidence_per_100k?: number | null
  mean_quality_score?: number | null
  is_preliminary: boolean
  municipalities_with_notified_cases: number
}

export interface ProvenanceSource {
  source_id: string
  name: string
  institution: string
  last_success_at?: string | null
}

export interface AnalyticsSummary {
  territory: string
  scope: 'national' | 'department' | 'municipality'
  disease: string
  latest?: AnalyticsSeriesPoint | null
  previous?: AnalyticsSeriesPoint | null
  absolute_change?: number | null
  percent_change?: number | null
  data_status: 'no_data' | 'fresh' | 'stale'
  observation_age_days?: number | null
  sources: ProvenanceSource[]
  population_denominator?: Record<string, unknown>
  windows: Array<{
    weeks: 4 | 12
    from_week: string
    to_week: string
    observed_cases: number
    observed_week_count: number
    missing_week_count: number
    previous_observed_cases?: number | null
    percent_change_vs_previous?: number | null
    incidence_per_100k?: number | null
  }>
}

export interface CurrentOfficialReference {
  requested_territory: string
  reference_territory_code: string
  reference_territory_name: string
  reference_territory_level: 'national' | 'department' | 'district'
  geographic_context_only: boolean
  disease: string
  event_label: string
  epidemiological_year: number
  epidemiological_week: number
  period_start: string
  period_end: string
  cumulative_cases: number
  expected_cases?: number | null
  observed_cases?: number | null
  comparison_basis: string
  is_preliminary: boolean
  data_status: 'current' | 'stale'
  age_days: number
  source_name: string
  source_document_url: string
  source_page: number
  limitations: string[]
}

export interface AnalyticsSeries {
  territory: string
  scope: 'national' | 'department' | 'municipality'
  disease: string
  points: AnalyticsSeriesPoint[]
  metadata: Record<string, unknown>
}

export interface AnalyticsForecastPoint {
  target_week: string
  predicted_cases: number
  lower_bound: number
  upper_bound: number
  max_outbreak_probability: number
  component_predictions: Record<string, number>
  municipalities: number
  model_version: string
}

export interface AnalyticsForecastSeries {
  territory: string
  scope: 'national' | 'department' | 'municipality'
  disease: string
  horizon: number
  points: AnalyticsForecastPoint[]
  metadata: Record<string, unknown>
}

export interface HistoricalTerritory {
  cod_dane: string
  municipality: string
  department_code: string
  department: string
  population?: number | null
  latitude?: number | null
  longitude?: number | null
  first_week: string
  latest_week: string
  observation_rows: number
  total_observed_cases: number
  latest_observed_cases: number
  latest_is_preliminary: boolean
  latest_quality_score: number
}

export interface HistoricalTerritoryCollection {
  disease: string
  total: number
  items: HistoricalTerritory[]
  metadata: Record<string, unknown>
}

export interface ApiAlertEvent {
  id: string
  forecast_id: string
  cod_dane: string
  municipality: string
  department: string
  disease: string
  horizon: number
  risk_score: number
  risk_level: string
  predicted_cases: number
  lower_bound: number
  upper_bound: number
  drivers: Record<string, unknown>[]
  status: string
  created_at: string
  issued_at: string
  target_week: string
  operationally_eligible: boolean
  reviewed_at?: string | null
  reviewed_by?: string | null
  review_notes?: string | null
}

export interface ApiNotificationDelivery {
  id: string
  alert_event_id: string
  alert_rule_id?: string | null
  rule_name: string
  disease: string
  municipality_code: string
  channel: AlertChannel
  status: 'pending' | 'delivered' | 'unsupported' | 'failed'
  provider?: string | null
  provider_message_id?: string | null
  failure_reason?: string | null
  title: string
  message: string
  payload: Record<string, unknown>
  delivered_at?: string | null
  read_at?: string | null
  created_at: string
  updated_at: string
}

export interface ApiSubscription {
  id: string
  user_id: string
  topic: 'critical_alerts' | 'territory_watch' | 'epidemiological_summary' | 'model_drift'
  target: string
  frequency: 'immediate' | 'daily' | 'weekly'
  channels: ('email' | 'push' | 'in_app' | 'webhook')[]
  enabled: boolean
  created_at: string
  updated_at: string
}

export type AlertChannel = 'email' | 'push' | 'in_app' | 'webhook'

export interface ApiAlertRule {
  id: string
  user_id: string
  name: string
  disease: string
  territories: string[]
  risk_threshold: number
  horizon_weeks: number
  channels: AlertChannel[]
  enabled: boolean
  notes?: string | null
  created_at: string
  updated_at: string
}

export type AlertRuleInput = Omit<ApiAlertRule, 'id' | 'user_id' | 'created_at' | 'updated_at'>

function getStoredValue(key: string) {
  return sessionStorage.getItem(key) ?? localStorage.getItem(key)
}

function getAccessToken() { return getStoredValue(ACCESS_TOKEN_KEY) }
function getRefreshToken() { return getStoredValue(REFRESH_TOKEN_KEY) }

function decodeAccessToken(): Partial<ApiUser> | null {
  const token = getAccessToken()
  const payload = token?.split('.')[1]
  if (!payload) return null
  try {
    const normalized = payload.replace(/-/g, '+').replace(/_/g, '/')
    const padded = normalized.padEnd(Math.ceil(normalized.length / 4) * 4, '=')
    const claims = JSON.parse(window.atob(padded)) as unknown
    return claims && typeof claims === 'object' ? claims as Partial<ApiUser> : null
  } catch {
    return null
  }
}

function storedProfileIdentity(): Partial<ApiUser> | null {
  const raw = getStoredValue(PROFILE_KEY)
  if (!raw) return null
  try {
    const profile = JSON.parse(raw) as unknown
    return profile && typeof profile === 'object' ? profile as Partial<ApiUser> : null
  } catch {
    return null
  }
}

function sessionRole() {
  return decodeAccessToken()?.role ?? storedProfileIdentity()?.role ?? null
}

function clearFromBoth(key: string) {
  localStorage.removeItem(key)
  sessionStorage.removeItem(key)
}

function hasPersistentSession() {
  return Boolean(localStorage.getItem(ACCESS_TOKEN_KEY) || localStorage.getItem(REFRESH_TOKEN_KEY))
}

export const apiSession = {
  save(tokens: TokenPair, persistent = hasPersistentSession()) {
    const target = persistent ? localStorage : sessionStorage
    const other = persistent ? sessionStorage : localStorage
    other.removeItem(ACCESS_TOKEN_KEY)
    other.removeItem(REFRESH_TOKEN_KEY)
    target.setItem(ACCESS_TOKEN_KEY, tokens.access_token)
    if (tokens.refresh_token) target.setItem(REFRESH_TOKEN_KEY, tokens.refresh_token)
    else target.removeItem(REFRESH_TOKEN_KEY)
  },
  clear() {
    clearFromBoth(ACCESS_TOKEN_KEY)
    clearFromBoth(REFRESH_TOKEN_KEY)
    clearFromBoth(PROFILE_KEY)
    window.dispatchEvent(new CustomEvent('prora-profile-updated', { detail: null }))
  },
  isAuthenticated() { return Boolean(getAccessToken()) },
  isRegistered() {
    if (!getAccessToken()) return false
    const claims = decodeAccessToken()
    if (claims?.is_registered === false || claims?.role === 'guest') return false
    const role = claims?.role ?? storedProfileIdentity()?.role
    return Boolean(role && role !== 'guest')
  },
  isGuest() { return Boolean(getAccessToken()) && sessionRole() === 'guest' },
  role() { return getAccessToken() ? sessionRole() : null },
  isPersistent() { return hasPersistentSession() },
  accessToken() { return getAccessToken() },
}

export const apiProfile = {
  load<T>() {
    const raw = sessionStorage.getItem(PROFILE_KEY) ?? localStorage.getItem(PROFILE_KEY)
    if (!raw) return null
    try { return JSON.parse(raw) as T } catch { return null }
  },
  save(profile: Record<string, unknown>, persistent = hasPersistentSession()) {
    clearFromBoth(PROFILE_KEY)
    ;(persistent ? localStorage : sessionStorage).setItem(PROFILE_KEY, JSON.stringify(profile))
  },
  clear() { clearFromBoth(PROFILE_KEY) },
}

async function parseResponse(response: Response) {
  const contentType = response.headers.get('content-type') ?? ''
  if (response.status === 204) return null
  if (contentType.includes('application/json')) return response.json()
  return response.text()
}

const API_TIMEOUT_MS = 10_000
const RETRYABLE_STATUS = new Set([502, 503, 504])

function readableApiError(payload: unknown, status: number) {
  if (!payload || typeof payload !== 'object') return `La API respondió con estado ${status}.`
  const record = payload as Record<string, unknown>
  const envelope = record.error && typeof record.error === 'object' ? record.error as Record<string, unknown> : null
  const direct = envelope?.message ?? record.message
  if (typeof direct === 'string' && direct.trim()) return direct
  if (typeof record.detail === 'string' && record.detail.trim()) return record.detail
  if (Array.isArray(record.detail)) {
    const messages = record.detail
      .map((item) => item && typeof item === 'object' ? (item as Record<string, unknown>).msg : null)
      .filter((message): message is string => typeof message === 'string')
    if (messages.length) return messages.join(' ')
  }
  return `La API respondió con estado ${status}.`
}

function wait(milliseconds: number) {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds))
}

async function fetchWithTimeout(url: string, init: RequestInit, timeoutMs = API_TIMEOUT_MS) {
  const controller = new AbortController()
  const timer = window.setTimeout(() => controller.abort(), timeoutMs)
  try {
    return await fetch(url, { ...init, signal: init.signal ?? controller.signal })
  } finally {
    window.clearTimeout(timer)
  }
}

async function refreshSession() {
  const refreshToken = getRefreshToken()
  if (!refreshToken) return false
  const persistent = apiSession.isPersistent()
  try {
    const response = await fetchWithTimeout(`${API_BASE_URL}/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: refreshToken }),
    })
    if (!response.ok) return false
    const tokens = await response.json() as TokenPair
    apiSession.save(tokens, persistent)
    return true
  } catch {
    return false
  }
}

async function request<T>(path: string, init: RequestInit = {}, retryAuth = true, transientAttempt = 0): Promise<T> {
  const headers = new Headers(init.headers)
  if (!headers.has('Accept')) headers.set('Accept', 'application/json')
  if (init.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  const accessToken = getAccessToken()
  if (accessToken) headers.set('Authorization', `Bearer ${accessToken}`)

  let response: Response
  try {
    response = await fetchWithTimeout(`${API_BASE_URL}${path}`, { ...init, headers })
  } catch (error) {
    const canRetry = (!init.method || init.method === 'GET') && transientAttempt === 0
    if (canRetry) {
      await wait(450)
      return request<T>(path, init, retryAuth, 1)
    }
    const timedOut = error instanceof DOMException && error.name === 'AbortError'
    throw new ApiError(
      timedOut
        ? 'La API no respondió en dos intentos de 10 segundos. Revisa que el backend esté iniciado y vuelve a intentar.'
        : 'No fue posible conectar con la API de PRORA después de dos intentos.',
      0,
      error,
    )
  }

  if (response.status === 401 && retryAuth && await refreshSession()) return request<T>(path, init, false, transientAttempt)

  if (RETRYABLE_STATUS.has(response.status) && (!init.method || init.method === 'GET') && transientAttempt === 0) {
    await wait(450)
    return request<T>(path, init, retryAuth, 1)
  }

  const payload = await parseResponse(response)
  if (!response.ok) {
    const message = readableApiError(payload, response.status)
    if (response.status === 401) apiSession.clear()
    throw new ApiError(message, response.status, payload)
  }
  return payload as T
}

export const proraApi = {
  health: () => request<{ status: string; version?: string }>('/health'),
  auth: {
    login: (email: string, password: string) => request<TokenPair>('/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) }),
    register: (payload: { email: string; password: string; full_name: string }) => request<TokenPair>('/auth/register', { method: 'POST', body: JSON.stringify(payload) }),
    guest: () => request<TokenPair>('/auth/guest', { method: 'POST' }),
    me: () => request<ApiUser>('/auth/me'),
    logout: async () => {
      const refreshToken = getRefreshToken()
      try {
        if (refreshToken) await request<{ message: string }>('/auth/logout', { method: 'POST', body: JSON.stringify({ refresh_token: refreshToken }) }, false)
      } finally {
        apiSession.clear()
      }
    },
  },
  preferences: {
    get: () => request<ApiPreferences>('/preferences'),
    update: (payload: Partial<ApiPreferences>) => request<ApiPreferences>('/preferences', { method: 'PATCH', body: JSON.stringify(payload) }),
  },
  risks: {
    map: (disease: string, horizon: number) => request<RiskMapItem[]>(`/risk/map?disease=${encodeURIComponent(disease)}&horizon=${horizon}`),
    municipality: (codDane: string, disease: string, horizon: number) => request<RiskMapItem>(`/risk/municipalities/${encodeURIComponent(codDane)}?disease=${encodeURIComponent(disease)}&horizon=${horizon}`),
    history: (codDane: string, disease: string, from?: string, to?: string) => {
      const params = new URLSearchParams({ disease })
      if (from) params.set('from', from)
      if (to) params.set('to', to)
      return request<HistoricalPoint[]>(`/risk/municipalities/${encodeURIComponent(codDane)}/history?${params}`)
    },
    explanation: (codDane: string, disease: string, horizon: number) => request<RiskExplanation>(`/risk/municipalities/${encodeURIComponent(codDane)}/explanation?disease=${encodeURIComponent(disease)}&horizon=${horizon}`),
  },
  models: {
    metadata: (disease: string, horizon = 4) => request<ModelMetadata>(`/models/${encodeURIComponent(disease)}?horizon=${horizon}`),
    versions: (disease: string, horizon = 4) => request<ModelVersion[]>(`/models/${encodeURIComponent(disease)}/versions?horizon=${horizon}`),
    trace: (disease: string, horizon: number, version: string) => request<ModelTrace>(`/models/${encodeURIComponent(disease)}/${horizon}/versions/${encodeURIComponent(version)}/trace`),
    readiness: () => request<ModelPortfolioReadiness>('/models/readiness/portfolio'),
    train: (disease: string) => request<{ job_id: string; status: string }>('/models/train', { method: 'POST', body: JSON.stringify({ disease }) }),
  },
  analytics: {
    summary: (disease: string, territory = 'national') => request<AnalyticsSummary>(`/analytics/summary?disease=${encodeURIComponent(disease)}&territory=${encodeURIComponent(territory)}`),
    currentReference: (disease: string, territory = 'national') => request<CurrentOfficialReference>(`/analytics/current-reference?disease=${encodeURIComponent(disease)}&territory=${encodeURIComponent(territory)}`),
    historicalTerritories: (disease: string) => request<HistoricalTerritoryCollection>(`/analytics/historical-territories?disease=${encodeURIComponent(disease)}`),
    series: (disease: string, territory = 'national', from?: string, to?: string) => {
      const params = new URLSearchParams({ disease, territory })
      if (from) params.set('from', from)
      if (to) params.set('to', to)
      return request<AnalyticsSeries>(`/analytics/series?${params}`)
    },
    forecastSeries: (disease: string, territory = 'national', horizon = 4) => request<AnalyticsForecastSeries>(`/analytics/forecast-series?disease=${encodeURIComponent(disease)}&territory=${encodeURIComponent(territory)}&horizon=${horizon}`),
  },
  alerts: {
    list: (filters?: { disease?: string; status?: string; limit?: number }) => {
      const params = new URLSearchParams()
      if (filters?.disease) params.set('disease', filters.disease)
      if (filters?.status) params.set('status', filters.status)
      if (filters?.limit) params.set('limit', String(filters.limit))
      const query = params.toString()
      return request<ApiAlertEvent[]>(`/risk/alerts${query ? `?${query}` : ''}`)
    },
    review: (alertId: string, payload: Record<string, unknown>) => request<ApiAlertEvent>(`/risk/alerts/${encodeURIComponent(alertId)}/review`, { method: 'POST', body: JSON.stringify(payload) }),
  },
  notifications: {
    list: (filters?: { channel?: AlertChannel; status?: ApiNotificationDelivery['status']; unreadOnly?: boolean; offset?: number; limit?: number }) => {
      const params = new URLSearchParams()
      if (filters?.channel) params.set('channel', filters.channel)
      if (filters?.status) params.set('status', filters.status)
      if (filters?.unreadOnly != null) params.set('unread_only', String(filters.unreadOnly))
      if (filters?.offset != null) params.set('offset', String(filters.offset))
      if (filters?.limit != null) params.set('limit', String(filters.limit))
      const query = params.toString()
      return request<ApiNotificationDelivery[]>(`/notifications${query ? `?${query}` : ''}`)
    },
    markRead: (notificationId: string) => request<ApiNotificationDelivery>(`/notifications/${encodeURIComponent(notificationId)}/read`, { method: 'PATCH' }),
  },
  alertRules: {
    list: (filters?: { disease?: string; enabled?: boolean }) => {
      const params = new URLSearchParams()
      if (filters?.disease) params.set('disease', filters.disease)
      if (filters?.enabled != null) params.set('enabled', String(filters.enabled))
      const query = params.toString()
      return request<ApiAlertRule[]>(`/alerts${query ? `?${query}` : ''}`)
    },
    create: (payload: AlertRuleInput) => request<ApiAlertRule>('/alerts', { method: 'POST', body: JSON.stringify(payload) }),
    update: (ruleId: string, payload: Partial<AlertRuleInput>) => request<ApiAlertRule>(`/alerts/${encodeURIComponent(ruleId)}`, { method: 'PATCH', body: JSON.stringify(payload) }),
    remove: (ruleId: string) => request<void>(`/alerts/${encodeURIComponent(ruleId)}`, { method: 'DELETE' }),
  },
  subscriptions: {
    list: () => request<ApiSubscription[]>('/subscriptions'),
    create: (payload: Record<string, unknown>) => request<ApiSubscription>('/subscriptions', { method: 'POST', body: JSON.stringify(payload) }),
    update: (subscriptionId: string, payload: Record<string, unknown>) => request<ApiSubscription>(`/subscriptions/${encodeURIComponent(subscriptionId)}`, { method: 'PATCH', body: JSON.stringify(payload) }),
    remove: (subscriptionId: string) => request<void>(`/subscriptions/${encodeURIComponent(subscriptionId)}`, { method: 'DELETE' }),
  },
  agent: {
    query: (question: string, context?: Record<string, unknown>, conversationId?: string) => request<AgentAnswer>('/agent/query', { method: 'POST', body: JSON.stringify({ question, context, conversation_id: conversationId }) }),
  },
  sources: {
    list: () => request<DataSourceRecord[]>('/sources'),
    runs: (limit = 100) => request<IngestionRunRecord[]>(`/sources/runs?limit=${limit}`),
    inventory: () => request<StoredDatasetInventory[]>('/sources/inventory'),
    manifest: (runId: string) => request<SnapshotManifest>(`/sources/runs/${encodeURIComponent(runId)}/manifest`),
    sync: (sourceId: string, payload: { mode: 'incremental' | 'backfill'; from_date?: string; to_date?: string; max_records?: number; event_codes?: number[] } = { mode: 'incremental' }) => request<IngestionRunRecord>(`/sources/${encodeURIComponent(sourceId)}/sync`, { method: 'POST', body: JSON.stringify(payload) }),
  },
}
