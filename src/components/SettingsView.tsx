import { Bell, Check, Download, KeyRound, LoaderCircle, LockKeyhole, Moon, Save, ShieldCheck, Sun, UserRound } from 'lucide-react'
import { useEffect, useState } from 'react'
import { API_BASE_URL, ApiError, apiProfile, apiSession, proraApi } from '../lib/api'

interface SettingsViewProps {
  theme: 'light' | 'dark'
  onThemeChange: (theme: 'light' | 'dark') => void
  onNotify: (message: string) => void
}

interface ProfileForm { name: string; role: string; institution: string; email?: string }
type SyncState = 'guest' | 'loading' | 'ready' | 'saving' | 'error'

function loadProfile(): ProfileForm {
  const stored = apiProfile.load<Partial<ProfileForm>>()
  return {
    name: stored?.name ?? 'Usuario invitado',
    role: stored?.role ?? '',
    institution: stored?.institution ?? '',
    email: stored?.email,
  }
}

export default function SettingsView({ theme, onThemeChange, onNotify }: SettingsViewProps) {
  const authenticated = apiSession.isRegistered()
  const [emailAlerts, setEmailAlerts] = useState(() => !authenticated && localStorage.getItem('prora-email-alerts') === 'true')
  const [weeklyDigest, setWeeklyDigest] = useState(() => !authenticated && localStorage.getItem('prora-weekly-digest') === 'true')
  const [pushAlerts, setPushAlerts] = useState(() => !authenticated && localStorage.getItem('prora-push-alerts') === 'true')
  const [saved, setSaved] = useState(false)
  const [profile, setProfile] = useState<ProfileForm>(loadProfile)
  const [syncState, setSyncState] = useState<SyncState>(authenticated ? 'loading' : 'guest')
  const [syncError, setSyncError] = useState('')

  useEffect(() => {
    if (!authenticated) return
    let active = true
    setSyncState('loading')
    Promise.all([proraApi.preferences.get(), proraApi.auth.me()])
      .then(([preferences, user]) => {
        if (!active) return
        setEmailAlerts(preferences.email_alerts)
        setWeeklyDigest(preferences.digest_enabled)
        setPushAlerts(preferences.push_alerts)
        const preferredTheme = preferences.theme === 'system'
          ? (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
          : preferences.theme
        onThemeChange(preferredTheme)
        const currentProfile: ProfileForm = {
          name: user.full_name || user.name || user.email,
          email: user.email,
          role: user.role,
          institution: '',
        }
        setProfile(currentProfile)
        apiProfile.save({ ...currentProfile, userId: user.id }, apiSession.isPersistent())
        window.dispatchEvent(new CustomEvent('prora-profile-updated', { detail: currentProfile }))
        setSyncError('')
        setSyncState('ready')
      })
      .catch((error: unknown) => {
        if (!active) return
        setSyncError(error instanceof Error ? error.message : 'No fue posible consultar las preferencias.')
        setSyncState('error')
      })
    return () => { active = false }
  }, [authenticated, onThemeChange])

  const savePreferences = async () => {
    setSyncError('')
    if (authenticated) {
      setSyncState('saving')
      try {
        await proraApi.preferences.update({
          theme,
          digest_enabled: weeklyDigest,
          email_alerts: emailAlerts,
          push_alerts: pushAlerts,
        })
        setSyncState('ready')
        setSaved(true)
        onNotify('Preferencias sincronizadas con tu cuenta')
      } catch (error) {
        setSyncState('error')
        const message = error instanceof ApiError ? error.message : 'No fue posible guardar las preferencias.'
        setSyncError(message)
        onNotify(message)
        return
      }
    } else {
      localStorage.setItem('prora-email-alerts', String(emailAlerts))
      localStorage.setItem('prora-weekly-digest', String(weeklyDigest))
      localStorage.setItem('prora-push-alerts', String(pushAlerts))
      const savedProfile = { ...profile, savedAt: new Date().toISOString() }
      apiProfile.save(savedProfile, true)
      window.dispatchEvent(new CustomEvent('prora-profile-updated', { detail: savedProfile }))
      setSaved(true)
      onNotify('Preferencias de invitado guardadas en este dispositivo')
    }
    window.setTimeout(() => setSaved(false), 1800)
  }

  const downloadPolicy = () => {
    const blob = new Blob(['PRORA · Política de uso responsable\n\nDatos agregados, privacidad por diseño y supervisión humana.'], { type: 'text/plain;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = 'prora-politica-uso-responsable.txt'
    link.click()
    URL.revokeObjectURL(url)
    onNotify('Política descargada')
  }

  const busy = syncState === 'loading' || syncState === 'saving'
  const apiDocsUrl = `${API_BASE_URL.replace(/\/api\/v1$/, '')}/docs`

  return (
    <section className="workspace-view settings-view" aria-labelledby="settings-title">
      <header className="view-heading"><div><span className="eyebrow"><SettingsIcon /> Preferencias personales</span><h1 id="settings-title">Configuración</h1><p>Controla tu experiencia, alertas y accesos de PRORA.</p></div><button className="button button-primary" onClick={() => void savePreferences()} disabled={busy}>{busy ? <LoaderCircle className="spin" size={16}/> : saved ? <Check size={16}/> : <Save size={16}/>} {syncState === 'saving' ? 'Sincronizando' : saved ? 'Guardado' : 'Guardar cambios'}</button></header>

      <div className={`settings-sync-status settings-sync-status--${syncState}`} role="status">
        <ShieldCheck size={16}/>
        <span>{authenticated ? syncState === 'loading' ? 'Consultando preferencias de tu cuenta…' : syncState === 'error' ? syncError : 'Tus preferencias se leen y guardan mediante la API de tu cuenta.' : 'Estás en modo invitado: los cambios se guardan únicamente en este navegador.'}</span>
      </div>

      <div className="settings-layout">
        <div className="settings-main">
          <article className="content-card settings-card">
            <div className="settings-card-heading"><span className="settings-icon"><UserRound size={19}/></span><div><h2>Perfil de trabajo</h2><p>{authenticated ? 'Identidad verificada por el servicio de autenticación.' : 'Información local para personalizar esta experiencia de invitado.'}</p></div></div>
            {authenticated ? (
              <div className="form-grid"><label className="form-field">Nombre completo<input value={profile.name} readOnly /></label><label className="form-field">Correo<input value={profile.email ?? ''} readOnly /></label><label className="form-field form-field-wide">Rol asignado<input value={profile.role} readOnly /></label><p className="settings-note form-field-wide"><LockKeyhole size={14}/> La API actual no permite editar identidad ni institución desde el tablero. No se completan campos con valores supuestos.</p></div>
            ) : (
              <div className="form-grid"><label className="form-field">Nombre visible<input value={profile.name} onChange={(event) => setProfile((value) => ({ ...value, name: event.target.value }))} /></label><label className="form-field">Cargo local<input value={profile.role} onChange={(event) => setProfile((value) => ({ ...value, role: event.target.value }))} placeholder="No informado" /></label><label className="form-field form-field-wide">Institución local<input value={profile.institution} onChange={(event) => setProfile((value) => ({ ...value, institution: event.target.value }))} placeholder="No informada" /></label></div>
            )}
          </article>

          <article className="content-card settings-card">
            <div className="settings-card-heading"><span className="settings-icon"><Bell size={19}/></span><div><h2>Alertas y resúmenes</h2><p>Elige qué señales quieres recibir y con qué frecuencia.</p></div></div>
            <PreferenceRow title="Alertas por correo" detail="Habilita el canal de correo para reglas y suscripciones compatibles." checked={emailAlerts} disabled={busy} onChange={() => setEmailAlerts((value) => !value)} />
            <PreferenceRow title="Resumen epidemiológico" detail="Recibe el resumen periódico configurado para tu cuenta." checked={weeklyDigest} disabled={busy} onChange={() => setWeeklyDigest((value) => !value)} />
            <PreferenceRow title="Notificaciones push" detail="Habilita avisos push cuando el despliegue disponga de este canal." checked={pushAlerts} disabled={busy} onChange={() => setPushAlerts((value) => !value)} />
          </article>

          <article className="content-card settings-card">
            <div className="settings-card-heading"><span className="settings-icon"><KeyRound size={19}/></span><div><h2>Acceso de desarrollador</h2><p>Las operaciones privadas usan el token Bearer emitido al iniciar sesión.</p></div></div>
            <div className="api-key-box"><code>{authenticated ? 'Bearer de sesión activo' : 'Inicia sesión para operaciones privadas'}</code><button className="button button-secondary button-small" onClick={() => window.open(apiDocsUrl, '_blank', 'noopener,noreferrer')}>Abrir OpenAPI</button></div>
            <p className="settings-note"><LockKeyhole size={14}/> PRORA no genera claves ficticias ni las muestra en pantalla.</p>
          </article>
        </div>

        <aside className="settings-side">
          <article className="content-card appearance-card"><span className="settings-icon"><Sun size={19}/></span><h2>Apariencia</h2><p>Elige la presentación que mejor se adapte a tu jornada.</p><div className="theme-choices"><button className={theme === 'light' ? 'is-active' : ''} onClick={() => onThemeChange('light')}><Sun size={16}/> Claro</button><button className={theme === 'dark' ? 'is-active' : ''} onClick={() => onThemeChange('dark')}><Moon size={16}/> Oscuro</button></div></article>
          <article className="content-card privacy-card"><ShieldCheck size={22}/><h2>Privacidad por diseño</h2><p>PRORA trabaja con datos agregados por municipio. No solicita información identificable de pacientes.</p><button className="button button-ghost button-block" onClick={downloadPolicy}><Download size={15}/> Descargar política</button></article>
        </aside>
      </div>
    </section>
  )
}

function PreferenceRow({ title, detail, checked, disabled, onChange }: { title: string; detail: string; checked: boolean; disabled?: boolean; onChange: () => void }) {
  return <div className="preference-row"><div><strong>{title}</strong><p>{detail}</p></div><button role="switch" aria-checked={checked} className={checked ? 'toggle active' : 'toggle'} disabled={disabled} onClick={onChange} aria-label={`${checked ? 'Desactivar' : 'Activar'} ${title}`} /></div>
}

function SettingsIcon() { return <span className="settings-icon-inline"><Save size={14}/></span> }
