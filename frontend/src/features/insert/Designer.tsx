import { lazy, Suspense, useEffect, useMemo, useRef, useState } from 'react'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useParams } from 'react-router'
import { ArrowClockwise, CheckCircle, CrosshairSimple, DownloadSimple, Plus, Rows, SquaresFour, Trash, XCircle } from '@phosphor-icons/react'
import { api } from '../../lib/api'
import type { Compartment, GripRecess, InsertSpec, LayoutOut, Level, ObjectSpec } from '../../lib/types'
import { BusyBar, Check, Field, Msg, Msgs, NumberField, Segmented, errText } from '../../components/ui'
import { arrange, placeNew } from '../../lib/placement'
import { Editor2D } from './Editor2D'
import type { Sel, Tool } from './Editor2D'

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
  const [compSel, setCompSel] = useState<number[]>([])
  const [pocketPt, setPocketPt] = useState<{ pi: number; s: number } | null>(null)
  const [compMsg, setCompMsg] = useState<{ text: string; grid: [number, number] } | null>(null)
  const select = (s: Sel, additive?: boolean) => {
    setSel(s)
    if (s?.kind === 'comp') {
      setCompSel((cur) => additive ? (cur.includes(s.index) ? cur.filter((i) => i !== s.index) : [...cur, s.index]) : [s.index])
    } else setCompSel([])
  }
  const [tab, setTab] = useState<'layout' | '3d'>('layout')
  const [jobId, setJobId] = useState<string | null>(null)
  const patch = (p: Partial<InsertSpec>) => setSpec((s) => ({ ...s, ...p }))

  const objects = useQuery({ queryKey: ['objects'], queryFn: () => api.objects(true) })
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
      if (s.kind === 'grip') return { ...sp, grip_recesses: sp.grip_recesses.map((p, i) => {
        if (i !== s.index) return p
        const pl = p.attach != null ? sp.placements[p.attach] : undefined
        const lg = lay?.grips.filter((q) => !q.auto)[i]
        if (pl && lg?.polygons[0]) {
          // Verschiebung entlang der Achse -> neue Position s (quer bleibt die Mulde mittig)
          const xs0 = lg.polygons[0].exterior.map((q) => q[0]), ys0 = lg.polygons[0].exterior.map((q) => q[1])
          const cx = (Math.min(...xs0) + Math.max(...xs0)) / 2 - (lay?.shift[0] ?? 0)
          const cy = (Math.min(...ys0) + Math.max(...ys0)) / 2 - (lay?.shift[1] ?? 0)
          const a = (pl.rot_deg * Math.PI) / 180
          const ds = (x - cx) * Math.cos(a) + (y - cy) * Math.sin(a)
          return { ...p, s: round1((p.s ?? 0) + ds) }
        }
        return { ...p, x: round1(x + dx), y: round1(y + dy) }
      }) }
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
  // Greifmulde: das Backend berechnet sie am Schwerpunkt (auto_grip), das Frontend übernimmt sie
  // sofort als normale Mulde -> direkt verschiebbar, drehbar, löschbar.
  const addGrip = () => patch({ auto_grip: true })
  const lay0 = layout.data
  useEffect(() => {
    if (!spec.auto_grip || !lay0 || layout.isPlaceholderData) return
    const params = lay0.grips.filter((g) => g.auto && g.params).map((g) => g.params!)
    if (!params.length && spec.placements.length) return
    const r = (v: number) => Math.round(v * 10) / 10
    setSpec((sp) => ({
      ...sp, auto_grip: false,
      grip_recesses: [...sp.grip_recesses, ...params.map((g) => ({ ...g, x: r(g.x), y: r(g.y), l: r(g.l), rot_deg: r(g.rot_deg) }))],
    }))
    if (params.length) setSel({ kind: 'grip', index: spec.grip_recesses.length })
  }, [lay0, spec.auto_grip]) // eslint-disable-line react-hooks/exhaustive-deps

  // Kästen: in den freien Flächen erzeugen, danach einzeln anwählbar und löschbar
  const genComps = useMutation({
    mutationFn: () => api.autoCompartments({ ...spec, auto_compartments: false }),
    onSuccess: (r) => {
      setCompMsg(r.compartments.length ? null : { text: r.reason ?? 'Kein Platz für Kästen.', grid: r.grid })
      setSpec((sp) => ({ ...sp, auto_compartments: false,
        compartments: [...sp.compartments.filter((c) => !c.generated), ...r.compartments.map((c) => ({ ...c, generated: true }))] }))
      select(null)
    },
  })
  // ältere Einlagen mit 'Kästen automatisch' einmalig in bearbeitbare Kästen umwandeln
  useEffect(() => { if (initial.auto_compartments) genComps.mutate() }, []) // eslint-disable-line react-hooks/exhaustive-deps
  const clearComps = () => { patch({ compartments: spec.compartments.filter((c) => !c.generated) }); select(null) }
  const editComps = useMutation({
    mutationFn: (v: { op: 'merge' | 'split'; parts?: number }) => api.editCompartments(spec, v.op, v.op === 'merge' ? compSel : [sel!.index], v.parts ?? 2),
    onSuccess: (r) => { patch({ compartments: r.compartments }); select(null) },
  })
  const growGrid = () => {
    if (!compMsg) return
    const [gx, gy] = compMsg.grid
    // kürzere Seite um ein Rasterfeld verbreitern, dann neu erzeugen
    patch(gx <= gy ? { grid_x: gx + 1, grid_y: gy } : { grid_x: gx, grid_y: gy + 1 })
    setCompMsg(null)
    setTimeout(() => genComps.mutate(), 400)
  }
  const nGenerated = spec.compartments.filter((c) => c.generated).length

  // Entf-Taste löscht das ausgewählte Element
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement
      if (!sel || (e.key !== 'Delete' && e.key !== 'Backspace') || t?.closest?.('input, textarea, select')) return
      e.preventDefault()
      setSpec((s) => ({
        ...s,
        placements: sel.kind === 'placement' ? s.placements.filter((_, i) => i !== sel.index) : s.placements,
        grip_recesses: sel.kind === 'grip' ? s.grip_recesses.filter((_, i) => i !== sel.index) : s.grip_recesses,
        compartments: sel.kind === 'comp' ? s.compartments.filter((_, i) => !(compSel.length ? compSel : [sel.index]).includes(i)) : s.compartments,
      }))
      select(null)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [sel, compSel])
  // Zeichenwerkzeuge: Kasten zeichnen (Linie um die Ecke, in der der Kasten liegen soll), gerader Schnitt
  const [tool, setTool] = useState<Tool>(null)
  const compAt = useMutation({
    mutationFn: (p: { x0: number; y0: number; x1: number; y1: number }) => api.compartmentRect(spec, p.x0, p.y0, p.x1, p.y1),
    onSuccess: (r) => { patch({ compartments: r.compartments }); select({ kind: 'comp', index: r.compartments.length - 1 }) },
  })
  const compCut = useMutation({
    mutationFn: (v: { comp: number; axis: 'h' | 'v'; at: number }) => api.editCompartments(spec, 'cut', [v.comp], 2, { axis: v.axis, at: v.at }),
    onSuccess: (r) => { patch({ compartments: r.compartments }); select(null) },
  })
  const onBox = (x0: number, y0: number, x1: number, y1: number) => compAt.mutate({ x0, y0, x1, y1 })
  const onCut = (x: number, y: number) => {
    if (tool?.kind !== 'cut') return
    const [sx0, sy0] = lay?.shift ?? [0, 0]
    setTool(null)
    compCut.mutate({ comp: tool.comp, axis: tool.axis, at: tool.axis === 'h' ? y - sy0 : x - sx0 })
  }
  useEffect(() => {
    if (!tool) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setTool(null) }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [tool])

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
          <Check label="Höhe automatisch" checked={spec.height_u === null && spec.height_mm === null}
            onChange={(v) => patch(v ? { height_u: null, height_mm: null } : { height_u: null, height_mm: Math.round(lay?.total_height ?? 32) })} />
          {spec.height_mm !== null && (
            <NumberField label="Gesamthöhe" step={1} min={10} value={spec.height_mm} onChange={(v) => patch({ height_mm: v, height_u: null })}
              hint={spec.stacking_lip ? 'inkl. Stapelrand (3,8 mm), ohne Werkzeug' : 'ohne Werkzeug'} />
          )}
          {spec.height_u !== null && spec.height_mm === null && (
            <NumberField label="Höhe" unit="U (7 mm)" step={1} min={1} value={spec.height_u} onChange={(v) => patch({ height_u: Math.round(v) })} />
          )}
          {lay && <div className="num hint">{lay.grid_x} x {lay.grid_y} Einheiten, {lay.total_height.toFixed(1)} mm hoch</div>}
          <label className="grid gap-1 mt-1">
            <span className="label mb-0">Werkzeug sinkt ein <span className="num">{Math.round(spec.sink * 100)} %</span>
              {lay && lay.sink.length > 0 && Math.min(...lay.sink) < spec.sink - 0.01 && <span className="num" style={{ color: 'var(--warn)' }}> (bei dieser Höhe {Math.round(Math.min(...lay.sink) * 100)} %)</span>}
            </span>
            <input type="range" min={30} max={100} step={5} value={Math.round(spec.sink * 100)} onChange={(e) => patch({ sink: +e.target.value / 100 })} />
            <span className="hint mt-0">Anteil der Werkzeugdicke, der in der Tasche verschwindet. 50 bis 75 % lässt sich gut greifen, 100 % = bündig.</span>
          </label>
          <Check label="Stapelrand" checked={spec.stacking_lip} onChange={(v) => patch({ stacking_lip: v })} />
          <Check label="Magnetlöcher" checked={spec.magnets} onChange={(v) => patch({ magnets: v })} />
        </section>

        <section className="grid gap-2">
          <h3 className="sect">Automatik</h3>
          <Check label="Inhalt mittig ausrichten" checked={spec.auto_center} onChange={(v) => patch({ auto_center: v })} />
          <div className="grid gap-2 mt-1">
            <div className="text-sm font-medium">Greifmulde (Langloch unter dem Werkzeug)</div>
            <div className="grid grid-cols-2 gap-2">
              <NumberField label="Breite" value={spec.grip_width} step={1} min={8} onChange={(v) => patch({ grip_width: v })} />
              <NumberField label="Überstand je Seite" value={spec.grip_overhang} step={1} min={0} onChange={(v) => patch({ grip_overhang: v })} />
              <NumberField label="Tiefe unter Werkzeug" value={spec.grip_depth_below} step={1} min={2} onChange={(v) => patch({ grip_depth_below: v })} />
            </div>
            <button className="btn btn-sm" onClick={addGrip} disabled={!spec.placements.length || spec.auto_grip}><Plus size={14} /> Greifmulde automatisch setzen</button>
            <div className="hint mt-0">Wird quer am Schwerpunkt gesetzt (bei Zangen am Gelenk). Querschnitt oval mit gerundeter Oberkante, ohne harte Kante. Danach entlang des Werkzeugs verschiebbar.</div>
          </div>
          <div className="grid gap-2 mt-1">
            <div className="text-sm font-medium">Kästen in den freien Flächen</div>
            <div className="grid grid-cols-2 gap-2">
              <NumberField label="Mindestgröße" value={spec.comp_min_size} step={1} min={10} onChange={(v) => patch({ comp_min_size: v })} />
              <NumberField label="Wandstärke" value={spec.comp_wall} step={0.1} min={0.8} onChange={(v) => patch({ comp_wall: v })} />
              <NumberField label="Tiefe (0 = max.)" value={spec.comp_depth ?? 0} step={1} min={0} onChange={(v) => patch({ comp_depth: v > 0 ? v : null })} />
            </div>
            <div className="flex gap-2 flex-wrap">
              <button className={`btn btn-sm ${tool?.kind === 'box' ? 'btn-on' : ''}`} onClick={() => setTool(tool?.kind === 'box' ? null : { kind: 'box' })}
                disabled={!spec.placements.length} title="Begrenzung des Kastens als Linie zeichnen, z. B. ein L vom Rand zur Werkzeugspitze und hoch zum Rand"><Plus size={14} /> Kasten zeichnen</button>
              <button className="btn btn-sm" onClick={() => genComps.mutate()} disabled={genComps.isPending || !spec.placements.length}>
                <SquaresFour size={14} /> Automatisch füllen</button>
            </div>
            <Check label="Kastenwand folgt der Werkzeugkontur" checked={spec.comp_follow} onChange={(v) => patch({ comp_follow: v })} />
            <div className="hint mt-0">Kasten zeichnen: die Begrenzung als Linie ziehen, z. B. ein L vom linken Rand bis zur Werkzeugspitze und hoch zum oberen Rand.
              Der Kasten füllt die Ecke bis an das Werkzeug. Der nächste Kasten daneben bekommt automatisch eine Wand dazwischen.
              Kasten anklicken: löschen (Entf) oder gerade teilen.</div>
            {nGenerated > 0 && <button className="btn btn-sm justify-self-start" onClick={clearComps}><Trash size={14} /> Alle {nGenerated} Kästen entfernen</button>}
            {compAt.isError && <Msg kind="err">{errText(compAt.error)}</Msg>}
            {genComps.isError && <Msg kind="err">{errText(genComps.error)}</Msg>}
            {compMsg && (
              <Msg kind="warn">{compMsg.text}
                <button className="btn btn-sm mt-2" onClick={growGrid}>Einlage um ein Rasterfeld vergrößern</button>
              </Msg>
            )}
          </div>
          <label className="grid gap-1">
            <span className="label mb-0">Kontur glätten <span className="num">{spec.smooth_mm.toFixed(1)} mm</span></span>
            <input type="range" min={0} max={8} step={0.5} value={spec.smooth_mm} onChange={(e) => patch({ smooth_mm: +e.target.value })} />
            <span className="hint mt-0">Glatte, ruhige Taschenkontur: Kerben und Zacken bis zu dieser Größe verschwinden. Die Tasche wird dabei nie kleiner als Werkzeug + Spiel.</span>
          </label>
        </section>

        <section className="grid gap-2">
          <h3 className="sect">Spiel</h3>
          <div className="hint mt-0">Luft zwischen Werkzeug und Taschenwand. Für den Anfang "Normal" wählen und mit dem Passform-Test prüfen.</div>
          <Segmented value={[0.3, 1.0, 2.0].includes(spec.clearance_xy) ? spec.clearance_xy : -1}
            onChange={(v) => v > 0 && patch({ clearance_xy: v })}
            options={[{ value: 0.3, label: 'Presspassung' }, { value: 1.0, label: 'Normal' }, { value: 2.0, label: 'Locker' }, { value: -1, label: 'Frei' }]} />
          <NumberField label="Spiel seitlich" value={spec.clearance_xy} step={0.1} min={0} max={4} onChange={(v) => patch({ clearance_xy: v })} hint="Standard 2,5 mm (Frei)" />
          <NumberField label="Zusatzspiel an den Enden" value={spec.clearance_end} step={0.1} min={0} onChange={(v) => patch({ clearance_end: v })} />
          <NumberField label="Abstand Boden zu Werkzeug" value={spec.clearance_z} step={0.1} min={0} onChange={(v) => patch({ clearance_z: v })} />
        </section>

        <details className="grid gap-2">
          <summary className="sect cursor-pointer">Boden und Wände</summary>
          <div className="grid gap-2 mt-2">
            <div className="hint mt-0">Die Stufen kommen aus den Ebenen im Seitenprofil des Objekts.</div>
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
          {lay && <span className="chip num">{lay.grid_x} x {lay.grid_y} Einheiten · {lay.total_height.toFixed(1)} mm hoch</span>}
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
            <button className="btn btn-sm" onClick={addGrip} disabled={!spec.placements.length || spec.auto_grip} title="Greifmulde automatisch am Schwerpunkt setzen"><Plus size={14} /> Greifmulde</button>
            <button className={`btn btn-sm ${tool?.kind === 'box' ? 'btn-on' : ''}`} onClick={() => setTool(tool?.kind === 'box' ? null : { kind: 'box' })}
              disabled={!spec.placements.length} title="Begrenzung des Kastens als Linie zeichnen, z. B. ein L vom Rand zur Werkzeugspitze und hoch zum Rand"><Plus size={14} /> Kasten zeichnen</button>

            <span className="w-px h-6" style={{ background: 'var(--line)' }} />
            <button className={`btn btn-sm ${spec.auto_center ? 'btn-on' : ''}`} onClick={centerNow} title="Inhalt mittig in die Einlage setzen und dort halten">
              <CrosshairSimple size={14} /> Mittig{spec.auto_center ? ' (aktiv)' : ''}
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
            {compAt.isError && <Msg kind="err">{errText(compAt.error)}</Msg>}
            {compCut.isError && !tool && <Msg kind="err">{errText(compCut.error)}</Msg>}
            <div className="panel p-2 relative">
              {layout.isFetching && <div className="absolute inset-x-2 top-1"><BusyBar /></div>}
              {tool && (
                <div className="absolute left-3 right-3 bottom-3 z-10 pointer-events-none grid gap-2 justify-items-start">
                  <Msg kind="info">{tool.kind === 'box'
                    ? 'Begrenzung des Kastens als Linie zeichnen (z. B. ein L vom Rand zur Werkzeugspitze und hoch zum Rand). Grün = wo der Kasten hinkommt, am Werkzeug endet er mit Wandabstand. Weitere Kästen gleich weiterzeichnen, Esc beendet.'
                    : `In den Kasten klicken: dort wird er ${tool.axis === 'h' ? 'waagrecht' : 'senkrecht'} gerade geteilt. Esc bricht ab.`}</Msg>
                </div>
              )}
              <Editor2D spec={spec} layout={lay} objects={objMap} sel={sel} onSelect={select} onMove={move} selectedComps={compSel}
                tool={tool} onBox={onBox} onCut={onCut}
                onPocketClick={(pi, x, y) => {
                  // Klickpunkt -> Position entlang der Werkzeugachse (objekt-lokal x)
                  const pl = spec.placements[pi]; const [sx0, sy0] = lay?.shift ?? [0, 0]
                  const a = (pl.rot_deg * Math.PI) / 180, dx = x - sx0 - pl.x, dy = y - sy0 - pl.y
                  setPocketPt({ pi, s: dx * Math.cos(a) + dy * Math.sin(a) })
                }} />
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
            {compMsg && (
              <Msg kind="warn">{compMsg.text}
                <button className="btn btn-sm ml-2" onClick={growGrid}>Einlage um ein Rasterfeld vergrößern</button>
              </Msg>
            )}
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
        <SelectionPanel spec={spec} lay={lay} sel={sel} setSpec={setSpec} onSel={select} objMap={objMap} pocketPt={pocketPt}
          onCutTool={(axis) => sel?.kind === 'comp' && setTool({ kind: 'cut', axis, comp: sel.index })} cutAxis={tool?.kind === 'cut' ? tool.axis : null}
          compSel={compSel} onMerge={() => editComps.mutate({ op: 'merge' })} onSplit={(n) => editComps.mutate({ op: 'split', parts: n })}
          compBusy={editComps.isPending} compErr={editComps.isError ? errText(editComps.error) : null}  />

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
        {c.grid_x} x {c.grid_y} Einheiten · {Number(c.bbox?.[2] ?? c.height_u * 7).toFixed(1)} mm hoch · {Math.round(c.volume_mm3 / 1000)} cm³ · ca. {c.weight_g} g PLA
      </div>
      <Msgs items={job.warnings} />
    </div>
  )
}

