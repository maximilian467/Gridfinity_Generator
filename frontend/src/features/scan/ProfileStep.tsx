import { useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router'
import { ArrowsClockwise, ArrowsHorizontal, ArrowsVertical } from '@phosphor-icons/react'
import { api } from '../../lib/api'
import { placeNew } from '../../lib/placement'
import type { ObjectSpec } from '../../lib/types'
import { BusyBar, Msg, Msgs, NumberField, Segmented, Stat, errText } from '../../components/ui'

const PAD = 28

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
  const [bottom, setBottom] = useState<number[]>(obj.profile?.bottom ?? [])
  const [top, setTop] = useState<number[]>(obj.profile?.top ?? [])
  const [edited, setEdited] = useState(false)

  const calc = useMutation({
    mutationFn: (v: { overrides?: boolean; lr?: typeof flipLr; ud?: boolean }) => api.profile(obj.id, {
      side_flip_lr: (v.lr ?? flipLr) === 'auto' ? null : (v.lr ?? flipLr) === 'yes',
      side_flip_ud: v.ud ?? flipUd,
      calipers: { length: len, max_thickness: thick },
      profile_overrides: v.overrides ? { bottom, top } : undefined,
    }),
    onSuccess: (o) => {
      qc.setQueryData(['object', obj.id], o); qc.invalidateQueries({ queryKey: ['objects'] })
      setBottom(o.profile!.bottom); setTop(o.profile!.top); setEdited(false)
    },
  })
  useEffect(() => { calc.mutate({}) }, []) // eslint-disable-line react-hooks/exhaustive-deps

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
              <ProfileView obj={o} bottom={bottom} top={top} onEdit={(b, t) => { setBottom(b); setTop(t); setEdited(true) }} />
            ) : <div className="skeleton h-80" />}
            {calc.isError && <Msg kind="err">{errText(calc.error)}</Msg>}
            <div className="flex flex-wrap gap-4 text-sm" style={{ color: 'var(--ink-2)' }}>
              <span className="inline-flex items-center gap-2"><span className="swatch" style={{ background: 'var(--accent)' }} /> Oberseite</span>
              <span className="inline-flex items-center gap-2"><span className="swatch" style={{ background: 'var(--blue)' }} /> Unterseite (liegt auf)</span>
              <span className="inline-flex items-center gap-2"><span className="swatch" style={{ background: 'color-mix(in srgb, var(--err) 25%, transparent)' }} /> ergänzt (verdeckt)</span>
              <span>Runde Punkte lassen sich ziehen, um das Profil von Hand zu korrigieren.</span>
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
                <button className="btn btn-sm" onClick={() => calc.mutate({})} disabled={calc.isPending}><ArrowsClockwise size={14} /> Neu berechnen</button>
                <button className="btn btn-sm" onClick={() => calc.mutate({ overrides: true })} disabled={calc.isPending || !edited}>Handkorrektur übernehmen</button>
              </div>
            </section>
          </aside>
        </div>
      </div>
      {bar({
        status: calc.isPending ? 'Berechne …' : edited ? 'Profil von Hand geändert, noch nicht übernommen.' : o.profile ? 'Objekt ist gespeichert.' : '',
        secondary: <button className="btn" onClick={() => nav('/')}>Zur Bibliothek</button>,
        primary: { label: 'Einlage anlegen', onClick: () => newInsert.mutate(), disabled: !o.profile || calc.isPending, busy: newInsert.isPending },
      })}
    </>
  )
}

