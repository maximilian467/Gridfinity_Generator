import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { api } from '../../lib/api'
import { Check, Msg, NumberField, errText } from '../../components/ui'
import type { InsertSpec } from '../../lib/types'
import { PLUG_MIN_H } from '../../lib/types'
import { binOuter } from '../../lib/binGrid'

const LIP_MIN_H = 7 + 3.8          // mit Stapelrand mindestens 1 U + Rand

/** Draufsicht des Blindstopfens mit Beschriftung (Schriftgröße wie im Backend: 30 % der kürzeren Seite, max. 8 mm). */
export function PlugSketch({ gx, gy, text, className }: { gx: number; gy: number; text: string; className?: string }) {
  const [ox, oy] = binOuter(gx, gy)
  const size = Math.min(8, Math.max(Math.round(0.3 * Math.min(ox, oy)), 3))
  return (
    <svg viewBox={`-2 -2 ${ox + 4} ${oy + 4}`} className={className} role="img" aria-label={`Blindstopfen ${gx} x ${gy}`}>
      <rect x={0} y={0} width={ox} height={oy} rx={3.75} fill="var(--surface-2)" stroke="var(--ink-3)" strokeWidth={0.8} />
      {Array.from({ length: gx - 1 }, (_, i) => <line key={'x' + i} x1={(i + 1) * 42} x2={(i + 1) * 42} y1={0} y2={oy} stroke="var(--line-2)" strokeWidth={0.4} strokeDasharray="1.5 2" />)}
      {Array.from({ length: gy - 1 }, (_, i) => <line key={'y' + i} y1={(i + 1) * 42} y2={(i + 1) * 42} x1={0} x2={ox} stroke="var(--line-2)" strokeWidth={0.4} strokeDasharray="1.5 2" />)}
      {text.trim() && <text x={ox / 2} y={oy / 2} textAnchor="middle" dominantBaseline="central" fontSize={size / 0.73}
        fontWeight={700} fill="var(--ink)" style={{ fontFamily: 'DejaVu Sans, Verdana, sans-serif' }}>{text.trim()}</text>}
    </svg>
  )
}

/** Formular "Neuer Blindstopfen": Raster, Höhe (auch sehr flach), optional Beschriftung. */
export function NewPlugForm({ projectId, onCreated, onCancel }: {
  projectId?: string | null; onCreated: (i: InsertSpec) => void; onCancel: () => void
}) {
  const [f, setF] = useState({ name: 'Blindstopfen', gx: 1, gy: 1, height: 7, lip: false, text: '' })
  const create = useMutation({
    mutationFn: () => api.createPlug({ name: f.name, grid_x: f.gx, grid_y: f.gy, height_mm: f.height, stacking_lip: f.lip,
      text: f.text, project_id: projectId ?? null }),
    onSuccess: onCreated,
  })
  const int = (v: number) => Math.min(Math.max(Math.round(v) || 1, 1), 12)
  return (
    <div className="panel p-3 grid gap-3 md:grid-cols-[minmax(0,1fr)_200px]">
      <div className="grid gap-2 content-start">
        <div className="hint mt-0">Verschließt freie Felder der Baseplate, damit nichts hineinfällt. Ohne Taschen und Fächer, die Höhe ist frei wählbar
          (ab {PLUG_MIN_H.toFixed(1).replace('.', ',')} mm){projectId ? ' und gilt auch im Projekt unabhängig von der Vorlage' : ''}. Beschriftung lässt sich später im Designer anpassen.</div>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          <label className="grid gap-1"><span className="label mb-0">Name</span>
            <input className="input" value={f.name} onChange={(e) => setF((q) => ({ ...q, name: e.target.value }))} /></label>
          <label className="grid gap-1"><span className="label mb-0">Beschriftung (optional)</span>
            <input className="input" value={f.text} maxLength={60} onChange={(e) => setF((q) => ({ ...q, text: e.target.value }))} placeholder="z. B. frei" /></label>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 items-end">
          <NumberField label="Breite" unit="E" step={1} min={1} max={12} value={f.gx} onChange={(v) => setF((q) => ({ ...q, gx: int(v) }))} />
          <NumberField label="Tiefe" unit="E" step={1} min={1} max={12} value={f.gy} onChange={(v) => setF((q) => ({ ...q, gy: int(v) }))} />
          <NumberField label="Gesamthöhe" step={0.5} min={PLUG_MIN_H} max={250} value={f.height}
            onChange={(v) => setF((q) => ({ ...q, height: Math.min(Math.max(v, PLUG_MIN_H), 250) }))} hint={f.lip ? 'inkl. Stapelrand' : 'ohne Schrift'} />
        </div>
        <div className="flex gap-1 flex-wrap items-center">
          {[PLUG_MIN_H, 7, 10, 14].map((h) => (
            <button key={h} className={`btn btn-sm ${f.height === h ? 'btn-on' : ''}`} onClick={() => setF((q) => ({ ...q, height: h }))}>
              {String(h).replace('.', ',')} mm{h === PLUG_MIN_H ? ' (flachste)' : ''}</button>
          ))}
        </div>
        <Check label="Stapelrand" checked={f.lip} onChange={(v) => setF((q) => ({ ...q, lip: v, height: v ? Math.max(q.height, LIP_MIN_H) : q.height }))} />
        {f.lip && <div className="hint mt-0">Mit Stapelrand ist der Stopfen mindestens {LIP_MIN_H.toFixed(1).replace('.', ',')} mm hoch.</div>}
        <div className="flex gap-2">
          <button className="btn btn-primary" onClick={() => create.mutate()} disabled={create.isPending}>Anlegen</button>
          <button className="btn" onClick={onCancel}>Abbrechen</button>
        </div>
        {create.isError && <Msg kind="err">{errText(create.error)}</Msg>}
      </div>
      <PlugSketch gx={f.gx} gy={f.gy} text={f.text} className="w-full max-h-48 self-center" />
    </div>
  )
}
