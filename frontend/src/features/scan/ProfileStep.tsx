import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router'
import { ArrowsClockwise, ArrowsHorizontal, ArrowsVertical, Stack, Trash } from '@phosphor-icons/react'
import { api } from '../../lib/api'
import { placeNew } from '../../lib/placement'
import type { Level, ObjectSpec } from '../../lib/types'
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
  const [levels, setLevels] = useState<Level[]>(obj.profile?.levels ?? [])
  const [top, setTop] = useState<number[]>(obj.profile?.top ?? [])
  const [edited, setEdited] = useState(false)
  const [selLv, setSelLv] = useState<number | null>(null)

  const calc = useMutation({
    mutationFn: (v: { levels?: Level[]; count?: number; lr?: typeof flipLr; ud?: boolean }) => api.profile(obj.id, {
      side_flip_lr: (v.lr ?? flipLr) === 'auto' ? null : (v.lr ?? flipLr) === 'yes',
      side_flip_ud: v.ud ?? flipUd,
      calipers: { length: len, max_thickness: thick },
      levels: v.levels,
      level_count: v.count,
    }),
    onSuccess: (o) => {
      qc.setQueryData(['object', obj.id], o); qc.invalidateQueries({ queryKey: ['objects'] })
      setShown(null); setLevels(o.profile!.levels ?? []); setTop(o.profile!.top); setEdited(false)
    },
  })
  // gespeicherte Ebenen behalten; ohne Ebenen (ältere Objekte) neu erkennen
  useEffect(() => { calc.mutate({ levels: obj.profile?.levels ?? undefined }) }, []) // eslint-disable-line react-hooks/exhaustive-deps
  const setLv = useMutation({
    mutationFn: (l: Level[]) => api.setLevels(obj.id, l),
    onSuccess: (o) => {
      qc.setQueryData(['object', obj.id], o); qc.invalidateQueries({ queryKey: ['objects'] })
      calc.reset()
      setShown(o); setLevels(o.profile!.levels ?? []); setTop(o.profile!.top); setEdited(false)
    },
  })
  const [shown, setShown] = useState<ObjectSpec | null>(null)
  const commit = (l: Level[]) => setLv.mutate(l)
  const insertAt = (s: number) => {
    const i = levels.findIndex((q) => s >= q[0] && s < q[1])
    if (i < 0 || levels.length >= 8) return
    const [a, b, z] = levels[i]
    const lo = Math.max(a, s - 8), hi = Math.min(b, s + 8)
    const parts: Level[] = []
    if (lo - a >= 3) parts.push([a, lo, z])
    parts.push([lo - a >= 3 ? lo : a, hi > b - 3 ? b : hi, z])
    if (b - hi >= 3) parts.push([hi, b, z])
    commit([...levels.slice(0, i), ...parts, ...levels.slice(i + 1)])
    setSelLv(i + (lo - a >= 3 ? 1 : 0))
  }
  const splitLevel = (i: number) => {
    const [a, b, z] = levels[i]
    if (b - a < 8 || levels.length >= 8) return
    const m = Math.round(a + b) / 2
    commit([...levels.slice(0, i), [a, m, z], [m, b, z], ...levels.slice(i + 1)])
    setSelLv(i + 1)
  }
  const removeLevel = (i: number) => {
    if (levels.length < 2) return
    // Abschnitt geht an den Nachbarn mit der tieferen Ebene (Werkzeug bleibt sicher frei)
    const left = i > 0 ? levels[i - 1] : null, right = i < levels.length - 1 ? levels[i + 1] : null
    const toLeft = left && (!right || left[2] <= right[2])
    const next = levels.map((q) => [...q] as Level)
    if (toLeft) next[i - 1][1] = levels[i][1]
    else next[i + 1][0] = levels[i][0]
    next.splice(i, 1)
    commit(next)
    setSelLv(null)
  }
  const nLevels = levels.length

  const o = calc.data ?? shown ?? obj
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
              <ProfileView obj={o} levels={levels} top={top} sel={selLv} onSelect={setSelLv} onInsert={insertAt}
                onChange={(q) => { setLevels(q); setEdited(true) }} onCommit={commit} />
            ) : <div className="skeleton h-80" />}
            {calc.isError && <Msg kind="err">{errText(calc.error)}</Msg>}
            <div className="flex flex-wrap gap-4 text-sm" style={{ color: 'var(--ink-2)' }}>
              <span className="inline-flex items-center gap-2"><span className="swatch" style={{ background: 'var(--blue)' }} /> Ebenen des Taschenbodens</span>
              <span className="inline-flex items-center gap-2"><span className="swatch" style={{ border: '1px dashed var(--ink-3)' }} /> gemessene Unterseite</span>
              <span className="inline-flex items-center gap-2"><span className="swatch" style={{ background: 'var(--green)' }} /> liegt hier auf</span>
              <span className="inline-flex items-center gap-2"><span className="swatch" style={{ background: 'var(--accent)' }} /> Oberseite (nur Gesamtdicke)</span>
              <span className="inline-flex items-center gap-2"><span className="swatch" style={{ background: 'color-mix(in srgb, var(--err) 25%, transparent)' }} /> ergänzt (verdeckt)</span>
            </div>
            <div className="hint mt-0">
              Jede Ebene liegt auf dem tiefsten Punkt ihres Abschnitts: das Werkzeug liegt auf allen Ebenen auf und kann nicht wippen.
              Blaue Ebene hoch/runter ziehen = Höhe ändern, Griff am Absatz ziehen = Grenze verschieben,
              Doppelklick auf eine Ebene = dort eigene Ebene (± 8 mm) anlegen, z. B. für den Griffschutz.
              Liegt das Werkzeug nur auf einer Seite auf (grüne Striche), die Ebene unter dem freien Teil anheben.
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
              <h2 className="sect flex items-center gap-2"><Stack size={16} /> Ebenen im Taschenboden</h2>
              <div className="hint mt-0">Meist reichen 2 bis 3 (Zange: Backen, Griffschutz, Griffe). Wahl erkennt die Ebenen neu.</div>
              <Segmented value={nLevels} onChange={(n) => { setSelLv(null); calc.mutate({ count: n }) }}
                options={[1, 2, 3, 4, 5].map((n) => ({ value: n, label: String(n) }))} />
              <button className="btn btn-sm justify-self-start" onClick={() => { setSelLv(null); calc.mutate({}) }} disabled={calc.isPending}>
                <ArrowsClockwise size={14} /> Automatisch erkennen</button>
              {selLv !== null && levels[selLv] && (
                <div className="grid gap-2 p-2 rounded" style={{ background: 'var(--surface-2)' }}>
                  <div className="text-sm font-medium">Ebene {selLv + 1}: {levels[selLv][0].toFixed(0)} bis {levels[selLv][1].toFixed(0)} mm</div>
                  <NumberField label="Höhe über tiefster Ebene" value={levels[selLv][2]} step={0.5}
                    onChange={(v) => commit(levels.map((q, j) => (j === selLv ? [q[0], q[1], v] as Level : q)))} />
                  <div className="flex gap-2 flex-wrap">
                    <button className="btn btn-sm" onClick={() => splitLevel(selLv)} disabled={nLevels >= 8 || levels[selLv][1] - levels[selLv][0] < 8}>Teilen</button>
                    <button className="btn btn-sm" onClick={() => removeLevel(selLv)} disabled={nLevels < 2}><Trash size={14} /> Entfernen</button>
                  </div>
                </div>
              )}
            </section>
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
                <button className="btn btn-sm" onClick={() => calc.mutate({ levels: levels.length ? levels : undefined })} disabled={calc.isPending}><ArrowsClockwise size={14} /> Übernehmen</button>
              </div>
            </section>
          </aside>
        </div>
      </div>
      {bar({
        status: calc.isPending || setLv.isPending ? 'Speichere Profil …' : edited ? 'Profil geändert …' : o.profile ? 'Objekt ist gespeichert.' : '',
        secondary: <button className="btn" onClick={() => nav('/')}>Zur Bibliothek</button>,
        primary: { label: 'Einlage anlegen', onClick: () => newInsert.mutate(), disabled: !o.profile || calc.isPending, busy: newInsert.isPending },
      })}
    </>
  )
}

