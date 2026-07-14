import { Check, ChevronDown, Search, X } from 'lucide-react'
import {
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import '../searchable-select.css'

export type SearchableSelectOption = {
  value: string
  label: string
  group?: string
  searchText?: string
  disabled?: boolean
}

type SearchableSelectProps = {
  value: string
  options: SearchableSelectOption[]
  onChange: (value: string) => void
  ariaLabel: string
  placeholder?: string
  searchPlaceholder?: string
  emptyLabel?: string
  disabled?: boolean
  leading?: ReactNode
  className?: string
}

function normalize(value: string) {
  return value
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLocaleLowerCase('es')
    .trim()
}

export default function SearchableSelect({
  value,
  options,
  onChange,
  ariaLabel,
  placeholder = 'Seleccione una opción',
  searchPlaceholder = 'Buscar…',
  emptyLabel = 'No hay coincidencias',
  disabled = false,
  leading,
  className = '',
}: SearchableSelectProps) {
  const id = useId().replace(/:/g, '')
  const rootRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const optionRefs = useRef<Array<HTMLButtonElement | null>>([])
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [activeIndex, setActiveIndex] = useState(0)

  const selected = options.find((option) => option.value === value)
  const selectedIndex = useMemo(() => Math.max(0, options.findIndex((option) => option.value === value)), [options, value])
  const filtered = useMemo(() => {
    const needle = normalize(query)
    if (!needle) return options
    return options.filter((option) => normalize(`${option.label} ${option.searchText ?? ''} ${option.group ?? ''}`).includes(needle))
  }, [options, query])

  useEffect(() => {
    if (!open) return
    const handlePointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('pointerdown', handlePointerDown)
    return () => document.removeEventListener('pointerdown', handlePointerDown)
  }, [open])

  useEffect(() => {
    if (!open) return
    setQuery('')
    setActiveIndex(selectedIndex)
    window.setTimeout(() => inputRef.current?.focus(), 0)
  }, [open, selectedIndex])

  useEffect(() => {
    if (activeIndex >= filtered.length) setActiveIndex(Math.max(0, filtered.length - 1))
  }, [activeIndex, filtered.length])

  const choose = (option: SearchableSelectOption) => {
    if (option.disabled) return
    onChange(option.value)
    setOpen(false)
    setQuery('')
  }

  const move = (direction: 1 | -1) => {
    if (!filtered.length) return
    let next = activeIndex
    do {
      next = (next + direction + filtered.length) % filtered.length
    } while (filtered[next]?.disabled && next !== activeIndex)
    setActiveIndex(next)
    optionRefs.current[next]?.scrollIntoView({ block: 'nearest' })
  }

  return (
    <div ref={rootRef} className={`searchable-select${open ? ' is-open' : ''}${disabled ? ' is-disabled' : ''}${className ? ` ${className}` : ''}`}>
      <button
        type="button"
        className="searchable-select__trigger"
        aria-label={ariaLabel}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={`${id}-listbox`}
        disabled={disabled}
        onClick={() => setOpen((current) => !current)}
        onKeyDown={(event) => {
          if (event.key === 'ArrowDown' || event.key === 'Enter' || event.key === ' ') {
            event.preventDefault()
            setOpen(true)
          }
          if (event.key === 'Escape') setOpen(false)
        }}
      >
        <span className={`searchable-select__leading${leading ? '' : ' is-empty'}`} aria-hidden="true">{leading}</span>
        <span className={selected ? '' : 'is-placeholder'}>{selected?.label ?? placeholder}</span>
        <ChevronDown size={16} aria-hidden="true" />
      </button>

      {open && (
        <div className="searchable-select__popover">
          <label className="searchable-select__search" htmlFor={`${id}-search`}>
            <Search size={16} aria-hidden="true" />
            <span className="sr-only">Buscar en {ariaLabel.toLocaleLowerCase('es')}</span>
            <input
              ref={inputRef}
              id={`${id}-search`}
              value={query}
              onChange={(event) => { setQuery(event.target.value); setActiveIndex(0) }}
              onKeyDown={(event) => {
                if (event.key === 'ArrowDown') { event.preventDefault(); move(1) }
                if (event.key === 'ArrowUp') { event.preventDefault(); move(-1) }
                if (event.key === 'Enter' && filtered[activeIndex]) { event.preventDefault(); choose(filtered[activeIndex]) }
                if (event.key === 'Escape') { event.preventDefault(); setOpen(false) }
              }}
              placeholder={searchPlaceholder}
              autoComplete="off"
            />
            {query && <button type="button" onClick={() => { setQuery(''); inputRef.current?.focus() }} aria-label="Limpiar búsqueda"><X size={14}/></button>}
          </label>

          <div id={`${id}-listbox`} className="searchable-select__list" role="listbox" aria-label={ariaLabel}>
            {filtered.map((option, index) => {
              const previousGroup = index > 0 ? filtered[index - 1]?.group : undefined
              const showGroup = option.group && option.group !== previousGroup
              return (
                <div className="searchable-select__option-wrap" key={option.value}>
                  {showGroup && <span className="searchable-select__group">{option.group}</span>}
                  <button
                    ref={(node) => { optionRefs.current[index] = node }}
                    type="button"
                    role="option"
                    aria-selected={option.value === value}
                    className={index === activeIndex ? 'is-active' : ''}
                    disabled={option.disabled}
                    onMouseEnter={() => setActiveIndex(index)}
                    onClick={() => choose(option)}
                  >
                    <span>{option.label}</span>
                    {option.value === value && <Check size={15} aria-hidden="true" />}
                  </button>
                </div>
              )
            })}
            {!filtered.length && <div className="searchable-select__empty">{emptyLabel}</div>}
          </div>
        </div>
      )}
    </div>
  )
}
