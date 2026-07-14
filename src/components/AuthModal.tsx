import { ArrowRight, Check, CircleHelp, Eye, EyeOff, LockKeyhole, Mail, RefreshCw, ShieldCheck, UserRound, WifiOff, X } from 'lucide-react'
import { FormEvent, useCallback, useEffect, useState } from 'react'
import { BrandMark } from './Brand'
import { ApiError, apiProfile, apiSession, proraApi } from '../lib/api'

interface AuthModalProps {
  initialMode: 'login' | 'register'
  onClose: () => void
  onSuccess: (persistent: boolean) => void
  onOpenSupport: () => void
  onContinueGuest: () => void
}

export default function AuthModal({ initialMode, onClose, onSuccess, onOpenSupport, onContinueGuest }: AuthModalProps) {
  const [mode, setMode] = useState(initialMode)
  const [showPassword, setShowPassword] = useState(false)
  const [submitted, setSubmitted] = useState(false)
  const [recoveryOpen, setRecoveryOpen] = useState(false)
  const [remember, setRemember] = useState(false)
  const [loading, setLoading] = useState(false)
  const [guestLoading, setGuestLoading] = useState(false)
  const [formError, setFormError] = useState('')
  const [apiState, setApiState] = useState<'checking' | 'online' | 'offline'>('checking')

  const checkApi = useCallback(() => {
    setApiState('checking')
    proraApi.health().then(() => setApiState('online')).catch(() => setApiState('offline'))
  }, [])

  useEffect(() => { checkApi() }, [checkApi])

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setFormError('')
    const formData = new FormData(event.currentTarget)
    const email = String(formData.get('email') ?? '').trim().toLowerCase()
    const password = String(formData.get('password') ?? '')
    const fullName = String(formData.get('name') ?? '').trim()
    if (mode === 'register') {
      if (fullName.length < 2) {
        setFormError('Escribe tu nombre completo para crear la cuenta.')
        return
      }
      if (password.length < 12 || !/[a-z]/.test(password) || !/[A-Z]/.test(password) || !/\d/.test(password)) {
        setFormError('La contraseña debe tener al menos 12 caracteres, una mayúscula, una minúscula y un número.')
        return
      }
    }
    setLoading(true)
    try {
      const tokens = mode === 'register'
        ? await proraApi.auth.register({ email, password, full_name: fullName })
        : await proraApi.auth.login(email, password)
      apiSession.save(tokens, remember)
      const apiUser = tokens.user ?? await proraApi.auth.me()
      const profile = {
        name: apiUser.full_name || apiUser.name || fullName || email.split('@')[0],
        email: apiUser.email || email,
        role: apiUser.role,
        userId: apiUser.id,
        savedAt: new Date().toISOString(),
      }
      apiProfile.save(profile, remember)
      window.dispatchEvent(new CustomEvent('prora-profile-updated', { detail: profile }))
      setSubmitted(true)
      window.setTimeout(() => onSuccess(remember), 500)
    } catch (error) {
      setFormError(error instanceof ApiError ? error.message : 'No fue posible completar el acceso.')
    } finally {
      setLoading(false)
    }
  }

  const continueAsGuest = async () => {
    if (apiState !== 'online') {
      onContinueGuest()
      return
    }
    setGuestLoading(true)
    setFormError('')
    try {
      const tokens = await proraApi.auth.guest()
      apiSession.save(tokens, false)
    } catch {
      // Public endpoints and the dashboard remain available without a token.
      // The interface will continue to report the API as offline if applicable.
    } finally {
      setGuestLoading(false)
      onContinueGuest()
    }
  }

  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <section className="auth-modal" role="dialog" aria-modal="true" aria-labelledby="auth-title">
        <div className="auth-aside">
          <BrandMark />
          <div>
            <span className="auth-aside__eyebrow"><ShieldCheck size={15}/> Acceso institucional</span>
            <h2>Decisiones más tempranas empiezan con señales más claras.</h2>
            <p>Configura territorios, recibe alertas y conserva trazabilidad de cada consulta.</p>
          </div>
          <div className="auth-proof">
            <div className="auth-avatars"><span>INS</span><span>MS</span><span>ET</span></div>
            <p>Diseñado para equipos nacionales y territoriales de salud pública.</p>
          </div>
        </div>
        <div className="auth-panel">
          <button className="icon-button auth-close" onClick={onClose} aria-label="Cerrar"><X size={19}/></button>
          <div className="auth-tabs" role="tablist">
            <button className={mode === 'login' ? 'is-active' : ''} onClick={() => { setMode('login'); setRecoveryOpen(false); setFormError('') }}>Iniciar sesión</button>
            <button className={mode === 'register' ? 'is-active' : ''} onClick={() => { setMode('register'); setRecoveryOpen(false); setFormError('') }}>Crear cuenta</button>
          </div>
          <div className="auth-heading">
            <span className="auth-heading__icon">{mode === 'login' ? <LockKeyhole/> : <UserRound/>}</span>
            <h1 id="auth-title">{mode === 'login' ? 'Bienvenido de nuevo' : 'Solicita tu acceso'}</h1>
            <p>{mode === 'login' ? 'Ingresa a tu espacio de vigilancia.' : 'Crea un perfil para guardar alertas y territorios.'}</p>
          </div>
          <div className={`auth-api-status auth-api-status--${apiState}`} role="status">
            {apiState === 'offline' ? <WifiOff size={17} /> : apiState === 'checking' ? <RefreshCw className="spin" size={17} /> : <Check size={17} />}
            <span>{apiState === 'online' ? 'Servicio de cuentas disponible' : apiState === 'checking' ? 'Verificando el servicio de cuentas…' : 'El backend no está respondiendo; no será posible registrar o iniciar sesión hasta reconectarlo.'}</span>
            {apiState === 'offline' && <button type="button" onClick={checkApi}>Reintentar</button>}
          </div>
          <form onSubmit={handleSubmit} className="auth-form">
            {mode === 'register' && (
              <label>Nombre completo<div className="input-shell"><UserRound size={17}/><input name="name" required placeholder="María Rodríguez" /></div></label>
            )}
            <label>Correo institucional<div className="input-shell"><Mail size={17}/><input name="email" type="email" required placeholder="nombre@institucion.gov.co" /></div></label>
            <label>Contraseña<div className="input-shell"><LockKeyhole size={17}/><input name="password" type={showPassword ? 'text' : 'password'} required minLength={mode === 'register' ? 12 : 1} placeholder="••••••••••••" /><button type="button" onClick={() => setShowPassword((value) => !value)} aria-label={showPassword ? 'Ocultar contraseña' : 'Mostrar contraseña'}>{showPassword ? <EyeOff size={17}/> : <Eye size={17}/>}</button></div>{mode === 'register' && <small className="auth-field-hint">Mínimo 12 caracteres, con mayúscula, minúscula y número.</small>}</label>
            <div className="form-meta"><label className="checkbox-label"><input type="checkbox" checked={remember} onChange={(event) => setRemember(event.target.checked)}/> <span>Recordarme en este dispositivo</span></label>{mode === 'login' && <button type="button" onClick={() => setRecoveryOpen((value) => !value)} aria-expanded={recoveryOpen}>Recuperar acceso</button>}</div>
            {recoveryOpen && <div className="auth-recovery-notice" role="status"><CircleHelp size={18}/><div><strong>Recuperación automática no configurada</strong><p>PRORA no dispone todavía de un endpoint para restablecer contraseñas. Ningún correo ha sido enviado.</p><button type="button" onClick={onOpenSupport}>Ir al centro de ayuda</button></div></div>}
            {formError && <p className="auth-form-error" role="alert">{formError}</p>}
            <button className={`button button--primary button--full ${submitted ? 'is-success' : ''}`} type="submit" disabled={loading || submitted}>
              {submitted ? <><Check size={18}/> Acceso correcto</> : loading ? 'Conectando con PRORA…' : <>{mode === 'login' ? 'Ingresar al tablero' : 'Crear cuenta'} <ArrowRight size={17}/></>}
            </button>
          </form>
          <div className="auth-separator"><span>o</span></div>
          <button className="button button--secondary button--full auth-guest-button" type="button" onClick={() => void continueAsGuest()} disabled={guestLoading}>
            {guestLoading ? <RefreshCw className="spin" size={17} /> : <UserRound size={17} />}
            {guestLoading ? 'Preparando acceso público…' : 'Continuar sin cuenta'}
          </button>
          <p className="auth-disclaimer">{remember ? 'La sesión permanecerá en este dispositivo hasta que cierres sesión.' : 'La sesión se conservará solo mientras esta pestaña o ventana permanezca abierta.'}</p>
        </div>
      </section>
    </div>
  )
}