function SelectionPanel({ spec, lay, sel, setSpec, onSel, objMap, compSel, onMerge, onSplit, compBusy, compErr, pocketPt, onCutTool, cutAxis }: {
  spec: InsertSpec; lay: LayoutOut | undefined; sel: Sel; setSpec: (f: (s: InsertSpec) => InsertSpec) => void; onSel: (s: Sel) => void
  pocketPt: { pi: number; s: number } | null
  onCutTool: (axis: 'h' | 'v') => void; cutAxis: 'h' | 'v' | null
  objMap: Record<string, ObjectSpec>; compSel: number[]; onMerge: () => void; onSplit: (n: number) => void
  compBusy: boolean; compErr: string | null
}) {
  if (!sel) return (
    <div className="grid gap-2">
      <h3 className="sect">Auswahl</h3>
      <div className="hint mt-0">Ein Element im Layout anklicken, um Position, Drehung und Maße genau einzustellen.</div>
    </div>
  )
  if (sel.kind === 'comp' && compSel.length > 1) return (
    <div className="grid gap-2">
      <h3 className="sect">{compSel.length} Kästen ausgewählt</h3>
      <div className="hint mt-0">Nebeneinanderliegende Kästen lassen sich zu einem verbinden; die Wand dazwischen fällt weg.</div>
      <button className="btn btn-sm btn-primary" onClick={onMerge} disabled={compBusy}>Verbinden</button>
      <button className="btn btn-sm" onClick={() => { setSpec((s) => ({ ...s, compartments: s.compartments.filter((_, i) => !compSel.includes(i)) })); onSel(null) }}>
        <Trash size={14} /> Alle {compSel.length} entfernen</button>
      {compErr && <Msg kind="err">{compErr}</Msg>}
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
        {objMap[p.object_id]?.profile?.levels && (
          <LevelTools obj={objMap[p.object_id]} s={pocketPt?.pi === sel.index ? pocketPt.s : null}
            pieces={lay?.pieces.filter((q) => q.placement === sel.index) ?? []} />
        )}
        {del}
      </div>
    )
  }
  if (sel.kind === 'grip') {
    const g = spec.grip_recesses[sel.index]
    if (!g) return null
    const upd = (q: Partial<GripRecess>) => setSpec((s) => ({ ...s, grip_recesses: s.grip_recesses.map((x, i) => (i === sel.index ? { ...x, ...q } : x)) }))
    const pl = g.attach != null ? spec.placements[g.attach] : undefined
    const L = pl ? objMap[pl.object_id]?.length_mm ?? 200 : 0
    // tatsächliche Länge der Mulde (bei automatischer Länge aus dem Layout)
    const lg = lay?.grips.filter((q) => !q.auto)[sel.index]?.polygons[0]
    const curLen = lg && pl ? (() => {
      const a = (pl.rot_deg * Math.PI) / 180, nx = -Math.sin(a), ny = Math.cos(a)
      const t = lg.exterior.map(([x, y]) => x * nx + y * ny)
      return Math.max(...t) - Math.min(...t)
    })() : undefined
    if (pl) return (
      <div className="grid gap-2">
        <h3 className="sect">Greifmulde (am Werkzeug)</h3>
        <div className="hint mt-0">Liegt quer mittig unter dem Werkzeug. Verschieben geht nur entlang der Werkzeugachse.</div>
        <label className="grid gap-1">
          <span className="label mb-0">Position entlang des Werkzeugs <span className="num">{(g.s ?? 0).toFixed(1)} mm</span></span>
          <input type="range" min={0} max={Math.round(L)} step={0.5} value={g.s ?? 0} onChange={(e) => upd({ s: +e.target.value })} />
        </label>
        <div className="grid grid-cols-2 gap-2">
          <NumberField label="Position" value={g.s ?? 0} step={1} min={0} max={L} onChange={(v) => upd({ s: v })} />
          <NumberField label="Breite" value={g.w} step={0.5} min={4} onChange={(v) => upd({ w: v })}
            hint="entlang des Werkzeugs" />
          <NumberField label="Länge" value={Math.round((curLen ?? g.l) * 10) / 10} step={1} min={4} onChange={(v) => upd({ l: v, auto_length: false })}
            hint={g.auto_length !== false ? 'automatisch' : 'quer zum Werkzeug'} />
          <NumberField label="Tiefe unter Tasche" value={g.depth_below} step={1} min={0} onChange={(v) => upd({ depth_below: v })} />
          <NumberField label="Kantenradius" value={g.edge_r ?? 1} step={0.5} min={0} max={15} onChange={(v) => upd({ edge_r: v })} />
        </div>
        <Check label="Länge automatisch (Breite der Tasche + Überstand)" checked={g.auto_length !== false} onChange={(v) => upd({ auto_length: v })} />
        <Check label="Weich ausgeformt (ovaler Boden, runde Kante)" checked={g.rounded !== false} onChange={(v) => upd({ rounded: v })} />
        <button className="btn btn-sm" onClick={() => upd({ attach: null })}>Vom Werkzeug lösen (frei verschieben)</button>
        {del}
      </div>
    )
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
        {g.shape !== 'rect' && <>
          <NumberField label="Kantenradius" value={g.edge_r ?? 1} step={0.5} min={0} max={15} onChange={(v) => upd({ edge_r: v })} />
          <Check label="Weich ausgeformt (ovaler Boden, runde Kante)" checked={g.rounded !== false} onChange={(v) => upd({ rounded: v })} />
        </>}
        {del}
      </div>
    )
  }
  const c = spec.compartments[sel.index]
  if (!c) return null
  const lc = lay?.compartments.filter((q) => !q.auto)[sel.index]
  const maxDepth = lc ? lc.depth : null
  const upd = (q: Partial<Compartment>) => setSpec((s) => ({ ...s, compartments: s.compartments.map((x, i) => (i === sel.index ? { ...x, ...q } : x)) }))
  if (c.polygon) return (
    <div className="grid gap-2">
      <h3 className="sect">Kasten</h3>
      <div className="num hint mt-0">ca. {Math.round(c.w)} x {Math.round(c.l)} mm</div>
      <Check label="So tief wie möglich" checked={c.depth === null} onChange={(v) => upd({ depth: v ? null : Math.round(maxDepth ?? 15) })} />
      {c.depth !== null && <NumberField label="Tiefe" value={c.depth} step={1} min={2} onChange={(v) => upd({ depth: v })} />}
      {c.depth === null && maxDepth !== null && <div className="num hint mt-0">derzeit {maxDepth.toFixed(1)} mm (folgt der Einlagenhöhe)</div>}
      <div className="text-sm font-medium mt-1">Gerade teilen an einer Stelle</div>
      <div className="flex gap-2">
        <button className={`btn btn-sm ${cutAxis === 'h' ? 'btn-on' : ''}`} onClick={() => onCutTool('h')}>Waagrechter Schnitt</button>
        <button className={`btn btn-sm ${cutAxis === 'v' ? 'btn-on' : ''}`} onClick={() => onCutTool('v')}>Senkrechter Schnitt</button>
      </div>
      <div className="text-sm font-medium mt-1">Teilen in gleich große Fächer</div>
      <div className="flex gap-2">
        {[2, 3, 4].map((n) => <button key={n} className="btn btn-sm" onClick={() => onSplit(n)} disabled={compBusy}>{n} Fächer</button>)}
      </div>
      <div className="hint mt-0">Mit Shift-Klick weitere Kästen auswählen, um sie zu verbinden. Entf-Taste löscht.</div>
      {compErr && <Msg kind="err">{compErr}</Msg>}
      {del}
    </div>
  )
  return (
    <div className="grid gap-2">
      <h3 className="sect">Fach</h3>
      <div className="grid grid-cols-2 gap-2">
        <NumberField label="X (links)" value={c.x} step={0.5} onChange={(v) => upd({ x: v })} />
        <NumberField label="Y (unten)" value={c.y} step={0.5} onChange={(v) => upd({ y: v })} />
        <NumberField label="Breite" value={c.w} step={0.5} min={4} onChange={(v) => upd({ w: v })} />
        <NumberField label="Länge" value={c.l} step={0.5} min={4} onChange={(v) => upd({ l: v })} />
        <NumberField label="Eckradius" value={c.radius} step={0.5} min={0} onChange={(v) => upd({ radius: v })} />
        {c.depth !== null && <NumberField label="Tiefe" value={c.depth} step={1} min={2} onChange={(v) => upd({ depth: v })} />}
      </div>
      <Check label="So tief wie möglich" checked={c.depth === null} onChange={(v) => upd({ depth: v ? null : Math.round(maxDepth ?? 15) })} />
      {del}
    </div>
  )
}


