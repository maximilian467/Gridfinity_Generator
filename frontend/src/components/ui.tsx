import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <div>
      <label className="label">{label}</label>
      {children}
      {hint && <div className="hint">{hint}</div>}
    </div>
  )
}

export function NumberField({ label, value, onChange, step = 0.1, unit = 'mm', min, max, hint, disabled }: {
  label: string; value: number; onChange: (v: number) => void; step?: number; unit?: string
  min?: number; max?: number; hint?: string; disabled?: boolean
}) {
  const [text, setText] = useState(String(value))
  useEffect(() => { setText(String(Math.round(value * 1000) / 1000)) }, [value])
  return (
    <Field label={label} hint={hint}>
      <div className="relative">
        <input
          className="input num pr-9" inputMode="decimal" value={text} disabled={disabled}
          onChange={(e) => {
            setText(e.target.value)
            const v = parseFloat(e.target.value.replace(',', '.'))
            if (!Number.isNaN(v) && (min === undefined || v >= min) && (max === undefined || v <= max)) onChange(v)
          }}
          onKeyDown={(e) => {
            if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
              e.preventDefault()
              const v = value + (e.key === 'ArrowUp' ? step : -step)
              onChange(Math.round(v * 1000) / 1000)
            }
          }}
          onBlur={() => setText(String(Math.round(value * 1000) / 1000))}
        />
        <span className="absolute right-2 top-1/2 -translate-y-1/2 text-xs" style={{ color: 'var(--ink-3)' }}>{unit}</span>
      </div>
    </Field>
  )
}

export function Segmented<T extends string | number>({ options, value, onChange }: {
  options: { value: T; label: string }[]; value: T; onChange: (v: T) => void
}) {
  return (
    <div className="inline-flex gap-1" role="group">
      {options.map((o) => (
        <button key={String(o.value)} className={`btn btn-sm ${o.value === value ? 'btn-on' : ''}`}
          aria-pressed={o.value === value} onClick={() => onChange(o.value)}>{o.label}</button>
      ))}
    </div>
  )
}

export function Check({ label, checked, onChange }: { label: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="flex items-center gap-2 cursor-pointer select-none">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)}
        style={{ accentColor: 'var(--accent)', width: 16, height: 16 }} />
      <span>{label}</span>
    </label>
  )
}

export function Stepper({ steps, current, onGo }: { steps: string[]; current: number; onGo: (i: number) => void }) {
  return (
    <ol className="flex flex-wrap gap-x-1 gap-y-1 m-0 p-0 list-none">
      {steps.map((s, i) => (
        <li key={s}>
          <button className={`btn btn-sm ${i === current ? 'btn-on' : 'btn-quiet'}`} onClick={() => onGo(i)}
            aria-current={i === current ? 'step' : undefined}>
            <span className="num">{i + 1}</span> {s}
          </button>
        </li>
      ))}
    </ol>
  )
}

export function Msgs({ items, kind = 'warn' }: { items?: string[]; kind?: 'warn' | 'err' | 'ok' }) {
  if (!items?.length) return null
  return (
    <div className="grid gap-1">
      {items.map((m, i) => <div key={i} className={`msg msg-${kind}`}>{m}</div>)}
    </div>
  )
}

export function Silhouette({ contour, className = '' }: { contour: [number, number][]; className?: string }) {
  if (!contour.length) return <div className={`skeleton ${className}`} />
  const xs = contour.map((p) => p[0]); const ys = contour.map((p) => p[1])
  const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys)
  const pad = 4
  const pts = contour.map(([x, y]) => `${(x - x0).toFixed(1)},${(y1 - y).toFixed(1)}`).join(' ')
  return (
    <svg className={className} viewBox={`${-pad} ${-pad} ${x1 - x0 + 2 * pad} ${y1 - y0 + 2 * pad}`} role="img" aria-label="Umriss">
      <polygon points={pts} fill="var(--accent-soft)" stroke="var(--accent)" strokeWidth={1.2} vectorEffect="non-scaling-stroke" />
    </svg>
  )
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="panel p-6 grid gap-2" style={{ borderStyle: 'dashed' }}>
      <div className="font-medium">{title}</div>
      <div style={{ color: 'var(--ink-2)' }}>{children}</div>
    </div>
  )
}
