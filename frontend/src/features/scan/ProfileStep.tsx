import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router'
import { ArrowsClockwise, ArrowsHorizontal, ArrowsVertical } from '@phosphor-icons/react'
import { api } from '../../lib/api'
import { placeNew } from '../../lib/placement'
import type { ObjectSpec } from '../../lib/types'
import { BusyBar, Msg, Msgs, NumberField, Segmented, Stat, errText } from '../../components/ui'

const PAD = 28

/** Zeiger festhalten (wirft bei manchen Eingabegeräten/synthetischen Ereignissen) */
function capture(e: React.PointerEvent) {
  try { (e.target as Element).setPointerCapture(e.pointerId) } catch { /* egal */ }
}

interface BarProps {
  status?: ReactNode
  secondary?: ReactNode
  primary?: { label: string; onClick: () => void; disabled?: boolean; busy?: boolean }
}

export function ProfileStep({ o: obj, header, bar }: {
  o: ObjectSpec; i: number; header: (c: ReactNode) => ReactNode; bar: (p: BarProps) => ReactNode
}) {
  const qc = useQueryClient()
  const nav = useNavigate()
  const [flipLr, setFlipLr] = useState<'auto' | 'no' | 'yes'>(obj.side_flip_lr === null ? 'auto' : obj.side_flip_lr ? 'yes' : 'no')
  const [flipUd, setFlipUd] = useState(obj.side_flip_ud)
  const [len, setLen] = useState(obj.calipers.length ?? 0)
  const [thick, setThick] = useState(obj.calipers.max_thickness ?? 0)
  const [pts, setPts] = useState<number[][]>(obj.profile?.bottom_points ?? [])
  const [top, setTop] = useState<number[]>(obj.profile?.top ?? [])
  const [edited, setEdited] = useState(false)

  const calc = useMutation({
    mutationFn: (v: { points?: number[][]; lr?: typeof flipLr; ud?: boolean }) => api.profile(obj.id, {
      side_flip_lr: (v.lr ?? flipLr) === 'auto' ? null : (v.lr ?? flipLr) === 'yes',
      side_flip_ud: v.ud ?? flipUd,
      calipers: { length: len, max_thickness: thick },
      bottom_points: v.points,
    }),
    onSuccess: (o) => {
      qc.setQueryData(['object', obj.id], o); qc.invalidateQueries({ queryKey: ['objects'] })
      setPts(o.profile!.bottom_points ?? []); setTop(o.profile!.top); setEdited(false)
    },
  })
  // gespeicherte Handkorrektur behalten; nur ohne Stützpunkte neu erkennen
  useEffect(() => { calc.mutate({ points: obj.profile?.bottom_points ?? undefined }) }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const o = calc.data ?? obj
  const newInsert = useMutation({
    mutationFn: () => {
      const base = { clearance_xy: 1.5, clearance_end: 1.0, min_wall: 1.6, placements: [] } as unknown as import('../../lib/types').InsertSpec
      return api.createInsert({ name: `Einlage ${o.name}`, placements: [placeNew(base, {}, o)] })
    },
    onSuccess: (i) => nav(`/insert/${i.id}`),
  })
  const maxT = o.profile ? Math.max(...o.profile.top) : 0

  return (
    <>
      <div className="p-6 grid grid-cols-[minmax(0,1fr)] gap-5">
        {header('Aus beiden Umrissen entstehen die Maße und das Höhenprofil entlang der Länge. Perspektivische Verzerrung (Parallaxe) ist bereits herausgerechnet. Unten ist die Unterseite in der Lage, in der das Werkzeug später in der Tasche liegt.')}
        <div className="grid grid-cols-[minmax(0,1fr)] gap-5 xl:grid-cols-[minmax(0,1fr)_320px]">
          <div className="grid grid-cols-[minmax(0,1fr)] gap-3 content-start min-w-0">
            {calc.isPending && <BusyBar label="Berechne Kontur und Profil …" />}
            {o.profile ? (
              <ProfileView obj={o} pts={pts} top={top} onChange={(q) => { setPts(q); setEdited(true) }}
                onCommit={(q) => calc.mutate({ points: q })} />
            ) : <div className="skeleton h-80" />}
            {calc.isError && <Msg kind="err">{errText(calc.error)}</Msg>}
            <div className="flex flex-wrap gap-4 text-sm" style={{ color: 'var(--ink-2)' }}>
              <span className="inline-flex items-center gap-2"><span className="swatch" style={{ background: 'var(--blue)' }} /> Unterseite: bestimmt die Stufen im Taschenboden</span>
              <span className="inline-flex items-center gap-2"><span className="swatch" style={{ background: 'var(--accent)' }} /> Oberseite (nur Gesamtdicke)</span>
              <span className="inline-flex items-center gap-2"><span className="swatch" style={{ background: 'color-mix(in srgb, var(--err) 25%, transparent)' }} /> ergänzt (verdeckt)</span>
            </div>
            <div className="hint mt-0">
              Blaue Punkte ziehen = Unterseite anpassen (z. B. den Griffschutz tiefer setzen, damit das Werkzeug nicht wippt).
              Klick auf die blaue Linie = Punkt einfügen. Rechtsklick auf einen Punkt = löschen. Änderungen werden beim Loslassen gespeichert.
            </div>
            <Msgs items={o.warnings} />
          </div>

          <aside className="grid grid-cols-[minmax(0,1fr)] gap-4 content-start">
            <div className="grid grid-cols-2 gap-2">
              <Stat k="Länge" v={o.length_mm.toFixed(1)} unit="mm" />
              <Stat k="Breite" v={o.width_mm.toFixed(1)} unit="mm" />
              <Stat k="Max. Dicke" v={maxT.toFixed(1)} unit="mm" />
              <Stat k="Kippwinkel" v={o.tilt_deg.toFixed(1)} unit="°" />
            </div>

            <section className="grid grid-cols-[minmax(0,1fr)] gap-2">
              <h2 className="sect flex items-center gap-2"><ArrowsHorizontal size={16} /> Seitenfoto spiegeln</h2>
              <div className="hint mt-0">Stimmt die Spitze im Profil nicht mit der Spitze in der Draufsicht überein, hier umschalten.</div>
              <Segmented value={flipLr} onChange={(v) => { setFlipLr(v); calc.mutate({ lr: v }) }}
                options={[{ value: 'auto', label: `Automatisch${flipLr === 'auto' && o.flip_lr_used !== null ? (o.flip_lr_used ? ' (gespiegelt)' : '') : ''}` },
                  { value: 'no', label: 'Normal' }, { value: 'yes', label: 'Gespiegelt' }]} />
            </section>
            <section className="grid grid-cols-[minmax(0,1fr)] gap-2">
              <h2 className="sect flex items-center gap-2"><ArrowsVertical size={16} /> Welche Seite liegt unten?</h2>
              <div className="hint mt-0">Bestimmt, welche Kante später auf dem Taschenboden aufliegt.</div>
              <Segmented value={flipUd ? 'b' : 'a'} onChange={(v) => { setFlipUd(v === 'b'); calc.mutate({ ud: v === 'b' }) }}
                options={[{ value: 'a', label: 'Wie im Foto unten' }, { value: 'b', label: 'Umgedreht' }]} />
            </section>
            <section className="grid grid-cols-[minmax(0,1fr)] gap-2">
              <h2 className="sect">Mit Messschieber nachmessen (optional)</h2>
              <div className="hint mt-0">Gemessene Werte skalieren Kontur und Profil. 0 = nicht verwenden.</div>
              <div className="grid grid-cols-2 gap-2">
                <NumberField label="Länge" value={len} onChange={setLen} min={0} />
                <NumberField label="Max. Dicke" value={thick} onChange={setThick} min={0} />
              </div>
              <div className="flex gap-2 flex-wrap">
                <button className="btn btn-sm" onClick={() => calc.mutate({ points: pts.length ? pts : undefined })} disabled={calc.isPending}><ArrowsClockwise size={14} /> Übernehmen</button>
                <button className="btn btn-sm" onClick={() => calc.mutate({})} disabled={calc.isPending} title="Unterseite wieder aus dem Foto erkennen (verwirft Handkorrekturen)">Profil neu erkennen</button>
              </div>
            </section>
          </aside>
        </div>
      </div>
      {bar({
        status: calc.isPending ? 'Speichere Profil …' : edited ? 'Profil geändert …' : o.profile ? 'Objekt ist gespeichert.' : '',
        secondary: <button className="btn" onClick={() => nav('/')}>Zur Bibliothek</button>,
        primary: { label: 'Einlage anlegen', onClick: () => newInsert.mutate(), disabled: !o.profile || calc.isPending, busy: newInsert.isPending },
      })}
    </>
  )
}

function interp(xs: number[], zs: number[], s: number): number {
  if (s <= xs[0]) return zs[0]
  for (let i = 1; i < xs.length; i++) if (s <= xs[i]) return zs[i - 1] + (zs[i] - zs[i - 1]) * (s - xs[i - 1]) / Math.max(1e-9, xs[i] - xs[i - 1])
  return zs[zs.length - 1]
}

/** Draufsicht + Seitenprofil. Die Unterseite (liegt in der Tasche auf) ist ein Polygonzug aus
 *  Stützpunkten: ziehen = verschieben, Klick auf die Linie = Punkt einfügen, Rechtsklick = löschen.
 *  Die Oberseite ist nur Referenz (zählt für die Gesamtdicke). Höhe zur Bearbeitung überhöht. */
function ProfileView({ obj, pts, top, onChange, onCommit }: {
  obj: ObjectSpec; pts: number[][]; top: number[]
  onChange: (p: number[][]) => void; onCommit: (p: number[][]) => void
}) {
  const p = obj.profile!
  const W = 1000
  const L = p.s[p.s.length - 1]
  const k = (W - 2 * PAD) / L
  const EX = 2                                   // Überhöhung der Höhenachse
  const kz = k * EX
  const contour = obj.contour_mm
  const ys = contour.map((c) => c[1])
  const ymin = Math.min(...ys), ymax = Math.max(...ys)
  const tMax = Math.max(...top, ...pts.map((q) => q[1]), 1)
  const zMin = Math.min(0, ...pts.map((q) => q[1]))
  const hTop = (ymax - ymin) * k + 2 * PAD + 18
  const hProf = (tMax - zMin) * kz + 2 * PAD + 26
  const svg = useRef<SVGSVGElement>(null)
  const [active, setActive] = useState<number | null>(null)
  const drag = useRef<{ i: number } | null>(null)
  const live = useRef(pts)
  live.current = pts

  const x = (s: number) => PAD + s * k
  const yTop = (y: number) => PAD + (ymax - y) * k
  const yProf = (z: number) => hTop + PAD + 10 + (tMax - z) * kz
  const toModel = (e: React.PointerEvent) => {
    const r = svg.current!.getBoundingClientRect()
    const sx = (e.clientX - r.left) * (W / r.width), sy = (e.clientY - r.top) * ((hTop + hProf) / r.height)
    return { s: (sx - PAD) / k, z: tMax - (sy - hTop - PAD - 10) / kz }
  }
  const sorted = [...pts].sort((a, b) => a[0] - b[0])
  const xs = sorted.map((q) => q[0]), zs = sorted.map((q) => q[1])
  const bottomPath = sorted.map(([s, z], i) => `${i ? 'L' : 'M'}${x(s).toFixed(1)},${yProf(z).toFixed(1)}`).join('')
  const topPath = top.map((z, i) => `${i ? 'L' : 'M'}${x(p.s[i]).toFixed(1)},${yProf(z).toFixed(1)}`).join('')
  const area = `${topPath}${[...sorted].reverse().map(([s, z]) => `L${x(s).toFixed(1)},${yProf(z).toFixed(1)}`).join('')}Z`

  const onMove = (e: React.PointerEvent) => {
    const d = drag.current; if (!d) return
    const m = toModel(e)
    const cur = [...live.current].sort((a, b) => a[0] - b[0])
    const i = d.i
    const lo = i === 0 ? 0 : cur[i - 1][0] + 0.5, hi = i === cur.length - 1 ? L : cur[i + 1][0] - 0.5
    const isEnd = i === 0 || i === cur.length - 1
    const ns = isEnd ? cur[i][0] : Math.min(hi, Math.max(lo, Math.round(m.s * 2) / 2))
    const nz = Math.max(-40, Math.round(m.z * 10) / 10)          // darf unter den tiefsten Punkt
    const next = cur.map((q, j) => (j === i ? [ns, nz] : q))
    live.current = next                 // sofort, sonst speichert das Loslassen den vorletzten Stand
    onChange(next)
  }
  const endDrag = () => { if (drag.current) { drag.current = null; onCommit(live.current) } }
  const insertAt = (e: React.PointerEvent) => {
    const m = toModel(e)
    if (m.s <= 0 || m.s >= L) return
    const s = Math.round(m.s * 2) / 2
    const next = [...sorted, [s, Math.round(interp(xs, zs, s) * 10) / 10]].sort((a, b) => a[0] - b[0])
    onChange(next)
    const i = next.findIndex((q) => q[0] === s)
    drag.current = { i }; setActive(i)
    ;capture(e)
  }
  const missing = obj.profile_missing ?? []
  const runs: [number, number][] = []
  missing.forEach((mm, i) => { if (mm) { if (runs.length && runs[runs.length - 1][1] === i - 1) runs[runs.length - 1][1] = i; else runs.push([i, i]) } })
  const dim = (x1: number, x2: number, y: number, label: string) => (
    <g stroke="var(--ink-2)" fill="var(--ink-2)">
      <line x1={x1} x2={x2} y1={y} y2={y} />
      <line x1={x1} x2={x1} y1={y - 5} y2={y + 5} /><line x1={x2} x2={x2} y1={y - 5} y2={y + 5} />
      <rect x={(x1 + x2) / 2 - 34} y={y - 9} width={68} height={18} fill="var(--surface)" stroke="none" />
      <text x={(x1 + x2) / 2} y={y + 4} fontSize={12} textAnchor="middle" stroke="none" className="num">{label}</text>
    </g>
  )

  return (
    <div className="panel p-2 overflow-x-auto drafting">
      <svg ref={svg} viewBox={`0 0 ${W} ${hTop + hProf}`} className="w-full" style={{ minWidth: 560, touchAction: 'none' }}
        onPointerMove={onMove} onPointerUp={endDrag} onPointerLeave={endDrag} onContextMenu={(e) => e.preventDefault()}>
        <text x={PAD} y={16} fontSize={12} fontWeight={600} fill="var(--ink)">Draufsicht</text>
        <polygon points={contour.map(([cx, cy]) => `${x(cx).toFixed(1)},${yTop(cy).toFixed(1)}`).join(' ')}
          fill="var(--accent-soft)" stroke="var(--accent)" strokeWidth={1.5} />
        {dim(x(0), x(L), hTop - 14, `${obj.length_mm.toFixed(1)} mm`)}

        <text x={PAD} y={hTop + 16} fontSize={12} fontWeight={600} fill="var(--ink)">Seitenprofil (Höhe {EX}-fach überhöht)</text>
        {runs.map(([a, b]) => (
          <rect key={a} x={x(p.s[a])} width={Math.max(2, x(p.s[b]) - x(p.s[a]))} y={yProf(tMax) - 4} height={tMax * kz + 8}
            fill="color-mix(in srgb, var(--err) 18%, transparent)" />
        ))}
        <line x1={x(0)} x2={x(L)} y1={yProf(0)} y2={yProf(0)} stroke="var(--line-2)" strokeDasharray="4 4" />
        <path d={area} fill="color-mix(in srgb, var(--blue) 14%, transparent)" />
        <path d={topPath} fill="none" stroke="var(--accent)" strokeWidth={1.5} opacity={0.8} />
        {/* breite, unsichtbare Trefferfläche: Klick auf die Unterseite fügt einen Punkt ein */}
        <path d={bottomPath} fill="none" stroke="transparent" strokeWidth={14} style={{ cursor: 'copy' }} onPointerDown={insertAt} />
        <path d={bottomPath} fill="none" stroke="var(--blue)" strokeWidth={2.2} pointerEvents="none" />
        <g stroke="var(--ink-2)" fill="var(--ink-2)">
          <line x1={x(L) + 10} x2={x(L) + 10} y1={yProf(0)} y2={yProf(Math.max(...top))} />
          <text x={x(L) + 4} y={yProf(Math.max(...top)) - 6} fontSize={12} textAnchor="end" stroke="none" className="num">{Math.max(...top).toFixed(1)} mm</text>
        </g>
        {sorted.map(([s, z], i) => (
          <g key={i}>
            <circle cx={x(s)} cy={yProf(z)} r={6.5} fill={active === i ? 'var(--blue)' : 'var(--surface)'} stroke="var(--blue)" strokeWidth={2.2}
              style={{ cursor: 'grab' }}
              onPointerEnter={() => setActive(i)} onPointerLeave={() => !drag.current && setActive(null)}
              onPointerDown={(e) => {
                e.stopPropagation()
                if ((e.button === 2 || e.altKey) && i > 0 && i < sorted.length - 1) {
                  const next = sorted.filter((_, j) => j !== i); onChange(next); onCommit(next); setActive(null); return
                }
                ;capture(e); drag.current = { i }; setActive(i)
              }} />
            {active === i && (
              <g pointerEvents="none">
                <rect x={x(s) - 34} y={yProf(z) + 10} width={68} height={18} rx={3} fill="var(--ink)" />
                <text x={x(s)} y={yProf(z) + 23} fontSize={11} textAnchor="middle" fill="var(--paper)" className="num">{z.toFixed(1)} mm</text>
              </g>
            )}
          </g>
        ))}
      </svg>
    </div>
  )
}
