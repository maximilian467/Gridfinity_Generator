import { lazy, Suspense, useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useParams } from 'react-router'
import { ArrowClockwise, ArrowsClockwise, CheckCircle, Cube, MagicWand, Plus, Rows, Scan, SignOut, Trash, XCircle } from '@phosphor-icons/react'
import { api } from '../../lib/api'
import type { BaseplateSpec, CloneData, CloneInsert, InsertTemplate, ProjectSpec, TemplateField } from '../../lib/types'
import { FIELD_LABELS } from '../../lib/types'
import { BusyBar, Check, Empty, Msg, NumberField, Segmented, Silhouette, errText } from '../../components/ui'
import { PartColorsEdit } from '../../components/ColorPick'
import { PlateBuild, PlateSettings, toggleCells, usePlatePlan } from '../baseplate/Baseplate'
import { PITCH, PlateEditor } from '../baseplate/PlateEditor'

const Clone3D = lazy(() => import('./Clone3D').then((m) => ({ default: m.Clone3D })))

type Tab = 'drawer' | 'tools' | 'template' | 'plate'

export function ProjectPage() {
  const { id = '' } = useParams()
  const loaded = useQuery({ queryKey: ['project', id], queryFn: () => api.project(id), staleTime: Infinity })
  if (loaded.isPending) return <div className="p-6"><div className="skeleton h-96 max-w-[1400px] mx-auto" /></div>
  if (loaded.isError) return <div className="p-6"><Msg kind="err">Projekt nicht gefunden.</Msg></div>
  return <ProjectInner key={id} initial={loaded.data} />
}

function ProjectInner({ initial }: { initial: ProjectSpec }) {
  const qc = useQueryClient()
  const nav = useNavigate()
  const [p, setP] = useState<ProjectSpec>(initial)
  const [tab, setTab] = useState<Tab>('drawer')
  const patch = (q: Partial<ProjectSpec>) => setP((s) => ({ ...s, ...q }))
  const clone = useQuery({ queryKey: ['clone', p.id], queryFn: () => api.clone(p.id) })
  const refreshClone = () => { qc.invalidateQueries({ queryKey: ['clone', p.id] }); qc.invalidateQueries({ queryKey: ['inserts'] }); qc.invalidateQueries({ queryKey: ['objects'] }) }

  // Autosave (Name, Schublade, Vorlage). Platzierungen speichert der Server selbst (place/arrange).
  const first = useRef(true)
  const [saveState, setSaveState] = useState<'saved' | 'pending' | 'error'>('saved')
  useEffect(() => {
    if (first.current) { first.current = false; return }
    setSaveState('pending')
    const t = setTimeout(() => {
      api.project(p.id).then((cur) => api.saveProject({ ...p, placements: cur.placements }))
        .then((saved) => { setSaveState('saved'); qc.setQueryData(['project', p.id], saved); refreshClone(); qc.invalidateQueries({ queryKey: ['projects'] }) })
        .catch(() => setSaveState('error'))
    }, 700)
    return () => clearTimeout(t)
  }, [p.name, p.drawer, p.template, p.drawer_h, p.notes]) // eslint-disable-line react-hooks/exhaustive-deps

  const del = useMutation({ mutationFn: () => api.deleteProject(p.id), onSuccess: () => { qc.invalidateQueries({ queryKey: ['projects'] }); nav('/?view=projects') } })
  const data = clone.data
  const placed = data?.inserts.filter((i) => i.placed).length ?? 0

  return (
    <div className="max-w-[1500px] mx-auto px-4 py-5 grid gap-4">
      <header className="flex flex-wrap items-center gap-3">
        <input className="input text-xl font-semibold tracking-tight" style={{ width: 'min(420px, 100%)' }} value={p.name}
          onChange={(e) => patch({ name: e.target.value })} aria-label="Projektname" />
        <span className="chip num">{p.drawer.drawer_x} x {p.drawer.drawer_y} mm</span>
        {data && <span className="chip num">{placed} / {data.inserts.length} Einlagen in der Schublade</span>}
        {data && data.inserts.some((i) => i.placed) && (
          <span className={`chip ${data.heights_equal ? 'chip-ok' : 'chip-warn'}`}>
            {data.heights_equal ? <><CheckCircle size={14} /> alle gleich hoch</> : <><XCircle size={14} /> unterschiedlich hoch</>}
          </span>
        )}
        <span className={`chip ${saveState === 'error' ? 'chip-err' : saveState === 'saved' ? 'chip-ok' : ''}`}>
          {saveState === 'saved' ? 'Gespeichert' : saveState === 'pending' ? 'Speichere …' : 'Nicht gespeichert'}</span>
        <div className="flex-1" />
        <Segmented value={tab} onChange={setTab} options={[
          { value: 'drawer', label: 'Schublade' }, { value: 'tools', label: 'Werkzeuge & Einlagen' },
          { value: 'template', label: 'Vorlage' }, { value: 'plate', label: 'Baseplate' }]} />
      </header>
      {clone.isError && <Msg kind="err">{errText(clone.error)}</Msg>}
      {data?.warnings.map((w) => <Msg key={w} kind="warn">{w}</Msg>)}

      {data && !data.heights_equal && data.inserts.some((i) => i.placed) && (() => {
        const h = Math.ceil(Math.max(...data.inserts.filter((i) => i.total_height).map((i) => i.total_height!)))
        return (
          <Msg kind="warn">Die Einlagen sind unterschiedlich hoch.
            <button className="btn btn-sm ml-2" onClick={() => patch({ template: { ...p.template, height_mm: h } })}>Alle auf {h} mm angleichen</button>
            <span className="hint"> (Vorlage: feste Gesamthöhe; eigene Höhen einzelner Einlagen bleiben)</span>
          </Msg>
        )
      })()}
      {tab === 'drawer' && <DrawerTab p={p} data={data} busy={clone.isFetching} refresh={refreshClone} />}
      {tab === 'tools' && <ToolsTab p={p} data={data} refresh={refreshClone} />}
      {tab === 'template' && <TemplateTab p={p} setTemplate={(t) => patch({ template: t })} />}
      {tab === 'plate' && <PlateTab p={p} patch={patch} />}

      <div className="flex justify-end">
        <button className="btn btn-sm btn-quiet" onClick={() => confirm(`Projekt "${p.name}" löschen? Einlagen und Werkzeuge bleiben erhalten.`) && del.mutate()}>
          <Trash size={14} /> Projekt löschen</button>
      </div>
    </div>
  )
}

