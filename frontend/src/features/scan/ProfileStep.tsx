import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router'
import { api } from '../../lib/api'
import type { ObjectSpec } from '../../lib/types'
import { Msgs, NumberField, Segmented } from '../../components/ui'

const PAD = 24

export function ProfileStep({ obj }: { obj: ObjectSpec }) {
  const qc = useQueryClient()
  const nav = useNavigate()
  const [flipLr, setFlipLr] = useState<'auto' | 'no' | 'yes'>(
    obj.side_flip_lr === null ? 'auto' : obj.side_flip_lr ? 'yes' : 'no')
  const [flipUd, setFlipUd] = useState(obj.side_flip_ud)
  const [len, setLen] = useState(obj.calipers.length ?? 0)
  const [thick, setThick] = useState(obj.calipers.max_thickness ?? 0)
  const [name, setName] = useState(obj.name)
  const [bottom, setBottom] = useState<number[]>(obj.profile?.bottom ?? [])
  const [top, setTop] = useState<number[]>(obj.profile?.top ?? [])
  const [edited, setEdited] = useState(false)

  const calc = useMutation({
    mutationFn: (overrides?: boolean) => api.profile(obj.id, {
      side_flip_lr: flipLr === 'auto' ? null : flipLr === 'yes',
      side_flip_ud: flipUd,
      calipers: { length: len, max_thickness: thick },
      profile_overrides: overrides ? { bottom, top } : undefined,
    }),
    onSuccess: (o) => { qc.setQueryData(['object', obj.id], o); setBottom(o.profile!.bottom); setTop(o.profile!.top); setEdited(false) },
  })
  useEffect(() => { calc.mutate(false) }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const o = calc.data ?? obj
  const rename = async () => { if (name !== obj.name) { await api.renameObject(obj.id, name); qc.invalidateQueries({ queryKey: ['objects'] }) } }
  const newInsert = useMutation({
    mutationFn: async () => { await rename(); return api.createInsert({ name: `Einlage ${name}`, placements: [{ object_id: obj.id, x: 6, y: 6, rot_deg: 0, side_down: 'A' }] }) },
    onSuccess: (i) => nav(`/insert/${i.id}`),
  })

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_300px]">
      <div className="grid gap-3 min-w-0">
        {calc.isPending && !o.profile ? <div className="skeleton h-72" /> : o.profile && <ProfileView
          obj={o} bottom={bottom} top={top}
          onEdit={(b, t) => { setBottom(b); setTop(t); setEdited(true) }} />}
        {calc.isError && <div className="msg msg-err">{String(calc.error).replace('Error: ', '')}</div>}
        <Msgs items={o.warnings} />
        <div className="hint">
          Oben: Draufsicht. Unten: Seitenprofil (blau: Unterseite, orange: Oberseite) entlang der Länge. Die Punkte lassen sich ziehen, um das Profil manuell zu korrigieren.
          Rote Spalten wurden interpoliert.
        </div>
      </div>
      <aside className="panel p-3 grid gap-3 content-start">
        <label className="label">Name
          <input className="input mt-1" value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        <div className="num grid grid-cols-2 gap-x-3 text-sm">
          <span>Länge</span><b>{o.length_mm.toFixed(1)} mm</b>
          <span>Breite</span><b>{o.width_mm.toFixed(1)} mm</b>
          <span>Max. Dicke</span><b>{o.profile ? Math.max(...o.profile.top).toFixed(1) : '-'} mm</b>
          <span>Kippwinkel</span><b>{o.tilt_deg.toFixed(1)}°</b>
        </div>
        <div>
          <div className="label">Seitenfoto spiegeln (links/rechts)</div>
          <Segmented value={flipLr} onChange={setFlipLr}
            options={[{ value: 'auto', label: `Auto${o.flip_lr_used !== null && flipLr === 'auto' ? (o.flip_lr_used ? ' (ja)' : ' (nein)') : ''}` },
              { value: 'no', label: 'Nein' }, { value: 'yes', label: 'Ja' }]} />
        </div>
        <div>
          <div className="label">Unten beim Liegen</div>
          <Segmented value={flipUd ? 'b' : 'a'} onChange={(v) => setFlipUd(v === 'b')}
            options={[{ value: 'a', label: 'Bildunterseite' }, { value: 'b', label: 'Bildoberseite' }]} />
        </div>
        <NumberField label="Messschieber: Länge" value={len} onChange={setLen} min={0} hint="0 = nicht verwenden" />
        <NumberField label="Messschieber: max. Dicke" value={thick} onChange={setThick} min={0} hint="0 = nicht verwenden" />
        <button className="btn" onClick={() => calc.mutate(false)} disabled={calc.isPending}>Neu berechnen</button>
        <button className="btn" onClick={() => calc.mutate(true)} disabled={calc.isPending || !edited}>Manuelles Profil übernehmen</button>
        <hr className="hair w-full" />
        <button className="btn btn-primary justify-center" disabled={newInsert.isPending || !o.profile} onClick={() => newInsert.mutate()}>
          Speichern und Einlage anlegen
        </button>
        <button className="btn" onClick={async () => { await rename(); nav('/') }}>Speichern und zur Bibliothek</button>
      </aside>
    </div>
  )
}