/** Taschenboden an der angeklickten Stelle: tiefer/flacher setzen oder dort eine eigene Ebene
 *  anlegen. Ändert die Ebenen des Werkzeugs (gilt in allen Einlagen mit diesem Werkzeug). */
function LevelTools({ obj, s, pieces }: { obj: ObjectSpec; s: number | null; pieces: LayoutOut['pieces'] }) {
  const qc = useQueryClient()
  const levels = obj.profile!.levels!
  const save = useMutation({
    mutationFn: (lv: Level[]) => api.setLevels(obj.id, lv),
    onSuccess: (o) => {
      qc.setQueryData<ObjectSpec[]>(['objects'], (cur) => cur?.map((q) => (q.id === o.id ? o : q)))
      qc.invalidateQueries({ queryKey: ['layout'] })
    },
  })
  if (s === null) return (
    <div className="grid gap-1 mt-2">
      <h3 className="sect">Taschenboden</h3>
      <div className="hint mt-0">In die Tasche klicken, um den Boden an dieser Stelle tiefer oder flacher zu setzen.</div>
    </div>
  )
  const L = levels[levels.length - 1][1]
  const sc = Math.min(Math.max(s, 0), L)
  const i = Math.max(0, levels.findIndex((q) => sc >= q[0] && sc < q[1]) === -1 ? levels.length - 1 : levels.findIndex((q) => sc >= q[0] && sc < q[1]))
  const [a, b, z] = levels[i]
  const depth = pieces.find((q) => q.zone === i)?.depth
  const shift = (d: number) => save.mutate(levels.map((q, j) => (j === i ? [q[0], q[1], Math.round((q[2] - d) * 10) / 10] as Level : q)))
  const own = () => {
    const lo = Math.max(a, sc - 8), hi = Math.min(b, sc + 8)
    const parts: Level[] = []
    if (lo - a >= 3) parts.push([a, lo, z])
    parts.push([lo - a >= 3 ? lo : a, hi > b - 3 ? b : hi, z])
    if (b - hi >= 3) parts.push([hi, b, z])
    save.mutate([...levels.slice(0, i), ...parts, ...levels.slice(i + 1)])
  }
  return (
    <div className="grid gap-2 mt-2">
      <h3 className="sect">Taschenboden an der Klickstelle</h3>
      <div className="num hint mt-0">Ebene {i + 1} von {levels.length}: {a.toFixed(0)} bis {b.toFixed(0)} mm entlang des Werkzeugs
        {depth !== undefined && <>, {depth.toFixed(1)} mm tief</>}</div>
      <div className="flex gap-2 flex-wrap">
        <button className="btn btn-sm" onClick={() => shift(1)} disabled={save.isPending}>1 mm tiefer</button>
        <button className="btn btn-sm" onClick={() => shift(-1)} disabled={save.isPending}>1 mm flacher</button>
      </div>
      <button className="btn btn-sm justify-self-start" onClick={own} disabled={save.isPending || levels.length >= 8 || b - a < 10}
        title="Teilt die Ebene: um die Klickstelle (± 8 mm) entsteht eine eigene Ebene, die du dann tiefer setzen kannst">
        Hier eigene Ebene (± 8 mm)</button>
      <div className="hint mt-0">Liegt das Werkzeug hier tiefer (z. B. Griffschutz), erst eine eigene Ebene anlegen, dann tiefer setzen.
        Gilt für dieses Werkzeug in allen Einlagen.</div>
      {save.isError && <Msg kind="err">{errText(save.error)}</Msg>}
    </div>
  )
}