/** Belegte Zellen aller platzierten Einlagen (außer except) */
function occupied(data: CloneData, except?: string): Set<string> {
  const s = new Set<string>()
  for (const i of data.inserts) {
    if (!i.placed || i.id === except || !i.gx || !i.gy) continue
    const [w, h] = i.placed.rot === 0 ? [i.gx, i.gy] : [i.gy, i.gx]
    for (let a = i.placed.ix; a < i.placed.ix + w; a++) for (let b = i.placed.iy; b < i.placed.iy + h; b++) s.add(`${a},${b}`)
  }
  return s
}

function firstFit(data: CloneData, ins: CloneInsert): { ix: number; iy: number; rot: 0 | 90 } | null {
  const occ = occupied(data, ins.id)
  const act = new Set(data.plan.active.map(([a, b]) => `${a},${b}`))
  for (const rot of [0, 90] as const) {
    const [w, h] = rot === 0 ? [ins.gx!, ins.gy!] : [ins.gy!, ins.gx!]
    for (let iy = 0; iy + h <= data.plan.cells_y; iy++) for (let ix = 0; ix + w <= data.plan.cells_x; ix++) {
      let ok = true
      for (let a = ix; a < ix + w && ok; a++) for (let b = iy; b < iy + h && ok; b++) ok = act.has(`${a},${b}`) && !occ.has(`${a},${b}`)
      if (ok) return { ix, iy, rot }
    }
  }
  return null
}

