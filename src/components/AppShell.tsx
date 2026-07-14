import {
  Bell,
  BookOpenText,
  ChevronDown,
  CircleHelp,
  CodeXml,
  Database,
  House,
  LayoutDashboard,
  LogOut,
  Menu,
  Moon,
  Search,
  Settings,
  ShieldAlert,
  Sun,
  X,
} from 'lucide-react'
import { ReactNode, useCallback, useEffect, useRef, useState } from 'react'
import { BrandMark } from './Brand'
import { apiProfile, apiSession, proraApi, type HistoricalTerritory } from '../lib/api'

export type AppView = 'overview' | 'data' | 'api' | 'alerts' | 'methodology' | 'settings' | 'help'

interface AppShellProps {
  view: AppView
  onChangeView: (view: AppView) => void
  onPublicHome: () => void
  theme: 'light' | 'dark'
  onToggleTheme: () => void
  children: ReactNode
}

const mainNavigation = [
  { id: 'overview' as const, label: 'Panorama nacional', icon: LayoutDashboard },
  { id: 'alerts' as const, label: 'Centro de alertas', icon: ShieldAlert },
  { id: 'data' as const, label: 'Fuentes y datos', icon: Database },
  { id: 'api' as const, label: 'API e integraciones', icon: CodeXml },
  { id: 'methodology' as const, label: 'Modelo y método', icon: BookOpenText },
]

type SearchResult = { label: string; meta: string; view: AppView; selection?: { territory?: string; disease?: string } }
type ShellNotification = {
  id: string
  title: string
  detail: string
  date: string
  riskLevel: string
  unread: boolean
  kind: 'delivery' | 'public-alert'
}

const searchCatalog: SearchResult[] = [
  { label: 'Panorama nacional', meta: 'Indicadores, mapa y análisis territorial', view: 'overview' },
  { label: 'Dengue', meta: 'Enfermedad priorizada', view: 'overview', selection: { disease: 'dengue' } },
  { label: 'Malaria', meta: 'Enfermedad priorizada', view: 'overview', selection: { disease: 'malaria' } },
  { label: 'Chikunguña', meta: 'Enfermedad priorizada', view: 'overview', selection: { disease: 'chikunguna' } },
  { label: 'Zika', meta: 'Enfermedad priorizada', view: 'overview', selection: { disease: 'zika' } },
  { label: 'Leishmaniasis', meta: 'Enfermedad priorizada', view: 'overview', selection: { disease: 'leishmaniasis' } },
  { label: 'IRA', meta: 'Infección respiratoria aguda', view: 'overview', selection: { disease: 'ira' } },
  { label: 'Centro de alertas', meta: 'Monitoreo y suscripciones', view: 'alerts' },
  { label: 'Fuentes de datos', meta: 'SIVIGILA, PAI, IDEAM y DANE', view: 'data' },
  { label: 'API e integraciones', meta: 'Endpoints y documentación', view: 'api' },
  { label: 'Modelo y metodología', meta: 'Validación, variables y trazabilidad', view: 'methodology' },
  { label: 'Configuración', meta: 'Perfil, seguridad y preferencias', view: 'settings' },
  { label: 'Centro de ayuda', meta: 'Guías y soporte', view: 'help' },
]

const prioritizedDiseases = ['dengue', 'malaria', 'chikunguna', 'zika', 'leishmaniasis', 'ira']
const normalizeSearch = (value: string) => value.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().trim()
const alertStatusLabels: Record<string, string> = {
  open: 'Activa', active: 'Activa', acknowledged: 'Revisada', archived: 'Histórica', closed: 'Cerrada', false_positive: 'Descartada',
}
const riskDotClass = (risk: string) => risk === 'critico' ? 'critical' : risk === 'alto' ? 'high' : risk === 'moderado' ? 'medium' : 'low'

interface StoredProfile { name?: string; email?: string; institution?: string; role?: string }

function readStoredProfile(): StoredProfile | null {
  return apiProfile.load<StoredProfile>()
}

