import { lazy, Suspense, useEffect, useMemo, useRef, useState } from 'react'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useParams } from 'react-router'
import { ArrowClockwise, DownloadSimple, Plus, Trash } from '@phosphor-icons/react'
import { api } from '../../lib/api'
import type { Compartment, GripRecess, InsertSpec, ObjectSpec } from '../../lib/types'
import { Check, Field, Msgs, NumberField, Segmented } from '../../components/ui'
import { Editor2D } from './Editor2D'
import type { Sel } from './Editor2D'

const Preview3D = lazy(() => import('./Preview3D').then((m) => ({ default: m.Preview3D })))

function useDebounced<T>(v: T, ms: number): T {
  const [d, setD] = useState(v)
  useEffect(() => { const t = setTimeout(() => setD(v), ms); return () => clearTimeout(t) }, [v, ms])
  return d
}

const OUTPUT_LABELS: [string, string, string][] = [
  ['3mf', '3MF für Bambu Studio / Orca', 'einlage.3mf'],
  ['stl', 'STL (ein Körper)', 'einlage.stl'],
  ['parts_zip', 'STL je Farbteil (ZIP)', 'einlage_teile.zip'],
  ['step', 'STEP mit Farben', 'einlage.step'],
  ['fit_test', 'Passform-Test (STL)', 'passform_test.stl'],
  ['3mf_plain', '3MF einfach (Ersatz)', 'einlage_einfach.3mf'],
]

export function Designer() {
  const { id = '' } = useParams()
  const loaded = useQuery({ queryKey: ['insert', id], queryFn: () => api.insert(id), staleTime: Infinity })
  if (loaded.isPending) return <div className="p-6"><div className="skeleton h-96 max-w-[1400px] mx-auto" /></div>
  if (loaded.isError) return <div className="p-6"><div className="msg msg-err">Einlage nicht gefunden.</div></div>
  return <DesignerInner key={id} initial={loaded.data} />
}

