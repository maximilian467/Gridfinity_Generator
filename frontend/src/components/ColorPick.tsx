import type { PartColors } from '../lib/types'

/** Gängige Filamentfarben; eigene Farben über den Farbwähler */
export const PALETTE: [string, string][] = [
  ['Anthrazit', '#3b3f45'], ['Schwarz', '#1d1f22'], ['Grau', '#8a8f96'], ['Weiß', '#f2f2f0'],
  ['Orange', '#f26b1d'], ['Rot', '#d6322e'], ['Gelb', '#f2c12e'], ['Blau', '#2a6fd6'], ['Grün', '#3a9d4f'],
]

export const PART_LABELS: [keyof PartColors, string][] = [
  ['body', 'Körper'], ['pocket', 'Taschen'], ['grip', 'Greifmulden'], ['compartment', 'Fächer'],
]

export function colorName(hex: string): string {
  return PALETTE.find(([, h]) => h.toLowerCase() === hex.toLowerCase())?.[0] ?? hex.toUpperCase()
}

/** Filament-Slots aus den Farben: gleiche Farbe = gleicher Slot, Reihenfolge Körper, Taschen, Mulden, Fächer */
export function slotsFromColors(c: PartColors): { body: number; pocket: number; grip: number; compartment: number } {
  const order: string[] = []
  const slot = (h: string) => {
    const k = h.toLowerCase()
    if (!order.includes(k)) order.push(k)
    return order.indexOf(k) + 1
  }
  return { body: slot(c.body), pocket: slot(c.pocket), grip: slot(c.grip), compartment: slot(c.compartment) }
}

export function ColorPick({ value, onChange, label }: { value: string; onChange: (v: string) => void; label: string }) {
  return (
    <div className="grid gap-1">
      <div className="flex items-center justify-between gap-2 text-sm">
        <span>{label}</span><span className="num text-xs" style={{ color: 'var(--ink-2)' }}>{colorName(value)}</span>
      </div>
      <div className="flex flex-wrap gap-1 items-center">
        {PALETTE.map(([name, hex]) => (
          <button key={hex} title={name} aria-label={`${label}: ${name}`} onClick={() => onChange(hex)}
            style={{ width: 22, height: 22, borderRadius: 6, background: hex, cursor: 'pointer',
              border: value.toLowerCase() === hex ? '2px solid var(--accent)' : '1px solid var(--line-2)',
              outline: value.toLowerCase() === hex ? '2px solid var(--surface)' : 'none', outlineOffset: -4 }} />
        ))}
        <label title="Eigene Farbe" className="inline-grid place-items-center" style={{ width: 22, height: 22, borderRadius: 6, border: '1px dashed var(--ink-3)', cursor: 'pointer', overflow: 'hidden' }}>
          <input type="color" value={value} onChange={(e) => onChange(e.target.value)} style={{ opacity: 0, width: 22, height: 22, cursor: 'pointer' }} aria-label={`${label}: eigene Farbe`} />
        </label>
      </div>
    </div>
  )
}

/** parts: nur diese Teile anbieten (z. B. Blindstopfen: nur der Körper) */
export function PartColorsEdit({ value, onChange, parts }: { value: PartColors; onChange: (v: PartColors) => void; parts?: (keyof PartColors)[] }) {
  const slots = slotsFromColors(value)
  return (
    <div className="grid gap-3">
      {PART_LABELS.filter(([k]) => !parts || parts.includes(k)).map(([k, label]) => (
        <ColorPick key={k} label={`${label} · Slot ${slots[k]}`} value={value[k]} onChange={(v) => onChange({ ...value, [k]: v })} />
      ))}
      <div className="hint mt-0">Gleiche Farben teilen sich einen Filament-Slot im 3MF (Bambu Studio / Orca).</div>
    </div>
  )
}
