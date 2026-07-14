import { CheckCircle2, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import AlertsCenter from './components/AlertsCenter'
import ApiExplorer from './components/ApiExplorer'
import AppShell, { type AppView } from './components/AppShell'
import AuthModal from './components/AuthModal'
import Dashboard from './components/Dashboard'
import DataHub from './components/DataHub'
import Methodology from './components/Methodology'
import PublicLanding from './components/PublicLanding'
import SettingsView from './components/SettingsView'
import HelpCenter from './components/HelpCenter'
import ProraAgent from './components/ProraAgent'

type PublicSection = 'inicio' | 'capacidades' | 'datos' | 'metodologia'
type RouteState = { surface: 'public'; section: PublicSection } | { surface: 'app'; view: AppView }

const viewHashes: Record<AppView, string> = {
  overview: '#/panorama',
  alerts: '#/alertas',
  data: '#/fuentes',
  api: '#/api',
  methodology: '#/metodologia',
  settings: '#/configuracion',
  help: '#/ayuda',
}

function parseRoute(hash = window.location.hash): RouteState {
  const normalized = hash.toLowerCase().replace(/^#/, '')
  const appEntry = (Object.entries(viewHashes) as [AppView, string][])
    .find(([, value]) => value.slice(1) === normalized)
  if (appEntry) return { surface: 'app', view: appEntry[0] }

  const publicMatch = normalized.match(/^\/inicio(?:\/(capacidades|datos|metodologia))?$/)
  if (publicMatch) return { surface: 'public', section: (publicMatch[1] as PublicSection | undefined) ?? 'inicio' }

  // Compatibilidad con enlaces compartidos por las primeras versiones de PRORA.
  if (normalized === 'datos') return { surface: 'app', view: 'data' }
  if (normalized === 'metodologia') return { surface: 'app', view: 'methodology' }
  if (normalized === 'capacidades') return { surface: 'public', section: 'capacidades' }
  return { surface: 'public', section: 'inicio' }
}

function routeHash(route: RouteState) {
  if (route.surface === 'app') return viewHashes[route.view]
  return route.section === 'inicio' ? '#/inicio' : `#/inicio/${route.section}`
}

const viewContext: Record<AppView, string> = {
  overview: 'el panorama nacional',
  data: 'las fuentes y la calidad de datos',
  api: 'la API y las integraciones',
  alerts: 'el centro de alertas',
  methodology: 'el modelo y la metodología',
  settings: 'la configuración de tu cuenta',
  help: 'el centro de ayuda',
}

export default function App() {
  const initialRoute = parseRoute()
  const [surface, setSurface] = useState<'public' | 'app'>(initialRoute.surface)
  const [view, setView] = useState<AppView>(initialRoute.surface === 'app' ? initialRoute.view : 'overview')
  const [publicSection, setPublicSection] = useState<PublicSection>(initialRoute.surface === 'public' ? initialRoute.section : 'inicio')
  const [authMode, setAuthMode] = useState<'login' | 'register' | null>(null)
  const [toast, setToast] = useState<string | null>(null)
  const [theme, setTheme] = useState<'light' | 'dark'>(() => {
    const stored = localStorage.getItem('prora-theme')
    if (stored === 'light' || stored === 'dark') return stored
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
  })

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    localStorage.setItem('prora-theme', theme)
  }, [theme])

  useEffect(() => {
    const applyLocation = () => {
      const route = parseRoute()
      const canonicalHash = routeHash(route)
      if (window.location.hash !== canonicalHash) window.history.replaceState(null, '', canonicalHash)
      setSurface(route.surface)
      if (route.surface === 'app') setView(route.view)
      else setPublicSection(route.section)
    }
    applyLocation()
    window.addEventListener('hashchange', applyLocation)
    window.addEventListener('popstate', applyLocation)
    return () => {
      window.removeEventListener('hashchange', applyLocation)
      window.removeEventListener('popstate', applyLocation)
    }
  }, [])

  useEffect(() => {
    if (surface !== 'public') return
    const timer = window.setTimeout(() => {
      if (publicSection === 'inicio') window.scrollTo({ top: 0, behavior: 'smooth' })
      else document.getElementById(publicSection)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }, 0)
    return () => window.clearTimeout(timer)
  }, [publicSection, surface])

  useEffect(() => {
    if (!toast) return
    const timer = window.setTimeout(() => setToast(null), 3200)
    return () => window.clearTimeout(timer)
  }, [toast])

  const navigate = (route: RouteState) => {
    const nextHash = routeHash(route)
    if (window.location.hash !== nextHash) window.history.pushState(null, '', nextHash)
    setSurface(route.surface)
    if (route.surface === 'app') setView(route.view)
    else setPublicSection(route.section)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  const navigateApp = (nextView: AppView) => navigate({ surface: 'app', view: nextView })
  const openDashboard = () => {
    navigateApp('overview')
  }

  const notify = (message: string) => setToast(message)

  const renderView = () => {
    switch (view) {
      case 'data':
        return <DataHub onNotify={notify} />
      case 'api':
        return <ApiExplorer onNotify={notify} />
      case 'alerts':
        return <AlertsCenter onNotify={notify} />
      case 'methodology':
        return <Methodology />
      case 'settings':
        return <SettingsView theme={theme} onThemeChange={setTheme} onNotify={notify} />
      case 'help':
        return <HelpCenter onNotify={notify} onGoTo={navigateApp} />
      default:
        return <Dashboard onOpenAlerts={() => navigateApp('alerts')} onOpenData={() => navigateApp('data')} onNotify={notify} />
    }
  }

  return (
    <>
      {surface === 'public' ? (
        <PublicLanding
          onEnterDashboard={openDashboard}
          onOpenMethodology={() => navigateApp('methodology')}
          onOpenAuth={setAuthMode}
          theme={theme}
          onToggleTheme={() => setTheme((value) => value === 'dark' ? 'light' : 'dark')}
        />
      ) : (
        <AppShell view={view} onChangeView={navigateApp} onPublicHome={() => navigate({ surface: 'public', section: 'inicio' })} theme={theme} onToggleTheme={() => setTheme((value) => value === 'dark' ? 'light' : 'dark')}>
          {renderView()}
        </AppShell>
      )}

      {authMode && (
        <AuthModal
          initialMode={authMode}
          onClose={() => setAuthMode(null)}
          onOpenSupport={() => {
            setAuthMode(null)
            navigateApp('help')
          }}
          onSuccess={(persistent) => {
            setAuthMode(null)
            openDashboard()
            notify(persistent ? 'Sesión iniciada y recordada en este dispositivo' : 'Sesión iniciada para esta ventana')
          }}
          onContinueGuest={() => {
            setAuthMode(null)
            openDashboard()
            notify('Entraste en modo público; inicia sesión cuando quieras guardar preferencias')
          }}
        />
      )}

      {toast && (
        <div className="app-toast" role="status">
          <CheckCircle2 size={18}/><span>{toast}</span><button onClick={() => setToast(null)} aria-label="Cerrar notificación"><X size={16}/></button>
        </div>
      )}

      {surface === 'app' && <ProraAgent contextLabel={viewContext[view]} onNavigate={navigateApp} />}
    </>
  )
}