export default function AppShell({ view, onChangeView, onPublicHome, theme, onToggleTheme, children }: AppShellProps) {
  const [mobileNav, setMobileNav] = useState(false)
  const [notifications, setNotifications] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [searchOpen, setSearchOpen] = useState(false)
  const [profile, setProfile] = useState<StoredProfile | null>(readStoredProfile)
  const [backendState, setBackendState] = useState<'loading' | 'live' | 'offline'>('loading')
  const [backendVersion, setBackendVersion] = useState('')
  const [territoryCatalog, setTerritoryCatalog] = useState<HistoricalTerritory[]>([])
  const [territorySearchState, setTerritorySearchState] = useState<'idle' | 'loading' | 'ready' | 'error'>('idle')
  const [notificationItems, setNotificationItems] = useState<ShellNotification[]>([])
  const [notificationState, setNotificationState] = useState<'idle' | 'loading' | 'live' | 'empty' | 'error'>('idle')
  const searchInputRef = useRef<HTMLInputElement>(null)
  const displayName = profile?.name || profile?.email?.split('@')[0] || 'Invitado'
  const displayRole = profile?.role || 'Acceso público'
  const initials = displayName.split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]?.toUpperCase()).join('') || 'PR'
  const shortName = displayName.split(/\s+/).filter(Boolean).slice(0, 2).join(' ')
  const registeredAccount = apiSession.isRegistered()
  const unreadNotifications = notificationItems.filter((item) => item.unread).length

  const checkBackend = useCallback(() => {
    setBackendState('loading')
    proraApi.health()
      .then((health) => {
        setBackendState('live')
        setBackendVersion(health.version ?? '')
        setTerritorySearchState((current) => current === 'error' ? 'idle' : current)
      })
      .catch(() => {
        setBackendState('offline')
        setBackendVersion('')
      })
  }, [])

  const loadNotifications = useCallback(() => {
    setNotificationState('loading')
    const request = registeredAccount
      ? proraApi.notifications.list({ channel: 'in_app', limit: 6 }).then((items): ShellNotification[] => items.map((item) => {
          const signal = item.payload.signal && typeof item.payload.signal === 'object' ? item.payload.signal as Record<string, unknown> : {}
          const municipality = typeof signal.municipality === 'string' ? signal.municipality : item.municipality_code
          const department = typeof signal.department === 'string' ? signal.department : ''
          const level = typeof signal.risk_level === 'string' ? signal.risk_level : 'moderado'
          return {
            id: item.id,
            title: item.title,
            detail: `${municipality}${department ? ` · ${department}` : ''} · ${level}`,
            date: item.delivered_at ?? item.created_at,
            riskLevel: level,
            unread: !item.read_at,
            kind: 'delivery',
          }
        }))
      : proraApi.alerts.list({ limit: 6 }).then((items): ShellNotification[] => items.map((item) => ({
          id: item.id,
          title: `${item.disease === 'ira' ? 'IRA' : item.disease.charAt(0).toUpperCase() + item.disease.slice(1)} · ${item.municipality}`,
          detail: `${item.risk_level} · ${alertStatusLabels[item.status] ?? item.status}${item.operationally_eligible ? ' · Operativa' : ' · Retrospectiva'}`,
          date: item.issued_at,
          riskLevel: item.risk_level,
          unread: false,
          kind: 'public-alert',
        })))
    request.then((items) => {
      setNotificationItems(items)
      setNotificationState(items.length ? 'live' : 'empty')
    })
      .catch(() => {
        setNotificationItems([])
        setNotificationState('error')
      })
  }, [registeredAccount])

  const markNotificationRead = (notification: ShellNotification) => {
    if (notification.kind !== 'delivery' || !notification.unread) return
    void proraApi.notifications.markRead(notification.id)
      .then(() => setNotificationItems((current) => current.map((item) => item.id === notification.id ? { ...item, unread: false } : item)))
      .catch(() => setNotificationState('error'))
  }

  const navigate = (nextView: AppView) => {
    onChangeView(nextView)
    setMobileNav(false)
  }

  useEffect(() => {
    const focusSearch = (event: globalThis.KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        searchInputRef.current?.focus()
        setSearchOpen(true)
      }
    }
    window.addEventListener('keydown', focusSearch)
    return () => window.removeEventListener('keydown', focusSearch)
  }, [])

  useEffect(() => {
    if (!searchOpen || searchQuery.trim().length < 2 || territorySearchState !== 'idle') return
    setTerritorySearchState('loading')
    Promise.allSettled(prioritizedDiseases.map((disease) => proraApi.analytics.historicalTerritories(disease)))
      .then((results) => {
        const byCode = new Map<string, HistoricalTerritory>()
        results.forEach((result) => {
          if (result.status === 'fulfilled') result.value.items.forEach((item) => byCode.set(item.cod_dane, item))
        })
        setTerritoryCatalog([...byCode.values()])
        setTerritorySearchState(byCode.size ? 'ready' : 'error')
      })
  }, [searchOpen, searchQuery, territorySearchState])

  useEffect(() => {
    checkBackend()
    window.addEventListener('online', checkBackend)
    return () => window.removeEventListener('online', checkBackend)
  }, [checkBackend])

  useEffect(() => {
    const updateProfile = (event: Event) => setProfile((event as CustomEvent<StoredProfile>).detail ?? readStoredProfile())
    window.addEventListener('prora-profile-updated', updateProfile)
    return () => window.removeEventListener('prora-profile-updated', updateProfile)
  }, [])

  const normalizedQuery = normalizeSearch(searchQuery)
  const staticResults = searchCatalog.filter((item) => normalizeSearch(`${item.label} ${item.meta}`).includes(normalizedQuery))
  const territoryResults: SearchResult[] = normalizedQuery.length < 2 ? [] : territoryCatalog
    .filter((item) => normalizeSearch(`${item.municipality} ${item.department} ${item.cod_dane}`).includes(normalizedQuery))
    .slice(0, 6)
    .map((item) => ({
      label: item.municipality,
      meta: `${item.department} · DIVIPOLA ${item.cod_dane}`,
      view: 'overview',
      selection: { territory: item.cod_dane },
    }))
  const visibleSearchResults = [...territoryResults, ...staticResults].slice(0, 8)

  const selectSearchResult = (result: SearchResult) => {
    if (result.selection) {
      sessionStorage.setItem('prora-global-selection', JSON.stringify(result.selection))
      window.dispatchEvent(new CustomEvent('prora-global-selection', { detail: result.selection }))
    }
    navigate(result.view)
    setSearchQuery('')
    setSearchOpen(false)
  }

  const signOut = async () => {
    try { await proraApi.auth.logout() } catch { apiSession.clear() }
    apiProfile.clear()
    setProfile(null)
    onPublicHome()
  }

  return (
    <div className="app-frame">
      <aside className={mobileNav ? 'app-sidebar is-open' : 'app-sidebar'}>
        <div className="sidebar-brand-row">
          <BrandMark />
          <button className="icon-button sidebar-close" onClick={() => setMobileNav(false)} aria-label="Cerrar navegación"><X size={19}/></button>
        </div>
        <nav className="sidebar-nav" aria-label="Navegación del tablero">
          <span className="nav-group-label">Inteligencia territorial</span>
          {mainNavigation.map(({ id, label, icon: Icon }) => (
            <button key={id} className={view === id ? 'is-active' : ''} onClick={() => navigate(id)}>
              <Icon size={19} strokeWidth={1.9}/><span>{label}</span>
            </button>
          ))}
          <span className="nav-group-label nav-group-label--space">General</span>
          <button className={view === 'settings' ? 'is-active' : ''} onClick={() => navigate('settings')}><Settings size={19}/><span>Configuración</span></button>
          <button className={view === 'help' ? 'is-active' : ''} onClick={() => navigate('help')}><CircleHelp size={19}/><span>Centro de ayuda</span></button>
          <button onClick={onPublicHome}><House size={19}/><span>Sitio público</span></button>
        </nav>
        <div className="sidebar-status" data-state={backendState}>
          <div className="sidebar-status__orb"><span/><span/><span/></div>
          <span><strong>{backendState === 'loading' ? 'Verificando trazabilidad' : backendState === 'live' ? 'Datos con corte visible' : 'Sin consulta en vivo'}</strong><small>{backendState === 'live' ? `${backendVersion ? `API ${backendVersion} · ` : ''}revisa fecha y cobertura` : backendState === 'loading' ? 'Consultando fuentes' : 'Revisa conexión y antigüedad'}</small></span>
          <i />
        </div>
        <div className="sidebar-user">
          <div className="avatar">{initials}</div>
          <span><strong>{displayName}</strong><small>{displayRole}</small></span>
          <button aria-label="Cerrar sesión" onClick={() => void signOut()}><LogOut size={17}/></button>
        </div>
      </aside>

      {mobileNav && <button className="sidebar-overlay" aria-label="Cerrar navegación" onClick={() => setMobileNav(false)} />}

      <div className="app-workspace">
        <header className="topbar">
          <button className="icon-button topbar-menu" onClick={() => setMobileNav(true)} aria-label="Abrir navegación"><Menu size={21}/></button>
          <div className="global-search-wrap">
            <div className={searchOpen ? 'global-search is-open' : 'global-search'}>
              <Search size={18}/>
              <input ref={searchInputRef} value={searchQuery} onChange={(event) => { setSearchQuery(event.target.value); setSearchOpen(true) }} onFocus={() => setSearchOpen(true)} onBlur={() => window.setTimeout(() => setSearchOpen(false), 140)} onKeyDown={(event) => { if (event.key === 'Enter' && visibleSearchResults[0]) selectSearchResult(visibleSearchResults[0]); if (event.key === 'Escape') setSearchOpen(false) }} aria-label="Buscar municipio, departamento o indicador" aria-expanded={searchOpen} aria-controls="global-search-results" placeholder="Buscar territorio, enfermedad o sección…" />
              <kbd>Ctrl K</kbd>
            </div>
            {searchOpen && (
              <div id="global-search-results" className="global-search-results" role="listbox" aria-label="Resultados de búsqueda">
                <span className="global-search-results__label">Resultados de PRORA</span>
                {visibleSearchResults.length > 0 ? visibleSearchResults.map((result) => <button type="button" role="option" aria-selected="false" key={`${result.view}-${result.label}-${result.selection?.territory ?? result.selection?.disease ?? ''}`} onMouseDown={(event) => event.preventDefault()} onClick={() => selectSearchResult(result)}><Search size={15}/><span><strong>{result.label}</strong><small>{result.meta}</small></span><em>Ir</em></button>) : territorySearchState === 'loading' ? <p>Consultando el catálogo territorial de la API…</p> : <p>No encontramos coincidencias. Prueba con una enfermedad, sección, municipio o código DANE.</p>}
              </div>
            )}
          </div>
          <div className="topbar-actions">
            <button className="environment-pill" data-state={backendState} type="button" onClick={checkBackend} disabled={backendState === 'loading'} aria-label={backendState === 'offline' ? 'API no disponible. Pulsar para reconectar' : 'Comprobar conexión con la API'} title="Comprobar conexión"><i/> {backendState === 'live' ? 'API disponible' : backendState === 'loading' ? 'Verificando API' : 'Reconectar API'}</button>
            <button className="icon-button theme-toggle" onClick={onToggleTheme} aria-label={theme === 'dark' ? 'Activar modo claro' : 'Activar modo oscuro'}>{theme === 'dark' ? <Sun size={18}/> : <Moon size={18}/>}</button>
            <div className="notification-wrap">
              <button className="icon-button notification-trigger" onClick={() => setNotifications((value) => { const next = !value; if (next) loadNotifications(); return next })} aria-label={`Notificaciones${unreadNotifications ? `: ${unreadNotifications} sin leer` : ''}`} aria-expanded={notifications}><Bell size={19}/>{unreadNotifications > 0 && <span>{Math.min(unreadNotifications, 9)}</span>}</button>
              {notifications && (
                <div className="notification-popover">
                  <div><strong>{registeredAccount ? 'Mis notificaciones' : 'Señales publicadas'}</strong><button onClick={() => { setNotifications(false); navigate('alerts') }}>Abrir centro</button></div>
                  {notificationState === 'loading' && <article className="notification-message"><span className="status-dot status-dot--online"/><p><strong>Consultando alertas</strong><small>Recuperando estados desde la API…</small></p></article>}
                  {notificationState === 'error' && <article className="notification-message"><span className="risk-dot risk-dot--medium"/><p><strong>No fue posible consultar alertas</strong><small>La bandeja no inventa notificaciones locales.</small></p><button type="button" onClick={loadNotifications}>Reintentar</button></article>}
                  {notificationState === 'empty' && <article className="notification-message"><span className="risk-dot risk-dot--low"/><p><strong>Sin alertas publicadas</strong><small>La API respondió correctamente y no devolvió registros.</small></p></article>}
                  {notificationState === 'live' && notificationItems.map((item) => <article key={item.id} className={item.unread ? 'is-unread' : ''}>
                    <span className={`risk-dot risk-dot--${riskDotClass(item.riskLevel)}`}/>
                    <p><strong>{item.title}</strong><small>{item.detail}</small>{item.kind === 'delivery' && item.unread && <button type="button" onClick={() => markNotificationRead(item)}>Marcar leída</button>}</p>
                    <time dateTime={item.date}>{new Intl.DateTimeFormat('es-CO', { day: '2-digit', month: 'short' }).format(new Date(item.date))}</time>
                  </article>)}
                </div>
              )}
            </div>
            <button className="topbar-profile" onClick={() => navigate('settings')}><span className="avatar">{initials}</span><span><strong>{shortName}</strong><small>{profile ? 'Perfil guardado' : 'Modo invitado'}</small></span><ChevronDown size={16}/></button>
          </div>
        </header>
        <main className="app-content">{children}</main>
      </div>
    </div>
  )
}
