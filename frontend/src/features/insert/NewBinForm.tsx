import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { api } from '../../lib/api'
import { Msg, NumberField, errText } from '../../components/ui'
import type { InsertSpec } from '../../lib/types'
import { LIP_MARGIN as LIP, MIN_SIDE, binOuter, cellSize } from '../../lib/binGrid'

const WALL = 1.6

/** Draufsicht der Teilung: Außenkante und Fächer (Standard-Wandstärke). */
export function BinSketch({ gx, gy, cols, rows, shelf = false, className }: { gx: number; gy: number; cols: number; rows: number; shelf?: boolean; className?: string }) {
  const [ox, oy] = binOuter(gx, gy)
  const [cw, ch] = cellSize(gx, gy, cols, rows)
  const ok = cw >= MIN_SIDE && ch >= MIN_SIDE
  return (
    <svg viewBox={`-2 -2 ${ox + 4} ${oy + 4}`} className={className} role="img" aria-label={`${cols} x ${rows} Fächer`}>
      <rect x={0} y={0} width={ox} height={oy} rx={3.75} fill="var(--surface-2)" stroke="var(--ink-3)" strokeWidth={0.8} />
      {ok && Array.from({ length: rows }, (_, j) => Array.from({ length: cols }, (_, i) => (
        <rect key={`${i}-${j}`} x={LIP + i * (cw + WALL)} y={LIP + j * (ch + WALL)} width={cw} height={ch}
          rx={Math.min(3, cw / 2, ch / 2)} fill="var(--accent-soft)" stroke="var(--accent)" strokeWidth={0.6} />
      )))}
      {ok && shelf && Array.from({ length: rows }, (_, j) => Array.from({ length: cols }, (_, i) => (
        // Vordach an der hinteren Wand (oben in der Draufsicht)
        <rect key={`s${i}-${j}`} x={LIP + i * (cw + WALL)} y={LIP + j * (ch + WALL)} width={cw} height={Math.min(12, 0.6 * Math.min(cw, ch))}
          fill="var(--ink-3)" opacity={0.55} />
      )))}
    </svg>
  )
}

/** Formular "Neue Fächer-Einlage": Raster, Teilung, Höhe. Legt an und meldet die neue Einlage. */
export function NewBinForm({ projectId, defaultHeight, onCreated, onCancel }: {
  projectId?: string | null; defaultHeight?: number | null
  onCreated: (i: InsertSpec) => void; onCancel: () => void
}) {
  const std = useQuery({ queryKey: ['standard-height'], queryFn: api.standardHeight, staleTime: 60_000, enabled: !projectId })
  const [f, setF] = useState({ name: 'Fächer-Einlage', gx: 2, gy: 2, cols: 2, rows: 2 })
  const [height, setHeight] = useState<number | null>(null)       // null = Standard bzw. Vorlage
  const [shelf, setShelf] = useState(false)                       // Vordach mit Beschriftung je Fach
  const [labels, setLabels] = useState('')                        // Beschriftungen, durch Komma getrennt
  const h = height ?? defaultHeight ?? std.data?.height_mm ?? null
  const [cw, ch] = cellSize(f.gx, f.gy, f.cols, f.rows)
  const tooSmall = cw < MIN_SIDE || ch < MIN_SIDE
  const create = useMutation({
    mutationFn: () => api.createBin({ name: f.name, grid_x: f.gx, grid_y: f.gy, cols: f.cols, rows: f.rows,
      height_mm: height, project_id: projectId ?? null, shelf,
      labels: labels.split(/[,;]/).map((t) => t.trim()).slice(0, f.cols * f.rows) }),
    onSuccess: onCreated,
  })
  const int = (v: number, max: number) => Math.min(Math.max(Math.round(v) || 1, 1), max)
  return (
    <div className="panel p-3 grid gap-3 md:grid-cols-[minmax(0,1fr)_200px]">
      <div className="grid gap-2 content-start">
        <div className="hint mt-0">Einlage ohne Werkzeug: die Fläche wird in gleich große Fächer geteilt, jedes so tief wie möglich.
          Danach lassen sich Fächer im Designer verbinden, teilen oder löschen.</div>
        <label className="grid gap-1"><span className="label mb-0">Name</span>
          <input className="input" value={f.name} onChange={(e) => setF((q) => ({ ...q, name: e.target.value }))} placeholder="z. B. Schrauben M3" /></label>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
          <NumberField label="Breite" unit="E" step={1} min={1} max={12} value={f.gx} onChange={(v) => setF((q) => ({ ...q, gx: int(v, 12) }))} />
          <NumberField label="Tiefe" unit="E" step={1} min={1} max={12} value={f.gy} onChange={(v) => setF((q) => ({ ...q, gy: int(v, 12) }))} />
          <NumberField label="Fächer nebeneinander" unit="" step={1} min={1} max={12} value={f.cols} onChange={(v) => setF((q) => ({ ...q, cols: int(v, 12) }))} />
          <NumberField label="Fächer hintereinander" unit="" step={1} min={1} max={12} value={f.rows} onChange={(v) => setF((q) => ({ ...q, rows: int(v, 12) }))} />
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 items-end">
          <NumberField label="Gesamthöhe" step={1} min={10} max={250} value={h ?? 32} onChange={(v) => setHeight(v)}
            hint={height === null ? (projectId ? 'aus der Projektvorlage' : h !== null ? 'Standardhöhe' : 'automatisch') : 'inkl. Stapelrand'} />
          <div className="sm:col-span-3 num text-sm" style={{ color: tooSmall ? 'var(--err)' : 'var(--ink-2)' }}>
            {tooSmall ? 'Fächer wären schmaler als 6 mm: weniger Fächer oder größeres Raster.'
              : <>{f.cols * f.rows} Fächer, je etwa {cw.toFixed(1).replace('.', ',')} x {ch.toFixed(1).replace('.', ',')} mm</>}
          </div>
        </div>
        <label className="grid gap-1"><span className="label mb-0">Beschriftung je Fach <span className="hint">(durch Komma getrennt, von hinten links zeilenweise; mittig im Fach)</span></span>
          <input className="input" value={labels} onChange={(e) => setLabels(e.target.value)} placeholder="z. B. 0.5, 0.75, 1, 1.5" /></label>
        <label className="inline-flex items-center gap-2 cursor-pointer">
          <input type="checkbox" checked={shelf} onChange={(e) => setShelf(e.target.checked)} />
          <span>Vordach mit Beschriftung an der hinteren Wand <span className="hint">(oben im Fach, darunter 45° abgeschrägt; druckt ohne Stützen)</span></span>
        </label>
        <div className="flex gap-2">
          <button className="btn btn-primary" onClick={() => create.mutate()} disabled={create.isPending || tooSmall}>Anlegen</button>
          <button className="btn" onClick={onCancel}>Abbrechen</button>
        </div>
        {create.isError && <Msg kind="err">{errText(create.error)}</Msg>}
      </div>
      <BinSketch gx={f.gx} gy={f.gy} cols={f.cols} rows={f.rows} shelf={shelf} className="w-full max-h-48 self-center" />
    </div>
  )
}
