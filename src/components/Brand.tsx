import { Activity, Radar } from 'lucide-react'

export function BrandMark({ compact = false }: { compact?: boolean }) {
  return (
    <div className={`brand ${compact ? 'brand--compact' : ''}`} aria-label="PRORA">
      <span className="brand__symbol" aria-hidden="true">
        <Radar size={18} strokeWidth={2.2} />
        <Activity size={16} strokeWidth={2.4} />
      </span>
      {!compact && (
        <span className="brand__copy">
          <strong>PRORA</strong>
          <small>Salud pública</small>
        </span>
      )}
    </div>
  )
}
