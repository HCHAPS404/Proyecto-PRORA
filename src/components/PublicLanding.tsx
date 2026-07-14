import {
  ArrowRight,
  BarChart3,
  BrainCircuit,
  CheckCircle2,
  CloudRain,
  Code2,
  Database,
  Globe2,
  LockKeyhole,
  MapPinned,
  Menu,
  Moon,
  ShieldCheck,
  Sparkles,
  Stethoscope,
  Trees,
  Sun,
  UsersRound,
  X,
} from 'lucide-react'
import { useState } from 'react'
import { BrandMark } from './Brand'
import { ColombiaOutline } from './ColombiaRiskMap'

interface PublicLandingProps {
  onEnterDashboard: () => void
  onOpenMethodology: () => void
  onOpenAuth: (mode: 'login' | 'register') => void
  theme: 'light' | 'dark'
  onToggleTheme: () => void
}

const diseases = ['Dengue', 'Malaria', 'Chikunguña', 'Zika', 'Leishmaniasis', 'IRA']

export default function PublicLanding({ onEnterDashboard, onOpenMethodology, onOpenAuth, theme, onToggleTheme }: PublicLandingProps) {
  const [mobileMenu, setMobileMenu] = useState(false)

  return (
    <div className="public-site">
      <header className="public-nav">
        <BrandMark />
        <nav className={mobileMenu ? 'public-nav__links is-open' : 'public-nav__links'} aria-label="Navegación principal">
          <a href="#/inicio/capacidades" onClick={() => setMobileMenu(false)}>Capacidades</a>
          <a href="#/inicio/datos" onClick={() => setMobileMenu(false)}>Fuentes de datos</a>
          <a href="#/inicio/metodologia" onClick={() => setMobileMenu(false)}>Metodología</a>
          <button className="landing-theme-toggle" type="button" onClick={onToggleTheme} aria-label={theme === 'dark' ? 'Activar modo claro' : 'Activar modo oscuro'}>
            {theme === 'dark' ? <Sun size={17} /> : <Moon size={17} />}
            <span>{theme === 'dark' ? 'Modo claro' : 'Modo oscuro'}</span>
          </button>
          <button className="nav-login" onClick={() => onOpenAuth('login')}>Iniciar sesión</button>
          <button className="button button--dark nav-register" onClick={() => onOpenAuth('register')}>Crear cuenta</button>
        </nav>
        <button className="icon-button mobile-menu" onClick={() => setMobileMenu((value) => !value)} aria-label="Abrir menú">
          {mobileMenu ? <X size={20} /> : <Menu size={20} />}
        </button>
      </header>

      <main>
        <section className="hero-section">
          <div className="hero-grid" aria-hidden="true" />
          <div className="hero-copy">
            <div className="eyebrow"><Sparkles size={14} /> Inteligencia epidemiológica explicable</div>
            <h1>Anticipar hoy.<br /><span>Proteger mañana.</span></h1>
            <p>
              Un sistema de alerta temprana para comprender el riesgo de brotes transmisibles en Colombia,
              municipio a municipio y con hasta cuatro semanas de anticipación.
            </p>
            <div className="hero-actions">
              <button className="button button--primary button--large" onClick={onEnterDashboard}>
                Explorar tablero <ArrowRight size={18} />
              </button>
              <a className="text-link" href="#/inicio/metodologia">Cómo funciona <span>↘</span></a>
            </div>
            <div className="hero-trust">
              <span><CheckCircle2 size={15} /> Datos agregados, no personales</span>
              <span><CheckCircle2 size={15} /> Diseñado para el sector público</span>
            </div>
          </div>

          <div className="hero-visual" aria-label="Vista previa del sistema de alertas">
            <div className="hero-orbit hero-orbit--one" />
            <div className="hero-orbit hero-orbit--two" />
            <div className="preview-card">
              <div className="preview-card__top">
                <span className="live-pill"><span /> Vista conceptual · Sin datos en vivo</span>
              </div>
              <div className="preview-map">
                <svg viewBox="0 0 620 560" role="img" aria-label="Mapa departamental ilustrativo de Colombia">
                  <defs><linearGradient id="mapGradient" x1="0" y1="0" x2="1" y2="1"><stop stopColor="#bfead0"/><stop offset="1" stopColor="#4fb27a"/></linearGradient></defs>
                  <ColombiaOutline fill="url(#mapGradient)" stroke="#dff7ea" transform="translate(105 0) scale(1.12)" />
                  <circle cx="255" cy="287" r="25" className="pulse-circle pulse-circle--red" />
                  <circle cx="255" cy="287" r="8" fill="#e35858" />
                  <circle cx="275" cy="110" r="19" className="pulse-circle pulse-circle--amber" />
                  <circle cx="275" cy="110" r="7" fill="#e8a43e" />
                  <circle cx="424" cy="366" r="13" fill="#1c9b72" fillOpacity=".35" />
                </svg>
                <div className="preview-tooltip">
                  <span className="risk-dot risk-dot--high" />
                  <div><small>Territorio ilustrativo</small><strong>Ejemplo de capa de riesgo</strong></div>
                </div>
              </div>
              <div className="preview-stats">
                <div><span>Alertas</span><strong>API</strong><small>Solo señales publicadas</small></div>
                <div><span>Territorios</span><strong>DIVIPOLA</strong><small>Identidad verificable</small></div>
                <div><span>Predicción</span><strong>Versionada</strong><small>Con trazabilidad</small></div>
              </div>
            </div>
            <div className="floating-note floating-note--weather"><CloudRain size={19} /><div><small>Variable ambiental</small><strong>Dato desde fuente oficial</strong></div></div>
            <div className="floating-note floating-note--model"><BrainCircuit size={19} /><div><small>Plataforma</small><strong>API + registro de modelos</strong></div></div>
          </div>
        </section>

        <section className="disease-marquee" aria-label="Enfermedades priorizadas">
          <span>Vigilancia priorizada</span>
          <div>{diseases.map((disease) => <span key={disease}><i /> {disease}</span>)}</div>
        </section>

        <section id="capacidades" className="landing-section">
          <div className="section-kicker">Del dato a la decisión</div>
          <div className="section-heading">
            <h2>Una misma señal.<br />Tres niveles de lectura.</h2>
            <p>Información clara para quien toma decisiones, profundidad para vigilancia epidemiológica y acceso abierto para equipos analíticos.</p>
          </div>
          <div className="capability-grid">
            <article className="capability-card capability-card--featured">
              <div className="capability-icon"><MapPinned /></div>
              <span className="card-index">01</span>
              <h3>Vista ejecutiva</h3>
              <p>Alertas priorizadas, población potencialmente expuesta y focos territoriales en una sola mirada.</p>
              <div className="mini-risk-list" aria-label="Ejemplo conceptual de niveles de prioridad">
                <span><i className="risk-dot risk-dot--critical" /> Crítico</span>
                <span><i className="risk-dot risk-dot--high" /> Alto</span>
                <span><i className="risk-dot risk-dot--medium" /> Moderado</span>
              </div>
            </article>
            <article className="capability-card">
              <div className="capability-icon"><BarChart3 /></div>
              <span className="card-index">02</span>
              <h3>Lectura epidemiológica</h3>
              <p>Historia de casos, incertidumbre y factores que impulsan cada alerta explicados sin cajas negras.</p>
              <div className="mini-bars" aria-hidden="true"><i/><i/><i/><i/><i/><i/><i/><i/></div>
            </article>
            <article className="capability-card">
              <div className="capability-icon"><Code2 /></div>
              <span className="card-index">03</span>
              <h3>Acceso para analistas</h3>
              <p>Plantillas CSV, catálogo de fuentes y explorador de una API REST lista para integraciones.</p>
              <div className="mini-code"><span>GET</span> /api/v1/risk/map</div>
            </article>
          </div>
        </section>

        <section id="datos" className="data-band">
          <div>
            <div className="section-kicker section-kicker--light">Fuentes públicas integrables</div>
            <h2>Señales complementarias para comprender cada territorio.</h2>
          </div>
          <div className="source-flow">
            {[
              [Stethoscope, 'SIVIGILA', 'Casos semanales'],
              [ShieldCheck, 'PAI', 'Vacunación'],
              [CloudRain, 'IDEAM', 'Clima'],
              [Trees, 'IDEAM', 'Deforestación'],
              [UsersRound, 'DANE', 'Contexto social'],
            ].map(([Icon, label, detail]) => {
              const SourceIcon = Icon as typeof Database
              return <div className="source-node" key={`${String(label)}-${String(detail)}`}><SourceIcon size={21}/><span><strong>{label as string}</strong><small>{detail as string}</small></span></div>
            })}
          </div>
        </section>

        <section id="metodologia" className="landing-section method-section">
          <div className="method-copy">
            <div className="section-kicker">IA responsable por diseño</div>
            <h2>Una alerta solo es útil si se puede explicar.</h2>
            <p>El sistema propuesto combina patrones temporales, interacciones territoriales y evidencia histórica. Cada predicción conserva su linaje y comunica sus limitaciones.</p>
            <ul>
              <li><BrainCircuit /> Arquitecturas predictivas versionables</li>
              <li><Globe2 /> Validación temporal y territorial</li>
              <li><LockKeyhole /> Datos municipales agregados</li>
              <li><ShieldCheck /> Trazabilidad de modelo y fuentes</li>
            </ul>
            <button className="button button--outline" onClick={onOpenMethodology}>Ver metodología en el tablero <ArrowRight size={17}/></button>
          </div>
          <div className="model-visual" aria-label="Flujo conceptual del modelo predictivo">
            <div className="model-node model-node--sources"><Database/><span>Fuentes oficiales<strong>Datos trazables</strong></span></div>
            <div className="model-line" />
            <div className="model-core"><BrainCircuit size={31}/><span>Registro de modelos</span><small>Arquitectura y métricas verificables</small></div>
            <div className="model-line model-line--right" />
            <div className="model-node model-node--output"><MapPinned/><span>Cobertura municipal<strong>Horizonte configurable</strong></span></div>
          </div>
        </section>
      </main>

      <footer className="public-footer">
        <BrandMark />
        <p>Plataforma de vigilancia · La interpretación siempre debe complementarse con el criterio territorial.</p>
        <button className="button button--primary" onClick={onEnterDashboard}>Abrir tablero <ArrowRight size={16}/></button>
      </footer>
    </div>
  )
}
