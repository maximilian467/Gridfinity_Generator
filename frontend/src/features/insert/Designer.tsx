import { lazy, Suspense, useEffect, useMemo, useRef, useState } from 'react'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useParams } from 'react-router'
import { ArrowClockwise, CheckCircle, CrosshairSimple, DownloadSimple, Plus, Rows, SquaresFour, Trash, XCircle } from '@phosphor-icons/react'
import { api } from '../../lib/api'
import type { Compartment, GripRecess, InsertSpec, ObjectSpec } from '../../lib/types'
import { BusyBar, Check, Field, Msg, Msgs, NumberField, Segmented, errText } from '../../components/ui'
import { arrange, placeNew } from '../../lib/placement'
import { Editor2D } from './Editor2D'
import type { Sel } from './Editor2D'

const Preview3D = lazy(() => import('./Preview3D').then((m) => ({ default: m.Preview3D })))

/** Zentrierungs-Verschiebung fest in alle Positionen übernehmen und Zentrierung ausschalten. */
function bake(sp: InsertSpec, dx: number, dy: number): InsertSpec {
  return {
    ...sp, auto_center: false,
    placements: sp.placements.map((p) => ({ ...p, x: round1(p.x + dx), y: round1(p.y + dy) })),
    grip_recesses: sp.grip_recesses.map((g) => ({ ...g, x: round1(g.x + dx), y: round1(g.y + dy) })),
    compartments: sp.compartments.map((c) => ({ ...c, x: round1(c.x + dx), y: round1(c.y + dy),
      polygon: c.polygon ? c.polygon.map(([x, y]) => [x + dx, y + dy] as [number, number]) : c.polygon })),
  }
}
const round1 = (v: number) => Math.round(v * 10) / 10

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
  const patch = (p: Partial<InsertSpec>) => setSpec((s) => ({ ...s, ...p }))

  const objects = useQuery({ queryKey: ['objects'], queryFn: api.objects })
  const objMap = useMemo(() => Object.fromEntries((objects.data ?? []).map((o) => [o.id, o])) as Record<string, ObjectSpec>, [objects.data])

  // Autosave
  const dSpec = useDebounced(spec, 300)
  const first = useRef(true)
  const saveT = useRef<ReturnType<typeof setTimeout>>(undefined)
  const [saveState, setSaveState] = useState<'saved' | 'pending' | 'error'>('saved')
  useEffect(() => {
    if (first.current) { first.current = false; return }
    setSaveState('pending')
    clearTimeout(saveT.current)
    saveT.current = setTimeout(() => {
      api.saveInsert(spec)
        .then(() => { setSaveState('saved'); qc.invalidateQueries({ queryKey: ['inserts'] }) })
        .catch(() => setSaveState('error'))
    }, 800)
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


  const move = (s: NonNullable<Sel>, x: number, y: number) => {
    // Wer von Hand verschiebt, will die Position behalten: automatische Zentrierung aus,
    // aktuelle Verschiebung in die Positionen übernehmen, damit nichts springt.
    const [dx, dy] = spec.auto_center && lay ? lay.shift : [0, 0]
    setSpec((sp0) => {
      const sp = sp0.auto_center ? bake(sp0, dx, dy) : sp0
      if (s.kind === 'placement') return { ...sp, placements: sp.placements.map((p, i) => (i === s.index ? { ...p, x: round1(x + dx), y: round1(y + dy) } : p)) }
      if (s.kind === 'grip') return { ...sp, grip_recesses: sp.grip_recesses.map((p, i) => (i === s.index ? { ...p, x: round1(x + dx), y: round1(y + dy) } : p)) }
      if (s.kind === 'comp') return { ...sp, compartments: sp.compartments.map((p, i) => {
        if (i !== s.index) return p
        const nx = round1(x + dx), ny = round1(y + dy)
        return { ...p, x: nx, y: ny, polygon: p.polygon ? p.polygon.map(([qx, qy]) => [qx + nx - p.x, qy + ny - p.y] as [number, number]) : p.polygon }
      }) }
      return sp
    })
  }
  const centerNow = () => setSpec((sp) => ({ ...sp, auto_center: true }))

  const usable = (objects.data ?? []).filter((o) => o.profile)
  const addObject = (oid: string) => objMap[oid] && patch({ placements: [...spec.placements, placeNew(spec, objMap, objMap[oid])] })
  const doArrange = () => patch({ placements: arrange(spec, objMap) })
  const addGrip = () => {
    // Standard: quer über die Mitte des ersten Objekts (dort greift man meist zu)
    const p = spec.placements[0], o = p && objMap[p.object_id]
    const g = o
      ? { x: p.x + (o.length_mm / 2) * Math.cos((p.rot_deg * Math.PI) / 180), y: p.y + (o.length_mm / 2) * Math.sin((p.rot_deg * Math.PI) / 180), l: o.width_mm + 16, rot: p.rot_deg + 90 }
      : { x: 30, y: 30, l: 30, rot: 0 }
    patch({ grip_recesses: [...spec.grip_recesses, { shape: 'stadium', x: Math.round(g.x), y: Math.round(g.y), w: 16, l: Math.round(g.l), rot_deg: g.rot % 360, depth_below: 10 }] })
    setSel({ kind: 'grip', index: spec.grip_recesses.length })
  }
  const addComp = () => {
    patch({ compartments: [...spec.compartments, { x: 10, y: 10, w: 25, l: 25, radius: 3, depth: 15 }] })
    setSel({ kind: 'comp', index: spec.compartments.length })
  }

  const lay = layout.data
  const warnings = lay?.warnings ?? []

  return (
    <div className="grid gap-0 lg:grid-cols-[300px_minmax(0,1fr)_320px] min-h-[calc(100dvh-56px)]">
      {/* Parameter */}
      <aside className="panel p-3 grid gap-3 content-start overflow-y-auto overflow-x-hidden" style={{ borderRadius: 0, borderWidth: '0 1px 0 0', maxHeight: 'calc(100dvh - 56px)' }}>
        <Field label="Name"><input className="input" value={spec.name} onChange={(e) => patch({ name: e.target.value })} /></Field>
        <section className="grid gap-2">
          <h3 className="sect">Größe</h3>
          <div className="hint mt-0">Automatisch: kleinstes Raster und kleinste Höhe, in die alles passt.</div>
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
          <h3 className="sect">Automatik</h3>
          <Check label="Inhalt mittig ausrichten" checked={spec.auto_center} onChange={(v) => patch({ auto_center: v })} />
          <Check label="Greifmulde unter dem Werkzeug" checked={spec.auto_grip} onChange={(v) => patch({ auto_grip: v })} />
          {spec.auto_grip && (
            <div className="grid grid-cols-2 gap-2 pl-6">
              <NumberField label="Breite" value={spec.grip_width} step={1} min={8} onChange={(v) => patch({ grip_width: v })} />
              <NumberField label="Überstand je Seite" value={spec.grip_overhang} step={1} min={0} onChange={(v) => patch({ grip_overhang: v })} />
              <NumberField label="Tiefe unter Werkzeug" value={spec.grip_depth_below} step={1} min={2} onChange={(v) => patch({ grip_depth_below: v })} />
            </div>
          )}
          {spec.auto_grip && <div className="hint mt-0 pl-6">Langloch quer am Schwerpunkt, Boden rund ausgeformt. Hier greift man unter das Werkzeug.</div>}
          <Check label="Kästen in freien Flächen" checked={spec.auto_compartments} onChange={(v) => patch({ auto_compartments: v })} />
          {spec.auto_compartments && (
            <div className="grid grid-cols-2 gap-2 pl-6">
              <NumberField label="Mindestgröße" value={spec.comp_min_size} step={1} min={10} onChange={(v) => patch({ comp_min_size: v })} />
              <NumberField label="Wandstärke" value={spec.comp_wall} step={0.1} min={0.8} onChange={(v) => patch({ comp_wall: v })} />
              <NumberField label="Tiefe (0 = max.)" value={spec.comp_depth ?? 0} step={1} min={0} onChange={(v) => patch({ comp_depth: v > 0 ? v : null })} />
            </div>
          )}
          <label className="grid gap-1">
            <span className="label mb-0">Kontur glätten <span className="num">{spec.smooth_mm.toFixed(1)} mm</span></span>
            <input type="range" min={0} max={5} step={0.5} value={spec.smooth_mm} onChange={(e) => patch({ smooth_mm: +e.target.value })} />
            <span className="hint mt-0">Füllt kleine Kerben und Zacken der Kontur. Die Tasche wird dabei nie kleiner als das Werkzeug.</span>
          </label>
        </section>

        <section className="grid gap-2">
          <h3 className="sect">Spiel</h3>
          <div className="hint mt-0">Luft zwischen Werkzeug und Taschenwand. Für den Anfang "Normal" wählen und mit dem Passform-Test prüfen.</div>
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
      <section className="min-w-0 p-4 grid grid-cols-[minmax(0,1fr)] gap-3 content-start">
        <header className="flex flex-wrap items-center gap-3">
          <h1 className="text-xl font-semibold tracking-tight mr-2">{spec.name || 'Einlage'}</h1>
          {lay && <span className="chip num">{lay.grid_x} x {lay.grid_y} Einheiten · {lay.height_u * 7} mm hoch</span>}
          <span className={`chip ${saveState === 'error' ? 'chip-err' : saveState === 'saved' ? 'chip-ok' : ''}`}>
            {saveState === 'saved' ? <><CheckCircle size={14} /> Gespeichert</> : saveState === 'pending' ? 'Speichere …' : <><XCircle size={14} /> Nicht gespeichert</>}
          </span>
          <div className="flex-1" />
          <Segmented value={tab} onChange={setTab} options={[{ value: 'layout', label: 'Layout (2D)' }, { value: '3d', label: '3D-Vorschau' }]} />
        </header>

        {tab === 'layout' && (
          <div className="flex flex-wrap items-center gap-2 panel p-2">
            {usable.length > 0 && (
              <select className="input" style={{ width: 210 }} value="" onChange={(e) => e.target.value && addObject(e.target.value)} aria-label="Objekt hinzufügen">
                <option value="">+ Objekt hinzufügen …</option>
                {usable.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
              </select>
            )}
            <button className="btn btn-sm" onClick={doArrange} disabled={!spec.placements.length} title="Objekte an die Innenecke rücken und untereinander anordnen"><Rows size={14} /> Anordnen</button>
            <span className="w-px h-6" style={{ background: 'var(--line)' }} />
            <button className="btn btn-sm" onClick={addGrip} disabled={!spec.placements.length}><Plus size={14} /> Greifmulde</button>
            <button className="btn btn-sm" onClick={addComp}><Plus size={14} /> Fach</button>
            <span className="w-px h-6" style={{ background: 'var(--line)' }} />
            <button className={`btn btn-sm ${spec.auto_center ? 'btn-on' : ''}`} onClick={centerNow} title="Inhalt mittig in die Einlage setzen und dort halten">
              <CrosshairSimple size={14} /> Mittig{spec.auto_center ? ' (aktiv)' : ''}
            </button>
            <button className={`btn btn-sm ${spec.auto_compartments ? 'btn-on' : ''}`} onClick={() => patch({ auto_compartments: !spec.auto_compartments })}
              title="Freie Flächen automatisch mit Kästen füllen">
              <SquaresFour size={14} /> Kästen{spec.auto_compartments ? ' (an)' : ''}
            </button>
          </div>
        )}

        {tab === 'layout' && (
          <>
            {usable.length === 0 && objects.isSuccess && (
              <Msg kind="warn">Es gibt noch kein fertig gescanntes Objekt. In der Bibliothek ein Objekt scannen oder die Demo-Zange anlegen.
                <button className="btn btn-sm ml-2" onClick={() => nav('/')}>Zur Bibliothek</button></Msg>
            )}
            {layout.isError && <Msg kind="err">{errText(layout.error)}</Msg>}
            {spec.placements.length === 0 && usable.length > 0 && (
              <Msg kind="info">Noch kein Werkzeug in dieser Einlage. Oben über "Objekt hinzufügen" ein gescanntes Werkzeug wählen.</Msg>
            )}
            <div className="panel p-2 relative">
              {layout.isFetching && <div className="absolute inset-x-2 top-1"><BusyBar /></div>}
              <Editor2D spec={spec} layout={lay} objects={objMap} sel={sel} onSelect={setSel} onMove={move} />
            </div>
            <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-sm" style={{ color: 'var(--ink-2)' }}>
              <span className="inline-flex items-center gap-2">
                <span className="swatch" style={{ width: 48, background: 'linear-gradient(90deg, color-mix(in srgb, var(--accent) 20%, transparent), var(--accent))' }} />
                Tasche: je dunkler, desto tiefer (Zahl = Tiefe in mm)
              </span>
              <span className="inline-flex items-center gap-2"><span className="swatch" style={{ background: 'color-mix(in srgb, var(--blue) 45%, transparent)' }} /> Greifmulde</span>
              <span className="inline-flex items-center gap-2"><span className="swatch" style={{ background: 'color-mix(in srgb, var(--green) 45%, transparent)' }} /> Fach</span>
              <span className="inline-flex items-center gap-2"><span className="swatch" style={{ border: '1px dashed var(--ink-3)' }} /> nutzbarer Innenbereich</span>
            </div>
            {warnings.map((w, i) => (
              <Msg key={i} kind="warn">{w}
                {/Innenbereich|überlappen|Wand zwischen/.test(w) && spec.placements.length > 0 &&
                  <button className="btn btn-sm ml-2" onClick={doArrange}><Rows size={14} /> Automatisch anordnen</button>}
              </Msg>
            ))}
            <div className="hint">Elemente mit der Maus verschieben, anklicken für genaue Maße (rechts).</div>
          </>
        )}
        {tab === '3d' && (
          job.data?.status === 'done' && job.data.outputs.glb ? (
            <>
              {outdated && <Msg kind="warn">Die Einlage wurde seit dem letzten Erzeugen geändert. Die Vorschau zeigt den alten Stand.
                <button className="btn btn-sm ml-2" onClick={() => build.mutate()}>Neu erzeugen</button></Msg>}
              <Suspense fallback={<div className="skeleton" style={{ height: 520 }} />}><Preview3D url={job.data.outputs.glb} /></Suspense>
            </>
          ) : (
            <div className="panel grid place-items-center gap-3 p-10 text-center" style={{ minHeight: 320 }}>
              {job.data?.status === 'running' || build.isPending ? (
                <div className="w-80"><BusyBar label="Erzeuge 3D-Modell mit Farbteilen. Das dauert 10 bis 40 Sekunden." /></div>
              ) : (
                <>
                  <div className="max-w-[48ch]" style={{ color: 'var(--ink-2)' }}>Das echte 3D-Modell (Tasche, Stufen, Farbteile, Gridfinity-Füße) wird auf dem Server berechnet und anschließend auf Fehler geprüft.</div>
                  <button className="btn btn-primary" onClick={() => build.mutate()} disabled={!spec.placements.length}>3D erzeugen</button>
                </>
              )}
              {job.data?.status === 'error' && <Msg kind="err">{job.data.error}</Msg>}
              {build.isError && <Msg kind="err">{errText(build.error)}</Msg>}
            </div>
          )
        )}
      </section>

      {/* Rechts */}
      <aside className="panel p-3 grid gap-4 content-start overflow-y-auto" style={{ borderRadius: 0, borderWidth: '0 0 0 1px', maxHeight: 'calc(100dvh - 56px)' }}>
        <SelectionPanel spec={spec} sel={sel} setSpec={setSpec} onSel={setSel} objMap={objMap}  />

        <section className="grid gap-2">
          <h3 className="sect">Export</h3>
          <div className="hint mt-0">1. Modell erzeugen, 2. Dateien laden. Zuerst den Passform-Test drucken, um das Spiel zu prüfen.</div>
          <button className="btn btn-primary justify-center" disabled={build.isPending || job.data?.status === 'running' || !spec.placements.length || warnings.some((w) => /Innenbereich/.test(w))}
            onClick={() => build.mutate()}>
            <ArrowClockwise size={16} /> {job.data?.status === 'running' ? 'Erzeuge …' : job.data?.status === 'done' ? 'Neu erzeugen' : '3D erzeugen'}
          </button>
          {warnings.some((w) => /Innenbereich/.test(w)) && <div className="hint mt-0">Erst möglich, wenn alle Taschen in der Einlage liegen.</div>}
          {!spec.placements.length && <div className="hint mt-0">Zuerst ein Objekt hinzufügen.</div>}
          {(job.data?.status === 'running' || build.isPending) && <BusyBar label="Berechne …" />}
          {build.isError && <Msg kind="err">{errText(build.error)}</Msg>}
          {job.data?.status === 'error' && <Msg kind="err">{job.data.error}</Msg>}
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
      <h3 className="sect mt-2">Prüfung</h3>
      {rows.map(([label, ok]) => (
        <div key={label} className="flex items-center gap-2">
          {ok ? <CheckCircle size={16} weight="fill" color="var(--ok)" /> : <XCircle size={16} weight="fill" color="var(--err)" />}
          <span>{label}</span></div>
      ))}
      <div className="num hint">
        {c.grid_x} x {c.grid_y} x {c.height_u} U · {Math.round(c.volume_mm3 / 1000)} cm³ · ca. {c.weight_g} g PLA
      </div>
      <Msgs items={job.warnings} />
    </div>
  )
}

function SelectionPanel({ spec, sel, setSpec, onSel, objMap }: {
  spec: InsertSpec; sel: Sel; setSpec: (f: (s: InsertSpec) => InsertSpec) => void; onSel: (s: Sel) => void
  objMap: Record<string, ObjectSpec>
}) {
  if (!sel) return (
    <div className="grid gap-2">
      <h3 className="sect">Auswahl</h3>
      <div className="hint mt-0">Ein Element im Layout anklicken, um Position, Drehung und Maße genau einzustellen.</div>
    </div>
  )
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