function DesignerInner({ initial }: { initial: InsertSpec }) {
  const nav = useNavigate()
  const qc = useQueryClient()
  const [spec, setSpec] = useState<InsertSpec>(initial)
  const [sel, setSel] = useState<Sel>(null)
  const [tab, setTab] = useState<'layout' | '3d'>('layout')
  const [jobId, setJobId] = useState<string | null>(null)
  const [proposals, setProposals] = useState<Compartment[]>([])
  const patch = (p: Partial<InsertSpec>) => setSpec((s) => ({ ...s, ...p }))

  const objects = useQuery({ queryKey: ['objects'], queryFn: api.objects })
  const objMap = useMemo(() => Object.fromEntries((objects.data ?? []).map((o) => [o.id, o])) as Record<string, ObjectSpec>, [objects.data])

  // Autosave
  const dSpec = useDebounced(spec, 300)
  const first = useRef(true)
  const saveT = useRef<ReturnType<typeof setTimeout>>(undefined)
  useEffect(() => {
    if (first.current) { first.current = false; return }
    clearTimeout(saveT.current)
    saveT.current = setTimeout(() => { api.saveInsert(spec).then(() => qc.invalidateQueries({ queryKey: ['inserts'] })) }, 800)
    return () => clearTimeout(saveT.current)
  }, [spec, qc])

  const layout = useQuery({
    queryKey: ['layout', JSON.stringify(dSpec)],
    queryFn: () => api.layout(dSpec),
    placeholderData: keepPreviousData,
    enabled: objects.isSuccess,
  })

  const built = useRef('')
  const build = useMutation({ mutationFn: () => { built.current = JSON.stringify(spec); return api.build(spec) }, onSuccess: (r) => { setJobId(r.job_id); setTab('3d') } })
  const job = useQuery({
    queryKey: ['job', jobId], queryFn: () => api.job(jobId!), enabled: !!jobId,
    refetchInterval: (q) => (q.state.data?.status === 'running' ? 1000 : false),
  })
  const outdated = job.data?.status === 'done' && built.current !== JSON.stringify(spec)

  const autoComp = useMutation({ mutationFn: () => api.autoCompartments(spec), onSuccess: (r) => setProposals(r.compartments) })

  const move = (s: NonNullable<Sel>, x: number, y: number) => {
    setSpec((sp) => {
      if (s.kind === 'placement') return { ...sp, placements: sp.placements.map((p, i) => (i === s.index ? { ...p, x, y } : p)) }
      if (s.kind === 'grip') return { ...sp, grip_recesses: sp.grip_recesses.map((p, i) => (i === s.index ? { ...p, x, y } : p)) }
      if (s.kind === 'comp') return { ...sp, compartments: sp.compartments.map((p, i) => (i === s.index ? { ...p, x, y } : p)) }
      return sp
    })
  }

  const usable = (objects.data ?? []).filter((o) => o.profile)
  const addObject = (oid: string) => patch({
    placements: [...spec.placements, { object_id: oid, x: 6 + spec.placements.length * 4, y: 8 + spec.placements.length * 4, rot_deg: 0, side_down: 'A' }],
  })
  const addGrip = () => patch({ grip_recesses: [...spec.grip_recesses, { shape: 'stadium', x: 30, y: 30, w: 14, l: 30, rot_deg: 0, depth_below: 10 }] })
  const addComp = () => patch({ compartments: [...spec.compartments, { x: 10, y: 10, w: 25, l: 25, radius: 3, depth: 15 }] })

  const lay = layout.data
  const warnings = lay?.warnings ?? []

  return (
    <div className="grid gap-0 lg:grid-cols-[300px_minmax(0,1fr)_320px] min-h-[calc(100dvh-56px)]">
      {/* Parameter */}
      <aside className="panel p-3 grid gap-3 content-start overflow-y-auto overflow-x-hidden" style={{ borderRadius: 0, borderWidth: '0 1px 0 0', maxHeight: 'calc(100dvh - 56px)' }}>
        <Field label="Name"><input className="input" value={spec.name} onChange={(e) => patch({ name: e.target.value })} /></Field>
        <section className="grid gap-2">
          <h3 className="sect">Größe</h3>
          <Check label="Raster automatisch" checked={spec.grid_x === null}
            onChange={(v) => patch(v ? { grid_x: null, grid_y: null } : { grid_x: lay?.grid_x ?? 3, grid_y: lay?.grid_y ?? 3 })} />
          {spec.grid_x !== null && (
            <div className="grid grid-cols-2 gap-2">
              <NumberField label="Breite" unit="E" step={1} min={1} value={spec.grid_x} onChange={(v) => patch({ grid_x: Math.round(v) })} />
              <NumberField label="Tiefe" unit="E" step={1} min={1} value={spec.grid_y ?? 1} onChange={(v) => patch({ grid_y: Math.round(v) })} />
            </div>
          )}
          <Check label="Höhe automatisch" checked={spec.height_u === null}
            onChange={(v) => patch({ height_u: v ? null : lay?.height_u ?? 4 })} />
          {spec.height_u !== null && <NumberField label="Höhe" unit="U (7 mm)" step={1} min={1} value={spec.height_u} onChange={(v) => patch({ height_u: Math.round(v) })} />}
          {lay && <div className="num hint">{lay.grid_x} x {lay.grid_y} Einheiten, {lay.height_u} U = {(lay.height_u * 7).toFixed(0)} mm</div>}
          <Check label="Stapelrand" checked={spec.stacking_lip} onChange={(v) => patch({ stacking_lip: v })} />
          <Check label="Magnetlöcher" checked={spec.magnets} onChange={(v) => patch({ magnets: v })} />
        </section>

        <section className="grid gap-2">
          <h3 className="sect">Spiel</h3>
          <Segmented value={[0.3, 1.0, 2.0].includes(spec.clearance_xy) ? spec.clearance_xy : -1}
            onChange={(v) => v > 0 && patch({ clearance_xy: v })}
            options={[{ value: 0.3, label: 'Presspassung' }, { value: 1.0, label: 'Normal' }, { value: 2.0, label: 'Locker' }, { value: -1, label: 'Frei' }]} />
          <NumberField label="Spiel seitlich" value={spec.clearance_xy} step={0.1} min={0} max={4} onChange={(v) => patch({ clearance_xy: v })} hint="Standard 1,5 mm" />
          <NumberField label="Zusatzspiel an den Enden" value={spec.clearance_end} step={0.1} min={0} onChange={(v) => patch({ clearance_end: v })} />
          <NumberField label="Abstand Boden zu Werkzeug" value={spec.clearance_z} step={0.1} min={0} onChange={(v) => patch({ clearance_z: v })} />
          <NumberField label="Überstand (+) / versenkt (-)" value={spec.overhang} step={0.5} onChange={(v) => patch({ overhang: v })}
            hint={spec.overhang > 0 ? 'Nicht stapelbar' : undefined} />
        </section>

        <details className="grid gap-2">
          <summary className="sect cursor-pointer">Stufen und Wände</summary>
          <div className="grid gap-2 mt-2">
            <NumberField label="Stufentoleranz" value={spec.step_tol} step={0.1} min={0.1} onChange={(v) => patch({ step_tol: v })} />
            <NumberField label="Min. Zonenlänge" value={spec.min_zone_len} step={1} min={1} onChange={(v) => patch({ min_zone_len: v })} />
            <NumberField label="Max. Zonen" unit="" value={spec.max_zones} step={1} min={1} onChange={(v) => patch({ max_zones: Math.round(v) })} />
            <NumberField label="Min. Material unter Boden" value={spec.floor_min} step={0.1} min={0.4} onChange={(v) => patch({ floor_min: v })} />
            <NumberField label="Min. Wand" value={spec.min_wall} step={0.1} min={0.4} onChange={(v) => patch({ min_wall: v })} />
          </div>
        </details>

        <section className="grid gap-2">
          <h3 className="sect">Farben (Filament-Slot)</h3>
          {([['body', 'Körper'], ['pocket', 'Taschen'], ['grip', 'Greifmulden'], ['compartment', 'Fächer']] as const).map(([key, label]) => (
            <div key={key} className="flex items-center justify-between gap-2">
              <span>{label}</span>
              <select className="input" style={{ width: 80 }} value={spec.colors[key]}
                onChange={(e) => patch({ colors: { ...spec.colors, [key]: +e.target.value } })}>
                {[1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>{n}</option>)}
              </select>
            </div>
          ))}
          <div className="grid grid-cols-2 gap-2">
            <NumberField label="Haut Boden" value={spec.color_skin.floor} step={0.1} min={0.2} onChange={(v) => patch({ color_skin: { ...spec.color_skin, floor: v } })} />
            <NumberField label="Haut Wand" value={spec.color_skin.wall} step={0.1} min={0.2} onChange={(v) => patch({ color_skin: { ...spec.color_skin, wall: v } })} />
          </div>
          <Check label="Farbring oben" checked={spec.color_skin.show_top_ring} onChange={(v) => patch({ color_skin: { ...spec.color_skin, show_top_ring: v } })} />
        </section>
      </aside>

      {/* Mitte */}
      <section className="min-w-0 p-3 grid grid-cols-[minmax(0,1fr)] gap-3 content-start">
        <div className="flex flex-wrap items-center gap-2">
          <Segmented value={tab} onChange={setTab} options={[{ value: 'layout', label: 'Layout' }, { value: '3d', label: '3D-Vorschau' }]} />
          <div className="flex-1" />
          {usable.length > 0 && (
            <select className="input" style={{ width: 200 }} value="" onChange={(e) => e.target.value && addObject(e.target.value)} aria-label="Objekt hinzufügen">
              <option value="">Objekt hinzufügen …</option>
              {usable.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
            </select>
          )}
          <button className="btn btn-sm" onClick={addGrip}><Plus size={14} /> Greifmulde</button>
          <button className="btn btn-sm" onClick={addComp}><Plus size={14} /> Fach</button>
          <button className="btn btn-sm" onClick={() => autoComp.mutate()} disabled={autoComp.isPending || !spec.placements.length}>Fächer vorschlagen</button>
        </div>

        {tab === 'layout' && (
          <>
            {usable.length === 0 && objects.isSuccess && (
              <div className="msg msg-warn">Es gibt noch kein fertig gescanntes Objekt. In der Bibliothek ein Objekt scannen oder die Demo-Zange anlegen.
                <button className="btn btn-sm ml-2" onClick={() => nav('/')}>Zur Bibliothek</button></div>
            )}
            {layout.isError && <div className="msg msg-err">{String(layout.error).replace('Error: ', '')}</div>}
            <div className="panel p-2"><Editor2D spec={spec} layout={lay} objects={objMap} sel={sel} onSelect={setSel} onMove={move} proposals={proposals} /></div>
            {proposals.length > 0 && (
              <div className="panel p-3 flex items-center gap-3 flex-wrap">
                <span>{proposals.length} Fach-Vorschläge (gestrichelt)</span>
                <button className="btn btn-sm btn-primary" onClick={() => { patch({ compartments: [...spec.compartments, ...proposals] }); setProposals([]) }}>Alle übernehmen</button>
                <button className="btn btn-sm" onClick={() => setProposals([])}>Verwerfen</button>
              </div>
            )}
            <Msgs items={warnings} />
            <div className="hint">Elemente per Maus verschieben. Zahlen in den Flächen: Tiefe unter der Oberkante in mm.</div>
          </>
        )}
        {tab === '3d' && (
          job.data?.status === 'done' && job.data.outputs.glb ? (
            <>
              {outdated && <div className="msg msg-warn">Die Einlage wurde seit dem letzten Build geändert. Bitte neu erzeugen.</div>}
              <Suspense fallback={<div className="skeleton" style={{ height: 520 }} />}><Preview3D url={job.data.outputs.glb} /></Suspense>
            </>
          ) : (
            <div className="panel grid place-items-center gap-3 p-10 text-center" style={{ minHeight: 320 }}>
              {job.data?.status === 'running' || build.isPending ? (
                <><div className="skeleton h-3 w-64" /><div>Erzeuge 3D-Modell … {Math.round((job.data?.progress ?? 0.05) * 100)} %</div></>
              ) : (
                <>
                  <div>Das 3D-Modell mit Farbteilen entsteht serverseitig und braucht einige Sekunden.</div>
                  <button className="btn btn-primary" onClick={() => build.mutate()}>3D erzeugen</button>
                </>
              )}
              {job.data?.status === 'error' && <div className="msg msg-err">{job.data.error}</div>}
            </div>
          )
        )}
      </section>

      {/* Rechts */}
      <aside className="panel p-3 grid gap-4 content-start overflow-y-auto" style={{ borderRadius: 0, borderWidth: '0 0 0 1px', maxHeight: 'calc(100dvh - 56px)' }}>
        <SelectionPanel spec={spec} sel={sel} setSpec={setSpec} onSel={setSel} objMap={objMap}
          proposals={proposals} acceptProposal={(i) => { patch({ compartments: [...spec.compartments, proposals[i]] }); setProposals(proposals.filter((_, j) => j !== i)); setSel(null) }} />

        <section className="grid gap-2">
          <h3 className="sect">Export</h3>
          <button className="btn btn-primary justify-center" disabled={build.isPending || job.data?.status === 'running' || !spec.placements.length}
            onClick={() => build.mutate()}>
            <ArrowClockwise size={16} /> {job.data?.status === 'running' ? 'Erzeuge …' : '3D erzeugen und exportieren'}
          </button>
          {build.isError && <div className="msg msg-err">{String(build.error).replace('Error: ', '')}</div>}
          {job.data?.status === 'error' && <div className="msg msg-err">{job.data.error}</div>}
          {job.data?.status === 'done' && (
            <>
              <div className="grid gap-1">
                {OUTPUT_LABELS.filter(([k]) => job.data!.outputs[k]).map(([k, label, fn]) => (
                  <a key={k} className="btn justify-between no-underline" style={{ color: 'var(--ink)' }}
                    href={job.data!.outputs[k]} download={fn}>
                    <span>{label}</span><DownloadSimple size={16} />
                  </a>
                ))}
              </div>
              <Checks job={job.data} />
            </>
          )}
        </section>
      </aside>
    </div>
  )
}

function Checks({ job }: { job: NonNullable<ReturnType<typeof useQuery<import('../../lib/types').Job>>['data']> }) {
  const c = job.checks
  const rows: [string, boolean | string][] = [
    ['Ein zusammenhängender Körper', c.solid_count === 1],
    ['Geometrie gültig', !!c.valid],
    ['Wasserdicht', !!c.watertight],
    ['Teilvolumen = Gesamtvolumen', !!c.volume_sum_ok],
  ]
  return (
    <div className="grid gap-1 text-sm">
      {rows.map(([label, ok]) => (
        <div key={label} className="flex justify-between"><span>{label}</span>
          <b style={{ color: ok ? 'var(--ok)' : 'var(--err)' }}>{ok ? 'ok' : 'FEHLER'}</b></div>
      ))}
      <div className="num hint">
        {c.grid_x} x {c.grid_y} x {c.height_u} U · {Math.round(c.volume_mm3 / 1000)} cm³ · ca. {c.weight_g} g PLA
      </div>
      <Msgs items={job.warnings} />
    </div>
  )
}

function SelectionPanel({ spec, sel, setSpec, onSel, objMap, proposals, acceptProposal }: {
  spec: InsertSpec; sel: Sel; setSpec: (f: (s: InsertSpec) => InsertSpec) => void; onSel: (s: Sel) => void
  objMap: Record<string, ObjectSpec>; proposals: Compartment[]; acceptProposal: (i: number) => void
}) {
  if (!sel) return <div className="hint">Ein Element im Layout anklicken, um Position und Maße zu ändern.</div>
  const remove = () => {
    setSpec((s) => ({
      ...s,
      placements: sel.kind === 'placement' ? s.placements.filter((_, i) => i !== sel.index) : s.placements,
      grip_recesses: sel.kind === 'grip' ? s.grip_recesses.filter((_, i) => i !== sel.index) : s.grip_recesses,
      compartments: sel.kind === 'comp' ? s.compartments.filter((_, i) => i !== sel.index) : s.compartments,
    }))
    onSel(null)
  }
  const del = <button className="btn btn-sm" onClick={remove}><Trash size={14} /> Entfernen</button>

  if (sel.kind === 'proposal') {
    return <div className="grid gap-2"><h3 className="sect">Fach-Vorschlag</h3>
      <div className="num hint">{proposals[sel.index]?.w} x {proposals[sel.index]?.l} mm</div>
      <button className="btn btn-sm btn-primary" onClick={() => acceptProposal(sel.index)}>Übernehmen</button></div>
  }
  if (sel.kind === 'placement') {
    const p = spec.placements[sel.index]
    if (!p) return null
    const upd = (q: Partial<typeof p>) => setSpec((s) => ({ ...s, placements: s.placements.map((x, i) => (i === sel.index ? { ...x, ...q } : x)) }))
    return (
      <div className="grid gap-2">
        <h3 className="sect">{objMap[p.object_id]?.name ?? 'Objekt'}</h3>
        <div className="grid grid-cols-2 gap-2">
          <NumberField label="X" value={p.x} step={0.5} onChange={(v) => upd({ x: v })} />
          <NumberField label="Y" value={p.y} step={0.5} onChange={(v) => upd({ y: v })} />
        </div>
        <NumberField label="Drehung" unit="°" value={p.rot_deg} step={1} onChange={(v) => upd({ rot_deg: v })} />
        <div className="flex gap-1">
          {[-90, 90, 180].map((d) => <button key={d} className="btn btn-sm" onClick={() => upd({ rot_deg: (((p.rot_deg + d) % 360) + 360) % 360 })}>{d > 0 ? '+' : ''}{d}°</button>)}
        </div>
        <div className="hint">X/Y ist der Ursprung des Objekts (linkes Ende der Längsachse).</div>
        {del}
      </div>
    )
  }
  if (sel.kind === 'grip') {
    const g = spec.grip_recesses[sel.index]
    if (!g) return null
    const upd = (q: Partial<GripRecess>) => setSpec((s) => ({ ...s, grip_recesses: s.grip_recesses.map((x, i) => (i === sel.index ? { ...x, ...q } : x)) }))
    return (
      <div className="grid gap-2">
        <h3 className="sect">Greifmulde</h3>
        <Segmented value={g.shape} onChange={(v) => upd({ shape: v })} options={[{ value: 'stadium', label: 'Oval' }, { value: 'rect', label: 'Rechteck' }, { value: 'circle', label: 'Kreis' }]} />
        <div className="grid grid-cols-2 gap-2">
          <NumberField label="X (Mitte)" value={g.x} step={0.5} onChange={(v) => upd({ x: v })} />
          <NumberField label="Y (Mitte)" value={g.y} step={0.5} onChange={(v) => upd({ y: v })} />
          <NumberField label={g.shape === 'circle' ? 'Durchmesser' : 'Breite'} value={g.w} step={0.5} min={2} onChange={(v) => upd({ w: v })} />
          {g.shape !== 'circle' && <NumberField label="Länge" value={g.l} step={0.5} min={2} onChange={(v) => upd({ l: v })} />}
        </div>
        <NumberField label="Drehung" unit="°" value={g.rot_deg} step={5} onChange={(v) => upd({ rot_deg: v })} />
        <NumberField label="Tiefe unter Taschenboden" value={g.depth_below} step={1} min={0} onChange={(v) => upd({ depth_below: v })} />
        {del}
      </div>
    )
  }
  const c = spec.compartments[sel.index]
  if (!c) return null
  const upd = (q: Partial<Compartment>) => setSpec((s) => ({ ...s, compartments: s.compartments.map((x, i) => (i === sel.index ? { ...x, ...q } : x)) }))
  return (
    <div className="grid gap-2">
      <h3 className="sect">Fach</h3>
      <div className="grid grid-cols-2 gap-2">
        <NumberField label="X (links)" value={c.x} step={0.5} onChange={(v) => upd({ x: v })} />
        <NumberField label="Y (unten)" value={c.y} step={0.5} onChange={(v) => upd({ y: v })} />
        <NumberField label="Breite" value={c.w} step={0.5} min={4} onChange={(v) => upd({ w: v })} />
        <NumberField label="Länge" value={c.l} step={0.5} min={4} onChange={(v) => upd({ l: v })} />
        <NumberField label="Eckradius" value={c.radius} step={0.5} min={0} onChange={(v) => upd({ radius: v })} />
        <NumberField label="Tiefe" value={c.depth} step={1} min={2} onChange={(v) => upd({ depth: v })} />
      </div>
      {del}
    </div>
  )
}