/** Draufsicht + Seitenprofil. Die Unterseite besteht aus wenigen waagrechten Ebenen (Taschenboden
 *  in Stufen). Ebene ziehen = Höhe ändern, Absatz ziehen = Grenze verschieben, Klick = auswählen.
 *  Grau: gemessene Unterseite, grüne Striche: dort liegt das Werkzeug auf. Höhe überhöht. */
function ProfileView({ obj, levels, top, sel, onSelect, onChange, onCommit, onInsert }: {
  obj: ObjectSpec; levels: Level[]; top: number[]; sel: number | null
  onSelect: (i: number | null) => void; onInsert: (s: number) => void
  onChange: (l: Level[]) => void; onCommit: (l: Level[]) => void
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
  const meas = p.measured ?? []
  const tMax = Math.max(...top, ...levels.map((q) => q[2]), 1)
  const zMin = Math.min(0, ...levels.map((q) => q[2]), ...meas.map((z) => z))
  const hTop = (ymax - ymin) * k + 2 * PAD + 18
  const hProf = (tMax - zMin) * kz + 2 * PAD + 26
  const svg = useRef<SVGSVGElement>(null)
  const drag = useRef<{ kind: 'level' | 'edge'; i: number; moved: boolean; off: number } | null>(null)
  const live = useRef(levels)
  live.current = levels
  const [hover, setHover] = useState<number | null>(null)

  const x = (s: number) => PAD + s * k
  const yTop = (y: number) => PAD + (ymax - y) * k
  const yProf = (z: number) => hTop + PAD + 10 + (tMax - z) * kz
  const toModel = (e: React.PointerEvent) => {
    const r = svg.current!.getBoundingClientRect()
    const sx = (e.clientX - r.left) * (W / r.width), sy = (e.clientY - r.top) * ((hTop + hProf) / r.height)
    return { s: (sx - PAD) / k, z: tMax - (sy - hTop - PAD - 10) / kz }
  }
  const floorAt = (s: number) => (levels.find((q) => s >= q[0] && s < q[1]) ?? levels[levels.length - 1])[2]
  const topPath = top.map((z, i) => `${i ? 'L' : 'M'}${x(p.s[i]).toFixed(1)},${yProf(z).toFixed(1)}`).join('')
  const measPath = meas.map((z, i) => `${i ? 'L' : 'M'}${x(p.s[i]).toFixed(1)},${yProf(z).toFixed(1)}`).join('')
  const stepPath = levels.map(([a, b, z], i) => `${i ? 'L' : 'M'}${x(a).toFixed(1)},${yProf(z).toFixed(1)}L${x(b).toFixed(1)},${yProf(z).toFixed(1)}`).join('')
  const area = `${topPath}${[...levels].reverse().map(([a, b, z]) => `L${x(b).toFixed(1)},${yProf(z).toFixed(1)}L${x(a).toFixed(1)},${yProf(z).toFixed(1)}`).join('')}Z`
  // Auflagepunkte: gemessene Unterseite berührt den Boden (± 0,8 mm)
  const touch: [number, number][] = []
  meas.forEach((z, i) => {
    if (obj.profile_missing?.[i]) return
    const s = p.s[i]
    if (z - floorAt(s) < 0.8) {
      if (touch.length && touch[touch.length - 1][1] >= s - p.ds * 1.5) touch[touch.length - 1][1] = s
      else touch.push([s, s])
    }
  })

  const onMove = (e: React.PointerEvent) => {
    const d = drag.current; if (!d) return
    const m = toModel(e)
    const cur = live.current
    let next = cur
    if (d.kind === 'level') {
      const nz = Math.max(-40, Math.min(80, Math.round((m.z - d.off) * 10) / 10))
      next = cur.map((q, j) => (j === d.i ? [q[0], q[1], nz] as Level : q))
    } else {
      // Grenze zwischen Ebene i und i+1
      const lo = cur[d.i][0] + 3, hi = cur[d.i + 1][1] - 3
      const ns = Math.min(hi, Math.max(lo, Math.round((m.s - d.off) * 2) / 2))
      next = cur.map((q, j) => (j === d.i ? [q[0], ns, q[2]] as Level : j === d.i + 1 ? [ns, q[1], q[2]] as Level : q))
    }
    if (next !== cur) d.moved = true
    live.current = next                 // sofort, sonst speichert das Loslassen den vorletzten Stand
    onChange(next)
  }
  const endDrag = () => {
    const d = drag.current
    if (!d) return
    drag.current = null
    if (d.moved) onCommit(live.current)
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
  const tTop = Math.max(...top)

  return (
    <div className="panel p-2 overflow-x-auto drafting">
      <svg ref={svg} viewBox={`0 0 ${W} ${hTop + hProf}`} className="w-full" style={{ minWidth: 560, touchAction: 'none' }}
        onPointerMove={onMove} onPointerUp={endDrag} onPointerLeave={endDrag} onContextMenu={(e) => e.preventDefault()}
        onPointerDown={(e) => { if (e.target === svg.current) onSelect(null) }}>
        <text x={PAD} y={16} fontSize={12} fontWeight={600} fill="var(--ink)">Draufsicht</text>
        <polygon points={contour.map(([cx, cy]) => `${x(cx).toFixed(1)},${yTop(cy).toFixed(1)}`).join(' ')}
          fill="var(--accent-soft)" stroke="var(--accent)" strokeWidth={1.5} />
        {levels.slice(1).map((q, i) => (
          <line key={'tl' + i} x1={x(q[0])} x2={x(q[0])} y1={yTop(ymax) - 4} y2={yTop(ymin) + 4} stroke="var(--blue)" strokeDasharray="3 4" opacity={0.7} />
        ))}
        {dim(x(0), x(L), hTop - 14, `${obj.length_mm.toFixed(1)} mm`)}

        <text x={PAD} y={hTop + 16} fontSize={12} fontWeight={600} fill="var(--ink)">Seitenprofil (Höhe {EX}-fach überhöht)</text>
        {runs.map(([a, b]) => (
          <rect key={a} x={x(p.s[a])} width={Math.max(2, x(p.s[b]) - x(p.s[a]))} y={yProf(tMax) - 4} height={(tMax - zMin) * kz + 8}
            fill="color-mix(in srgb, var(--err) 18%, transparent)" />
        ))}
        <path d={area} fill="color-mix(in srgb, var(--blue) 12%, transparent)" />
        <path d={topPath} fill="none" stroke="var(--accent)" strokeWidth={1.5} opacity={0.8} />
        {measPath && <path d={measPath} fill="none" stroke="var(--ink-2)" strokeWidth={1.6} strokeDasharray="4 3" />}
        <path d={stepPath} fill="none" stroke="var(--blue)" strokeWidth={1.4} opacity={0.6} pointerEvents="none" />
        {touch.map(([a, b], i) => (
          <line key={'t' + i} x1={x(a) - 1} x2={x(b) + 1} y1={yProf(floorAt((a + b) / 2)) + 5} y2={yProf(floorAt((a + b) / 2)) + 5}
            stroke="var(--green)" strokeWidth={4} strokeLinecap="round" pointerEvents="none" />
        ))}
        <g stroke="var(--ink-2)" fill="var(--ink-2)">
          <line x1={x(L) + 10} x2={x(L) + 10} y1={yProf(0)} y2={yProf(tTop)} />
          <text x={x(L) + 4} y={yProf(tTop) - 6} fontSize={12} textAnchor="end" stroke="none" className="num">{tTop.toFixed(1)} mm</text>
        </g>
        {/* Ebenen: breite Trefferfläche, senkrecht ziehbar */}
        {levels.map(([a, b, z], i) => {
          const on = sel === i || hover === i
          return (
            <g key={'lv' + i}>
              <line x1={x(a) + 3} x2={x(b) - 3} y1={yProf(z)} y2={yProf(z)} stroke="transparent" strokeWidth={18} style={{ cursor: 'ns-resize' }}
                onPointerEnter={() => setHover(i)} onPointerLeave={() => !drag.current && setHover(null)}
                onPointerDown={(e) => { e.stopPropagation(); capture(e); drag.current = { kind: 'level', i, moved: false, off: toModel(e).z - z }; onSelect(i) }}
                onDoubleClick={(e) => onInsert(Math.round(toModel(e as unknown as React.PointerEvent).s * 2) / 2)} />
              <line x1={x(a) + 2} x2={x(b) - 2} y1={yProf(z)} y2={yProf(z)} stroke="var(--blue)" strokeWidth={on ? 5 : 3.5} strokeLinecap="round" pointerEvents="none" />
              <g pointerEvents="none">
                <rect x={(x(a) + x(b)) / 2 - 38} y={yProf(z) + 9} width={76} height={18} rx={3} fill={on ? 'var(--ink)' : 'var(--surface)'} stroke="var(--line-2)" />
                <text x={(x(a) + x(b)) / 2} y={yProf(z) + 22} fontSize={11} textAnchor="middle" fill={on ? 'var(--paper)' : 'var(--ink)'} className="num">
                  {i + 1}: {z.toFixed(1)} mm</text>
              </g>
            </g>
          )
        })}
        {/* Absätze: waagrecht ziehbar */}
        {levels.slice(0, -1).map((q, i) => {
          const zHi = Math.max(q[2], levels[i + 1][2]), zLo = Math.min(q[2], levels[i + 1][2])
          return (
            <g key={'ed' + i} style={{ cursor: 'ew-resize' }}
              onPointerDown={(e) => { e.stopPropagation(); capture(e); drag.current = { kind: 'edge', i, moved: false, off: toModel(e).s - q[1] } }}>
              <line x1={x(q[1])} x2={x(q[1])} y1={yProf(zHi) - 6} y2={yProf(zLo) + 6} stroke="transparent" strokeWidth={16} />
              <line x1={x(q[1])} x2={x(q[1])} y1={yProf(zHi)} y2={yProf(zLo)} stroke="var(--blue)" strokeWidth={1.5} strokeDasharray="3 3" pointerEvents="none" />
              <rect x={x(q[1]) - 5} y={(yProf(zHi) + yProf(zLo)) / 2 - 9} width={10} height={18} rx={3} fill="var(--surface)" stroke="var(--blue)" strokeWidth={2} />
            </g>
          )
        })}
      </svg>
    </div>
  )
}