function ProfileView({ obj, bottom, top, onEdit }: {
  obj: ObjectSpec; bottom: number[]; top: number[]; onEdit: (b: number[], t: number[]) => void
}) {
  const p = obj.profile!
  const W = 900
  const L = p.s[p.s.length - 1]
  const k = (W - 2 * PAD) / L
  const contour = obj.contour_mm
  const ys = contour.map((c) => c[1])
  const wTop = Math.max(...ys) - Math.min(...ys)
  const tMax = Math.max(...top, 1)
  const hTop = wTop * k + 2 * PAD
  const hProf = tMax * k + 2 * PAD
  const svg = useRef<SVGSVGElement>(null)
  const drag = useRef<{ curve: 'b' | 't'; i: number; y0: number; b0: number[]; t0: number[] } | null>(null)

  const x = (s: number) => PAD + s * k
  const yProf = (z: number) => hTop + PAD + (tMax - z) * k
  const ymin = Math.min(...ys), ymax = Math.max(...ys)
  const path = (arr: number[]) => arr.map((z, i) => `${i ? 'L' : 'M'}${x(p.s[i]).toFixed(1)},${yProf(z).toFixed(1)}`).join('')
  const area = useMemo(() => `${path(top)}${[...bottom].reverse().map((z, j) => `L${x(p.s[bottom.length - 1 - j]).toFixed(1)},${yProf(z).toFixed(1)}`).join('')}Z`,
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [top, bottom, k, tMax])
  const handles = [] as number[]
  for (let s = 0; s <= L + 1e-6; s += 10) handles.push(Math.min(Math.round(s / p.ds), p.s.length - 1))

  const onMove = (e: React.PointerEvent) => {
    const d = drag.current; if (!d) return
    const dz = -(e.clientY - d.y0) / (svg.current!.getBoundingClientRect().width / W) / k
    const b = [...d.b0], t = [...d.t0]
    const arr = d.curve === 'b' ? b : t
    const half = 12
    for (let j = -half; j <= half; j++) {
      const idx = d.i + j
      if (idx < 0 || idx >= arr.length) continue
      const wgt = 0.5 * (1 + Math.cos((Math.PI * j) / (half + 1)))
      arr[idx] = Math.max(0, arr[idx] + dz * wgt)
    }
    for (let q = 0; q < b.length; q++) if (b[q] > t[q]) { if (d.curve === 'b') b[q] = t[q]; else t[q] = b[q] }
    onEdit(b, t)
  }

  return (
    <div className="panel p-2 overflow-x-auto">
      <svg ref={svg} viewBox={`0 0 ${W} ${hTop + hProf}`} className="w-full" style={{ minWidth: 560, touchAction: 'none' }}
        onPointerMove={onMove} onPointerUp={() => (drag.current = null)} onPointerLeave={() => (drag.current = null)}>
        {/* 10-mm-Raster */}
        {Array.from({ length: Math.floor(L / 10) + 1 }, (_, i) => (
          <g key={i}>
            <line x1={x(i * 10)} x2={x(i * 10)} y1={PAD / 2} y2={hTop + hProf - PAD / 2} stroke="var(--grid)" strokeWidth={1} />
            <text x={x(i * 10)} y={hTop + hProf - 4} fontSize={9} textAnchor="middle" fill="var(--ink-3)" className="num">{i * 10}</text>
          </g>
        ))}
        <polygon points={contour.map(([cx, cy]) => `${x(cx).toFixed(1)},${(PAD + (ymax - cy) * k).toFixed(1)}`).join(' ')}
          fill="var(--accent-soft)" stroke="var(--accent)" strokeWidth={1.5} />
        <text x={PAD} y={12} fontSize={10} fill="var(--ink-2)">Draufsicht {obj.length_mm.toFixed(1)} x {(ymax - ymin).toFixed(1)} mm</text>
        <path d={area} fill="rgba(31,111,235,0.14)" />
        <path d={path(top)} fill="none" stroke="var(--accent)" strokeWidth={1.8} />
        <path d={path(bottom)} fill="none" stroke="#1f6feb" strokeWidth={1.8} />
        {(['b', 't'] as const).flatMap((curve) => handles.map((i) => (
          <circle key={curve + i} cx={x(p.s[i])} cy={yProf((curve === 'b' ? bottom : top)[i])} r={5}
            fill="var(--surface)" stroke={curve === 'b' ? '#1f6feb' : 'var(--accent)'} strokeWidth={2} style={{ cursor: 'ns-resize' }}
            onPointerDown={(e) => { (e.target as Element).setPointerCapture(e.pointerId); drag.current = { curve, i, y0: e.clientY, b0: bottom, t0: top } }} />
        )))}
      </svg>
    </div>
  )
}