function DrawerTab({ p, data, busy, refresh }: { p: ProjectSpec; data: CloneData | undefined; busy: boolean; refresh: () => void }) {
  const [view, setView] = useState<'2d' | '3d'>('2d')
  const [sel, setSel] = useState<string | null>(null)
  const [msg, setMsg] = useState<{ kind: 'warn' | 'err' | 'ok'; text: string } | null>(null)
  const nav = useNavigate()
  const place = useMutation({
    mutationFn: (v: { id: string; pl: { ix: number; iy: number; rot: 0 | 90 } | null }) =>
      api.place(p.id, v.id, v.pl ? { insert_id: v.id, ...v.pl } : null),
    onSuccess: () => { setMsg(null); refresh() },
    onError: (e) => { setMsg({ kind: 'err', text: errText(e) }); refresh() },
  })
  const arrange = useMutation({
    mutationFn: (mode: 'all' | 'missing') => api.arrange(p.id, mode),
    onSuccess: (r) => {
      const t = [r.left_out.length ? `Passt nicht mehr hinein: ${r.left_out_names.join(', ')}. Diese Einlagen liegen bei "Nicht in der Schublade"; zum Tauschen eine andere herausnehmen und die gewünschte aufs Raster ziehen.` : 'Alle Einlagen angeordnet.']
      if (r.unfinished_names?.length) t.push(`Nicht angeordnet, weil das Werkzeug noch nicht fertig gescannt ist: ${r.unfinished_names.join(', ')}.`)
      setMsg({ kind: r.left_out.length || r.unfinished_names?.length ? 'warn' : 'ok', text: t.join(' ') })
      refresh()
    },
  })
  const gen = useMutation({
    mutationFn: () => api.generate(p.id),
    onSuccess: (r) => {
      const parts = [`${r.created.length} Einlage(n) nach der Vorlage erzeugt.`]
      if (r.skipped.length) parts.push(`Noch nicht fertig gescannt: ${r.skipped.join(', ')}.`)
      if (r.unfinished_names?.length) parts.push(`Nicht angeordnet (unfertig): ${r.unfinished_names.join(', ')}.`)
      if (r.left_out_names?.length) parts.push(`Passt nicht hinein: ${r.left_out_names.join(', ')}.`)
      setMsg({ kind: r.left_out_names?.length || r.skipped.length ? 'warn' : 'ok', text: parts.join(' ') })
      refresh()
    },
  })
  const selected = data?.inserts.find((i) => i.id === sel)
  const out = data?.inserts.filter((i) => !i.placed) ?? []
  const inside = data?.inserts.filter((i) => i.placed) ?? []

  return (
    <div className="grid gap-4 lg:grid-cols-[300px_minmax(0,1fr)]">
      <aside className="panel p-3 grid gap-3 content-start">
        <div className="grid gap-2">
          <button className="btn btn-primary justify-center" onClick={() => gen.mutate()} disabled={gen.isPending}>
            <MagicWand size={16} /> Fehlende Einlagen erzeugen</button>
          <div className="hint mt-0">Für jedes Werkzeug im Projekt ohne Einlage wird eine Einlage nach der Vorlage erzeugt und eingeordnet.</div>
          <button className="btn justify-center" onClick={() => confirm('Alle Einlagen neu anordnen? Von Hand gesetzte Positionen gehen verloren.') && arrange.mutate('all')} disabled={arrange.isPending}>
            <Rows size={16} /> Alles neu anordnen</button>
          {(gen.isPending || arrange.isPending) && <BusyBar />}
        </div>
        {msg && <Msg kind={msg.kind}>{msg.text}</Msg>}
        {selected && selected.placed && (
          <section className="grid gap-2">
            <h3 className="sect">{selected.name}</h3>
            <div className="num hint mt-0">{selected.gx} x {selected.gy} Einheiten · {selected.total_height?.toFixed(1)} mm hoch</div>
            <div className="flex flex-wrap gap-2">
              <button className="btn btn-sm" onClick={() => place.mutate({ id: selected.id, pl: { ...selected.placed!, rot: selected.placed!.rot === 0 ? 90 : 0 } })}>
                <ArrowsClockwise size={14} /> Drehen</button>
              <button className="btn btn-sm" onClick={() => { place.mutate({ id: selected.id, pl: null }); setSel(null) }}><SignOut size={14} /> Herausnehmen</button>
              <button className="btn btn-sm" onClick={() => nav(`/insert/${selected.id}`)}><Cube size={14} /> Bearbeiten</button>
            </div>
          </section>
        )}
        <section className="grid gap-1">
          <h3 className="sect">Nicht in der Schublade ({out.length})</h3>
          {!out.length && <div className="hint mt-0">Alle Einlagen liegen in der Schublade.</div>}
          {out.map((i) => (
            <div key={i.id} className="flex items-center gap-2 text-sm" draggable={!i.error}
              onDragStart={(e) => { e.dataTransfer.setData('text/insert', i.id); e.dataTransfer.effectAllowed = 'move' }}
              style={{ cursor: i.error ? 'default' : 'grab' }} title={i.error ? i.error : 'Aufs Raster ziehen oder "Einsetzen"'}>
              <span className="flex-1 truncate">{i.name}{i.gx ? <span className="num" style={{ color: 'var(--ink-2)' }}> · {i.gx}x{i.gy}</span> : null}</span>
              {i.error ? <span className="chip chip-warn text-xs" title={i.error}>unfertig</span> : (
                <button className="btn btn-sm" disabled={!data} onClick={() => {
                  const f = data && firstFit(data, i)
                  if (f) place.mutate({ id: i.id, pl: f })
                  else setMsg({ kind: 'warn', text: `Kein Platz für ${i.name}. Erst eine andere Einlage herausnehmen.` })
                }}>Einsetzen</button>
              )}
            </div>
          ))}
        </section>
        <section className="grid gap-1">
          <h3 className="sect">In der Schublade ({inside.length})</h3>
          {inside.map((i) => (
            <button key={i.id} className={`btn btn-sm justify-start ${sel === i.id ? 'btn-on' : ''}`} onClick={() => setSel(i.id)}>
              <span className="truncate">{i.name}</span><span className="num ml-auto" style={{ color: 'var(--ink-2)' }}>{i.total_height?.toFixed(1)} mm</span>
            </button>
          ))}
        </section>
      </aside>
      <section className="grid gap-3 content-start min-w-0">
        <div className="flex items-center gap-2">
          <Segmented value={view} onChange={setView} options={[{ value: '2d', label: 'Anordnen (2D)' }, { value: '3d', label: 'Digitaler Klon (3D)' }]} />
          {busy && <div className="w-40"><BusyBar /></div>}
        </div>
        {!data ? <div className="skeleton" style={{ height: 480 }} /> : view === '2d' ? (
          <>
            <div className="panel p-3">
              <DrawerView p={p} data={data} sel={sel} onSelect={setSel}
                onDrop={(id, pl) => place.mutate({ id, pl })} />
            </div>
            <div className="hint mt-0">Einlage anklicken zum Auswählen, ziehen zum Verschieben (rastet auf 42-mm-Zellen ein). Einlagen von links ("Nicht in der Schublade") lassen sich direkt aufs Raster ziehen. Belegte oder abgewählte Zellen lehnt die Schublade ab.</div>
          </>
        ) : (
          <Suspense fallback={<div className="skeleton" style={{ height: 560 }} />}><Clone3D data={data} /></Suspense>
        )}
      </section>
    </div>
  )
}