function ProfileView({ obj, bottom, top, onEdit }: {
  obj: ObjectSpec; bottom: number[]; top: number[]; onEdit: (b: number[], t: number[]) => void
}) {
  const p = obj.profile!
  const W = 1000
  const L = p.s[p.s.length - 1]
  const k = (W - 2 * PAD) / L
  const contour = obj.contour_mm
  const ys = contour.map((c) => c[1])
  const ymin = Math.min(...ys), ymax = Math.max(...ys)
  const tMax = Math.max(...top, 1)
  const hTop = (ymax - ymin) * k + 2 * PAD + 18
  const hProf = tMax * k + 2 * PAD + 18
  const svg = useRef<SVGSVGElement>(null)
  const drag = useRef<{ curve: 'b' | 't'; i: number; y0: number; b0: number[]; t0: number[] } | null>(null)

  const x = (s: number) => PAD + s * k
  const yTop = (y: number) => PAD + (ymax - y) * k
  const yProf = (z: number) => hTop + PAD + (tMax - z) * k
  const path = (arr: number[]) => arr.map((z, i) => `${i ? 'L' : 'M'}${x(p.s[i]).toFixed(1)},${yProf(z).toFixed(1)}`).join('')
  const area = useMemo(() => `${path(top)}${[...bottom].reverse().map((z, j) => `L${x(p.s[bottom.length - 1 - j]).toFixed(1)},${yProf(z).toFixed(1)}`).join('')}Z`,
    [top, bottom, k, tMax]) // eslint-disable-line react-hooks/exhaustive-deps
  const handles: number[] = []
  for (let s = 0; s <= L + 1e-6; s += 10) handles.push(Math.min(Math.round(s / p.ds), p.s.length - 1))
  const missing = obj.profile_missing ?? []
  const runs: [number, number][] = []
  missing.forEach((m, i) => { if (m) { if (runs.length && runs[runs.length - 1][1] === i - 1) runs[runs.length - 1][1] = i; else runs.push([i, i]) } })

  const onMove = (e: React.PointerEvent) => {
    const d = drag.current; if (!d) return
    const dz = -(e.clientY - d.y0) / (svg.current!.getBoundingClientRect().width / W) / k
    const b = [...d.b0], t = [...d.t0]
    const arr = d.curve === 'b' ? b : t
    const half = 12
    for (let j = -half; j <= half; j++) {
      const idx = d.i + j
      if (idx < 0 || idx >= arr.length) continue
      arr[idx] = Math.max(0, arr[idx] + dz * 0.5 * (1 + Math.cos((Math.PI * j) / (half + 1))))
    }
    for (let q = 0; q < b.length; q++) if (b[q] > t[q]) { if (d.curve === 'b') b[q] = t[q]; else t[q] = b[q] }
    onEdit(b, t)
  }
  const dim = (x1: number, x2: number, y: number, label: string) => (
    <g stroke="var(--ink-2)" fill="var(--ink-2)">
      <line x1={x1} x2={x2} y1={y} y2={y} />
      <line x1={x1} x2={x1} y1={y - 5} y2={y + 5} /><line x1={x2} x2={x2} y1={y - 5} y2={y + 5} />
      <polygon points={`${x1},${y} ${x1 + 8},${y - 3} ${x1 + 8},${y + 3}`} stroke="none" />
      <polygon points={`${x2},${y} ${x2 - 8},${y - 3} ${x2 - 8},${y + 3}`} stroke="none" />
      <rect x={(x1 + x2) / 2 - 34} y={y - 9} width={68} height={18} fill="var(--surface)" stroke="none" />
      <text x={(x1 + x2) / 2} y={y + 4} fontSize={12} textAnchor="middle" stroke="none" className="num">{label}</text>
    </g>
  )

  return (
    <div className="panel p-2 overflow-x-auto drafting">
      <svg ref={svg} viewBox={`0 0 ${W} ${hTop + hProf}`} className="w-full" style={{ minWidth: 560, touchAction: 'none' }}
        onPointerMove={onMove} onPointerUp={() => (drag.current = null)} onPointerLeave={() => (drag.current = null)}>
        <text x={PAD} y={16} fontSize={12} fontWeight={600} fill="var(--ink)">Draufsicht</text>
        <polygon points={contour.map(([cx, cy]) => `${x(cx).toFixed(1)},${yTop(cy).toFixed(1)}`).join(' ')}
          fill="var(--accent-soft)" stroke="var(--accent)" strokeWidth={1.5} />
        {dim(x(0), x(L), hTop - 14, `${obj.length_mm.toFixed(1)} mm`)}

        <text x={PAD} y={hTop + 16} fontSize={12} fontWeight={600} fill="var(--ink)">Seitenprofil</text>
        {runs.map(([a, b]) => (
          <rect key={a} x={x(p.s[a])} width={Math.max(2, x(p.s[b]) - x(p.s[a]))} y={hTop + PAD - 4} height={tMax * k + 8}
            fill="color-mix(in srgb, var(--err) 18%, transparent)" />
        ))}
        <line x1={x(0)} x2={x(L)} y1={yProf(0)} y2={yProf(0)} stroke="var(--line-2)" strokeDasharray="4 4" />
        <path d={area} fill="color-mix(in srgb, var(--blue) 14%, transparent)" />
        <path d={path(top)} fill="none" stroke="var(--accent)" strokeWidth={2} />
        <path d={path(bottom)} fill="none" stroke="var(--blue)" strokeWidth={2} />
        <g stroke="var(--ink-2)" fill="var(--ink-2)">
          <line x1={x(L) + 10} x2={x(L) + 10} y1={yProf(0)} y2={yProf(tMax)} />
          <text x={x(L) + 4} y={yProf(tMax) - 6} fontSize={12} textAnchor="end" stroke="none" className="num">{tMax.toFixed(1)} mm</text>
        </g>
        {(['b', 't'] as const).flatMap((curve) => handles.map((i) => (
          <circle key={curve + i} cx={x(p.s[i])} cy={yProf((curve === 'b' ? bottom : top)[i])} r={5.5}
            fill="var(--surface)" stroke={curve === 'b' ? 'var(--blue)' : 'var(--accent)'} strokeWidth={2} style={{ cursor: 'ns-resize' }}
            onPointerDown={(e) => { (e.target as Element).setPointerCapture(e.pointerId); drag.current = { curve, i, y0: e.clientY, b0: bottom, t0: top } }} />
        )))}
      </svg>
    </div>
  )
}