function DrawerView({ p, data, sel, onSelect, onDrop }: {
  p: ProjectSpec; data: CloneData; sel: string | null; onSelect: (id: string) => void
  onDrop: (id: string, pl: { ix: number; iy: number; rot: 0 | 90 }) => void
}) {
  const wrap = useRef<HTMLDivElement>(null)
  const [drag, setDrag] = useState<{ id: string; dx: number; dy: number; x: number; y: number } | null>(null)
  const P = data.plan
  const toMm = (e: { clientX: number; clientY: number }) => {
    const svg = wrap.current?.querySelector('svg')
    if (!svg) return null
    const pt = svg.createSVGPoint(); pt.x = e.clientX; pt.y = e.clientY
    const q = pt.matrixTransform(svg.getScreenCTM()!.inverse())
    return { x: q.x, y: p.drawer.drawer_y - q.y }
  }
  useEffect(() => {
    if (!drag) return
    const mv = (e: PointerEvent) => { const m = toMm(e); if (m) setDrag((d) => d && { ...d, x: m.x, y: m.y }) }
    const up = () => {
      setDrag((d) => {
        if (d) {
          const ins = data.inserts.find((i) => i.id === d.id)
          if (ins?.placed) {
            const ix = Math.round((d.x - d.dx - P.origin[0]) / PITCH), iy = Math.round((d.y - d.dy - P.origin[1]) / PITCH)
            if (ix !== ins.placed.ix || iy !== ins.placed.iy) onDrop(d.id, { ix: Math.max(0, ix), iy: Math.max(0, iy), rot: ins.placed.rot })
          }
        }
        return null
      })
    }
    window.addEventListener('pointermove', mv); window.addEventListener('pointerup', up)
    return () => { window.removeEventListener('pointermove', mv); window.removeEventListener('pointerup', up) }
  }, [drag?.id]) // eslint-disable-line react-hooks/exhaustive-deps

  // Einlage aus der Liste "Nicht in der Schublade" aufs Raster ziehen: die Mitte landet unter dem Zeiger
  const onDropNew = (e: React.DragEvent) => {
    const id = e.dataTransfer.getData('text/insert')
    const ins = data.inserts.find((i) => i.id === id)
    const m = toMm(e)
    if (!ins || !ins.gx || !m) return
    e.preventDefault()
    const ix = Math.round((m.x - P.origin[0]) / PITCH - ins.gx / 2), iy = Math.round((m.y - P.origin[1]) / PITCH - ins.gy! / 2)
    onDrop(id, { ix: Math.max(0, ix), iy: Math.max(0, iy), rot: 0 })
  }
  return (
    <div ref={wrap} onDragOver={(e) => { if (e.dataTransfer.types.includes('text/insert')) e.preventDefault() }} onDrop={onDropNew}>
      <PlateEditor drawer={[p.drawer.drawer_x, p.drawer.drawer_y]} plan={P} disabled={p.drawer.disabled ?? []} editable={false} height="min(68vh, 640px)">
        {data.inserts.filter((i) => i.placed && i.gx).map((i) => {
          const [w, h] = i.placed!.rot === 0 ? [i.gx!, i.gy!] : [i.gy!, i.gx!]
          let x = P.origin[0] + i.placed!.ix * PITCH, y = P.origin[1] + i.placed!.iy * PITCH
          if (drag?.id === i.id) { x = drag.x - drag.dx; y = drag.y - drag.dy }
          const on = sel === i.id
          return (
            <g key={i.id} style={{ cursor: 'grab' }} onPointerDown={(e) => {
              e.stopPropagation(); onSelect(i.id)
              const m = toMm(e); if (m) setDrag({ id: i.id, dx: m.x - x, dy: m.y - y, x: m.x, y: m.y })
            }}>
              <rect x={x + 0.6} y={y + 0.6} width={w * PITCH - 1.2} height={h * PITCH - 1.2} rx={4}
                fill={`color-mix(in srgb, ${i.colors.pocket} ${on ? 45 : 28}%, var(--surface))`}
                stroke={on ? 'var(--accent)' : i.colors.body} strokeWidth={on ? 2.5 : 1.5} opacity={drag?.id === i.id ? 0.8 : 1} />
              {i.tools?.map((t, k) => (
                <g key={k} transform={`translate(${x + 0.25 + (i.placed!.rot === 90 ? i.layout!.outer[1] : 0)} ${y + 0.25}) rotate(${i.placed!.rot})`}>
                  <polygon points={t.contour.filter((_, q) => q % 3 === 0).map(([a, b]) => `${a},${b}`).join(' ')}
                    transform={`translate(${t.x} ${t.y}) rotate(${t.rot_deg})`} fill={i.colors.body} opacity={0.75} />
                </g>
              ))}
              <text x={x + 5} y={-(y + h * PITCH - 12)} transform="scale(1 -1)" fontSize={9} fill="var(--ink)" pointerEvents="none">{i.name}</text>
            </g>
          )
        })}
      </PlateEditor>
    </div>
  )
}

function ToolsTab({ p, data, refresh }: { p: ProjectSpec; data: CloneData | undefined; refresh: () => void }) {
  const nav = useNavigate()
  const objects = useQuery({ queryKey: ['objects', 'mine'], queryFn: () => api.objects() })
  const inserts = useQuery({ queryKey: ['inserts', 'mine'], queryFn: () => api.inserts() })
  const mine = (objects.data ?? []).filter((o) => o.project_id === p.id)
  const others = (objects.data ?? []).filter((o) => o.project_id !== p.id && o.profile)
  const otherIns = (inserts.data ?? []).filter((i) => i.project_id !== p.id)
  const withInsert = new Set((inserts.data ?? []).filter((i) => i.project_id === p.id).flatMap((i) => i.placements.map((q) => q.object_id)))
  const done = () => { refresh(); objects.refetch(); inserts.refetch() }
  const insOf = (oid: string) => (data?.inserts ?? []).filter((i) => i.tools?.some((t) => t.object_id === oid)
    || (inserts.data ?? []).some((q) => q.id === i.id && q.placements.some((pl) => pl.object_id === oid)))
  const scan = useMutation({
    mutationFn: async () => { const o = await api.createObject('Neues Werkzeug'); await api.assign(p.id, 'object', o.id); return o },
    onSuccess: (o) => nav(`/scan/${o.id}`),
  })
  const assign = useMutation({ mutationFn: (v: { kind: 'insert' | 'object'; id: string; member: boolean }) => api.assign(p.id, v.kind, v.id, v.member), onSuccess: done })
  const gen = useMutation({ mutationFn: (oid: string) => api.generate(p.id, [oid], true), onSuccess: done })
  return (
    <div className="grid gap-6">
      <section className="grid gap-3">
        <div className="flex items-center gap-3 flex-wrap">
          <h2 className="text-lg font-semibold">Werkzeuge im Projekt</h2>
          <div className="flex-1" />
          {others.length > 0 && (
            <select className="input" style={{ width: 240 }} value="" onChange={(e) => e.target.value && assign.mutate({ kind: 'object', id: e.target.value, member: true })} aria-label="Vorhandenes Werkzeug hinzufügen">
              <option value="">+ Vorhandenes Werkzeug …</option>
              {others.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
            </select>
          )}
          <button className="btn btn-primary" onClick={() => scan.mutate()} disabled={scan.isPending}><Scan size={16} /> Werkzeug scannen</button>
        </div>
        {!mine.length ? <Empty title="Noch keine Werkzeuge">Werkzeug scannen oder ein vorhandenes hinzufügen. Nach dem Scan entsteht die Einlage automatisch nach der Vorlage.</Empty> : (
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3">
            {mine.map((o) => (
              <article key={o.id} className="panel p-3 grid gap-2">
                <Silhouette contour={o.contour_mm} className="w-full h-24" />
                <div className="font-medium truncate">{o.name}</div>
                <div className="num text-xs" style={{ color: 'var(--ink-2)' }}>{o.profile ? `${o.length_mm.toFixed(0)} x ${o.width_mm.toFixed(0)} mm` : 'noch nicht fertig gescannt'}</div>
                {insOf(o.id).map((i) => (
                  <button key={i.id} className={`chip text-xs cursor-pointer w-fit ${i.placed ? 'chip-ok' : ''}`} onClick={() => nav(`/insert/${i.id}`)}
                    title={i.placed ? 'Einlage liegt in der Schublade' : 'Einlage liegt noch nicht in der Schublade'}>
                    <Cube size={12} /> {i.gx ? `${i.gx}x${i.gy}, ${i.total_height?.toFixed(0)} mm` : 'Einlage'}{i.placed ? '' : ' · draußen'}
                  </button>
                ))}
                <div className="flex gap-1 flex-wrap">
                  <button className="btn btn-sm" onClick={() => nav(`/scan/${o.id}`)}>Scan</button>
                  {o.profile && !withInsert.has(o.id) && <button className="btn btn-sm" onClick={() => gen.mutate(o.id)} disabled={gen.isPending}><Plus size={14} /> Einlage</button>}
                  <button className="btn btn-sm btn-quiet" title="Aus dem Projekt nehmen" onClick={() => assign.mutate({ kind: 'object', id: o.id, member: false })}><SignOut size={14} /></button>
                </div>
              </article>
            ))}
          </div>
        )}
      </section>
      <section className="grid gap-3">
        <div className="flex items-center gap-3 flex-wrap">
          <h2 className="text-lg font-semibold">Einlagen im Projekt</h2>
          <div className="flex-1" />
          {otherIns.length > 0 && (
            <select className="input" style={{ width: 240 }} value="" onChange={(e) => e.target.value && confirm('Die Einlage übernimmt dann die Einstellungen der Projektvorlage. Fortfahren?') && assign.mutate({ kind: 'insert', id: e.target.value, member: true })} aria-label="Vorhandene Einlage hinzufügen">
              <option value="">+ Vorhandene Einlage …</option>
              {otherIns.map((i) => <option key={i.id} value={i.id}>{i.name}</option>)}
            </select>
          )}
        </div>
        <div className="panel divide-y" style={{ borderColor: 'var(--line)' }}>
          {!data?.inserts.length && <div className="p-3 hint mt-0">Noch keine Einlagen.</div>}
          {data?.inserts.map((i) => (
            <div key={i.id} className="flex items-center gap-3 px-3 py-2 flex-wrap">
              <span className="swatch" style={{ background: i.colors.pocket, border: `3px solid ${i.colors.body}` }} />
              <button className="font-medium text-left flex-1 truncate bg-transparent border-0 cursor-pointer p-0" style={{ color: 'var(--ink)', font: 'inherit', fontWeight: 500 }}
                onClick={() => nav(`/insert/${i.id}`)}>{i.name}</button>
              {i.overrides.length > 0 && <span className="chip chip-warn text-xs" title={i.overrides.map((f) => FIELD_LABELS[f as TemplateField] ?? f).join(', ')}>{i.overrides.length} eigene Einstellung(en)</span>}
              <span className="num text-xs" style={{ color: 'var(--ink-2)' }}>{i.gx ? `${i.gx} x ${i.gy} · ${i.total_height?.toFixed(1)} mm` : i.error}</span>
              <span className={`chip text-xs ${i.placed ? 'chip-ok' : ''}`}>{i.placed ? 'in der Schublade' : 'draußen'}</span>
              <button className="btn btn-sm btn-quiet" title="Aus dem Projekt nehmen" onClick={() => assign.mutate({ kind: 'insert', id: i.id, member: false })}><SignOut size={14} /></button>
            </div>
          ))}
        </div>
      </section>
    </div>
  )
}

function TemplateTab({ p, setTemplate }: { p: ProjectSpec; setTemplate: (t: InsertTemplate) => void }) {
  const t = p.template
  const up = (q: Partial<InsertTemplate>) => setTemplate({ ...t, ...q })
  return (
    <div className="grid gap-4 md:grid-cols-3">
      <section className="panel p-4 grid gap-3 content-start">
        <h2 className="sect">Größe</h2>
        <div className="hint mt-0">Gilt für alle Einlagen des Projekts. Einlagen, in denen du einen Wert bewusst überschrieben hast, behalten ihren Wert.</div>
        <Check label="Höhe automatisch (je Einlage, dann evtl. unterschiedlich hoch)" checked={t.height_mm === null} onChange={(v) => up({ height_mm: v ? null : 32 })} />
        {t.height_mm !== null && <NumberField label="Gesamthöhe aller Einlagen" value={t.height_mm} step={1} min={10} onChange={(v) => up({ height_mm: v })} hint="gleiche Höhe für alle, inkl. Stapelrand" />}
        <label className="grid gap-1">
          <span className="label mb-0">Werkzeug sinkt ein <span className="num">{Math.round(t.sink * 100)} %</span></span>
          <input type="range" min={30} max={100} step={5} value={Math.round(t.sink * 100)} onChange={(e) => up({ sink: +e.target.value / 100 })} />
        </label>
        <Check label="Stapelrand" checked={t.stacking_lip} onChange={(v) => up({ stacking_lip: v })} />
        <Check label="Magnetlöcher" checked={t.magnets} onChange={(v) => up({ magnets: v })} />
      </section>
      <section className="panel p-4 grid gap-3 content-start">
        <h2 className="sect">Spiel und Greifmulde</h2>
        <NumberField label="Spiel seitlich" value={t.clearance_xy} step={0.1} min={0} max={10} onChange={(v) => up({ clearance_xy: v })} />
        <NumberField label="Zusatzspiel an den Enden" value={t.clearance_end} step={0.1} min={0} onChange={(v) => up({ clearance_end: v })} />
        <NumberField label="Abstand Boden zu Werkzeug" value={t.clearance_z} step={0.1} min={0} onChange={(v) => up({ clearance_z: v })} />
        <NumberField label="Kontur glätten" value={t.smooth_mm} step={0.5} min={0} max={10} onChange={(v) => up({ smooth_mm: v })} />
        <Check label="Greifmulde automatisch setzen" checked={t.auto_grip} onChange={(v) => up({ auto_grip: v })} />
        <div className="grid grid-cols-2 gap-2">
          <NumberField label="Mulde Breite" value={t.grip_width} step={1} min={4} onChange={(v) => up({ grip_width: v })} />
          <NumberField label="Überstand" value={t.grip_overhang} step={1} min={0} onChange={(v) => up({ grip_overhang: v })} />
          <NumberField label="Tiefe unter Werkzeug" value={t.grip_depth_below} step={1} min={0} onChange={(v) => up({ grip_depth_below: v })} />
          <NumberField label="Min. Boden" value={t.floor_min} step={0.1} min={0.4} onChange={(v) => up({ floor_min: v })} />
        </div>
      </section>
      <section className="panel p-4 grid gap-3 content-start">
        <h2 className="sect">Farben</h2>
        <PartColorsEdit value={t.color_hex} onChange={(v) => up({ color_hex: v })} />
      </section>
    </div>
  )
}

function PlateTab({ p, patch }: { p: ProjectSpec; patch: (q: Partial<ProjectSpec>) => void }) {
  const plan = usePlatePlan(p.drawer)
  const setDrawer = (q: Partial<BaseplateSpec>) => patch({ drawer: { ...p.drawer, ...q } })
  const pl = plan.data
  const used = useMemo(() => pl ? `${pl.cells_x} x ${pl.cells_y} Zellen (${pl.active.length} aktiv) · Rand ${pl.rest_x} / ${pl.rest_y} mm · ${pl.tiles.length} Kacheln` : '', [pl])
  return (
    <div className="grid gap-4 md:grid-cols-[320px_minmax(0,1fr)]">
      <section className="panel p-4 grid gap-3 content-start">
        <h2 className="sect">Schublade</h2>
        <PlateSettings spec={p.drawer} patch={setDrawer} />
        <NumberField label="Innenhöhe der Schublade (optional)" value={p.drawer_h ?? 0} step={1} min={0}
          onChange={(v) => patch({ drawer_h: v > 0 ? v : null })} hint="0 = unbekannt; sonst Warnung, wenn eine Einlage höher ist" />
        <PlateBuild spec={p.drawer} disabled={plan.isError} />
      </section>
      <section className="grid gap-3 content-start">
        {plan.isError && <Msg kind="err">{errText(plan.error)}</Msg>}
        <div className="panel p-3">
          <PlateEditor drawer={[p.drawer.drawer_x, p.drawer.drawer_y]} plan={pl} disabled={p.drawer.disabled ?? []}
            onToggle={(cells, on) => setDrawer({ disabled: toggleCells(p.drawer.disabled ?? [], cells, on) })} />
        </div>
        <div className="hint mt-0">Zellen anklicken oder darüberziehen, um sie wegzulassen (z. B. eine Ecke oder die Mitte). Farbige Umrisse = Kacheln, die einzeln aufs Druckbett passen.</div>
        <div className="num text-sm" style={{ color: 'var(--ink-2)' }}>{used}</div>
        <div className="flex gap-2">
          <button className="btn btn-sm" onClick={() => setDrawer({ disabled: [] })} disabled={!p.drawer.disabled?.length}><ArrowClockwise size={14} /> Alle Zellen aktiv</button>
        </div>
      </section>
    </div>
  )
}
